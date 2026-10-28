/**
 * `viewmagnet-mcp` CLI entry point.
 *
 * Two subcommands:
 *
 *   serve        Boot the MCP server over stdio. Called by Claude
 *                Desktop / Cursor / Cline; not meant for humans.
 *   install      Write the MCP server entry into one or more
 *                detected agent config files. The on-ramp.
 *
 * Plus a default behaviour when invoked with no args: print help.
 */
import { Command } from "commander";
import { createInterface } from "node:readline/promises";
import pc from "picocolors";

import { loadConfig } from "./config.js";
import { buildServer, SERVER_VERSION } from "./server.js";
import { claudeDesktopInstaller } from "./installers/claudeDesktop.js";
import { clineInstaller } from "./installers/cline.js";
import { cursorInstaller } from "./installers/cursor.js";
import { genericInstaller, renderGenericSnippet } from "./installers/generic.js";
import type { Installer, InstallerInputs } from "./installers/types.js";
import { log } from "./util/log.js";

const ALL_INSTALLERS: Installer[] = [
  claudeDesktopInstaller,
  cursorInstaller,
  clineInstaller,
];

// Local API by default (uvicorn on :8000). Point at a deployed backend with
// VIEWMAGNET_API_URL / VM_API_URL or --api-url.
const DEFAULT_API_URL = "http://localhost:8000";

async function runServe(opts: { apiUrl?: string; token?: string }): Promise<void> {
  // Lazy-load the SDK so the `install` subcommand stays fast even
  // when @modelcontextprotocol/sdk has a slow cold start. (At time
  // of writing it imports ~17 transitive deps.)
  const { StdioServerTransport } = await import(
    "@modelcontextprotocol/sdk/server/stdio.js"
  );

  const config = loadConfig({
    apiUrl: opts.apiUrl,
    patToken: opts.token,
  });

  if (!config.patToken) {
    log.error(
      "No PAT configured. Set VM_PAT_TOKEN, or pass --token, or run `npx viewmagnet-mcp install`.",
    );
    process.exit(1);
  }

  log.info(
    `viewmagnet-mcp v${SERVER_VERSION} serving over stdio (api=${config.apiUrl})`,
  );

  const server = buildServer(config);
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // The transport keeps the process alive while stdin stays open.
  // Closing stdin (parent process exits) drops the connection and
  // ends the process — no extra signal handlers needed.
}

async function promptForToken(): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  try {
    process.stderr.write(
      pc.bold(
        "Paste your ViewMagnet PAT (vm_pat_...). Generate one at " +
          pc.cyan("https://viewmagnet.com/dashboard/api-tokens") +
          ".\n",
      ),
    );
    const answer = (await rl.question(pc.dim("token> "))).trim();
    return answer;
  } finally {
    rl.close();
  }
}

interface InstallOptions {
  token?: string;
  apiUrl?: string;
  targets?: string;
  yes?: boolean;
  print?: boolean;
}

async function runInstall(opts: InstallOptions): Promise<void> {
  const apiUrl = opts.apiUrl ?? process.env.VM_API_URL ?? process.env.VIEWMAGNET_API_URL ?? DEFAULT_API_URL;

  let token = opts.token ?? process.env.VM_PAT_TOKEN ?? "";
  if (!token) {
    token = await promptForToken();
  }
  if (!token.startsWith("vm_pat_")) {
    log.error(
      "That doesn't look like a ViewMagnet PAT (expected `vm_pat_<prefix>_<secret>`).",
    );
    process.exit(1);
  }

  const inputs: InstallerInputs = { patToken: token, apiUrl };

  if (opts.print) {
    process.stdout.write(renderGenericSnippet(inputs) + "\n");
    return;
  }

  const selectedIds = (opts.targets ?? "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

  let targets: Installer[];
  if (selectedIds.length > 0) {
    const byId = new Map([
      ...ALL_INSTALLERS.map((i) => [i.id, i] as const),
      [genericInstaller.id, genericInstaller],
    ]);
    targets = [];
    for (const id of selectedIds) {
      const inst = byId.get(id);
      if (!inst) {
        log.error(
          `Unknown --target "${id}". Known: ${[...byId.keys()].join(", ")}.`,
        );
        process.exit(1);
      }
      targets.push(inst);
    }
  } else {
    targets = ALL_INSTALLERS.filter((i) => i.detect());
    if (targets.length === 0) {
      log.warn(
        "Didn't detect Claude Desktop, Cursor, or Cline. Falling back to generic mode — paste the snippet below into your MCP client's config:",
      );
      process.stdout.write("\n" + renderGenericSnippet(inputs) + "\n");
      return;
    }
  }

  process.stderr.write(
    pc.bold(`\nInstalling viewmagnet MCP server into ${targets.length} target(s):\n`),
  );
  for (const inst of targets) {
    process.stderr.write(`  - ${inst.label}\n`);
  }
  process.stderr.write("\n");

  if (!opts.yes) {
    const rl = createInterface({ input: process.stdin, output: process.stderr });
    try {
      const answer = (await rl.question(pc.dim("Proceed? [Y/n] "))).trim().toLowerCase();
      if (answer === "n" || answer === "no") {
        log.info("Aborted.");
        return;
      }
    } finally {
      rl.close();
    }
  }

  let failures = 0;
  for (const inst of targets) {
    const result = await inst.install(inputs);
    if (result.ok) {
      const label = result.updated ? "updated" : "added";
      process.stderr.write(
        `${pc.green("✓")} ${inst.label}: ${label} ${pc.dim(result.configPath)}\n`,
      );
    } else {
      failures++;
      process.stderr.write(
        `${pc.red("✗")} ${inst.label}: ${result.reason}\n`,
      );
    }
  }

  process.stderr.write(
    "\n" +
      pc.bold("Next step: restart your MCP client") +
      " (close + reopen Claude Desktop / Cursor / Cline) so it loads the new server.\n",
  );

  if (failures > 0) {
    process.exit(1);
  }
}

function buildCli(): Command {
  const program = new Command();
  program
    .name("viewmagnet-mcp")
    .version(SERVER_VERSION)
    .description(
      "MCP server for ViewMagnet — analyze YouTube videos, generate scripts, score hooks, and pull outcomes from any AI agent.",
    );

  program
    .command("serve")
    .description("Run the MCP server over stdio (spawned by Claude/Cursor/Cline; not meant to be run manually).")
    .option("--api-url <url>", "ViewMagnet API base URL", DEFAULT_API_URL)
    .option("--token <pat>", "Personal Access Token (overrides VM_PAT_TOKEN env var)")
    .action(async (opts) => {
      try {
        await runServe(opts);
      } catch (err) {
        log.error(
          "fatal",
          err instanceof Error ? { message: err.message, stack: err.stack } : err,
        );
        process.exit(1);
      }
    });

  program
    .command("install")
    .description("Write the MCP server entry into your AI agent's config (Claude Desktop, Cursor, Cline, or generic).")
    .option("--token <pat>", "Personal Access Token to install. Prompted interactively if omitted.")
    .option("--api-url <url>", "ViewMagnet API base URL", DEFAULT_API_URL)
    .option(
      "--target <ids>",
      "Comma-separated targets: claude,cursor,cline,generic. Default: all detected.",
    )
    .option("--yes", "Skip the confirmation prompt.", false)
    .option("--print", "Just print the JSON snippet to stdout, don't write any file.", false)
    .action(async (opts) => {
      try {
        await runInstall(opts);
      } catch (err) {
        log.error(
          "install failed",
          err instanceof Error ? { message: err.message } : err,
        );
        process.exit(1);
      }
    });

  return program;
}

const program = buildCli();
// Top-level await is fine — this file is ESM and bundles as such.
await program.parseAsync(process.argv);

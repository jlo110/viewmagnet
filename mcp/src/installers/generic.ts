/**
 * "Generic" installer — never touches disk. Prints the JSON snippet
 * the user can paste into ANY MCP-compatible client's config file.
 *
 * Use this as a fallback when none of the named clients are detected,
 * or when the user explicitly asks for it via `--target generic`.
 */
import {
  buildMcpServerEntry,
  type Installer,
  type InstallerInputs,
  type InstallerResult,
} from "./types.js";

export function renderGenericSnippet(inputs: InstallerInputs): string {
  const entry = buildMcpServerEntry(inputs);
  return JSON.stringify(
    {
      mcpServers: {
        viewmagnet: entry,
      },
    },
    null,
    2,
  );
}

export const genericInstaller: Installer = {
  id: "generic",
  label: "Generic (print JSON snippet)",

  detect(): boolean {
    // Always available — it's the fallback.
    return true;
  },

  async install(_inputs: InstallerInputs): Promise<InstallerResult> {
    // The CLI prints the snippet at a higher layer; we just signal
    // "nothing to write, success" so the install loop continues.
    return { ok: true, configPath: "<stdout>", updated: false };
  },
};

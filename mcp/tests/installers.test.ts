/**
 * Installer tests — make sure we merge into existing configs without
 * clobbering unrelated MCP server entries the user already wired up.
 * Uses temp files so we never touch the host's real Claude / Cursor /
 * Cline config.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  backupIfExists,
  mergeMcpServerEntry,
  readJsonFile,
  writeJsonFile,
} from "../src/installers/configIo.js";
import { buildMcpServerEntry } from "../src/installers/types.js";
import { renderGenericSnippet } from "../src/installers/generic.js";

let tmp: string;

beforeEach(() => {
  tmp = mkdtempSync(join(tmpdir(), "vm-mcp-test-"));
});

afterEach(() => {
  rmSync(tmp, { recursive: true, force: true });
});

describe("configIo", () => {
  it("readJsonFile returns {} for a missing file", () => {
    const data = readJsonFile(join(tmp, "nope.json"));
    expect(data).toEqual({});
  });

  it("readJsonFile parses an existing JSON object", () => {
    const path = join(tmp, "config.json");
    writeFileSync(path, JSON.stringify({ foo: "bar", mcpServers: { other: { command: "x" } } }));
    const data = readJsonFile(path);
    expect(data.foo).toBe("bar");
    expect(data.mcpServers?.other).toEqual({ command: "x" });
  });

  it("readJsonFile throws a useful message on malformed JSON", () => {
    const path = join(tmp, "broken.json");
    writeFileSync(path, "{not json");
    expect(() => readJsonFile(path)).toThrow(/Could not parse/);
  });

  it("writeJsonFile creates parent directories", () => {
    const nested = join(tmp, "deep", "nest", "file.json");
    writeJsonFile(nested, { hello: "world" });
    expect(JSON.parse(readFileSync(nested, "utf8"))).toEqual({ hello: "world" });
  });

  it("backupIfExists copies the existing file with a timestamped suffix", () => {
    const path = join(tmp, "config.json");
    writeFileSync(path, "{}");
    const backup = backupIfExists(path);
    expect(backup).toBeTruthy();
    expect(backup!.startsWith(path + ".bak.")).toBe(true);
    expect(readFileSync(backup!, "utf8")).toBe("{}");
  });

  it("backupIfExists returns null for a missing file", () => {
    expect(backupIfExists(join(tmp, "absent.json"))).toBeNull();
  });

  it("mergeMcpServerEntry preserves unrelated keys and other servers", () => {
    const before = {
      mcpServers: {
        other: { command: "other-bin", args: ["x"] },
      },
      somethingElse: { keep: true },
    };
    const entry = buildMcpServerEntry({
      patToken: "vm_pat_a_" + "b".repeat(32),
      apiUrl: "https://api.example.com",
    });
    const { data, existed } = mergeMcpServerEntry(before, "viewmagnet", entry);

    expect(existed).toBe(false);
    expect(data.somethingElse).toEqual({ keep: true });
    expect(data.mcpServers?.other).toEqual({ command: "other-bin", args: ["x"] });
    expect(data.mcpServers?.viewmagnet?.command).toBe("npx");
    expect(data.mcpServers?.viewmagnet?.env?.VM_API_URL).toBe(
      "https://api.example.com",
    );
  });

  it("mergeMcpServerEntry reports existed=true when overwriting an existing entry", () => {
    const before = {
      mcpServers: {
        viewmagnet: { command: "old", args: [] },
      },
    };
    const entry = buildMcpServerEntry({
      patToken: "vm_pat_a_" + "b".repeat(32),
      apiUrl: "https://api.example.com",
    });
    const { data, existed } = mergeMcpServerEntry(before, "viewmagnet", entry);
    expect(existed).toBe(true);
    expect(data.mcpServers?.viewmagnet?.command).toBe("npx");
  });
});

describe("generic snippet", () => {
  it("renders the full mcpServers wrapping", () => {
    const snippet = renderGenericSnippet({
      patToken: "vm_pat_xyz_" + "a".repeat(32),
      apiUrl: "https://api.example.com",
    });
    const parsed = JSON.parse(snippet);
    expect(parsed.mcpServers.viewmagnet).toEqual({
      command: "npx",
      args: ["-y", "viewmagnet-mcp", "serve"],
      env: {
        VM_API_URL: "https://api.example.com",
        VM_PAT_TOKEN: "vm_pat_xyz_" + "a".repeat(32),
      },
    });
  });
});

describe("end-to-end merge through a real installer-style flow", () => {
  it("first install adds the entry; second install overwrites cleanly", () => {
    const path = join(tmp, "fake_claude.json");

    // Simulate a config file the user already has with another MCP
    // server in it — most users will have at least filesystem or
    // brave-search wired up.
    mkdirSync(tmp, { recursive: true });
    writeFileSync(
      path,
      JSON.stringify({
        mcpServers: {
          filesystem: {
            command: "npx",
            args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/x"],
          },
        },
      }),
    );

    const inputs = {
      patToken: "vm_pat_first_" + "a".repeat(32),
      apiUrl: "https://api.viewmagnet.com",
    };

    let parsed = readJsonFile(path);
    let merged = mergeMcpServerEntry(parsed, "viewmagnet", buildMcpServerEntry(inputs));
    writeJsonFile(path, merged.data);

    let onDisk = JSON.parse(readFileSync(path, "utf8"));
    expect(onDisk.mcpServers.filesystem).toBeTruthy();
    expect(onDisk.mcpServers.viewmagnet.env.VM_PAT_TOKEN).toBe(inputs.patToken);

    // Re-install with a new token; the filesystem entry must survive
    // and the viewmagnet entry must update in place.
    parsed = readJsonFile(path);
    const inputs2 = {
      patToken: "vm_pat_second_" + "b".repeat(32),
      apiUrl: "https://api.viewmagnet.com",
    };
    merged = mergeMcpServerEntry(parsed, "viewmagnet", buildMcpServerEntry(inputs2));
    expect(merged.existed).toBe(true);
    writeJsonFile(path, merged.data);

    onDisk = JSON.parse(readFileSync(path, "utf8"));
    expect(onDisk.mcpServers.filesystem).toBeTruthy();
    expect(onDisk.mcpServers.viewmagnet.env.VM_PAT_TOKEN).toBe(inputs2.patToken);
  });
});

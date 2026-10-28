/**
 * Cursor installer.
 *
 * Cursor reads MCP server config from `~/.cursor/mcp.json`. The schema
 * is identical to Claude Desktop's (top-level `mcpServers` object),
 * which makes the merge trivial.
 *
 * Detection is "the ~/.cursor directory exists", which is true for
 * anyone who has launched Cursor at least once.
 */
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import {
  backupIfExists,
  mergeMcpServerEntry,
  readJsonFile,
  writeJsonFile,
} from "./configIo.js";
import {
  buildMcpServerEntry,
  type Installer,
  type InstallerInputs,
  type InstallerResult,
} from "./types.js";

function cursorDir(): string {
  return join(homedir(), ".cursor");
}

function cursorConfigPath(): string {
  return join(cursorDir(), "mcp.json");
}

export const cursorInstaller: Installer = {
  id: "cursor",
  label: "Cursor",

  detect(): boolean {
    return existsSync(cursorDir());
  },

  async install(inputs: InstallerInputs): Promise<InstallerResult> {
    const configPath = cursorConfigPath();
    try {
      backupIfExists(configPath);
      const parsed = readJsonFile(configPath);
      const { data, existed } = mergeMcpServerEntry(
        parsed,
        "viewmagnet",
        buildMcpServerEntry(inputs),
      );
      writeJsonFile(configPath, data);
      return { ok: true, configPath, updated: existed };
    } catch (err) {
      return {
        ok: false,
        reason: err instanceof Error ? err.message : String(err),
        configPath,
      };
    }
  },
};

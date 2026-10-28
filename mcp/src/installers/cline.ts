/**
 * Cline installer (VS Code / Cursor / Windsurf extension).
 *
 * Cline keeps its MCP server entries in a JSON file under the
 * extension's globalStorage path:
 *   macOS:   ~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
 *   Linux:   ~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
 *   Windows: %APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
 *
 * The schema mirrors Claude Desktop's. Detection looks for the
 * extension's globalStorage folder, which exists only after Cline has
 * been installed via the VS Code Marketplace.
 */
import { existsSync } from "node:fs";
import { homedir, platform } from "node:os";
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

const CLINE_EXT_ID = "saoudrizwan.claude-dev";

function vscodeUserDir(): string | null {
  const home = homedir();
  switch (platform()) {
    case "darwin":
      return join(home, "Library", "Application Support", "Code", "User");
    case "win32": {
      const appData = process.env.APPDATA;
      if (!appData) return null;
      return join(appData, "Code", "User");
    }
    case "linux":
      return join(home, ".config", "Code", "User");
    default:
      return null;
  }
}

function clineSettingsDir(): string | null {
  const userDir = vscodeUserDir();
  return userDir
    ? join(userDir, "globalStorage", CLINE_EXT_ID, "settings")
    : null;
}

function clineConfigPath(): string | null {
  const dir = clineSettingsDir();
  return dir ? join(dir, "cline_mcp_settings.json") : null;
}

export const clineInstaller: Installer = {
  id: "cline",
  label: "Cline (VS Code)",

  detect(): boolean {
    const dir = clineSettingsDir();
    return !!dir && existsSync(dir);
  },

  async install(inputs: InstallerInputs): Promise<InstallerResult> {
    const configPath = clineConfigPath();
    if (!configPath) {
      return {
        ok: false,
        reason: `Unsupported OS (${platform()}).`,
        configPath: null,
      };
    }
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

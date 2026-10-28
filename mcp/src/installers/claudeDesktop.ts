/**
 * Claude Desktop installer.
 *
 * Config location is OS-specific (Anthropic hasn't standardized it
 * yet):
 *   macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
 *   Windows: %APPDATA%/Claude/claude_desktop_config.json
 *   Linux:   ~/.config/Claude/claude_desktop_config.json
 *
 * The file might not exist if the user has never added an MCP server;
 * we create it. Detection treats "directory exists" as "Claude
 * Desktop is installed" — opening the app once creates that folder
 * even if the config file is still absent.
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

function claudeDesktopConfigDir(): string | null {
  const home = homedir();
  switch (platform()) {
    case "darwin":
      return join(home, "Library", "Application Support", "Claude");
    case "win32": {
      const appData = process.env.APPDATA;
      if (!appData) return null;
      return join(appData, "Claude");
    }
    case "linux":
      return join(home, ".config", "Claude");
    default:
      return null;
  }
}

function claudeDesktopConfigPath(): string | null {
  const dir = claudeDesktopConfigDir();
  return dir ? join(dir, "claude_desktop_config.json") : null;
}

export const claudeDesktopInstaller: Installer = {
  id: "claude",
  label: "Claude Desktop",

  detect(): boolean {
    const dir = claudeDesktopConfigDir();
    return !!dir && existsSync(dir);
  },

  async install(inputs: InstallerInputs): Promise<InstallerResult> {
    const configPath = claudeDesktopConfigPath();
    if (!configPath) {
      return {
        ok: false,
        reason: `Unsupported OS (${platform()}). Use --target generic to print the JSON snippet manually.`,
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

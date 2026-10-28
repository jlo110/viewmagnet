/**
 * Filesystem helpers shared by the installers.
 *
 * Every installer follows the same pattern: read existing JSON (if
 * any), shallow-merge the `mcpServers.viewmagnet` entry, write back
 * with a `.bak.<timestamp>` backup beside the original. Those steps
 * live here so the installer modules can stay declarative.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync, statSync, copyFileSync } from "node:fs";
import { dirname } from "node:path";

export interface McpServersFile {
  mcpServers?: Record<
    string,
    {
      command: string;
      args?: string[];
      env?: Record<string, string>;
    }
  >;
  // Preserve anything else the user has in the file — we never own
  // the whole file, just our key under `mcpServers`.
  [key: string]: unknown;
}

export function readJsonFile(path: string): McpServersFile {
  if (!existsSync(path)) return {};
  try {
    const txt = readFileSync(path, "utf8");
    if (!txt.trim()) return {};
    const parsed = JSON.parse(txt) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as McpServersFile;
    }
    return {};
  } catch (err) {
    throw new Error(
      `Could not parse ${path} as JSON: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

/** Backup the file at `path` (no-op if it doesn't exist). Returns
 * the backup path or null. Used before any destructive write so the
 * user can recover if our merge corrupts their config. */
export function backupIfExists(path: string): string | null {
  if (!existsSync(path)) return null;
  try {
    const stat = statSync(path);
    if (!stat.isFile()) return null;
  } catch {
    return null;
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backup = `${path}.bak.${stamp}`;
  copyFileSync(path, backup);
  return backup;
}

export function writeJsonFile(path: string, data: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n", "utf8");
}

/** Merge a new `viewmagnet` MCP server entry into a parsed config
 * object. Returns the mutated object + whether the key was already
 * present (so callers can report "added" vs "updated"). */
export function mergeMcpServerEntry(
  data: McpServersFile,
  serverName: string,
  entry: { command: string; args: string[]; env: Record<string, string> },
): { data: McpServersFile; existed: boolean } {
  const next = { ...data };
  const mcp = { ...(next.mcpServers ?? {}) };
  const existed = serverName in mcp;
  mcp[serverName] = entry;
  next.mcpServers = mcp;
  return { data: next, existed };
}

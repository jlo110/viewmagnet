/**
 * Shared types for MCP-server installers.
 *
 * An installer is a small adapter that knows where a specific agent
 * keeps its MCP server config and how to merge a `viewmagnet` entry
 * into it without clobbering whatever else the user has already wired
 * up. Each implementation gets the same shape so the CLI can iterate
 * them uniformly.
 */
export interface InstallerInputs {
  /** Plaintext PAT from `vm_pat_...`. */
  patToken: string;
  /** API base URL — defaults to http://localhost:8000. */
  apiUrl: string;
}

export type InstallerResult =
  | {
      ok: true;
      /** Resolved absolute path of the config file we wrote. */
      configPath: string;
      /** True when the entry was already present and we updated it,
       * false when we added it for the first time. */
      updated: boolean;
    }
  | {
      ok: false;
      /** Human-readable failure reason (e.g. "config not found"). */
      reason: string;
      /** Where we looked for the config file. */
      configPath: string | null;
    };

export interface Installer {
  /** Lowercase ID, used by the CLI for `--targets cursor,claude`. */
  id: string;
  /** Display name for status output. */
  label: string;
  /** Detect whether this agent appears to be installed on the host. */
  detect(): boolean;
  /** Actually perform the install. Returns a result describing the
   * outcome rather than throwing — the CLI batches several installers
   * and one missing target shouldn't take down the others. */
  install(inputs: InstallerInputs): Promise<InstallerResult>;
}

/** The MCP server entry every installer writes. All three target
 * config formats accept the same shape — the only thing that differs
 * is the surrounding JSON. */
export function buildMcpServerEntry(inputs: InstallerInputs): {
  command: string;
  args: string[];
  env: Record<string, string>;
} {
  return {
    command: "npx",
    // `-y` auto-accepts the npx prompt so the agent can spawn us
    // headlessly; the package name pins the implementation users
    // installed at install time, while npx still updates to the
    // latest patch within that major on next run.
    args: ["-y", "viewmagnet-mcp", "serve"],
    env: {
      VM_API_URL: inputs.apiUrl,
      VM_PAT_TOKEN: inputs.patToken,
    },
  };
}

/**
 * Logging helper for the MCP server.
 *
 * IMPORTANT: stdio MCP transport uses stdout for the JSON-RPC stream,
 * so anything we want to "log" MUST go to stderr — writing to stdout
 * here would corrupt the protocol and the client would disconnect.
 */
import pc from "picocolors";

const isVerbose = process.env.VM_MCP_VERBOSE === "1";

function ts(): string {
  return new Date().toISOString().slice(11, 23);
}

export const log = {
  info(msg: string, extra?: unknown): void {
    process.stderr.write(`${pc.dim(ts())} ${pc.cyan("info")} ${msg}`);
    if (extra !== undefined) {
      process.stderr.write(" " + safeStringify(extra));
    }
    process.stderr.write("\n");
  },
  warn(msg: string, extra?: unknown): void {
    process.stderr.write(`${pc.dim(ts())} ${pc.yellow("warn")} ${msg}`);
    if (extra !== undefined) {
      process.stderr.write(" " + safeStringify(extra));
    }
    process.stderr.write("\n");
  },
  error(msg: string, extra?: unknown): void {
    process.stderr.write(`${pc.dim(ts())} ${pc.red("error")} ${msg}`);
    if (extra !== undefined) {
      process.stderr.write(" " + safeStringify(extra));
    }
    process.stderr.write("\n");
  },
  debug(msg: string, extra?: unknown): void {
    if (!isVerbose) return;
    process.stderr.write(`${pc.dim(ts())} ${pc.dim("debug")} ${msg}`);
    if (extra !== undefined) {
      process.stderr.write(" " + safeStringify(extra));
    }
    process.stderr.write("\n");
  },
};

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

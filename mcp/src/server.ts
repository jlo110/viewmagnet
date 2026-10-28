/**
 * Construct and wire the ViewMagnet MCP server.
 *
 * One process == one McpServer == 10 tools, all routed through a
 * single authenticated HTTP client. The transport is created by the
 * caller (cli.ts uses stdio) so this module stays unit-testable.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

import { ViewMagnetClient } from "./client.js";
import type { RuntimeConfig } from "./config.js";
import { registerAnalyzePacing } from "./tools/analyzePacing.js";
import { registerAnalyzeVideo } from "./tools/analyzeVideo.js";
import { registerDetectHighlights } from "./tools/detectHighlights.js";
import { registerGenerateScript } from "./tools/generateScript.js";
import { registerGenerateTitles } from "./tools/generateTitles.js";
import { registerGetOutcomes } from "./tools/getOutcomes.js";
import { registerListFrameworks } from "./tools/listFrameworks.js";
import { registerListHookTypes } from "./tools/listHookTypes.js";
import { registerScoreHook } from "./tools/scoreHook.js";
import { registerScoreTitle } from "./tools/scoreTitle.js";

/** Server metadata exposed to MCP clients during initialize handshake. */
export const SERVER_NAME = "viewmagnet";
export const SERVER_VERSION = "0.1.0";

/** Build the McpServer with all 10 tools registered. The caller is
 * responsible for connecting a transport. */
export function buildServer(config: RuntimeConfig): McpServer {
  const server = new McpServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
  });

  const client = new ViewMagnetClient(config);
  const deps = { client };

  // Order here matters only for human-readable tool listings — the SDK
  // doesn't impose any ordering on the agent's tool selection. We group
  // discovery tools first, then content generation, then analysis, then
  // outcomes — roughly the order a creator would touch them in.
  registerListFrameworks(server, deps);
  registerListHookTypes(server, deps);
  registerGenerateScript(server, deps);
  registerGenerateTitles(server, deps);
  registerScoreHook(server, deps);
  registerScoreTitle(server, deps);
  registerAnalyzeVideo(server, deps);
  registerAnalyzePacing(server, deps);
  registerDetectHighlights(server, deps);
  registerGetOutcomes(server, deps);

  return server;
}

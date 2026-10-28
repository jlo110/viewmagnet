import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "List ViewMagnet's 4 viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet)",
  "with their primary goals, section structure, and example use cases.",
  "",
  "Use this BEFORE calling viewmagnet_generate_script so you know which `framework` value to pass.",
  "Also useful when the user asks 'what frameworks does ViewMagnet support?' or 'which framework should I use for X?'.",
].join(" ");

export function registerListFrameworks(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool("viewmagnet_list_frameworks", DESCRIPTION, {}, async () => {
    const data = await deps.client.get("/scripts/frameworks");
    return asJsonText(data);
  });
}

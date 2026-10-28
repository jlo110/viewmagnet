import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "List ViewMagnet's 6 hook archetypes (Summary, Mistake Callout, Belief Destruction,",
  "Authority Anchor, Stake Reversal, Specificity) with definitions and short examples.",
  "",
  "Use this when the user asks 'what hook types exist?', 'what should my hook be?',",
  "or before writing a hook so the agent can pick the archetype that best fits the topic.",
].join(" ");

export function registerListHookTypes(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool("viewmagnet_list_hook_types", DESCRIPTION, {}, async () => {
    const data = await deps.client.get("/hooks/types");
    return asJsonText(data);
  });
}

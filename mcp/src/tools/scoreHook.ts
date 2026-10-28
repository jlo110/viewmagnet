import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Score a video hook (the first 3-7 seconds of dialogue) on belief challenge, mistake callout,",
  "urgency, and specificity — the four dimensions that predict whether viewers will keep watching.",
  "Returns an overall 0-100 score, detected hook type, the weakest and strongest dimensions,",
  "and a plain-language rationale.",
  "",
  "Use this when the user pastes a hook line and asks 'is this hook good?',",
  "'rate my opener', or 'why is my retention dropping in the first 10 seconds?'.",
].join(" ");

const inputSchema = {
  hook: z
    .string()
    .min(5)
    .max(500)
    .describe(
      "The literal first 1-3 sentences of the video, exactly as spoken or written on screen.",
    ),
};

export function registerScoreHook(server: McpServer, deps: ToolDeps): void {
  server.tool(
    "viewmagnet_score_hook",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.post("/hooks/score", { hook: input.hook });
      return asJsonText(data);
    },
  );
}

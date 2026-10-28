import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Pull the user's published-video performance dataset from ViewMagnet's post-publish analytics loop.",
  "Returns recent outcomes (per platform: posted URL, published_at, snapshot timeseries, latest stats)",
  "AND the rolled-up `recommendation_effectiveness` data — i.e. 'videos that followed the Lead Magnet",
  "framework averaged +Y% engagement vs videos that didn't'. This is how the agent answers",
  "'is my advice actually working?'.",
  "",
  "Use this when the user asks 'how are my recent videos doing?',",
  "'which framework actually performs best for me?',",
  "or 'show me the impact of following ViewMagnet's recommendations'.",
].join(" ");

const inputSchema = {
  limit: z
    .number()
    .int()
    .min(1)
    .max(200)
    .optional()
    .describe("Number of recent outcomes to fetch (default 50)."),
};

export function registerGetOutcomes(server: McpServer, deps: ToolDeps): void {
  server.tool(
    "viewmagnet_get_outcomes",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.get("/distribution/outcomes", {
        limit: input.limit ?? 50,
      });
      return asJsonText(data);
    },
  );
}

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Generate N optimized YouTube title variations for a given topic + niche.",
  "Each suggestion comes with a predicted score and a brief reason explaining why it should perform.",
  "",
  "Use this when the user asks 'give me title ideas for X', 'I need 5 click-worthy titles',",
  "or 'A/B test some titles for my next video'. Pair with viewmagnet_score_title to compare with an existing draft.",
].join(" ");

const inputSchema = {
  topic: z
    .string()
    .min(3)
    .max(300)
    .describe("Plain-language topic of the video."),
  niche: z
    .string()
    .max(50)
    .describe(
      "Niche/category for context — e.g. 'technology', 'gaming', 'fitness', 'finance'.",
    ),
  style: z
    .string()
    .optional()
    .describe(
      "Optional tonal hint — 'casual', 'authoritative', 'controversial', 'educational'.",
    ),
  count: z
    .number()
    .int()
    .min(1)
    .max(15)
    .optional()
    .describe("How many title variations to generate (default 5)."),
};

export function registerGenerateTitles(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool(
    "viewmagnet_generate_titles",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.post("/titles/generate", {
        topic: input.topic,
        niche: input.niche,
        style: input.style,
        count: input.count ?? 5,
      });
      return asJsonText(data);
    },
  );
}

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Score a YouTube video title on click-through-rate predictors: curiosity gap, specificity,",
  "loss-aversion framing, length, and uppercase ratio. Returns an overall 0-100 score plus",
  "per-feature breakdown and concrete improvement recommendations.",
  "",
  "Use this when the user pastes a title and asks 'will this get clicks?', 'rate this title',",
  "or 'how do I make this title better?'. Pair with viewmagnet_generate_titles to A/B several options.",
].join(" ");

const inputSchema = {
  title: z
    .string()
    .min(3)
    .max(300)
    .describe("The exact title text as it would appear on YouTube."),
  niche: z
    .string()
    .max(50)
    .optional()
    .describe(
      "Optional niche/category (e.g. 'technology', 'gaming', 'fitness'). Improves scoring fidelity. Defaults to 'general'.",
    ),
};

export function registerScoreTitle(server: McpServer, deps: ToolDeps): void {
  server.tool(
    "viewmagnet_score_title",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      // /titles/score uses query params, not a JSON body.
      const data = await deps.client.post(
        `/titles/score?title=${encodeURIComponent(input.title)}` +
          `&niche=${encodeURIComponent(input.niche ?? "general")}`,
      );
      return asJsonText(data);
    },
  );
}

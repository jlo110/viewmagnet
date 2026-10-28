import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Predict whether a YouTube video will perform well, before the user uploads it (works on already-published videos too).",
  "Returns a 0-100 prediction score, prediction tier (e.g. 'Viral', 'Mid-tier', 'Underperform'), niche comparison,",
  "separate Title / Thumbnail / Channel scores, and the algorithm-signal bottleneck",
  "(Start / Keep / Repeat) with concrete rewrite recommendations.",
  "",
  "Use this when the user pastes a YouTube URL and asks 'will this do well?',",
  "'why isn't this working?', 'how do I make this video better?',",
  "or 'should I publish this?'. Also useful for competitive analysis — point it at a competitor's video.",
].join(" ");

const inputSchema = {
  url: z
    .string()
    .url()
    .describe("Full YouTube watch URL (e.g. https://www.youtube.com/watch?v=...)"),
  channel_id: z
    .string()
    .optional()
    .describe(
      "Optional UC... channel ID. Provide it to score the video against the channel's own history; omit to score against the niche.",
    ),
};

export function registerAnalyzeVideo(server: McpServer, deps: ToolDeps): void {
  server.tool(
    "viewmagnet_analyze_video",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.post("/analyze", {
        url: input.url,
        channel_id: input.channel_id,
      });
      return asJsonText(data);
    },
  );
}

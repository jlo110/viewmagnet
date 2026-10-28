import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Analyze a video's pacing — scene cuts, dead-air segments, and over-long monologue stretches.",
  "Returns a pacing grade, average cut interval, the longest dead-air windows with timestamps,",
  "and concrete recommendations (e.g. 'add a cut around 2:14 — dead air for 7s').",
  "",
  "Use this when the user asks 'why does this video feel slow?', 'where should I cut?',",
  "or 'is my pacing too aggressive?'. Particularly useful for talking-head and tutorial videos.",
].join(" ");

const inputSchema = {
  video_url: z
    .string()
    .url()
    .describe("Full YouTube URL or direct video file URL."),
};

export function registerAnalyzePacing(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool(
    "viewmagnet_analyze_pacing",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.post("/pacing/analyze", {
        video_url: input.video_url,
      });
      return asJsonText(data);
    },
  );
}

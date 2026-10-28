import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Find the best clip-worthy moments inside a long-form video and return them ranked by virality.",
  "Each highlight has start/end timestamps, a hook score, the matched hook type, suggested clip title,",
  "and the transcript snippet that triggered the match. The best overall moment is highlighted separately.",
  "",
  "Pass either `video_url` (YouTube or direct media) OR raw `transcript` text — at least one is required.",
  "Use this when the user asks 'find the best clips from this video', 'what should I cut for a short?',",
  "or 'pull 5 viral moments from this podcast'.",
].join(" ");

const inputSchema = {
  video_url: z
    .string()
    .url()
    .optional()
    .describe(
      "Full video URL. ViewMagnet will fetch + transcribe it. Omit if you pass `transcript` instead.",
    ),
  transcript: z
    .string()
    .optional()
    .describe(
      "Raw transcript with implicit or explicit timestamps. Use when you already have one (skips transcription cost).",
    ),
  max_highlights: z
    .number()
    .int()
    .min(1)
    .max(20)
    .optional()
    .describe("How many highlights to return (default 5)."),
};

export function registerDetectHighlights(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool(
    "viewmagnet_detect_highlights",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      if (!input.video_url && !input.transcript) {
        throw new Error(
          "Pass either `video_url` or `transcript` — at least one is required.",
        );
      }
      const data = await deps.client.post("/shorts/detect-highlights", {
        video_url: input.video_url,
        transcript: input.transcript,
        max_highlights: input.max_highlights ?? 5,
      });
      return asJsonText(data);
    },
  );
}

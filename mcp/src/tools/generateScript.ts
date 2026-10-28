import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ToolDeps } from "./_helpers.js";
import { asJsonText } from "./_helpers.js";

const DESCRIPTION = [
  "Generate a full long-form YouTube script using one of ViewMagnet's viral frameworks.",
  "Returns the framework metadata, estimated duration, word count, and section-by-section content",
  "(hook, payoff, body sections, cta) plus the assembled `full_script`.",
  "",
  "If you don't know which framework to use, call viewmagnet_list_frameworks first.",
  "Use this when the user asks 'write me a script about X', 'turn this idea into a video',",
  "or 'give me a Lead Magnet script for X topic'.",
].join(" ");

const inputSchema = {
  topic: z
    .string()
    .min(3)
    .describe(
      "Plain-language topic of the video, e.g. 'why most diets fail in week 3'.",
    ),
  framework: z
    .enum(["authority_myth_buster", "delta_shift", "progressive_debunking", "hype_heit"])
    .describe(
      "Framework slug. Get exact slugs from viewmagnet_list_frameworks. Note: `hype_heit` is the internal slug for the Lead Magnet framework.",
    ),
  target_duration: z
    .number()
    .int()
    .min(15)
    .max(1800)
    .optional()
    .describe(
      "Target video duration in seconds (default 60). 60-180s for shorts, 480-900s for tutorials, 1200+ for long-form.",
    ),
  additional_context: z
    .string()
    .optional()
    .describe(
      "Optional extra context for the LLM — target audience, brand voice, specific examples to weave in, etc.",
    ),
};

export function registerGenerateScript(
  server: McpServer,
  deps: ToolDeps,
): void {
  server.tool(
    "viewmagnet_generate_script",
    DESCRIPTION,
    inputSchema,
    async (input) => {
      const data = await deps.client.post("/scripts/generate-framework", {
        topic: input.topic,
        framework: input.framework,
        target_duration: input.target_duration ?? 60,
        additional_context: input.additional_context,
      });
      return asJsonText(data);
    },
  );
}

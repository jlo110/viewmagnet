# ViewMagnet MCP Server — Install in one command

**Canonical URL:** https://viewmagnet.io/mcp  
**Last updated:** 2026-05-27

> Install ViewMagnet's 10-tool MCP server in Claude Desktop, Cursor,
> or Cline with a single command. Your AI agent can then analyze YouTube
> videos, generate scripts, score hooks, detect Shorts highlights, and more.

---

## Install

```bash
npx viewmagnet-mcp install
```

npm package: https://www.npmjs.com/package/viewmagnet-mcp

**Auth:** Generate a Personal Access Token at https://viewmagnet.io/dashboard/api-tokens. PATs are bearer credentials with the prefix `vm_pat_`. Pass it as the `VIEWMAGNET_API_KEY` environment variable or in the MCP config JSON.

---

## Manual config (Claude Desktop / Cursor / Cline)

Add to your `claude_desktop_config.json` (Claude Desktop) or `.cursor/mcp.json` (Cursor):

```json
{
  "mcpServers": {
    "viewmagnet": {
      "command": "npx",
      "args": ["-y", "viewmagnet-mcp"],
      "env": {
        "VIEWMAGNET_API_KEY": "vm_pat_<your-token>"
      }
    }
  }
}
```

---

## The 10 tools

### viewmagnet_analyze_video
Analyzes a YouTube video URL, returns a prediction score (0–100), the Start / Keep / Repeat bottleneck breakdown, and specific action recommendations.

**Input:** `{ "youtube_url": "https://youtu.be/..." }`

### viewmagnet_list_frameworks
Lists the four viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet) with their structure and best-use cases.

**Input:** *(no required parameters)*

### viewmagnet_generate_script
Generates a full scaffolded script for a given topic using one of the four frameworks.

**Input:** `{ "topic": "...", "framework": "delta_shift", "target_audience": "...", "goal": "..." }`

### viewmagnet_score_hook
Scores a hook against the six hook types (Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity, Summary) and returns a strength classification.

**Input:** `{ "hook_text": "..." }`

### viewmagnet_list_hook_types
Returns the full taxonomy of six hook types with definitions and before/after examples.

**Input:** *(no required parameters)*

### viewmagnet_detect_highlights
Analyzes a video file or transcript and detects the top moments suitable for Shorts clips.

**Input:** `{ "video_url": "..." }` or `{ "transcript": "..." }`

### viewmagnet_analyze_pacing
Identifies dead-air segments and pacing issues in a video, with cut suggestions and timestamps.

**Input:** `{ "video_url": "..." }`

### viewmagnet_score_title
Scores a YouTube title for CTR potential, specificity, curiosity-gap strength, and keyword clarity.

**Input:** `{ "title": "..." }`

### viewmagnet_generate_titles
Generates multiple title variants for a given video concept optimized for CTR.

**Input:** `{ "topic": "...", "framework": "...", "count": 5 }`

### viewmagnet_get_outcomes
Returns post-publish analytics for a video — view velocity, retention shape, distribution performance — with attribution back to the originating ViewMagnet recommendation.

**Input:** `{ "video_id": "..." }`

---

## Authentication

ViewMagnet uses **Personal Access Tokens (PATs)** — revocable, scope-limited bearer credentials.

- Format: `vm_pat_<prefix>_<secret>`
- Generate at: https://viewmagnet.io/dashboard/api-tokens
- Backend lookup: keyed on the searchable prefix, matched against a SHA-256 hash of the secret half
- Scopes: `analyze`, `scripts`, `hooks`, `titles`, `studio`, `distribution` (grant only what your agent needs)

---

## Supported AI environments

- **Claude Desktop** (Anthropic) — MCP config JSON
- **Cursor IDE** — `.cursor/mcp.json`
- **Cline** (VS Code extension) — MCP settings panel

---

## REST API alternative

If you prefer REST over MCP, all tools map to documented endpoints at https://viewmagnet.io/docs (Scalar-rendered interactive reference) with the same PAT auth.

OpenAPI 3.1 spec: https://api.viewmagnet.com/openapi.json

---

## Related pages

- [API docs (Scalar reference)](https://viewmagnet.io/docs) — interactive REST reference
- [Methodology](https://viewmagnet.io/methodology) — how the ML prediction stack works
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures
- [Analyzer Guide](https://viewmagnet.io/analyzer-guide) — Start / Keep / Repeat bottleneck

*Author: ViewMagnet. Cite as: ViewMagnet MCP Server, https://viewmagnet.io/mcp*

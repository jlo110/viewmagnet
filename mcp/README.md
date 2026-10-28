# viewmagnet-mcp

[![npm version](https://img.shields.io/npm/v/viewmagnet-mcp.svg)](https://www.npmjs.com/package/viewmagnet-mcp)

A [Model Context Protocol](https://modelcontextprotocol.io) server that puts the full ViewMagnet toolkit (YouTube video analysis, viral script generation, hook scoring, post-publish outcomes) inside any MCP-compatible agent — Claude Desktop, Cursor, Cline, or anything that speaks the protocol.

## What you get

Once installed, your agent can call these 10 tools on your behalf:

| Tool | What it does |
| --- | --- |
| `viewmagnet_analyze_video` | Predict 0–100 score, tier, niche comparison, and bottleneck (Start / Keep / Repeat) for any YouTube URL. |
| `viewmagnet_list_frameworks` | List the 4 viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet). |
| `viewmagnet_generate_script` | Generate a full long-form script using one of the frameworks. |
| `viewmagnet_score_hook` | Score a hook on belief challenge, mistake callout, urgency, specificity. |
| `viewmagnet_list_hook_types` | List the 6 hook archetypes with definitions and examples. |
| `viewmagnet_detect_highlights` | Find the most clip-worthy moments in a long video. |
| `viewmagnet_analyze_pacing` | Get a pacing grade and concrete "cut here" recommendations. |
| `viewmagnet_score_title` | CTR-focused title scoring with per-feature breakdown. |
| `viewmagnet_generate_titles` | Generate N optimized title variations for a topic. |
| `viewmagnet_get_outcomes` | Pull recent published-video performance + per-recommendation effectiveness rollups. |

## Install in one command

```bash
npx viewmagnet-mcp install
```

The installer:

1. Detects which AI agents you have installed (Claude Desktop, Cursor, Cline).
2. Prompts you for a Personal Access Token (PAT). Generate one at [viewmagnet.com/dashboard/api-tokens](https://viewmagnet.com/dashboard/api-tokens) if you don't have one yet.
3. Writes the MCP server entry into the matching config file(s), keeping any existing entries you have for other MCP servers untouched.
4. Tells you to restart your agent.

## Manual install

If `install` can't detect your agent, or you prefer to wire it up by hand, drop this snippet into your client's MCP config (Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`, Cursor: `~/.cursor/mcp.json`, Cline: VS Code globalStorage):

```json
{
  "mcpServers": {
    "viewmagnet": {
      "command": "npx",
      "args": ["-y", "viewmagnet-mcp", "serve"],
      "env": {
        "VM_API_URL": "https://api.viewmagnet.com",
        "VM_PAT_TOKEN": "vm_pat_<your-token-here>"
      }
    }
  }
}
```

Or just run:

```bash
npx viewmagnet-mcp install --print --token vm_pat_...
```

to print the snippet without touching disk.

## Example prompts

Once the server is loaded, try:

- "Analyze https://www.youtube.com/watch?v=dQw4w9WgXcQ and tell me what to fix."
- "Write me a Lead Magnet script about morning routines that destroy your focus."
- "Score this hook: 'Most diets are designed to fail. Here's why.'"
- "Find the 5 best clip moments in this video: https://youtu.be/..."
- "How are my recent published videos doing? Pull the outcomes and tell me which framework actually worked."

## Configuration

The `serve` subcommand reads its config from CLI flags or environment variables:

| Flag | Env var | Default | Purpose |
| --- | --- | --- | --- |
| `--api-url` | `VM_API_URL` / `VIEWMAGNET_API_URL` | `http://localhost:8000` | ViewMagnet API base URL. |
| `--token` | `VM_PAT_TOKEN` | _(required)_ | Personal Access Token. |
| _(none)_ | `VM_REQUEST_TIMEOUT_MS` | `60000` | Per-request timeout in milliseconds. |
| _(none)_ | `VM_MCP_VERBOSE` | `0` | Set to `1` for debug logging on stderr. |

## What's coming in v2

Today's release is the read/write **sync** surface. Coming next:

- `viewmagnet_extract_clip` — actually cut + return the rendered short.
- `viewmagnet_render_studio` — drive the Studio editor as a tool (async with polling).
- `viewmagnet_publish_distribution` — schedule a post across connected social accounts.

These all need backend work (binary delivery, job polling, scheduled-at fields) and are tracked separately.

## Troubleshooting

- **`No ViewMagnet API token configured`** — generate one at the dashboard and pass it as `--token` or `VM_PAT_TOKEN`.
- **`Invalid, revoked, or expired API token`** — token was revoked, expired, or never existed. Generate a new one.
- **Tool calls hang** — bump `VM_REQUEST_TIMEOUT_MS` (default 60s) if you're on a slow network. Studio rendering and `detect_highlights` on long videos are the usual culprits.
- **Claude Desktop doesn't see the tools** — fully quit Claude (Cmd-Q on macOS) and reopen; just closing the window isn't enough.

## License

MIT. See `LICENSE`.

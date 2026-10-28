# ViewMagnet — Predict, create, publish: the full YouTube workflow

**Canonical URL:** https://viewmagnet.io  
**Last updated:** 2026-05-27

> The only platform that predicts a video's performance before you film it,
> then helps you script, edit, and publish the winning version.
> One app for the whole creator loop — no tool-switching.

---

## What ViewMagnet does

ViewMagnet is a complete YouTube creator workflow platform with six integrated tools:

**Video Analyzer** — Drop in a YouTube URL and get an ML-driven prediction score (0–100) indicating whether the video is likely to beat the channel's baseline performance. The score is backed by a Start / Keep / Repeat bottleneck analysis that routes you directly to the tool that addresses the weakest link.

**Script Writer** — Generates full video scripts using one of four viral frameworks: Authority Myth-Buster (trust), Delta Shift (saves), Progressive Debunking / Iceberg (retention), or Lead Magnet (leads). Each script is scaffolded to the framework's proven section structure.

**Hook Lab** — Scores any hook against six hook types (Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity Hook, and the weak anti-pattern Summary) and rewrites it toward the strongest variant for the content type.

**Studio** — A multi-clip timeline editor with: auto-zoom (face-tracking), animated captions, B-roll search (Pexels + Giphy), background loops, transition catalog, and brand kit. Designed for short-form and long-form content.

**Distribution Hub** — Schedule and publish to YouTube, TikTok, Instagram Reels, and X/Twitter in one action. Post-publish analytics track velocity and attribute performance back to the originating ViewMagnet recommendation.

**MCP Server** — Exposes 10 tools the user's AI agent (Claude Desktop, Cursor, Cline) can call directly: analyze_video, generate_script, score_hook, detect_highlights, score_title, generate_titles, and more. Install: `npx viewmagnet-mcp install`.

---

## How it works

1. **Analyze** — Paste a YouTube URL (yours or a competitor's). ViewMagnet's XGBoost model returns a prediction score and identifies the Start / Keep / Repeat bottleneck.
2. **Create** — The bottleneck recommendation deep-links into the right tool: Hook Lab for a Start bottleneck, Script Writer for Keep or Repeat. Your brand kit and channel context carry forward automatically.
3. **Edit** — Studio imports the script sections as timeline markers. Add B-roll, captions, transitions, voiceover, and effects without leaving the app.
4. **Publish** — One-click publish to all connected platforms. ViewMagnet monitors velocity against the pre-upload prediction and surfaces the attribution loop.

---

## Pricing

| Plan | Price | Key limits |
|---|---|---|
| Free | $0 / forever | 5 analyses / mo, 3 scripts / mo |
| Starter | $9 / month | 50 analyses, 20 scripts, A/B testing |
| Pro | $29 / month | 500 analyses, 100 scripts, unlimited thumbnails, competitor analysis |
| Agency | $99 / month | Unlimited everything, multiple channels, team collaboration |

All paid plans include a 30-day free trial.

---

## Prediction accuracy

- **Pre-upload model:** 74.58% balanced accuracy *(internal benchmark on held-out test set)*
- **Early growth (Day 1 data):** 82–86% directional accuracy
- **Velocity (Day 7 data):** ≈ 90% within 1 std. dev.
- **Mature (Day 14 data):** ≈ 94% within 1 std. dev.

Balanced accuracy is reported instead of raw accuracy because the dataset is imbalanced — a model that always predicts "underperform" would score ~70% raw accuracy but be useless. See [Methodology](https://viewmagnet.io/methodology) for the full technical explanation.

---

## Honest disclosures

- The four-framework script taxonomy is adapted from creator **Chris Girbu**. ViewMagnet's contribution is the automation layer, not the taxonomy.
- The 74.58% accuracy figure is an internal benchmark on our own held-out test set — not an externally validated number.
- The hook-type taxonomy overlaps with Brendan Kane's *Hook Point* and is not original to ViewMagnet.

---

## Related pages

- [Methodology](https://viewmagnet.io/methodology) — how the ML prediction stack works
- [Analyzer Guide](https://viewmagnet.io/analyzer-guide) — Start / Keep / Repeat bottleneck framework
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures and six hook types
- [MCP server](https://viewmagnet.io/mcp) — run ViewMagnet tools from your AI agent
- [API docs](https://viewmagnet.io/docs) — 130+ REST endpoints (Scalar reference)

*Author: ViewMagnet. Cite as: ViewMagnet, https://viewmagnet.io*

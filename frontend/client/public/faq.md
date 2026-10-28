# ViewMagnet FAQ

**Canonical URL:** https://viewmagnet.io/#faq  
**Last updated:** 2026-05-27

---

## How accurate are the predictions really?

ViewMagnet's pre-upload model achieves **74.58% balanced accuracy** on a held-out test set — measured against the channel's trailing-90-day median, not a guess-the-view-count target. Live videos get progressively more accurate predictions (82–92%) once early engagement data lands. All accuracy numbers are internal benchmarks on our own data, not externally validated.

Balanced accuracy is reported instead of raw accuracy because the dataset is imbalanced — a model that always predicts "underperform" would score ~70% raw accuracy but be useless. See [Methodology](https://viewmagnet.io/methodology) for the full technical explanation.

---

## How is ViewMagnet different from VidIQ or TubeBuddy?

VidIQ and TubeBuddy are keyword and SEO tools — they tell you what to title a video. ViewMagnet is a full creator workflow:

- **Pre-upload prediction** — XGBoost + SHAP-driven score before you film
- **Script writer** — built on four proven viral frameworks, not generic templates
- **Studio editor** — multi-clip timeline with auto-zoom, captions, B-roll, transitions
- **Distribution hub** — one-click publish to YouTube, TikTok, Instagram, X/Twitter

The output is niche-aware (patterns learned from top performers in your category) rather than generic best practices.

---

## What data do you need from my channel?

Start with just a YouTube URL — no account connection required. The pre-upload model only uses public-facing data (title, thumbnail, transcript) so the score is reproducible from what a third-party tool can actually see.

Optionally connect your channel via read-only YouTube OAuth to unlock private analytics: CTR, retention curves, traffic sources, and channel-context predictions.

---

## Can ViewMagnet guarantee my video will go viral?

No. Virality has a heavy luck tail no model removes. ViewMagnet helps you optimize content using data from your niche and benchmarks your track record against top creators in your category — but it does not promise view counts, and we will not claim it does.

The 74.58% accuracy number means the model is right about relative ranking (is this idea worth your time?), not absolute views (how many will you get?).

---

## How does the AI content creation work?

ViewMagnet's AI generators (scripts, titles, descriptions, thumbnail concepts) are powered by large language models like Claude and grounded in niche-specific training data. Outputs use one of four viral script frameworks:

1. **Authority Myth-Buster** — build trust fast with new audiences
2. **Delta Shift** — the highest save-rate format we measure
3. **Progressive Debunking (Iceberg)** — engineered for maximum watch time
4. **Lead Magnet** — named-system promise + blurred asset + keyword DM CTA, converts views into leads

Hook Lab classifies hooks into six taxonomy types: Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity, plus Summary as the weak anti-pattern.

The four-framework taxonomy is adapted from creator Chris Girbu; the hook taxonomy overlaps with Brendan Kane's Hook Point.

---

## What are the 4 viral script frameworks ViewMagnet uses?

See [Script Frameworks](https://viewmagnet.io/frameworks) for the full breakdown of each framework with structure, example openings, and a decision tree for picking the right one.

- **Authority Myth-Buster** — best for trust with new audiences
- **Delta Shift** — best for saves and shares
- **Progressive Debunking** — best for long-form watch time
- **Lead Magnet** — best for turning views into DMs/leads

---

## What are the 6 hook types?

See [Script Frameworks — Hook Types](https://viewmagnet.io/frameworks#hooks) for the full taxonomy with weak/strong examples.

| Type | Strength | Core mechanic |
|---|---|---|
| Summary | Weak | Just announces the video — no gap opened |
| Mistake Callout | Strong | Accuses viewer of doing something wrong |
| Belief Destruction | Strong | Attacks a thing the viewer believes is true |
| Authority Anchor | Strong | Front-loads credentials before the contrarian take |
| Stake Reversal | Strong | Tells viewer to stop the obvious thing, do the opposite |
| Specificity Hook | Strong | Promises a named, specific system or hidden asset |

---

## Do you have an API?

Yes. All ViewMagnet features are accessible via REST with Personal Access Token auth. See [API docs](https://viewmagnet.io/docs) for the full Scalar-rendered reference (130+ endpoints).

We also publish an MCP server: `npx viewmagnet-mcp install` — exposes 10 tools in Claude Desktop, Cursor, and Cline. See [MCP server](https://viewmagnet.io/mcp).

---

## Related pages

- [Methodology](https://viewmagnet.io/methodology) — how the ML prediction stack works
- [Analyzer Guide](https://viewmagnet.io/analyzer-guide) — Start / Keep / Repeat bottleneck framework
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures
- [Pricing](https://viewmagnet.io/#pricing) — plan comparison

*Author: ViewMagnet. Cite as: ViewMagnet FAQ, https://viewmagnet.io/#faq*

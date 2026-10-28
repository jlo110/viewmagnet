# ViewMagnet — Product Catalog & Capability Analysis

*A grounded inventory of everything the product can and does offer, assessed for real user value — plus what's planned. Written from the codebase (routers, feature modules, dashboard nav, model registry), not aspiration. Last mapped: 2026-06-15.*

---

## 1. What ViewMagnet actually is

A **YouTube video-performance intelligence platform** with an unusually wide surface (~30 user-facing tools), organized around one closed loop:

> **See what's winning → understand why → make your version → publish it → measure the outcome → learn.**

Most competitors do *one* slice of this (a keyword tool, a thumbnail tester, a static "viral video" index). ViewMagnet's bet is that the slices become a **moat when connected** — every tool can hand context to the next (the `deepLinks` system literally exists to pass a transcript/clip/recommendation between tools).

**The wedge** (what no static-index competitor can copy): a **live, cross-channel Breakout Radar** powered by a real-time velocity-collection engine watching ~7,600 channels. Everything else is supporting cast around that signal.

### Maturity legend
- 🟢 **Live & served** — a real model/pipeline running in production
- 🔵 **Live (LLM-backed)** — works today via the LLM layer; degrades gracefully
- 🟡 **Built, needs a QA/polish pass** — code + router exist; maturity varies
- ⚪ **Scaffolded / dormant** — present but not the focus

---

## 2. The two product surfaces

The dashboard splits tools into **Intelligence** (analyze/decide) and **Create** (produce/publish). That split is the right mental model for users too.

---

## 3. INTELLIGENCE — "What should I make, and is now the moment?"

This is the differentiated half. It answers the only questions that actually grow a channel.

| Tool | What it does | Who needs it | Maturity |
|---|---|---|---|
| **Breakout Radar** ⭐ | Live feed of videos breaking out *across the tracked ecosystem right now* — calibrated P(breakout), the topic it's riding + how saturated that topic is, niche-conditioned confidence. The flagship. | Every creator hunting their next video while the wave is still open | 🟢 (AUC 0.93 @6h, calibrated, channel-grouped) |
| **Breakout Explainer** | On any radar item: *why* it's winning + a concrete "your version of this angle this week" — grounded only in measured evidence (no web hallucination). | Creators who need the *move*, not just the signal | 🔵 |
| **Candidate Ranker** | Score 2–4 of your own title+thumbnail options against a fine-tuned reach model before you publish. | Pre-publish decision moment | 🟢 (CLIP head, AUC 0.668 > 0.615 baseline) |
| **Video Analyzer** | Run any video/URL through the content classifier for an honest read on packaging + winning-formula breakdown. | Diagnosing a video or a competitor's | 🟢 (balanced-acc 0.746 / F1 0.638) |
| **Velocity Tracker** | The view-trajectory time series behind the radar — how a video is accelerating across checkpoints (1h→30d). | Power users watching specific videos | 🟢 |
| **Winning Formula** | Reverse-engineers what's working in a channel/niche into repeatable packaging patterns. | Pattern-finding for a niche | 🟡 |
| **Competitor Analysis** | Side-by-side read of rival channels' packaging + performance. | Positioning against rivals | 🟡 |
| **Trend Timing** | When to post / when a trend is rising vs. saturating (pairs with topic-saturation index). | Timing the upload | 🟡 |
| **A/B Tester** | Simulate/compare packaging variants. | Pre-publish iteration | 🟡 |
| **Keyword Research** | Search-demand + opportunity for topics. | Discovery / SEO | 🟡 |
| **Impact** | Closes the loop: did the tools' recommendations actually move realized views? Attribution from recommendation → outcome. | Trust / proving the product works | 🟡 |

**The love-worthy moment here:** opening the Radar and seeing a real video in *your* niche at "4.7× its channel's norm, P 0.83, topic still open" — and one click later getting *your* angle on it. That's the "I'd pay for this" feeling.

---

## 4. CREATE — "Help me actually make and ship the winning version"

The production half. Breadth play: take the creator from idea → finished, published video without tool-switching.

### 4a. Packaging & writing (LLM-backed)
| Tool | What it does | Maturity |
|---|---|---|
| **Title Generator** | On-brand titles scored by the packaging rubric (MrBeast-grounded). | 🔵 |
| **Script Writer** | Full scripts using viral frameworks. | 🔵 |
| **AI Writer** | General long-form/copy assistant. | 🔵 |
| **Thumbnail Creator** | Generate/iterate thumbnails. | 🟡 |
| **Hook Analyzer / Hook Lab** | Scores opening hooks for clips/Shorts retention. | 🔵 (backend shipped) |

### 4b. Video production (the Studio stack)
| Tool | What it does | Maturity |
|---|---|---|
| **Studio** ⭐ | In-app video editor — timeline, clips, overlays, subject-tracked vertical crops. The heavy engineering piece. | 🟢 (render pipeline verified end-to-end) |
| **Shorts Creator** | Auto-detect highlights from a long video → vertical Shorts. | 🟡 |
| **Animated Captions** | Word-level animated subtitles. | 🟡 |
| **Voiceover / Voice Dubbing** | TTS voiceover; dub into other languages. | 🟡 |
| **Faceless Generator** | Faceless-channel video assembly (B-roll + voiceover + captions). | 🟡 |
| **B-roll Finder / AI Effects / Loop Designer / Pacing** | Supporting editing utilities (stock footage, effects, seamless loops, pacing analysis). | 🟡/⚪ |
| **Drafts / Renders** | Manage works-in-progress and exported renders (R2-backed). | 🟢 |

### 4c. Publish & measure
| Tool | What it does | Maturity |
|---|---|---|
| **Distribution Hub** | Publish/cross-post to YouTube, TikTok, Instagram (OAuth connectors present). | 🟡 |
| **Outcomes** | Post-publish performance of what you shipped. | 🟡 |
| **Smart Alerts** | Get pinged when a video in your niche — or your own — starts to break out. | 🟡 |

**The love-worthy moment here:** "Re-edit in Studio" appearing on a Shorts highlight or a recommendation, carrying the transcript + hooks straight in. The connected-workflow promise made real.

---

## 5. The engine under the hood (why the above can exist)

These aren't tools users click — they're the infrastructure that makes the intelligence *real* and hard to copy.

- **Live collection engine** 🟢 — WebSub push discovery (zero-quota, ~30s latency) + 6h polling reconciliation, sampling ~7,600 channels at checkpoints (1h/6h/24h/3d/7d/14d/30d). *This is the irreplaceable asset — every hour it runs is data competitors can't backfill.*
- **Served ML models** 🟢 — content classifier (packaging), velocity models (trajectory), breakout detector (calibrated, AUC 0.93 @6h), reach model (fine-tuned CLIP head).
- **Topic-saturation index + "Most Replayed" heatmap capture** 🟢 — is a wave crowded? what's the retention shape? Both shipped.
- **LLM layer** 🔵 — Anthropic → Synthetic → Groq fallback with per-user budget caps + prompt caching. *Note: currently running on the Groq fallback until Anthropic credits are topped up; LLM tools work but on the cheaper model.*
- **Comment intelligence** 🟡 — top-comment capture feeds the explainer's "early audience reaction."
- **Billing transparency, usage metering, API tokens** 🟢 — the SaaS plumbing.

---

## 6. Practical lens — what users actually need, use, and love

Mapping features to a creator's real jobs-to-be-done:

| The creator's job | The tool(s) that win | Verdict |
|---|---|---|
| "What should my next video be?" | **Breakout Radar → Explainer** | ⭐ The killer flow. This alone justifies the product. |
| "Will this packaging work?" | **Candidate Ranker, Video Analyzer, A/B Tester** | Strong, pre-publish — high-frequency use. |
| "Write it for me" | **Script Writer, Title Generator, Hook Lab** | Table-stakes but solid; commoditized vs. competitors. |
| "Make the actual video" | **Studio, Shorts, Captions, Faceless** | Ambitious; the breadth differentiator if polished. |
| "Ship it everywhere" | **Distribution Hub** | Convenience layer; not a reason to switch alone. |
| "Did it work?" | **Outcomes, Impact, Smart Alerts** | The honesty loop — quietly the trust-builder. |

**What users will love (the keepers):**
1. **The live Radar** — genuinely novel, demoable in 5 seconds, no competitor match.
2. **Grounded "your angle" explainers** — turns a signal into an action.
3. **The connected workflow** — radar → ranker → studio → publish → outcome, with context carried.
4. **Honest measurement** — published real metrics, no "94% accuracy" theatre. A trust moat in a snake-oil category.

**The honest risk:** breadth (~30 tools) can read as thin if the long tail (4b/4c) isn't polished. The strategic move is to make the **Intelligence half undeniably excellent** and treat Create as the "and we help you ship it too" — not to claim 30 best-in-class tools.

---

## 7. What we plan to do (roadmap)

From `remediation_plan.md` (Phases 5–9) + `TODO.md`. The foundational/security/CI work (Phases 0–4) and the collection rebuild (Phase 5) are largely **done**; the forward agenda is about turning the live data into deeper intelligence and sharper positioning.

### Near-term, data-gated
- **Full-trajectory velocity retrain** (~July 2026) — once 30-day trajectories mature, retrain the trajectory model as a real curve, not 21 disconnected regressors. (Phase 5.5 / 6.2)
- **Calibrated uncertainty (conformal prediction)** — every prediction ships with an honest confidence interval. (Phase 6.3)
- **Reach predictor v2** — beyond the current CLIP head. (Phase 6.1/3.3)

### The "closed-loop optimizer" vision (Phase 6 — the north star)
- **Generate → score → rank → publish → measure → learn** as one reward-model loop. (6.4)
- **Retrieval-augmented niche intelligence** — kills staleness by grounding advice in fresh, niche-specific evidence. (6.5)
- **Causal uplift from real outcomes** — move from correlation ("videos like this do well") to causation ("*this change* caused the lift"). (6.6)
- **Agentic optimizer** — an assistant that runs the loop with you. (6.7, positioning-first per 9.3)

### Collection & coverage (Phase 7–8)
- **Tracked-set expansion 4.8k → 15–20k channels** (post-WebSub capacity). (8.11)
- **HIP/Hawkes decomposition** with user-facing virality parameters. (8.4)
- **Satisfaction-weighted targets** when OAuth analytics (CTR/retention) data lands — *flagged as the single biggest long-term accuracy lever.* (8.8 / TODO #6)
- **Pretrain on YouNiverse** to bootstrap the trajectory model before our own data fully matures. (8.3)

### Positioning (Phase 9 — the current focus)
- **9.1 Win the wedge, don't out-feature** — flagship Radar shipped; lead with it. ✅
- **9.2 Make honest measurement the brand** — the metrics page as a differentiator.
- **9.3 Borrow the agentic framing** — position the connected loop as an agent (UX/positioning, not a rebuild).

---

## 8. Strategic summary

**Strengths to lean on:** the live collection engine + Breakout Radar (a real moat), honest measurement (a brand moat in a hype-filled category), and a connected workflow most rivals can't match.

**Where to focus:** make the Intelligence half *undeniable*, polish the Create long tail or scope it honestly, and land the OAuth-analytics loop (#6) — it's the accuracy unlock that compounds.

**One-line pitch the catalog supports:**
> *"Every other tool shows you what already went viral. ViewMagnet shows you what's breaking out right now — and helps you make your version before the wave peaks."*

---

*Maturity tags are assessed from code presence + the model registry + plan status, not a hands-on QA of every tool. Recommend a click-through QA pass on the 🟡 Create long-tail before marketing any of them as flagship.*

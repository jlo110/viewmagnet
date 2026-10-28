# Research notes — cutting-edge ML for video performance (2026-06-12)

Literature sweep mapped against our roadmap (remediation_plan.md / TODO.md). Four findings
validate our current direction; the rest are adoptable techniques, new trackable variables,
and product ideas.

## A. What the literature VALIDATES about our approach

1. **Early trajectory >> content features for popularity.** Meme-virality time-window study
   (arXiv 2510.05761): content-only models plateau at PR-AUC ~0.13 while temporal/engagement
   features reach 0.54; 30 min of engagement → 0.43, 7h → 0.80. Exactly matches our breakout
   finding (early views-vs-channel carries ~all signal; AUC 0.94 @6h). Their "evidentiary
   transition" framing (static context predicts early, dynamic engagement predicts later) is a
   good mental model for when each of our models applies (reach predictor pre-upload →
   breakout detector post-upload).
2. **Rubric/VLM scoring of content correlates with engagement** (arXiv 2512.21402): VLM-extracted
   audiovisual features → interpretable factors → light regression on engagement; beats
   SSIM/FID-style metrics and is explainable. Validates our MrBeast packaging rubric + planned
   VLM ensemble (TODO #17.3) — and suggests extending it from thumbnail/title to full video.
3. **Drift-triggered adaptation beats indiscriminate retraining** (Shorts-Cast, arXiv 2605.18653):
   selective LoRA updates triggered by growth-anomaly drift detection outperform constant
   updates. Matches our drift-check-gates-retrain design (3.2).
4. **Label construction dominates results** (2510.05761): virality prediction is "highly sensitive
   to label construction" + time-censoring matters. We already learned this (channel-relative vs
   absolute reach flipped the CLIP verdict; age-normalized reach labels).

## B. Techniques to adopt

1. **Hawkes / HIP self-exciting processes for the trajectory model (5.5/6.2).** HIP (WWW'17,
   built FOR YouTube views) decomposes a view series into exogenous promotion × endogenous
   virality × promotion-sensitivity; Hawkes-family models cut short-term forecast error 25–30%
   vs autoregressive baselines. Two wins for us: (a) a principled curve model fit on our
   checkpoint series (better than generic parametric fits), (b) **interpretable per-video/channel
   params to surface to users**: "inherent virality" vs "promotion sensitivity" ("this video
   responds strongly to external pushes — promote it now"). See also "Popularity Prediction over
   Arbitrary Time Horizons" (arXiv 2009.02092) — directly relevant to our horizon-conditioned plan.
2. **Open-web grounding (Shorts-Cast, arXiv 2605.18653).** Popularity depends on whether the
   topic currently commands attention and how saturated the content pool is. Their structure:
   D1 topic/entity context, D2 public discourse, D3 competing content — collected at upload time
   via search-augmented LLMs. **Key caveat: unstructured web snippets HURT (below content-only
   baseline); structured evidence helps.** Cheap first step for us: compute D3 from OUR OWN
   collection — "topic saturation index" = density of same-topic uploads across our 4.8k tracked
   channels in the last 48h (title embeddings + clustering; zero quota, zero web dependency).
3. **Multimodal-LLM hook analysis (arXiv 2602.22299).** Frameworks scoring the first-3-seconds
   "hooking period" of video ads (visual+audio+text interplay). With 55% of viewers lost by 60s
   and ~8s decision windows (2025 retention benchmarks), a **hook analyzer** for clips/Shorts is
   research-supported and we already have video-analysis + LLM infra. OpusClip ships an
   LLM-as-judge clip-quality system in production — competitive proof.
4. **Satisfaction-weighted watch time.** YouTube (Beaupre, 2025) now weights watch time by
   satisfaction signals — surveys, RETURNING viewers, session continuation. Variables to favor
   when we have user OAuth: returning-viewer ratio, post-video session behavior, not raw minutes.

## C. New variables worth capturing (cost-ranked)

Already free (derivable from data we have — just compute):
- **Upload timing features**: hour-of-day / day-of-week / gap-since-channel's-last-upload.
- **Comment velocity** between checkpoints (comment_count deltas — snapshots already store it).
- **Like-velocity deltas** between checkpoints (likes at cp − likes at prev cp).
- **Channel cadence/consistency** + subscriber delta around upload (channel_snapshots daily ✓).
- **Topic saturation index** (B2): title-embedding cluster density per 48h window, per niche.

Free at capture time (same videos.list call — add columns, like 7.1 did):
- **description** (→ chapters present?, link/hashtag count, description length — chapters
  correlate with retention; we currently discard description entirely)
- **liveStreamingDetails** (was it a live/premiere — different velocity curves, contaminate
  training if unlabeled)
- **raw tags** (we store only tag_count; tags carry topic signal for the saturation index)
- **defaultAudioLanguage / region** (market segmentation for niche-normalization)

Costs quota/infra (prioritize when justified):
- **First-30s transcript/audio** for the hook analyzer (captions require owner OAuth; public ASR
  needs audio download — do only for user-owned or opt-in videos)
- **Open-web topic context** (Shorts-Cast D1/D2) — search-augmented LLM at video-discovery time;
  start with breakout videos only (cheap, highest value: "WHY is this breaking out").

## D. Product ideas backed by the research

1. **Hook analyzer** (B3) — score the first 3s/30s of a user's clip against hook patterns;
   explainable rubric (like the packaging score, for the opening). Fits the studio/clips tools.
2. **Topic saturation / timing advisor** (B2) — "12 tracked channels posted this topic in 48h;
   saturated — differentiate or wait" vs "rising topic, low saturation — post now."
3. **Virality vs promotion-sensitivity decomposition** (B1, HIP params) — tells a creator
   whether a video will spread on its own or needs a push, and when to spend promo budget.
4. **"Why it broke out" explainers** — for breakout-feed videos, attach LLM-grounded context
   (D1/D2 evidence) — turns the feed into actionable competitive intelligence.
5. **Retention-shape benchmarking** (once user OAuth data exists) — 2025 benchmark: average
   video retains 23.7%, 55% lost by 60s; channel-vs-niche retention-curve comparison.

## E. Where to get viewer/retention-style data (added 2026-06-12)

The exact B4 data (per-video retention curves, returning-viewer ratio, satisfaction surveys) is
**owner-private** via YouTube Analytics — not legally purchasable from anyone; vendors (Tubular,
SocialBlade etc.) resell *public* metrics only. Real substitutes, all free:

1. **"Most Replayed" heatmaps — the public retention-SHAPE proxy.** YouTube shows a per-video
   replay heatmap in the player; extractable via yt-dlp (`--write-info-json` includes `heatmap`)
   or Apify actors. 100 normalized points per video = which moments retain/lose viewers. Caveats:
   relative shape only (no absolute retention %), only on videos with enough views, unofficial
   endpoint (ToS gray zone — data is public in the UI). **Could be added to our capture jobs for
   breakout/tracked videos → retention-shape features + a "where viewers drop" advisor without OAuth.**
2. **KuaiRec** (kuairec.com, free) — fully-observed user×video matrix from Kuaishou with
   **watch_ratio** (watch time / video length) per interaction: real continuous engagement labels.
   Small (1.4k users × 3.3k videos dense + big sparse matrix) but ideal for prototyping
   watch-time/satisfaction models.
3. **MicroLens** (free, research) — **1B interactions, 34M users, 1M short videos WITH raw
   content** (title, cover image, audio, full video). The largest multimodal short-video
   engagement dataset; suited to pretraining content→engagement models (hook analyzer, reach).
4. **YouNiverse** (Zenodo 4650046, free) — 136k channels / 73M videos / **weekly channel-level
   view+sub time series** (avg 2.8 yrs/channel, through 2019). Old, but the *structure* transfers:
   pretrain trajectory/growth-curve models + channel-baseline priors before our own 30d data
   matures; 73M-video metadata (incl. tags/descriptions) is also a title/packaging corpus.
5. Kaggle "YouTube Trending" datasets — daily public stats of trending videos; strictly weaker
   than our own collection (no early checkpoints, survivor-biased to already-trending videos).

**Bottom line:** satisfaction/retention truth can't be bought — it's earned via owner OAuth (the
label flywheel, TODO #6). But heatmaps give a free public retention proxy at scale, and
KuaiRec/MicroLens/YouNiverse let us pretrain the model families now.

## Sources
- [Shorts-Cast: Grounding Micro-Video Popularity Prediction on the Open Web (arXiv 2605.18653)](https://arxiv.org/html/2605.18653)
- [Rubric-based VLM Framework for Short-Form Virality (arXiv 2512.21402)](https://arxiv.org/abs/2512.21402)
- [Early Multimodal Prediction of Meme Virality: Time-Window Analysis (arXiv 2510.05761)](https://arxiv.org/html/2510.05761v1)
- [Decoding the Hook: Multimodal LLM Analysis of the Hooking Period (arXiv 2602.22299)](https://arxiv.org/abs/2602.22299)
- [HIP: Hawkes Intensity Processes for Social Media Popularity (WWW'17)](https://ssanner.github.io/papers/www17_hip.pdf)
- [SEISMIC: Self-Exciting Point Process for Popularity (KDD'15)](http://snap.stanford.edu/seismic/seismic.pdf)
- [Popularity Prediction over Arbitrary Time Horizons (arXiv 2009.02092)](https://arxiv.org/pdf/2009.02092)
- [M3TR: Temporal-Retrieval-Enhanced Multi-Modal Popularity Prediction (arXiv 2411.15455)](https://arxiv.org/pdf/2411.15455)
- [2025 State of YouTube Audience Retention (Retention Rabbit)](https://www.retentionrabbit.com/blog/2025-youtube-audience-retention-benchmark-report)
- [YouTube algorithm satisfaction signals, 2025 (Marketing Agent blog)](https://marketingagent.blog/2025/11/04/youtubes-recommendation-algorithm-satisfaction-signals-what-you-can-control/)
- [OpusClip: LLM-as-a-Judge for video quality (production system)](https://medium.com/opus-engineering/a-scalable-llm-as-a-judge-framework-for-video-quality-evaluation-74612034bd1e)

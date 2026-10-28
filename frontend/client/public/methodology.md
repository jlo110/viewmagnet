# ViewMagnet Methodology: how our virality prediction works

**Canonical URL:** https://viewmagnet.io/methodology  
**Last updated:** 2026-05-27

> Plain-English walk-through of ViewMagnet's ML stack, training data,
> and the recommendation engine that turns predictions into actionable advice.

---

## The four models behind the dashboard

Different surfaces call different models. Each is trained separately because the question changes as a video ages — pre-upload prediction is a fundamentally different problem from 14-day-old extrapolation.

| Stage | Model type | Accuracy | Predicts |
|---|---|---|---|
| Pre-upload | XGBoost (gradient boosted trees) | **74.58% balanced accuracy** *(internal benchmark)* | Will this beat the channel's median? |
| Early growth (Day 1 → target) | Growth multiplier (rule + regression hybrid) | 82–86% directional accuracy *(internal)* | 30-day view band |
| Velocity (Day 7 → Day 30) | XGBoost regression | ≈ 90% within 1 std. dev. *(internal)* | Day-30 view count |
| Mature (Day 14 → Day 30) | XGBoost regression | ≈ 94% within 1 std. dev. *(internal)* | Day-30 view count |

All accuracy figures are measured on our own held-out test data, not from an external benchmark.

---

## Why we report balanced accuracy (not raw accuracy)

Most uploads don't beat their channel baseline. That's a data-imbalance problem — and it makes raw accuracy actively misleading.

Out of every 100 uploads, roughly 70 will *under-*perform their channel's trailing median and roughly 30 will *over-*perform. A model that learns nothing except "always predict underperform" will be right ~70% of the time — and completely useless to you, because it can never flag a winner.

**Balanced accuracy** averages the recall on each class. To score well, the model has to identify both winners *and* losers correctly. Our pre-upload model scores **74.58% balanced accuracy**, which means:

- Of videos that *do* beat the channel baseline, the model flags ~75% of them as likely winners.
- Of videos that *don't* beat the channel baseline, the model flags ~75% of them as likely underperformers.
- No silent free lunch from the majority class.

### What this number is not

It is not a guarantee that 74.58% of videos flagged "likely viral" will go viral. Virality has a heavy luck tail; the model is right about the *relative* ranking, not absolute view counts. Use it as a filter ("is this idea worth my time?") not as an oracle ("how many views will I get?").

---

## Training data & what the model can see

The pre-upload model only ever sees the same surface a third-party tool would have — public metadata, the title, the thumbnail, transcript-derived features. Never private YouTube analytics.

### What's in the dataset

- Hundreds of thousands of public YouTube videos across every major category (educational, gaming, lifestyle, business, music, comedy, reviews, news commentary).
- Both Shorts and long-form, kept in separate length buckets so the model never compares a 30-second hook against a 12-minute essay.
- Full thumbnail images + titles + descriptions + tags + auto-captioned transcripts.
- Channel context: subscriber count, trailing-90-day median, upload cadence, hit rate.

### What's deliberately excluded

- Private analytics (CTR, average view duration, retention curves) — the model has to predict those, not be told them.
- Any data from the creator's own channel until they opt-in to channel-aware predictions inside the dashboard.
- Personally identifiable information.

**Why this matters:** a lot of "AI virality" tools quietly train on leaked analytics or pay-walled creator dashboards, which makes their numbers look better than they are at upload time. We restrict ourselves to the public surface so the score on your screen is actually reproducible from what you can see.

---

## From prediction to recommendation: Start / Keep / Repeat

A single number is a verdict, not a tool. The recommendation engine breaks the prediction back down into the feature groups the algorithm rewards, names the weakest one, and routes you to the in-app tool that fixes it.

### Step 1 — Explain the prediction with SHAP

SHAP (SHapley Additive exPlanations) attributes a fraction of the predicted score to each input feature. For your video that means: how much of the score came from the thumbnail, how much from the title, how much from the channel's history, how much from the topic specificity. We use the same library that's standard in research papers — Lundberg & Lee, NeurIPS 2017 (https://arxiv.org/abs/1705.07874).

### Step 2 — Roll features up into Start / Keep / Repeat

Raw feature attribution is unreadable. We roll those values up into three buckets that match how the YouTube algorithm actually evaluates a video:

- **START** — Did people click? Title + thumbnail packaging.
- **KEEP** — Did they stay watching? Predicted retention plus channel context.
- **REPEAT** — Did they want to come back? Saves, shares, return-viewer signals.

### Step 3 — Route to the right tool

The lowest-scoring bucket becomes your bottleneck. The Algorithm Signals card then surfaces 2–3 specific CTAs that deep-link into the right tool with the right context already loaded — Hook Lab for Start, Script Writer for Keep / Repeat, A/B Tester to validate the change.

---

## Frequently asked

**Why "balanced" accuracy?** Because the dataset is imbalanced: most uploads do not exceed their channel baseline, so a model that always predicts "underperform" would score ~70% raw accuracy while being useless. Balanced accuracy averages the recall on each class (overperform vs underperform) so a useful model has to actually be right on both — not just on the majority class.

**What counts as a "win"?** A video is labelled an overperformer (the positive class) when its 30-day view count beats the creator's trailing-90-day median for the same length bucket (Shorts vs long-form). That eliminates "lucky" viral spikes from the comparison and isolates the question we actually care about: did this video out-earn the channel's normal output?

**What data was the pre-upload model trained on?** Public YouTube metadata + thumbnails + titles + transcript-derived features across hundreds of thousands of videos spanning every major category. The model never sees private analytics — only what a third-party tool would have at upload time.

**Is 74.58% any good?** It's well above the strongest "always predict the majority" baseline (~70%) and well above a random coin-flip (50%). It's not a perfect oracle. A useful mental model: about 3 out of 4 of our "this is a winner" predictions land — the other 1 is your reminder that virality has a luck component no model removes.

**What does the model NOT do?** It does not guarantee views, audit watch time, or replace human judgement on whether a topic is right for your audience. It also does not predict niche-specific virality cliffs (e.g. an evergreen tutorial may underperform on day 30 and then crush over six months). Use it as a filter, not a verdict.

**How is the recommendation engine different from the prediction?** The prediction is one number. The recommendation engine takes the underlying feature contributions (via SHAP) and turns them into named bottlenecks (Start / Keep / Repeat) plus targeted CTAs into Hook Lab, Script Writer, A/B Tester, etc.

---

## Sources & further reading

1. **Chen, T. & Guestrin, C. (2016).** XGBoost: A Scalable Tree Boosting System. *Proceedings of the 22nd ACM SIGKDD (KDD '16).* https://arxiv.org/abs/1603.02754 — The gradient-boosted tree algorithm we use for the pre-upload, velocity, and mature-stage models.

2. **Lundberg, S. M. & Lee, S.-I. (2017).** A Unified Approach to Interpreting Model Predictions. *NeurIPS 2017.* https://arxiv.org/abs/1705.07874 — SHAP — the explanation framework we use to attribute prediction score to title / thumbnail / channel features.

3. **Brodersen, K. H. et al. (2010).** The Balanced Accuracy and Its Posterior Distribution. *20th International Conference on Pattern Recognition.* https://ieeexplore.ieee.org/document/5597285 — Defines balanced accuracy and the reasoning for using it instead of raw accuracy when the positive class is rarer than the negative class.

4. **He, H. & Garcia, E. A. (2009).** Learning from Imbalanced Data. *IEEE Transactions on Knowledge and Data Engineering, 21(9).* https://ieeexplore.ieee.org/document/5128907 — Survey of why majority-class predictors get ~70% accuracy on imbalanced datasets while being useless.

5. **Provost, F. & Fawcett, T. (2013).** Data Science for Business (Chapters 7–8). *O'Reilly Media.* https://www.oreilly.com/library/view/data-science-for/9781449374273/ — Plain-English treatment of the imbalanced-class problem.

---

## Related pages

- [Analyzer Guide](https://viewmagnet.io/analyzer-guide) — Start / Keep / Repeat bottleneck framework with sample rewrites
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures and six hook types
- [MCP server](https://viewmagnet.io/mcp) — run ViewMagnet tools from Claude Desktop, Cursor, or Cline
- [API docs](https://viewmagnet.io/docs) — 130+ REST endpoints

*Author: ViewMagnet. Cite as: ViewMagnet Methodology, https://viewmagnet.io/methodology*

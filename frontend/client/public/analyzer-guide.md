# ViewMagnet Analyzer Guide: Start / Keep / Repeat

**Canonical URL:** https://viewmagnet.io/analyzer-guide  
**Last updated:** 2026-05-27

> The Start / Keep / Repeat bottleneck framework with diagnosis,
> symptoms, weak-vs-strong rewrites, and the research behind each.

---

## What the Analyzer tells you

ViewMagnet's Video Analyzer returns a prediction score *and* a bottleneck. The bottleneck is the single weakest signal in your video's feature set — the one thing, if fixed, most likely to move the overall score.

There are three bottlenecks, named after the three algorithmic signals YouTube actually measures:

- **START** — Did people click?
- **KEEP** — Did they stay watching?
- **REPEAT** — Did they want to come back?

The bottleneck is surfaced by running SHAP (SHapley Additive exPlanations) over the XGBoost prediction and rolling the per-feature attributions up into these three buckets. See [Methodology](https://viewmagnet.io/methodology) for the technical details.

---

## Start Bottleneck

**Core question:** Did people click to start watching?

### Diagnosis

Your title and thumbnail aren't earning enough clicks. Even great content can't reach an audience if nobody clicks. Fix the packaging before anything else — every other improvement is downstream of impressions converting to views.

### Symptoms

- CTR (click-through rate) noticeably below your channel's typical baseline
- Strong retention on the few people who do click — they like the content, you just aren't getting them in the door
- Thumbnail is "competent" but blends in (similar palette, no obvious focal point, words a viewer has seen 100 times)
- Title summarizes the video rather than opening a curiosity gap

### What to do

Rewrite the hook so it opens a gap the viewer needs to close. Make the thumbnail readable at 2cm. Validate with the A/B Tester before committing.

**In-app tools:** Hook Lab → generate title + thumbnail variants → A/B Test the packaging.

### Weak vs. strong rewrites

**Before:** "Here are 3 tips to grow your Instagram"  
**After:** "Stop posting Reels until you've fixed the mistake 87% of new accounts make in their first week"  
*Why it works: Converts a generic tip-list into a mistake callout — viewer can't tell if they're making the mistake without watching.*

**Before:** "How I edit my YouTube videos"  
**After:** "I used to spend 6 hours editing one video. Then I cut 5 things from my workflow — same retention, 90 minutes total"  
*Why it works: Anchors specificity (6 hours → 90 minutes) and creates an open loop (which 5 things?).*

**Before:** "Marketing strategies for 2026"  
**After:** "Every marketing playbook from 2024 is obsolete. Here are the 3 plays still working in Q2 2026 (and the one that just broke)"  
*Why it works: Uses stake reversal plus belief destruction, which consistently outperform summary hooks.*

---

## Keep Bottleneck

**Core question:** Did they stay watching after they clicked?

### Diagnosis

Viewers click but drop off early. The hook is doing its job — the body of the video is losing them. Usually that's pacing, structure, or a hook that over-promises and doesn't pay off in the first 30 seconds.

### Symptoms

- CTR is healthy but Average View Duration is well below the platform's typical retention for the length bucket
- Sharp drop-off in the first 15–30 seconds (the "they clicked but bounced" shape) — folk-wisdom rule of thumb from creator-side analysis, not a peer-reviewed claim
- Long monologues without re-anchoring curiosity
- Hook promises something the video buries 4 minutes in

### What to do

Tighten the hook → payoff loop. Use the Progressive Debunking framework to keep viewers expecting the next revelation. Cut dead air. Re-anchor curiosity every 15–30 seconds.

**In-app tools:** Use Progressive Debunking framework → score your hook in Hook Lab → design a retention loop.

### Weak vs. strong rewrites

**Before:** "Open: 'Today I'm going to show you 5 tips. Tip #1 is...' — single linear list, no loop."  
**After:** "Open: 'There are 5 reasons your videos plateau. The 4th one is what almost every YouTuber gets wrong — we'll get there in 2 minutes.' Then deliver 1, 2, 3 with a tease back to #4 before each one."  
*Why it works: Creates a forward-pointing curiosity loop — viewers stay watching specifically to hear #4.*

**Before:** "Open with a long personal anecdote before the value lands at 1:30."  
**After:** "Open with the single most counterintuitive insight in the video, THEN give the anecdote that earned it."  
*Why it works: Puts payoff in the first 10 seconds, which is when retention curves typically inflect.*

---

## Repeat Bottleneck

**Core question:** Did they want to come back?

### Diagnosis

Viewers watch once but don't save, share, or come back for the next upload. The video delivers in the moment but doesn't earn long-term attention. Usually that's because the content doesn't crystallise into something the viewer wants to bookmark or pass along.

### Symptoms

- Saves and shares are low relative to view count
- Return-viewer rate (followers who come back for the next upload) trending down
- Comments are generic ("nice video!") rather than reaction-driven
- Content has no named, repeatable structure the viewer can hold onto

### What to do

Add named systems (give your method a name viewers can search later). Build in clear lead-magnet payoffs. Use the Lead Magnet or Authority Myth-Buster framework — both engineer saves and shares.

**In-app tools:** Lead Magnet framework → Authority Myth-Buster framework → Delta Shift framework (highest save rate).

### Weak vs. strong rewrites

**Before:** "Generic 'follow for more tips' end-card."  
**After:** "Name the system and give it a keyword CTA: 'I call this the 3-Block method. Comment BLOCK and I'll DM you the template.' Now the system has a memorable name and the save → DM loop earns the lead."  
*Why it works: Turns a forgettable end-card into a named asset viewers can search for and re-share.*

**Before:** "Restate the conclusion in a different way at the end."  
**After:** "End with the single counterintuitive insight as a one-line takeaway viewers can screenshot and share — and tease the next video as a direct extension."  
*Why it works: Engineers the screenshot / DM loop, which is the actual mechanic behind a high save rate.*

---

## Academic sources

1. **Loewenstein, G. (1994).** The Psychology of Curiosity: A Review and Reinterpretation. *Psychological Bulletin, 116(1).* https://doi.org/10.1037/0033-2909.116.1.75 — The foundational "information gap" paper. Every Hook Lab rewrite operationalizes this: the strong version opens a gap the viewer needs to close.

2. **Berger, J. & Milkman, K. L. (2012).** What Makes Online Content Viral? *Journal of Marketing Research, 49(2).* https://doi.org/10.1509/jmr.10.0353 — Empirical work showing that high-arousal emotion predicts sharing better than valence. Backs the Repeat-bottleneck advice to engineer shareable insights.

3. **Kahneman, D. & Tversky, A. (1979).** Prospect Theory: An Analysis of Decision under Risk. *Econometrica, 47(2).* https://doi.org/10.2307/1914185 — Loss aversion — losses are felt roughly 2× as strongly as equivalent gains. The "stake reversal" rewrite pattern leans on this directly.

4. **Schindler, R. M. & Yalch, R. (2006).** It Seems Factual, But Is It? *Advances in Consumer Research, Vol. 33.* https://www.acrwebsite.org/volumes/12390/volumes/v33/NA-33 — Precise numbers outperform round ones in perceived credibility — the empirical basis for the specificity rewrites.

5. **Berger, J. (2013).** Contagious: Why Things Catch On (Chapter 4 — Practical Value). *Simon & Schuster.* https://jonahberger.com/books/contagious/ — Practical-value content gets saved and shared at much higher rates — the empirical case behind the Lead Magnet and Delta Shift framework advice.

## Creator sources

- **Girbu, C.** The 4 viral script frameworks. https://www.chrisgirbu.com/ — Origin of the Authority Myth-Buster / Delta Shift / Progressive Debunking / Lead Magnet taxonomy.
- **Galloway, P.** Retention-curve & packaging breakdowns. https://www.paddygalloway.com/ — Reference point for the observation that the first 10–30 seconds is where retention curves typically inflect. Treated as folk wisdom rather than academic claim.
- **Kane, B. (2020).** Hook Point: How to Stand Out in a 3-Second World. https://hookpoint.com/ — Heritage for the strong-vs-weak hook taxonomy.
- **YouTube Creator Insider.** Algorithm & retention guidance. https://www.youtube.com/@YouTubeCreators — Platform-side observations about CTR + AVD as the two strongest reach signals.

---

## Related pages

- [Methodology](https://viewmagnet.io/methodology) — how the ML prediction stack works
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures and six hook types
- [API docs](https://viewmagnet.io/docs) — /analyze/video endpoint
- [MCP server](https://viewmagnet.io/mcp) — viewmagnet_analyze_video tool

*Author: ViewMagnet. Cite as: ViewMagnet Analyzer Guide, https://viewmagnet.io/analyzer-guide*

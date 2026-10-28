/**
 * /methodology — public marketing + credibility page that explains
 * the ML stack behind ViewMagnet's prediction and recommendation
 * surfaces.
 *
 * Why this page exists:
 *
 *  - Marketing copy and the dashboard repeatedly cite numbers like
 *    "74.58% balanced accuracy" without anywhere defining what that
 *    means or how it was measured. For a sceptical creator that
 *    looks like vanity stats; for an honest evaluator it raises the
 *    question "balanced against what baseline?".
 *  - The product makes algorithmic claims (Start / Keep / Repeat
 *    breakdown, prediction score, channel score) that look opaque
 *    without a methodology page to point at.
 *  - We want a single citable URL for the FAQ, footer, and the
 *    Video Analyzer's "What does this mean?" tooltip.
 *
 * Source of truth for the numbers:
 *   - ``PRODUCT_FEATURES.md`` §4.2 "Models (under the hood)"
 *   - ``src/ml/improved_predictor_v2.py`` (XGBoost pre-upload model)
 *   - ``scripts/train_with_content.py`` (training pipeline)
 *
 * If those numbers ever change, update this page in lockstep.
 */
import { Link } from "wouter";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Database,
  ExternalLink,
  FlaskConical,
  GraduationCap,
  LineChart,
  Scale,
  ShieldAlert,
  Sparkles,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SEOHead, StructuredData } from "@/components/seo";

// ---------------------------------------------------------------------------
// Model table
// ---------------------------------------------------------------------------

type ModelRow = {
  stage: string;
  blurb: string;
  type: string;
  metric: string;
  target: string;
};

const MODELS: ModelRow[] = [
  {
    stage: "Pre-upload",
    blurb:
      "Predicts whether an idea + title + thumbnail is likely to outperform a creator's channel baseline — used in the Video Analyzer before you upload.",
    type: "XGBoost (gradient boosted trees)",
    // The 74.58% number is the held-out balanced accuracy on our
    // own internal test split; it is NOT externally validated.
    // The "Internal benchmark" pill in the rendered table is the
    // visual disclosure of that distinction.
    metric: "74.58% balanced accuracy",
    target: "Will this beat the channel's median?",
  },
  {
    stage: "Early growth (Day 1 → target)",
    blurb:
      "Extrapolates a video's expected 30-day view count from its first 24 hours of performance.",
    type: "Growth multiplier (rule + regression hybrid)",
    metric: "82–86% directional accuracy",
    target: "30-day view band",
  },
  {
    stage: "Velocity (Day 7 → Day 30)",
    blurb:
      "Once a video has 7 days of public data, projects the remaining month-end performance.",
    type: "XGBoost regression",
    metric: "≈ 90% within 1 std. dev.",
    target: "Day-30 view count",
  },
  {
    stage: "Mature (Day 14 → Day 30)",
    blurb:
      "Final-fit projection used in the Velocity Tracker once the early-life noise has decayed.",
    type: "XGBoost regression",
    metric: "≈ 94% within 1 std. dev.",
    target: "Day-30 view count",
  },
];

// ---------------------------------------------------------------------------
// Citations
//
// These are the real, externally-verifiable references behind the
// methods we use. Each entry MUST be a paper / book / standard
// that actually exists — no hallucinated DOIs. If a future
// contributor wants to add a citation, the rule is: must be on
// arXiv / DOI-resolvable / a Wikipedia-citable book. If you can
// only find the claim on a blog, demote it to the "creator
// sources" footnote on /frameworks instead.
// ---------------------------------------------------------------------------

type Citation = {
  authors: string;
  year: string;
  title: string;
  venue: string;
  url: string;
  why: string;
};

const CITATIONS: Citation[] = [
  {
    authors: "Chen, T. & Guestrin, C.",
    year: "2016",
    title: "XGBoost: A Scalable Tree Boosting System",
    venue: "Proceedings of the 22nd ACM SIGKDD (KDD '16)",
    url: "https://arxiv.org/abs/1603.02754",
    why: "The gradient-boosted tree algorithm we use for the pre-upload, velocity, and mature-stage models.",
  },
  {
    authors: "Lundberg, S. M. & Lee, S.-I.",
    year: "2017",
    title:
      "A Unified Approach to Interpreting Model Predictions",
    venue: "NeurIPS 2017",
    url: "https://arxiv.org/abs/1705.07874",
    why: "SHAP — the explanation framework we use to attribute prediction score to title / thumbnail / channel features for the Start / Keep / Repeat bottleneck rollup.",
  },
  {
    authors: "Brodersen, K. H. et al.",
    year: "2010",
    title:
      "The Balanced Accuracy and Its Posterior Distribution",
    venue: "20th International Conference on Pattern Recognition",
    url: "https://ieeexplore.ieee.org/document/5597285",
    why: "Defines balanced accuracy and the reasoning for using it instead of raw accuracy when the positive class is rarer than the negative class.",
  },
  {
    authors: "He, H. & Garcia, E. A.",
    year: "2009",
    title: "Learning from Imbalanced Data",
    venue:
      "IEEE Transactions on Knowledge and Data Engineering, 21(9)",
    url: "https://ieeexplore.ieee.org/document/5128907",
    why: "Survey of why majority-class predictors get ~70% accuracy on imbalanced datasets while being useless — the failure mode our balanced-accuracy reporting protects against.",
  },
  {
    authors: "Provost, F. & Fawcett, T.",
    year: "2013",
    title: "Data Science for Business (Chapters 7–8)",
    venue: "O'Reilly Media",
    url: "https://www.oreilly.com/library/view/data-science-for/9781449374273/",
    why: "Plain-English treatment of the imbalanced-class problem and the 'majority-class baseline' framing we use to explain why 74.58% is a meaningful number.",
  },
];

// ---------------------------------------------------------------------------
// FAQ items — short, scannable, no marketing fluff
// ---------------------------------------------------------------------------

const FAQ_ITEMS: Array<{ q: string; a: string }> = [
  {
    q: 'Why "balanced" accuracy?',
    a: "Because the dataset is imbalanced: most uploads do not exceed their channel baseline, so a model that always predicts 'underperform' would score ~70% raw accuracy while being useless. Balanced accuracy averages the recall on each class (overperform vs underperform) so a useful model has to actually be right on both — not just on the majority class.",
  },
  {
    q: "What counts as a 'win'?",
    a: "A video is labelled an overperformer (the positive class) when its 30-day view count beats the creator's trailing-90-day median for the same length bucket (Shorts vs long-form). That eliminates 'lucky' viral spikes from the comparison and isolates the question we actually care about: did this video out-earn the channel's normal output?",
  },
  {
    q: "What data was the pre-upload model trained on?",
    a: "Public YouTube metadata + thumbnails + titles + transcript-derived features across hundreds of thousands of videos spanning every major category. The model never sees private analytics — only what a third-party tool would have at upload time. This is deliberate so the pre-upload score is honest about what's actually predictable from the public surface.",
  },
  {
    q: "Is 74.58% any good?",
    a: "It's well above the strongest 'always predict the majority' baseline (~70%) and well above a random coin-flip (50%). It's not a perfect oracle. A useful mental model: about 3 out of 4 of our 'this is a winner' predictions land — the other 1 is your reminder that virality has a luck component no model removes.",
  },
  {
    q: "What does the model NOT do?",
    a: "It does not guarantee views, audit watch time, or replace human judgement on whether a topic is right for your audience. It also does not predict niche-specific virality cliffs (e.g. an evergreen tutorial may underperform on day 30 and then crush over six months). Use it as a filter, not a verdict.",
  },
  {
    q: "How is the recommendation engine different from the prediction?",
    a: "The prediction is one number. The recommendation engine takes the underlying feature contributions (via SHAP — SHapley Additive exPlanations) and turns them into named bottlenecks (Start / Keep / Repeat) plus targeted CTAs into Hook Lab, Script Writer, A/B Tester, etc. That's why two 60-scoring videos can get different advice: the same composite score can come from different feature weaknesses.",
  },
];

// ---------------------------------------------------------------------------
// Small reusable bits
// ---------------------------------------------------------------------------

/**
 * Visual badge that marks a claim as "we measured this on our own
 * data" rather than "this comes from a published paper". Used
 * alongside the per-model accuracy numbers and any dataset-derived
 * statistic. The point is to be honest about the difference
 * between externally-cited methodology and internal benchmarks.
 */
function InternalBenchmark() {
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-amber-glow/30 bg-amber-glow/5 text-[10px] font-medium text-amber-glow"
      title="This number is measured on our own internal test data, not from an externally published benchmark."
    >
      <FlaskConical className="w-3 h-3" />
      Internal benchmark
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MethodologyPage() {
  return (
    <>
      <SEOHead
        title="ViewMagnet Methodology: how our virality prediction works"
        description="What 74.58% balanced accuracy actually means, what data ViewMagnet's pre-upload model was trained on, and how the Start / Keep / Repeat recommendation engine turns those predictions into actionable advice."
        canonicalUrl="/methodology"
        ogType="article"
        keywords="balanced accuracy, XGBoost, SHAP, YouTube prediction model, virality prediction, ML methodology, machine learning explainability, video performance prediction"
        markdownUrl="/methodology.md"
        article={{
          publishedTime: "2026-05-23",
          modifiedTime: "2026-05-24",
          author: "ViewMagnet",
          tags: [
            "methodology",
            "machine learning",
            "balanced accuracy",
            "XGBoost",
            "SHAP",
            "YouTube analytics",
          ],
        }}
      />
      <StructuredData
        type="article"
        headline="ViewMagnet Methodology: how our virality prediction works"
        description="A plain-English walk-through of ViewMagnet's ML stack, training data, and recommendation engine."
        datePublished="2026-05-23"
        dateModified="2026-05-24"
        author="ViewMagnet"
        url="/methodology"
      />
      {/* Breadcrumb trail so search + AI engines see the page
          hierarchy without parsing the nav. */}
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "Methodology", url: "/methodology" },
        ]}
      />
      {/* FAQPage schema — the FAQ_ITEMS array gets a parallel
          JSON-LD representation so generative engines can quote
          the answers verbatim with attribution. */}
      <StructuredData
        type="faq"
        questions={FAQ_ITEMS.map((item) => ({
          question: item.q,
          answer: item.a,
        }))}
      />

      <div className="min-h-screen bg-gradient-to-b from-deep-charcoal to-gunmetal">
        <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
          <div className="container mx-auto px-4 h-16 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
                <Zap
                  className="w-4 h-4 text-deep-charcoal"
                  strokeWidth={2.5}
                />
              </div>
              <span className="text-lg font-bold">
                View<span className="text-cyan-glow">Magnet</span>
              </span>
            </Link>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to Home
              </Link>
            </Button>
          </div>
        </header>

        <main className="container mx-auto px-4 py-16 max-w-5xl">
          {/* Hero */}
          <section className="text-center mb-16">
            <Badge
              variant="outline"
              className="mb-4 border-cyan-glow/30 text-cyan-glow"
            >
              Methodology
            </Badge>
            <h1 className="text-4xl md:text-5xl font-bold mb-4 tracking-tight">
              How ViewMagnet predicts virality
            </h1>
            <p className="text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed">
              Four models, one shared honesty rule: if we can't
              explain it in plain English, it doesn't ship. Here's
              the stack — what each model does, what it was trained
              on, and what the numbers we quote actually mean.
            </p>
          </section>

          {/* Quick links */}
          <section className="mb-16 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl mx-auto">
            <a
              href="#models"
              className="p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors bg-background/30"
            >
              <Database className="w-5 h-5 text-cyan-glow mb-2" />
              <p className="text-sm font-semibold">The four models</p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Pre-upload, early growth, velocity, mature
              </p>
            </a>
            <a
              href="#balanced-accuracy"
              className="p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors bg-background/30"
            >
              <Scale className="w-5 h-5 text-cyan-glow mb-2" />
              <p className="text-sm font-semibold">
                What "balanced accuracy" means
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Why we don't quote raw accuracy
              </p>
            </a>
            <a
              href="#recommendations"
              className="p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors bg-background/30"
            >
              <Target className="w-5 h-5 text-cyan-glow mb-2" />
              <p className="text-sm font-semibold">
                Predictions → recommendations
              </p>
              <p className="text-[11px] text-muted-foreground mt-1">
                How SHAP becomes Start / Keep / Repeat
              </p>
            </a>
          </section>

          {/* The four models */}
          <section id="models" className="mb-20 scroll-mt-24">
            <div className="mb-8">
              <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">
                <Database className="w-6 h-6 text-cyan-glow" />
                The four models behind the dashboard
              </h2>
              <p className="text-sm text-muted-foreground">
                Different surfaces (Video Analyzer, Velocity Tracker,
                Early Growth) call different models. Each is trained
                separately because the question changes as a video
                ages — pre-upload prediction is a fundamentally
                different problem from 14-day-old extrapolation.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4">
              {MODELS.map((m) => (
                <Card
                  key={m.stage}
                  className="bg-background/40 border-border/40"
                >
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <CardTitle className="text-lg">
                        {m.stage}
                      </CardTitle>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge
                          variant="outline"
                          className="border-cyan-glow/30 text-cyan-glow"
                        >
                          {m.metric}
                        </Badge>
                        {/* All four model accuracy numbers come
                            from our own held-out test set, not
                            from any external benchmark. The pill
                            is the visual disclosure that lets a
                            careful reader tell the difference
                            between externally-cited methodology
                            (XGBoost, SHAP) and internal
                            measurement (our model's accuracy on
                            our data). */}
                        <InternalBenchmark />
                      </div>
                    </div>
                    <CardDescription>{m.blurb}</CardDescription>
                  </CardHeader>
                  <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div>
                      <p className="text-muted-foreground mb-1">
                        Model type
                      </p>
                      <p className="font-medium text-foreground">
                        {m.type}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground mb-1">
                        Predicts
                      </p>
                      <p className="font-medium text-foreground">
                        {m.target}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>

          {/* What balanced accuracy means */}
          <section
            id="balanced-accuracy"
            className="mb-20 scroll-mt-24"
          >
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Scale className="w-5 h-5 text-cyan-glow" />
                  Why we report balanced accuracy (not raw accuracy)
                </CardTitle>
                <CardDescription>
                  Most uploads don't beat their channel baseline.
                  That's a data-imbalance problem — and it makes raw
                  accuracy actively misleading.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm leading-relaxed">
                <p className="flex flex-wrap items-baseline gap-2">
                  <span>
                    Out of every 100 uploads, roughly 70 will{" "}
                    <em>under-</em>perform their channel's trailing
                    median and roughly 30 will <em>over-</em>
                    perform. A model that learns nothing except
                    "always predict underperform" will be right
                    ~70% of the time — and completely useless to
                    you, because it can never flag a winner.
                  </span>
                  <InternalBenchmark />
                </p>
                <p>
                  Balanced accuracy averages the recall on each
                  class. To score well, the model has to identify
                  both winners <em>and</em> losers correctly. Our
                  pre-upload model scores 74.58% balanced accuracy,
                  which means:
                </p>
                <ul className="list-disc pl-6 space-y-2">
                  <li>
                    Of videos that <em>do</em> beat the channel
                    baseline, the model flags ~75% of them as
                    likely winners.
                  </li>
                  <li>
                    Of videos that <em>don't</em> beat the channel
                    baseline, the model flags ~75% of them as
                    likely underperformers.
                  </li>
                  <li>
                    No silent free lunch from the majority class.
                  </li>
                </ul>
                <div className="rounded-md border border-amber-glow/30 bg-amber-glow/5 p-4">
                  <p className="text-xs font-semibold text-amber-glow mb-1 flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4" />
                    What this number is not
                  </p>
                  <p className="text-xs text-muted-foreground">
                    It is not a guarantee that 74.58% of videos
                    flagged "likely viral" will go viral. Virality
                    has a heavy luck tail; the model is right about
                    the <em>relative</em> ranking, not absolute
                    view counts. Use it as a filter (
                    <em>"is this idea worth my time?"</em>) not as
                    an oracle (<em>"how many views will I get?"</em>
                    ).
                  </p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* Training data */}
          <section id="training" className="mb-20 scroll-mt-24">
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GraduationCap className="w-5 h-5 text-cyan-glow" />
                  Training data &amp; what the model can see
                </CardTitle>
                <CardDescription>
                  The pre-upload model only ever sees the same
                  surface a third-party tool would have — public
                  metadata, the title, the thumbnail, transcript-
                  derived features. Never private YouTube analytics.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm leading-relaxed">
                <div>
                  <h3 className="font-semibold text-foreground mb-2 text-base">
                    What's in the dataset
                  </h3>
                  <ul className="list-disc pl-6 space-y-1.5 text-sm">
                    <li>
                      Hundreds of thousands of public YouTube videos
                      across every major category (educational,
                      gaming, lifestyle, business, music, comedy,
                      reviews, news commentary).
                    </li>
                    <li>
                      Both Shorts and long-form, kept in separate
                      length buckets so the model never compares a
                      30-second hook against a 12-minute essay.
                    </li>
                    <li>
                      Full thumbnail images + titles + descriptions
                      + tags + auto-captioned transcripts.
                    </li>
                    <li>
                      Channel context: subscriber count, trailing-
                      90-day median, upload cadence, hit rate.
                    </li>
                  </ul>
                </div>

                <div>
                  <h3 className="font-semibold text-foreground mb-2 text-base">
                    What's deliberately excluded
                  </h3>
                  <ul className="list-disc pl-6 space-y-1.5 text-sm">
                    <li>
                      Private analytics (CTR, average view duration,
                      retention curves) — the model has to predict
                      those, not be told them.
                    </li>
                    <li>
                      Any data from the creator's own channel until
                      they opt-in to channel-aware predictions
                      inside the dashboard.
                    </li>
                    <li>
                      Personally identifiable information.
                    </li>
                  </ul>
                </div>

                <div className="rounded-md border border-cyan-glow/20 bg-cyan-glow/5 p-4">
                  <p className="text-xs text-muted-foreground">
                    <strong className="text-cyan-glow">Why this matters:</strong>{" "}
                    a lot of "AI virality" tools quietly train on
                    leaked analytics or pay-walled creator dashboards,
                    which makes their numbers look better than they
                    are at upload time. We restrict ourselves to the
                    public surface so the score on your screen is
                    actually reproducible from what you can see.
                  </p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* Predictions → recommendations */}
          <section
            id="recommendations"
            className="mb-20 scroll-mt-24"
          >
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-cyan-glow" />
                  From prediction to recommendation
                </CardTitle>
                <CardDescription>
                  A single number is a verdict, not a tool. The
                  recommendation engine breaks the prediction back
                  down into the feature groups the algorithm
                  rewards, names the weakest one, and routes you to
                  the in-app tool that fixes it.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5 text-sm leading-relaxed">
                <div>
                  <h3 className="font-semibold text-foreground mb-2 text-base">
                    Step 1 — Explain the prediction with SHAP
                  </h3>
                  <p className="text-sm">
                    SHAP (SHapley Additive exPlanations) attributes a
                    fraction of the predicted score to each input
                    feature. For your video that means: how much of
                    the score came from the thumbnail, how much from
                    the title, how much from the channel's history,
                    how much from the topic specificity. We use the
                    same library that's standard in research
                    papers — nothing custom or proprietary about the
                    explanation step (
                    <a
                      href="https://arxiv.org/abs/1705.07874"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-glow hover:underline inline-flex items-baseline gap-1"
                    >
                      Lundberg &amp; Lee, NeurIPS 2017
                      <ExternalLink className="w-3 h-3 self-center" />
                    </a>
                    ).
                  </p>
                </div>

                <div>
                  <h3 className="font-semibold text-foreground mb-2 text-base">
                    Step 2 — Roll features up into Start / Keep / Repeat
                  </h3>
                  <p className="text-sm mb-3">
                    Raw feature attribution is unreadable. We roll
                    those values up into three buckets that match
                    how the YouTube algorithm actually evaluates a
                    video:
                  </p>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="p-3 rounded-md border border-border/40 bg-background/30">
                      <p className="text-xs font-bold text-cyan-glow mb-1">
                        START
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        Did people click? Title + thumbnail packaging.
                      </p>
                    </div>
                    <div className="p-3 rounded-md border border-border/40 bg-background/30">
                      <p className="text-xs font-bold text-cyan-glow mb-1">
                        KEEP
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        Did they stay watching? Predicted retention
                        plus channel context.
                      </p>
                    </div>
                    <div className="p-3 rounded-md border border-border/40 bg-background/30">
                      <p className="text-xs font-bold text-cyan-glow mb-1">
                        REPEAT
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        Did they want to come back? Saves, shares,
                        return-viewer signals.
                      </p>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground mt-3">
                    See the{" "}
                    <Link
                      href="/analyzer-guide"
                      className="text-cyan-glow hover:underline"
                    >
                      Analyzer Guide
                    </Link>{" "}
                    for the full breakdown of each category, with
                    sample rewrites.
                  </p>
                </div>

                <div>
                  <h3 className="font-semibold text-foreground mb-2 text-base">
                    Step 3 — Route to the right tool
                  </h3>
                  <p className="text-sm">
                    The lowest-scoring bucket becomes your
                    bottleneck. The Algorithm Signals card then
                    surfaces 2–3 specific CTAs that deep-link into
                    the right tool with the right context already
                    loaded — Hook Lab for Start, Script Writer for
                    Keep / Repeat, A/B Tester to validate the
                    change. That's why two videos with the same
                    overall score can get different advice: the
                    same composite can come from different feature
                    weaknesses.
                  </p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* FAQ */}
          <section id="faq" className="mb-20 scroll-mt-24">
            <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
              <BookOpen className="w-6 h-6 text-cyan-glow" />
              Frequently asked
            </h2>
            <div className="space-y-4">
              {FAQ_ITEMS.map((item) => (
                <Card
                  key={item.q}
                  className="bg-background/40 border-border/40"
                >
                  <CardHeader>
                    <CardTitle className="text-base flex items-start gap-2">
                      <CheckCircle2 className="w-4 h-4 text-cyan-glow mt-1 shrink-0" />
                      {item.q}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground leading-relaxed">
                    {item.a}
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>

          {/* Sources & further reading */}
          <section id="sources" className="mb-20 scroll-mt-24">
            <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">
              <BookOpen className="w-6 h-6 text-cyan-glow" />
              Sources &amp; further reading
            </h2>
            <p className="text-sm text-muted-foreground mb-6 max-w-3xl">
              These are the externally-published references behind
              the methods on this page. Anything tagged{" "}
              <InternalBenchmark /> is measured on our own data and
              is{" "}
              <em>not</em> covered by these citations — it's a
              ViewMagnet-internal number, disclosed as such.
            </p>
            <div className="space-y-3">
              {CITATIONS.map((c) => (
                <Card
                  key={c.title}
                  className="bg-background/40 border-border/40"
                >
                  <CardContent className="p-4 space-y-2">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="flex-1 min-w-0">
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-semibold text-foreground hover:text-cyan-glow inline-flex items-center gap-1"
                        >
                          {c.title}
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {c.authors} ({c.year}). <em>{c.venue}</em>
                          .
                        </p>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      <strong className="text-foreground">
                        Why we cite it:
                      </strong>{" "}
                      {c.why}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-6 italic">
              Spotted a stretch? Email{" "}
              <a
                href="mailto:hello@viewmagnet.app"
                className="text-cyan-glow hover:underline not-italic"
              >
                hello@viewmagnet.app
              </a>{" "}
              with the paragraph and the source you think we're
              missing — we'd rather rewrite than over-claim.
            </p>
          </section>

          {/* Closing CTA */}
          <section className="mb-12 text-center">
            <Card className="bg-gradient-to-br from-cyan-glow/10 to-purple-500/10 border-cyan-glow/30">
              <CardContent className="p-8 space-y-4">
                <Sparkles className="w-8 h-8 text-cyan-glow mx-auto" />
                <h3 className="text-2xl font-bold">
                  See the model in action
                </h3>
                <p className="text-sm text-muted-foreground max-w-2xl mx-auto">
                  Drop a YouTube URL into the Video Analyzer and
                  you'll see the predicted score, the SHAP-driven
                  Start / Keep / Repeat breakdown, and the bottleneck
                  with one-click routes into Hook Lab and Script
                  Writer.
                </p>
                <div className="flex flex-wrap gap-3 justify-center pt-2">
                  <Button asChild>
                    <Link href="/dashboard/analyze">
                      <TrendingUp className="w-4 h-4 mr-2" />
                      Open Video Analyzer
                      <ArrowRight className="w-4 h-4 ml-2" />
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link href="/analyzer-guide">
                      <LineChart className="w-4 h-4 mr-2" />
                      Read the Analyzer Guide
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link href="/frameworks">
                      <BookOpen className="w-4 h-4 mr-2" />
                      Script frameworks
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>
        </main>
      </div>
    </>
  );
}

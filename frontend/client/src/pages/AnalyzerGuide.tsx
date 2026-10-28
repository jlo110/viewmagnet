/**
 * /analyzer-guide — public marketing + reference page that defines
 * the Start / Keep / Repeat algorithm signals ViewMagnet uses in
 * the Video Analyzer, with sample weak vs. strong rewrites.
 *
 * Why this page exists:
 *
 *  - The Video Analyzer surfaces a "bottleneck" (Start / Keep /
 *    Repeat / balanced) on every analysis, but the in-product
 *    explanation is one sentence — not enough for a creator who's
 *    seeing the framework for the first time.
 *  - The recommendation CTAs (Hook Lab, Script Writer) deep-link
 *    with a ``reason=start_bottleneck`` query param that surfaces
 *    in the destination tool. This page is the canonical place to
 *    point at when someone asks "what's a Start bottleneck?".
 *  - We want a single citable URL for the FAQ, footer, and the
 *    Analyzer's "Learn more" link.
 *
 * Source of truth for the bottleneck logic and copy:
 *   - ``src/features/llm_analyzer.py::compute_bottleneck()`` —
 *     weights for start_score, keep_score, repeat_score.
 *   - ``src/features/llm_analyzer.py`` bottleneck_messages dict.
 *
 * If those messages or weights change, update the bottleneck cards
 * below so the in-product UI and this public page agree.
 */
import { Link } from "wouter";
import type { ComponentType } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  ExternalLink,
  Eye,
  FlaskConical,
  Magnet,
  MousePointerClick,
  Play,
  Sparkles,
  Target,
  TrendingUp,
  Users,
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
// Bottleneck definitions
// ---------------------------------------------------------------------------

type BottleneckRewrite = {
  weak: string;
  strong: string;
  why: string;
};

type Bottleneck = {
  slug: "start" | "keep" | "repeat";
  name: string;
  shortQuestion: string;
  icon: ComponentType<{ className?: string }>;
  diagnosis: string;
  symptoms: string[];
  fixSummary: string;
  tools: Array<{ label: string; href: string; reason: string }>;
  rewrites: BottleneckRewrite[];
};

const BOTTLENECKS: Bottleneck[] = [
  {
    slug: "start",
    name: "Start bottleneck",
    shortQuestion: "Did people click to start watching?",
    icon: MousePointerClick,
    diagnosis:
      "Your title and thumbnail aren't earning enough clicks. Even great content can't reach an audience if nobody clicks. Fix the packaging before anything else — every other improvement is downstream of impressions converting to views.",
    symptoms: [
      "CTR (click-through rate) noticeably below your channel's typical baseline",
      "Strong retention on the few people who do click — they like the content, you just aren't getting them in the door",
      'Thumbnail is "competent" but blends in (similar palette, no obvious focal point, words a viewer has seen 100 times)',
      "Title summarizes the video rather than opening a curiosity gap",
    ],
    fixSummary:
      "Rewrite the hook so it opens a gap the viewer needs to close. Make the thumbnail readable at 2cm. Validate with the A/B Tester before committing.",
    tools: [
      {
        label: "Engineer a stronger hook in Hook Lab",
        href: "/dashboard/titles?tab=hooks",
        reason: "start_bottleneck",
      },
      {
        label: "Generate title + thumbnail variants",
        href: "/dashboard/titles",
        reason: "start_bottleneck",
      },
      {
        label: "A/B Test the packaging",
        href: "/dashboard/ab-test",
        reason: "start_bottleneck",
      },
    ],
    rewrites: [
      {
        weak: "Here are 3 tips to grow your Instagram",
        strong:
          "Stop posting Reels until you've fixed the mistake 87% of new accounts make in their first week",
        why: "Strong version converts a generic tip-list into a mistake callout — viewer can't tell if they're making the mistake without watching.",
      },
      {
        weak: "How I edit my YouTube videos",
        strong:
          "I used to spend 6 hours editing one video. Then I cut 5 things from my workflow — same retention, 90 minutes total",
        why: "Strong version anchors specificity (6 hours → 90 minutes) and creates an open loop (which 5 things?).",
      },
      {
        weak: "Marketing strategies for 2026",
        strong:
          "Every marketing playbook from 2024 is obsolete. Here are the 3 plays still working in Q2 2026 (and the one that just broke)",
        why: "Strong version uses stake reversal (the things you've been doing are wrong) plus belief destruction, which both consistently outperform summary hooks.",
      },
    ],
  },
  {
    slug: "keep",
    name: "Keep bottleneck",
    shortQuestion: "Did they stay watching after they clicked?",
    icon: Eye,
    diagnosis:
      "Viewers click but drop off early. The hook is doing its job — the body of the video is losing them. Usually that's pacing, structure, or a hook that over-promises and doesn't pay off in the first 30 seconds.",
    symptoms: [
      "CTR is healthy but Average View Duration is well below the platform's typical retention for the length bucket",
      "Sharp drop-off in the first 15–30 seconds (the 'they clicked but bounced' shape) — folk-wisdom rule of thumb from creator-side analysis, not a peer-reviewed claim",
      "Long monologues without re-anchoring curiosity",
      "Hook promises something the video buries 4 minutes in",
    ],
    fixSummary:
      "Tighten the hook → payoff loop. Use the Progressive Debunking framework to keep viewers expecting the next revelation. Cut dead air. Re-anchor curiosity every 15–30 seconds.",
    tools: [
      {
        label: "Use Progressive Debunking framework",
        href: "/dashboard/scripts?tab=frameworks&framework=progressive_debunking",
        reason: "keep_bottleneck",
      },
      {
        label: "Score your hook in Hook Lab",
        href: "/dashboard/titles?tab=hooks",
        reason: "keep_bottleneck",
      },
      {
        label: "Design a retention loop",
        href: "/dashboard/loop-designer",
        reason: "keep_bottleneck",
      },
    ],
    rewrites: [
      {
        weak:
          "Open: 'Today I'm going to show you 5 tips. Tip #1 is...' — single linear list, no loop.",
        strong:
          "Open: 'There are 5 reasons your videos plateau. The 4th one is what almost every YouTuber gets wrong — we'll get there in 2 minutes.' Then deliver 1, 2, 3 with a tease back to #4 before each one.",
        why: "Strong version creates a forward-pointing curiosity loop — viewers stay watching specifically to hear #4.",
      },
      {
        weak:
          "Open with a long personal anecdote before the value lands at 1:30.",
        strong:
          "Open with the single most counterintuitive insight in the video, THEN give the anecdote that earned it.",
        why: "Strong version puts payoff in the first 10 seconds, which is when retention curves typically inflect.",
      },
    ],
  },
  {
    slug: "repeat",
    name: "Repeat bottleneck",
    shortQuestion: "Did they want to come back?",
    icon: Magnet,
    diagnosis:
      "Viewers watch once but don't save, share, or come back for the next upload. The video delivers in the moment but doesn't earn long-term attention. Usually that's because the content doesn't crystallise into something the viewer wants to bookmark or pass along.",
    symptoms: [
      "Saves and shares are low relative to view count",
      "Return-viewer rate (followers who come back for the next upload) trending down",
      "Comments are generic ('nice video!') rather than reaction-driven",
      "Content has no named, repeatable structure the viewer can hold onto",
    ],
    fixSummary:
      "Add named systems (give your method a name viewers can search later). Build in clear lead-magnet payoffs. Use the Lead Magnet or Authority Myth-Buster framework — both engineer saves and shares.",
    tools: [
      {
        label: "Use Lead Magnet framework",
        href: "/dashboard/scripts?tab=frameworks&framework=hype_heit",
        reason: "repeat_bottleneck",
      },
      {
        label: "Use Authority Myth-Buster framework",
        href: "/dashboard/scripts?tab=frameworks&framework=authority_myth_buster",
        reason: "repeat_bottleneck",
      },
      {
        label: "Use Delta Shift framework (highest save rate)",
        href: "/dashboard/scripts?tab=frameworks&framework=delta_shift",
        reason: "repeat_bottleneck",
      },
    ],
    rewrites: [
      {
        weak: "Generic 'follow for more tips' end-card.",
        strong:
          "Name the system and give it a keyword CTA: 'I call this the 3-Block method. Comment BLOCK and I'll DM you the template.' Now the system has a memorable name and the save → DM loop earns the lead.",
        why: "Strong version turns a forgettable end-card into a named asset viewers can search for and re-share.",
      },
      {
        weak: "Restate the conclusion in a different way at the end.",
        strong:
          "End with the single counterintuitive insight as a one-line takeaway viewers can screenshot and share — and tease the next video as a direct extension.",
        why: "Strong version engineers the screenshot / DM loop, which is the actual mechanic behind a high save rate.",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Citations & creator sources
//
// Two separate lists on purpose:
//
//  * ``ACADEMIC_CITATIONS`` are peer-reviewed papers / canonical
//    textbooks. The psychology behind the hook-as-curiosity-gap
//    mechanic, the share/save behavior, and the loss-aversion
//    framing of "stake reversal" all have real, externally
//    verifiable references — those go here.
//
//  * ``CREATOR_SOURCES`` are creator-economy writeups, podcast
//    transcripts, and platform blog posts that originated the
//    framework taxonomy and the platform-side folk wisdom about
//    retention curves. They aren't peer-reviewed but they're the
//    honest provenance of the language we use. Calling them out
//    separately keeps the academic list clean and signals to
//    readers which class of source they're looking at.
//
// Rule for adding entries: every item must have a real working
// URL or DOI. No invented citations. If the only source is a
// tweet or a deleted YouTube video, leave it out.
// ---------------------------------------------------------------------------

type Citation = {
  authors: string;
  year: string;
  title: string;
  venue: string;
  url: string;
  why: string;
};

const ACADEMIC_CITATIONS: Citation[] = [
  {
    authors: "Loewenstein, G.",
    year: "1994",
    title: "The Psychology of Curiosity: A Review and Reinterpretation",
    venue: "Psychological Bulletin, 116(1)",
    url: "https://doi.org/10.1037/0033-2909.116.1.75",
    why: "The foundational 'information gap' paper. Every Hook Lab rewrite operationalizes this: the strong version opens a gap the viewer needs to close.",
  },
  {
    authors: "Berger, J. & Milkman, K. L.",
    year: "2012",
    title: "What Makes Online Content Viral?",
    venue: "Journal of Marketing Research, 49(2)",
    url: "https://doi.org/10.1509/jmr.10.0353",
    why: "Empirical work showing that high-arousal emotion (awe, anger, anxiety, amusement) predicts sharing better than valence. Backs the Repeat-bottleneck advice to engineer shareable insights instead of neutral summaries.",
  },
  {
    authors: "Kahneman, D. & Tversky, A.",
    year: "1979",
    title:
      "Prospect Theory: An Analysis of Decision under Risk",
    venue: "Econometrica, 47(2)",
    url: "https://doi.org/10.2307/1914185",
    why: "Loss aversion — losses are felt roughly 2× as strongly as equivalent gains. The 'stake reversal' rewrite pattern (the things you're doing are actively losing you views) leans on this directly.",
  },
  {
    authors: "Schindler, R. M. & Yalch, R.",
    year: "2006",
    title:
      "It Seems Factual, But Is It? Effects of Using Sharp versus Round Numbers in Advertising Claims",
    venue: "Advances in Consumer Research, Vol. 33",
    url: "https://www.acrwebsite.org/volumes/12390/volumes/v33/NA-33",
    why: "Precise numbers ('cut 5 things from my workflow', '90 minutes total') outperform round ones in perceived credibility — the empirical basis for the specificity rewrites in this guide.",
  },
  {
    authors: "Berger, J.",
    year: "2013",
    title: "Contagious: Why Things Catch On (Chapter 4 — Practical Value)",
    venue: "Simon & Schuster",
    url: "https://jonahberger.com/books/contagious/",
    why: "Practical-value content (named systems, repeatable methods, screenshot-worthy frameworks) gets saved and shared at much higher rates — the empirical case behind the Lead Magnet and Delta Shift framework advice.",
  },
];

const CREATOR_SOURCES: Citation[] = [
  {
    authors: "Girbu, C.",
    year: "2024",
    title: "The 4 viral script frameworks",
    venue: "Public framework breakdown",
    url: "https://www.chrisgirbu.com/",
    why: "Origin of the Authority Myth-Buster / Delta Shift / Progressive Debunking / Lead Magnet taxonomy. ViewMagnet adapts the system; the framework names are his.",
  },
  {
    authors: "Galloway, P.",
    year: "Various",
    title: "Retention-curve & packaging breakdowns",
    venue: "Paddy Galloway newsletter + YouTube",
    url: "https://www.paddygalloway.com/",
    why: "Reference point for the platform-side observation that the first 10–30 seconds is where retention curves typically inflect. Treated as folk wisdom rather than academic claim.",
  },
  {
    authors: "Kane, B.",
    year: "2020",
    title: "Hook Point: How to Stand Out in a 3-Second World",
    venue: "Waterside Productions",
    url: "https://hookpoint.com/",
    why: "Heritage for the strong-vs-weak hook taxonomy (mistake callouts, belief destruction, stake reversal). Hook Lab's six-type system overlaps with the categories laid out here.",
  },
  {
    authors: "YouTube Creator Insider",
    year: "Various",
    title: "Algorithm & retention guidance",
    venue: "YouTube's official creator channel",
    url: "https://www.youtube.com/@YouTubeCreators",
    why: "Platform-side observations about CTR + AVD as the two strongest reach signals, and saves/shares as the strongest return-viewer signal. Source for the Start / Keep / Repeat factoring (our naming, their underlying signals).",
  },
];

// ---------------------------------------------------------------------------
// Small reusable bits
// ---------------------------------------------------------------------------

/**
 * Same pill component as /methodology — flags any claim that is
 * a ViewMagnet-internal measurement rather than an externally
 * validated number. Duplicated rather than imported to keep each
 * marketing page self-contained.
 */
function InternalBenchmark() {
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-amber-glow/30 bg-amber-glow/5 text-[10px] font-medium text-amber-glow"
      title="This number is measured on our own internal data, not from an externally published benchmark."
    >
      <FlaskConical className="w-3 h-3" />
      Internal benchmark
    </span>
  );
}

function CitationCard({ c }: { c: Citation }) {
  return (
    <Card className="bg-background/40 border-border/40">
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
              {c.authors} ({c.year}). <em>{c.venue}</em>.
            </p>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          <strong className="text-foreground">Why we cite it:</strong>{" "}
          {c.why}
        </p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AnalyzerGuidePage() {
  return (
    <>
      <SEOHead
        title="Analyzer Guide: Start / Keep / Repeat bottlenecks explained"
        description="What Start, Keep, and Repeat bottlenecks mean in ViewMagnet's Video Analyzer — diagnosis, symptoms, and weak-vs-strong rewrites for each."
        canonicalUrl="/analyzer-guide"
        ogType="article"
        keywords="YouTube algorithm signals, click-through rate, average view duration, video retention, hook rewrites, video bottleneck analysis, YouTube growth diagnosis"
        markdownUrl="/analyzer-guide.md"
        article={{
          publishedTime: "2026-05-23",
          modifiedTime: "2026-05-24",
          author: "ViewMagnet",
          tags: [
            "YouTube algorithm",
            "retention",
            "click-through rate",
            "video hooks",
            "creator strategy",
          ],
        }}
      />
      <StructuredData
        type="article"
        headline="Analyzer Guide: Start / Keep / Repeat bottlenecks"
        description="A plain-English walk-through of ViewMagnet's three algorithm signals, with sample rewrites for each."
        datePublished="2026-05-23"
        dateModified="2026-05-24"
        author="ViewMagnet"
        url="/analyzer-guide"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "Analyzer Guide", url: "/analyzer-guide" },
        ]}
      />
      {/* HowTo schema. The three bottleneck remedies are a
          natural fit — generative engines treat HowTo as one of
          the highest-confidence "show step-by-step" formats. We
          collapse each bottleneck into a single step rather than
          per-rewrite so the schema stays under the practical
          step-count Google's parser cares about. */}
      <StructuredData
        type="howTo"
        name="How to fix a YouTube video's bottleneck"
        description="Diagnose whether your video's bottleneck is Start (clicks), Keep (retention), or Repeat (saves &amp; shares), and apply the right rewrite pattern."
        totalTime="PT15M"
        steps={BOTTLENECKS.map((b) => ({
          name: `Fix the ${b.name}`,
          text: `${b.diagnosis} ${b.fixSummary}`,
          url: `/analyzer-guide#${b.slug}`,
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
              Analyzer Guide
            </Badge>
            <h1 className="text-4xl md:text-5xl font-bold mb-4 tracking-tight">
              Start. Keep. Repeat.
            </h1>
            <p className="text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed">
              Every video on every platform competes on the same
              three questions. ViewMagnet's Video Analyzer scores
              each one separately and tells you which one is your
              bottleneck. Here's what each score means — and how to
              fix it.
            </p>

            <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl mx-auto">
              {BOTTLENECKS.map((b) => {
                const Icon = b.icon;
                return (
                  <a
                    key={b.slug}
                    href={`#${b.slug}`}
                    className="group p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors text-left bg-background/30"
                  >
                    <Icon className="w-5 h-5 text-cyan-glow mb-2" />
                    <p className="text-sm font-semibold text-foreground group-hover:text-cyan-glow transition-colors">
                      {b.name}
                    </p>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      {b.shortQuestion}
                    </p>
                  </a>
                );
              })}
            </div>
          </section>

          {/* The framework */}
          <section className="mb-20">
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-cyan-glow" />
                  Why Start / Keep / Repeat?
                </CardTitle>
                <CardDescription>
                  The YouTube algorithm (and every short-form
                  algorithm) approximates these three questions
                  with different signals. Improving the wrong one
                  doesn't move the needle — that's why a single
                  composite score isn't enough.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm leading-relaxed">
                <p>
                  Every video on every platform competes on the
                  same three questions:
                </p>
                <ul className="space-y-3">
                  <li className="flex items-start gap-3">
                    <MousePointerClick className="w-5 h-5 text-cyan-glow shrink-0 mt-0.5" />
                    <div>
                      <strong className="text-foreground">START.</strong>{" "}
                      Did people click to watch? — Title +
                      thumbnail packaging.
                    </div>
                  </li>
                  <li className="flex items-start gap-3">
                    <Eye className="w-5 h-5 text-cyan-glow shrink-0 mt-0.5" />
                    <div>
                      <strong className="text-foreground">KEEP.</strong>{" "}
                      Did they stay watching? — Hook + pacing +
                      structure.
                    </div>
                  </li>
                  <li className="flex items-start gap-3">
                    <Magnet className="w-5 h-5 text-cyan-glow shrink-0 mt-0.5" />
                    <div>
                      <strong className="text-foreground">REPEAT.</strong>{" "}
                      Did they want to come back? — Saves, shares,
                      return-viewer signals.
                    </div>
                  </li>
                </ul>
                <p>
                  ViewMagnet scores all three (0–100) and surfaces
                  the lowest one as your <em>bottleneck</em>. The
                  reasoning is that improving the bottleneck has the
                  highest leverage — you don't fix Start by writing
                  better scripts, and you don't fix Repeat by
                  changing the thumbnail.
                </p>
                <p className="text-xs text-muted-foreground">
                  Want the math? The composite weights and SHAP-
                  derived feature attribution are described in the{" "}
                  <Link
                    href="/methodology"
                    className="text-cyan-glow hover:underline"
                  >
                    Methodology page
                  </Link>
                  .
                </p>
              </CardContent>
            </Card>
          </section>

          {/* Per-bottleneck deep-dive */}
          {BOTTLENECKS.map((b) => {
            const Icon = b.icon;
            return (
              <section
                key={b.slug}
                id={b.slug}
                className="mb-20 scroll-mt-24"
              >
                <Card className="bg-background/40 border-border/40">
                  <CardHeader>
                    <div className="flex items-center gap-3 mb-2">
                      <div className="w-12 h-12 rounded-lg bg-cyan-glow/10 border border-cyan-glow/30 flex items-center justify-center shrink-0">
                        <Icon className="w-6 h-6 text-cyan-glow" />
                      </div>
                      <div>
                        <CardTitle className="text-2xl">
                          {b.name}
                        </CardTitle>
                        <CardDescription className="text-base">
                          {b.shortQuestion}
                        </CardDescription>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-6 text-sm leading-relaxed">
                    {/* Diagnosis */}
                    <div>
                      <h3 className="font-semibold text-foreground mb-2 text-base">
                        Diagnosis
                      </h3>
                      <p>{b.diagnosis}</p>
                    </div>

                    {/* Symptoms */}
                    <div>
                      <h3 className="font-semibold text-foreground mb-2 text-base">
                        Symptoms (what you'll see in your analytics)
                      </h3>
                      <ul className="list-disc pl-6 space-y-1.5">
                        {b.symptoms.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Fix summary */}
                    <div className="rounded-md border border-cyan-glow/30 bg-cyan-glow/5 p-4">
                      <p className="text-xs font-semibold text-cyan-glow mb-1 flex items-center gap-2">
                        <Sparkles className="w-4 h-4" />
                        How to fix it
                      </p>
                      <p className="text-sm text-foreground">
                        {b.fixSummary}
                      </p>
                    </div>

                    {/* Tools */}
                    <div>
                      <h3 className="font-semibold text-foreground mb-2 text-base">
                        Tools that target this bottleneck
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {b.tools.map((t) => (
                          <Button
                            key={t.href + t.label}
                            asChild
                            size="sm"
                            variant="outline"
                            className="border-cyan-glow/30 text-cyan-glow hover:bg-cyan-glow/10"
                          >
                            <Link href={t.href}>
                              <Play className="w-3 h-3 mr-2" />
                              {t.label}
                            </Link>
                          </Button>
                        ))}
                      </div>
                    </div>

                    {/* Rewrites */}
                    <div>
                      <h3 className="font-semibold text-foreground mb-3 text-base">
                        Weak → strong rewrites
                      </h3>
                      <div className="space-y-3">
                        {b.rewrites.map((r, i) => (
                          <div
                            key={i}
                            className="rounded-md border border-border/40 bg-background/30 p-4 space-y-3"
                          >
                            <div>
                              <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
                                Weak
                              </p>
                              <p className="text-sm text-foreground/80 italic">
                                "{r.weak}"
                              </p>
                            </div>
                            <div>
                              <p className="text-[11px] uppercase tracking-wide text-cyan-glow mb-1">
                                Strong
                              </p>
                              <p className="text-sm text-foreground">
                                "{r.strong}"
                              </p>
                            </div>
                            <p className="text-xs text-muted-foreground border-t border-border/30 pt-3">
                              <strong className="text-foreground">
                                Why:
                              </strong>{" "}
                              {r.why}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </section>
            );
          })}

          {/* "Balanced" note */}
          <section className="mb-20">
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-cyan-glow" />
                  What if my video is "balanced"?
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed space-y-3">
                <p>
                  When Start, Keep, and Repeat are all within ~8
                  points of each other the Analyzer labels the
                  video <em>balanced</em>. That doesn't mean
                  "great" — it means there isn't a single weak link
                  to break. The strategy here is different: pick
                  the lowest of the three and try to lift it
                  meaningfully, even by 5–10 points. Once one
                  becomes a clear leader you'll have a new lowest,
                  which then becomes the next bottleneck to attack.
                </p>
                <p>
                  Balanced videos in the 70+ band are typically
                  high-performers. Balanced videos in the 40–60
                  band usually need a structural rebuild rather
                  than a tactical fix — the right move is to
                  re-shoot the video with a different framework
                  rather than to optimise one signal at a time.
                </p>
              </CardContent>
            </Card>
          </section>

          {/* Sources */}
          <section id="sources" className="mb-20 scroll-mt-24">
            <h2 className="text-2xl font-bold mb-2 flex items-center gap-2">
              <BookOpen className="w-6 h-6 text-cyan-glow" />
              Sources &amp; further reading
            </h2>
            <p className="text-sm text-muted-foreground mb-6 max-w-3xl">
              The psychology backing the rewrite patterns and
              hook-type advice on this page is real and published.
              The platform-side observations about retention curves
              and saves come from creator-economy sources rather
              than peer-reviewed work — listed separately so you
              can tell which is which. Anything tagged{" "}
              <InternalBenchmark /> is measured on our own data
              and not externally validated.
            </p>

            <h3 className="text-base font-semibold text-foreground mb-3 flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-cyan-glow" />
              Peer-reviewed &amp; canonical
            </h3>
            <div className="space-y-3 mb-8">
              {ACADEMIC_CITATIONS.map((c) => (
                <CitationCard key={c.title} c={c} />
              ))}
            </div>

            <h3 className="text-base font-semibold text-foreground mb-3 flex items-center gap-2">
              <Users className="w-4 h-4 text-cyan-glow" />
              Creator-economy &amp; platform sources
            </h3>
            <p className="text-xs text-muted-foreground mb-3">
              Not peer-reviewed, but the honest provenance of the
              framework taxonomy and the platform-side intuitions
              we restate. Listed so you can judge the source
              instead of taking our word for it.
            </p>
            <div className="space-y-3">
              {CREATOR_SOURCES.map((c) => (
                <CitationCard key={c.title} c={c} />
              ))}
            </div>

            <p className="text-xs text-muted-foreground mt-6 italic">
              Think we're misrepresenting one of these sources?
              Email{" "}
              <a
                href="mailto:hello@viewmagnet.app"
                className="text-cyan-glow hover:underline not-italic"
              >
                hello@viewmagnet.app
              </a>{" "}
              with the paragraph and we'll fix it.
            </p>
          </section>

          {/* Closing CTA */}
          <section className="mb-12 text-center">
            <Card className="bg-gradient-to-br from-cyan-glow/10 to-purple-500/10 border-cyan-glow/30">
              <CardContent className="p-8 space-y-4">
                <Sparkles className="w-8 h-8 text-cyan-glow mx-auto" />
                <h3 className="text-2xl font-bold">
                  Want to see your bottleneck?
                </h3>
                <p className="text-sm text-muted-foreground max-w-2xl mx-auto">
                  Drop any YouTube URL into the Video Analyzer.
                  You'll get a Start / Keep / Repeat breakdown plus
                  routed recommendations into Hook Lab and Script
                  Writer with the right framework already loaded.
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
                    <Link href="/frameworks">
                      <BookOpen className="w-4 h-4 mr-2" />
                      The 4 script frameworks
                    </Link>
                  </Button>
                  <Button variant="outline" asChild>
                    <Link href="/methodology">
                      <Sparkles className="w-4 h-4 mr-2" />
                      How the model works
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

/**
 * /frameworks — public marketing page that defines ViewMagnet's
 * 4 viral script frameworks.
 *
 * Why this page exists (beyond SEO):
 *
 *  - The recommendation engine (Algorithm Signals, Hook Lab, the
 *    Analyzer) routinely tells users to "try the Lead Magnet
 *    framework" or "try Authority Myth-Buster". Without a public
 *    definition page, a user who clicks one of those CTAs has no
 *    context for what they're being asked to use until they're
 *    already inside the Script Writer.
 *  - We want a single, citable URL we can link from in-product
 *    tooltips, blog posts, and onboarding without having to repeat
 *    the explanation in every surface.
 *  - The credibility of the "engineered virality" pitch depends on
 *    the framework system being shown, not just named.
 *
 * Data source of truth: the framework names + section labels here
 * mirror ``src/features/script_writer.py::FRAMEWORK_TEMPLATES``.
 * If you rename or restructure a framework in the backend, update
 * the matching ``FRAMEWORKS`` entry below — keeping these aligned
 * matters because users who land here and then click into the
 * Script Writer should see the same labels both places.
 *
 * Attribution: the four-framework system is adapted from creator
 * Chris Girbu's published framework breakdown. We credit him in the
 * page footer so the methodology section reads honestly instead of
 * implicitly claiming the system as our own.
 */
import { Link } from "wouter";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Crosshair,
  FileText,
  Flame,
  Layers,
  Magnet,
  Repeat,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import type { ComponentType } from "react";

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
// Framework definitions
//
// Mirror of ``src/features/script_writer.py::FRAMEWORK_TEMPLATES`` —
// kept inline rather than fetched from the API because (a) this is a
// public page that should render before any auth roundtrip and (b)
// the framework set changes rarely enough that a hardcoded mirror is
// cheaper than a public endpoint.
// ---------------------------------------------------------------------------

type FrameworkSection = {
  label: string;
  description: string;
};

type Framework = {
  /** Internal slug — matches the Script Writer URL parameter so
   *  ``/dashboard/scripts?tab=frameworks&framework=<slug>`` deep
   *  links work directly from the "Try in Script Writer" CTAs. */
  slug: string;
  name: string;
  tagline: string;
  primaryGoal: string;
  goalDescription: string;
  bestFor: string;
  icon: ComponentType<{ className?: string }>;
  gradient: string;
  sections: FrameworkSection[];
  /** A short example that makes the framework concrete. We keep
   *  these niche-agnostic on purpose so a creator in any vertical
   *  can imagine adapting them. */
  example: string;
};

// ---------------------------------------------------------------------------
// Hook type definitions
//
// Mirror of ``src/features/hook_lab.py::HookType`` +
// ``HOOK_TYPE_DESCRIPTIONS``. These are the labels users see in the
// Hook Lab dropdown (Mistake Callout, Belief Destruction, Authority
// Anchor, Stake Reversal, Specificity Hook) — without a public
// definition the dropdown looks like a list of cryptic jargon. We
// pair each type with a "weak version" / "strong version" example
// so creators can see the upgrade move in context.
//
// Order matters: "Summary" is intentionally first as the
// anti-pattern (Hook Lab classifies it as WEAK), then the five
// strong types follow in roughly the order the Hook Lab rewrites
// will reach for them.
// ---------------------------------------------------------------------------

type HookType = {
  /** Internal slug from the backend enum — matches the dropdown
   *  value in Hook Lab. */
  slug: string;
  name: string;
  strength: "weak" | "strong";
  icon: ComponentType<{ className?: string }>;
  /** One-sentence definition (what it does to the viewer's brain). */
  definition: string;
  /** A flat-summary version of the same idea — the version a hook
   *  generally STARTS as. */
  weakExample: string;
  /** The upgraded version after applying this hook type. */
  strongExample: string;
};

const HOOK_TYPES: HookType[] = [
  {
    slug: "summary",
    name: "Summary",
    strength: "weak",
    icon: FileText,
    definition:
      "Just announces what the video covers. Doesn't open a gap, doesn't make the viewer feel anything is at stake — so the scroll wins.",
    weakExample: "Here are 3 tips to grow your Instagram.",
    strongExample:
      "(Hook Lab flags this as Summary and offers a rewrite into one of the strong types below.)",
  },
  {
    slug: "mistake_callout",
    name: "Mistake Callout",
    strength: "strong",
    icon: AlertTriangle,
    definition:
      "Accuses the viewer (specifically) of doing something wrong. Triggers the 'wait, is that me?' loop — the viewer can't keep scrolling until they know.",
    weakExample: "Here's how to post reels better.",
    strongExample:
      "You've been posting reels wrong — and here's the proof.",
  },
  {
    slug: "belief_destruction",
    name: "Belief Destruction",
    strength: "strong",
    icon: Flame,
    definition:
      "Attacks a thing the viewer believes is true. Forces them to either defend their belief (engagement) or stay to find out if they've been wrong (watch time).",
    weakExample: "The best time to post is important.",
    strongExample:
      "Posting times don't matter. Here's what actually does.",
  },
  {
    slug: "authority_anchor",
    name: "Authority Anchor",
    strength: "strong",
    icon: Shield,
    definition:
      "Front-loads your credentials so the contrarian take that follows lands as 'expert insight' instead of 'random opinion'. Best paired with a Belief Destruction or Mistake Callout right after.",
    weakExample: "Most creators chase trends.",
    strongExample:
      "I've generated 8B views across 60+ industries — and here's why chasing trends is killing your channel.",
  },
  {
    slug: "stake_reversal",
    name: "Stake Reversal",
    strength: "strong",
    icon: Repeat,
    definition:
      "Tells the viewer to STOP doing the obvious thing and do the opposite instead. Inverts expectation — that surprise is what holds attention through the first 5 seconds.",
    weakExample: "You should batch your content.",
    strongExample: "Stop batching your content. Do this instead.",
  },
  {
    slug: "specificity",
    name: "Specificity Hook",
    strength: "strong",
    icon: Crosshair,
    definition:
      "Promises a NAMED, specific system or hidden asset. The named-thing makes it feel concrete instead of generic — and pairs naturally with the Lead Magnet framework's keyword-DM mechanic.",
    weakExample: "I have a method that works really well.",
    strongExample:
      "The CLEAR framework I use to write hooks — full template blurred on screen right now.",
  },
];

const FRAMEWORKS: Framework[] = [
  {
    slug: "authority_myth_buster",
    name: "Authority Myth-Buster",
    tagline: "Build trust fast with new audiences",
    primaryGoal: "Trust",
    goalDescription:
      "When your audience doesn't know who you are yet, you need to earn the right to be listened to in the first 18 seconds.",
    bestFor:
      "New audiences, cold reach, channels that need to anchor their authority before delivering value.",
    icon: Shield,
    gradient: "from-blue-500/20 to-cyan-glow/20",
    sections: [
      {
        label: "Contrarian Hook",
        description:
          "Open by challenging a widely-held belief in the niche. The viewer's first internal reaction should be 'wait, am I doing this wrong?'",
      },
      {
        label: "Authority Anchor",
        description:
          "Drop credentials within the first 15 seconds — what you've done, built, or measured that gives you the right to challenge that belief.",
      },
      {
        label: "3-Part Solution",
        description:
          "Three concrete, actionable points. Each builds on or contrasts the previous one. The third should be the most counterintuitive.",
      },
      {
        label: "Ideological CTA",
        description:
          "Belief-based call to action: 'If you believe X, follow for more.' This converts trust into followers, not just views.",
      },
    ],
    example:
      "\"Everyone tells you to post 3 times a week. I built a 2M-follower channel posting twice a month. Here's why frequency is killing your growth…\"",
  },
  {
    slug: "delta_shift",
    name: "Delta Shift",
    tagline: "The highest-save-rate format we measure",
    primaryGoal: "Saves",
    goalDescription:
      "Show the gap between what most people do and what the top 1% does. The contrast itself is what makes viewers hit save — 'I want to come back to this'.",
    bestFor:
      "Tactical content where the value is in a specific behavioral upgrade the viewer wants to remember.",
    icon: TrendingUp,
    gradient: "from-emerald-400/20 to-cyan-glow/20",
    sections: [
      {
        label: "Baseline",
        description:
          "Show what the AVERAGE person does. Be specific so the viewer self-identifies: 'Most creators post 3 times a week and…'",
      },
      {
        label: "Delta (the top 1% move)",
        description:
          "Reveal what the top 1% does instead. The contrast should be sharp and surprising — not a slight tweak.",
      },
      {
        label: "Single Takeaway",
        description:
          "ONE immediately actionable thing the viewer can apply today. Don't list five — five things never get implemented.",
      },
      {
        label: "Save CTA",
        description:
          "Direct prompt: 'Save this so you don't forget' or 'Send this to the creator friend who needs to hear it.'",
      },
    ],
    example:
      "\"Most YouTubers spend 4 hours writing titles. The top 1% spend 4 hours writing the first 3 seconds — here's the one move that doubled my CTR…\"",
  },
  {
    slug: "progressive_debunking",
    name: "Progressive Debunking (Iceberg)",
    tagline: "Engineered for maximum watch time",
    primaryGoal: "Retention",
    goalDescription:
      "Each revelation makes the previous one feel like the surface. The viewer keeps watching because the brain refuses to stop before the deepest layer.",
    bestFor:
      "Long-form content, deep dives, polarizing topics where the audience already has strong opinions you can progressively dismantle.",
    icon: Layers,
    gradient: "from-purple-500/20 to-amber-glow/20",
    sections: [
      {
        label: "Polarizing Topic",
        description:
          "Pick a hot debate in the niche and state the controversial topic upfront so the viewer commits to a side.",
      },
      {
        label: "Dismiss the Surface",
        description:
          "'Everyone obsesses over X. That's noise.' Dismiss the surface-level tactics — establishes that you're going somewhere deeper.",
      },
      {
        label: "Reveal Layer 1",
        description:
          "'The real mechanic is Y.' First deeper revelation — what people who've gone one level deeper already understand.",
      },
      {
        label: "Reveal Layer 2",
        description:
          "'But underneath that is Z.' Even deeper. This is what experts think about. By here, the viewer is locked in.",
      },
      {
        label: "Final Revelation",
        description:
          "The deepest truth — what only the top 0.1% understand. Make it feel like insider knowledge the viewer just earned.",
      },
      {
        label: "Loop Back",
        description:
          "End by referencing the polarizing topic from the hook so the viewer wants to rewatch with the new context — the loop is what pushes watch time above 100%.",
      },
    ],
    example:
      "\"Most creators think the algorithm rewards quality. They're wrong — it rewards watch behavior. But underneath that is what TikTok engineers call the 'completion lattice', and underneath THAT is the only signal that actually matters…\"",
  },
  {
    slug: "hype_heit",
    name: "Lead Magnet Framework",
    tagline: "Fills auto-DM funnels with keyword CTAs",
    primaryGoal: "Leads",
    goalDescription:
      "Promise a named system. Tease the deliverable on screen (blurred). Hand it over only when the viewer comments your keyword — which becomes an auto-DM trigger.",
    bestFor:
      "Creators with a product, service, or audience to build off-platform. Pure lead-gen mechanic — converts views into DMs into emails.",
    icon: Magnet,
    gradient: "from-amber-glow/20 to-pink-500/20",
    sections: [
      {
        label: "Named System Promise",
        description:
          "Promise a memorable, distinctive named method. The name doubles as the comment keyword later, so it has to be specific enough that 'comment X' won't pull in unrelated replies.",
      },
      {
        label: "Blurred Asset Tease",
        description:
          "Show the deliverable on screen, deliberately blurred. The visual proof that the asset exists is what pulls comments — words alone don't.",
      },
      {
        label: "Rapid Breakdown",
        description:
          "Three quick, punchy parts of the system. Just enough detail to validate that the full asset is worth getting. Hold back the actual playbook.",
      },
      {
        label: "Keyword CTA",
        description:
          "'Comment [SYSTEM-NAME] and I'll send it to you.' The same name from the opening — pattern-completes the whole script and triggers the auto-DM.",
      },
    ],
    example:
      "\"I built the CLEAR framework to write hooks that 10x'd my views. Full template is blurred on screen right now. Comment CLEAR and I'll DM it to you…\"",
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FrameworksPage() {
  return (
    <>
      <SEOHead
        title="The Frameworks & Hook Types behind ViewMagnet"
        description="The 4 viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet) and the 6 hook types (Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity) ViewMagnet uses to engineer videos for trust, saves, retention, and leads."
        canonicalUrl="/frameworks"
        ogType="article"
        keywords="viral script frameworks, YouTube script structure, hook types, Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet, mistake callout, belief destruction, stake reversal, specificity hook"
        markdownUrl="/frameworks.md"
        article={{
          publishedTime: "2026-05-23",
          modifiedTime: "2026-05-24",
          author: "ViewMagnet",
          tags: [
            "script frameworks",
            "viral content",
            "hook writing",
            "YouTube scripts",
            "creator strategy",
          ],
        }}
      />
      <StructuredData
        type="article"
        headline="The 4 Viral Script Frameworks"
        description="The four script frameworks ViewMagnet uses to engineer videos for trust, saves, retention, and leads."
        datePublished="2026-05-23"
        dateModified="2026-05-24"
        author="ViewMagnet"
        url="/frameworks"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "Script Frameworks", url: "/frameworks" },
        ]}
      />
      {/* ItemList for the four frameworks. Lets AI crawlers
          extract the framework set as structured data instead of
          scraping the DOM — especially useful for "what are the
          viral script frameworks?" generative queries. */}
      <StructuredData
        type="itemList"
        name="The 4 Viral Script Frameworks"
        description="The four script structures ViewMagnet uses to engineer videos for specific outcomes."
        items={FRAMEWORKS.map((fw) => ({
          name: fw.name,
          description: `${fw.primaryGoal} — ${fw.tagline}`,
          url: `/frameworks#${fw.slug}`,
        }))}
      />
      {/* Second ItemList for the six hook types. */}
      <StructuredData
        type="itemList"
        name="The 6 Hook Types"
        description="The six hook taxonomy categories ViewMagnet's Hook Lab classifies and rewrites against."
        items={HOOK_TYPES.map((ht) => ({
          name: ht.name,
          description: ht.definition,
          url: `/frameworks#hook-${ht.slug}`,
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
              The 4 Viral Script Frameworks
            </h1>
            <p className="text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed">
              Every script ViewMagnet generates is built on one of
              four frameworks — each engineered for a specific
              outcome the algorithm actually rewards.
            </p>

            <div className="mt-8 grid grid-cols-2 md:grid-cols-4 gap-3 max-w-3xl mx-auto">
              {FRAMEWORKS.map((fw) => {
                const Icon = fw.icon;
                return (
                  <a
                    key={fw.slug}
                    href={`#${fw.slug}`}
                    className="group p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors text-left bg-background/30"
                  >
                    <Icon className="w-5 h-5 text-cyan-glow mb-2" />
                    <p className="text-sm font-semibold text-foreground group-hover:text-cyan-glow transition-colors">
                      {fw.name}
                    </p>
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Best for {fw.primaryGoal.toLowerCase()}
                    </p>
                  </a>
                );
              })}
            </div>

            <p className="mt-6 text-sm text-muted-foreground">
              Looking for the hook-type definitions (Mistake Callout,
              Belief Destruction, etc.)?{" "}
              <a
                href="#hook-summary"
                className="text-cyan-glow hover:underline"
              >
                Jump to the 6 hook types →
              </a>
            </p>
          </section>

          {/* Why frameworks matter */}
          <section className="mb-20">
            <Card className="bg-background/40 border-border/40">
              <CardContent className="p-8 prose prose-invert max-w-none">
                <h2 className="text-2xl font-semibold mb-4">
                  Why frameworks?
                </h2>
                <p className="text-muted-foreground leading-relaxed mb-4">
                  Most creators think viral content is about quality.
                  Quality is necessary but not sufficient — the
                  algorithm rewards three mechanical signals: did
                  the viewer start watching, did they keep watching,
                  did they watch again. A framework is just a
                  repeatable structure that engineers all three.
                </p>
                <p className="text-muted-foreground leading-relaxed">
                  Each of the four below is optimized for a
                  different outcome. Picking the right one for the
                  job matters more than improvising — that's why
                  ViewMagnet's Script Writer asks you what you're
                  trying to do first, then writes against the
                  structure proven to deliver it.
                </p>
              </CardContent>
            </Card>
          </section>

          {/* Per-framework deep dives */}
          <section className="space-y-12 mb-20">
            {FRAMEWORKS.map((fw) => {
              const Icon = fw.icon;
              return (
                <Card
                  key={fw.slug}
                  id={fw.slug}
                  className={`bg-gradient-to-br ${fw.gradient} border-border/40 scroll-mt-24`}
                >
                  <CardHeader>
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-xl bg-background/40 flex items-center justify-center shrink-0">
                        <Icon className="w-6 h-6 text-foreground" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <CardTitle className="text-2xl">
                            {fw.name}
                          </CardTitle>
                          <Badge
                            variant="outline"
                            className="text-xs border-cyan-glow/40 text-cyan-glow"
                          >
                            {fw.primaryGoal}
                          </Badge>
                        </div>
                        <CardDescription className="text-base text-foreground/70">
                          {fw.tagline}
                        </CardDescription>
                      </div>
                    </div>
                  </CardHeader>

                  <CardContent className="space-y-6">
                    <div className="grid md:grid-cols-2 gap-6">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-cyan-glow mb-2">
                          What it's for
                        </p>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {fw.goalDescription}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-cyan-glow mb-2">
                          When to reach for it
                        </p>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {fw.bestFor}
                        </p>
                      </div>
                    </div>

                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-cyan-glow mb-3">
                        Structure
                      </p>
                      <ol className="space-y-2">
                        {fw.sections.map((section, idx) => (
                          <li
                            key={section.label}
                            className="flex gap-3 items-start"
                          >
                            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-background/50 text-xs font-bold flex items-center justify-center text-cyan-glow">
                              {idx + 1}
                            </span>
                            <div>
                              <p className="text-sm font-semibold text-foreground">
                                {section.label}
                              </p>
                              <p className="text-sm text-muted-foreground leading-relaxed">
                                {section.description}
                              </p>
                            </div>
                          </li>
                        ))}
                      </ol>
                    </div>

                    <div className="border-l-2 border-cyan-glow/40 pl-4 italic">
                      <p className="text-xs font-semibold uppercase tracking-wider text-cyan-glow/70 mb-1 not-italic">
                        Example opening
                      </p>
                      <p className="text-sm text-foreground/80 leading-relaxed">
                        {fw.example}
                      </p>
                    </div>

                    <div className="pt-2">
                      <Button asChild className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold">
                        <Link
                          href={`/dashboard/scripts?tab=frameworks&framework=${fw.slug}`}
                        >
                          Try {fw.name} in Script Writer
                          <ArrowRight className="w-4 h-4 ml-2" />
                        </Link>
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </section>

          {/* Hook types — the building blocks frameworks open with */}
          <section id="hooks" className="mb-20 scroll-mt-24">
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-cyan-glow" />
                  The 6 hook types (what Hook Lab classifies into)
                </CardTitle>
                <CardDescription>
                  Every framework above opens with a hook. ViewMagnet's
                  Hook Lab scores yours against these six types — one
                  weak (Summary) and five strong — and rewrites it
                  toward whichever type fits the situation best.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {HOOK_TYPES.map((ht) => {
                  const Icon = ht.icon;
                  const isWeak = ht.strength === "weak";
                  return (
                    <div
                      key={ht.slug}
                      id={`hook-${ht.slug}`}
                      className={`p-4 rounded-lg border scroll-mt-24 ${
                        isWeak
                          ? "border-rose-500/30 bg-rose-500/5"
                          : "border-border/40 bg-background/30"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                            isWeak
                              ? "bg-rose-500/15 text-rose-300"
                              : "bg-cyan-glow/10 text-cyan-glow"
                          }`}
                        >
                          <Icon className="w-4 h-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <h3 className="text-sm font-bold text-foreground">
                              {ht.name}
                            </h3>
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                isWeak
                                  ? "border-rose-500/40 text-rose-300"
                                  : "border-emerald-400/40 text-emerald-300"
                              }`}
                            >
                              {isWeak ? "Weak — avoid" : "Strong"}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                            {ht.definition}
                          </p>
                          <div className="grid sm:grid-cols-2 gap-3">
                            <div className="rounded-md border border-rose-500/20 bg-rose-500/5 p-3">
                              <p className="text-[10px] uppercase tracking-wider font-semibold text-rose-300/70 mb-1">
                                Before
                              </p>
                              <p className="text-sm italic text-foreground/70">
                                "{ht.weakExample}"
                              </p>
                            </div>
                            <div className="rounded-md border border-emerald-400/20 bg-emerald-400/5 p-3">
                              <p className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300/70 mb-1">
                                After
                              </p>
                              <p className="text-sm italic text-foreground/90">
                                "{ht.strongExample}"
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}

                <div className="pt-2">
                  <Button
                    asChild
                    variant="outline"
                    className="border-cyan-glow/40 text-cyan-glow hover:bg-cyan-glow/10"
                  >
                    <Link href="/dashboard/titles?tab=hooks">
                      Open Hook Lab
                      <ArrowRight className="w-4 h-4 ml-2" />
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* How to pick */}
          <section className="mb-20">
            <Card className="bg-background/40 border-border/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-cyan-glow" />
                  Which framework should I pick?
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid md:grid-cols-2 gap-4">
                  {[
                    {
                      ask: "I want new viewers to take me seriously.",
                      pick: "Authority Myth-Buster",
                      slug: "authority_myth_buster",
                    },
                    {
                      ask: "I want viewers to save and share.",
                      pick: "Delta Shift",
                      slug: "delta_shift",
                    },
                    {
                      ask: "I want maximum watch time on a longer video.",
                      pick: "Progressive Debunking",
                      slug: "progressive_debunking",
                    },
                    {
                      ask: "I want to turn views into DMs and leads.",
                      pick: "Lead Magnet",
                      slug: "hype_heit",
                    },
                  ].map((row) => (
                    <Link
                      key={row.slug}
                      href={`/dashboard/scripts?tab=frameworks&framework=${row.slug}`}
                      className="group p-4 rounded-lg border border-border/40 hover:border-cyan-glow/40 transition-colors flex items-start gap-3 bg-background/30"
                    >
                      <Check className="w-4 h-4 text-cyan-glow mt-0.5 shrink-0" />
                      <div>
                        <p className="text-sm text-muted-foreground italic">
                          "{row.ask}"
                        </p>
                        <p className="text-sm font-semibold text-foreground group-hover:text-cyan-glow transition-colors mt-1">
                          → {row.pick}
                        </p>
                      </div>
                    </Link>
                  ))}
                </div>
              </CardContent>
            </Card>
          </section>

          {/* Attribution + sources */}
          <section id="sources" className="mb-20 scroll-mt-24">
            <Card className="bg-background/30 border-border/30">
              <CardContent className="p-6 space-y-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Methodology credit
                  </p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    The four-framework system is adapted from
                    creator Chris Girbu's published framework
                    breakdown (
                    <a
                      href="https://www.chrisgirbu.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-glow hover:underline"
                    >
                      chrisgirbu.com
                    </a>
                    ). The six hook-type taxonomy overlaps with
                    Brendan Kane's{" "}
                    <em>Hook Point</em> (
                    <a
                      href="https://hookpoint.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-glow hover:underline"
                    >
                      hookpoint.com
                    </a>
                    ). ViewMagnet's contribution is the automated
                    layer — using your channel's data to recommend
                    which framework to reach for, and generating a
                    scaffolded first draft so you can iterate on
                    ideas instead of staring at a blank page.
                  </p>
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Why these frameworks work — the underlying
                    research
                  </p>
                  <p className="text-sm text-muted-foreground leading-relaxed mb-3">
                    The frameworks themselves are creator-economy
                    taxonomy, but the <em>reason</em> each one
                    works hooks into well-established research:
                  </p>
                  <ul className="space-y-2 text-sm text-muted-foreground leading-relaxed">
                    <li>
                      <strong className="text-foreground">
                        Hooks open curiosity gaps
                      </strong>{" "}
                      —{" "}
                      <a
                        href="https://doi.org/10.1037/0033-2909.116.1.75"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-glow hover:underline"
                      >
                        Loewenstein (1994), <em>Psychological Bulletin</em>
                      </a>
                      . The foundational paper on information-gap
                      theory.
                    </li>
                    <li>
                      <strong className="text-foreground">
                        High-arousal emotion drives shares
                      </strong>{" "}
                      —{" "}
                      <a
                        href="https://doi.org/10.1509/jmr.10.0353"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-glow hover:underline"
                      >
                        Berger &amp; Milkman (2012),{" "}
                        <em>Journal of Marketing Research</em>
                      </a>
                      . Why awe / anger / amusement out-performs
                      neutral framing for the Delta Shift &amp;
                      Authority Myth-Buster patterns.
                    </li>
                    <li>
                      <strong className="text-foreground">
                        Loss aversion makes stake-reversal hooks
                        feel urgent
                      </strong>{" "}
                      —{" "}
                      <a
                        href="https://doi.org/10.2307/1914185"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-glow hover:underline"
                      >
                        Kahneman &amp; Tversky (1979),{" "}
                        <em>Econometrica</em>
                      </a>
                      . Losses are felt ~2× as strongly as
                      equivalent gains.
                    </li>
                    <li>
                      <strong className="text-foreground">
                        Specific numbers out-credibilize round
                        ones
                      </strong>{" "}
                      —{" "}
                      <a
                        href="https://www.acrwebsite.org/volumes/12390/volumes/v33/NA-33"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-glow hover:underline"
                      >
                        Schindler &amp; Yalch (2006),{" "}
                        <em>Advances in Consumer Research</em>
                      </a>
                      . The empirical case for the Specificity
                      hook.
                    </li>
                    <li>
                      <strong className="text-foreground">
                        Practical-value content gets saved &amp;
                        shared
                      </strong>{" "}
                      —{" "}
                      <a
                        href="https://jonahberger.com/books/contagious/"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-glow hover:underline"
                      >
                        Berger (2013), <em>Contagious</em> ch. 4
                      </a>
                      . Why named systems and screenshot-worthy
                      frameworks (Lead Magnet) over-index on save
                      rate.
                    </li>
                  </ul>
                </div>

                <div className="text-xs text-muted-foreground italic">
                  See the{" "}
                  <Link
                    href="/analyzer-guide#sources"
                    className="text-cyan-glow hover:underline not-italic"
                  >
                    Analyzer Guide sources
                  </Link>{" "}
                  for the full citation list, and the{" "}
                  <Link
                    href="/methodology#sources"
                    className="text-cyan-glow hover:underline not-italic"
                  >
                    Methodology sources
                  </Link>{" "}
                  for the ML stack references (XGBoost, SHAP,
                  balanced-accuracy literature).
                </div>
              </CardContent>
            </Card>
          </section>

          {/* CTA */}
          <section className="text-center">
            <h2 className="text-2xl md:text-3xl font-bold mb-4">
              Ready to write your next script?
            </h2>
            <p className="text-muted-foreground mb-6 max-w-2xl mx-auto">
              ViewMagnet's Script Writer picks the right framework
              for your goal and drafts every section against the
              structure proven to deliver it.
            </p>
            <Button
              asChild
              size="lg"
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
            >
              <Link href="/dashboard/scripts?tab=frameworks">
                Open Script Writer
                <ArrowRight className="w-4 h-4 ml-2" />
              </Link>
            </Button>
          </section>
        </main>
      </div>
    </>
  );
}

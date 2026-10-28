/*
 * Design: Signal Flow — Kinetic Minimalism
 * FAQ: Accordion-style with clean typography
 *
 * SEO / GEO note:
 *
 *   Every FAQ entry carries a parallel ``plainAnswer`` field so we
 *   can ship a ``FAQPage`` JSON-LD block alongside the visual
 *   accordion. Schema.org requires plain text in
 *   ``Question.acceptedAnswer.text`` (no React, no JSX, no
 *   Markdown), and generative engines (Perplexity, ChatGPT Search,
 *   Bing Copilot) preferentially cite pages that ship this schema
 *   because it's the highest-confidence machine-readable answer
 *   format.
 *
 *   When you edit an answer, update BOTH ``a`` (the rich React
 *   version users see) and ``plainAnswer`` (the indexable copy AI
 *   crawlers quote). Keeping them in lockstep is the deal.
 */
import { Link } from "wouter";

import SectionReveal from "@/components/SectionReveal";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { StructuredData } from "@/components/seo";

type Faq = {
  q: string;
  /** Rich React answer shown to humans. */
  a: React.ReactNode;
  /** Plain-text version used in FAQPage JSON-LD. Must be clean
   *  prose with no Markdown / HTML / React. */
  plainAnswer: string;
};

const faqs: Faq[] = [
  {
    q: "How accurate are the predictions really?",
    a: "Our pre-upload model achieves 74.58% balanced accuracy — about 24% better than random guessing. Once your video is live, our velocity models reach 88-92% accuracy using early engagement signals. We're transparent about these numbers because we believe in honest metrics, not marketing hype.",
    plainAnswer:
      "ViewMagnet's pre-upload model achieves 74.58% balanced accuracy on a held-out test set — measured against the channel's trailing-90-day median, not a guess-the-view-count target. Live videos get progressively more accurate predictions (88-92%) once early engagement data lands. All accuracy numbers are internal benchmarks on our own data, not externally validated.",
  },
  {
    q: "How is ViewMagnet different from VidIQ or TubeBuddy?",
    a: "VidIQ and TubeBuddy focus on keyword research and SEO. ViewMagnet uses machine learning to predict performance, discover niche-specific patterns (like \"questions hurt in Tech but help in Education\"), and generate content optimized for YOUR category — not generic best practices.",
    plainAnswer:
      "VidIQ and TubeBuddy are keyword and SEO tools — they tell you what to title a video. ViewMagnet is a full creator workflow: pre-upload prediction (XGBoost + SHAP), a script writer built on four proven viral frameworks, a studio editor, and a one-click distribution hub. The output is niche-aware (patterns learned from top performers in your category) rather than generic best practices.",
  },
  {
    q: "What data do you need from my channel?",
    a: "You can start with just a video URL — no account connection needed. For deeper insights, you can optionally connect your YouTube channel via OAuth (read-only access) to unlock private analytics like CTR, retention curves, and traffic sources.",
    plainAnswer:
      "Start with just a YouTube URL — no account connection required. Optionally connect your channel via read-only YouTube OAuth to unlock private analytics (CTR, retention curves, traffic sources). The pre-upload model only ever uses public-facing data (title, thumbnail, transcript) so the score is reproducible from what a third-party tool can actually see.",
  },
  {
    q: "Can ViewMagnet guarantee my video will go viral?",
    a: "No — and we'd be dishonest to claim otherwise. Virality is stochastic and depends on many factors outside anyone's control. What we CAN do is help you optimize your content using data from your niche, and show you how your track record compares to top creators.",
    plainAnswer:
      "No. Virality has a heavy luck tail no model removes. ViewMagnet helps you optimize content using data from your niche and benchmarks your track record against top creators in your category — but it does not promise view counts, and we will not claim it does. The 74.58% accuracy number means the model is right about relative ranking, not absolute views.",
  },
  {
    q: "How does the AI content creation work?",
    a: "Our AI tools (scripts, descriptions, titles, thumbnails) are powered by LLMs like Claude, but they're enhanced with your niche data. Instead of generic output, they use patterns learned from top performers in YOUR category — specific hook types, power words, and formats that actually work.",
    plainAnswer:
      "ViewMagnet's AI generators (scripts, titles, descriptions, thumbnail concepts) are powered by large language models like Claude and grounded in niche-specific training data. Outputs use one of four viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet) and one of six hook types (Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity; Summary flagged as the weak anti-pattern).",
  },
  {
    // Methodology entry — added when we renamed the
    // ``hype_heit`` framework to "Lead Magnet" so users no longer
    // hit unexplained terminology in recommendations. The link
    // points at the dedicated breakdown page rather than inlining
    // every framework definition here.
    q: "What are the 4 viral script frameworks ViewMagnet uses?",
    plainAnswer:
      "Every ViewMagnet-generated script is built on one of four frameworks: Authority Myth-Buster (build trust fast with new audiences), Delta Shift (the highest save-rate format we measure), Progressive Debunking / Iceberg (engineered for maximum watch time), and Lead Magnet (named-system promise + blurred asset + keyword DM CTA, converts views into leads). Hook Lab classifies hooks into six taxonomy types: Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity, plus Summary as the weak anti-pattern. The four-framework taxonomy is adapted from creator Chris Girbu; the hook taxonomy overlaps with Brendan Kane's Hook Point.",
    a: (
      <>
        Every script we generate is built on one of four frameworks,
        each engineered for a specific outcome the algorithm
        rewards:
        <ul className="mt-3 space-y-1.5 list-disc list-inside">
          <li>
            <strong className="text-foreground">
              Authority Myth-Buster
            </strong>{" "}
            — build trust fast with new audiences.
          </li>
          <li>
            <strong className="text-foreground">Delta Shift</strong>{" "}
            — show the gap between average and top-1% behavior;
            the highest save-rate format we measure.
          </li>
          <li>
            <strong className="text-foreground">
              Progressive Debunking (Iceberg)
            </strong>{" "}
            — engineered for maximum watch time on longer videos.
          </li>
          <li>
            <strong className="text-foreground">
              Lead Magnet
            </strong>{" "}
            — named-system promise + blurred asset + keyword DM CTA;
            converts views into leads.
          </li>
        </ul>
          <p className="mt-3">
          Plus the 6 hook types Hook Lab classifies and rewrites
          into — Mistake Callout, Belief Destruction, Authority
          Anchor, Stake Reversal, and Specificity (with Summary
          flagged as the weak anti-pattern).
        </p>
        <Link
          href="/frameworks"
          className="inline-block mt-3 text-cyan-glow hover:underline font-medium"
        >
          See the full framework + hook-type breakdown →
        </Link>
      </>
    ),
  },
  {
    // Model methodology entry — points at the public Methodology
    // page so the "74.58% balanced accuracy" claim has a citable
    // explanation instead of looking like marketing speak.
    q: 'What does "74.58% balanced accuracy" actually mean?',
    plainAnswer:
      "Balanced accuracy is the version of accuracy that doesn't get fooled by class imbalance. Around 70% of uploads underperform their channel baseline, so a naive model that always predicts 'underperform' would score 70% raw accuracy while being useless — it could never flag a winner. Balanced accuracy averages the recall on each class (overperformer vs underperformer), so the model has to be right on both. 74.58% means about 75% of true overperformers are flagged correctly and about 75% of underperformers are flagged correctly — no free lunch from the majority class. The number is a ViewMagnet-internal benchmark on our held-out test set, not externally validated.",
    a: (
      <>
        Balanced accuracy is the version of accuracy that doesn't
        get fooled by class imbalance. Most uploads underperform
        their channel baseline, so a model that always predicts
        "underperform" would hit ~70% raw accuracy while being
        useless. We report balanced accuracy because the model has
        to be right on both winners <em>and</em> losers — no free
        lunch from the majority class.
        <Link
          href="/methodology"
          className="inline-block mt-3 text-cyan-glow hover:underline font-medium"
        >
          See how the models work, what they were trained on, and
          what they don't do →
        </Link>
      </>
    ),
  },
  {
    // Algorithm signals entry — points at the Analyzer Guide so
    // creators who see "Start bottleneck" / "Keep bottleneck" /
    // "Repeat bottleneck" in the Video Analyzer have a deep
    // explanation with sample rewrites.
    q: 'What do "Start", "Keep", and "Repeat" mean in the Video Analyzer?',
    plainAnswer:
      "Every video on every platform competes on the same three questions: did people START watching (clicks, driven by title + thumbnail), did they KEEP watching (retention, driven by hook + pacing), and did they want to REPEAT (saves, shares, return visits — driven by named systems and shareable insights). ViewMagnet scores all three out of 100 and flags the lowest as the bottleneck, because improving the bottleneck has the highest leverage. Recommendations deep-link into Hook Lab for Start bottlenecks, Script Writer for Keep/Repeat bottlenecks, and the A/B Tester to validate the change.",
    a: (
      <>
        Every video on every platform competes on the same three
        questions: did people <strong>start</strong> watching
        (clicks), did they <strong>keep</strong> watching
        (retention), did they want to come back to{" "}
        <strong>repeat</strong> (saves, shares, return visits).
        ViewMagnet scores all three and flags the lowest as your
        bottleneck — improving the bottleneck has the highest
        leverage.
        <Link
          href="/analyzer-guide"
          className="inline-block mt-3 text-cyan-glow hover:underline font-medium"
        >
          See the full Start / Keep / Repeat guide with sample
          rewrites →
        </Link>
      </>
    ),
  },
  {
    q: "Does ViewMagnet work with Claude, Cursor, or other AI agents?",
    a: (
      <>
        Yes. The{" "}
        <Link
          href="/mcp"
          className="text-cyan-glow hover:underline font-medium"
        >
          ViewMagnet MCP server
        </Link>{" "}
        installs into Claude Desktop, Cursor, and Cline in one command
        (<code className="text-xs">npx viewmagnet-mcp install</code>)
        and exposes 10 tools — analyze video, generate script, score
        hook, detect highlights, analyze pacing, score / generate
        titles, pull outcomes — that your agent can call on your behalf
        using a revocable Personal Access Token. No password sharing,
        no long-lived JWTs.
        <Link
          href="/mcp"
          className="inline-block mt-3 text-cyan-glow hover:underline font-medium"
        >
          See the install snippet and tool list →
        </Link>
      </>
    ),
    plainAnswer:
      "Yes. ViewMagnet publishes an open Model Context Protocol (MCP) server at https://viewmagnet.io/mcp and as the npm package `viewmagnet-mcp`. One command installs it into Claude Desktop, Cursor, or Cline. The server exposes 10 tools: viewmagnet_analyze_video, viewmagnet_list_frameworks, viewmagnet_generate_script, viewmagnet_score_hook, viewmagnet_list_hook_types, viewmagnet_detect_highlights, viewmagnet_analyze_pacing, viewmagnet_score_title, viewmagnet_generate_titles, viewmagnet_get_outcomes. Auth is via Personal Access Tokens generated from the dashboard at /dashboard/api-tokens — revocable, scope-limited, and never reusing the user's password.",
  },
  {
    q: "Is there a free plan?",
    a: "Yes! The free plan includes 5 video analyses, 3 AI scripts, and 5 thumbnails per month. No credit card required. It's enough to see how ViewMagnet can help your channel before upgrading.",
    plainAnswer:
      "Yes. The free plan includes 5 video analyses, 3 AI-generated scripts, and 5 thumbnail generations per month with no credit card required. It is sized to let you fully evaluate the prediction model, script frameworks, and studio editor before deciding whether to upgrade.",
  },
  {
    q: "What niches do you support?",
    a: "Our models are trained on 144,641+ videos across all major YouTube categories including Gaming, Tech, Education, Lifestyle, Entertainment, Finance, and more. We have niche-specific patterns and benchmarks for each category.",
    plainAnswer:
      "ViewMagnet's models are trained on a corpus spanning all major YouTube categories — Gaming, Tech, Education, Lifestyle, Entertainment, Finance, Music, Comedy, News commentary, Reviews — plus niche-specific benchmarks for each. Shorts and long-form are kept in separate length buckets so a 30-second hook isn't compared against a 12-minute essay.",
  },
];

export default function FAQ() {
  return (
    <section className="relative py-24 md:py-32">
      {/* FAQPage JSON-LD — uses the plain-text answers so it's
          a clean, machine-readable mirror of the visual
          accordion. Generative engines (ChatGPT Search,
          Perplexity, Bing Copilot) preferentially quote pages
          that ship this schema. */}
      <StructuredData
        type="faq"
        questions={faqs.map((f) => ({
          question: f.q,
          answer: f.plainAnswer,
        }))}
      />
      <div className="container">
        <SectionReveal>
          <div className="text-center max-w-2xl mx-auto mb-12">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-amber-glow">
              FAQ
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight">
              Common Questions
            </h2>
          </div>
        </SectionReveal>

        <SectionReveal delay={0.1}>
          <div className="max-w-3xl mx-auto">
            <Accordion type="single" collapsible className="space-y-3">
              {faqs.map((faq, i) => (
                <AccordionItem
                  key={i}
                  value={`faq-${i}`}
                  className="glass-card rounded-xl px-6 border-border/30 data-[state=open]:border-cyan-glow/20"
                >
                  <AccordionTrigger className="text-left text-sm font-semibold text-foreground hover:no-underline py-4">
                    {faq.q}
                  </AccordionTrigger>
                  <AccordionContent className="text-sm text-muted-foreground leading-relaxed pb-4">
                    {faq.a}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

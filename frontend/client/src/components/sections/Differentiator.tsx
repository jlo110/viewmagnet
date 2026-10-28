/*
 * Design: Signal Flow — Kinetic Minimalism
 * Differentiator: Side-by-side comparison showing generic vs ViewMagnet advice
 */
import SectionReveal from "@/components/SectionReveal";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";

const VELOCITY_IMG = "https://private-us-east-1.manuscdn.com/sessionFile/pj36B0BzIZ7Osio6X1a34c/sandbox/CwHSCmBUP1IcP4HpneKu4a-img-5_1770792160000_na1fn_dmVsb2NpdHktcHJlZGljdGlvbg.png?x-oss-process=image/resize,w_1920,h_1920/format,webp/quality,q_80&Expires=1798761600&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvcGozNkIwQnpJWjdPc2lvNlgxYTM0Yy9zYW5kYm94L0N3SFNDbUJVUDFJY1A0SHBuZUt1NGEtaW1nLTVfMTc3MDc5MjE2MDAwMF9uYTFmbl9kbVZzYjJOcGRIa3RjSEpsWkdsamRHbHZiZy5wbmc~eC1vc3MtcHJvY2Vzcz1pbWFnZS9yZXNpemUsd18xOTIwLGhfMTkyMC9mb3JtYXQsd2VicC9xdWFsaXR5LHFfODAiLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTg3NjE2MDB9fX1dfQ__&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=gfjLgrNb0dibQsm133vyXwD4H0vCvC91PUuy8Twh3OPWcnc2HUoPv2M7w98US~agSVvyLo1Nw1xppt8i8a7Z6noGXvKRGDSm6CNmxM2YJLC8O8lJrModxbgrhnzGqWei2SFrFV8ExDw1oqZD~ERBpZABoMw0mnDzQvsMGiIgYAlTxpnsKm4GagDGQpBJVFdCrIRQ6SwbgYs8QrZme-cOKDPERYuu2ScF3BkrqsY2JvuUXgj61TXP~Sx3dYpRH6y3rGVR~TibQf9PmIZTPPt1j8I8ZGWFog0kqBbodE0HEp8QasLUVd1f3WUfiGG8n7SY4S93v6Bu2XzAJSEjgtOPcQ__";

const comparisons = [
  {
    generic: '"Add a number to your title"',
    viewmagnet: "Gaming: numbers +6%. Tech: numbers -2% (they hurt!)",
  },
  {
    generic: '"Use questions in titles"',
    viewmagnet: "Tech: questions -6%. Education: questions +4%",
  },
  {
    generic: '"Add exclamation marks!"',
    viewmagnet: "Gaming: exclamation -13% (looks spammy to that audience)",
  },
  {
    generic: '"Follow best practices"',
    viewmagnet: '"I [verb]ed..." pattern = 2.69x in Tech, 1.66x in Gaming',
  },
];

const nichePatterns = [
  { niche: "Gaming", pattern: '"speedrun in" = +32% within-creator validated', color: "cyan" },
  { niche: "Education", pattern: '"you need to" = +80% within-creator validated', color: "amber" },
  { niche: "Music", pattern: '"music video" = +193% within-creator validated', color: "cyan" },
  { niche: "Entertainment", pattern: '"movie reaction" = +58% within-creator', color: "amber" },
  { niche: "Lifestyle", pattern: '"decorate with me" = +28% validated', color: "cyan" },
];

export default function Differentiator() {
  return (
    <section className="relative py-24 md:py-32 bg-surface-dark">
      <div className="container">
        <SectionReveal>
          <div className="max-w-2xl">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-amber-glow">
              Why ViewMagnet
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight leading-tight">
              Data-Driven, Not{" "}
              <span className="text-muted-foreground line-through decoration-destructive/50">
                Generic Advice
              </span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground leading-relaxed">
              Other tools give you the same tips for every creator. ViewMagnet learns
              what actually works in <em>your</em> niche from real performance data.
            </p>
          </div>
        </SectionReveal>

        {/* Comparison Table */}
        <div className="mt-12 grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Generic column */}
          <SectionReveal delay={0.1} direction="left">
            <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-6">
              <div className="flex items-center gap-2 mb-5">
                <AlertTriangle className="w-5 h-5 text-destructive" />
                <h3 className="font-bold text-foreground">Generic Tools Say</h3>
              </div>
              <div className="space-y-3">
                {comparisons.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 p-3 rounded-lg bg-background/50"
                  >
                    <X className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                    <span className="text-sm text-muted-foreground">{c.generic}</span>
                  </div>
                ))}
              </div>
            </div>
          </SectionReveal>

          {/* ViewMagnet column */}
          <SectionReveal delay={0.2} direction="right">
            <div className="rounded-xl border border-cyan-glow/20 bg-cyan-glow/5 p-6">
              <div className="flex items-center gap-2 mb-5">
                <CheckCircle2 className="w-5 h-5 text-cyan-glow" />
                <h3 className="font-bold text-foreground">ViewMagnet Says</h3>
              </div>
              <div className="space-y-3">
                {comparisons.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 p-3 rounded-lg bg-background/50"
                  >
                    <CheckCircle2 className="w-4 h-4 text-cyan-glow shrink-0 mt-0.5" />
                    <span className="text-sm text-foreground font-medium">{c.viewmagnet}</span>
                  </div>
                ))}
              </div>
            </div>
          </SectionReveal>
        </div>

        {/* Velocity Prediction + Niche Patterns */}
        <div className="mt-16 grid grid-cols-1 lg:grid-cols-5 gap-8">
          {/* Velocity Image */}
          <SectionReveal delay={0.1} className="lg:col-span-3">
            <div className="relative rounded-xl overflow-hidden border border-border/30 h-full">
              <img
                src={VELOCITY_IMG}
                alt="ViewMagnet velocity prediction chart showing actual vs predicted view trajectory"
                className="w-full h-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-r from-background/80 via-background/30 to-transparent" />
              <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-background/90 to-transparent">
                <p className="text-xs font-[var(--font-mono)] text-cyan-glow mb-1">VELOCITY TRACKER</p>
                <p className="text-xl font-bold text-foreground">90-94% Accuracy</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Auto-track channels, predict views at 3d, 7d, 14d, 30d milestones
                </p>
              </div>
            </div>
          </SectionReveal>

          {/* Niche Patterns */}
          <SectionReveal delay={0.2} className="lg:col-span-2">
            <div className="glass-card rounded-xl p-6 h-full">
              <h3 className="text-xs font-[var(--font-mono)] tracking-widest uppercase text-amber-glow mb-4">
                Causally Validated Phrases
              </h3>
              <div className="space-y-3">
                {nichePatterns.map((p, i) => (
                  <div key={i} className="p-3 rounded-lg bg-background/50 border border-border/30">
                    <span
                      className={`text-[10px] font-[var(--font-mono)] tracking-wider uppercase ${
                        p.color === "cyan" ? "text-cyan-glow" : "text-amber-glow"
                      }`}
                    >
                      {p.niche}
                    </span>
                    <p className="text-sm text-foreground mt-1 font-medium">{p.pattern}</p>
                  </div>
                ))}
              </div>
            </div>
          </SectionReveal>
        </div>
      </div>
    </section>
  );
}

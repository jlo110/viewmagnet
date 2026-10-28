/*
 * Design: Signal Flow — Kinetic Minimalism
 * How It Works: 3-step flow with connecting gradient line
 */
import SectionReveal from "@/components/SectionReveal";
import { ArrowDown, BarChart3, Lightbulb, Upload } from "lucide-react";

const DATA_INSIGHTS_IMG = "https://private-us-east-1.manuscdn.com/sessionFile/pj36B0BzIZ7Osio6X1a34c/sandbox/CwHSCmBUP1IcP4HpneKu4a-img-4_1770792169000_na1fn_ZGF0YS1pbnNpZ2h0cw.png?x-oss-process=image/resize,w_1920,h_1920/format,webp/quality,q_80&Expires=1798761600&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvcGozNkIwQnpJWjdPc2lvNlgxYTM0Yy9zYW5kYm94L0N3SFNDbUJVUDFJY1A0SHBuZUt1NGEtaW1nLTRfMTc3MDc5MjE2OTAwMF9uYTFmbl9aR0YwWVMxcGJuTnBaMmgwY3cucG5nP3gtb3NzLXByb2Nlc3M9aW1hZ2UvcmVzaXplLHdfMTkyMCxoXzE5MjAvZm9ybWF0LHdlYnAvcXVhbGl0eSxxXzgwIiwiQ29uZGl0aW9uIjp7IkRhdGVMZXNzVGhhbiI6eyJBV1M6RXBvY2hUaW1lIjoxNzk4NzYxNjAwfX19XX0_&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=OyiUxupmdjJl~peYe2odSd4qR~O2kZQYPOTirr8vRvq8pmma2j7rXqfizeSDlt2Q~MePtCC1dkDnG9CZNio4V97zzpiq0oMl1O109wPKsGnhxQRNh1pItNBagPjYmZ1~B5xB2x~-cFZw0LQ7G3oElFhJri-eoNvjtewIKqlGgxf7GRQrwpsRx7fZ6WEqSv7oM~hoR5cvF0LgayfVhlwdRlIJ-Nl9eD9hQPeOKg4Z3ovJTB2YL0C8-h5~UNqJbVg8k24ou1eRE1pT3Xyci3NpkvqWncgWj~YmYiW62Ef9pS8OfWpo1NjZHef3feKHv3bV8dZUYypp8eMXE4m~IDfANQ__";

const steps = [
  {
    icon: Upload,
    step: "01",
    title: "Paste Your Video URL",
    desc: "Drop a YouTube link or connect your channel. We analyze your title, thumbnail, channel history, and niche benchmarks in seconds.",
  },
  {
    icon: BarChart3,
    step: "02",
    title: "Get Your Magnet Score",
    desc: "Our XGBoost model scores your video's likelihood of beating your baseline. SHAP explanations show exactly which factors help or hurt.",
  },
  {
    icon: Lightbulb,
    step: "03",
    title: "Optimize & Create",
    desc: "Use AI tools to generate better titles, thumbnails, scripts, and more — all optimized for YOUR niche patterns, not generic advice.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="relative py-24 md:py-32 overflow-hidden">
      {/* Background accent */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-cyan-glow/5 rounded-full blur-[120px]" />

      <div className="container relative">
        <SectionReveal>
          <div className="text-center max-w-2xl mx-auto">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-amber-glow">
              How It Works
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight">
              From Upload to{" "}
              <span className="gradient-text">Actionable Insights</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Three steps to data-driven YouTube growth. No guesswork required.
            </p>
          </div>
        </SectionReveal>

        {/* Steps */}
        <div className="mt-16 md:mt-20 grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-6 relative">
          {/* Connecting line (desktop) */}
          <div className="hidden md:block absolute top-12 left-[16.67%] right-[16.67%] h-px bg-gradient-to-r from-cyan-glow/40 via-amber-glow/40 to-cyan-glow/40" />

          {steps.map((step, i) => (
            <SectionReveal key={step.step} delay={i * 0.15}>
              <div className="relative flex flex-col items-center text-center">
                {/* Step circle */}
                <div className="relative z-10 w-24 h-24 rounded-2xl bg-surface-dark border border-border/50 flex flex-col items-center justify-center mb-6 group-hover:border-cyan-glow/30 transition-colors">
                  <step.icon className="w-8 h-8 text-cyan-glow mb-1" />
                  <span className="text-[10px] font-[var(--font-mono)] text-muted-foreground tracking-wider">
                    STEP {step.step}
                  </span>
                </div>

                <h3 className="text-xl font-bold text-foreground">{step.title}</h3>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-xs">
                  {step.desc}
                </p>

                {/* Arrow between steps on mobile */}
                {i < steps.length - 1 && (
                  <ArrowDown className="md:hidden w-5 h-5 text-muted-foreground/40 mt-6" />
                )}
              </div>
            </SectionReveal>
          ))}
        </div>

        {/* Data Insights Visual */}
        <SectionReveal delay={0.3}>
          <div className="mt-20 relative rounded-xl overflow-hidden border border-border/30 max-w-4xl mx-auto">
            <img
              src={DATA_INSIGHTS_IMG}
              alt="ViewMagnet neural network visualization showing connected data nodes representing machine learning pattern discovery"
              className="w-full h-auto"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-background/80 via-transparent to-transparent" />
            <div className="absolute bottom-6 left-6 right-6">
              <p className="text-sm font-[var(--font-mono)] text-cyan-glow">
                Trained on 144,641+ real YouTube videos across every niche
              </p>
            </div>
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

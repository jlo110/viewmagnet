/*
 * Design: Signal Flow — Kinetic Minimalism
 * Model Accuracy: Showcasing honest, transparent ML performance
 */
import AnimatedCounter from "@/components/AnimatedCounter";
import SectionReveal from "@/components/SectionReveal";
import { Activity, Clock, Gauge, Target } from "lucide-react";

const models = [
  {
    icon: Target,
    name: "Magnet Score",
    accuracy: 74.58,
    suffix: "%",
    desc: "Pre-upload content optimization score. Know your potential before you publish.",
    detail: "XGBoost · 409 features · 144K training videos",
    color: "cyan",
  },
  {
    icon: Clock,
    name: "Day 1 → Day 30",
    accuracy: 74,
    suffix: "%",
    desc: "Predict final views from 24 hours of data + channel patterns.",
    detail: "Growth multiplier · Channel history boost",
    color: "amber",
  },
  {
    icon: Activity,
    name: "Day 7 → Day 30",
    accuracy: 90,
    suffix: "%",
    desc: "High-confidence prediction. Most views are in by day 7.",
    detail: "XGBoost velocity · 0.993 correlation",
    color: "cyan",
  },
  {
    icon: Gauge,
    name: "Day 14 → Day 30",
    accuracy: 94,
    suffix: "%",
    desc: "Our most accurate model. Near-perfect trajectory prediction.",
    detail: "Velocity v3 · 17K videos with 30-day tracking",
    color: "amber",
  },
];

export default function ModelAccuracy() {
  return (
    <section className="relative py-24 md:py-32">
      <div className="container">
        <SectionReveal>
          <div className="max-w-2xl">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-cyan-glow">
              Transparent ML
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight leading-tight">
              Honest About Our{" "}
              <span className="gradient-text">Model Performance</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground leading-relaxed">
              We don't hide behind vague claims. Here are our real, validated accuracy
              numbers — tested on held-out data with no leakage.
            </p>
          </div>
        </SectionReveal>

        {/* Model Cards */}
        <div className="mt-14 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {models.map((model, i) => (
            <SectionReveal key={model.name} delay={i * 0.1}>
              <div className="glass-card rounded-xl p-6 h-full hover:border-cyan-glow/30 transition-all duration-300 group">
                <div
                  className={`w-10 h-10 rounded-lg flex items-center justify-center mb-4 ${
                    model.color === "cyan"
                      ? "bg-cyan-glow/10 group-hover:bg-cyan-glow/20"
                      : "bg-amber-glow/10 group-hover:bg-amber-glow/20"
                  } transition-colors`}
                >
                  <model.icon
                    className={`w-5 h-5 ${
                      model.color === "cyan" ? "text-cyan-glow" : "text-amber-glow"
                    }`}
                  />
                </div>

                <div className="mb-3">
                  <span
                    className={`text-3xl font-bold font-[var(--font-display)] ${
                      model.color === "cyan" ? "text-cyan-glow text-glow-cyan" : "text-amber-glow text-glow-amber"
                    }`}
                  >
                    <AnimatedCounter
                      value={model.accuracy}
                      suffix={model.suffix}
                      decimals={model.accuracy % 1 !== 0 ? 2 : 0}
                    />
                  </span>
                </div>

                <h3 className="font-bold text-foreground text-sm">{model.name}</h3>
                <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                  {model.desc}
                </p>
                <p className="text-[11px] font-[var(--font-mono)] text-muted-foreground/60 mt-3">
                  {model.detail}
                </p>
              </div>
            </SectionReveal>
          ))}
        </div>

        {/* Key Insight */}
        <SectionReveal delay={0.3}>
          <div className="mt-10 p-5 rounded-xl border border-amber-glow/20 bg-amber-glow/5 max-w-3xl">
            <p className="text-sm text-foreground leading-relaxed">
              <span className="font-bold text-amber-glow">Key Insight:</span>{" "}
              Pre-upload prediction is inherently hard (~75% ceiling) because we don't have
              audience reaction data yet. Once your video is live, our velocity models are{" "}
              <span className="font-bold">20%+ more accurate</span> because early engagement
              signals are highly predictive of final performance.
            </p>
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

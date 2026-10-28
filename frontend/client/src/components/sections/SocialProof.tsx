/*
 * Design: Signal Flow — Kinetic Minimalism
 * Social proof bar with key differentiators
 */
import SectionReveal from "@/components/SectionReveal";
import { BarChart3, Brain, Target, TrendingUp } from "lucide-react";

const proofs = [
  {
    icon: Brain,
    label: "ML-Powered Predictions",
    desc: "XGBoost models, not rules of thumb",
  },
  {
    icon: Target,
    label: "Niche-Specific Insights",
    desc: "What works in YOUR category",
  },
  {
    icon: TrendingUp,
    label: "88-92% Velocity Accuracy",
    desc: "Predict final views from early signals",
  },
  {
    icon: BarChart3,
    label: "144K+ Videos Trained",
    desc: "Real data, not assumptions",
  },
];

export default function SocialProof() {
  return (
    <section className="relative py-16 border-y border-border/30">
      <div className="container">
        <SectionReveal>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-8 md:gap-6">
            {proofs.map((item, i) => (
              <SectionReveal key={item.label} delay={i * 0.1}>
                <div className="flex flex-col items-start gap-3 group">
                  <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center group-hover:bg-cyan-glow/20 transition-colors">
                    <item.icon className="w-5 h-5 text-cyan-glow" />
                  </div>
                  <div>
                    <p className="font-semibold text-sm text-foreground">{item.label}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                  </div>
                </div>
              </SectionReveal>
            ))}
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

/*
 * Design: Signal Flow — Kinetic Minimalism
 * Comparison table: ViewMagnet vs VidIQ vs TubeBuddy
 */
import SectionReveal from "@/components/SectionReveal";
import { Check, Minus, Star } from "lucide-react";

const features: { name: string; vm: boolean | "unique"; vidiq: boolean; tubebuddy: boolean }[] = [
  { name: "ML Performance Prediction", vm: "unique", vidiq: false, tubebuddy: false },
  { name: "Velocity Tracking (88-92%)", vm: "unique", vidiq: false, tubebuddy: false },
  { name: "Niche-Optimized Output", vm: "unique", vidiq: false, tubebuddy: false },
  { name: "Uses YOUR Channel Data", vm: "unique", vidiq: false, tubebuddy: false },
  { name: "AI Thumbnail Creator", vm: true, vidiq: true, tubebuddy: true },
  { name: "AI Title Generator", vm: true, vidiq: true, tubebuddy: true },
  { name: "AI Script Writer", vm: true, vidiq: true, tubebuddy: false },
  { name: "Keyword Research", vm: true, vidiq: true, tubebuddy: true },
  { name: "AI Shorts Creator", vm: true, vidiq: true, tubebuddy: false },
  { name: "Animated Captions", vm: true, vidiq: false, tubebuddy: false },
  { name: "Pre-Upload A/B Testing", vm: true, vidiq: false, tubebuddy: false },
  { name: "Competitor Tracking", vm: true, vidiq: true, tubebuddy: true },
];

function FeatureCell({ value }: { value: boolean | "unique" }) {
  if (value === "unique") {
    return (
      <span className="inline-flex items-center gap-1 text-amber-glow">
        <Star className="w-4 h-4 fill-amber-glow" />
        <span className="text-xs font-bold font-[var(--font-mono)]">UNIQUE</span>
      </span>
    );
  }
  if (value) {
    return <Check className="w-4 h-4 text-cyan-glow mx-auto" />;
  }
  return <Minus className="w-4 h-4 text-muted-foreground/40 mx-auto" />;
}

export default function Comparison() {
  return (
    <section id="compare" className="relative py-24 md:py-32 bg-surface-dark">
      <div className="container">
        <SectionReveal>
          <div className="text-center max-w-2xl mx-auto">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-cyan-glow">
              Comparison
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight">
              How We Stack Up
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              ViewMagnet offers capabilities that no other YouTube tool provides.
            </p>
          </div>
        </SectionReveal>

        <SectionReveal delay={0.15}>
          <div className="mt-12 overflow-x-auto">
            <table className="w-full min-w-[600px]">
              <thead>
                <tr className="border-b border-border/40">
                  <th className="text-left py-4 px-4 text-sm font-medium text-muted-foreground w-[40%]">
                    Feature
                  </th>
                  <th className="text-center py-4 px-4 w-[20%]">
                    <span className="text-sm font-bold gradient-text">ViewMagnet</span>
                  </th>
                  <th className="text-center py-4 px-4 text-sm font-medium text-muted-foreground w-[20%]">
                    VidIQ
                  </th>
                  <th className="text-center py-4 px-4 text-sm font-medium text-muted-foreground w-[20%]">
                    TubeBuddy
                  </th>
                </tr>
              </thead>
              <tbody>
                {features.map((f, i) => (
                  <tr
                    key={f.name}
                    className={`border-b border-border/20 ${
                      i < 4 ? "bg-cyan-glow/[0.03]" : ""
                    }`}
                  >
                    <td className="py-3.5 px-4 text-sm text-foreground font-medium">
                      {f.name}
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <FeatureCell value={f.vm} />
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <FeatureCell value={f.vidiq} />
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <FeatureCell value={f.tubebuddy} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

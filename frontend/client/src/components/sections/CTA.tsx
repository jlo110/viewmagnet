/*
 * Design: Signal Flow — Kinetic Minimalism
 * CTA: Full-width gradient banner with strong call to action
 */
import SectionReveal from "@/components/SectionReveal";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

export default function CTA() {
  return (
    <section className="relative py-24 md:py-32 overflow-hidden">
      {/* Gradient background */}
      <div className="absolute inset-0 bg-gradient-to-br from-cyan-glow/10 via-background to-amber-glow/10" />
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-glow/30 to-transparent" />

      <div className="container relative">
        <SectionReveal>
          <div className="text-center max-w-3xl mx-auto">
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight leading-tight">
              Ready to Stop Guessing and{" "}
              <span className="gradient-text">Start Growing?</span>
            </h2>
            <p className="mt-6 text-lg text-muted-foreground leading-relaxed max-w-xl mx-auto">
              Join creators who use data — not luck — to grow their channels.
              Start with 5 free video analyses today.
            </p>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
              <Button
                size="lg"
                className="text-base font-semibold bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 shadow-[0_0_30px_oklch(0.82_0.15_200/0.35)] h-12 px-8"
              >
                Start Free — No Credit Card
                <ArrowRight className="ml-2 w-4 h-4" />
              </Button>
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              Free plan includes 5 video analyses, 3 scripts, and 5 thumbnails per month.
            </p>
          </div>
        </SectionReveal>
      </div>
    </section>
  );
}

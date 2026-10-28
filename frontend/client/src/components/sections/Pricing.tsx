/*
 * Design: Signal Flow — Kinetic Minimalism
 * Pricing: 4 tiers with Pro highlighted, glass cards
 */
import SectionReveal from "@/components/SectionReveal";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { createCheckout } from "@/lib/api";
import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useLocation } from "wouter";

const tiers = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    desc: "Try ViewMagnet with basic features",
    features: [
      "5 video analyses / month",
      "3 AI scripts / month",
      "5 thumbnails / month",
      "Basic title scoring",
      "Niche benchmarks",
    ],
    cta: "Get Started",
    highlighted: false,
    accent: "default",
  },
  {
    name: "Starter",
    price: "$9",
    period: "/month",
    desc: "For growing creators who want an edge",
    features: [
      "50 video analyses / month",
      "20 AI scripts / month",
      "30 thumbnails + AI backgrounds",
      "Full title generator",
      "Trend timing alerts",
      "A/B test simulator",
    ],
    cta: "Start Free Trial",
    highlighted: false,
    accent: "default",
  },
  {
    name: "Pro",
    price: "$29",
    period: "/month",
    desc: "Full suite for serious creators",
    features: [
      "500 video analyses / month",
      "100 AI scripts / month",
      "Unlimited thumbnails",
      "Competitor analysis",
      "Winning formula dashboard",
      "Smart alerts + notifications",
      "Keyword research tool",
      "Animated captions",
      "Chrome extension",
    ],
    cta: "Start Free Trial",
    highlighted: true,
    accent: "cyan",
  },
  {
    name: "Agency",
    price: "$99",
    period: "/month",
    desc: "Unlimited access for teams & agencies",
    features: [
      "Unlimited everything",
      "Multiple channel management",
      "Priority API access",
      "Custom niche models",
      "Dedicated support",
      "Team collaboration",
      "White-label reports",
    ],
    cta: "Contact Sales",
    highlighted: false,
    accent: "default",
  },
];

export default function Pricing() {
  const { demoLoginEnabled, loginAsDemo, isAuthenticated } = useAuth();
  const [, navigate] = useLocation();
  const [signingInTier, setSigningInTier] = useState<string | null>(null);

  // Maps the marketing tier name to the backend plan slug used by Stripe.
  const PLAN_SLUG: Record<string, string> = {
    Free: "free",
    Starter: "starter",
    Pro: "pro",
    Agency: "agency",
  };

  const handleTierCta = async (tier: { name: string; cta: string }) => {
    // Agency is sales-assisted (custom contracts / seats).
    if (tier.cta === "Contact Sales") {
      navigate("/contact");
      return;
    }

    const plan = PLAN_SLUG[tier.name] ?? "free";

    // Free tier: just get them into the app.
    if (plan === "free") {
      if (isAuthenticated || !demoLoginEnabled) {
        navigate("/dashboard");
        return;
      }
      setSigningInTier(tier.name);
      try {
        await loginAsDemo();
        toast.success("Signed in as demo user");
        navigate("/dashboard");
      } catch (err) {
        toast.error("Could not sign in to demo account. Please try again.");
        console.error("demo login failed", err);
      } finally {
        setSigningInTier(null);
      }
      return;
    }

    // Paid tier (Starter / Pro): authenticated users go straight to Stripe
    // Checkout; everyone else signs up first (carrying the intended plan).
    if (!isAuthenticated) {
      navigate(`/signup?plan=${plan}`);
      return;
    }

    setSigningInTier(tier.name);
    try {
      const url = await createCheckout(plan);
      window.location.href = url;
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        toast.error("Billing isn't available just yet — please check back soon.");
      } else {
        toast.error("Couldn't start checkout. Please try again.");
      }
      console.error("checkout failed", err);
      setSigningInTier(null);
    }
  };

  return (
    <section id="pricing" className="relative py-24 md:py-32">
      {/* Background glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] bg-cyan-glow/5 rounded-full blur-[150px]" />

      <div className="container relative">
        <SectionReveal>
          <div className="text-center max-w-2xl mx-auto">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-cyan-glow">
              Pricing
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight">
              Start Free.{" "}
              <span className="gradient-text">Scale When Ready.</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Every plan includes our ML prediction engine. Upgrade as your channel grows.
            </p>
          </div>
        </SectionReveal>

        {/* Pricing Grid */}
        <div className="mt-14 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {tiers.map((tier, i) => (
            <SectionReveal key={tier.name} delay={i * 0.1}>
              <div
                className={`relative rounded-xl p-6 h-full flex flex-col ${
                  tier.highlighted
                    ? "border-2 border-cyan-glow/50 bg-cyan-glow/5 shadow-[0_0_40px_oklch(0.82_0.15_200/0.15)]"
                    : "glass-card"
                }`}
              >
                {tier.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="px-3 py-1 rounded-full text-[10px] font-bold font-[var(--font-mono)] uppercase tracking-wider bg-cyan-glow text-deep-charcoal">
                      Most Popular
                    </span>
                  </div>
                )}

                <div className="mb-6">
                  <h3 className="text-lg font-bold text-foreground">{tier.name}</h3>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="text-4xl font-bold font-[var(--font-display)] text-foreground">
                      {tier.price}
                    </span>
                    <span className="text-sm text-muted-foreground">{tier.period}</span>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{tier.desc}</p>
                </div>

                <ul className="space-y-2.5 mb-8 flex-1">
                  {tier.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2.5">
                      <Check
                        className={`w-4 h-4 shrink-0 mt-0.5 ${
                          tier.highlighted ? "text-cyan-glow" : "text-muted-foreground"
                        }`}
                      />
                      <span className="text-sm text-foreground/80">{feature}</span>
                    </li>
                  ))}
                </ul>

                <Button
                  onClick={() => handleTierCta(tier)}
                  disabled={signingInTier !== null}
                  className={`w-full font-semibold ${
                    tier.highlighted
                      ? "bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 shadow-[0_0_20px_oklch(0.82_0.15_200/0.3)]"
                      : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
                  }`}
                >
                  {signingInTier === tier.name ? (
                    <>
                      <Loader2 className="mr-2 w-4 h-4 animate-spin" />
                      Signing in…
                    </>
                  ) : (
                    tier.cta
                  )}
                </Button>
              </div>
            </SectionReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

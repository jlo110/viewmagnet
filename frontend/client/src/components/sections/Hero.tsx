/*
 * Design: Signal Flow — Kinetic Minimalism
 * Hero: Full-viewport, dark bg with flowing gradient lines
 * Cyan (#00D4FF) primary accent, amber (#FFB800) secondary
 */
import AnimatedCounter from "@/components/AnimatedCounter";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { motion } from "framer-motion";
import { ArrowRight, Loader2, Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useLocation } from "wouter";

const HERO_BG = "https://private-us-east-1.manuscdn.com/sessionFile/pj36B0BzIZ7Osio6X1a34c/sandbox/CwHSCmBUP1IcP4HpneKu4a-img-1_1770792157000_na1fn_aGVyby1iZw.png?x-oss-process=image/resize,w_1920,h_1920/format,webp/quality,q_80&Expires=1798761600&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvcGozNkIwQnpJWjdPc2lvNlgxYTM0Yy9zYW5kYm94L0N3SFNDbUJVUDFJY1A0SHBuZUt1NGEtaW1nLTFfMTc3MDc5MjE1NzAwMF9uYTFmbl9hR1Z5YnkxaVp3LnBuZz94LW9zcy1wcm9jZXNzPWltYWdlL3Jlc2l6ZSx3XzE5MjAsaF8xOTIwL2Zvcm1hdCx3ZWJwL3F1YWxpdHkscV84MCIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc5ODc2MTYwMH19fV19&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=CNIjZkc6IyX7lFlP-O7NFUuDS5A76UuEWhUWiYoePbg8h6Dle9-raStIbPFDTmYTNEw~JEg2u0tB2nN~paNlChN-VN7vERrP6voRnoU32F6SRHuNXxBaylKmX-6e0muocbmRTLS8uxuPeQbX4YReLjDX1Nan~buUlB36OrPOf~O0UZksJSwy7YEJXYSH3ok194MxDRWD92HaQFn2JaTpXWHB4px8s4dANpt-AQW3pBwza9s70G3bIOmPhSA19vQ-il8ZS7phg4C4FL2RGP8yfhvmGw5hm~oyZZnDTHdBPdD-1VJbQx2FaFmPjvlP5EygwL1c4n~xcAPmz6XCuic-3A__";

const DASHBOARD_IMG = "https://private-us-east-1.manuscdn.com/sessionFile/pj36B0BzIZ7Osio6X1a34c/sandbox/CwHSCmBUP1IcP4HpneKu4a-img-2_1770792157000_na1fn_ZGFzaGJvYXJkLW1vY2t1cA.png?x-oss-process=image/resize,w_1920,h_1920/format,webp/quality,q_80&Expires=1798761600&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvcGozNkIwQnpJWjdPc2lvNlgxYTM0Yy9zYW5kYm94L0N3SFNDbUJVUDFJY1A0SHBuZUt1NGEtaW1nLTJfMTc3MDc5MjE1NzAwMF9uYTFmbl9aR0Z6YUdKdllYSmtMVzF2WTJ0MWNBLnBuZz94LW9zcy1wcm9jZXNzPWltYWdlL3Jlc2l6ZSx3XzE5MjAsaF8xOTIwL2Zvcm1hdCx3ZWJwL3F1YWxpdHkscV84MCIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc5ODc2MTYwMH19fV19&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=RSa~x6zS9OETkWWn8I~FeT6BMEj2fnqizz1yW1btGxeS8Tzbx5V9M0KQIvNoWvDLXPqjTyLsCzdV2-VhIjygTQBZb3U0uyZQuFoeTDhk0GS2LuXGEJnGLk0vM5cJ4tSXcxQvvVs5s99g4HZ2Okb4ivlD~3FNlHHGFDxAi51jzsa~9CI2qU4SQioZhnvAyOWbHeKYh91c0oA27jHeGPAGPP86lH3C7Wco7Kqhhrk1WlIyOJ3~Ij5PF4jn0cZMkWkPPpouXaBDVpi3M-ES3Qu1~nneLvIuy6T3ExqhPkG~eYoDj9yCRWI1~90x64UU5j49lMx1llFoM3pKyfh5tyo-2w__";

const stats = [
  { value: 144641, suffix: "+", label: "Videos Analyzed" },
  { value: 94, suffix: "%", label: "Velocity Accuracy" },
  { value: 14, suffix: "", label: "AI-Powered Tools" },
];

export default function Hero() {
  const { demoLoginEnabled, loginAsDemo, isAuthenticated } = useAuth();
  const [, navigate] = useLocation();
  const [signingIn, setSigningIn] = useState(false);

  const handleStart = async () => {
    if (isAuthenticated || !demoLoginEnabled) {
      navigate("/dashboard");
      return;
    }
    setSigningIn(true);
    try {
      await loginAsDemo();
      toast.success("Signed in as demo user");
      navigate("/dashboard");
    } catch (err) {
      toast.error("Could not sign in to demo account. Please try again.");
      console.error("demo login failed", err);
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <section className="relative min-h-screen flex flex-col justify-center overflow-hidden">
      {/* Background Image */}
      <div className="absolute inset-0 z-0">
        <img
          src={HERO_BG}
          alt=""
          className="w-full h-full object-cover opacity-40"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-background/60 via-background/40 to-background" />
      </div>

      {/* Dot Grid Overlay */}
      <div
        className="absolute inset-0 z-0 opacity-[0.03]"
        style={{
          backgroundImage: "radial-gradient(circle, oklch(0.92 0.01 260) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />

      {/* Content */}
      <div className="relative z-10 container pt-28 pb-12 md:pt-36 md:pb-20">
        {/* Badge */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="mb-6"
        >
          <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-medium font-[var(--font-mono)] tracking-wider uppercase bg-cyan-glow/10 text-cyan-glow border border-cyan-glow/20">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-glow animate-pulse" />
            Trained on 144,641+ YouTube Videos
          </span>
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2 }}
          className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold leading-[1.05] tracking-tight max-w-4xl"
        >
          Stop Guessing.{" "}
          <span className="gradient-text">Start Predicting</span>{" "}
          YouTube Success.
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.35 }}
          className="mt-6 text-lg md:text-xl text-muted-foreground max-w-2xl leading-relaxed"
        >
          ViewMagnet uses machine learning to predict your video's performance
          before you upload. Get niche-specific insights, not generic advice — because
          what works in Gaming <em>hurts</em> in Tech.
        </motion.p>

        {/* CTAs */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.5 }}
          className="mt-10 flex flex-wrap items-center gap-4"
        >
          <Button
            size="lg"
            onClick={handleStart}
            disabled={signingIn}
            className="text-base font-semibold bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 shadow-[0_0_30px_oklch(0.82_0.15_200/0.35)] h-12 px-8"
          >
            {signingIn ? (
              <>
                <Loader2 className="mr-2 w-4 h-4 animate-spin" />
                Setting up your demo…
              </>
            ) : (
              <>
                Start Free Trial
                <ArrowRight className="ml-2 w-4 h-4" />
              </>
            )}
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="text-base font-medium border-border/60 hover:bg-muted/50 h-12 px-8"
            onClick={() => document.querySelector("#how-it-works")?.scrollIntoView({ behavior: "smooth" })}
          >
            <Play className="mr-2 w-4 h-4" />
            See How It Works
          </Button>
        </motion.div>

        {/* Stats Row */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.65 }}
          className="mt-16 flex flex-wrap gap-8 md:gap-16"
        >
          {stats.map((stat) => (
            <div key={stat.label} className="flex flex-col">
              <span className="text-3xl md:text-4xl font-bold font-[var(--font-display)] text-foreground">
                <AnimatedCounter value={stat.value} suffix={stat.suffix} />
              </span>
              <span className="text-sm text-muted-foreground mt-1">{stat.label}</span>
            </div>
          ))}
        </motion.div>

        {/* Dashboard Preview */}
        <motion.div
          initial={{ opacity: 0, y: 60 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, delay: 0.8 }}
          className="mt-16 md:mt-20 relative"
        >
          <div className="relative rounded-xl overflow-hidden border border-border/40 shadow-2xl shadow-cyan-glow/5">
            <img
              src={DASHBOARD_IMG}
              alt="ViewMagnet Dashboard showing Magnet Score, view velocity charts, thumbnail analysis, and niche benchmarks"
              className="w-full h-auto"
            />
            {/* Gradient overlay at bottom */}
            <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-background to-transparent" />
          </div>
          {/* Glow behind the image */}
          <div className="absolute -inset-4 -z-10 rounded-2xl bg-gradient-to-r from-cyan-glow/10 via-transparent to-amber-glow/10 blur-3xl" />
        </motion.div>
      </div>
    </section>
  );
}

/*
 * Design: Signal Flow — Kinetic Minimalism
 * Navbar: Transparent, sticky, with glass-morphism on scroll
 * Colors: Deep charcoal bg, cyan accent, off-white text
 */
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { motion, useScroll, useTransform } from "framer-motion";
import { Loader2, Menu, X, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Link, useLocation } from "wouter";

const navLinks = [
  { label: "Features", href: "#features" },
  { label: "How It Works", href: "#how-it-works" },
  { label: "Pricing", href: "#pricing" },
  { label: "Compare", href: "#compare" },
];

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const { scrollY } = useScroll();
  const bgOpacity = useTransform(scrollY, [0, 100], [0, 0.85]);
  const borderOpacity = useTransform(scrollY, [0, 100], [0, 0.3]);
  const { demoLoginEnabled, loginAsDemo, isAuthenticated } = useAuth();
  const [, navigate] = useLocation();

  const scrollToSection = (href: string) => {
    setMobileOpen(false);
    const el = document.querySelector(href);
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  const handleGetStarted = async () => {
    setMobileOpen(false);
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
    <>
      <motion.header
        className="fixed top-0 left-0 right-0 z-50"
        style={{
          backgroundColor: useTransform(bgOpacity, (v) => `oklch(0.13 0.01 260 / ${v})`),
          borderBottom: useTransform(borderOpacity, (v) => `1px solid oklch(0.30 0.01 260 / ${v})`),
          backdropFilter: useTransform(scrollY, [0, 100], ["blur(0px)", "blur(20px)"]),
        }}
      >
        <nav className="container flex items-center justify-between h-16 md:h-18">
          {/* Logo */}
          <a
            href="#"
            className="flex items-center gap-2 group"
            onClick={(e) => {
              e.preventDefault();
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          >
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
              <Zap className="w-4.5 h-4.5 text-deep-charcoal" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-bold font-[var(--font-display)] tracking-tight text-foreground">
              View<span className="text-cyan-glow">Magnet</span>
            </span>
          </a>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-8">
            {navLinks.map((link) => (
              <button
                key={link.href}
                onClick={() => scrollToSection(link.href)}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors duration-200 font-medium"
              >
                {link.label}
              </button>
            ))}
          </div>

          {/* Desktop CTA */}
          <div className="hidden md:flex items-center gap-3">
            <Link href="/login">
              <Button
                variant="ghost"
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                Log in
              </Button>
            </Link>
            <Button
              onClick={handleGetStarted}
              disabled={signingIn}
              className="text-sm font-semibold bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 shadow-[0_0_20px_oklch(0.82_0.15_200/0.3)]"
            >
              {signingIn ? (
                <>
                  <Loader2 className="mr-2 w-4 h-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                "Get Started Free"
              )}
            </Button>
          </div>

          {/* Mobile Toggle */}
          <button
            className="md:hidden text-foreground p-2"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </nav>
      </motion.header>

      {/* Mobile Menu */}
      {mobileOpen && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed inset-0 top-16 z-40 bg-background/95 backdrop-blur-xl md:hidden"
        >
          <div className="container py-8 flex flex-col gap-6">
            {navLinks.map((link) => (
              <button
                key={link.href}
                onClick={() => scrollToSection(link.href)}
                className="text-lg font-medium text-foreground text-left"
              >
                {link.label}
              </button>
            ))}
            <div className="pt-4 border-t border-border flex flex-col gap-3">
              <Link href="/login">
                <Button variant="outline" className="w-full">Log in</Button>
              </Link>
              <Button
                onClick={handleGetStarted}
                disabled={signingIn}
                className="w-full bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
              >
                {signingIn ? (
                  <>
                    <Loader2 className="mr-2 w-4 h-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  "Get Started Free"
                )}
              </Button>
            </div>
          </div>
        </motion.div>
      )}
    </>
  );
}

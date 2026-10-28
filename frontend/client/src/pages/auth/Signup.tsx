import { useState } from "react";
import { Link, useLocation, useSearch } from "wouter";
import { useAuth } from "@/contexts/AuthContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, Eye, EyeOff, Magnet, Check } from "lucide-react";
import { toast } from "sonner";
import { SEOHead } from "@/components/seo";
import { createCheckout } from "@/lib/api";

const PAID_PLANS = ["starter", "pro", "agency"];

export default function Signup() {
  const [, navigate] = useLocation();
  const search = useSearch();
  const intendedPlan = new URLSearchParams(search).get("plan");
  const { signup, isLoading: authLoading } = useAuth();
  
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  const passwordChecks = {
    length: password.length >= 8,
    match: password === confirmPassword && password.length > 0,
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!email || !password || !confirmPassword) {
      toast.error("Please fill in all fields");
      return;
    }

    if (password !== confirmPassword) {
      toast.error("Passwords don't match");
      return;
    }

    if (password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      // Get referral code from localStorage (captured from URL)
      const referralCode = localStorage.getItem('ViewMagnet_referral_code');
      
      await signup({ 
        email, 
        password, 
        name: name || undefined,
        referral_code: referralCode || undefined,
      });
      
      // Clear referral code after successful signup
      localStorage.removeItem('ViewMagnet_referral_code');
      
      toast.success("Account created successfully!");

      // If they came from a paid-plan CTA, continue straight to checkout.
      if (intendedPlan && PAID_PLANS.includes(intendedPlan)) {
        try {
          const url = await createCheckout(intendedPlan);
          window.location.href = url;
          return;
        } catch {
          // Billing not configured / checkout failed — land them in the app
          // where they can upgrade from Settings later.
          toast.message("You can upgrade anytime from Settings → Billing.");
        }
      }

      navigate("/dashboard");
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Failed to create account");
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-deep-charcoal">
        <Loader2 className="w-8 h-8 animate-spin text-cyan-glow" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-deep-charcoal to-gunmetal p-4">
      <SEOHead
        title="Create Account"
        description="Sign up for ViewMagnet and start optimizing your YouTube videos with AI-powered insights."
        noIndex={true}
      />
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Magnet className="w-8 h-8 text-cyan-glow" />
            <span className="text-2xl font-bold font-[var(--font-display)] text-foreground">
              ViewMagnet
            </span>
          </div>
          <p className="text-muted-foreground">
            Create your account to get started
          </p>
        </div>

        <Card className="bg-card border-border/50">
          <CardHeader>
            <CardTitle className="text-xl text-center">Create account</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name (optional)</Label>
                <Input
                  id="name"
                  type="text"
                  placeholder="Your name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="bg-secondary/50 border-border/50"
                  autoComplete="name"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="bg-secondary/50 border-border/50"
                  autoComplete="email"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="bg-secondary/50 border-border/50 pr-10"
                    autoComplete="new-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="bg-secondary/50 border-border/50"
                  autoComplete="new-password"
                  required
                />
              </div>

              {password.length > 0 && (
                <div className="space-y-1.5 text-xs">
                  <div className={`flex items-center gap-2 ${passwordChecks.length ? "text-emerald-400" : "text-muted-foreground"}`}>
                    <Check className={`w-3 h-3 ${passwordChecks.length ? "opacity-100" : "opacity-30"}`} />
                    At least 8 characters
                  </div>
                  {confirmPassword.length > 0 && (
                    <div className={`flex items-center gap-2 ${passwordChecks.match ? "text-emerald-400" : "text-destructive"}`}>
                      <Check className={`w-3 h-3 ${passwordChecks.match ? "opacity-100" : "opacity-30"}`} />
                      Passwords match
                    </div>
                  )}
                </div>
              )}

              <Button
                type="submit"
                className="w-full bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                disabled={loading || !passwordChecks.length || (confirmPassword.length > 0 && !passwordChecks.match)}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Create account"
                )}
              </Button>
            </form>

            <div className="mt-6 text-center text-sm">
              <span className="text-muted-foreground">Already have an account? </span>
              <Link href="/login" className="text-cyan-glow hover:underline">
                Sign in
              </Link>
            </div>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          By creating an account, you agree to our{" "}
          <Link href="/terms" className="text-cyan-glow hover:underline">Terms of Service</Link>{" "}
          and{" "}
          <Link href="/privacy" className="text-cyan-glow hover:underline">Privacy Policy</Link>
        </p>
      </div>
    </div>
  );
}





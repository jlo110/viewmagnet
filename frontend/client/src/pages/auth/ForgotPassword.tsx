import { useState } from "react";
import { Link } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, Magnet, MailCheck, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { forgotPassword } from "@/lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      toast.error("Please enter your email");
      return;
    }
    setLoading(true);
    try {
      await forgotPassword(email);
      setSent(true);
    } catch {
      // The backend returns a generic success even for unknown emails, so a
      // thrown error here is a network/server issue, not "email not found".
      toast.error("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-deep-charcoal to-gunmetal p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Magnet className="w-8 h-8 text-cyan-glow" />
            <span className="text-2xl font-bold font-[var(--font-display)] text-foreground">
              ViewMagnet
            </span>
          </div>
          <p className="text-muted-foreground">Reset your password</p>
        </div>

        <Card className="bg-card border-border/50">
          {sent ? (
            <CardContent className="pt-6 text-center space-y-4">
              <div className="flex justify-center">
                <div className="w-12 h-12 rounded-full bg-cyan-glow/10 flex items-center justify-center">
                  <MailCheck className="w-6 h-6 text-cyan-glow" />
                </div>
              </div>
              <CardTitle className="text-lg">Check your inbox</CardTitle>
              <p className="text-sm text-muted-foreground">
                If an account exists for <span className="text-foreground">{email}</span>, we've
                sent a link to reset your password. The link expires in 1 hour.
              </p>
              <Button asChild variant="outline" className="w-full">
                <Link href="/login">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back to sign in
                </Link>
              </Button>
            </CardContent>
          ) : (
            <>
              <CardHeader>
                <CardTitle className="text-xl text-center">Forgot password?</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-4 text-center">
                  Enter your email and we'll send you a link to reset your password.
                </p>
                <form onSubmit={handleSubmit} className="space-y-4">
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
                    />
                  </div>
                  <Button
                    type="submit"
                    className="w-full bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                    disabled={loading}
                  >
                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Send reset link"}
                  </Button>
                </form>
                <div className="mt-6 text-center text-sm">
                  <Link href="/login" className="text-cyan-glow hover:underline">
                    Back to sign in
                  </Link>
                </div>
              </CardContent>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

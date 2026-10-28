import { useEffect, useRef, useState } from "react";
import { Link, useSearch } from "wouter";
import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Magnet, CheckCircle2, XCircle } from "lucide-react";
import { verifyEmail } from "@/lib/api";

type Status = "verifying" | "success" | "error";

export default function VerifyEmail() {
  const search = useSearch();
  const token = new URLSearchParams(search).get("token") ?? "";
  const [status, setStatus] = useState<Status>("verifying");
  // StrictMode double-invokes effects in dev; guard so we only POST once.
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    if (!token) {
      setStatus("error");
      return;
    }
    verifyEmail(token)
      .then(() => setStatus("success"))
      .catch(() => setStatus("error"));
  }, [token]);

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
        </div>

        <Card className="bg-card border-border/50">
          <CardContent className="pt-6 text-center space-y-4">
            {status === "verifying" && (
              <>
                <Loader2 className="w-8 h-8 animate-spin text-cyan-glow mx-auto" />
                <CardTitle className="text-lg">Verifying your email…</CardTitle>
              </>
            )}
            {status === "success" && (
              <>
                <div className="flex justify-center">
                  <div className="w-12 h-12 rounded-full bg-emerald-400/10 flex items-center justify-center">
                    <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                  </div>
                </div>
                <CardTitle className="text-lg">Email verified</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Your email is confirmed. You're all set.
                </p>
                <Button
                  asChild
                  className="w-full bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                >
                  <Link href="/dashboard">Go to dashboard</Link>
                </Button>
              </>
            )}
            {status === "error" && (
              <>
                <div className="flex justify-center">
                  <div className="w-12 h-12 rounded-full bg-rose-500/10 flex items-center justify-center">
                    <XCircle className="w-6 h-6 text-rose-400" />
                  </div>
                </div>
                <CardTitle className="text-lg">Verification failed</CardTitle>
                <p className="text-sm text-muted-foreground">
                  This verification link is invalid or has already been used. You can request a new
                  one from your dashboard settings.
                </p>
                <Button asChild variant="outline" className="w-full">
                  <Link href="/dashboard">Go to dashboard</Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

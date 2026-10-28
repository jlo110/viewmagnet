/*
 * Soft email-verification banner.
 *
 * Decision (per product): verification is SOFT — unverified users keep full
 * access (better trial conversion), but we nudge them to confirm. The banner
 * is dismissible for the session and only shows when the auth context knows
 * the user is explicitly unverified (is_verified === false). Users from older
 * tokens that don't carry the flag (undefined) are not nagged.
 */
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { resendVerification } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { MailWarning, X, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function VerificationBanner() {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  if (dismissed || !user || user.is_verified !== false) return null;

  const handleResend = async () => {
    setSending(true);
    try {
      await resendVerification();
      setSent(true);
      toast.success("Verification email sent — check your inbox.");
    } catch {
      toast.error("Couldn't send the email. Please try again shortly.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mx-6 mt-4 flex items-center gap-3 rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-2.5 text-sm">
      <MailWarning className="h-4 w-4 shrink-0 text-amber-400" />
      <p className="flex-1 text-foreground/90">
        Please verify your email address to secure your account.
      </p>
      {!sent && (
        <Button
          size="sm"
          variant="outline"
          className="h-7 border-amber-400/40 text-xs"
          onClick={handleResend}
          disabled={sending}
        >
          {sending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Resend email"}
        </Button>
      )}
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="text-muted-foreground hover:text-foreground"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

/*
 * API Tokens — Personal Access Token management for the MCP server,
 * CI scripts, and any other automation that wants to call ViewMagnet on
 * behalf of a user without holding their password.
 *
 * UX rules:
 * - The plaintext secret is shown ONCE in a reveal panel and never
 *   reconstructable thereafter. Make it loud, obvious, and copy-friendly.
 * - List view is functional, not flashy — name, prefix (last 4 visible),
 *   scopes, created, last used, expires, revoke. Revoked tokens stay in
 *   the table greyed out so the user can audit who-saw-what.
 * - Empty state doubles as the MCP server pitch: "Install ViewMagnet in
 *   Claude / Cursor / Cline in one command."
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  createPersonalAccessToken,
  listPersonalAccessTokens,
  revokePersonalAccessToken,
  PAT_SCOPES,
  type PersonalAccessToken,
  type PersonalAccessTokenWithSecret,
} from "@/lib/api";

type ScopeId = "read" | "write" | "admin";

const EXPIRY_OPTIONS: { id: string; label: string; days: number | null }[] = [
  { id: "30", label: "30 days", days: 30 },
  { id: "90", label: "90 days", days: 90 },
  { id: "365", label: "1 year", days: 365 },
  { id: "never", label: "No expiration", days: null },
];

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelativeTime(value: string | null): string {
  if (!value) return "Never";
  const then = new Date(value).getTime();
  const now = Date.now();
  const diffSec = Math.max(0, Math.round((now - then) / 1000));
  if (diffSec < 60) return "Just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86_400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 30 * 86_400) return `${Math.floor(diffSec / 86_400)}d ago`;
  return formatTimestamp(value);
}

function tokenStatus(t: PersonalAccessToken): "revoked" | "expired" | "active" {
  if (t.revoked_at) return "revoked";
  if (t.expires_at && new Date(t.expires_at).getTime() <= Date.now())
    return "expired";
  return "active";
}

export default function ApiTokens() {
  const [tokens, setTokens] = useState<PersonalAccessToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [revealToken, setRevealToken] =
    useState<PersonalAccessTokenWithSecret | null>(null);

  async function refresh() {
    try {
      const rows = await listPersonalAccessTokens();
      setTokens(rows);
      setLoadError(null);
    } catch (err) {
      console.error("Failed to load API tokens:", err);
      setLoadError(
        err instanceof Error
          ? err.message
          : "Could not load tokens. Refresh to try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleRevoke(t: PersonalAccessToken) {
    if (
      !window.confirm(
        `Revoke "${t.name}"? Any agent or script using this token will stop working immediately.`,
      )
    ) {
      return;
    }
    try {
      await revokePersonalAccessToken(t.id);
      toast.success(`"${t.name}" revoked.`);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not revoke token.",
      );
    }
  }

  const activeCount = useMemo(
    () => tokens.filter((t) => tokenStatus(t) === "active").length,
    [tokens],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
            API Tokens
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Personal Access Tokens let AI agents and scripts call ViewMagnet on
            your behalf without your password.{" "}
            <Link
              href="/mcp"
              className="text-cyan-glow hover:underline inline-flex items-center gap-1"
            >
              Install the MCP server
              <ExternalLink className="w-3 h-3" />
            </Link>
          </p>
        </div>
        <Button
          onClick={() => setCreateOpen(true)}
          className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
        >
          <Plus className="w-4 h-4 mr-1.5" />
          Generate token
        </Button>
      </div>

      {loadError && (
        <Card className="border-amber-glow/40 bg-amber-glow/5">
          <CardContent className="py-3 text-sm text-amber-glow flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" />
            {loadError}
          </CardContent>
        </Card>
      )}

      {loading ? (
        <Card className="bg-card border-border/50">
          <CardContent className="py-12 flex justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-cyan-glow" />
          </CardContent>
        </Card>
      ) : tokens.length === 0 ? (
        <EmptyState onCreate={() => setCreateOpen(true)} />
      ) : (
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-cyan-glow" />
              {activeCount} active
              {tokens.length > activeCount
                ? `, ${tokens.length - activeCount} revoked / expired`
                : null}
            </CardTitle>
            <CardDescription className="text-xs">
              Newest first. Click revoke to permanently disable a token.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border/40">
              {tokens.map((t) => (
                <TokenRow key={t.id} token={t} onRevoke={handleRevoke} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <CreateTokenDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(token) => {
          setRevealToken(token);
          setCreateOpen(false);
          refresh();
        }}
      />

      <RevealTokenDialog
        token={revealToken}
        onClose={() => setRevealToken(null)}
      />
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <Card className="bg-card border-border/50">
      <CardContent className="py-12 text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-full bg-cyan-glow/10 flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-cyan-glow" />
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold">
            No API tokens yet
          </h2>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Generate one to install the ViewMagnet MCP server in Claude
            Desktop, Cursor, or Cline. Your AI agent will be able to analyze
            videos, generate scripts, and score hooks for you.
          </p>
        </div>
        <div className="flex items-center justify-center gap-2 pt-1">
          <Button
            onClick={onCreate}
            className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Generate your first token
          </Button>
          <Button variant="outline" asChild>
            <Link href="/mcp">
              <ExternalLink className="w-4 h-4 mr-1.5" />
              Learn about the MCP server
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function TokenRow({
  token,
  onRevoke,
}: {
  token: PersonalAccessToken;
  onRevoke: (t: PersonalAccessToken) => void;
}) {
  const status = tokenStatus(token);
  const isDead = status !== "active";
  return (
    <div
      className={`px-4 py-3 flex items-center gap-4 ${
        isDead ? "opacity-50" : ""
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-foreground truncate">
            {token.name}
          </span>
          {status === "revoked" && (
            <Badge variant="outline" className="text-[10px] border-destructive/40 text-destructive">
              Revoked
            </Badge>
          )}
          {status === "expired" && (
            <Badge variant="outline" className="text-[10px] border-amber-glow/40 text-amber-glow">
              Expired
            </Badge>
          )}
          {token.scopes.map((s) => (
            <Badge
              key={s}
              variant="outline"
              className="text-[10px] uppercase tracking-wider"
            >
              {s}
            </Badge>
          ))}
        </div>
        <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3 flex-wrap">
          <code className="font-mono">{token.prefix}_••••</code>
          <span>Created {formatTimestamp(token.created_at)}</span>
          <span>Last used: {formatRelativeTime(token.last_used_at)}</span>
          {token.expires_at && (
            <span>Expires {formatTimestamp(token.expires_at)}</span>
          )}
        </div>
      </div>
      {!isDead && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onRevoke(token)}
          className="border-destructive/40 text-destructive hover:bg-destructive/10"
        >
          <Trash2 className="w-3.5 h-3.5 mr-1.5" />
          Revoke
        </Button>
      )}
    </div>
  );
}

function CreateTokenDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (t: PersonalAccessTokenWithSecret) => void;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ScopeId[]>(["read"]);
  const [expiry, setExpiry] = useState<string>("90");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setName("");
      setScopes(["read"]);
      setExpiry("90");
      setSubmitting(false);
    }
  }, [open]);

  function toggleScope(id: ScopeId) {
    setScopes((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  async function handleSubmit() {
    if (!name.trim()) {
      toast.error("Give this token a name so you can recognize it later.");
      return;
    }
    if (scopes.length === 0) {
      toast.error("Select at least one scope.");
      return;
    }
    setSubmitting(true);
    try {
      const expiryOpt = EXPIRY_OPTIONS.find((o) => o.id === expiry);
      const token = await createPersonalAccessToken({
        name: name.trim(),
        scopes,
        expires_in_days: expiryOpt?.days ?? undefined,
      });
      onCreated(token);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not create token.",
      );
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Generate API token</DialogTitle>
          <DialogDescription>
            You'll see the token once on the next screen. Copy it then — we
            can't show it again.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Name
            </label>
            <Input
              autoFocus
              placeholder="MacBook Claude, CI pipeline, etc."
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Scopes
            </label>
            <div className="space-y-2 rounded-md border border-border/50 bg-secondary/30 p-3">
              {PAT_SCOPES.map((scope) => (
                <label
                  key={scope.id}
                  className="flex items-start gap-2 cursor-pointer"
                >
                  <Checkbox
                    checked={scopes.includes(scope.id)}
                    onCheckedChange={() => toggleScope(scope.id)}
                    className="mt-0.5"
                  />
                  <div className="text-sm">
                    <div className="font-medium text-foreground">
                      {scope.label}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {scope.description}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Expiration
            </label>
            <Select value={expiry} onValueChange={setExpiry}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPIRY_OPTIONS.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground">
              Shorter is safer. You can revoke at any time.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={submitting}
            className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                Creating…
              </>
            ) : (
              "Generate token"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevealTokenDialog({
  token,
  onClose,
}: {
  token: PersonalAccessTokenWithSecret | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!token) setCopied(false);
  }, [token]);

  async function copy() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
      toast.success("Token copied to clipboard.");
    } catch {
      toast.error("Could not copy — select the field and copy manually.");
    }
  }

  return (
    <Dialog
      open={!!token}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="w-4 h-4 text-cyan-glow" />
            Token created
          </DialogTitle>
          <DialogDescription className="text-amber-glow">
            <AlertTriangle className="w-3.5 h-3.5 inline-block mr-1 align-text-bottom" />
            Copy this token now. It will not be shown again.
          </DialogDescription>
        </DialogHeader>
        {token && (
          <div className="space-y-4">
            <div className="rounded-md border border-cyan-glow/30 bg-cyan-glow/5 p-3 font-mono text-xs break-all">
              {token.token}
            </div>
            <Button
              onClick={copy}
              className="w-full bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
            >
              {copied ? (
                <>
                  <Check className="w-4 h-4 mr-1.5" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4 mr-1.5" />
                  Copy token
                </>
              )}
            </Button>
            <Separator className="bg-border/40" />
            <div className="text-xs text-muted-foreground space-y-2">
              <p className="font-medium text-foreground">Use it like this:</p>
              <div className="rounded-md bg-secondary/40 p-2 font-mono whitespace-pre-wrap break-all">
                {`Authorization: Bearer ${token.token}`}
              </div>
              <p>
                Or install it into Claude / Cursor / Cline with{" "}
                <code className="font-mono">npx viewmagnet-mcp install</code> —
                the installer will prompt for this token and write it to the
                right config file.
              </p>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            I've copied it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

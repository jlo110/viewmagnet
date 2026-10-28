/*
 * Distribution Hub: multi-account, cross-platform publishing.
 * - Connected accounts grid (YouTube, TikTok, Instagram, Twitter)
 * - Add-account dialog
 * - Jobs history table
 * - OAuth setup tip card per platform
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Network,
  Plus,
  Youtube,
  Instagram,
  Twitter,
  Music2,
  ExternalLink,
  Trash2,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Info,
  RefreshCw,
  Send,
  Sparkles,
  Palette,
} from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import {
  listConnectedAccounts,
  connectAccount,
  removeConnectedAccount,
  getDistributionSetupStatus,
  listDistributionJobs,
  startYouTubeAuth,
  startTikTokAuth,
  startInstagramAuth,
  publishDistribution,
  getStudioProject,
  type ConnectedAccountSummary,
  type DistributionJobSummary,
  type SetupStatusResponse,
  type DistributionPlatform,
} from "@/lib/api";
import { getUserBrandKit, type UserBrandKit } from "@/studio/api";
import { readDistributionDeepLink } from "@/lib/deepLinks";

const PLATFORM_CONFIG: Record<
  DistributionPlatform,
  { label: string; icon: typeof Youtube; gradient: string }
> = {
  youtube: { label: "YouTube", icon: Youtube, gradient: "from-red-500/20 to-red-700/20" },
  tiktok: { label: "TikTok", icon: Music2, gradient: "from-pink-500/20 to-purple-500/20" },
  instagram: { label: "Instagram", icon: Instagram, gradient: "from-pink-400/20 to-amber-400/20" },
  twitter: { label: "Twitter / X", icon: Twitter, gradient: "from-cyan-400/20 to-blue-500/20" },
};

const STATUS_BADGE: Record<string, { className: string; label: string }> = {
  pending: { className: "bg-muted-foreground/10 text-muted-foreground", label: "Pending" },
  running: { className: "bg-cyan-glow/10 text-cyan-glow", label: "Running" },
  completed: { className: "bg-emerald-400/10 text-emerald-400", label: "Completed" },
  partial: { className: "bg-amber-glow/10 text-amber-glow", label: "Partial" },
  failed: { className: "bg-destructive/10 text-destructive", label: "Failed" },
  success: { className: "bg-emerald-400/10 text-emerald-400", label: "Success" },
};

export default function DistributionHub() {
  const [accounts, setAccounts] = useState<ConnectedAccountSummary[]>([]);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(null);
  const [jobs, setJobs] = useState<DistributionJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshingJobs, setRefreshingJobs] = useState(false);

  // Add account dialog state
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newPlatform, setNewPlatform] = useState<DistributionPlatform>("instagram");
  const [newHandle, setNewHandle] = useState("");
  const [newAccountId, setNewAccountId] = useState("");
  const [newToken, setNewToken] = useState("");

  // Disconnect-confirmation dialog (replaces window.confirm).
  const [pendingRemoval, setPendingRemoval] = useState<ConnectedAccountSummary | null>(null);
  const [removing, setRemoving] = useState(false);

  // ---------------------------------------------------------------------
  // Publish-from-Studio panel. Hydrated from `?renderUrl=&title=&clipKey=`
  // when the user arrives via the cross-tool deep link (e.g. Drafts page
  // "publish" button). See `lib/deepLinks.ts`.
  //
  // Why this lives in DistributionHub and not Studio: the publish form
  // needs the user's connected accounts, which DistributionHub already
  // loads. Routing through here keeps connect-flow next to publish-flow.
  // ---------------------------------------------------------------------
  const [, navigate] = useLocation();
  const [publishRenderUrl, setPublishRenderUrl] = useState<string | null>(null);
  const [publishTitle, setPublishTitle] = useState("");
  const [publishCaption, setPublishCaption] = useState("");
  const [publishHashtags, setPublishHashtags] = useState("");
  /** Optional thumbnail URL surfaced as a publish input. Pre-filled
   *  from the cross-tool deep link (Week 9 Connected Tools), edited
   *  by the user before submit. */
  const [publishThumbnailUrl, setPublishThumbnailUrl] = useState("");
  /** Studio Project id (when the user arrived from a project render
   *  vs a single-clip render). Used to look up project-scoped brand
   *  kit / description fallbacks. */
  const [publishProjectId, setPublishProjectId] = useState<number | null>(null);
  const [publishTargets, setPublishTargets] = useState<Set<number>>(new Set());
  const [publishing, setPublishing] = useState(false);
  const [brandKit, setBrandKit] = useState<UserBrandKit | null>(null);

  // Show toast when returning from a TikTok / Instagram OAuth callback.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tiktok_connected") === "true") {
      toast.success("TikTok account connected!");
      window.history.replaceState({}, "", window.location.pathname);
      listConnectedAccounts().then(setAccounts).catch(() => {});
    } else if (params.get("tiktok_error") === "true") {
      toast.error("TikTok connection failed. Please try again.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("instagram_connected") === "true") {
      toast.success("Instagram account connected!");
      window.history.replaceState({}, "", window.location.pathname);
      listConnectedAccounts().then(setAccounts).catch(() => {});
    } else if (params.get("instagram_error") === "true") {
      toast.error("Instagram connection failed. Please try again.");
      window.history.replaceState({}, "", window.location.pathname);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Read deep-link params + load the user's brand kit so the publish
  // form can "auto-apply brand" (visual brand is already burned into
  // the render at this point; what we still surface is the brand color +
  // logo as a confidence cue, and we leave room for a future
  // caption-signature field on UserBrandKit).
  useEffect(() => {
    const link = readDistributionDeepLink();
    if (link.renderUrl) {
      setPublishRenderUrl(link.renderUrl);
      setPublishTitle(link.title ?? "");
      // Prefer the project/clip description as the seed caption —
      // it's the long-form text the user composed alongside the
      // edit. Fall back to the title for backward compat with
      // single-clip handoffs that don't carry a description yet.
      setPublishCaption(link.description ?? link.title ?? "");
      setPublishThumbnailUrl(link.thumbnailUrl ?? "");
      setPublishProjectId(link.projectId ?? null);
    }
    // Always load the brand kit so we can show the "brand applied" badge.
    getUserBrandKit()
      .then(setBrandKit)
      .catch(() => setBrandKit(null));
  }, []);

  // When the deep link references a Studio Project, hydrate the
  // project-level brand-kit hashtags as a fallback (alongside the
  // user-level brand kit). Project-scoped hashtags win over global
  // ones because they're more contextual to this specific render.
  useEffect(() => {
    if (publishProjectId == null) return;
    let cancelled = false;
    (async () => {
      try {
        const project = await getStudioProject(publishProjectId);
        if (cancelled) return;
        const projectHashtags = (project.brand_kit?.default_hashtags ?? "")
          .toString()
          .trim();
        if (projectHashtags && !publishHashtags.trim()) {
          setPublishHashtags(projectHashtags);
        }
        // If no explicit description came through but the project
        // has one, surface that into the caption.
        if (project.description && !publishCaption.trim()) {
          setPublishCaption(project.description);
        }
      } catch {
        // Project may have been deleted between render + publish;
        // silently fall back to user-level brand kit only.
      }
    })();
    return () => {
      cancelled = true;
    };
    // We deliberately don't depend on publishCaption/publishHashtags
    // so the hydration only runs once per project handoff (and not
    // every keystroke).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [publishProjectId]);

  // Auto-select all active connected accounts as publish targets
  // whenever the accounts list refreshes. This is the common case —
  // the user typically wants to fan out to everything they connected.
  useEffect(() => {
    if (accounts.length === 0) return;
    const activeIds = accounts.filter((a) => a.is_active).map((a) => a.id);
    setPublishTargets((cur) => {
      if (cur.size > 0) return cur; // Don't clobber an in-progress selection.
      return new Set(activeIds);
    });
  }, [accounts]);

  const togglePublishTarget = (id: number) => {
    setPublishTargets((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const dismissPublishPanel = () => {
    setPublishRenderUrl(null);
    setPublishTitle("");
    setPublishCaption("");
    setPublishHashtags("");
    setPublishThumbnailUrl("");
    setPublishProjectId(null);
    // Clear the deep-link params from the URL so a refresh doesn't
    // re-open the panel after the user dismissed it.
    navigate("/dashboard/distribution", { replace: true });
  };

  const handlePublishSubmit = async () => {
    if (!publishRenderUrl) return;
    if (!publishTitle.trim()) {
      toast.error("Add a title");
      return;
    }
    if (publishTargets.size === 0) {
      toast.error("Pick at least one account to publish to");
      return;
    }
    setPublishing(true);
    try {
      // Apply brand voice (caption signature + default hashtags) so
      // every cross-post carries the user's stock sign-off without
      // them having to retype it for each platform. This is the
      // *voice* leg of the brand-kit auto-apply story (the visual
      // leg already runs inside the Studio render pipeline).
      const userTypedHashtags = publishHashtags
        .split(/[,\s]+/)
        .map((h) => h.trim().replace(/^#/, ""))
        .filter(Boolean);
      const brandHashtags = (brandKit?.default_hashtags ?? "")
        .split(/[,\s]+/)
        .map((h) => h.trim().replace(/^#/, ""))
        .filter(Boolean);
      // Dedupe case-insensitively while preserving the user's typed
      // order (their on-the-fly hashtags trump the default ones).
      const seen = new Set<string>();
      const hashtags: string[] = [];
      for (const tag of [...userTypedHashtags, ...brandHashtags]) {
        const key = tag.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        hashtags.push(tag);
      }

      const baseCaption = publishCaption.trim() || publishTitle.trim();
      const signature = (brandKit?.caption_signature ?? "").trim();
      // Only append the signature if the user hasn't already typed it
      // (case-insensitive substring check). Avoids double-stamping when
      // the caption was previously edited inside Studio.
      const finalCaption =
        signature && !baseCaption.toLowerCase().includes(signature.toLowerCase())
          ? `${baseCaption}\n\n${signature}`
          : baseCaption;

      const result = await publishDistribution({
        title: publishTitle.trim(),
        base_caption: finalCaption,
        target_account_ids: Array.from(publishTargets),
        video_url: publishRenderUrl,
        hashtags: hashtags.length > 0 ? hashtags : undefined,
        vary_captions: true,
        thumbnail_url: publishThumbnailUrl.trim() || undefined,
      });
      toast.success(`Publishing to ${result.target_count} account(s)`);
      dismissPublishPanel();
      // Pop the new job to the top of the history so the user sees it.
      await refreshJobs();
    } catch (err) {
      console.error("Failed to publish:", err);
      toast.error("Failed to publish");
    } finally {
      setPublishing(false);
    }
  };

  const loadAll = useCallback(async () => {
    try {
      const [acc, status, jobsList] = await Promise.all([
        listConnectedAccounts(),
        getDistributionSetupStatus(),
        listDistributionJobs(20),
      ]);
      setAccounts(acc);
      setSetupStatus(status);
      setJobs(jobsList);
    } catch (err) {
      console.error("Failed to load distribution hub:", err);
      toast.error("Failed to load distribution data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const refreshJobs = async () => {
    setRefreshingJobs(true);
    try {
      const jobsList = await listDistributionJobs(20);
      setJobs(jobsList);
    } finally {
      setRefreshingJobs(false);
    }
  };

  const handleAdd = async () => {
    if (!newHandle.trim() || !newAccountId.trim() || !newToken.trim()) {
      toast.error("Fill in handle, account ID, and access token");
      return;
    }
    setAdding(true);
    try {
      await connectAccount({
        platform: newPlatform,
        platform_account_id: newAccountId,
        handle: newHandle,
        access_token: newToken,
      });
      toast.success(`Connected @${newHandle}`);
      setAddOpen(false);
      setNewHandle("");
      setNewAccountId("");
      setNewToken("");
      await loadAll();
    } catch (err) {
      console.error("Failed to connect account:", err);
      toast.error("Failed to connect account");
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = (account: ConnectedAccountSummary) => {
    setPendingRemoval(account);
  };

  const confirmRemove = async () => {
    if (!pendingRemoval) return;
    setRemoving(true);
    try {
      await removeConnectedAccount(pendingRemoval.id);
      toast.success(`Disconnected @${pendingRemoval.handle}`);
      setPendingRemoval(null);
      await loadAll();
    } catch (err) {
      console.error("Failed to remove account:", err);
      toast.error("Failed to disconnect account");
    } finally {
      setRemoving(false);
    }
  };

  const handleYouTubeOAuth = async () => {
    try {
      const { auth_url } = await startYouTubeAuth();
      window.location.href = auth_url;
    } catch (err) {
      console.error("Failed to start YouTube OAuth:", err);
      toast.error("Failed to start YouTube OAuth");
    }
  };

  const handleTikTokOAuth = async () => {
    try {
      const { auth_url } = await startTikTokAuth();
      window.location.href = auth_url;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        toast.error("TikTok OAuth not configured — set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET.");
      } else {
        console.error("Failed to start TikTok OAuth:", err);
        toast.error("Failed to start TikTok OAuth");
      }
    }
  };

  const handleInstagramOAuth = async () => {
    try {
      const { auth_url } = await startInstagramAuth();
      window.location.href = auth_url;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        toast.error("Instagram OAuth not configured — set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET.");
      } else {
        console.error("Failed to start Instagram OAuth:", err);
        toast.error("Failed to start Instagram OAuth");
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
            <Network className="w-6 h-6 text-cyan-glow" />
            Distribution Hub
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage connected accounts across YouTube, TikTok, Instagram, and X. Push one clip to many accounts in one click.
          </p>
        </div>
        <Button
          className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
          onClick={() => setAddOpen(true)}
        >
          <Plus className="w-4 h-4 mr-2" />
          Connect Account
        </Button>
      </div>

      {/*
        Publish-from-Studio panel — shown when the user arrives via a
        cross-tool deep link (Drafts page → "Publish" button). Renders
        the finished render alongside a publish form with title +
        caption + per-account targeting. The brand kit is fetched on
        mount so we can show a visible "brand applied" badge with the
        user's logo + accent color — reinforcing that the breadth play
        actually wires through end-to-end.
      */}
      {publishRenderUrl && (
        <Card className="bg-gradient-to-br from-cyan-glow/5 to-violet-500/5 border-cyan-glow/30">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Send className="w-4 h-4 text-cyan-glow" />
                  Publish your Studio render
                </CardTitle>
                <p className="text-xs text-muted-foreground mt-1">
                  Caption variants are generated per-platform; brand visuals
                  are already baked into the render.
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={dismissPublishPanel}
                disabled={publishing}
                className="text-muted-foreground text-xs h-7"
              >
                Dismiss
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
              <div className="aspect-[9/16] md:aspect-video rounded-lg overflow-hidden bg-black/60 border border-border/40">
                <video
                  src={publishRenderUrl}
                  preload="metadata"
                  muted
                  playsInline
                  controls
                  className="w-full h-full object-cover"
                />
              </div>
              <div className="space-y-3">
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                    Title
                  </label>
                  <Input
                    value={publishTitle}
                    onChange={(e) => setPublishTitle(e.target.value)}
                    placeholder="Used as the post title on YouTube"
                    disabled={publishing}
                    className="mt-1 bg-secondary/30 border-border/50"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                    Caption
                  </label>
                  <Textarea
                    value={publishCaption}
                    onChange={(e) => setPublishCaption(e.target.value)}
                    placeholder="One base caption — we'll auto-vary per platform"
                    disabled={publishing}
                    rows={3}
                    className="mt-1 bg-secondary/30 border-border/50 text-sm"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                    Hashtags <span className="text-muted-foreground/60">(comma or space separated)</span>
                  </label>
                  <Input
                    value={publishHashtags}
                    onChange={(e) => setPublishHashtags(e.target.value)}
                    placeholder="#shorts #creator"
                    disabled={publishing}
                    className="mt-1 bg-secondary/30 border-border/50"
                  />
                </div>
                {/* Optional thumbnail override — pre-filled when an
                    upstream tool passed ``?thumbnailUrl=`` on the deep
                    link (Week 9 Connected Tools). Most platforms
                    auto-generate a thumbnail from the first frame;
                    creators with their own custom thumbnail can
                    override here. */}
                <div>
                  <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                    Custom thumbnail URL <span className="text-muted-foreground/60">(optional)</span>
                  </label>
                  <Input
                    type="url"
                    value={publishThumbnailUrl}
                    onChange={(e) => setPublishThumbnailUrl(e.target.value)}
                    placeholder="https://..."
                    disabled={publishing}
                    className="mt-1 bg-secondary/30 border-border/50"
                  />
                </div>
              </div>
            </div>

            {/* Brand applied confidence cue. Only renders when the user
                has a real brand kit set — keeps the panel honest for
                first-time users. */}
            {brandKit && brandKit.exists && (
              <div className="flex items-center gap-3 p-3 rounded-lg bg-secondary/30 border border-border/40">
                <div className="flex items-center gap-2">
                  {brandKit.logo_url ? (
                    <img
                      src={brandKit.logo_url}
                      alt=""
                      className="w-8 h-8 rounded object-contain bg-white/5 p-0.5"
                    />
                  ) : (
                    <div
                      className="w-8 h-8 rounded"
                      style={{
                        background:
                          brandKit.primary_color ||
                          brandKit.accent_color ||
                          "var(--cyan-glow)",
                      }}
                    />
                  )}
                  <div>
                    <p className="text-xs font-medium text-foreground flex items-center gap-1.5">
                      <Sparkles className="w-3 h-3 text-cyan-glow" />
                      Brand kit applied
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {brandKit.caption_signature || brandKit.default_hashtags
                        ? "Visuals baked into the render; sign-off + default hashtags merge into the caption automatically."
                        : "Logo, colors, and fonts from your Brand panel are baked into this render."}
                    </p>
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-1">
                  {brandKit.primary_color && (
                    <span
                      className="w-3 h-3 rounded-full border border-border/30"
                      style={{ background: brandKit.primary_color }}
                      title={`Primary ${brandKit.primary_color}`}
                    />
                  )}
                  {brandKit.accent_color && (
                    <span
                      className="w-3 h-3 rounded-full border border-border/30"
                      style={{ background: brandKit.accent_color }}
                      title={`Accent ${brandKit.accent_color}`}
                    />
                  )}
                  {brandKit.font_family && (
                    <span title={`Font: ${brandKit.font_family}`} className="ml-1 inline-flex">
                      <Palette className="w-3 h-3 text-muted-foreground" />
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Brand-voice preview — only shown when the user has at
                least one voice field set, so we don't add noise for
                creators who only configured visual branding. */}
            {brandKit && (brandKit.caption_signature || brandKit.default_hashtags) && (
              <div className="flex flex-col gap-1.5 p-2.5 rounded-lg bg-violet-500/5 border border-violet-500/20 text-[11px]">
                {brandKit.caption_signature && (
                  <div className="flex gap-2">
                    <span className="font-mono text-violet-300 shrink-0 opacity-80">
                      Signature
                    </span>
                    <span className="text-muted-foreground whitespace-pre-wrap break-words line-clamp-3">
                      {brandKit.caption_signature}
                    </span>
                  </div>
                )}
                {brandKit.default_hashtags && (
                  <div className="flex gap-2">
                    <span className="font-mono text-violet-300 shrink-0 opacity-80">
                      Hashtags
                    </span>
                    <span className="text-muted-foreground break-words">
                      {brandKit.default_hashtags}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Account targeting */}
            <div>
              <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                Publish to
              </label>
              {accounts.filter((a) => a.is_active).length === 0 ? (
                <div className="mt-2 p-3 rounded-lg bg-amber-glow/5 border border-amber-glow/30 text-xs text-muted-foreground">
                  No active accounts — connect at least one below to publish.
                </div>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {accounts
                    .filter((a) => a.is_active)
                    .map((acct) => {
                      const config = PLATFORM_CONFIG[acct.platform];
                      const Icon = config?.icon || Network;
                      const selected = publishTargets.has(acct.id);
                      return (
                        <button
                          key={acct.id}
                          type="button"
                          onClick={() => togglePublishTarget(acct.id)}
                          disabled={publishing}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-xs transition-colors ${
                            selected
                              ? "bg-cyan-glow/15 border-cyan-glow/40 text-cyan-glow"
                              : "bg-secondary/30 border-border/50 text-muted-foreground hover:border-border"
                          }`}
                        >
                          <Icon className="w-3 h-3" />
                          @{acct.handle}
                        </button>
                      );
                    })}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button
                onClick={handlePublishSubmit}
                disabled={
                  publishing ||
                  !publishTitle.trim() ||
                  publishTargets.size === 0
                }
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
              >
                {publishing ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Send className="w-4 h-4 mr-2" />
                )}
                Publish to {publishTargets.size} account
                {publishTargets.size === 1 ? "" : "s"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* OAuth setup tip */}
      <Card className="bg-gradient-to-br from-amber-glow/5 to-cyan-glow/5 border-amber-glow/20">
        <CardContent className="p-4 flex items-start gap-3">
          <Info className="w-5 h-5 text-amber-glow shrink-0 mt-0.5" />
          <div className="flex-1 text-xs text-foreground">
            <p className="font-medium mb-1">One-click OAuth</p>
            <p className="text-muted-foreground">
              YouTube, TikTok, and Instagram all support one-click OAuth — just click{" "}
              <span className="text-foreground font-medium">Connect Account</span> and choose your platform.
              Twitter / X still requires a manual access token from your developer dashboard.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Connected accounts grid */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3">
          Connected Accounts
          <Badge variant="outline" className="ml-2 text-[10px] border-border/50 text-muted-foreground">
            {accounts.filter((a) => a.is_active).length} active
          </Badge>
        </h2>
        {accounts.length === 0 ? (
          <Card className="bg-card border-border/50 border-dashed">
            <CardContent className="p-8 text-center">
              <Network className="w-10 h-10 text-muted-foreground/50 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground mb-3">
                No accounts connected yet.
              </p>
              <Button
                size="sm"
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                onClick={() => setAddOpen(true)}
              >
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                Connect Your First Account
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {accounts.map((acct) => {
              const config = PLATFORM_CONFIG[acct.platform];
              const Icon = config?.icon || Network;
              return (
                <Card
                  key={acct.id}
                  className={`bg-gradient-to-br ${config?.gradient || "from-secondary/20 to-secondary/40"} ${
                    acct.is_active ? "border-border/50" : "border-border/30 opacity-60"
                  }`}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <div className="w-10 h-10 rounded-lg bg-background/30 flex items-center justify-center shrink-0">
                          <Icon className="w-5 h-5 text-foreground" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-foreground truncate">
                            @{acct.handle}
                          </p>
                          <p className="text-[10px] text-muted-foreground">
                            {config?.label}
                            {acct.follower_count !== null
                              ? ` · ${acct.follower_count.toLocaleString()} followers`
                              : ""}
                          </p>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 shrink-0"
                        onClick={() => handleRemove(acct)}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {acct.is_active ? (
                        <Badge className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20 text-[9px]">
                          Active
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground">
                          Inactive
                        </Badge>
                      )}
                      {acct.auto_publish && (
                        <Badge variant="outline" className="text-[9px] border-cyan-glow/30 text-cyan-glow">
                          Auto-publish
                        </Badge>
                      )}
                      {acct.last_used_at && (
                        <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground font-mono">
                          {new Date(acct.last_used_at).toLocaleDateString()}
                        </Badge>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* Per-platform setup status */}
      {setupStatus && (
        <div>
          <h2 className="text-sm font-semibold text-foreground mb-3">
            Platform Setup
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {(Object.keys(PLATFORM_CONFIG) as DistributionPlatform[]).map((p) => {
              const status = setupStatus[p];
              const config = PLATFORM_CONFIG[p];
              const Icon = config.icon;
              const connected = status?.connected_count || 0;
              return (
                <Card key={p} className="bg-card border-border/50">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Icon className="w-4 h-4 text-muted-foreground" />
                      <h3 className="text-sm font-semibold text-foreground">
                        {config.label}
                      </h3>
                    </div>
                    <div className="flex items-baseline gap-1.5 mb-2">
                      <span className={`text-2xl font-bold font-[var(--font-display)] ${
                        connected > 0 ? "text-cyan-glow" : "text-muted-foreground/50"
                      }`}>
                        {connected}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        connected
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed">
                      {status?.docs}
                    </p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Jobs history */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-foreground">
            Recent Distribution Jobs
            <Badge variant="outline" className="ml-2 text-[10px] border-border/50 text-muted-foreground">
              {jobs.length}
            </Badge>
          </h2>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={refreshJobs}
            disabled={refreshingJobs}
          >
            {refreshingJobs ? (
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3 mr-1" />
            )}
            Refresh
          </Button>
        </div>

        {jobs.length === 0 ? (
          <Card className="bg-card border-border/50 border-dashed">
            <CardContent className="p-8 text-center">
              <Clock className="w-8 h-8 text-muted-foreground/50 mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">
                No distribution jobs yet. Use Shorts Creator → "Clip & Distribute" to publish to all your accounts.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {jobs.map((job) => {
              const status = STATUS_BADGE[job.status] || STATUS_BADGE.pending;
              return (
                <Card key={job.id} className="bg-card border-border/50">
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <CardTitle className="text-sm font-semibold truncate">
                          {job.title}
                        </CardTitle>
                        <p className="text-[10px] text-muted-foreground mt-0.5 font-mono">
                          {new Date(job.created_at).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Badge className={`${status.className} text-[10px]`}>
                          {status.label}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] border-border/50 text-muted-foreground">
                          {job.success_count}/{job.target_count} ok
                        </Badge>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {job.results.length > 0 && (
                      <div className="space-y-1.5">
                        {job.results.map((r) => {
                          const resultStatus = STATUS_BADGE[r.status] || STATUS_BADGE.pending;
                          const platformConfig = PLATFORM_CONFIG[r.platform as DistributionPlatform];
                          const Icon = platformConfig?.icon || Network;
                          return (
                            <div
                              key={r.id}
                              className="flex items-center gap-3 p-2 rounded bg-secondary/30 border border-border/20"
                            >
                              <Icon className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                              <span className="text-xs text-foreground flex-1 truncate">
                                @{r.handle || `account-${r.account_id}`}
                              </span>
                              {r.status === "success" && r.posted_url ? (
                                <a
                                  href={r.posted_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-cyan-glow hover:text-cyan-glow/80 flex items-center gap-1 text-[10px]"
                                >
                                  View <ExternalLink className="w-2.5 h-2.5" />
                                </a>
                              ) : r.status === "success" ? (
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                              ) : r.status === "failed" ? (
                                <span title={r.error_message || "Failed"} className="flex items-center gap-1">
                                  <XCircle className="w-3.5 h-3.5 text-destructive" />
                                </span>
                              ) : (
                                <Loader2 className="w-3.5 h-3.5 text-muted-foreground animate-spin" />
                              )}
                              <Badge
                                className={`${resultStatus.className} text-[9px] shrink-0`}
                              >
                                {resultStatus.label}
                              </Badge>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* Add Account Dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="bg-card border-border/50">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus className="w-4 h-4 text-cyan-glow" />
              Connect Social Account
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label htmlFor="distribution-platform" className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Platform
              </label>
              <Select
                value={newPlatform}
                onValueChange={(v) => setNewPlatform(v as DistributionPlatform)}
              >
                <SelectTrigger id="distribution-platform" className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="instagram">Instagram</SelectItem>
                  <SelectItem value="tiktok">TikTok</SelectItem>
                  <SelectItem value="twitter">Twitter / X</SelectItem>
                  <SelectItem value="youtube">YouTube</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {newPlatform === "youtube" ? (
              <div className="rounded border border-cyan-glow/30 bg-cyan-glow/5 p-3 text-xs text-foreground space-y-2">
                <p className="font-medium">One-click OAuth for YouTube</p>
                <p className="text-muted-foreground">
                  We'll redirect you to Google's OAuth screen and store the refresh token securely. No copy/paste required.
                </p>
                <Button
                  size="sm"
                  className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                  onClick={handleYouTubeOAuth}
                >
                  <Youtube className="w-4 h-4 mr-2" />
                  Connect with Google
                </Button>
              </div>
            ) : newPlatform === "tiktok" ? (
              <div className="rounded border border-pink-500/30 bg-pink-500/5 p-3 text-xs text-foreground space-y-2">
                <p className="font-medium">One-click OAuth for TikTok</p>
                <p className="text-muted-foreground">
                  We'll redirect you to TikTok's Login Kit. Your account is linked securely — no copy/paste required.
                </p>
                <Button
                  size="sm"
                  className="bg-pink-500 text-white hover:bg-pink-600"
                  onClick={handleTikTokOAuth}
                >
                  <Music2 className="w-4 h-4 mr-2" />
                  Connect with TikTok
                </Button>
              </div>
            ) : newPlatform === "instagram" ? (
              <div className="rounded border border-amber-400/30 bg-amber-400/5 p-3 text-xs text-foreground space-y-2">
                <p className="font-medium">One-click OAuth for Instagram</p>
                <p className="text-muted-foreground">
                  We'll redirect you to Meta's Business Login screen. A long-lived token (60 days) is stored securely.
                </p>
                <Button
                  size="sm"
                  className="bg-gradient-to-r from-pink-500 to-amber-500 text-white hover:opacity-90"
                  onClick={handleInstagramOAuth}
                >
                  <Instagram className="w-4 h-4 mr-2" />
                  Connect with Instagram
                </Button>
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="distribution-handle" className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Handle (without @)
                  </label>
                  <Input
                    id="distribution-handle"
                    className="bg-secondary/50 border-border/50"
                    value={newHandle}
                    onChange={(e) => setNewHandle(e.target.value.replace(/^@/, ""))}
                    placeholder="myhandle"
                  />
                </div>
                <div>
                  <label htmlFor="distribution-account-id" className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Platform Account ID
                  </label>
                  <Input
                    id="distribution-account-id"
                    className="bg-secondary/50 border-border/50"
                    value={newAccountId}
                    onChange={(e) => setNewAccountId(e.target.value)}
                    placeholder="The platform's internal user/channel ID"
                  />
                </div>
                <div>
                  <label htmlFor="distribution-access-token" className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Access Token
                  </label>
                  <Input
                    id="distribution-access-token"
                    type="password"
                    className="bg-secondary/50 border-border/50"
                    value={newToken}
                    onChange={(e) => setNewToken(e.target.value)}
                    placeholder="Long-lived OAuth access token"
                  />
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Paste a long-lived access token from your developer dashboard.
                  </p>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setAddOpen(false)}
              disabled={adding}
              className="border-border/50"
            >
              Cancel
            </Button>
            {newPlatform !== "youtube" && newPlatform !== "tiktok" && newPlatform !== "instagram" && (
              <Button
                onClick={handleAdd}
                disabled={adding}
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
              >
                {adding ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4 mr-2" />
                )}
                Connect
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disconnect confirmation (replaces window.confirm) */}
      <AlertDialog open={pendingRemoval !== null} onOpenChange={(open) => !open && setPendingRemoval(null)}>
        <AlertDialogContent className="bg-card border-border/50">
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect this account?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingRemoval ? (
                <>
                  You're about to disconnect <span className="font-mono">@{pendingRemoval.handle}</span> from
                  ViewMagnet. Scheduled distributions to this account will be cancelled. You can reconnect later.
                </>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removing}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                void confirmRemove();
              }}
              disabled={removing}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {removing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Trash2 className="w-4 h-4 mr-2" />}
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

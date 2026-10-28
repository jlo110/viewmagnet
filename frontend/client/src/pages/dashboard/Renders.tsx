/**
 * Renders dashboard (Week 8 — Cloud renders + queue UI).
 *
 * One place for the user to see every render they've kicked off,
 * what's still in flight, where the finished MP4s are, and how
 * close they are to the monthly render-minute cap.
 *
 * Data sources, in priority order:
 *
 *   1. ``useAllRenderProgress()`` — live WS events for whatever's
 *      currently queued or rendering. Sub-second updates without
 *      polling.
 *   2. ``listSessions()`` + ``listStudioProjects()`` — recent history.
 *      Already paginated server-side; we just merge them client-side
 *      so a future "Sessions" sub-tab is free.
 *   3. ``getRenderBudget()`` — fills the quota card.
 *
 * The page degrades gracefully: if any of those fails, the others
 * still render. We never block the whole page on a single endpoint.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import { toast } from "sonner";
import {
  Clapperboard,
  CloudUpload,
  Download,
  Loader2,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  FileStack,
  Send,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";

import {
  cancelStudioProjectRender,
  getRenderBudget,
  listStudioProjects,
  renderStudioProject,
  RENDER_BUDGET_HEADER_EVENT,
  type RenderBudget,
  type StudioProjectListItem,
} from "@/lib/api";
import { cancelSessionRender, listSessions, renderSession } from "@/studio/api";
import {
  recordRenderTrigger,
  useAllRenderProgress,
  useRenderProgressFor,
} from "@/lib/renderProgress";
import { useUpgrade } from "@/contexts/UpgradeContext";
import { buildDistributionLink } from "@/lib/deepLinks";

// ---------------------------------------------------------------------------
// Types — a single shape for both single-clip and project renders so the UI
// can render them uniformly. The ``kind`` discriminator preserves the deep
// link for "open source".
// ---------------------------------------------------------------------------

type RenderStatus = "idle" | "queued" | "rendering" | "done" | "failed";

interface RenderRow {
  kind: "session" | "project";
  id: number;
  title: string;
  status: RenderStatus;
  downloadUrl: string | null;
  updatedAt: string;
  // Used for deep linking the "open source" action.
  deepLink: string;
  // Session-only: the clip key. Needed so the row's Re-run button
  // can fire ``POST /studio/render`` directly instead of bouncing the
  // user back into the editor to click Render again.
  clipKey?: string;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RendersPage() {
  const { openUpgrade } = useUpgrade();

  const [budget, setBudget] = useState<RenderBudget | null>(null);
  const [rows, setRows] = useState<RenderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const liveEvents = useAllRenderProgress();

  // ---- initial load ---------------------------------------------------
  const loadAll = async () => {
    setLoading(true);
    setError(null);
    const [budgetRes, sessionsRes, projectsRes] = await Promise.allSettled([
      getRenderBudget(),
      listSessions(),
      listStudioProjects(),
    ]);
    if (budgetRes.status === "fulfilled") {
      setBudget(budgetRes.value);
    }
    const merged: RenderRow[] = [];
    if (sessionsRes.status === "fulfilled") {
      for (const s of sessionsRes.value) {
        merged.push({
          kind: "session",
          id: s.id,
          title: s.title || "Untitled clip",
          status: (s.last_render_status as RenderStatus) || "idle",
          downloadUrl: s.last_render_url ?? null,
          updatedAt: s.updated_at,
          deepLink: `/dashboard/studio/${encodeURIComponent(s.clip_key)}`,
          clipKey: s.clip_key,
        });
      }
    }
    if (projectsRes.status === "fulfilled") {
      for (const p of projectsRes.value as StudioProjectListItem[]) {
        merged.push({
          kind: "project",
          id: p.id,
          title: p.title || "Untitled project",
          status: (p.last_render_status as RenderStatus) || "idle",
          downloadUrl: p.last_render_url ?? null,
          updatedAt: p.updated_at,
          deepLink: `/dashboard/studio/project/${p.id}`,
        });
      }
    }
    merged.sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    );
    setRows(merged);
    if (
      budgetRes.status === "rejected" &&
      sessionsRes.status === "rejected" &&
      projectsRes.status === "rejected"
    ) {
      setError("Couldn't load your renders. Check your connection and retry.");
    }
    setLoading(false);
  };

  useEffect(() => {
    loadAll();
  }, []);

  // Listen for the post-render budget header from any other page
  // (e.g. user clicks Render in Studio while this page is open in
  // another tab). Refetch once when we hear it so the quota card
  // mirrors the new remaining minutes without a polling interval.
  useEffect(() => {
    const handler = () => {
      getRenderBudget()
        .then((b) => setBudget(b))
        .catch(() => {
          // Ignore — the next page-load will pick up the real value.
        });
    };
    window.addEventListener(RENDER_BUDGET_HEADER_EVENT, handler);
    return () => window.removeEventListener(RENDER_BUDGET_HEADER_EVENT, handler);
  }, []);

  // ---- merge live events into the row list ---------------------------
  // When a WS event arrives for a row already in the list, replace the
  // status/url inline. The list is sorted by most recent so live ones
  // bubble to the top naturally on the next refetch.
  const rowsWithLive = useMemo(() => {
    if (liveEvents.length === 0) return rows;
    const byKey = new Map<string, RenderRow>();
    for (const r of rows) byKey.set(`${r.kind}:${r.id}`, r);
    for (const ev of liveEvents) {
      const key = `${ev.kind}:${ev.render_id}`;
      const existing = byKey.get(key);
      if (existing) {
        byKey.set(key, {
          ...existing,
          status: ev.status,
          downloadUrl: ev.download_url ?? existing.downloadUrl,
        });
      }
    }
    return Array.from(byKey.values()).sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    );
  }, [rows, liveEvents]);

  const inFlight = rowsWithLive.filter(
    (r) => r.status === "queued" || r.status === "rendering",
  );
  const recent = rowsWithLive.filter(
    (r) => r.status !== "queued" && r.status !== "rendering",
  );

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Renders</h1>
          <p className="text-sm text-zinc-400">
            Every clip and project you've rendered, in one place.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadAll}
          disabled={loading}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Quota card */}
      <QuotaCard
        budget={budget}
        onUpgrade={() => openUpgrade("render_budget")}
      />

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* In flight */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-300">
            In flight
          </h2>
          <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
            {inFlight.length}
          </Badge>
        </div>
        {inFlight.length === 0 ? (
          <EmptyState
            icon={<CloudUpload className="h-5 w-5 text-zinc-500" />}
            message="No active renders. Hit Render in Studio or on a project to queue one."
          />
        ) : (
          <div className="grid gap-3">
            {inFlight.map((row) => (
              <ActiveRenderRow key={`${row.kind}:${row.id}`} row={row} />
            ))}
          </div>
        )}
      </section>

      <Separator className="bg-zinc-800" />

      {/* Recent */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
          Recent
        </h2>
        {recent.length === 0 ? (
          <EmptyState
            icon={<FileStack className="h-5 w-5 text-zinc-500" />}
            message="Once a render finishes, it'll show up here for download or re-render."
          />
        ) : (
          <div className="grid gap-3">
            {recent.slice(0, 50).map((row) => (
              <RecentRenderRow key={`${row.kind}:${row.id}`} row={row} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quota card
// ---------------------------------------------------------------------------

function QuotaCard({
  budget,
  onUpgrade,
}: {
  budget: RenderBudget | null;
  onUpgrade: () => void;
}) {
  if (!budget) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardContent className="flex items-center gap-2 p-4 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading quota…
        </CardContent>
      </Card>
    );
  }

  if (budget.unlimited) {
    return (
      <Card className="border-emerald-900/50 bg-emerald-950/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Unlimited renders</CardTitle>
          <CardDescription>
            You're on <span className="font-medium capitalize">{budget.plan}</span>.
            Render minutes don't count against you.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0 text-sm text-zinc-300">
          {budget.minutes_used.toFixed(1)} minutes rendered this month.
        </CardContent>
      </Card>
    );
  }

  const nearLimit = budget.percent_used >= 70;
  const outOfBudget = budget.percent_used >= 100;
  return (
    <Card
      className={
        outOfBudget
          ? "border-red-900/60 bg-red-950/30"
          : nearLimit
            ? "border-amber-900/60 bg-amber-950/20"
            : "border-zinc-800 bg-zinc-950/80"
      }
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            {budget.minutes_used.toFixed(1)} of {budget.minutes_limit.toFixed(0)}{" "}
            render minutes used
          </CardTitle>
          <Badge variant="outline" className="capitalize">
            {budget.plan}
          </Badge>
        </div>
        <CardDescription>
          {outOfBudget
            ? "You're out of render minutes for the month."
            : nearLimit
              ? `Heads up — you've used ${budget.percent_used.toFixed(0)}% of this month's allotment.`
              : `Resets on the 1st of next month (UTC).`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <Progress value={Math.min(100, budget.percent_used)} />
        {(nearLimit || outOfBudget) && (
          <Button size="sm" onClick={onUpgrade}>
            Upgrade for unlimited renders
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Row components
// ---------------------------------------------------------------------------

function ActiveRenderRow({ row }: { row: RenderRow }) {
  // Resubscribe per-row so each row updates independently of the others
  // when its event arrives. The transport is a singleton so this doesn't
  // open N sockets.
  const live = useRenderProgressFor(row.kind, row.id);
  const status = live?.status ?? row.status;
  const percent = live?.percent ?? null;
  const message = live?.message ?? null;
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    setCancelling(true);
    try {
      if (row.kind === "project") {
        await cancelStudioProjectRender(row.id);
      } else {
        await cancelSessionRender(row.id);
      }
      toast.success("Render cancelled");
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      if (status === 409) {
        // Already terminal — nothing to cancel. Quiet success rather
        // than an error so the UI doesn't yell at the user for a
        // race they didn't cause.
        toast.info("Render already finished");
      } else {
        toast.error("Couldn't cancel render");
      }
    } finally {
      setCancelling(false);
    }
  };

  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <KindIcon kind={row.kind} />
            <Link
              href={row.deepLink}
              className="truncate text-sm font-medium hover:underline"
            >
              {row.title}
            </Link>
            <StatusBadge status={status} />
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="text-xs text-zinc-500">
              {percent !== null ? `${percent}%` : "—"}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleCancel}
              disabled={cancelling}
              title="Cancel this render"
              className="h-7 px-2 text-xs text-zinc-400 hover:text-red-300"
            >
              {cancelling ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <>
                  <X className="mr-1 h-3.5 w-3.5" /> Cancel
                </>
              )}
            </Button>
          </div>
        </div>
        <Progress value={percent ?? 5} />
        <p className="truncate text-xs text-zinc-400">{message ?? "Working…"}</p>
      </CardContent>
    </Card>
  );
}

function RecentRenderRow({ row }: { row: RenderRow }) {
  const [retrying, setRetrying] = useState(false);

  const handleDownload = () => {
    if (!row.downloadUrl) return;
    window.open(row.downloadUrl, "_blank", "noopener,noreferrer");
  };

  const handleReRun = async () => {
    setRetrying(true);
    try {
      if (row.kind === "project") {
        const status = await renderStudioProject(row.id);
        recordRenderTrigger("project", row.id, status.status);
      } else {
        if (!row.clipKey) {
          toast.error("Missing clip key — open the clip in Studio to retry");
          return;
        }
        const status = await renderSession(row.clipKey);
        recordRenderTrigger("session", row.id, status.status);
      }
      // The global RenderNotifier handles the "Render queued" toast
      // so it fires regardless of which page the user lands on.
    } catch {
      toast.error("Couldn't re-run render");
    } finally {
      setRetrying(false);
    }
  };

  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardContent className="flex items-center justify-between gap-3 p-4">
        <div className="flex min-w-0 items-center gap-2">
          <KindIcon kind={row.kind} />
          <Link
            href={row.deepLink}
            className="truncate text-sm font-medium hover:underline"
          >
            {row.title}
          </Link>
          <StatusBadge status={row.status} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {row.downloadUrl && (
            <Button size="sm" variant="outline" onClick={handleDownload}>
              <Download className="mr-2 h-4 w-4" /> Download
            </Button>
          )}
          {row.status === "done" && row.downloadUrl && (
            // Week 9 Connected Tools: closing the loop from the
            // Renders queue straight into the Distribution Hub. Pre-
            // fills the publish form with the rendered MP4 URL, title
            // and (for projects) the project ID so the hub's effect
            // can also hydrate description + hashtags from the
            // project's brand kit.
            <Link
              href={buildDistributionLink({
                renderUrl: row.downloadUrl,
                title: row.title,
                clipKey: row.clipKey,
                projectId: row.kind === "project" ? row.id : undefined,
              })}
            >
              <Button
                size="sm"
                variant="outline"
                title="Publish this render to your connected social accounts"
              >
                <Send className="mr-2 h-4 w-4" /> Publish
              </Button>
            </Link>
          )}
          {(row.status === "failed" || row.status === "done") && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleReRun}
              disabled={retrying}
              title={row.status === "done" ? "Render again" : "Re-run failed render"}
            >
              {retrying ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              {row.status === "done" ? "Render again" : "Re-run"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function KindIcon({ kind }: { kind: "session" | "project" }) {
  return kind === "project" ? (
    <FileStack className="h-4 w-4 text-zinc-400" />
  ) : (
    <Clapperboard className="h-4 w-4 text-zinc-400" />
  );
}

function StatusBadge({ status }: { status: RenderStatus }) {
  if (status === "queued" || status === "rendering") {
    return (
      <Badge variant="secondary" className="h-5 px-1.5 text-[10px] uppercase tracking-wider">
        <Loader2 className="mr-1 h-3 w-3 animate-spin" /> {status}
      </Badge>
    );
  }
  if (status === "done") {
    return (
      <Badge className="h-5 bg-emerald-900/40 px-1.5 text-[10px] uppercase tracking-wider text-emerald-300 hover:bg-emerald-900/40">
        <CheckCircle2 className="mr-1 h-3 w-3" /> done
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge className="h-5 bg-red-900/40 px-1.5 text-[10px] uppercase tracking-wider text-red-300 hover:bg-red-900/40">
        <AlertCircle className="mr-1 h-3 w-3" /> failed
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase tracking-wider">
      {status}
    </Badge>
  );
}

function EmptyState({
  icon,
  message,
}: {
  icon: React.ReactNode;
  message: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-dashed border-zinc-800 bg-zinc-950/50 p-4 text-sm text-zinc-400">
      {icon}
      <span>{message}</span>
    </div>
  );
}

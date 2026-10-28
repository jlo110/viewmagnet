/**
 * Admin Telemetry dashboard (Week 8 P3 polish — real telemetry).
 *
 * The operator answer to "is the render pipeline healthy?" — rolled
 * up from the audit table that ``src/queue/telemetry.py`` writes
 * lifecycle events into. Backed by ``/admin/telemetry/renders`` and
 * ``/admin/telemetry/queue``; both endpoints are admin-gated.
 *
 * Surfaces:
 *
 *   1. **Funnel counts**: queued → started → completed/failed/cancelled.
 *      The headline number is the success rate (completed / terminal),
 *      and crucially we split ``cancelled`` from ``failed`` so a
 *      cancel-happy user doesn't make our health chart lie.
 *   2. **Wait + render durations**: p50 / p95, sampled from
 *      ``queued → started`` (wait) and ``started → completed`` (render)
 *      pairs. The two together tell you whether a slow render is the
 *      queue or the worker.
 *   3. **Top error types**: grouped from ``failed`` + ``dlq`` events,
 *      so a recurring TimeoutError jumps out instead of being buried
 *      in a tail of one-offs.
 *   4. **Daily series**: by-day buckets of queued/completed/failed so
 *      a regression from yesterday is immediately visible.
 *   5. **Live queue depth + surge level**: classified normal/busy/
 *      slammed so an operator can decide whether to spin up another
 *      worker or wait it out.
 *
 * UI guidelines:
 *
 *   - Loading state shows skeleton cards (not a giant spinner) so the
 *     page layout doesn't reflow when data lands.
 *   - All charts are *honest empty states*: zero events in the window
 *     renders "no renders in the last X hours" with a clear hint to
 *     widen the lookback, never invented sample data.
 *   - Queue snapshot polls every 10s; the funnel summary refreshes
 *     when the lookback selector changes or the operator clicks
 *     Refresh. Background polling is intentionally bounded to the
 *     queue card because the funnel query touches the audit table.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Clock,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Zap,
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
  getAdminQueueSnapshot,
  getRenderTelemetry,
  type AdminQueueSnapshot,
  type RenderTelemetrySummary,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const LOOKBACK_OPTIONS = [
  { label: "1h", hours: 1 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 24 * 7 },
  { label: "30d", hours: 24 * 30 },
];

const QUEUE_POLL_MS = 10_000;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminTelemetryPage() {
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin);

  const [lookbackHours, setLookbackHours] = useState(24);
  const [summary, setSummary] = useState<RenderTelemetrySummary | null>(null);
  const [queue, setQueue] = useState<AdminQueueSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const data = await getRenderTelemetry(lookbackHours);
      setSummary(data);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status
        ?? (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        setForbidden(true);
      } else if (status === 503) {
        setError("Telemetry rollup is unavailable. Check the audit DB.");
      } else {
        setError(
          (err as { message?: string })?.message
          ?? "Couldn't load telemetry summary.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [lookbackHours]);

  const loadQueue = useCallback(async () => {
    try {
      const data = await getAdminQueueSnapshot();
      setQueue(data);
    } catch {
      // Queue snapshot is non-critical to the rest of the page —
      // swallow and let the next poll retry.
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    loadSummary();
  }, [isAdmin, loadSummary]);

  useEffect(() => {
    if (!isAdmin) return;
    loadQueue();
    const handle = window.setInterval(loadQueue, QUEUE_POLL_MS);
    return () => window.clearInterval(handle);
  }, [isAdmin, loadQueue]);

  if (!isAdmin && !loading) {
    return <AdminGate />;
  }
  if (forbidden) {
    return <AdminGate />;
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Render Telemetry
          </h1>
          <p className="text-sm text-zinc-400">
            Pipeline health rolled up from the audit table. Funnel + duration
            stats over the selected lookback window.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <LookbackPicker
            value={lookbackHours}
            onChange={setLookbackHours}
            disabled={loading}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={loadSummary}
            disabled={loading}
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* Live queue + surge */}
      <QueueCard snapshot={queue} />

      <Separator className="bg-zinc-800" />

      {/* Funnel + rates */}
      <FunnelSection summary={summary} loading={loading && !summary} />

      {/* Durations */}
      <DurationsSection summary={summary} loading={loading && !summary} />

      {/* Top errors + per-day series */}
      <div className="grid gap-4 md:grid-cols-2">
        <TopErrorsCard summary={summary} loading={loading && !summary} />
        <DailySeriesCard summary={summary} loading={loading && !summary} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function LookbackPicker({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (hours: number) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex gap-1 rounded-md border border-zinc-800 bg-zinc-950/50 p-1">
      {LOOKBACK_OPTIONS.map((opt) => (
        <button
          key={opt.label}
          type="button"
          onClick={() => onChange(opt.hours)}
          disabled={disabled}
          className={`rounded px-2 py-0.5 text-xs transition-colors ${
            value === opt.hours
              ? "bg-cyan-glow/20 text-cyan-glow"
              : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function QueueCard({ snapshot }: { snapshot: AdminQueueSnapshot | null }) {
  if (!snapshot) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardContent className="flex items-center gap-3 p-4 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading worker queue snapshot…
        </CardContent>
      </Card>
    );
  }
  if (!snapshot.available) {
    return (
      <Card className="border-dashed border-zinc-800 bg-transparent">
        <CardContent className="flex items-center gap-3 p-4 text-sm text-zinc-500">
          <AlertTriangle className="h-4 w-4" />
          Worker queue not reachable on this environment (Redis missing). Live
          surge data is unavailable.
        </CardContent>
      </Card>
    );
  }
  const tone = surgeTone(snapshot.level);
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Zap className={`h-4 w-4 ${tone.icon}`} />
          Live worker queue
          <Badge variant="secondary" className={`ml-2 ${tone.badge}`}>
            {snapshot.level}
          </Badge>
        </CardTitle>
        <CardDescription>
          Snapshot of RQ registries, sampled every {QUEUE_POLL_MS / 1000}s.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 pt-0 md:grid-cols-5">
        <Metric label="Queued" value={snapshot.queue_depth} />
        <Metric label="Running" value={snapshot.started} />
        <Metric label="Scheduled" value={snapshot.scheduled} />
        <Metric label="Deferred" value={snapshot.deferred} />
        <Metric
          label="Est. wait"
          value={formatSeconds(snapshot.estimated_wait_seconds)}
        />
      </CardContent>
    </Card>
  );
}

function FunnelSection({
  summary,
  loading,
}: {
  summary: RenderTelemetrySummary | null;
  loading: boolean;
}) {
  if (loading) {
    return <SkeletonCard title="Funnel" lines={4} />;
  }
  if (!summary) return null;
  const { counts, rates } = summary;
  const terminal = counts.completed + counts.failed + counts.dlq + counts.cancelled;
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4 text-cyan-glow" />
          Render funnel
        </CardTitle>
        <CardDescription>
          Last {Math.round(summary.window.lookback_seconds / 3600)}h.
          {terminal === 0
            ? " No terminal renders in this window — widen the lookback if you expected data."
            : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Queued" value={counts.queued} />
          <Metric label="Started" value={counts.started} />
          <Metric label="Completed" value={counts.completed} positive />
          <Metric
            label="Failed"
            value={counts.failed + counts.dlq}
            danger={counts.failed + counts.dlq > 0}
          />
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Cancelled" value={counts.cancelled} muted />
          <Metric label="Budget blocked" value={counts.budget_blocked} muted />
          <Metric label="Retries" value={counts.retried} muted />
          <Metric label="DLQ" value={counts.dlq} danger={counts.dlq > 0} />
        </div>
        {terminal > 0 && (
          <div className="space-y-2">
            <RateBar
              label="Success rate"
              percent={rates.success_rate * 100}
              tone="emerald"
            />
            <RateBar
              label="Failure rate"
              percent={rates.failure_rate * 100}
              tone="red"
            />
            <RateBar
              label="Cancel rate"
              percent={rates.cancel_rate * 100}
              tone="amber"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DurationsSection({
  summary,
  loading,
}: {
  summary: RenderTelemetrySummary | null;
  loading: boolean;
}) {
  if (loading) {
    return <SkeletonCard title="Durations" lines={2} />;
  }
  if (!summary) return null;
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-4 w-4 text-cyan-glow" />
          Wait + render durations
        </CardTitle>
        <CardDescription>
          Sampled from queued → started (wait) and started → completed
          (render) pairs. Slow renders + low waits = the worker is
          struggling; slow waits + fast renders = the queue is the
          bottleneck.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <DurationBlock label="Wait (queued → started)" block={summary.wait_seconds} />
        <DurationBlock label="Render (started → completed)" block={summary.render_seconds} />
      </CardContent>
    </Card>
  );
}

function DurationBlock({
  label,
  block,
}: {
  label: string;
  block: { p50: number | null; p95: number | null; samples: number };
}) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3">
      <p className="text-xs font-mono uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <div className="mt-2 flex gap-4">
        <div>
          <p className="text-2xl font-semibold text-foreground">
            {block.p50 == null ? "—" : formatSeconds(block.p50)}
          </p>
          <p className="text-[10px] uppercase text-zinc-500">p50</p>
        </div>
        <div>
          <p className="text-2xl font-semibold text-foreground">
            {block.p95 == null ? "—" : formatSeconds(block.p95)}
          </p>
          <p className="text-[10px] uppercase text-zinc-500">p95</p>
        </div>
      </div>
      <p className="mt-2 text-xs text-zinc-500">{block.samples} samples</p>
    </div>
  );
}

function TopErrorsCard({
  summary,
  loading,
}: {
  summary: RenderTelemetrySummary | null;
  loading: boolean;
}) {
  if (loading) return <SkeletonCard title="Top errors" lines={3} />;
  if (!summary) return null;
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Top failure types</CardTitle>
        <CardDescription>
          Grouped from failed + DLQ events by ``error_type``.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {summary.top_errors.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No failures in this window. Nice.
          </p>
        ) : (
          summary.top_errors.map((e) => (
            <div
              key={e.error_type}
              className="flex items-center justify-between rounded border border-zinc-900 bg-zinc-950/60 px-3 py-2"
            >
              <code className="text-xs text-red-300">{e.error_type}</code>
              <Badge variant="secondary" className="text-[10px]">
                {e.count}
              </Badge>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function DailySeriesCard({
  summary,
  loading,
}: {
  summary: RenderTelemetrySummary | null;
  loading: boolean;
}) {
  if (loading) return <SkeletonCard title="Daily series" lines={3} />;
  if (!summary) return null;
  const max = useMemoMax(summary);
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Per-day buckets</CardTitle>
        <CardDescription>
          Queued vs completed vs failed by UTC date.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {summary.by_day.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No renders in this window.
          </p>
        ) : (
          summary.by_day.map((d) => (
            <div key={d.date} className="space-y-1">
              <div className="flex items-center justify-between text-xs text-zinc-400">
                <span className="font-mono">{d.date}</span>
                <span className="text-zinc-500">
                  {d.completed}/{d.queued} done · {d.failed} failed
                </span>
              </div>
              <div className="flex h-2 gap-0.5">
                <div
                  className="rounded-l bg-emerald-500/70"
                  style={{ width: `${pct(d.completed, max)}%` }}
                />
                <div
                  className="bg-red-500/70"
                  style={{ width: `${pct(d.failed, max)}%` }}
                />
                <div
                  className="rounded-r bg-zinc-600/40"
                  style={{
                    width: `${pct(d.queued - d.completed - d.failed, max)}%`,
                  }}
                />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function useMemoMax(summary: RenderTelemetrySummary): number {
  return useMemo(() => {
    let m = 1;
    for (const d of summary.by_day) {
      m = Math.max(m, d.queued, d.completed, d.failed);
    }
    return m;
  }, [summary]);
}

function pct(value: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (value / max) * 100));
}

function surgeTone(level: AdminQueueSnapshot["level"]) {
  if (level === "slammed") {
    return { icon: "text-red-400", badge: "bg-red-900/40 text-red-300" };
  }
  if (level === "busy") {
    return { icon: "text-amber-300", badge: "bg-amber-900/40 text-amber-200" };
  }
  return {
    icon: "text-emerald-400",
    badge: "bg-emerald-900/40 text-emerald-300",
  };
}

function formatSeconds(seconds: number): string {
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s === 0 ? `${m}m` : `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm === 0 ? `${h}h` : `${h}h ${rm}m`;
}

function Metric({
  label,
  value,
  positive,
  danger,
  muted,
}: {
  label: string;
  value: number | string;
  positive?: boolean;
  danger?: boolean;
  muted?: boolean;
}) {
  const tone = danger
    ? "text-red-300"
    : positive
    ? "text-emerald-300"
    : muted
    ? "text-zinc-400"
    : "text-foreground";
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/50 p-3">
      <p className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
        {label}
      </p>
      <p className={`mt-1 text-xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

function RateBar({
  label,
  percent,
  tone,
}: {
  label: string;
  percent: number;
  tone: "emerald" | "red" | "amber";
}) {
  const colorMap = {
    emerald: "[&>div]:bg-emerald-500/70",
    red: "[&>div]:bg-red-500/70",
    amber: "[&>div]:bg-amber-400/70",
  } as const;
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-zinc-400">
        <span>{label}</span>
        <span className="font-mono text-zinc-300">{percent.toFixed(1)}%</span>
      </div>
      <Progress value={percent} className={`mt-1 h-1.5 ${colorMap[tone]}`} />
    </div>
  );
}

function SkeletonCard({ title, lines }: { title: string; lines: number }) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {Array.from({ length: lines }, (_, i) => (
          <div
            key={i}
            className="h-6 animate-pulse rounded bg-zinc-900/80"
          />
        ))}
      </CardContent>
    </Card>
  );
}

function AdminGate() {
  return (
    <div className="p-6">
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-5 w-5 text-amber-300" />
            Admin access required
          </CardTitle>
          <CardDescription>
            This dashboard is operator-only. Add your account email to the{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 text-xs">
              ADMIN_EMAILS
            </code>{" "}
            environment variable and re-login to access it.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

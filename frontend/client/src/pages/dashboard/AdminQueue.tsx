/**
 * Admin Queue dashboard (Week 8 — Cloud renders + queue UI polish).
 *
 * Operator-only surface for inspecting and managing the worker
 * dead-letter queue (DLQ). Backed by ``/admin/queue/dlq*`` on the
 * API — endpoints are admin-gated (``ADMIN_EMAILS`` env), so this
 * page is reachable but useless to non-admins (the API returns 403
 * and we render a friendly "admin access required" panel).
 *
 * Why a real UI for this:
 *
 *   - Previously, a failed render that exhausted retries silently
 *     accumulated in the DLQ with no way to act on it short of
 *     ``redis-cli``. That's fine for a hobby project but not for
 *     paid users who notice "my render never came back" and want
 *     us to re-run it.
 *   - This page gives an on-call operator a 1-click "re-enqueue"
 *     (re-runs the job with the same args + kwargs the original
 *     job had) plus an explicit "delete" for when the job is no
 *     longer relevant (e.g. user already started a fresh render).
 *   - Prune controls let us clear out the long tail without
 *     touching infra — useful when migrating queues or after a
 *     fix-then-replay session.
 *
 * Design notes:
 *
 *   - Re-enqueue keeps the DLQ row until the new job is accepted by
 *     Redis, so a transient blip can't lose the failure record.
 *     If we get a stale view (row already pruned), the API returns
 *     ``{status: "not_found"}`` and we just refresh.
 *   - We deliberately don't offer a "re-enqueue all" — it's too
 *     easy to nuke prod with one wrong click. Operators pick row
 *     by row.
 *   - The view is read-only-friendly: rows show the original
 *     ``func_name`` + ``args`` (truncated) + the stringified
 *     ``error`` so the operator can decide before re-running.
 */
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  AlertTriangle,
  Loader2,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Trash2,
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
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";

import {
  deleteDlqEntry,
  listDlqEntries,
  pruneDlq,
  reenqueueDlqEntry,
  type DlqEntry,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminQueuePage() {
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin);

  const [entries, setEntries] = useState<DlqEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [pruneDays, setPruneDays] = useState(30);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [pruning, setPruning] = useState(false);
  const [filter, setFilter] = useState("");

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const res = await listDlqEntries(200);
      setEntries(res.entries);
      setTotal(res.total);
    } catch (err) {
      const status = (err as { status?: number; response?: { status?: number } })?.status
        ?? (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        setForbidden(true);
      } else if (status === 503) {
        setError("Queue is not configured on this environment (REDIS_URL missing).");
      } else {
        setError(
          (err as { message?: string })?.message
            ?? "Couldn't load DLQ entries. Check the worker is up.",
        );
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const filtered = useMemo(() => {
    if (!filter.trim()) return entries;
    const needle = filter.trim().toLowerCase();
    return entries.filter((e) => {
      const hay = [
        e.job_id,
        e.func_name,
        e.error,
        e.error_type,
        e.failed_at,
        JSON.stringify(e.args ?? []),
        JSON.stringify(e.kwargs ?? {}),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [entries, filter]);

  const handleReenqueue = async (entry: DlqEntry) => {
    if (!entry.job_id) {
      toast.error("DLQ entry has no job_id; cannot re-enqueue.");
      return;
    }
    if (busyJobId) return;
    setBusyJobId(entry.job_id);
    try {
      const res = await reenqueueDlqEntry(entry.job_id);
      if (res.status === "not_found") {
        toast.info("Entry was already removed; refreshing.");
      } else {
        toast.success(
          `Re-enqueued as ${res.job_id ?? "(new job)"}. Watch the worker for status.`,
        );
      }
      await loadAll();
    } catch (err) {
      const message =
        (err as { message?: string })?.message ?? "Re-enqueue failed.";
      toast.error(message);
    } finally {
      setBusyJobId(null);
    }
  };

  const handleDelete = async (entry: DlqEntry) => {
    if (!entry.job_id) {
      toast.error("DLQ entry has no job_id; cannot delete.");
      return;
    }
    if (busyJobId) return;
    const ok = window.confirm(
      `Drop DLQ entry for ${entry.func_name ?? "(unknown)"}?\n\nThis cannot be undone.`,
    );
    if (!ok) return;
    setBusyJobId(entry.job_id);
    try {
      const res = await deleteDlqEntry(entry.job_id);
      if (res.status === "not_found") {
        toast.info("Entry was already removed; refreshing.");
      } else {
        toast.success("Entry deleted.");
      }
      await loadAll();
    } catch (err) {
      const message =
        (err as { message?: string })?.message ?? "Delete failed.";
      toast.error(message);
    } finally {
      setBusyJobId(null);
    }
  };

  const handlePrune = async () => {
    if (pruning) return;
    const ok = window.confirm(
      `Drop DLQ entries older than ${pruneDays} day(s)? This cannot be undone.`,
    );
    if (!ok) return;
    setPruning(true);
    try {
      const res = await pruneDlq(pruneDays);
      toast.success(`Pruned ${res.dropped} entr${res.dropped === 1 ? "y" : "ies"}.`);
      await loadAll();
    } catch (err) {
      const message =
        (err as { message?: string })?.message ?? "Prune failed.";
      toast.error(message);
    } finally {
      setPruning(false);
    }
  };

  // -------------------------------------------------------------
  // Gating: even if the route is reachable, lean on the user
  // payload first so we don't have to wait for the API 403. This
  // is a UX nicety — the backend is still the source of truth.
  // -------------------------------------------------------------
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
          <h1 className="text-2xl font-semibold tracking-tight">Worker DLQ</h1>
          <p className="text-sm text-zinc-400">
            Inspect, re-run, or drop jobs that exhausted their retries.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by func, error, job_id…"
            className="h-8 w-64"
          />
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
      </div>

      {/* Prune card */}
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Prune by age</CardTitle>
          <CardDescription>
            Drop DLQ entries older than the cutoff. The worker also runs this
            automatically (30d) on startup; this is for manual cleanup.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-end gap-3 pt-0">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-400">Older than (days)</label>
            <Input
              type="number"
              min={1}
              max={365}
              value={pruneDays}
              onChange={(e) =>
                setPruneDays(
                  Math.max(1, Math.min(365, Number(e.target.value) || 30)),
                )
              }
              className="h-9 w-32"
            />
          </div>
          <Button
            variant="destructive"
            size="sm"
            onClick={handlePrune}
            disabled={pruning}
          >
            {pruning ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="mr-2 h-4 w-4" />
            )}
            Prune
          </Button>
        </CardContent>
      </Card>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      <Separator className="bg-zinc-800" />

      {/* Entries */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-300">
            Entries
          </h2>
          <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
            {filtered.length} / {total}
          </Badge>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading DLQ…
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            message={
              total === 0
                ? "No entries in the dead-letter queue. Everything has been processed cleanly."
                : "No entries match your filter."
            }
          />
        ) : (
          <div className="grid gap-3">
            {filtered.map((entry) => (
              <DlqRow
                key={`${entry.index}:${entry.job_id ?? "no-id"}`}
                entry={entry}
                busy={busyJobId === entry.job_id}
                onReenqueue={() => handleReenqueue(entry)}
                onDelete={() => handleDelete(entry)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function DlqRow({
  entry,
  busy,
  onReenqueue,
  onDelete,
}: {
  entry: DlqEntry;
  busy: boolean;
  onReenqueue: () => void;
  onDelete: () => void;
}) {
  const failedAt = entry.failed_at ? new Date(entry.failed_at) : null;
  const failedLabel = failedAt && !Number.isNaN(failedAt.getTime())
    ? failedAt.toLocaleString()
    : entry.failed_at ?? "unknown";

  const argsText = (() => {
    try {
      const raw = JSON.stringify(entry.args ?? []);
      return raw.length > 200 ? raw.slice(0, 200) + "…" : raw;
    } catch {
      return "(unserializable)";
    }
  })();

  const kwargsText = (() => {
    try {
      const raw = JSON.stringify(entry.kwargs ?? {});
      return raw.length > 200 ? raw.slice(0, 200) + "…" : raw;
    } catch {
      return "(unserializable)";
    }
  })();

  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardContent className="space-y-2 p-4 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <code className="rounded bg-zinc-900 px-1.5 py-0.5 text-xs text-cyan-glow">
                {entry.func_name ?? "(no func_name)"}
              </code>
              {entry.error_type && (
                <Badge
                  variant="outline"
                  className="border-red-900/60 text-[10px] text-red-300"
                >
                  {entry.error_type}
                </Badge>
              )}
              <span className="text-xs text-zinc-500">row #{entry.index}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
              <span className="font-mono">{entry.job_id ?? "(no job_id)"}</span>
              <span className="text-zinc-600">·</span>
              <span>failed {failedLabel}</span>
            </div>
            {entry.error && (
              <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded border border-red-900/30 bg-red-950/20 p-2 text-xs text-red-200">
                {entry.error}
              </pre>
            )}
            <details className="text-xs text-zinc-500">
              <summary className="cursor-pointer select-none">payload</summary>
              <div className="mt-1 space-y-1 font-mono">
                <div>
                  <span className="text-zinc-600">args:</span> {argsText}
                </div>
                <div>
                  <span className="text-zinc-600">kwargs:</span> {kwargsText}
                </div>
              </div>
            </details>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onReenqueue}
              disabled={busy || !entry.job_id || !entry.func_name}
            >
              {busy ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-2 h-4 w-4" />
              )}
              Re-enqueue
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              disabled={busy || !entry.job_id}
              className="text-red-300 hover:text-red-200"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Drop
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function EmptyState({ message }: { message: string }) {
  return (
    <Card className="border-dashed border-zinc-800 bg-transparent">
      <CardContent className="flex items-center gap-3 p-4 text-sm text-zinc-400">
        <AlertTriangle className="h-5 w-5 text-zinc-500" />
        {message}
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
            This page is operator-only. Add your account email to the{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 text-xs">
              ADMIN_EMAILS
            </code>{" "}
            environment variable and re-login to get access.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

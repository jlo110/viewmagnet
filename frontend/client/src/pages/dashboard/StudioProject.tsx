/**
 * Studio Project page — long-form multi-clip editor (Week 7).
 *
 * Renders a single :class:`StudioProjectSpec` as a horizontal clip rail.
 * Each card represents one underlying ``EditSession`` (drafted in the
 * single-clip Studio); the project view owns the ordering, the trims,
 * the inter-clip transitions, and the project-level brand kit. Clicking
 * "Edit clip" deep-links into the existing Studio editor with
 * ``?projectId=...&projectClipId=...`` so the Save action there bounces
 * back here.
 *
 * Drag-and-drop reorder uses the native HTML5 API — no extra deps. Any
 * mutation hits the backend (``PATCH/DELETE /studio/projects/:id/clips``)
 * and we replace local state with the response so positions/ripple math
 * stay server-authoritative.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useLocation } from "wouter";
import {
  ArrowDown,
  ArrowUp,
  Clapperboard,
  Clock,
  Film,
  GripVertical,
  Loader2,
  Lock,
  Pencil,
  Play,
  Plus,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import {
  appendStudioProjectClip,
  deleteStudioProjectClip,
  getStudioProject,
  renderStudioProject,
  updateStudioProject,
  updateStudioProjectClip,
  type StudioProjectClip,
  type StudioProjectSpec,
} from "@/lib/api";
import { listSessions } from "@/studio/api";
import { buildDistributionLink } from "@/lib/deepLinks";
import {
  recordRenderTrigger,
  useIsLive,
  useRenderProgressFor,
} from "@/lib/renderProgress";
import { useUpgrade } from "@/contexts/UpgradeContext";
import { usePlan } from "@/hooks/usePlan";
import { useRenderBudget } from "@/lib/useRenderBudget";
import { RenderBudgetNudge } from "@/components/RenderBudgetNudge";

// ---------------------------------------------------------------------------
// Constants — kept in sync with backend ``ProjectSpec`` defaults.
// ---------------------------------------------------------------------------

const ASPECT_OPTIONS: Array<{ value: StudioProjectSpec["default_aspect"]; label: string }> = [
  { value: "9:16", label: "9:16 (Shorts)" },
  { value: "1:1", label: "1:1 (Square)" },
  { value: "4:5", label: "4:5 (Feed)" },
  { value: "16:9", label: "16:9 (YouTube)" },
];

const TRANSITION_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "cut", label: "Cut (no transition)" },
  { value: "fade", label: "Fade" },
  { value: "dissolve", label: "Dissolve" },
  { value: "slide_up", label: "Slide up" },
  { value: "slide_down", label: "Slide down" },
  { value: "zoom_in", label: "Zoom in" },
  { value: "zoom_out", label: "Zoom out" },
  { value: "whoosh", label: "Whoosh" },
  { value: "flash_white", label: "Flash" },
];

function formatSeconds(s: number): string {
  if (!Number.isFinite(s) || s <= 0) return "0:00";
  const total = Math.round(s);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// Mirror of the backend's ``ProjectSpec.total_duration_seconds`` math
// so the header can update optimistically while the API call is in
// flight. Same formula — sum effective durations minus transition
// overlaps (cut has 0 overlap, anything else uses transition_in_ms
// or the project default).
function computeTotalSeconds(spec: StudioProjectSpec): number {
  if (spec.clips.length === 0) return 0;
  const effective = (c: StudioProjectClip) => {
    const dur = Math.max(0, c.source_end_time - c.source_start_time);
    return Math.max(0, dur - (c.trim_in_seconds ?? 0) - (c.trim_out_seconds ?? 0));
  };
  let total = effective(spec.clips[0]);
  for (let i = 1; i < spec.clips.length; i++) {
    const c = spec.clips[i];
    const tType = c.transition_in_type ?? spec.default_transition_type;
    const tMs = c.transition_in_ms ?? spec.default_transition_ms;
    const overlap = tType !== "cut" ? tMs / 1000 : 0;
    total += Math.max(0, effective(c) - overlap);
  }
  return total;
}

// ---------------------------------------------------------------------------
// Add-clip modal (multi-select from user's EditSessions)
// ---------------------------------------------------------------------------

interface DraftSession {
  id: number;
  clip_key: string;
  title: string | null;
  source_video_url: string;
  last_render_status?: string;
  last_render_url?: string | null;
  updated_at: string;
}

function AddClipsModal({
  open,
  onOpenChange,
  alreadyAdded,
  onAdd,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  alreadyAdded: Set<number>;
  onAdd: (sessionIds: number[]) => Promise<void>;
}) {
  const [sessions, setSessions] = useState<DraftSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setSelected(new Set());
    (async () => {
      try {
        const rows = (await listSessions()) as DraftSession[];
        if (!cancelled) setSessions(rows ?? []);
      } catch {
        if (!cancelled) setSessions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const handleConfirm = async () => {
    if (selected.size === 0) return;
    setAdding(true);
    try {
      // Preserve the user's check order — Map iteration order matches
      // insertion. The backend's "append to end" semantics mean this
      // is also the order they'll appear in the project.
      await onAdd(Array.from(selected));
      onOpenChange(false);
    } finally {
      setAdding(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add clips to project</DialogTitle>
          <DialogDescription>
            Pick one or more saved Studio sessions. They'll be appended
            in selection order; you can reorder them later.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[420px] overflow-y-auto space-y-2 py-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-cyan-glow" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-12">
              No saved sessions yet. Edit a clip in the Studio first, then
              come back here to add it to your project.
            </p>
          ) : (
            sessions.map((s) => {
              const isAdded = alreadyAdded.has(s.id);
              const isSelected = selected.has(s.id);
              return (
                <label
                  key={s.id}
                  className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    isAdded
                      ? "opacity-60 cursor-not-allowed bg-secondary/20 border-border/30"
                      : isSelected
                      ? "bg-cyan-glow/10 border-cyan-glow/40"
                      : "bg-secondary/30 border-border/30 hover:border-cyan-glow/40"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={isAdded}
                    onChange={() => !isAdded && toggle(s.id)}
                    className="h-4 w-4"
                  />
                  <Film className="w-4 h-4 text-cyan-glow shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {s.title || "Untitled clip"}
                    </p>
                    <p className="text-xs text-muted-foreground truncate">
                      {s.source_video_url}
                    </p>
                  </div>
                  {isAdded && (
                    <Badge variant="outline" className="text-[10px]">
                      Added
                    </Badge>
                  )}
                </label>
              );
            })
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={adding}
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={selected.size === 0 || adding}
            className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
          >
            {adding ? (
              <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5 mr-1" />
            )}
            Add {selected.size > 0 ? `${selected.size} clip${selected.size === 1 ? "" : "s"}` : "clips"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Clip card (one entry in the rail)
// ---------------------------------------------------------------------------

function ClipCard({
  clip,
  index,
  total,
  projectId,
  defaultTransitionType,
  onMove,
  onPatchTrim,
  onPatchTransition,
  onDelete,
  dragHandlers,
}: {
  clip: StudioProjectClip;
  index: number;
  total: number;
  projectId: number;
  defaultTransitionType: string;
  onMove: (clipId: number, newIndex: number) => void;
  onPatchTrim: (clipId: number, trimIn: number, trimOut: number) => void;
  onPatchTransition: (clipId: number, type: string) => void;
  onDelete: (clipId: number) => void;
  dragHandlers: {
    onDragStart: () => void;
    onDragOver: (e: React.DragEvent) => void;
    onDrop: () => void;
  };
}) {
  const [trimIn, setTrimIn] = useState(clip.trim_in_seconds ?? 0);
  const [trimOut, setTrimOut] = useState(clip.trim_out_seconds ?? 0);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setTrimIn(clip.trim_in_seconds ?? 0);
    setTrimOut(clip.trim_out_seconds ?? 0);
  }, [clip.trim_in_seconds, clip.trim_out_seconds]);

  const sourceDuration = Math.max(
    0,
    clip.source_end_time - clip.source_start_time,
  );
  const effectiveDuration = Math.max(0, sourceDuration - trimIn - trimOut);
  const transitionLabel =
    clip.transition_in_type ??
    (index === 0 ? "(no transition)" : defaultTransitionType);

  return (
    <Card
      draggable
      onDragStart={dragHandlers.onDragStart}
      onDragOver={dragHandlers.onDragOver}
      onDrop={dragHandlers.onDrop}
      className="bg-secondary/40 border-border/40 hover:border-cyan-glow/40 transition-colors"
    >
      <CardContent className="p-3 flex items-center gap-3">
        {/* Drag handle + order arrows. The arrows are the accessible
            fallback for keyboard users; the GripVertical is the visual
            affordance for HTML5 drag-and-drop. */}
        <div className="flex flex-col items-center gap-0.5 shrink-0">
          <GripVertical className="w-4 h-4 text-muted-foreground/60 cursor-grab" />
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            disabled={index === 0}
            onClick={() => onMove(clip.id, index - 1)}
            aria-label="Move up"
          >
            <ArrowUp className="w-3 h-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            disabled={index === total - 1}
            onClick={() => onMove(clip.id, index + 1)}
            aria-label="Move down"
          >
            <ArrowDown className="w-3 h-3" />
          </Button>
        </div>

        {/* Position badge */}
        <div className="w-7 h-7 rounded-full bg-cyan-glow/10 text-cyan-glow text-xs font-mono font-bold flex items-center justify-center shrink-0">
          {index + 1}
        </div>

        {/* Thumbnail / poster */}
        <div className="w-24 h-14 rounded bg-deep-charcoal overflow-hidden shrink-0 flex items-center justify-center">
          {clip.session_render_url ? (
            <video
              src={clip.session_render_url}
              preload="metadata"
              className="w-full h-full object-cover"
              muted
            />
          ) : (
            <Film className="w-5 h-5 text-muted-foreground/50" />
          )}
        </div>

        {/* Title + meta */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">
            {clip.title || "Untitled clip"}
          </p>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
            <Clock className="w-3 h-3" />
            <span>{formatSeconds(effectiveDuration)}</span>
            <span>•</span>
            <span className="capitalize">{transitionLabel.replace(/_/g, " ")}</span>
            <Badge
              variant="outline"
              className={`text-[10px] ${
                clip.session_render_status === "done"
                  ? "border-emerald-500/40 text-emerald-400"
                  : "border-amber-500/40 text-amber-400"
              }`}
            >
              {clip.session_render_status}
            </Badge>
          </div>
        </div>

        {/* Trim inputs */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px] text-muted-foreground">In (s)</label>
            <Input
              type="number"
              min={0}
              step={0.1}
              value={trimIn}
              onChange={(e) => setTrimIn(parseFloat(e.target.value) || 0)}
              onBlur={() => onPatchTrim(clip.id, trimIn, trimOut)}
              className="h-7 w-16 text-xs"
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px] text-muted-foreground">Out (s)</label>
            <Input
              type="number"
              min={0}
              step={0.1}
              value={trimOut}
              onChange={(e) => setTrimOut(parseFloat(e.target.value) || 0)}
              onBlur={() => onPatchTrim(clip.id, trimIn, trimOut)}
              className="h-7 w-16 text-xs"
            />
          </div>
        </div>

        {/* Per-clip transition override (only relevant for clips after the first) */}
        {index > 0 && (
          <Select
            value={clip.transition_in_type ?? "__default"}
            onValueChange={(v) =>
              onPatchTransition(clip.id, v === "__default" ? "" : v)
            }
          >
            <SelectTrigger className="h-7 w-32 text-xs">
              <SelectValue placeholder="Transition" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default">Inherit default</SelectItem>
              {TRANSITION_OPTIONS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <Link
            href={`/dashboard/studio/${clip.clip_key}?projectId=${projectId}&projectClipId=${clip.id}`}
          >
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              title="Edit this clip in the Studio"
            >
              <Pencil className="w-3.5 h-3.5 mr-1" />
              Edit
            </Button>
          </Link>
          <Button
            size="sm"
            variant="ghost"
            className={`h-7 text-xs ${
              confirmDelete ? "text-red-400" : "text-muted-foreground"
            }`}
            onClick={() => {
              if (!confirmDelete) {
                setConfirmDelete(true);
                window.setTimeout(() => setConfirmDelete(false), 3000);
                return;
              }
              onDelete(clip.id);
            }}
            title={confirmDelete ? "Click again to remove" : "Remove from project"}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function StudioProjectPage() {
  const params = useParams<{ projectId: string }>();
  const [, navigate] = useLocation();
  const projectId = useMemo(() => Number(params.projectId), [params.projectId]);
  const { openUpgrade } = useUpgrade();

  const [spec, setSpec] = useState<StudioProjectSpec | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  /** Local draft mirror of ``spec.description`` so the textarea is
   *  fully controlled and we can debounce-save on blur (same pattern
   *  as the title input above). Long-form text — used as the publish
   *  caption seed in the Distribution Hub handoff. */
  const [descriptionDraft, setDescriptionDraft] = useState("");

  // Drag-and-drop state — index of the card the user is dragging.
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  // ---- initial load ---------------------------------------------------
  useEffect(() => {
    if (!Number.isFinite(projectId)) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await getStudioProject(projectId);
        if (!cancelled) {
          setSpec(data);
          setTitleDraft(data.title);
          setDescriptionDraft(data.description ?? "");
        }
      } catch (err) {
        toast.error("Failed to load project");
        if (!cancelled) setSpec(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // ---- live render-progress via WebSocket (Week 8) --------------------
  // ``useRenderProgressFor`` opens a per-tab WebSocket once and exposes
  // the latest event for this project. It transparently falls back to
  // ``/studio/projects/:id/render/status`` polling when the WS is
  // unavailable (no Redis / bad token / repeated reconnect failures),
  // so this single hook replaces the old setInterval block. ``isLive``
  // surfaces which transport is active so the UI can label it.
  const liveEvent = useRenderProgressFor("project", spec?.id ?? null);
  const isLive = useIsLive();

  // Reflect each event into the local spec so the rest of the page
  // (progress bar, status pill, success banner) can keep reading from
  // ``spec`` without knowing the transport changed underneath it.
  useEffect(() => {
    if (!liveEvent || !spec) return;
    setSpec((prev) =>
      prev
        ? {
            ...prev,
            last_render_status: liveEvent.status,
            last_render_url:
              liveEvent.download_url ?? prev.last_render_url,
            last_render_error: liveEvent.error ?? prev.last_render_error,
            render_progress:
              liveEvent.percent ?? prev.render_progress ?? 0,
            render_progress_message:
              liveEvent.message ?? prev.render_progress_message,
          }
        : prev,
    );
    if (liveEvent.status === "done") {
      toast.success("Project render finished");
    } else if (liveEvent.status === "failed") {
      toast.error(`Project render failed${liveEvent.error ? `: ${liveEvent.error}` : ""}`);
    }
  }, [liveEvent?.status, liveEvent?.percent, liveEvent?.message, liveEvent?.download_url]);

  // ---- handlers -------------------------------------------------------
  const refreshFrom = useCallback((next: StudioProjectSpec) => {
    setSpec(next);
    setTitleDraft(next.title);
    setDescriptionDraft(next.description ?? "");
  }, []);

  const handleTitleBlur = async () => {
    if (!spec || !titleDraft.trim() || titleDraft === spec.title) return;
    try {
      const next = await updateStudioProject(spec.id, { title: titleDraft.trim() });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save title");
    }
  };

  const handleDescriptionBlur = async () => {
    if (!spec) return;
    const trimmed = descriptionDraft;
    const current = spec.description ?? "";
    if (trimmed === current) return;
    try {
      const next = await updateStudioProject(spec.id, {
        description: trimmed,
      });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save description");
    }
  };

  const handleAspect = async (value: StudioProjectSpec["default_aspect"]) => {
    if (!spec) return;
    try {
      const next = await updateStudioProject(spec.id, { default_aspect: value });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save aspect");
    }
  };

  const handleDefaultTransition = async (value: string) => {
    if (!spec) return;
    try {
      const next = await updateStudioProject(spec.id, {
        default_transition_type: value,
      });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save transition");
    }
  };

  const handleAddClips = async (sessionIds: number[]) => {
    if (!spec) return;
    let latest = spec;
    for (const sid of sessionIds) {
      try {
        latest = await appendStudioProjectClip(spec.id, {
          edit_session_id: sid,
        });
      } catch {
        toast.error("Couldn't add a clip");
        break;
      }
    }
    refreshFrom(latest);
    toast.success(`Added ${sessionIds.length} clip${sessionIds.length === 1 ? "" : "s"}`);
  };

  const handleMove = async (clipId: number, newIndex: number) => {
    if (!spec) return;
    try {
      const next = await updateStudioProjectClip(spec.id, clipId, {
        position: newIndex,
      });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't reorder clip");
    }
  };

  const handlePatchTrim = async (
    clipId: number,
    trimIn: number,
    trimOut: number,
  ) => {
    if (!spec) return;
    // Clamp negatives — backend already validates ≥ 0 but the UI
    // shouldn't even send invalid values.
    const payload = {
      trim_in_seconds: Math.max(0, trimIn),
      trim_out_seconds: Math.max(0, trimOut),
    };
    try {
      const next = await updateStudioProjectClip(spec.id, clipId, payload);
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save trim");
    }
  };

  const handlePatchTransition = async (clipId: number, type: string) => {
    if (!spec) return;
    try {
      // Empty string from the select means "inherit default" — we
      // pass undefined so the PATCH leaves the field untouched.
      // We can't currently clear it back to null via PATCH (the
      // backend treats null as "no change"); that's a known
      // limitation we'll address if users ask for it.
      const next = await updateStudioProjectClip(spec.id, clipId, {
        transition_in_type: type || undefined,
      });
      refreshFrom(next);
    } catch {
      toast.error("Couldn't save transition");
    }
  };

  const handleDeleteClip = async (clipId: number) => {
    if (!spec) return;
    try {
      const next = await deleteStudioProjectClip(spec.id, clipId);
      refreshFrom(next);
      toast.success("Clip removed");
    } catch {
      toast.error("Couldn't remove clip");
    }
  };

  // Pre-render budget gate (Week 8 Day 4.3). Same as the single-clip
  // editor — pop the upgrade modal instead of letting the server 402.
  const budgetState = useRenderBudget();

  const handleRender = async () => {
    if (!spec) return;
    if (budgetState.isOut) {
      openUpgrade("render_budget");
      return;
    }
    setRendering(true);
    try {
      const status = await renderStudioProject(spec.id);
      // Optimistically seed the WS event store so the progress bar
      // appears instantly, before the worker's first publish lands.
      // Real events arrive via ``useRenderProgressFor`` and overwrite
      // this placeholder.
      recordRenderTrigger("project", spec.id, status.status);
      setSpec((prev) =>
        prev
          ? {
              ...prev,
              last_render_status: status.status,
              last_render_error: null,
              render_progress: status.progress ?? 0,
              render_progress_message:
                status.progress_message ?? "Queued",
            }
          : prev,
      );
      toast.success("Project render started");
    } catch {
      toast.error("Couldn't start render");
    } finally {
      setRendering(false);
    }
  };

  // ---- render ---------------------------------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
      </div>
    );
  }

  if (!spec) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-muted-foreground">Project not found.</p>
        <Link href="/dashboard/drafts">
          <Button variant="outline" size="sm">
            Back to Drafts
          </Button>
        </Link>
      </div>
    );
  }

  const totalSeconds = computeTotalSeconds(spec);
  const isRendering =
    spec.last_render_status === "queued" || spec.last_render_status === "rendering";
  const alreadyAdded = new Set(spec.clips.map((c) => c.edit_session_id));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-end gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
            <Clapperboard className="w-3.5 h-3.5" />
            Studio Project
          </div>
          <Input
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                (e.target as HTMLInputElement).blur();
              }
            }}
            className="text-2xl font-bold border-0 bg-transparent px-0 focus-visible:ring-0 focus-visible:border-b focus-visible:border-cyan-glow/40"
          />
          {/* Long-form description — used as the seed publish caption
              when this project is handed off to the Distribution Hub
              (Week 9 Connected Tools). Stays inline so creators don't
              have to dig into a separate settings panel just to write
              a caption. */}
          <Textarea
            value={descriptionDraft}
            onChange={(e) => setDescriptionDraft(e.target.value)}
            onBlur={handleDescriptionBlur}
            placeholder="Project description (used as the publish caption when you send this to Distribution)"
            rows={2}
            className="mt-1 text-xs border-0 bg-transparent px-0 resize-none focus-visible:ring-0 focus-visible:border-b focus-visible:border-cyan-glow/40 text-muted-foreground placeholder:text-muted-foreground/60"
          />
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1">
            <span>{spec.clips.length} clip{spec.clips.length === 1 ? "" : "s"}</span>
            <span>•</span>
            <span>{formatSeconds(totalSeconds)} total</span>
            <span>•</span>
            <Badge
              variant="outline"
              className={`text-[10px] ${
                spec.last_render_status === "done"
                  ? "border-emerald-500/40 text-emerald-400"
                  : spec.last_render_status === "failed"
                  ? "border-red-500/40 text-red-400"
                  : isRendering
                  ? "border-cyan-glow/40 text-cyan-glow"
                  : "border-border/40 text-muted-foreground"
              }`}
            >
              {spec.last_render_status}
            </Badge>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Select value={spec.default_aspect} onValueChange={handleAspect}>
            <SelectTrigger className="h-9 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ASPECT_OPTIONS.map((a) => (
                <SelectItem key={a.value} value={a.value}>
                  {a.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={spec.default_transition_type}
            onValueChange={handleDefaultTransition}
          >
            <SelectTrigger className="h-9 w-44 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TRANSITION_OPTIONS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* Budget nudge (Week 8 Day 4.3). Quiet on Pro; escalates
              to amber at 80% and red at 100% for free users. */}
          <RenderBudgetNudge
            state={budgetState.state}
            minutesRemaining={
              budgetState.budget && !budgetState.budget.unlimited
                ? budgetState.budget.minutes_remaining
                : undefined
            }
            minutesLimit={
              budgetState.budget && !budgetState.budget.unlimited
                ? budgetState.budget.minutes_limit
                : undefined
            }
          />
          <Button
            onClick={handleRender}
            disabled={
              spec.clips.length === 0 ||
              rendering ||
              isRendering ||
              budgetState.isOut
            }
            className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
            title={
              budgetState.isOut
                ? "Out of render minutes this month. Upgrade for unlimited."
                : undefined
            }
          >
            {rendering || isRendering ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Play className="w-4 h-4 mr-2" />
            )}
            {isRendering ? "Rendering…" : "Render project"}
          </Button>
        </div>
      </div>

      {/* Render progress bar (Week 8: WS-driven; falls back to polling
          transparently inside ``useRenderProgressFor``). The Live/
          Polling pill tells the user why their updates may feel less
          fluid when Redis is unavailable. */}
      {isRendering && (
        <div className="rounded-lg border border-cyan-glow/30 bg-cyan-glow/5 p-3">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="font-medium flex items-center gap-2">
              {spec.render_progress_message || "Rendering…"}
              <Badge
                variant="outline"
                className={`text-[9px] px-1 py-0 ${
                  isLive
                    ? "border-emerald-500/40 text-emerald-400"
                    : "border-amber-500/40 text-amber-400"
                }`}
                title={
                  isLive
                    ? "Live updates via WebSocket"
                    : "WebSocket unavailable — polling every 2s"
                }
              >
                {isLive ? "Live" : "Polling"}
              </Badge>
            </span>
            <span className="text-muted-foreground">
              {spec.render_progress ?? 0}%
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-deep-charcoal overflow-hidden">
            <div
              className="h-full bg-cyan-glow transition-all"
              style={{ width: `${spec.render_progress ?? 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Render result */}
      {spec.last_render_status === "done" && spec.last_render_url && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">Project rendered</p>
            <p className="text-xs text-muted-foreground truncate">
              {spec.last_render_url}
            </p>
          </div>
          <Link
            href={buildDistributionLink({
              renderUrl: spec.last_render_url,
              title: spec.title,
              // Week 9 Connected Tools: also carry the long-form
              // description + projectId so the Distribution Hub
              // pre-fills the caption (vs. starting from just the
              // title every time) and can look up brand-kit /
              // hashtag fallbacks specific to this project.
              description: spec.description ?? undefined,
              projectId: spec.id,
            })}
          >
            <Button size="sm" variant="outline" className="border-emerald-500/40 text-emerald-400">
              <Send className="w-3.5 h-3.5 mr-1" />
              Publish
            </Button>
          </Link>
        </div>
      )}

      {/* Render failure with retry — surfaces the actual error so the
          user doesn't have to dig into devtools. Retry re-enqueues the
          same project (same idempotent endpoint as the original click). */}
      {spec.last_render_status === "failed" && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-red-300">Render failed</p>
            <p className="text-xs text-muted-foreground break-words">
              {spec.last_render_error || "An unknown error occurred."}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="border-red-500/40 text-red-300 hover:bg-red-500/10"
            onClick={handleRender}
            disabled={rendering}
          >
            {rendering ? (
              <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 mr-1" />
            )}
            Retry
          </Button>
        </div>
      )}

      {/* Clip rail */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Clips
          </h2>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="w-3.5 h-3.5 mr-1" />
            Add clip
          </Button>
        </div>

        {spec.clips.length === 0 ? (
          <Card className="border-dashed border-border/40">
            <CardContent className="py-12 text-center">
              <Film className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
              <p className="text-sm font-medium mb-1">No clips yet</p>
              <p className="text-xs text-muted-foreground mb-4">
                Add saved Studio sessions to assemble your long-form video.
              </p>
              <Button
                onClick={() => setAddOpen(true)}
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
              >
                <Plus className="w-4 h-4 mr-2" />
                Add your first clip
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {spec.clips.map((clip, index) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                index={index}
                total={spec.clips.length}
                projectId={spec.id}
                defaultTransitionType={spec.default_transition_type}
                onMove={handleMove}
                onPatchTrim={handlePatchTrim}
                onPatchTransition={handlePatchTransition}
                onDelete={handleDeleteClip}
                dragHandlers={{
                  onDragStart: () => setDragIndex(index),
                  onDragOver: (e) => e.preventDefault(),
                  onDrop: () => {
                    // Move the *dragged* clip (not the drop target)
                    // into the slot of whichever card it was dropped
                    // on. dragIndex is captured at drag-start time;
                    // index is the drop-target's current position.
                    const draggedClip =
                      dragIndex !== null ? spec.clips[dragIndex] : null;
                    if (draggedClip && dragIndex !== index) {
                      handleMove(draggedClip.id, index);
                    }
                    setDragIndex(null);
                  },
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Project-level brand kit — applied as the FINAL overlay so
          the logo lower-third is consistent across every clip
          regardless of per-clip brand kits. */}
      <ProjectBrandKitPanel
        projectId={spec.id}
        brandKit={spec.brand_kit}
        onUpdated={refreshFrom}
      />

      <AddClipsModal
        open={addOpen}
        onOpenChange={setAddOpen}
        alreadyAdded={alreadyAdded}
        onAdd={handleAddClips}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Project Brand Kit panel
// ---------------------------------------------------------------------------

function ProjectBrandKitPanel({
  projectId,
  brandKit,
  onUpdated,
}: {
  projectId: number;
  brandKit: StudioProjectSpec["brand_kit"];
  onUpdated: (next: StudioProjectSpec) => void;
}) {
  const [logoUrl, setLogoUrl] = useState(brandKit.logo_url ?? "");
  const [position, setPosition] = useState<"tl" | "tr" | "bl" | "br">(
    brandKit.logo_position ?? "br",
  );
  const [opacity, setOpacity] = useState(brandKit.logo_opacity ?? 0.85);
  const [saving, setSaving] = useState(false);
  const { openUpgrade } = useUpgrade();
  const { isFree } = usePlan();

  useEffect(() => {
    setLogoUrl(brandKit.logo_url ?? "");
    setPosition((brandKit.logo_position as "tl" | "tr" | "bl" | "br") ?? "br");
    setOpacity(brandKit.logo_opacity ?? 0.85);
  }, [brandKit.logo_url, brandKit.logo_position, brandKit.logo_opacity]);

  const handleSave = async () => {
    // Free plan: branding is a Pro feature. Open the upgrade modal
    // instead of saving so the user understands why the button
    // didn't take effect. The controls stay visible (and editable)
    // so users can preview the experience while deciding.
    if (isFree) {
      openUpgrade("branding");
      return;
    }
    setSaving(true);
    try {
      const next = await updateStudioProject(projectId, {
        brand_kit: {
          logo_url: logoUrl.trim() || null,
          logo_position: position,
          logo_opacity: opacity,
        },
      });
      onUpdated(next);
      toast.success("Project brand kit saved");
    } catch {
      toast.error("Couldn't save brand kit");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="bg-secondary/30 border-border/40">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold">Project brand kit</h3>
              {isFree && (
                <Badge
                  variant="outline"
                  className="text-[10px] border-amber-glow/40 text-amber-glow gap-1"
                >
                  <Sparkles className="w-3 h-3" />
                  Pro
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Logo applied as the final overlay across every clip in this
              project. Layers on top of per-clip brand kits so the
              project stays consistent without overriding per-clip
              branding.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-[11px] text-muted-foreground">Logo URL</label>
            <Input
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.target.value)}
              placeholder="https://… or /api/studio/assets/uploads/..."
              className="h-8 text-xs"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground">Position</label>
              <Select
                value={position}
                onValueChange={(v) =>
                  setPosition(v as "tl" | "tr" | "bl" | "br")
                }
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tl">Top-left</SelectItem>
                  <SelectItem value="tr">Top-right</SelectItem>
                  <SelectItem value="bl">Bottom-left</SelectItem>
                  <SelectItem value="br">Bottom-right</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-muted-foreground">
                Opacity ({Math.round(opacity * 100)}%)
              </label>
              <Input
                type="range"
                min={0.05}
                max={1}
                step={0.05}
                value={opacity}
                onChange={(e) => setOpacity(parseFloat(e.target.value))}
                className="h-8"
              />
            </div>
          </div>
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving}
            className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            ) : isFree ? (
              <Lock className="w-3.5 h-3.5 mr-1" />
            ) : null}
            {isFree ? "Upgrade to save brand kit" : "Save brand kit"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

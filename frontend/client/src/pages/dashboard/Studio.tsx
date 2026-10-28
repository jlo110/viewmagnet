/**
 * Studio — full-screen video editor (Week 2 — Spikes-parity timeline +
 * B-roll loop + undo/redo + live render progress).
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────────────────┐
 *   │ Top bar: title + save badge + undo/redo + render                    │
 *   ├──────┬─────────────┬─────────────────────────┬──────────────────────┤
 *   │ tool │  tool       │   Remotion <Player/>    │   right panel        │
 *   │ stri │  panel      │   (B-roll overlays      │   (aspect / trans-   │
 *   │  p   │  (captions  │    composited live)     │    cript / progress) │
 *   │      │   / B-roll  │                         │                      │
 *   │      │   / brand)  │                         │                      │
 *   ├──────┴─────────────┴─────────────────────────┴──────────────────────┤
 *   │  Timeline: ruler · source · captions · B-roll lanes · playhead      │
 *   └─────────────────────────────────────────────────────────────────────┘
 *
 * State lives in `useEditSession`. Every mutation goes through `updateSpec`
 * which feeds both the debounced auto-save and the coalesced undo history.
 * The Timeline calls `beginInteraction()` at the start of a drag so a
 * gesture becomes ONE undo entry, not 60.
 */
import { Player, type PlayerRef } from "@remotion/player";
import {
  Download,
  Eye,
  EyeOff,
  Film,
  Image as ImageIcon,
  Layers,
  LayoutTemplate,
  Loader2,
  Palette,
  Plus,
  Redo2,
  Search,
  Sparkles,
  Trash2,
  Type,
  Undo2,
  Users,
  Volume2,
  VolumeX,
  Wand2,
  X,
  ZoomIn,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "wouter";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ProBadge } from "@/components/upgrade/ProBadge";
import { RenderBudgetNudge } from "@/components/RenderBudgetNudge";
import { useUpgrade } from "@/contexts/UpgradeContext";
import { usePlan } from "@/hooks/usePlan";
import { useRenderBudget } from "@/lib/useRenderBudget";

import {
  applyTemplate as apiApplyTemplate,
  applyTransitionToAllBoundaries,
  deleteBoundaryTransition,
  deleteUserBrandLogo,
  detectAutoZoom,
  getUserBrandKit,
  listBackgrounds,
  listFeaturedBRoll,
  listTemplates,
  listTransitions,
  postAutoSwitch,
  promoteImageToVideo,
  saveUserBrandKit,
  searchBackgrounds,
  searchBRoll,
  suggestEmojis,
  uploadUserBrandLogo,
  upsertBoundaryTransition,
  type BackgroundCatalogEntry,
  type BackgroundSearchResult,
  type BRollMediaType,
  type BRollSearchResult,
  type FeaturedBRollItem,
  type TemplateInfo,
  type TransitionInfo,
  type UserBrandKit,
} from "@/studio/api";
import { CAPTION_PRESETS } from "@/studio/composition/captionStyles";
import { StudioComposition } from "@/studio/composition/StudioComposition";
import { Timeline, type TimelineSelection } from "@/studio/timeline/Timeline";
import {
  ASPECT_DIMENSIONS,
  ASPECT_LABELS,
  computeClipKey,
  type AspectRatio,
  type AutoZoom,
  type BackgroundLoop,
  type CameraCut,
  type CaptionStyleName,
  type EditSpec,
  type Layout,
  type SourceClip,
  type TrackingData,
  type TransitionCategory,
  type TransitionInstance,
  type Transitions,
  type TransitionType,
} from "@/studio/types";
import { DEMO_SOURCE } from "@/studio/demoSource";
import { readStudioDeepLink, stashPendingCta } from "@/lib/deepLinks";
import { proxyVideoUrl, isYouTubeUrl } from "@/studio/sourceUrl";
import { SourceUploadZone } from "@/studio/SourceUploadZone";
import { useEditSession } from "@/studio/useEditSession";
import {
  useTrackingData,
  type TrackingHookStatus,
} from "@/studio/useTrackingData";
import { useTransitionSfx } from "@/studio/useTransitionSfx";

const FPS = 30;

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function StudioPage() {
  const params = useParams<{ clipKey?: string }>();
  const [, navigate] = useLocation();
  const [resolvedKey, setResolvedKey] = useState<string | null>(params.clipKey ?? null);
  // When another tool (Shorts, Analyzer, Velocity) deep-links into Studio
  // with `?source=&start=&end=&title=` params, we seed a fresh session
  // with that clip instead of the static demo. Resumed sessions (same
  // clipKey already saved on the server) still load from the server —
  // this only affects the *fallback* used when no saved session exists.
  const [seedClip, setSeedClip] = useState<SourceClip>(DEMO_SOURCE);
  const [seedReady, setSeedReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // 1. Resolve seed clip from URL deep-link params (if present).
      //    The deep-link spec lives in `lib/deepLinks.ts` so every
      //    upstream tool uses the same convention.
      const deepLink = params.clipKey ? readStudioDeepLink(params.clipKey) : null;
      let nextSeed: SourceClip = DEMO_SOURCE;
      if (deepLink) {
        // ``end_time = 0`` is the sentinel buildStudioLink emits when
        // the upstream tool (e.g. Analyzer "Re-edit in Studio")
        // doesn't know the source duration yet. Fall back to a
        // 10-minute placeholder; the preview overrides this once the
        // ``<video>`` element loads its real metadata.
        const endTime =
          deepLink.endSeconds > 0 ? deepLink.endSeconds : 600;
        nextSeed = {
          source_url: deepLink.sourceUrl,
          source_clip_path: null,
          start_time: deepLink.startSeconds,
          end_time: endTime,
          suggested_title: deepLink.title ?? null,
          transcript: deepLink.context?.transcript ?? [],
        };

        // Surface a one-time confirmation that the handoff brought
        // over the transcript / hook context — without this the user
        // has no signal that Studio loaded their Shorts/Analyzer
        // data vs the default empty session. The toast is deduped
        // per clipKey via sessionStorage so a refresh doesn't
        // re-fire it.
        const ctx = deepLink.context;
        if (ctx && params.clipKey) {
          // Week 10: persist the CTA envelope into a separate
          // sessionStorage slot so the next session save (from
          // ``useEditSession``) can ship it as ``cta_provenance``.
          // The contextBag itself is single-use and would be cleared
          // before the autosave fires, so we mirror the CTA only.
          if (ctx.cta?.tool) {
            stashPendingCta(params.clipKey, ctx.cta);
          }
          const seenKey = `viewmagnet.studio.handoff.${params.clipKey}`;
          if (typeof window !== "undefined" && !sessionStorage.getItem(seenKey)) {
            sessionStorage.setItem(seenKey, "1");
            const pieces: string[] = [];
            if (ctx.transcript?.length) {
              pieces.push(`${ctx.transcript.length} transcript words`);
            }
            if (ctx.hooks?.length) {
              pieces.push(
                ctx.hooks.length === 1
                  ? `${ctx.hooks[0]} hook hint`
                  : `${ctx.hooks.length} hook hints`,
              );
            }
            if (pieces.length) {
              const origin = ctx.origin ? ` from ${ctx.origin}` : "";
              toast.success(`Pre-loaded ${pieces.join(" + ")}${origin}`);
            }
          }
        }
      }
      if (!cancelled) {
        setSeedClip(nextSeed);
        setSeedReady(true);
      }

      // 2. Resolve the clip key. If the route already has one, trust it.
      //    Otherwise either derive from deep-link params (rare — usually
      //    the upstream tool already navigated to a /studio/:clipKey URL)
      //    or fall back to the demo.
      if (params.clipKey) {
        setResolvedKey(params.clipKey);
        return;
      }
      const seedForKey = deepLink ? nextSeed : DEMO_SOURCE;
      const key = await computeClipKey(
        seedForKey.source_url,
        0,
        seedForKey.start_time,
        seedForKey.end_time,
      );
      if (!cancelled) {
        setResolvedKey(key);
        // Preserve any deep-link query params on the redirect so the
        // editor mount can still pick them up (readStudioDeepLink reads
        // window.location.search).
        const search = window.location.search;
        navigate(`/dashboard/studio/${key}${search}`, { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.clipKey, navigate]);

  if (!resolvedKey || !seedReady) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin opacity-60" />
      </div>
    );
  }

  return <StudioEditor clipKey={resolvedKey} fallbackClip={seedClip} />;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Stable per-clip / per-cut ID generator, mirroring the backend's
 *  ``_stable_id`` in src/features/studio/spec.py. ``crypto.randomUUID``
 *  is available in all modern browsers + jsdom + Vitest. Six hex bytes
 *  is the same width the backend uses (collision risk negligible for the
 *  N≈100 clips an editor session realistically holds). */
function stableId(): string {
  // Try the cheap modern API first; fall back to Math.random() so unit
  // tests under older runtimes don't blow up.
  const u =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
  return u.slice(0, 12);
}

// ---------------------------------------------------------------------------
// Editor body
// ---------------------------------------------------------------------------

interface StudioEditorProps {
  clipKey: string;
  fallbackClip: SourceClip;
}

function StudioEditor({ clipKey, fallbackClip }: StudioEditorProps) {
  const {
    loading,
    error,
    spec,
    setSpec,
    updateSpec,
    saveState,
    render,
    rendering,
    renderUrl,
    renderError,
    renderProgress,
    beginInteraction,
    undo,
    redo,
    canUndo,
    canRedo,
  } = useEditSession({ clipKey, fallbackClip, fallbackTitle: fallbackClip.suggested_title ?? undefined });

  const playerRef = useRef<PlayerRef>(null);
  const [activeTool, setActiveTool] = useState<ToolId>("captions");
  const [selection, setSelection] = useState<TimelineSelection>({ kind: "none" });
  // Timeline zoom (1 = fit-to-container, 16 = max). Owned here so the
  // top-level Cmd-+/-/0 shortcuts can poke it without prop-drilling state
  // back from Timeline.
  const [zoom, setZoom] = useState(1);

  // Auto-jump to Effects tool when a boundary marker (single diamond OR
  // "between two clips" pill) is clicked so the user lands directly on
  // the per-boundary transition controls.
  useEffect(() => {
    if (selection.kind === "boundary" || selection.kind === "between") {
      setActiveTool("effects");
    }
  }, [selection]);

  // UI state for the boundary "Apply to all" button — driven by the
  // bulk endpoint round-trip so the user gets feedback when the global
  // default is stamped onto every boundary.
  const [applyAllStatus, setApplyAllStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");

  // Auto-run subject tracking on session open (Week 4). Refetch whenever the
  // user changes the requested subject count; the polling hook handles the
  // 503-with-retry pattern when the worker is still computing.
  const nSubjects = spec?.camera?.n_subjects_requested ?? 4;
  const tracking = useTrackingData(clipKey, nSubjects);

  // Memoize the Player's inputProps so the Player doesn't see a fresh object
  // reference on every Studio.tsx render (zoom drag, timeline tick, tracking
  // poll, etc). A new inputProps reference makes Remotion deep-diff the prop
  // tree which can interrupt the <video> element's loading state on Safari.
  // Must be declared BEFORE any early returns below — hooks rule.
  //
  // When the source is a YouTube URL (which Railway's datacenter IP can't
  // fetch), we show an upload zone instead of the player. Once the user drops
  // their footage we have two URLs:
  //   - blobUrl  → immediate client-side preview (blob: URI, never saved)
  //   - serverUrl → server-side path for rendering (set after upload finishes)
  const [localBlobUrl, setLocalBlobUrl] = useState<string | null>(null);
  const needsLocalFile =
    isYouTubeUrl(spec?.clip.source_url) && !localBlobUrl;

  // ``videoUrl`` is routed through ``proxyVideoUrl`` so cross-origin MP4s
  // get rewritten to faststart on first request — Safari otherwise refuses
  // to paint the first frame for moov-at-end uploads. When the user has
  // supplied a local file we use the blob URL directly (no proxy needed).
  const resolvedVideoUrl = localBlobUrl
    ? localBlobUrl
    : proxyVideoUrl(spec?.clip.source_url);

  const playerInputProps = useMemo(
    () => ({
      spec: spec as EditSpec,
      videoUrl: resolvedVideoUrl,
      tracking: tracking.data,
    }),
    [spec, resolvedVideoUrl, tracking.data],
  );

  // Pre-render budget gate (Week 8 Day 4.3). Free users that are
  // already past 100% should never reach the server enqueue — we
  // pop the upgrade modal instead. Pro/Enterprise short-circuits
  // to ``state === "unlimited"`` so the gate is invisible.
  const budgetState = useRenderBudget();
  const { openUpgrade: openUpgradeReason } = useUpgrade();

  const handleRender = useCallback(async () => {
    if (budgetState.isOut) {
      openUpgradeReason("render_budget");
      return;
    }
    const status = await render();
    if (!status) {
      toast.error(renderError ?? "Render failed");
      return;
    }
    if (status.status === "done" && status.last_render_url) {
      toast.success("Render complete! Output saved.");
    } else if (status.status === "queued" || status.status === "rendering") {
      toast.info("Render queued — progress will update live");
    } else if (status.status === "failed") {
      toast.error("Render failed — check API logs");
    }
  }, [budgetState.isOut, openUpgradeReason, render, renderError]);

  // ---------------------------------------------------------------------
  // Camera lane helpers (Week 4)
  // ---------------------------------------------------------------------

  // Backfill ``camera`` on a draft EditSpec for legacy sessions saved before
  // Week 4. The server normalizes specs on read so this is belt-and-braces
  // for stale cached payloads during the same browser session.
  function ensureCamera(s: EditSpec) {
    if (!s.camera) {
      s.camera = {
        tracks: [],
        bbox_overlay_enabled: false,
        ease_pan: false,
        n_subjects_requested: 4,
      };
    }
    return s.camera;
  }

  const insertCameraCut = useCallback(
    (subjectId: number, atSeconds: number) => {
      if (!spec) return;
      beginInteraction();
      updateSpec((s) => {
        ensureCamera(s);
        const dur = s.clip.end_time - s.clip.start_time;
        const start = Math.max(0, Math.min(dur, atSeconds));
        const sorted = s.camera.tracks
          .map((c, i) => ({ c, i }))
          .sort((a, b) => a.c.start - b.c.start);

        // Find the next existing cut that starts AFTER `start`. New cut runs
        // until that one (Premiere multi-cam semantics). If no cut starts
        // after us, run to clip end. Also trim any overlapping cut that
        // contains `start` to end at our new boundary.
        let nextStart = dur;
        for (const { c } of sorted) {
          if (c.start > start && c.start < nextStart) nextStart = c.start;
          if (c.start <= start && c.end > start) {
            c.end = start;
          }
        }
        // Drop any zero/negative-length cuts created by the trim above.
        s.camera.tracks = s.camera.tracks.filter((c) => c.end > c.start + 0.001);

        s.camera.tracks.push({
          id: stableId(),
          start,
          end: Math.max(start + 0.3, nextStart),
          subject_id: subjectId,
        });
        s.camera.tracks.sort((a, b) => a.start - b.start);
      });
    },
    [spec, updateSpec, beginInteraction],
  );

  const handleAutoSwitch = useCallback(async () => {
    if (!spec) return;
    if (tracking.status !== "done" || !tracking.data) {
      toast.error("Tracking still computing — try again in a moment");
      return;
    }
    try {
      const tracks = await postAutoSwitch(clipKey);
      if (tracks.length === 0) {
        toast.info("Auto-switch couldn't pick any cuts");
        return;
      }
      beginInteraction();
      updateSpec((s) => {
        ensureCamera(s).tracks = tracks;
      });
      toast.success(`Auto-switch picked ${tracks.length} camera cuts`);
    } catch (err) {
      toast.error("Auto-switch failed");
    }
  }, [spec, tracking.status, tracking.data, clipKey, updateSpec, beginInteraction]);

  // ---------------------------------------------------------------------
  // Templates + Effects (Week 5)
  // ---------------------------------------------------------------------

  const [templates, setTemplates] = useState<TemplateInfo[] | null>(null);
  const [applyingTemplate, setApplyingTemplate] = useState<string | null>(null);
  const [detectingZoom, setDetectingZoom] = useState(false);
  const [suggestingEmojis, setSuggestingEmojis] = useState(false);

  // Fetch the template catalog once per editor mount. Cheap (5 small rows)
  // and lets the Templates panel render synchronously when the user opens it.
  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((items) => {
        if (!cancelled) setTemplates(items);
      })
      .catch(() => {
        // Non-fatal — the panel renders an empty state.
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleApplyTemplate = useCallback(
    async (name: string) => {
      if (!spec) return;
      setApplyingTemplate(name);
      try {
        beginInteraction();
        const session = await apiApplyTemplate(clipKey, name);
        // The server returns the freshly normalized session with the merged
        // spec — drop straight into local state and the debounced save loop
        // will see no diff (lastSavedJson tracks what was last persisted).
        setSpec(session.spec);
        toast.success(`Applied "${name}" template`);
      } catch (err) {
        toast.error(`Couldn't apply ${name}`);
      } finally {
        setApplyingTemplate(null);
      }
    },
    [spec, clipKey, setSpec, beginInteraction],
  );

  const handleDetectZooms = useCallback(async () => {
    if (!spec) return;
    if (!spec.clip.transcript.length) {
      toast.error("Need a transcript to detect zooms");
      return;
    }
    setDetectingZoom(true);
    try {
      const result = await detectAutoZoom(clipKey);
      beginInteraction();
      updateSpec((s) => {
        if (!s.auto_zoom) {
          s.auto_zoom = { enabled: true, max_scale: 1.2, timestamps: [] };
        }
        s.auto_zoom.timestamps = result.timestamps;
        s.auto_zoom.enabled = true;
      });
      toast.success(`Found ${result.count} zoom moments`);
    } catch (err) {
      toast.error("Zoom detection failed");
    } finally {
      setDetectingZoom(false);
    }
  }, [spec, clipKey, updateSpec, beginInteraction]);

  const handleSuggestEmojis = useCallback(async () => {
    if (!spec) return;
    if (!spec.clip.transcript.length) {
      toast.error("Need a transcript to suggest emojis");
      return;
    }
    setSuggestingEmojis(true);
    try {
      const result = await suggestEmojis(clipKey);
      // The backend returns the updated spec with .emoji fields populated
      // on the affected words. We replace the whole spec to stay in sync
      // with the persisted server copy, but capture a history entry first
      // so the user can undo back to the un-decorated transcript.
      beginInteraction();
      setSpec(result.spec);
      toast.success(`Added ${result.n_suggestions} emojis`);
    } catch (err) {
      toast.error("Emoji suggestion failed");
    } finally {
      setSuggestingEmojis(false);
    }
  }, [spec, clipKey, setSpec, beginInteraction]);

  const handleClearEmojis = useCallback(() => {
    beginInteraction();
    updateSpec((s) => {
      for (const w of s.clip.transcript) {
        if (w.emoji) w.emoji = null;
      }
    });
  }, [updateSpec, beginInteraction]);

  // SFX preview — fires fade/swipe/whoosh stingers as the playhead crosses
  // each transition boundary. Mirrors the backend SFX mixing so what the
  // user hears in the preview matches the rendered MP4.
  useTransitionSfx({ playerRef, spec, fps: FPS });

  // Bbox-click in the preview dispatches studio:camera-insert-cut. Listen
  // here so we can route through our insertCameraCut (which is the single
  // source of truth for the Premiere-style "until next cut" semantics).
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ subjectId: number; t: number }>).detail;
      if (detail == null) return;
      insertCameraCut(detail.subjectId, detail.t);
    };
    window.addEventListener("studio:camera-insert-cut", handler);
    return () => window.removeEventListener("studio:camera-insert-cut", handler);
  }, [insertCameraCut]);

  // Keyboard shortcuts ----------------------------------------------------
  // Single top-level keydown listener with input-focus guard so typing in
  // the transcript / search inputs doesn't trigger seek/play/delete.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      const isEditable =
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        target?.isContentEditable === true;
      if (isEditable) return;

      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
        return;
      }

      // Zoom shortcuts — match the standard zoom set used by every browser
      // and by most NLEs. `=` is the unshifted `+` key on US layouts.
      if (mod && (e.key === "=" || e.key === "+")) {
        e.preventDefault();
        setZoom((z) => Math.min(16, z * 1.5));
        return;
      }
      if (mod && e.key === "-") {
        e.preventDefault();
        setZoom((z) => Math.max(1, z / 1.5));
        return;
      }
      if (mod && e.key === "0") {
        e.preventDefault();
        setZoom(1);
        return;
      }

      // S → toggle the manual caption break/merge on the word before the
      // currently selected one. Hands off to Timeline via a custom event so
      // the toggle logic + history tracking stay close to the rest of the
      // caption-lane code.
      if ((e.key === "s" || e.key === "S") && selection.kind === "word" && !mod) {
        e.preventDefault();
        window.dispatchEvent(
          new CustomEvent("studio:caption-split", {
            detail: { action: e.shiftKey ? "reset" : "toggle" },
          }),
        );
        return;
      }

      // T → switch to the Templates panel; E → switch to the Effects panel.
      // Quick-access shortcuts for the Week 5 "auto-magic" tools.
      if (!mod && (e.key === "t" || e.key === "T")) {
        e.preventDefault();
        setActiveTool("templates");
        return;
      }
      if (!mod && (e.key === "e" || e.key === "E")) {
        e.preventDefault();
        setActiveTool("effects");
        return;
      }
      // B → Backgrounds panel, L → Layout panel (Week 6 Phase 5).
      // L overrides the JKL "forward 1s" shortcut intentionally — use
      // Shift+ArrowRight for the 1-second seek instead.
      if (!mod && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        setActiveTool("backgrounds");
        return;
      }
      if (!mod && (e.key === "l" || e.key === "L")) {
        e.preventDefault();
        setActiveTool("layout");
        return;
      }

      // 1-4 → insert a CameraCut at the playhead for subject N (Premiere-style
      // multi-cam). Requires tracking to be loaded — otherwise we don't know
      // what subject IDs exist. The "ends at the next existing cut or
      // clip.end_time" math happens in insertCameraCut().
      if (
        !mod &&
        ["1", "2", "3", "4"].includes(e.key) &&
        tracking.data &&
        spec
      ) {
        const subjectId = parseInt(e.key, 10) - 1;
        const subjectExists = tracking.data.subjects.some(
          (s) => s.id === subjectId,
        );
        if (!subjectExists) return;
        e.preventDefault();
        const player = playerRef.current;
        const t = player ? player.getCurrentFrame() / FPS : 0;
        insertCameraCut(subjectId, t);
        return;
      }

      const player = playerRef.current;
      if (!player) return;

      if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        player.toggle();
      } else if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        player.seekTo(Math.max(0, player.getCurrentFrame() - FPS));
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        player.pause();
        // NOTE: the JKL convention's "l" (forward 1s) was repurposed for
        // the Layout panel shortcut above. Use Shift+ArrowRight for the
        // 1-second seek instead.
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        const step = e.shiftKey ? FPS : 1;
        player.seekTo(Math.max(0, player.getCurrentFrame() - step));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        const step = e.shiftKey ? FPS : 1;
        player.seekTo(player.getCurrentFrame() + step);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (selection.kind === "broll") {
          e.preventDefault();
          beginInteraction();
          updateSpec((s) => {
            s.broll.clips.splice(selection.index, 1);
          });
          setSelection({ kind: "none" });
        } else if (selection.kind === "camera") {
          e.preventDefault();
          beginInteraction();
          updateSpec((s) => {
            if (s.camera?.tracks) s.camera.tracks.splice(selection.index, 1);
          });
          setSelection({ kind: "none" });
        } else if (selection.kind === "zoom") {
          e.preventDefault();
          beginInteraction();
          updateSpec((s) => {
            if (s.auto_zoom?.timestamps) {
              s.auto_zoom.timestamps.splice(selection.index, 1);
            }
          });
          setSelection({ kind: "none" });
        } else if (selection.kind === "boundary" && clipKey) {
          // Deleting a boundary "removes the override" — falls back to the
          // global default. Optimistic UI: drop from local spec first, then
          // call the backend; failures revert via the auto-save round-trip.
          e.preventDefault();
          const boundaryId = selection.id;
          beginInteraction();
          updateSpec((s) => {
            s.boundary_transitions = (s.boundary_transitions ?? []).filter(
              (t: TransitionInstance) => t.boundary_id !== boundaryId,
            );
          });
          setSelection({ kind: "none" });
          void deleteBoundaryTransition(clipKey, boundaryId).catch((err) => {
            console.error("studio.boundary.delete_failed", err);
          });
        } else if (selection.kind === "between" && clipKey) {
          // Deleting a between-pair removes BOTH the OUT and IN overrides.
          // We deliberately leave the clip positions alone: undoing the
          // overlap automatically when the user clears the transition
          // would surprise them mid-edit. They can drag clip B back if
          // they want the original gap.
          e.preventDefault();
          const outId = selection.outId;
          const inId = selection.inId;
          beginInteraction();
          updateSpec((s) => {
            s.boundary_transitions = (s.boundary_transitions ?? []).filter(
              (t: TransitionInstance) =>
                t.boundary_id !== outId && t.boundary_id !== inId,
            );
          });
          setSelection({ kind: "none" });
          void deleteBoundaryTransition(clipKey, outId).catch((err) => {
            console.error("studio.boundary.delete_failed", err);
          });
          void deleteBoundaryTransition(clipKey, inId).catch((err) => {
            console.error("studio.boundary.delete_failed", err);
          });
        }
        // Word selection intentionally does NOT delete the transcript word
        // on backspace — deleting transcript words drifts the audio
        // alignment. Use the transcript editor on the right to edit text.
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo, beginInteraction, updateSpec, selection, spec, tracking.data]);

  if (loading || !spec) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin opacity-60" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-[calc(100vh-64px)] items-center justify-center">
        <Card className="p-6 text-sm text-red-500">Failed to load session: {error}</Card>
      </div>
    );
  }

  const dims = ASPECT_DIMENSIONS[spec.aspect_ratio];
  const durationFrames = Math.max(
    1,
    Math.round((spec.clip.end_time - spec.clip.start_time) * FPS),
  );

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col bg-zinc-950 text-zinc-100">
      {/* Top bar -------------------------------------------------------- */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
        <div className="flex items-center gap-3">
          {/* Project breadcrumb — surfaces when this clip is being
              edited as part of a multi-clip Project (Week 7). Lets the
              user bounce back to the project view instead of forcing
              a hard browser-back. */}
          <ProjectBreadcrumb />
          <span className="text-sm font-medium opacity-70">Studio</span>
          <span className="text-sm">·</span>
          <span className="text-sm truncate max-w-[40ch]">
            {fallbackClip.suggested_title ?? "Untitled clip"}
          </span>
          <SaveBadge state={saveState} />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={undo}
            disabled={!canUndo}
            title="Undo (⌘Z)"
            className="h-8 w-8 p-0"
          >
            <Undo2 className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={redo}
            disabled={!canRedo}
            title="Redo (⌘⇧Z)"
            className="h-8 w-8 p-0"
          >
            <Redo2 className="h-4 w-4" />
          </Button>
          <div className="w-px h-5 bg-zinc-800" />
          {renderUrl && (
            <a
              href={renderUrl}
              download
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-3 py-1.5 text-xs hover:bg-zinc-800"
            >
              <Download className="h-3 w-3" />
              Last render
            </a>
          )}
          {/* Budget nudge — quiet on Pro, escalates to amber at 80%
              and red at 100% for free users (Week 8 Day 4.3). */}
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
            disabled={rendering || budgetState.isOut}
            className="gap-1.5"
            title={
              budgetState.isOut
                ? "Out of render minutes this month. Upgrade for unlimited."
                : undefined
            }
          >
            {rendering ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {rendering ? "Rendering…" : "Render"}
          </Button>
        </div>
      </div>

      {/* Render-progress strip — collapses out when idle. */}
      {(rendering ||
        renderProgress.status === "queued" ||
        renderProgress.status === "rendering") && (
        <RenderProgressBar progress={renderProgress} />
      )}

      {/* Main row ------------------------------------------------------- */}
      <div className="flex min-h-0 flex-1">
        {/* Left tool strip */}
        <LeftToolStrip active={activeTool} onChange={setActiveTool} />

        {/* Tool panel */}
        <div className="w-72 border-r border-zinc-800 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="p-3">
              {activeTool === "captions" && (
                <CaptionStylePanel
                  selected={spec.captions.style}
                  uppercase={spec.captions.uppercase}
                  position={spec.captions.position}
                  highlightMode={spec.captions.highlight_mode}
                  fontSize={spec.captions.font_size}
                  colorHighlight={spec.captions.color_highlight}
                  onChangeStyle={(style) =>
                    updateSpec((s) => {
                      s.captions.style = style;
                    })
                  }
                  onChangeUpper={(v) =>
                    updateSpec((s) => {
                      s.captions.uppercase = v;
                    })
                  }
                  onChangePosition={(p) =>
                    updateSpec((s) => {
                      s.captions.position = p;
                    })
                  }
                  onChangeHighlight={(h) =>
                    updateSpec((s) => {
                      s.captions.highlight_mode = h;
                    })
                  }
                  onChangeSize={(n) =>
                    updateSpec((s) => {
                      s.captions.font_size = n;
                    })
                  }
                  onChangeHighlightColor={(c) =>
                    updateSpec((s) => {
                      s.captions.color_highlight = c;
                    })
                  }
                  emojiEnabled={spec.captions.emoji_enabled}
                  hasAnyEmoji={spec.clip.transcript.some((w) => !!w.emoji)}
                  hasTranscript={spec.clip.transcript.length > 0}
                  suggestingEmojis={suggestingEmojis}
                  onToggleEmoji={(v) =>
                    updateSpec((s) => {
                      s.captions.emoji_enabled = v;
                    })
                  }
                  onSuggestEmojis={handleSuggestEmojis}
                  onClearEmojis={handleClearEmojis}
                />
              )}
              {activeTool === "broll" && (
                <BRollPanel
                  initialQuery={spec.clip.suggested_title ?? ""}
                  onAdd={(clip) =>
                    updateSpec((s) => {
                      const lastEnd = s.broll.clips.length
                        ? Math.max(...s.broll.clips.map((c) => c.end))
                        : s.clip.start_time;
                      const start = Math.max(0, lastEnd - s.clip.start_time);
                      s.broll.clips.push({
                        id: stableId(),
                        track: 2,
                        start,
                        end: Math.min(spec.clip.end_time - spec.clip.start_time, start + Math.min(4, clip.duration)),
                        clip_url: clip.download_url,
                        source: clip.source,
                        opacity: 1.0,
                        mute: true,
                        label: clip.title,
                      });
                    })
                  }
                  onAddFeatured={(clip) =>
                    updateSpec((s) => {
                      // Insert at the playhead (or 0 if the player hasn't
                      // mounted yet) so quick-picks feel like dropping a
                      // sticker — the user knows exactly where it landed.
                      const player = playerRef.current;
                      const localDuration =
                        s.clip.end_time - s.clip.start_time;
                      const playheadSec = player
                        ? player.getCurrentFrame() / FPS
                        : 0;
                      const start = Math.max(
                        0,
                        Math.min(playheadSec, Math.max(0, localDuration - 1.0)),
                      );
                      const end = Math.min(
                        localDuration,
                        start + Math.min(clip.duration_seconds, 4.0),
                      );
                      s.broll.clips.push({
                        id: stableId(),
                        track: 2,
                        start,
                        end,
                        clip_url: clip.download_url,
                        source: "upload",
                        opacity: 1.0,
                        mute: true,
                        label: clip.label,
                      });
                    })
                  }
                  selectedClips={spec.broll.clips}
                  onRemove={(i) =>
                    updateSpec((s) => {
                      s.broll.clips.splice(i, 1);
                    })
                  }
                />
              )}
              {activeTool === "camera" && (
                <CameraPanel
                  spec={spec}
                  tracking={tracking.data}
                  trackingStatus={tracking.status}
                  trackingProgress={tracking.progress}
                  trackingProgressMessage={tracking.progressMessage}
                  trackingError={tracking.error}
                  onAutoSwitch={handleAutoSwitch}
                  onRefreshTracking={tracking.refresh}
                  onToggleBbox={(v) =>
                    updateSpec((s) => {
                      ensureCamera(s).bbox_overlay_enabled = v;
                    })
                  }
                  onToggleEasePan={(v) =>
                    updateSpec((s) => {
                      ensureCamera(s).ease_pan = v;
                    })
                  }
                  onChangeNSubjects={(n) =>
                    updateSpec((s) => {
                      ensureCamera(s).n_subjects_requested = n;
                    })
                  }
                  onClearTracks={() =>
                    updateSpec((s) => {
                      ensureCamera(s).tracks = [];
                    })
                  }
                  onInsertCutForSubject={(subjectId) => {
                    const player = playerRef.current;
                    const t = player ? player.getCurrentFrame() / FPS : 0;
                    insertCameraCut(subjectId, t);
                  }}
                />
              )}
              {activeTool === "branding" && (
                <BrandKitPanel
                  brandKit={spec.brand_kit}
                  beginInteraction={beginInteraction}
                  onUpdate={(patch) =>
                    updateSpec((s) => {
                      Object.assign(s.brand_kit, patch);
                    })
                  }
                />
              )}
              {activeTool === "templates" && (
                <TemplatesPanel
                  templates={templates}
                  activeTemplate={spec.template ?? null}
                  applyingName={applyingTemplate}
                  onApply={handleApplyTemplate}
                />
              )}
              {activeTool === "effects" && (
                <EffectsPanel
                  autoZoom={spec.auto_zoom}
                  transitions={spec.transitions}
                  detecting={detectingZoom}
                  hasTranscript={spec.clip.transcript.length > 0}
                  onDetectZooms={handleDetectZooms}
                  onToggleAutoZoom={(v) =>
                    updateSpec((s) => {
                      if (!s.auto_zoom) {
                        s.auto_zoom = {
                          enabled: v,
                          max_scale: 1.2,
                          timestamps: [],
                        };
                      } else {
                        s.auto_zoom.enabled = v;
                      }
                    })
                  }
                  onChangeMaxScale={(n) =>
                    updateSpec((s) => {
                      if (!s.auto_zoom) {
                        s.auto_zoom = {
                          enabled: false,
                          max_scale: n,
                          timestamps: [],
                        };
                      } else {
                        s.auto_zoom.max_scale = n;
                      }
                    })
                  }
                  onClearZooms={() =>
                    updateSpec((s) => {
                      if (s.auto_zoom) s.auto_zoom.timestamps = [];
                    })
                  }
                  onChangeTxEnabled={(v) =>
                    updateSpec((s) => {
                      s.transitions.enabled = v;
                    })
                  }
                  onChangeTxType={(t) =>
                    updateSpec((s) => {
                      s.transitions.type = t;
                      // Toggling away from "cut" enables transitions so
                      // changing the type takes effect immediately.
                      if (t !== "cut") s.transitions.enabled = true;
                    })
                  }
                  onChangeTxDuration={(ms) =>
                    updateSpec((s) => {
                      s.transitions.duration_ms = ms;
                    })
                  }
                  onChangeTxSfx={(v) =>
                    updateSpec((s) => {
                      s.transitions.sfx_enabled = v;
                    })
                  }
                  selectedBoundaryId={
                    selection.kind === "boundary" ? selection.id : null
                  }
                  boundaryInstance={
                    selection.kind === "boundary"
                      ? (spec.boundary_transitions ?? []).find(
                          (t) => t.boundary_id === selection.id,
                        ) ?? null
                      : null
                  }
                  onUpsertBoundary={(instance) => {
                    if (!clipKey) return;
                    // Optimistic update: patch the spec locally so the
                    // preview updates instantly, then mirror to backend.
                    beginInteraction();
                    updateSpec((s) => {
                      const list = s.boundary_transitions ?? [];
                      const idx = list.findIndex(
                        (t) => t.boundary_id === instance.boundary_id,
                      );
                      if (idx === -1) list.push(instance);
                      else list[idx] = instance;
                      s.boundary_transitions = list;
                      // Mirror what the backend's upsert handler does so
                      // the global enable flag isn't stuck false.
                      s.transitions.enabled = true;
                    });
                    void upsertBoundaryTransition(clipKey, instance).catch(
                      (err) =>
                        console.error("studio.boundary.upsert_failed", err),
                    );
                  }}
                  onClearBoundary={() => {
                    if (!clipKey || selection.kind !== "boundary") return;
                    const boundaryId = selection.id;
                    beginInteraction();
                    updateSpec((s) => {
                      s.boundary_transitions = (s.boundary_transitions ?? []).filter(
                        (t) => t.boundary_id !== boundaryId,
                      );
                    });
                    void deleteBoundaryTransition(clipKey, boundaryId).catch(
                      (err) =>
                        console.error("studio.boundary.delete_failed", err),
                    );
                  }}
                  selectedBetween={
                    selection.kind === "between"
                      ? {
                          outId: selection.outId,
                          inId: selection.inId,
                          clipAIdx: selection.clipAIdx,
                          clipBIdx: selection.clipBIdx,
                        }
                      : null
                  }
                  betweenInstance={
                    selection.kind === "between"
                      ? (spec.boundary_transitions ?? []).find(
                          (t) =>
                            t.boundary_id === selection.outId ||
                            t.boundary_id === selection.inId,
                        ) ?? null
                      : null
                  }
                  onUpsertBetween={(template) => {
                    if (!clipKey || selection.kind !== "between") return;
                    // CapCut-style "transition between clips":
                    //
                    //   1. Stamp the SAME instance on BOTH boundaries so
                    //      the renderer applies a matching fade-out to A
                    //      and fade-in to B, which blends to a true
                    //      crossfade during the overlap.
                    //   2. Shift clip B leftward (BOTH start and end) by
                    //      duration_ms so the clips overlap by that much.
                    //      We keep B's source duration intact — only its
                    //      position on the timeline moves.
                    //   3. Clamp so B can't overlap clip A entirely or go
                    //      below 0 on the timeline.
                    const outId = selection.outId;
                    const inId = selection.inId;
                    const clipAIdx = selection.clipAIdx;
                    const clipBIdx = selection.clipBIdx;
                    const durationSeconds =
                      Math.max(100, template.duration_ms || 400) / 1000;

                    const outInstance: TransitionInstance = {
                      ...template,
                      boundary_id: outId,
                    };
                    const inInstance: TransitionInstance = {
                      ...template,
                      boundary_id: inId,
                    };

                    beginInteraction();
                    updateSpec((s) => {
                      // Stamp both boundaries with the chosen transition.
                      const list = s.boundary_transitions ?? [];
                      for (const inst of [outInstance, inInstance]) {
                        const idx = list.findIndex(
                          (t) => t.boundary_id === inst.boundary_id,
                        );
                        if (idx === -1) list.push(inst);
                        else list[idx] = inst;
                      }
                      s.boundary_transitions = list;
                      s.transitions.enabled = true;

                      // Auto-overlap: pull clip B leftward so it overlaps
                      // clip A by ``durationSeconds``. Skip if either clip
                      // index moved (defensive) or the math would make
                      // clip B negative / shorter than 0.2s.
                      const clipA = s.broll?.clips?.[clipAIdx];
                      const clipB = s.broll?.clips?.[clipBIdx];
                      if (clipA && clipB) {
                        const targetStart = clipA.end - durationSeconds;
                        const maxStartLeftBound = Math.max(
                          0,
                          clipA.start + 0.2,
                        );
                        const newStart = Math.max(
                          maxStartLeftBound,
                          targetStart,
                        );
                        const sourceDuration = clipB.end - clipB.start;
                        if (
                          newStart < clipB.start &&
                          sourceDuration > 0.2
                        ) {
                          clipB.start = newStart;
                          clipB.end = newStart + sourceDuration;
                        }
                      }
                    });

                    void upsertBoundaryTransition(clipKey, outInstance).catch(
                      (err) =>
                        console.error("studio.boundary.upsert_failed", err),
                    );
                    void upsertBoundaryTransition(clipKey, inInstance).catch(
                      (err) =>
                        console.error("studio.boundary.upsert_failed", err),
                    );
                  }}
                  onClearBetween={() => {
                    if (!clipKey || selection.kind !== "between") return;
                    const outId = selection.outId;
                    const inId = selection.inId;
                    beginInteraction();
                    updateSpec((s) => {
                      s.boundary_transitions = (
                        s.boundary_transitions ?? []
                      ).filter(
                        (t) =>
                          t.boundary_id !== outId && t.boundary_id !== inId,
                      );
                    });
                    void deleteBoundaryTransition(clipKey, outId).catch(
                      (err) =>
                        console.error("studio.boundary.delete_failed", err),
                    );
                    void deleteBoundaryTransition(clipKey, inId).catch(
                      (err) =>
                        console.error("studio.boundary.delete_failed", err),
                    );
                  }}
                  onApplyToAll={async () => {
                    if (!clipKey) return;
                    // Snapshot for undo BEFORE the bulk write so the
                    // user can revert the whole "apply to all" in one
                    // Cmd+Z (the server response will rewrite many
                    // boundary entries at once).
                    beginInteraction();
                    setApplyAllStatus("saving");
                    try {
                      const session = await applyTransitionToAllBoundaries(
                        clipKey,
                      );
                      // Sync the local spec from the server's response so
                      // the new boundary_transitions list shows up in the
                      // panel / timeline markers immediately.
                      const nextList =
                        session?.spec?.boundary_transitions ?? null;
                      if (nextList) {
                        updateSpec((s) => {
                          s.boundary_transitions = nextList;
                        });
                      }
                      setApplyAllStatus("saved");
                      window.setTimeout(
                        () => setApplyAllStatus("idle"),
                        2000,
                      );
                    } catch (err) {
                      console.error("studio.boundary.apply_all_failed", err);
                      setApplyAllStatus("error");
                      window.setTimeout(
                        () => setApplyAllStatus("idle"),
                        2500,
                      );
                    }
                  }}
                  applyAllStatus={applyAllStatus}
                />
              )}
              {activeTool === "backgrounds" && (
                <BackgroundsPanel
                  backgroundLoop={spec.background_loop ?? null}
                  onPick={(bg) =>
                    updateSpec((s) => {
                      s.background_loop = bg;
                      // Smart-pair: in single layout the main video covers
                      // the entire canvas so the bg is invisible. Auto-
                      // promote to split_horizontal so the user actually
                      // SEES what they just picked. They can always switch
                      // back via the Layout tab.
                      if (!s.layout || s.layout.mode === "single") {
                        s.layout = {
                          ...(s.layout ?? {
                            pip_corner: "br",
                            pip_size: 0.3,
                            main_weight: 0.5,
                          }),
                          mode: "split_horizontal",
                        };
                      }
                    })
                  }
                  onClear={() =>
                    updateSpec((s) => {
                      s.background_loop = null;
                    })
                  }
                  layoutMode={spec.layout?.mode ?? "single"}
                  onPromoteLayout={() =>
                    updateSpec((s) => {
                      if (s.layout.mode === "single") {
                        s.layout.mode = "split_horizontal";
                      }
                    })
                  }
                />
              )}
              {activeTool === "layout" && (
                <LayoutPanel
                  layout={spec.layout ?? { mode: "single", pip_corner: "br", pip_size: 0.3, main_weight: 0.5 }}
                  onUpdate={(patch) =>
                    updateSpec((s) => {
                      Object.assign(s.layout, patch);
                    })
                  }
                  hasBackground={spec.background_loop != null}
                  onJumpToBackgrounds={() => setActiveTool("backgrounds")}
                />
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Center: preview — sized via measured pixels (NOT bare aspect-ratio
            CSS) because flex items with only maxWidth + aspectRatio collapse
            to 0×0 in some browsers, leaving the Player invisible. */}
        <PreviewStage aspectRatio={dims.width / dims.height}>
          {({ width, height }) =>
            needsLocalFile ? (
              <SourceUploadZone
                width={width}
                height={height}
                onBlobReady={(blobUrl) => setLocalBlobUrl(blobUrl)}
                onSourceReady={(serverUrl) => {
                  // Persist the server-side URL so render works.
                  updateSpec((s) => { s.clip.source_url = serverUrl; });
                }}
              />
            ) : (
              <Player
                ref={playerRef}
                component={StudioComposition}
                inputProps={playerInputProps}
                compositionWidth={dims.width}
                compositionHeight={dims.height}
                durationInFrames={durationFrames}
                fps={FPS}
                controls
                loop
                style={{ width, height, display: "block" }}
              />
            )
          }
        </PreviewStage>

        {/* Right: aspect + transcript */}
        <div className="w-80 border-l border-zinc-800 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="p-3 space-y-4">
              <AspectRatioPanel
                value={spec.aspect_ratio}
                onChange={(v) =>
                  updateSpec((s) => {
                    s.aspect_ratio = v;
                  })
                }
              />
              <TranscriptEditor
                words={spec.clip.transcript}
                beginInteraction={beginInteraction}
                onChange={(words) =>
                  updateSpec((s) => {
                    s.clip.transcript = words;
                  })
                }
              />
              {(renderError || renderUrl) && (
                <RenderStatusCard renderUrl={renderUrl} renderError={renderError} />
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Timeline — bottom strip; spans full width below the main row. */}
      <Timeline
        spec={spec}
        playerRef={playerRef}
        selection={selection}
        setSelection={setSelection}
        updateSpec={updateSpec}
        beginInteraction={beginInteraction}
        clipKey={clipKey}
        zoom={zoom}
        setZoom={setZoom}
        tracking={tracking.data}
        trackingStatus={tracking.status}
      />
    </div>
  );
}

/**
 * PreviewStage — measures its container with ResizeObserver and renders the
 * largest aspect-correct rectangle that fits inside it, in EXPLICIT pixels.
 *
 * Why not just `aspect-ratio` + `max-width` CSS? Because a flex child with
 * only `max-width` (and no `width`/`flex-basis`) collapses to 0×0 in Chrome
 * before browsers apply aspect-ratio to derive the other dimension — the
 * Remotion <Player> then mounts into a 0×0 box and renders an invisible
 * canvas. Measuring + setting explicit pixels avoids the entire edge case.
 */
function PreviewStage({
  aspectRatio,
  children,
}: {
  aspectRatio: number;
  children: (dims: { width: number; height: number }) => React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      // Subtract padding (p-4 = 16px each side) since we draw inside it.
      const availW = Math.max(0, rect.width - 32);
      const availH = Math.max(0, rect.height - 32);
      if (availW <= 0 || availH <= 0) {
        setBox(null);
        return;
      }
      // Largest aspect-correct rectangle that fits.
      const widthIfHeightLimited = availH * aspectRatio;
      const heightIfWidthLimited = availW / aspectRatio;
      let width: number;
      let height: number;
      if (widthIfHeightLimited <= availW) {
        width = widthIfHeightLimited;
        height = availH;
      } else {
        width = availW;
        height = heightIfWidthLimited;
      }
      setBox({ width: Math.floor(width), height: Math.floor(height) });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [aspectRatio]);

  return (
    <div
      ref={containerRef}
      className="flex min-w-0 flex-1 items-center justify-center overflow-hidden bg-zinc-900 p-4"
    >
      {box ? (
        <div
          className="relative overflow-hidden rounded-lg bg-black shadow-2xl"
          style={{ width: box.width, height: box.height }}
        >
          {children(box)}
        </div>
      ) : null}
    </div>
  );
}

function RenderProgressBar({ progress }: { progress: { percent: number | null; message: string | null; status: string } }) {
  const pct = Math.max(0, Math.min(100, progress.percent ?? 0));
  return (
    <div className="border-b border-zinc-800 bg-zinc-900/60 px-4 py-2">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin text-violet-400" />
          <span className="opacity-80">
            {progress.message ?? (progress.status === "queued" ? "Queued" : "Rendering…")}
          </span>
        </div>
        <span className="tabular-nums opacity-60">{pct}%</span>
      </div>
      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full bg-violet-500 transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

type ToolId =
  | "captions"
  | "broll"
  | "camera"
  | "branding"
  | "templates"
  | "effects"
  | "backgrounds"
  | "layout";

function LeftToolStrip({
  active,
  onChange,
}: {
  active: ToolId;
  onChange: (id: ToolId) => void;
}) {
  const tools: { id: ToolId; icon: React.ComponentType<{ className?: string }>; label: string; shortcut?: string }[] = [
    { id: "templates", icon: LayoutTemplate, label: "Templates", shortcut: "T" },
    { id: "captions", icon: Type, label: "Captions" },
    { id: "broll", icon: ImageIcon, label: "B-Roll" },
    { id: "camera", icon: Users, label: "Camera" },
    { id: "effects", icon: Wand2, label: "Effects", shortcut: "E" },
    { id: "backgrounds", icon: Film, label: "Backgrounds", shortcut: "B" },
    { id: "layout", icon: Layers, label: "Layout", shortcut: "L" },
    { id: "branding", icon: Palette, label: "Brand" },
  ];
  // Reviewer pushback: 8 tools × 64px tall = ~512px vertical, which
  // on a 14" laptop (≈760px viewport after chrome) crowds the bottom
  // tools off-screen. Under `xl` (1280px) we collapse to icon-only
  // (40px tall each, ~320px total) and rely on the native tooltip;
  // at >=xl we keep the label so the strip stays self-describing.
  return (
    <div className="w-12 flex-shrink-0 border-r border-zinc-800 bg-zinc-950 xl:w-16">
      <div className="flex flex-col items-stretch py-2">
        {tools.map((t) => {
          const Icon = t.icon;
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              title={t.shortcut ? `${t.label} (${t.shortcut})` : t.label}
              aria-label={t.label}
              aria-pressed={isActive}
              className={`flex flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition-colors xl:py-3 ${
                isActive
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-white"
              }`}
            >
              <Icon className="h-4 w-4" />
              {/* Label only above xl so 14" screens get all 8 tools
                  visible without scrolling. Tooltip still works below. */}
              <span className="hidden xl:inline">{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SaveBadge({ state }: { state: ReturnType<typeof useEditSession>["saveState"] }) {
  if (state === "idle") return null;
  const label = {
    saving: "Saving…",
    saved: "Saved",
    error: "Save failed",
  }[state];
  return (
    <Badge variant="outline" className="text-[10px]">
      {label}
    </Badge>
  );
}

/** "← Back to project" breadcrumb. Visible only when the URL carries
 *  a ``projectId`` query param (the Project page deep-links into the
 *  Studio with ``?projectId=...&projectClipId=...`` so the editor can
 *  cleanly bounce back). Renders nothing for standalone Studio
 *  sessions. Kept lightweight so it doesn't crowd the top bar. */
function ProjectBreadcrumb() {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get("projectId");
  if (!projectId) return null;
  return (
    <a
      href={`/dashboard/studio/project/${projectId}`}
      className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2 py-1 text-[10px] uppercase tracking-wider opacity-80 hover:opacity-100 hover:bg-zinc-800"
      title="Back to project"
    >
      ← Project
    </a>
  );
}

/** Short demo words paired with each caption preset. Picked so each
 *  word plays to the style's strength — MrBeast's tall caps, Hormozi's
 *  yellow-box rhythm, Neon's wide tracking, etc. Keep words ≤ 5 chars
 *  so they fit the picker tile at preview size without truncation. */
const CAPTION_PREVIEW_SAMPLES: Record<CaptionStyleName, string> = {
  capcut: "POP",
  mrbeast: "$10K",
  hormozi: "WIN",
  neon: "VIBE",
  minimal: "idea",
  bounce: "Yo!",
  karaoke: "Sing",
};

/** Renders the preset's font/stroke/box/glow combo at a small size so the
 *  picker shows a *real* preview of the caption instead of a static "Aa".
 *
 *  Mirrors the multi-shadow stroke trick + boxed branch from
 *  ``CaptionLayer.WordSpan`` so the picker tile is pixel-accurate to what
 *  will render in the preview canvas at full size. Stroke/shadow widths
 *  are scaled down proportional to ``fontSize`` so a 9px stroke (MrBeast)
 *  doesn't dominate a 28px sample word.
 *
 *  ``highlight``: when true, paints the sample in ``highlightColor`` to
 *  preview how the current "highlight active word" color will look against
 *  the style — this is what makes Karaoke/CapCut feel different from Neon.
 */
function CaptionPreviewTile({
  preset,
  sample,
  fontSize = 28,
  highlight = false,
  highlightColor = "#00FF00",
}: {
  preset: (typeof CAPTION_PRESETS)[CaptionStyleName];
  sample: string;
  fontSize?: number;
  highlight?: boolean;
  highlightColor?: string;
}) {
  // Stroke + shadow values in the preset are tuned for a ~64px 1080p
  // caption. Scaling them by sample/preset font ratio keeps the visual
  // weight balanced at the picker's smaller render size.
  const scale = fontSize / 64;
  const stroke = Math.max(1, Math.round(preset.strokeWidth * scale));
  const offsetY = Math.round(preset.shadowOffsetY * scale);
  const blur = Math.round(preset.shadowBlur * scale);

  const strokeShadows = stroke
    ? [
        `${stroke}px 0 0 ${preset.strokeColor}`,
        `-${stroke}px 0 0 ${preset.strokeColor}`,
        `0 ${stroke}px 0 ${preset.strokeColor}`,
        `0 -${stroke}px 0 ${preset.strokeColor}`,
        `${stroke}px ${stroke}px 0 ${preset.strokeColor}`,
        `-${stroke}px -${stroke}px 0 ${preset.strokeColor}`,
        `${stroke}px -${stroke}px 0 ${preset.strokeColor}`,
        `-${stroke}px ${stroke}px 0 ${preset.strokeColor}`,
      ]
    : [];
  const dropShadow =
    blur || offsetY
      ? `0 ${offsetY}px ${blur}px ${preset.shadowColor}`
      : null;
  const textShadow = [...strokeShadows, dropShadow].filter(Boolean).join(", ");

  // ``shadowColor: "currentColor"`` (Neon Glow uses this) lets us tint
  // the glow by changing the `color` property — when highlighted, the
  // glow also picks up the highlight tint, which feels right.
  const color = highlight ? highlightColor : "#FFFFFF";

  const baseStyle: React.CSSProperties = {
    color,
    fontFamily: preset.fontFamily,
    fontWeight: preset.fontWeight,
    fontSize: `${fontSize}px`,
    lineHeight: 1,
    textTransform: preset.textTransform,
    letterSpacing: preset.letterSpacing,
    textShadow,
    display: "inline-block",
    whiteSpace: "nowrap",
  };

  if (preset.boxed) {
    return (
      <span
        style={{
          ...baseStyle,
          backgroundColor: highlight ? highlightColor : preset.boxColor,
          color: highlight ? "#000" : color,
          padding: "4px 10px",
          borderRadius: 4,
        }}
      >
        {sample}
      </span>
    );
  }
  return <span style={baseStyle}>{sample}</span>;
}

function CaptionStylePanel(props: {
  selected: CaptionStyleName;
  uppercase: boolean;
  position: "top" | "middle" | "bottom";
  highlightMode: "word" | "group";
  fontSize: number;
  colorHighlight: string;
  emojiEnabled: boolean;
  hasAnyEmoji: boolean;
  hasTranscript: boolean;
  suggestingEmojis: boolean;
  onChangeStyle: (s: CaptionStyleName) => void;
  onChangeUpper: (v: boolean) => void;
  onChangePosition: (p: "top" | "middle" | "bottom") => void;
  onChangeHighlight: (m: "word" | "group") => void;
  onChangeSize: (n: number) => void;
  onChangeHighlightColor: (c: string) => void;
  onToggleEmoji: (v: boolean) => void;
  onSuggestEmojis: () => void;
  onClearEmojis: () => void;
}) {
  const { isFree } = usePlan();
  const { openUpgrade } = useUpgrade();
  const gateEmojis = () => {
    if (isFree) openUpgrade("emojis");
  };
  return (
    <div className="space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Caption Style
      </div>
      {/* Preset picker — each card renders a *real* sample of the style
          (font + stroke + glow + box) so the user sees what they'll get
          before clicking, instead of a generic "Aa" swatch. */}
      <div className="grid grid-cols-2 gap-2">
        {Object.values(CAPTION_PRESETS).map((preset) => {
          const isActive = preset.name === props.selected;
          // Short, recognizable demo words per preset — chosen so each
          // style shows off the trait it's best at (uppercase impact for
          // MrBeast, glow loop for Neon, springy descender for Bounce…).
          const sample = CAPTION_PREVIEW_SAMPLES[preset.name] ?? "POP";
          return (
            <button
              key={preset.name}
              onClick={() => props.onChangeStyle(preset.name)}
              title={preset.description}
              className={`group relative flex h-[78px] flex-col items-center justify-center overflow-hidden rounded-md border text-left transition-colors ${
                isActive
                  ? "border-violet-500 ring-1 ring-violet-500/40 bg-violet-500/5"
                  : "border-zinc-800 bg-black hover:border-zinc-600"
              }`}
            >
              {/* Sample word — rendered at the same stroke/shadow math
                  the preview canvas uses, so picking by eye is reliable. */}
              <div className="flex flex-1 items-center justify-center px-2">
                <CaptionPreviewTile
                  preset={preset}
                  sample={sample}
                  fontSize={preset.boxed ? 22 : 26}
                  highlight={preset.name === "karaoke"}
                  highlightColor={props.colorHighlight}
                />
              </div>
              {/* Label strip — small footer band so the tile stays mostly
                  preview, with just enough text to be identifiable. */}
              <div
                className={`w-full px-2 py-1 text-[10px] font-medium uppercase tracking-wider ${
                  isActive ? "bg-violet-500 text-white" : "bg-zinc-900/80 text-zinc-300"
                }`}
              >
                {preset.label}
              </div>
            </button>
          );
        })}
      </div>

      <div className="space-y-3 pt-1 border-t border-zinc-800">
        <div>
          <Label className="text-[11px] opacity-70">Position</Label>
          <Select value={props.position} onValueChange={(v) => props.onChangePosition(v as "top" | "middle" | "bottom")}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="top">Top</SelectItem>
              <SelectItem value="middle">Middle</SelectItem>
              <SelectItem value="bottom">Bottom</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="text-[11px] opacity-70">Highlight</Label>
          <Select value={props.highlightMode} onValueChange={(v) => props.onChangeHighlight(v as "word" | "group")}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="word">Word-by-word</SelectItem>
              <SelectItem value="group">Phrase group</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="text-[11px] opacity-70">Font size</Label>
          <Input
            type="number"
            min={24}
            max={160}
            value={props.fontSize}
            onChange={(e) => props.onChangeSize(Number(e.target.value) || 72)}
            className="h-8 text-xs"
          />
        </div>

        <div className="flex items-center justify-between">
          <Label className="text-[11px] opacity-70">UPPERCASE</Label>
          <Switch checked={props.uppercase} onCheckedChange={props.onChangeUpper} />
        </div>

        <div className="flex items-center gap-2">
          <Label className="text-[11px] opacity-70 flex-1">Highlight color</Label>
          <input
            type="color"
            value={props.colorHighlight}
            onChange={(e) => props.onChangeHighlightColor(e.target.value)}
            className="h-7 w-12 cursor-pointer rounded border-0 bg-transparent p-0"
          />
        </div>
      </div>

      {/* Auto-emojis (Week 6) — LLM picks one sentiment glyph per phrase
          and attaches it to spec.clip.transcript[i].emoji. The toggle is
          decoupled from the suggestion data so flipping off keeps the
          stored emojis ready to re-enable instantly. */}
      <div className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/50 p-3">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2 text-[11px] font-semibold">
            Auto-emojis
            <ProBadge />
          </Label>
          <Switch
            checked={props.emojiEnabled}
            onCheckedChange={(v) => {
              gateEmojis();
              props.onToggleEmoji(v);
            }}
          />
        </div>
        <div className="text-[10px] leading-snug opacity-60">
          One sentiment emoji per phrase, rendered both in preview and the
          final MP4. Toggle off any time without losing suggestions.
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="flex-1 gap-1.5 text-[11px]"
            disabled={props.suggestingEmojis || !props.hasTranscript}
            onClick={() => {
              gateEmojis();
              props.onSuggestEmojis();
            }}
          >
            {props.suggestingEmojis ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Wand2 className="h-3 w-3" />
            )}
            {props.suggestingEmojis
              ? "Suggesting…"
              : props.hasAnyEmoji
              ? "Re-suggest"
              : "Suggest emojis"}
          </Button>
          {props.hasAnyEmoji && (
            <Button
              size="sm"
              variant="outline"
              className="text-[11px] text-red-300 hover:text-red-200"
              onClick={props.onClearEmojis}
              title="Clear all suggested emojis"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function AspectRatioPanel({
  value,
  onChange,
}: {
  value: AspectRatio;
  onChange: (v: AspectRatio) => void;
}) {
  const ratios: AspectRatio[] = ["9:16", "1:1", "4:5", "16:9"];
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Aspect Ratio
      </div>
      <div className="grid grid-cols-2 gap-2">
        {ratios.map((r) => {
          const dims = ASPECT_DIMENSIONS[r];
          const isActive = r === value;
          return (
            <button
              key={r}
              onClick={() => onChange(r)}
              className={`flex flex-col items-center gap-1 rounded-md border p-2 text-xs transition-colors ${
                isActive
                  ? "border-violet-500 bg-violet-500/10"
                  : "border-zinc-800 bg-zinc-900 hover:border-zinc-700"
              }`}
            >
              <div
                className="rounded-sm border border-zinc-600"
                style={{
                  width: Math.min(40, dims.width / 36),
                  height: Math.min(40, dims.height / 36),
                }}
              />
              <span className="font-medium">{r}</span>
              <span className="text-[9px] opacity-60">{ASPECT_LABELS[r]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TranscriptEditor({
  words,
  onChange,
  beginInteraction,
}: {
  words: { text: string; start: number; end: number }[];
  onChange: (
    w: { text: string; start: number; end: number }[],
  ) => void;
  beginInteraction: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Transcript
      </div>
      <div className="rounded-md border border-zinc-800 bg-zinc-900 p-2 max-h-64 overflow-y-auto">
        {words.length === 0 ? (
          <div className="p-2 text-xs opacity-50">No transcript yet.</div>
        ) : (
          <div className="space-y-1">
            {words.map((w, i) => (
              <TranscriptWordRow
                key={`${w.start.toFixed(3)}-${i}`}
                index={i}
                word={w}
                words={words}
                onChange={onChange}
                beginInteraction={beginInteraction}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// One word per row. Edits live in local state; we only commit to the
// canonical spec on blur (or Enter), so a 20-character edit produces ONE
// undo entry — not 20. The snapshot is taken on the first keystroke via
// ``beginInteraction`` so undoing returns to the pre-edit text in one
// step. Matches the "transcript-word commit on blur" item in the Week 6
// undo/redo polish plan.
function TranscriptWordRow({
  index,
  word,
  words,
  onChange,
  beginInteraction,
}: {
  index: number;
  word: { text: string; start: number; end: number };
  words: { text: string; start: number; end: number }[];
  onChange: (w: { text: string; start: number; end: number }[]) => void;
  beginInteraction: () => void;
}) {
  const [draft, setDraft] = useState(word.text);
  const [dirty, setDirty] = useState(false);
  const interactionStarted = useRef(false);

  // External edits (template apply, demo migration, etc) should reset
  // any in-progress local edit so the panel doesn't show stale text.
  useEffect(() => {
    if (!dirty) setDraft(word.text);
  }, [word.text, dirty]);

  const commit = () => {
    if (!dirty) return;
    const trimmed = draft;
    if (trimmed === word.text) {
      setDirty(false);
      interactionStarted.current = false;
      return;
    }
    const next = words.slice();
    next[index] = { ...word, text: trimmed };
    onChange(next);
    setDirty(false);
    interactionStarted.current = false;
  };

  return (
    <div className="flex items-center gap-2">
      <span className="w-12 text-[10px] tabular-nums opacity-50">
        {word.start.toFixed(1)}s
      </span>
      <input
        value={draft}
        onChange={(e) => {
          if (!interactionStarted.current) {
            beginInteraction();
            interactionStarted.current = true;
          }
          setDraft(e.target.value);
          setDirty(true);
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
            (e.currentTarget as HTMLInputElement).blur();
          }
          if (e.key === "Escape") {
            setDraft(word.text);
            setDirty(false);
            interactionStarted.current = false;
            (e.currentTarget as HTMLInputElement).blur();
          }
        }}
        className="flex-1 rounded bg-zinc-950 px-2 py-1 text-xs text-white outline-none focus:ring-1 focus:ring-violet-500"
      />
    </div>
  );
}

/**
 * Renders a single search-result tile. Pexels returns ``preview_url`` /
 * ``thumbnail_url`` as JPG poster frames (NOT MP4s) — only ``download_url``
 * is the actual video. To keep the grid lightweight we show the static
 * thumbnail by default and only mount a ``<video>`` element while the user
 * hovers, so 12 HD MP4s don't all stream at once.
 */
function BRollSearchTile({
  clip,
  kind,
  pending = false,
  onAdd,
}: {
  clip: BRollSearchResult;
  kind: BRollMediaType;
  /** When true, the tile is mid-promote (image → MP4) and should show
   *  a spinner instead of accepting another click. */
  pending?: boolean;
  onAdd: () => void;
}) {
  const [hover, setHover] = useState(false);
  // Track whether the thumbnail actually loaded — used to swap in a
  // neutral fallback so the user never sees raw alt text bleeding through
  // the tile (which is what Safari does when an `<img>` is still loading
  // OR when the host blocks the request).
  const [imgFailed, setImgFailed] = useState(false);
  // GIFs from Tenor/Giphy return an MP4 ``download_url`` AND a smaller
  // GIF/JPG thumbnail. We render the still as a poster so the tile has
  // something to show before the MP4 element finishes buffering.
  const posterUrl = clip.thumbnail_url || clip.preview_url;
  // Images never need the hover-swap-to-video trick; they're already
  // static, and mounting a `<video>` for a .jpg silently fails (which
  // is what caused the original blank-tile bug).
  const showHoverVideo = kind === "video" && hover && !!clip.download_url;
  // GIFs autoplay even without hover — that's the whole point of a GIF.
  const showAutoVideo = kind === "gif" && !!clip.download_url;
  // Tile-corner pill content: media-type tag for images/gifs, duration
  // for videos (matches what video tiles showed before this rewrite).
  const tag = kind === "image"
    ? "IMG"
    : kind === "gif"
      ? "GIF"
      : clip.duration ? `${Math.round(clip.duration)}s` : "VID";
  const tagColor = kind === "image"
    ? "bg-emerald-500/80"
    : kind === "gif"
      ? "bg-pink-500/80"
      : "bg-black/70";
  return (
    <button
      type="button"
      onClick={() => {
        if (pending) return;
        onAdd();
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="group relative aspect-video overflow-hidden rounded border border-zinc-800 bg-zinc-900 hover:border-violet-500"
      title={clip.title}
    >
      {posterUrl && !imgFailed && (
        // alt="" is intentional: when an image is still loading (or fails
        // silently because of a referrer-block / ad-blocker), browsers
        // render the alt text inside the tile and it looks like the tile
        // is broken. Empty alt keeps the tile clean — the title is still
        // available via the button's `title` tooltip + the hover overlay.
        <img
          src={posterUrl}
          alt=""
          decoding="async"
          // Drop `loading="lazy"`: all search results are visible at once
          // in the panel, so deferring just delays the visual feedback.
          referrerPolicy="no-referrer"
          onError={() => setImgFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      {/* Neutral fallback when the image truly fails. Shows the provider
          + first letter of the title so the tile still feels intentional
          instead of just being a black rectangle. */}
      {(!posterUrl || imgFailed) && !showAutoVideo && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-zinc-800 to-zinc-900 text-center">
          <div className="text-lg font-bold opacity-70">
            {(clip.title || clip.source || "?").trim().charAt(0).toUpperCase()}
          </div>
          <div className="mt-0.5 text-[8px] uppercase tracking-wider opacity-50">
            {clip.source}
          </div>
        </div>
      )}
      {(showHoverVideo || showAutoVideo) && (
        <video
          src={clip.download_url}
          muted
          loop
          autoPlay
          playsInline
          preload="metadata"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      {/* Type tag — quick visual cue of what's behind the thumbnail. */}
      <span
        className={`absolute top-1 left-1 rounded px-1 text-[8px] font-bold uppercase tracking-wider text-white ${tagColor}`}
      >
        {tag}
      </span>
      {pending && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-[10px] text-white">
          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          Converting…
        </div>
      )}
      <div className="absolute inset-0 flex items-end bg-gradient-to-t from-black/80 via-transparent p-1.5 opacity-0 transition-opacity group-hover:opacity-100">
        <Plus className="h-3 w-3 text-white" />
        <span className="ml-1 text-[10px] text-white">Add</span>
      </div>
    </button>
  );
}

function BRollPanel({
  initialQuery,
  onAdd,
  onAddFeatured,
  selectedClips,
  onRemove,
}: {
  initialQuery: string;
  onAdd: (clip: BRollSearchResult) => void;
  onAddFeatured: (clip: FeaturedBRollItem) => void;
  selectedClips: { clip_url: string; label?: string | null; start: number; end: number }[];
  onRemove: (index: number) => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [mediaType, setMediaType] = useState<BRollMediaType>("video");
  const [results, setResults] = useState<BRollSearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  // Tracks which image (preview_url) is mid-promote so we can show
  // a spinner on that specific tile instead of blocking the whole panel.
  const [promotingImageId, setPromotingImageId] = useState<string | null>(null);
  const [featured, setFeatured] = useState<FeaturedBRollItem[]>([]);
  const [loadingFeatured, setLoadingFeatured] = useState(true);
  // Tracks whether the most recent search returned zero clips AND why
  // — distinguishes "no providers configured" from "the term truly
  // had no matches" so the empty state can be actionable.
  const [searchState, setSearchState] = useState<{
    ran: boolean;
    query: string;
    mediaType: BRollMediaType;
    availableSources: string[];
  }>({ ran: false, query: "", mediaType: "video", availableSources: [] });

  useEffect(() => {
    let alive = true;
    listFeaturedBRoll()
      .then((rows) => {
        if (alive) setFeatured(rows);
      })
      .catch(() => {
        // Backend unreachable — fall through to empty featured list so
        // the search-only path still works.
      })
      .finally(() => {
        if (alive) setLoadingFeatured(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const resp = await searchBRoll(trimmed, 12, mediaType);
      setResults(resp.clips);
      setSearchState({
        ran: true,
        query: trimmed,
        mediaType: resp.media_type,
        availableSources: resp.available_sources,
      });
      if (resp.clips.length === 0 && resp.available_sources.length === 0) {
        const envHint =
          resp.media_type === "gif"
            ? "GIPHY_API_KEY or TENOR_API_KEY"
            : "PEXELS_API_KEY";
        toast.error(
          `Stock search isn't configured — add ${envHint} to .env`,
          { duration: 6000 },
        );
      }
    } catch (err) {
      toast.error("B-roll search failed");
    } finally {
      setBusy(false);
    }
  }, [query, mediaType]);

  // Re-run the active search when the user flips the media-type toggle
  // so the grid updates without a second "Go" click.
  useEffect(() => {
    if (!searchState.ran || !query.trim()) return;
    if (mediaType === searchState.mediaType) return;
    handleSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaType]);

  /** Promote an image result into a short MP4 (server-cached), then add
   *  it to the timeline the same way a video clip would be added. */
  const handleAddImage = useCallback(
    async (clip: BRollSearchResult) => {
      setPromotingImageId(clip.id);
      try {
        const promoted = await promoteImageToVideo(clip.download_url, 4.0);
        // Synthesize a video-shaped clip whose download_url is the
        // freshly-encoded MP4. We keep the original ``title``/``preview_url``
        // so the timeline label + tooltip still match what the user picked.
        onAdd({
          ...clip,
          duration: promoted.duration_seconds,
          download_url: promoted.download_url,
          // Source becomes a synthetic "pexels-image" tag so a future
          // schema migration can tell promoted-image B-rolls apart from
          // native video clips if we ever need to.
          source: clip.source,
          media_type: "video",
        });
        toast.success(`Added "${clip.title.slice(0, 40)}"`);
      } catch (err) {
        toast.error("Couldn't convert image to clip");
      } finally {
        setPromotingImageId(null);
      }
    },
    [onAdd],
  );

  return (
    <div className="space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        B-Roll
      </div>

      {/* ------- Stock search: videos | images | gifs -------
          Search comes first — it's the primary action (the user usually
          has something specific in mind like "minecraft" or "city").
          Quick picks live below as a fallback when no good search hit.
          One search box drives three providers; the toggle picks which
          one we hit. Images are promoted to short MP4s on add so the
          timeline only ever holds video clips. */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-[11px] opacity-70">Search</Label>
          <span className="text-[9px] opacity-50">
            {mediaType === "video"
              ? "Pexels + Pixabay"
              : mediaType === "image"
              ? "Pexels photos"
              : "Giphy + Tenor"}
          </span>
        </div>

        {/* Segmented control — Videos / Images / GIFs */}
        <div className="grid grid-cols-3 gap-1 rounded-md bg-zinc-900 p-0.5">
          {(["video", "image", "gif"] as const).map((t) => {
            const active = mediaType === t;
            const label =
              t === "video" ? "Videos" : t === "image" ? "Images" : "GIFs";
            return (
              <button
                key={t}
                type="button"
                onClick={() => setMediaType(t)}
                className={`h-6 rounded text-[10px] font-medium uppercase tracking-wide transition-colors ${
                  active
                    ? "bg-violet-500 text-white"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
                title={`Search ${label.toLowerCase()}`}
              >
                {label}
              </button>
            );
          })}
        </div>

        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              mediaType === "gif"
                ? "Search GIFs (minecraft, parkour, dance…)"
                : mediaType === "image"
                ? "Search photos (forest, neon, food…)"
                : "Search stock footage…"
            }
            className="h-8 text-xs"
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <Button onClick={handleSearch} size="sm" disabled={busy}>
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Go"}
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {results.map((clip) => {
            const kind = clip.media_type ?? mediaType;
            const isImage = kind === "image";
            return (
              <BRollSearchTile
                key={clip.id}
                clip={clip}
                kind={kind}
                pending={isImage && promotingImageId === clip.id}
                onAdd={() => {
                  if (isImage) {
                    handleAddImage(clip);
                  } else {
                    onAdd(clip);
                    toast.success(`Added "${clip.title.slice(0, 40)}"`);
                  }
                }}
              />
            );
          })}
        </div>

        {/* Empty-state diagnostics for the search: tells the user WHY the
            grid is empty so they don't think the search button is broken. */}
        {searchState.ran && results.length === 0 && !busy && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2.5 text-[11px] leading-snug text-amber-200">
            {searchState.availableSources.length === 0 ? (
              <>
                <div className="font-semibold mb-1">
                  {searchState.mediaType === "gif"
                    ? "GIF search isn't configured"
                    : "Stock search isn't configured"}
                </div>
                <div className="opacity-80">
                  {searchState.mediaType === "gif" ? (
                    <>
                      Add a free{" "}
                      <a
                        href="https://developers.giphy.com/dashboard/"
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-amber-100"
                      >
                        GIPHY_API_KEY
                      </a>{" "}
                      (or{" "}
                      <a
                        href="https://developers.google.com/tenor/guides/quickstart"
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-amber-100"
                      >
                        TENOR_API_KEY
                      </a>
                      ) to your <code>.env</code> and restart the server.
                      Videos and Quick picks always work.
                    </>
                  ) : (
                    <>
                      Add a free{" "}
                      <a
                        href="https://www.pexels.com/api/"
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-amber-100"
                      >
                        PEXELS_API_KEY
                      </a>{" "}
                      to your <code>.env</code> and restart the server.
                      Quick picks below always work.
                    </>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="font-semibold mb-1">
                  No {searchState.mediaType === "gif" ? "GIFs" : searchState.mediaType === "image" ? "photos" : "clips"} for "{searchState.query}"
                </div>
                <div className="opacity-80">
                  Tried: {searchState.availableSources.join(", ")}. Try a
                  broader term like "city", "ocean", or "people".
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ------- Featured (bundled quick-picks) -------
          Moved below search: these are the always-available fallback
          tiles (procedural MP4s bundled with the app). The user usually
          knows what they want and types it; quick picks fill the gap
          when search returns nothing or no API keys are wired. */}
      <div className="space-y-1.5 pt-2 border-t border-zinc-800">
        <div className="flex items-center justify-between">
          <Label className="text-[11px] opacity-70">Quick picks</Label>
          <span className="text-[9px] opacity-50">
            Click to add a 4s clip at the playhead
          </span>
        </div>
        {loadingFeatured ? (
          <div className="flex items-center gap-2 text-[11px] opacity-60">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading…
          </div>
        ) : featured.length === 0 ? (
          <div className="text-[11px] opacity-60">
            Bundled library not available.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-1.5">
            {featured.map((b) => (
              <button
                key={b.id}
                onClick={() => {
                  onAddFeatured(b);
                  toast.success(`Added "${b.label}"`);
                }}
                title={b.description}
                className="group relative aspect-video overflow-hidden rounded border border-zinc-800 transition-colors hover:border-violet-500"
              >
                <video
                  src={b.download_url}
                  poster={b.preview_thumbnail}
                  muted
                  loop
                  autoPlay
                  playsInline
                  preload="metadata"
                  className="h-full w-full object-cover"
                />
                <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1 text-[9px] font-medium uppercase">
                  {b.category}
                </span>
                <div className="absolute inset-0 flex items-end bg-gradient-to-t from-black/80 via-transparent p-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <Plus className="h-3 w-3 text-white" />
                  <span className="ml-1 text-[10px] text-white">{b.label}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedClips.length > 0 && (
        <div className="pt-2 border-t border-zinc-800">
          <div className="text-[10px] uppercase opacity-60 mb-1">In timeline</div>
          {selectedClips.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-xs py-1">
              <span className="truncate flex-1">{c.label ?? c.clip_url.split("/").pop()}</span>
              <span className="opacity-50 text-[10px]">
                {c.start.toFixed(1)}–{c.end.toFixed(1)}s
              </span>
              <button onClick={() => onRemove(i)} className="opacity-50 hover:opacity-100">
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CameraPanel(props: {
  spec: EditSpec;
  tracking: TrackingData | null;
  trackingStatus: TrackingHookStatus;
  trackingProgress: number | null;
  trackingProgressMessage: string | null;
  trackingError: string | null;
  onAutoSwitch: () => void;
  onRefreshTracking: () => void;
  onToggleBbox: (v: boolean) => void;
  onToggleEasePan: (v: boolean) => void;
  onChangeNSubjects: (n: number) => void;
  onClearTracks: () => void;
  onInsertCutForSubject: (subjectId: number) => void;
}) {
  const subjects = props.tracking?.subjects ?? [];
  // Defensive default so a session loaded under the old schema (pre-Week-4)
  // doesn't crash the panel before the server normalizes the row on save.
  const camera = props.spec.camera ?? {
    tracks: [],
    bbox_overlay_enabled: false,
    ease_pan: false,
    n_subjects_requested: 4,
  };
  const statusBadge = useMemo(() => {
    if (props.trackingStatus === "computing") {
      const pct = props.trackingProgress ?? 0;
      const msg = props.trackingProgressMessage ?? "Detecting subjects…";
      return (
        <Badge variant="outline" className="gap-1 text-[10px]">
          <Loader2 className="h-3 w-3 animate-spin" />
          {msg} {pct ? `(${pct}%)` : ""}
        </Badge>
      );
    }
    if (props.trackingStatus === "done") {
      return (
        <Badge variant="outline" className="text-[10px]">
          {subjects.length} subject{subjects.length === 1 ? "" : "s"} detected
        </Badge>
      );
    }
    if (props.trackingStatus === "failed") {
      return (
        <Badge variant="destructive" className="text-[10px]">
          Detection failed
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="text-[10px]">
        Idle
      </Badge>
    );
  }, [
    props.trackingStatus,
    props.trackingProgress,
    props.trackingProgressMessage,
    subjects.length,
  ]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
          Camera
        </div>
        {statusBadge}
      </div>

      {props.trackingError && (
        <div className="rounded border border-red-900/60 bg-red-950/40 p-2 text-[11px] text-red-300">
          {props.trackingError}{" "}
          <button
            className="underline hover:no-underline"
            onClick={props.onRefreshTracking}
          >
            Retry
          </button>
        </div>
      )}

      {/* Subject legend — colored swatch + label. Clicking inserts a cut
          for that subject at the current playhead. */}
      <div className="space-y-1">
        <div className="text-[10px] uppercase opacity-60">Subjects</div>
        {subjects.length === 0 ? (
          <div className="rounded border border-dashed border-zinc-800 p-2 text-[11px] opacity-50">
            {props.trackingStatus === "computing"
              ? "Waiting for the first detection…"
              : "No subjects detected yet."}
          </div>
        ) : (
          subjects.map((s, i) => (
            <button
              key={s.id}
              onClick={() => props.onInsertCutForSubject(s.id)}
              className="flex w-full items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-left hover:border-zinc-700"
              title={`Insert cut for ${s.label} at playhead (key ${i + 1})`}
            >
              <span
                className="inline-block h-3 w-3 rounded"
                style={{ background: s.color_hex }}
              />
              <span className="flex-1 text-xs font-medium">{s.label}</span>
              <span className="text-[10px] tabular-nums opacity-50">
                {i + 1}
              </span>
            </button>
          ))
        )}
      </div>

      {/* Big "Auto-switch" button — the marquee feature of the Camera panel. */}
      <Button
        onClick={props.onAutoSwitch}
        disabled={props.trackingStatus !== "done" || subjects.length === 0}
        className="w-full gap-1.5"
        size="sm"
      >
        <Wand2 className="h-3.5 w-3.5" />
        Auto-switch cameras
      </Button>

      {/* Toggles */}
      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2 text-[11px] opacity-80">
            {camera.bbox_overlay_enabled ? (
              <Eye className="h-3 w-3" />
            ) : (
              <EyeOff className="h-3 w-3" />
            )}
            Subject overlay
          </Label>
          <Switch
            checked={camera.bbox_overlay_enabled}
            onCheckedChange={props.onToggleBbox}
          />
        </div>
        <div className="flex items-center justify-between">
          <Label className="text-[11px] opacity-80">Ease-pan (smooth cuts)</Label>
          <Switch
            checked={camera.ease_pan}
            onCheckedChange={props.onToggleEasePan}
          />
        </div>
        <div>
          <Label className="text-[11px] opacity-70">Subjects to detect</Label>
          <Select
            value={String(camera.n_subjects_requested)}
            onValueChange={(v) => props.onChangeNSubjects(parseInt(v, 10))}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[1, 2, 3, 4].map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Cuts summary */}
      {camera.tracks.length > 0 && (
        <div className="border-t border-zinc-800 pt-3">
          <div className="mb-1 flex items-center justify-between">
            <div className="text-[10px] uppercase opacity-60">
              Cuts ({camera.tracks.length})
            </div>
            <button
              onClick={props.onClearTracks}
              className="text-[10px] text-zinc-500 hover:text-red-400"
            >
              Clear all
            </button>
          </div>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {camera.tracks.map((c, i) => {
              const subject = subjects.find((s) => s.id === c.subject_id);
              const color = subject?.color_hex ?? "#7c3aed";
              return (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded bg-zinc-900 px-2 py-1 text-[11px]"
                >
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: color }}
                  />
                  <span className="flex-1 truncate">
                    {subject?.label ?? `Cam ${c.subject_id + 1}`}
                  </span>
                  <span className="tabular-nums opacity-60">
                    {c.start.toFixed(1)}–{c.end.toFixed(1)}s
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2 text-[10px] leading-snug opacity-70">
        Tip: press <kbd className="rounded bg-zinc-800 px-1">1</kbd>–
        <kbd className="rounded bg-zinc-800 px-1">4</kbd> to switch to subject
        N at the playhead. Toggle "Subject overlay" to click faces directly in
        the preview.
      </div>
    </div>
  );
}

type BrandKitState = {
  logo_url?: string | null;
  logo_position?: "tl" | "tr" | "bl" | "br" | null;
  logo_opacity?: number | null;
  primary_color?: string | null;
  accent_color?: string | null;
  font_family?: string | null;
};

type BrandKitPatch = Partial<{
  logo_url: string | null;
  logo_position: "tl" | "tr" | "bl" | "br";
  logo_opacity: number;
  primary_color: string | null;
  accent_color: string | null;
  font_family: string | null;
}>;

// Hand-curated font picker — every entry is either a web-safe system font
// or one of the @fontsource/* packages already bundled by the app. We
// keep the list short so users aren't paralyzed by choice.
const BRAND_FONT_OPTIONS: { value: string; label: string; preview: string }[] = [
  { value: "Inter", label: "Inter (default)", preview: "Inter, system-ui, sans-serif" },
  { value: "Montserrat", label: "Montserrat", preview: "Montserrat, sans-serif" },
  { value: "Poppins", label: "Poppins", preview: "Poppins, sans-serif" },
  { value: "Bebas Neue", label: "Bebas Neue", preview: "'Bebas Neue', sans-serif" },
  { value: "Roboto", label: "Roboto", preview: "Roboto, sans-serif" },
  { value: "Impact", label: "Impact", preview: "Impact, sans-serif" },
  { value: "Arial Black", label: "Arial Black", preview: "'Arial Black', sans-serif" },
  { value: "system-ui", label: "System UI", preview: "system-ui, sans-serif" },
];

// Default shape we initialize the panel's local ``userKit`` state with
// when the brand-voice fields are edited before the GET resolves.
// Kept here (not in api.ts) because it's only used by this panel.
const EMPTY_BRAND_KIT_DEFAULTS: UserBrandKit = {
  logo_url: null,
  logo_position: "br",
  logo_opacity: 0.85,
  primary_color: null,
  accent_color: null,
  font_family: null,
  caption_signature: null,
  default_hashtags: null,
  exists: false,
};

function BrandKitPanel({
  brandKit,
  onUpdate,
  beginInteraction,
}: {
  brandKit: BrandKitState;
  onUpdate: (patch: BrandKitPatch) => void;
  beginInteraction: () => void;
}) {
  const [userKit, setUserKit] = useState<UserBrandKit | null>(null);
  const [uploading, setUploading] = useState(false);
  const [savingDefault, setSavingDefault] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const { isFree } = usePlan();
  const { openUpgrade } = useUpgrade();
  const gateBranding = () => {
    if (isFree) openUpgrade("branding");
  };

  // Load saved per-user brand kit so we can show the "Save as default" and
  // "Reset to my brand" affordances accurately. Failure here is non-fatal
  // — the panel still works against the session-level spec.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getUserBrandKit();
        if (!cancelled) setUserKit(data);
      } catch (err) {
        if (!cancelled) console.warn("[studio] brand-kit GET failed", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounced auto-sync to the user-level brand kit. Whenever the
  // SESSION-level brand kit changes (color/font/position/opacity, NOT
  // logo — logos go through the explicit upload endpoint), push the
  // change to the user record so it follows them across new clips.
  const lastSyncedRef = useRef<string>("");
  useEffect(() => {
    if (!userKit) return; // wait until we've loaded the user row
    const patch: BrandKitPatch = {
      primary_color: brandKit.primary_color ?? null,
      accent_color: brandKit.accent_color ?? null,
      font_family: brandKit.font_family ?? null,
      logo_position: (brandKit.logo_position as "tl" | "tr" | "bl" | "br") ?? "br",
      logo_opacity: brandKit.logo_opacity ?? 0.85,
    };
    const json = JSON.stringify(patch);
    if (json === lastSyncedRef.current) return;
    const t = setTimeout(async () => {
      try {
        await saveUserBrandKit(patch);
        lastSyncedRef.current = json;
      } catch (err) {
        console.warn("[studio] brand-kit auto-save failed", err);
      }
    }, 600);
    return () => clearTimeout(t);
  }, [
    userKit,
    brandKit.primary_color,
    brandKit.accent_color,
    brandKit.font_family,
    brandKit.logo_position,
    brandKit.logo_opacity,
  ]);

  const handleLogoFile = async (file: File | null) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast.error("Logo too large (limit 2 MB)");
      return;
    }
    // Soft-gate: surface the upgrade modal but still run the upload so
    // the user sees their logo actually applied (mock soft-gating policy).
    gateBranding();
    setUploading(true);
    try {
      const updated = await uploadUserBrandLogo(file);
      setUserKit(updated);
      // Snapshot for undo: the upload swaps a URL in one user-visible step.
      beginInteraction();
      onUpdate({ logo_url: updated.logo_url });
      toast.success("Logo uploaded");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Logo upload failed",
      );
    } finally {
      setUploading(false);
    }
  };

  const handleRemoveLogo = async () => {
    try {
      const updated = await deleteUserBrandLogo();
      setUserKit(updated);
      beginInteraction();
      onUpdate({ logo_url: null });
      toast.success("Logo removed");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to remove logo",
      );
    }
  };

  const handleSaveAsDefault = async () => {
    gateBranding();
    setSavingDefault(true);
    try {
      const updated = await saveUserBrandKit({
        primary_color: brandKit.primary_color ?? null,
        accent_color: brandKit.accent_color ?? null,
        font_family: brandKit.font_family ?? null,
        logo_position: (brandKit.logo_position as "tl" | "tr" | "bl" | "br") ?? "br",
        logo_opacity: brandKit.logo_opacity ?? 0.85,
      });
      setUserKit(updated);
      toast.success("Saved as your default brand kit");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to save brand kit",
      );
    } finally {
      setSavingDefault(false);
    }
  };

  const handleResetToUserDefault = () => {
    if (!userKit) return;
    beginInteraction();
    onUpdate({
      logo_url: userKit.logo_url,
      logo_position: userKit.logo_position,
      logo_opacity: userKit.logo_opacity,
      primary_color: userKit.primary_color,
      accent_color: userKit.accent_color,
      font_family: userKit.font_family,
    });
    toast.success("Reset to your saved brand kit");
  };

  const position = (brandKit.logo_position as "tl" | "tr" | "bl" | "br") ?? "br";
  const opacity = brandKit.logo_opacity ?? 0.85;

  const sessionDiffersFromUser = userKit?.exists
    ? userKit.logo_url !== (brandKit.logo_url ?? null) ||
      userKit.logo_position !== position ||
      Math.abs((userKit.logo_opacity ?? 0.85) - opacity) > 1e-3 ||
      (userKit.primary_color ?? null) !== (brandKit.primary_color ?? null) ||
      (userKit.accent_color ?? null) !== (brandKit.accent_color ?? null) ||
      (userKit.font_family ?? null) !== (brandKit.font_family ?? null)
    : false;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
            Brand Kit
          </div>
          <ProBadge />
        </div>
        <Badge variant="outline" className="text-[9px] uppercase opacity-70">
          Auto-applied
        </Badge>
      </div>

      {/* Logo — drag-and-drop / click upload zone with preview */}
      <div className="space-y-2">
        <Label className="text-[11px] opacity-70">Logo</Label>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
          }}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files?.[0];
            if (file) void handleLogoFile(file);
          }}
          onClick={() => fileInputRef.current?.click()}
          className="relative flex h-32 w-full cursor-pointer items-center justify-center overflow-hidden rounded-md border border-dashed border-zinc-700 bg-zinc-950 hover:border-violet-500 hover:bg-zinc-900"
        >
          {brandKit.logo_url ? (
            <>
              <img
                src={brandKit.logo_url}
                alt="Brand logo"
                className="max-h-24 max-w-[80%] object-contain"
              />
              {uploading && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              )}
            </>
          ) : uploading ? (
            <Loader2 className="h-5 w-5 animate-spin opacity-60" />
          ) : (
            <div className="text-center text-[11px] opacity-60">
              <div className="mb-1 font-medium">Drop logo here</div>
              <div className="text-[10px] opacity-80">
                PNG, JPEG, WebP, SVG · max 2 MB
              </div>
            </div>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/webp,image/svg+xml"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            void handleLogoFile(file ?? null);
            // Reset so the same file can be re-selected.
            e.target.value = "";
          }}
        />
        {brandKit.logo_url && (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1 text-[11px]"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              Replace
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-[11px] text-red-400 hover:text-red-300"
              onClick={handleRemoveLogo}
              disabled={uploading}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>

      {/* Position picker (4 corners) */}
      <div className="space-y-2">
        <Label className="text-[11px] opacity-70">Logo position</Label>
        <div className="grid grid-cols-2 gap-1 rounded-md border border-zinc-800 bg-zinc-950 p-1">
          {(["tl", "tr", "bl", "br"] as const).map((corner) => {
            const isActive = position === corner;
            const cornerLabel = {
              tl: "Top left",
              tr: "Top right",
              bl: "Bottom left",
              br: "Bottom right",
            }[corner];
            return (
              <button
                key={corner}
                onClick={() => {
                  beginInteraction();
                  onUpdate({ logo_position: corner });
                }}
                className={`relative h-10 rounded text-[10px] transition-colors ${
                  isActive
                    ? "bg-violet-500/20 ring-1 ring-violet-500"
                    : "hover:bg-zinc-900"
                }`}
              >
                <span
                  className={`absolute h-2 w-2 rounded-sm bg-violet-400 ${
                    corner === "tl"
                      ? "left-2 top-2"
                      : corner === "tr"
                      ? "right-2 top-2"
                      : corner === "bl"
                      ? "bottom-2 left-2"
                      : "bottom-2 right-2"
                  }`}
                />
                <span className="absolute inset-0 flex items-center justify-center opacity-70">
                  {cornerLabel}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Opacity slider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label className="text-[11px] opacity-70">Logo opacity</Label>
          <span className="text-[10px] tabular-nums opacity-60">
            {Math.round(opacity * 100)}%
          </span>
        </div>
        <input
          type="range"
          min={5}
          max={100}
          step={1}
          value={Math.round(opacity * 100)}
          onPointerDown={() => beginInteraction()}
          onChange={(e) =>
            onUpdate({ logo_opacity: Number(e.target.value) / 100 })
          }
          className="h-2 w-full cursor-pointer appearance-none rounded bg-zinc-800 accent-violet-500"
        />
      </div>

      {/* Brand colors */}
      <div>
        <Label className="text-[11px] opacity-70">Brand colors</Label>
        <div className="mt-1 flex gap-2">
          <div className="flex-1">
            <div className="mb-1 text-[10px] opacity-60">Primary</div>
            <div className="flex items-center gap-1">
              <input
                type="color"
                value={brandKit.primary_color ?? "#7c3aed"}
                onPointerDown={() => beginInteraction()}
                onChange={(e) => onUpdate({ primary_color: e.target.value })}
                className="h-8 w-12 cursor-pointer rounded border-0 bg-transparent p-0"
              />
              {brandKit.primary_color && (
                <button
                  onClick={() => {
                    beginInteraction();
                    onUpdate({ primary_color: null });
                  }}
                  className="text-[10px] opacity-50 hover:opacity-100"
                  title="Clear primary color"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
          <div className="flex-1">
            <div className="mb-1 text-[10px] opacity-60">Accent</div>
            <div className="flex items-center gap-1">
              <input
                type="color"
                value={brandKit.accent_color ?? "#fbbf24"}
                onPointerDown={() => beginInteraction()}
                onChange={(e) => onUpdate({ accent_color: e.target.value })}
                className="h-8 w-12 cursor-pointer rounded border-0 bg-transparent p-0"
              />
              {brandKit.accent_color && (
                <button
                  onClick={() => {
                    beginInteraction();
                    onUpdate({ accent_color: null });
                  }}
                  className="text-[10px] opacity-50 hover:opacity-100"
                  title="Clear accent color"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
        </div>
        <div className="mt-1 text-[10px] opacity-50">
          Apply to captions when they're at the default white / green.
        </div>
      </div>

      {/* Font picker */}
      <div className="space-y-1">
        <Label className="text-[11px] opacity-70">Brand font</Label>
        <Select
          value={brandKit.font_family ?? ""}
          onValueChange={(v) => {
            beginInteraction();
            onUpdate({ font_family: v || null });
          }}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Use caption preset default" />
          </SelectTrigger>
          <SelectContent>
            {BRAND_FONT_OPTIONS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                <span style={{ fontFamily: f.preview }}>{f.label}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* ---------------------------------------------------------------
          Brand voice — auto-applied to Distribution publishes (NOT to
          Studio renders). Lets a creator set their stock sign-off + a
          permanent hashtag set once and have it follow every cross-post.
          Completes the third leg of the brand-kit auto-apply story:
          visual on render, voice on publish.
          --------------------------------------------------------------- */}
      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <div className="flex items-center gap-2">
          <Label className="text-[11px] opacity-70">
            Caption sign-off
          </Label>
          <Badge variant="outline" className="text-[9px] uppercase opacity-70">
            Auto-applied · Distribution
          </Badge>
        </div>
        <Textarea
          value={userKit?.caption_signature ?? ""}
          onChange={(e) => {
            const value = e.target.value;
            setUserKit((prev) =>
              prev
                ? { ...prev, caption_signature: value }
                : { ...EMPTY_BRAND_KIT_DEFAULTS, caption_signature: value },
            );
            // Debounced PUT happens via auto-save effect; this only
            // updates local UI state immediately so the textarea is
            // responsive.
          }}
          onBlur={async () => {
            if (!userKit) return;
            try {
              await saveUserBrandKit({
                caption_signature: userKit.caption_signature,
              });
            } catch (err) {
              console.warn("[studio] brand-voice signature save failed", err);
            }
          }}
          placeholder={"Appended to every published caption.\nExample:\n— Reps Daily · subscribe for more 💪"}
          className="min-h-[72px] resize-y bg-zinc-950 text-xs"
          maxLength={2000}
        />
        <div className="text-[10px] opacity-50">
          Appended to the base caption on every Distribution publish — line
          breaks, emoji, and links all work.
        </div>
      </div>

      <div className="space-y-2">
        <Label className="text-[11px] opacity-70">
          Default hashtags
        </Label>
        <input
          type="text"
          value={userKit?.default_hashtags ?? ""}
          onChange={(e) => {
            const value = e.target.value;
            setUserKit((prev) =>
              prev
                ? { ...prev, default_hashtags: value }
                : { ...EMPTY_BRAND_KIT_DEFAULTS, default_hashtags: value },
            );
          }}
          onBlur={async () => {
            if (!userKit) return;
            try {
              await saveUserBrandKit({
                default_hashtags: userKit.default_hashtags,
              });
            } catch (err) {
              console.warn("[studio] brand-voice hashtags save failed", err);
            }
          }}
          placeholder="#fitness, #workout, #protein"
          className="h-8 w-full rounded border border-zinc-800 bg-zinc-950 px-2 text-xs placeholder:opacity-40 focus:border-violet-500 focus:outline-none"
          maxLength={1000}
        />
        <div className="text-[10px] opacity-50">
          Comma-separated. Merged into every Distribution publish (deduped
          against whatever you've typed in the caption box).
        </div>
      </div>

      {/* Save / reset to default actions */}
      <div className="space-y-2 border-t border-zinc-800 pt-3">
        <Button
          variant="default"
          size="sm"
          className="w-full text-[11px]"
          onClick={handleSaveAsDefault}
          disabled={savingDefault}
        >
          {savingDefault ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : null}
          Save as my brand kit
        </Button>
        {sessionDiffersFromUser && (
          <Button
            variant="outline"
            size="sm"
            className="w-full text-[11px] opacity-80"
            onClick={handleResetToUserDefault}
          >
            Reset to saved brand kit
          </Button>
        )}
        <div className="text-[10px] opacity-50">
          Auto-applied to new clips. Changes here also sync to your saved
          brand kit so every future session starts branded.
        </div>
      </div>
    </div>
  );
}

function TemplatesPanel({
  templates,
  activeTemplate,
  applyingName,
  onApply,
}: {
  templates: TemplateInfo[] | null;
  activeTemplate: string | null;
  applyingName: string | null;
  onApply: (name: string) => void;
}) {
  if (templates === null) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin opacity-50" />
      </div>
    );
  }
  if (templates.length === 0) {
    return (
      <div className="rounded border border-zinc-800 p-3 text-xs opacity-60">
        No templates configured.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Templates
      </div>
      <div className="text-[10px] opacity-60">
        One-click presets for caption style, transitions, and zoom behavior.
        Press <kbd className="rounded bg-zinc-800 px-1">T</kbd> to jump here.
      </div>
      <div className="space-y-2">
        {templates.map((t) => {
          const isActive = activeTemplate === t.name;
          const isApplying = applyingName === t.name;
          return (
            <button
              key={t.name}
              disabled={applyingName != null}
              onClick={() => onApply(t.name)}
              className={`group w-full rounded-md border p-3 text-left transition-colors ${
                isActive
                  ? "border-violet-500 bg-violet-500/10"
                  : "border-zinc-800 bg-zinc-900 hover:border-zinc-700"
              } disabled:opacity-50`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold capitalize">
                  {t.name.replace("-", " ")}
                </span>
                {isApplying ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : isActive ? (
                  <Badge variant="outline" className="text-[9px]">
                    Active
                  </Badge>
                ) : null}
              </div>
              <div className="mt-1 text-[11px] leading-snug opacity-70">
                {t.description}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge variant="outline" className="text-[9px]">
                  {t.caption_style}
                </Badge>
                <Badge variant="outline" className="text-[9px]">
                  {t.transition_type}
                </Badge>
                {t.auto_zoom_enabled && (
                  <Badge variant="outline" className="text-[9px]">
                    zoom
                  </Badge>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function EffectsPanel({
  autoZoom,
  transitions,
  detecting,
  hasTranscript,
  onDetectZooms,
  onToggleAutoZoom,
  onChangeMaxScale,
  onClearZooms,
  onChangeTxEnabled,
  onChangeTxType,
  onChangeTxDuration,
  onChangeTxSfx,
  selectedBoundaryId,
  boundaryInstance,
  onUpsertBoundary,
  onClearBoundary,
  selectedBetween,
  betweenInstance,
  onUpsertBetween,
  onClearBetween,
  onApplyToAll,
  applyAllStatus,
}: {
  autoZoom: AutoZoom | undefined;
  transitions: Transitions;
  detecting: boolean;
  hasTranscript: boolean;
  onDetectZooms: () => void;
  onToggleAutoZoom: (v: boolean) => void;
  onChangeMaxScale: (n: number) => void;
  onClearZooms: () => void;
  onChangeTxEnabled: (v: boolean) => void;
  onChangeTxType: (t: TransitionType) => void;
  onChangeTxDuration: (ms: number) => void;
  onChangeTxSfx: (v: boolean) => void;
  /** Currently selected boundary id (from timeline marker) or null. */
  selectedBoundaryId: string | null;
  /** Existing TransitionInstance for the selected boundary, or null when
   *  no override is saved (boundary uses the global default). */
  boundaryInstance: TransitionInstance | null;
  /** Persist a per-boundary override. */
  onUpsertBoundary: (instance: TransitionInstance) => void;
  /** Remove the per-boundary override so it falls back to global. */
  onClearBoundary: () => void;
  /** Currently selected "between two clips" pair (from a timeline pill)
   *  or null. Mutually exclusive with selectedBoundaryId. */
  selectedBetween: {
    outId: string;
    inId: string;
    clipAIdx: number;
    clipBIdx: number;
  } | null;
  /** Existing override for the between-pair (we prefer the OUT side's
   *  instance, falling back to IN's). null when neither side has an
   *  override — the pair will then render as a plain cut. */
  betweenInstance: TransitionInstance | null;
  /** Persist the transition on BOTH boundaries of the pair AND shift
   *  clip B leftward so they overlap by duration_ms. */
  onUpsertBetween: (template: TransitionInstance) => void;
  /** Remove the override on BOTH boundaries of the pair. */
  onClearBetween: () => void;
  /** "Apply to all" — bulk-expand the global default to every boundary. */
  onApplyToAll: () => void;
  /** UI state for the apply-all action. */
  applyAllStatus: "idle" | "saving" | "saved" | "error";
}) {
  // Defensive: legacy specs may be missing the auto_zoom block until the
  // server-side normalization round-trip lands.
  const az = autoZoom ?? { enabled: false, max_scale: 1.2, timestamps: [] };

  // Soft-gate PRO controls: free users see the badge AND the upgrade
  // modal when they touch a gated control, but the action still executes
  // so they can feel what they'd unlock.
  const { isFree } = usePlan();
  const { openUpgrade } = useUpgrade();
  const gateAnimations = () => {
    if (isFree) openUpgrade("animations");
  };
  const gateSound = () => {
    if (isFree) openUpgrade("sound");
  };

  return (
    <div className="space-y-5">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Effects
      </div>
      <div className="text-[10px] opacity-60">
        Auto-zoom punch-ins + transition library. Press{" "}
        <kbd className="rounded bg-zinc-800 px-1">E</kbd> to jump here.
      </div>

      {/* ------- Auto-zoom ------- */}
      <div className="space-y-3 rounded-md border border-zinc-800 bg-zinc-900/50 p-3">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2 text-[12px] font-semibold">
            <ZoomIn className="h-3.5 w-3.5" />
            Auto-zoom
            <ProBadge />
          </Label>
          <Switch
            checked={az.enabled}
            onCheckedChange={(v) => {
              gateAnimations();
              onToggleAutoZoom(v);
            }}
          />
        </div>

        <Button
          size="sm"
          variant="outline"
          className="w-full gap-1.5"
          onClick={() => {
            gateAnimations();
            onDetectZooms();
          }}
          disabled={detecting || !hasTranscript}
        >
          {detecting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Wand2 className="h-3 w-3" />
          )}
          {detecting ? "Detecting…" : "Detect zooms with AI"}
        </Button>

        <div>
          <Label className="text-[11px] opacity-70">
            Max zoom: {az.max_scale.toFixed(2)}x
          </Label>
          <input
            type="range"
            min={1.0}
            max={1.6}
            step={0.05}
            value={az.max_scale}
            onChange={(e) => onChangeMaxScale(parseFloat(e.target.value))}
            className="mt-1 w-full accent-violet-500"
          />
        </div>

        <div className="flex items-center justify-between text-[11px]">
          <span className="opacity-70">
            {az.timestamps.length} moment{az.timestamps.length === 1 ? "" : "s"}
          </span>
          {az.timestamps.length > 0 && (
            <button
              onClick={onClearZooms}
              className="inline-flex items-center gap-1 text-zinc-500 hover:text-red-400"
            >
              <Trash2 className="h-3 w-3" />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* ------- Transitions (15-card grid + boundary mode) ------- */}
      <div className="space-y-3 rounded-md border border-zinc-800 bg-zinc-900/50 p-3">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2 text-[12px] font-semibold">
            <Sparkles className="h-3.5 w-3.5" />
            Transitions
            <ProBadge />
          </Label>
          <Switch
            checked={transitions.enabled}
            onCheckedChange={(v) => {
              gateAnimations();
              onChangeTxEnabled(v);
            }}
          />
        </div>

        {/* Mode toggle — "Global default" vs "Selected boundary". The
            boundary tab is forced active whenever the user clicks a
            diamond on the timeline (auto-jump via useEffect in parent). */}
        <BoundaryModeTabs
          selectedBoundaryId={selectedBoundaryId}
          boundaryInstance={boundaryInstance}
          selectedBetween={selectedBetween}
          betweenInstance={betweenInstance}
          onUpsertBetween={(template) => {
            gateAnimations();
            onUpsertBetween(template);
          }}
          onClearBetween={onClearBetween}
          transitions={transitions}
          onUpsertBoundary={(instance) => {
            gateAnimations();
            onUpsertBoundary(instance);
          }}
          onClearBoundary={onClearBoundary}
          onChangeTxType={(t) => {
            gateAnimations();
            onChangeTxType(t);
          }}
          onChangeTxEnabled={onChangeTxEnabled}
          onChangeTxDuration={onChangeTxDuration}
          onChangeTxSfx={(v) => {
            gateSound();
            onChangeTxSfx(v);
          }}
        />

        {/* Apply-to-all bulk action: stamps the GLOBAL transition onto
            every boundary so the user can tweak each one individually
            after dialing in a great default. Disabled until the global
            transition is enabled. */}
        <button
          type="button"
          onClick={() => {
            gateAnimations();
            onApplyToAll();
          }}
          disabled={!transitions.enabled || applyAllStatus === "saving"}
          className="w-full rounded border border-zinc-800 px-2 py-1.5 text-[10px] font-medium hover:bg-zinc-800/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {applyAllStatus === "saving"
            ? "Applying…"
            : applyAllStatus === "saved"
            ? "Applied to all boundaries"
            : applyAllStatus === "error"
            ? "Apply failed — retry?"
            : "Apply global default to every boundary"}
        </button>

        <div className="rounded border border-zinc-800/60 bg-zinc-950/40 p-2 text-[10px] leading-snug opacity-70">
          Click a diamond marker on the timeline to override that boundary
          individually. Press Delete to remove an override.
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Boundary mode tabs (Week 6 Phase 4)
// ---------------------------------------------------------------------------

function BoundaryModeTabs({
  selectedBoundaryId,
  boundaryInstance,
  selectedBetween,
  betweenInstance,
  onUpsertBetween,
  onClearBetween,
  transitions,
  onUpsertBoundary,
  onClearBoundary,
  onChangeTxType,
  onChangeTxEnabled,
  onChangeTxDuration,
  onChangeTxSfx,
}: {
  selectedBoundaryId: string | null;
  boundaryInstance: TransitionInstance | null;
  selectedBetween: {
    outId: string;
    inId: string;
    clipAIdx: number;
    clipBIdx: number;
  } | null;
  betweenInstance: TransitionInstance | null;
  onUpsertBetween: (template: TransitionInstance) => void;
  onClearBetween: () => void;
  transitions: Transitions;
  onUpsertBoundary: (instance: TransitionInstance) => void;
  onClearBoundary: () => void;
  onChangeTxType: (t: TransitionType) => void;
  onChangeTxEnabled: (v: boolean) => void;
  onChangeTxDuration: (ms: number) => void;
  onChangeTxSfx: (v: boolean) => void;
}) {
  // Boundary mode covers BOTH single-boundary selections (a diamond
  // marker) and "between two clips" selections (a pill marker). The
  // selected-tab label switches to "Crossfade between clips" in the
  // latter case so users see what their edit will do.
  const hasBoundarySelection = !!selectedBoundaryId || !!selectedBetween;

  const [tab, setTab] = useState<"global" | "boundary">(
    hasBoundarySelection ? "boundary" : "global",
  );
  useEffect(() => {
    if (hasBoundarySelection) setTab("boundary");
    else setTab("global");
  }, [hasBoundarySelection]);

  // For single-boundary mode, derive the "effective" instance: either
  // the saved override or a synthesized copy of the global defaults so
  // the picker has something to highlight.
  const singleEffective: TransitionInstance | null = selectedBoundaryId
    ? boundaryInstance ?? {
        boundary_id: selectedBoundaryId,
        type: transitions.type,
        duration_ms: transitions.duration_ms,
        sfx_enabled: transitions.sfx_enabled,
        params: {},
      }
    : null;

  // For between mode, do the same — but the "template" instance carries
  // a synthetic id; the parent's onUpsertBetween splats it onto BOTH
  // real boundary ids before persisting.
  const betweenEffective: TransitionInstance | null = selectedBetween
    ? betweenInstance ?? {
        boundary_id: `between_${selectedBetween.outId}_${selectedBetween.inId}`,
        // Default to "fade" when first creating a crossfade between two
        // clips — it's the safe choice that actually overlaps blends
        // visually for the user; they can pick something flashier next.
        type:
          transitions.type === "cut" || !transitions.type
            ? "fade"
            : transitions.type,
        duration_ms: transitions.duration_ms || 400,
        sfx_enabled: transitions.sfx_enabled,
        params: {},
      }
    : null;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1 rounded-md bg-zinc-950/60 p-0.5">
        <button
          type="button"
          onClick={() => setTab("global")}
          className={`rounded px-2 py-1 text-[10px] font-medium transition-colors ${
            tab === "global"
              ? "bg-zinc-800 text-white"
              : "text-zinc-400 hover:text-white"
          }`}
        >
          Global default
        </button>
        <button
          type="button"
          onClick={() => hasBoundarySelection && setTab("boundary")}
          disabled={!hasBoundarySelection}
          className={`rounded px-2 py-1 text-[10px] font-medium transition-colors ${
            tab === "boundary"
              ? "bg-violet-900/40 text-violet-100"
              : "text-zinc-500 hover:text-white disabled:cursor-not-allowed disabled:hover:text-zinc-500"
          }`}
          title={
            selectedBetween
              ? `Crossfade ${selectedBetween.outId} → ${selectedBetween.inId}`
              : selectedBoundaryId ??
                "Click a boundary marker on the timeline first"
          }
        >
          {selectedBetween
            ? "Crossfade between clips"
            : selectedBoundaryId
            ? "Selected boundary"
            : "Select a boundary…"}
        </button>
      </div>

      {tab === "global" && (
        <div className="space-y-3">
          <TransitionGrid
            activeType={transitions.type}
            enabled={transitions.enabled}
            onPick={(t) => {
              onChangeTxType(t);
              if (t !== "cut" && !transitions.enabled) onChangeTxEnabled(true);
            }}
          />

          <div>
            <Label className="text-[11px] opacity-70">
              Duration: {transitions.duration_ms}ms
            </Label>
            <input
              type="range"
              min={100}
              max={800}
              step={50}
              value={transitions.duration_ms}
              onChange={(e) => onChangeTxDuration(parseInt(e.target.value, 10))}
              disabled={!transitions.enabled}
              className="mt-1 w-full accent-violet-500"
            />
          </div>

          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-2 text-[11px] opacity-80">
              {transitions.sfx_enabled ? (
                <Volume2 className="h-3 w-3" />
              ) : (
                <VolumeX className="h-3 w-3" />
              )}
              SFX stinger
            </Label>
            <Switch
              checked={transitions.sfx_enabled}
              onCheckedChange={onChangeTxSfx}
              disabled={!transitions.enabled}
            />
          </div>
        </div>
      )}

      {tab === "boundary" && singleEffective && !selectedBetween && (
        <div className="space-y-3">
          <div className="rounded border border-violet-900/40 bg-violet-950/20 p-2 text-[10px] leading-snug">
            <div className="font-mono opacity-70">{selectedBoundaryId}</div>
            <div className="mt-0.5 opacity-60">
              {boundaryInstance
                ? "Override active. Press Delete to revert to global."
                : "No override yet — showing the global default."}
            </div>
          </div>

          <TransitionGrid
            activeType={singleEffective.type}
            enabled
            onPick={(t) =>
              onUpsertBoundary({
                ...singleEffective,
                type: t,
              })
            }
          />

          <div>
            <Label className="text-[11px] opacity-70">
              Duration: {singleEffective.duration_ms}ms
            </Label>
            <input
              type="range"
              min={100}
              max={800}
              step={50}
              value={singleEffective.duration_ms}
              onChange={(e) =>
                onUpsertBoundary({
                  ...singleEffective,
                  duration_ms: parseInt(e.target.value, 10),
                })
              }
              className="mt-1 w-full accent-violet-500"
            />
          </div>

          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-2 text-[11px] opacity-80">
              {singleEffective.sfx_enabled ? (
                <Volume2 className="h-3 w-3" />
              ) : (
                <VolumeX className="h-3 w-3" />
              )}
              SFX stinger
            </Label>
            <Switch
              checked={singleEffective.sfx_enabled}
              onCheckedChange={(v) =>
                onUpsertBoundary({ ...singleEffective, sfx_enabled: v })
              }
            />
          </div>

          {boundaryInstance && (
            <button
              type="button"
              onClick={onClearBoundary}
              className="w-full rounded border border-zinc-800 px-2 py-1.5 text-[10px] font-medium text-zinc-300 hover:bg-zinc-800/60"
            >
              Revert to global default
            </button>
          )}
        </div>
      )}

      {tab === "boundary" && betweenEffective && selectedBetween && (
        <div className="space-y-3">
          <div className="rounded border border-pink-900/40 bg-pink-950/20 p-2 text-[10px] leading-snug">
            <div className="font-medium text-pink-200">
              Crossfade between clips
            </div>
            <div className="mt-1 font-mono opacity-70">
              {selectedBetween.outId} → {selectedBetween.inId}
            </div>
            <div className="mt-1 opacity-70">
              Picking a transition stamps it on both edges and shifts the
              second clip left by{" "}
              <span className="font-medium text-pink-200">
                {betweenEffective.duration_ms}ms
              </span>{" "}
              so they overlap visually. Press Delete to clear.
            </div>
          </div>

          <TransitionGrid
            activeType={betweenEffective.type}
            enabled
            onPick={(t) =>
              onUpsertBetween({
                ...betweenEffective,
                type: t,
              })
            }
          />

          <div>
            <Label className="text-[11px] opacity-70">
              Duration / overlap: {betweenEffective.duration_ms}ms
            </Label>
            <input
              type="range"
              min={100}
              max={800}
              step={50}
              value={betweenEffective.duration_ms}
              onChange={(e) =>
                onUpsertBetween({
                  ...betweenEffective,
                  duration_ms: parseInt(e.target.value, 10),
                })
              }
              className="mt-1 w-full accent-pink-500"
            />
          </div>

          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-2 text-[11px] opacity-80">
              {betweenEffective.sfx_enabled ? (
                <Volume2 className="h-3 w-3" />
              ) : (
                <VolumeX className="h-3 w-3" />
              )}
              SFX stinger
            </Label>
            <Switch
              checked={betweenEffective.sfx_enabled}
              onCheckedChange={(v) =>
                onUpsertBetween({ ...betweenEffective, sfx_enabled: v })
              }
            />
          </div>

          {betweenInstance && (
            <button
              type="button"
              onClick={onClearBetween}
              className="w-full rounded border border-zinc-800 px-2 py-1.5 text-[10px] font-medium text-zinc-300 hover:bg-zinc-800/60"
            >
              Remove crossfade
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const TRANSITION_CATEGORY_ORDER: TransitionCategory[] = [
  "basic",
  "slide",
  "zoom",
  "glitch",
  "cinematic",
];

const TRANSITION_CATEGORY_LABEL: Record<TransitionCategory, string> = {
  basic: "Basic",
  slide: "Slide",
  zoom: "Zoom",
  glitch: "Glitch",
  cinematic: "Cinematic",
};

/**
 * Category-tabbed grid of transition cards. Each card shows a placeholder
 * thumbnail (the actual animated previews are wired in Phase 5 via
 * scripts/render_transition_thumbnails.py → public/transitions/*.webm)
 * and a label. Picking a card sets ``transitions.type``.
 *
 * Lives inside EffectsPanel — extracted so the markup stays readable and
 * the per-card state (hover preview, etc.) has its own scope.
 */
function TransitionGrid({
  activeType,
  enabled,
  onPick,
}: {
  activeType: TransitionType;
  enabled: boolean;
  onPick: (t: TransitionType) => void;
}) {
  const [catalog, setCatalog] = useState<TransitionInfo[]>([]);
  const [tab, setTab] = useState<TransitionCategory>("basic");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    listTransitions()
      .then((rows) => {
        if (alive) setCatalog(rows);
      })
      .catch(() => {
        // Backend may not be up yet — leave the grid empty rather than
        // crashing the panel.
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // Move the tab to whichever category the currently-active type is in
  // so the user sees the highlighted card when re-opening the panel.
  useEffect(() => {
    const found = catalog.find((t) => t.name === activeType);
    if (found) setTab(found.category);
  }, [catalog, activeType]);

  const filtered = useMemo(
    () => catalog.filter((t) => t.category === tab),
    [catalog, tab],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[11px] opacity-60">
        <Loader2 className="h-3 w-3 animate-spin" />
        Loading transitions…
      </div>
    );
  }
  if (catalog.length === 0) {
    return (
      <div className="text-[11px] opacity-60">
        Couldn't load the transitions catalog.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {TRANSITION_CATEGORY_ORDER.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setTab(c)}
            disabled={!enabled}
            className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide transition-colors ${
              tab === c
                ? "bg-violet-600 text-white"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            } ${!enabled ? "cursor-not-allowed opacity-50" : ""}`}
          >
            {TRANSITION_CATEGORY_LABEL[c]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        {filtered.map((t) => (
          <TransitionCard
            key={t.name}
            info={t}
            active={t.name === activeType}
            disabled={!enabled}
            onPick={() => onPick(t.name)}
          />
        ))}
      </div>
    </div>
  );
}

function TransitionCard({
  info,
  active,
  disabled,
  onPick,
}: {
  info: TransitionInfo;
  active: boolean;
  disabled: boolean;
  onPick: () => void;
}) {
  // Phase 5: each thumbnail is a ~1.5s VP9 webm loop rendered by
  // ``scripts/render_transition_thumbnails.py`` into
  // ``public/transitions/<name>.webm``. The video tag autoplays muted +
  // loops on hover so the panel feels alive without burning CPU.
  const placeholderGradient: Record<TransitionCategory, string> = {
    basic: "from-zinc-700 to-zinc-900",
    slide: "from-blue-700 to-zinc-900",
    zoom: "from-violet-700 to-zinc-900",
    glitch: "from-pink-700 to-zinc-900",
    cinematic: "from-amber-700 to-zinc-900",
  };
  const thumbUrl = `/transitions/${info.thumbnail}`;
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={disabled}
      title={info.description}
      className={`group relative flex flex-col overflow-hidden rounded border text-left transition-all ${
        active
          ? "border-violet-500 ring-1 ring-violet-500/40"
          : "border-zinc-800 hover:border-zinc-600"
      } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <div
        className={`relative aspect-video w-full bg-gradient-to-br ${
          placeholderGradient[info.category]
        } flex items-center justify-center`}
      >
        <video
          src={thumbUrl}
          className="absolute inset-0 h-full w-full object-cover"
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          aria-hidden
        />
        {info.has_sfx && (
          <Volume2 className="absolute right-1 top-1 h-2.5 w-2.5 text-white/70 drop-shadow-[0_0_2px_rgba(0,0,0,0.8)]" />
        )}
        <span className="relative z-10 rounded bg-black/40 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white/90 backdrop-blur-sm">
          {info.label}
        </span>
      </div>
      <div className="flex items-center justify-between gap-1 px-1.5 py-1 text-[9px] opacity-70">
        <span>{info.default_duration_ms}ms</span>
        {active && <span className="text-violet-400">●</span>}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Backgrounds panel (Week 6 Phase 2)
// ---------------------------------------------------------------------------

function BackgroundsPanel({
  backgroundLoop,
  onPick,
  onClear,
  layoutMode,
  onPromoteLayout,
}: {
  backgroundLoop: BackgroundLoop | null;
  onPick: (bg: BackgroundLoop) => void;
  onClear: () => void;
  layoutMode: Layout["mode"];
  onPromoteLayout: () => void;
}) {
  const [featured, setFeatured] = useState<BackgroundCatalogEntry[]>([]);
  const [loadingFeatured, setLoadingFeatured] = useState(true);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<BackgroundSearchResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    listBackgrounds()
      .then((rows) => {
        if (alive) setFeatured(rows);
      })
      .catch(() => {
        // Backend unreachable — leave the panel empty rather than crashing.
      })
      .finally(() => alive && setLoadingFeatured(false));
    return () => {
      alive = false;
    };
  }, []);

  async function runSearch() {
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const rows = await searchBackgrounds(query.trim());
      setResults(rows);
      if (rows.length === 0) setSearchError("No results. Try a different keyword.");
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Backgrounds
      </div>
      <div className="text-[10px] opacity-60">
        Add a looping video underneath your main clip. Press{" "}
        <kbd className="rounded bg-zinc-800 px-1">B</kbd> to jump here.
      </div>

      {/* ------- Current background + clear ------- */}
      {backgroundLoop && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-violet-700/50 bg-violet-950/30 p-2 text-[11px]">
          <div className="min-w-0 flex-1 truncate">
            <span className="opacity-70">Active: </span>
            <span className="font-medium">
              {backgroundLoop.label ||
                backgroundLoop.catalog_id ||
                "Pexels clip"}
            </span>
          </div>
          <button
            onClick={onClear}
            className="inline-flex items-center gap-1 text-zinc-300 hover:text-red-400"
            title="Remove background"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* ------- Smart-pair CTA when layout would hide the bg ------- */}
      {backgroundLoop && layoutMode === "single" && (
        <button
          onClick={onPromoteLayout}
          className="w-full rounded-md border border-amber-700/50 bg-amber-950/30 p-2 text-left text-[11px]"
        >
          <div className="font-medium text-amber-300">
            Background is hidden in Single layout
          </div>
          <div className="opacity-70">
            Click to switch to Split Horizontal so it shows behind your video.
          </div>
        </button>
      )}

      {/* ------- Featured grid ------- */}
      <div className="space-y-2">
        <Label className="text-[11px] opacity-70">Featured</Label>
        {loadingFeatured ? (
          <div className="flex items-center gap-2 text-[11px] opacity-60">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading…
          </div>
        ) : featured.length === 0 ? (
          <div className="text-[11px] opacity-60">
            Couldn't load featured backgrounds.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-1.5">
            {featured.map((b) => {
              const active =
                backgroundLoop?.source === "catalog" &&
                backgroundLoop.catalog_id === b.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() =>
                    onPick({
                      source: "catalog",
                      catalog_id: b.id,
                      clip_url: b.download_url || null,
                      loop_start_offset_seconds: 0,
                      volume: 0,
                      label: b.label,
                    })
                  }
                  className={`overflow-hidden rounded border text-left transition-all ${
                    active
                      ? "border-violet-500 ring-1 ring-violet-500/40"
                      : "border-zinc-800 hover:border-zinc-600"
                  }`}
                  title={b.label}
                >
                  <div className="relative aspect-video w-full bg-zinc-900">
                    <img
                      src={b.preview_thumbnail}
                      alt={b.label}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                    <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[9px] font-medium uppercase">
                      {b.category}
                    </span>
                  </div>
                  <div className="px-1.5 py-1 text-[9px] opacity-80">
                    {b.label}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ------- Pexels search ------- */}
      <div className="space-y-2">
        <Label className="text-[11px] opacity-70">Search Pexels</Label>
        <div className="flex gap-1.5">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSearch();
            }}
            placeholder="e.g. minecraft, lofi rain, fireplace"
            className="h-8 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={runSearch}
            disabled={searching || !query.trim()}
          >
            {searching ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Search className="h-3 w-3" />
            )}
          </Button>
        </div>
        {searchError && (
          <div className="text-[10px] text-red-400">{searchError}</div>
        )}
        {results.length > 0 && (
          <div className="grid grid-cols-2 gap-1.5">
            {results.map((r) => {
              const active =
                backgroundLoop?.source === "pexels" &&
                backgroundLoop.clip_url === r.download_url;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() =>
                    onPick({
                      source: "pexels",
                      catalog_id: null,
                      clip_url: r.download_url,
                      loop_start_offset_seconds: 0,
                      volume: 0,
                      label: r.label,
                    })
                  }
                  className={`overflow-hidden rounded border text-left transition-all ${
                    active
                      ? "border-violet-500 ring-1 ring-violet-500/40"
                      : "border-zinc-800 hover:border-zinc-600"
                  }`}
                  title={r.label}
                >
                  <div className="aspect-video w-full bg-zinc-900">
                    <img
                      src={r.preview_thumbnail}
                      alt={r.label}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  </div>
                  <div className="truncate px-1.5 py-1 text-[9px] opacity-80">
                    {r.label}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout panel (Week 6 Phase 3 — UI shell, math wired in Phase 3 render)
// ---------------------------------------------------------------------------

function LayoutPanel({
  layout,
  onUpdate,
  hasBackground,
  onJumpToBackgrounds,
}: {
  layout: Layout;
  onUpdate: (patch: Partial<Layout>) => void;
  hasBackground: boolean;
  onJumpToBackgrounds: () => void;
}) {
  const modes: { id: Layout["mode"]; label: string; sketch: string }[] = [
    { id: "single", label: "Single", sketch: "▮" },
    { id: "split_horizontal", label: "Split H", sketch: "▼" },
    { id: "split_vertical", label: "Split V", sketch: "▶" },
    { id: "pip_corner", label: "PiP", sketch: "▣" },
  ];

  return (
    <div className="space-y-4">
      <div className="text-xs font-semibold uppercase tracking-wider opacity-60">
        Layout
      </div>
      <div className="text-[10px] opacity-60">
        Stack your video with a background loop. Press{" "}
        <kbd className="rounded bg-zinc-800 px-1">L</kbd> to jump here.
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {modes.map((m) => {
          const active = layout.mode === m.id;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => onUpdate({ mode: m.id })}
              className={`rounded border p-3 text-center transition-all ${
                active
                  ? "border-violet-500 bg-violet-900/30 text-white"
                  : "border-zinc-800 text-zinc-300 hover:border-zinc-600"
              }`}
            >
              <div className="text-2xl">{m.sketch}</div>
              <div className="text-[10px] font-medium">{m.label}</div>
            </button>
          );
        })}
      </div>

      {(layout.mode === "split_horizontal" || layout.mode === "split_vertical") && (
        <div>
          <Label className="text-[11px] opacity-70">
            Main video size: {(layout.main_weight * 100).toFixed(0)}%
          </Label>
          <input
            type="range"
            min={0.30}
            max={0.80}
            step={0.05}
            value={layout.main_weight}
            onChange={(e) => onUpdate({ main_weight: parseFloat(e.target.value) })}
            className="mt-1 w-full accent-violet-500"
          />
        </div>
      )}

      {layout.mode === "pip_corner" && (
        <div className="space-y-3">
          <div>
            <Label className="text-[11px] opacity-70">Inset corner</Label>
            <div className="mt-1 grid grid-cols-2 gap-1">
              {(["tl", "tr", "bl", "br"] as const).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => onUpdate({ pip_corner: c })}
                  className={`rounded border px-2 py-1 text-[10px] font-medium uppercase transition-colors ${
                    layout.pip_corner === c
                      ? "border-violet-500 bg-violet-900/30 text-white"
                      : "border-zinc-800 text-zinc-300 hover:border-zinc-600"
                  }`}
                >
                  {c.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label className="text-[11px] opacity-70">
              Inset size: {(layout.pip_size * 100).toFixed(0)}%
            </Label>
            <input
              type="range"
              min={0.15}
              max={0.50}
              step={0.05}
              value={layout.pip_size}
              onChange={(e) => onUpdate({ pip_size: parseFloat(e.target.value) })}
              className="mt-1 w-full accent-violet-500"
            />
          </div>
        </div>
      )}

      {/* Smart-pair CTA: hint to add a background when a split/pip layout
          is selected but no bg loop is configured (the empty region would
          render as a solid black rectangle). */}
      {layout.mode !== "single" && !hasBackground && (
        <button
          onClick={onJumpToBackgrounds}
          className="w-full rounded-md border border-amber-700/50 bg-amber-950/30 p-2 text-left text-[11px]"
        >
          <div className="font-medium text-amber-300">
            Pick a background to fill the empty region
          </div>
          <div className="opacity-70">
            Otherwise the secondary area renders as a solid black rectangle.
          </div>
        </button>
      )}
    </div>
  );
}

function RenderStatusCard({
  renderUrl,
  renderError,
}: {
  renderUrl: string | null;
  renderError: string | null;
}) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900 p-3 text-xs">
      <div className="font-semibold opacity-80 mb-1">Last render</div>
      {renderUrl && (
        <a
          href={renderUrl}
          target="_blank"
          rel="noreferrer"
          className="text-violet-400 underline break-all"
        >
          {renderUrl}
        </a>
      )}
      {renderError && <div className="text-red-400 mt-1">{renderError}</div>}
    </div>
  );
}

/**
 * Studio editor — TypeScript types mirroring `src/features/studio/spec.py`.
 *
 * Keep this in sync with the Pydantic models on the backend. The spec is the
 * single source of truth that drives both the in-browser Remotion preview
 * and the server-side ffmpeg render, so a drift here means the user previews
 * something different from what gets rendered.
 */

export const SPEC_VERSION = 1;

export type AspectRatio = "9:16" | "1:1" | "4:5" | "16:9";

export type CaptionStyleName =
  | "capcut"
  | "mrbeast"
  | "hormozi"
  | "neon"
  | "minimal"
  | "bounce"
  | "karaoke";

export type CaptionPosition = "top" | "middle" | "bottom";
export type HighlightMode = "word" | "group";

/** Mirror of TransitionType in src/features/studio/spec.py. Keep both in sync.
 *  Catalog metadata (label, default duration, sfx, ffmpeg recipe) lives on
 *  the backend; the frontend mirrors the visual behaviour in
 *  studio/composition/transitionRecipes.ts. */
export type TransitionType =
  // basic
  | "cut"
  | "fade"
  | "dissolve"
  // slide ("swipe" kept as legacy alias for slide-left from Week 5)
  | "swipe"
  | "slide_up"
  | "slide_down"
  // zoom
  | "zoom_in"
  | "zoom_out"
  | "zoom_blur"
  // glitch
  | "rgb_split"
  | "glitch_shake"
  | "vhs"
  // cinematic
  | "flash_white"
  | "fade_to_black"
  | "whoosh";

export type TransitionCategory = "basic" | "slide" | "zoom" | "glitch" | "cinematic";

export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  confidence?: number;
  /**
   * Manual caption-grouping override (mirrors `TranscriptWord.force_break_after`
   * in `src/features/studio/spec.py`):
   * - `true`  → next word always starts a new caption phrase (manual split)
   * - `false` → next word always continues this phrase (manual merge)
   * - `null` / undefined → fall back to the default grouping heuristic
   */
  force_break_after?: boolean | null;
  /**
   * Optional sentiment emoji attached to this word by the Week 6
   * emoji_suggester. Rendered as a trailing inline span in preview and
   * burned into the ASS karaoke text when `captions.emoji_enabled` is
   * true. Storing it on the word (not in `text`) keeps the toggle
   * reversible without re-running the LLM.
   */
  emoji?: string | null;
}

export interface PeaksResponse {
  /** End - start seconds covered by the peaks array. */
  duration: number;
  /** Length of `peaks`; equal to the `bins` query param requested. */
  bins: number;
  /** Max absolute audio amplitude per bin, normalized to [0,1]. */
  peaks: number[];
}

export interface SourceClip {
  source_url: string;
  source_clip_path?: string | null;
  start_time: number;
  end_time: number;
  transcript: TranscriptWord[];
  suggested_title?: string | null;
}

export interface Crop {
  x: number;
  y: number;
  width: number;
  height: number;
  tracking: "static" | "smart";
}

export interface Captions {
  enabled: boolean;
  style: CaptionStyleName;
  position: CaptionPosition;
  highlight_mode: HighlightMode;
  font_family: string;
  font_size: number;
  color_primary: string;
  color_highlight: string;
  stroke_width: number;
  stroke_color: string;
  uppercase: boolean;
  emoji_enabled: boolean;
}

export interface BRollClip {
  /** Stable per-clip id used by per-boundary transitions (Week 6).
   *  Auto-assigned by the backend when missing; treated as required
   *  client-side so the per-boundary code can rely on it. */
  id: string;
  track: number;
  start: number;
  end: number;
  clip_url: string;
  source: "pexels" | "pixabay" | "upload" | "tenor" | "giphy";
  opacity: number;
  mute: boolean;
  label?: string | null;
}

export interface BRollTrack {
  enabled: boolean;
  auto_suggest: boolean;
  clips: BRollClip[];
}

export interface Transitions {
  enabled: boolean;
  type: TransitionType;
  duration_ms: number;
  sfx_enabled: boolean;
}

/** Per-boundary transition override (Week 6). When the spec's
 *  ``boundary_transitions`` array is non-empty it takes precedence over
 *  the global ``transitions`` block; the renderer + preview look up each
 *  boundary individually so users can tweak a single edge. */
export interface TransitionInstance {
  /** One of:
   *   - "broll_{clip.id}_in"   - leading edge of a B-roll clip
   *   - "broll_{clip.id}_out"  - trailing edge of a B-roll clip
   *   - "camera_cut_{cut.id}"  - camera-cut boundary at the cut's start
   */
  boundary_id: string;
  type: TransitionType;
  duration_ms: number;
  sfx_enabled: boolean;
  params?: Record<string, unknown>;
}

/** Canvas layout (Week 6). Same shape as Layout in spec.py. */
export interface Layout {
  mode: "single" | "split_horizontal" | "split_vertical" | "pip_corner";
  pip_corner: "tl" | "tr" | "bl" | "br";
  pip_size: number;     // 0.15..0.50
  main_weight: number;  // 0.30..0.80
}

/** Background loop (Week 6). Mirrors BackgroundLoop in spec.py. */
export interface BackgroundLoop {
  source: "catalog" | "pexels";
  catalog_id?: string | null;
  clip_url?: string | null;
  loop_start_offset_seconds: number;
  volume: number;
  label?: string | null;
}

export interface BrandKit {
  logo_url?: string | null;
  logo_position: "tl" | "tr" | "bl" | "br";
  logo_opacity: number;
  primary_color?: string | null;
  accent_color?: string | null;
  font_family?: string | null;
}

export interface AutoZoom {
  enabled: boolean;
  max_scale: number;
  timestamps: number[];
}

/** One contiguous focus-on-subject segment in the Camera lane. Mirrors
 *  `CameraCut` in src/features/studio/spec.py. Times are clip-local seconds. */
export interface CameraCut {
  /** Stable per-cut id used by per-boundary transitions (Week 6). */
  id: string;
  start: number;
  end: number;
  subject_id: number;
}

/** Multi-subject virtual multi-cam config. Mirrors `Camera` in spec.py. */
export interface Camera {
  tracks: CameraCut[];
  bbox_overlay_enabled: boolean;
  ease_pan: boolean;
  n_subjects_requested: number;
}

/** One detected subject within the cached tracking payload. */
export interface TrackingSubject {
  id: number;
  label: string;
  color_hex: string;
  /** Per-frame smoothed crop X (horizontal offset). Indexed by frame number
   *  within the cached segment. */
  smoothed_crop_x: number[];
  /** Sparse per-detection bbox samples (one per detection_interval frame). */
  frames: Array<{
    t: number;
    x: number;
    y: number;
    w: number;
    h: number;
    conf: number;
  }>;
}

export interface TrackingData {
  fps: number;
  frame_w: number;
  frame_h: number;
  /** Clip-local start time the tracking was computed for (matches the
   *  session's clip.start_time at compute time). */
  start_time: number;
  /** Clip-local end time the tracking was computed for. */
  end_time: number;
  subjects: TrackingSubject[];
}

/** Status payload returned by GET /studio/sessions/:key/tracking when the
 *  cached payload isn't ready yet. Shape matches the 503 body. */
export interface TrackingStatus {
  status: "idle" | "computing" | "done" | "failed";
  progress?: number | null;
  progress_message?: string | null;
  retry_after?: number | null;
}

export interface EditSpec {
  version: number;
  clip: SourceClip;
  aspect_ratio: AspectRatio;
  crop?: Crop | null;
  captions: Captions;
  broll: BRollTrack;
  transitions: Transitions;
  /** Per-boundary transition overrides (Week 6). Empty = use global. */
  boundary_transitions: TransitionInstance[];
  brand_kit: BrandKit;
  auto_zoom: AutoZoom;
  camera: Camera;
  layout: Layout;
  background_loop?: BackgroundLoop | null;
  template?: string | null;
}

/** Recommendation envelope captured when the user lands in Studio via
 *  a cross-tool deep link. Mirrors the structured CTA shape used by
 *  ``mapRecommendationToCta``. Persists with the session so that
 *  post-publish metrics can roll up against the originating tool. */
export interface CtaProvenance {
  /** The tool the recommendation pointed at: ``"hook_lab"``,
   *  ``"script_writer"``, ``"ab_tester"``, etc. */
  tool: string;
  /** Optional machine-readable reason key (e.g. ``"start_bottleneck"``). */
  reason?: string;
  /** Where the user came from: ``"analyzer"``, ``"shorts"``,
   *  ``"velocity"``, ``"drafts"``, … */
  from?: string;
  /** Free-form label that was on the CTA button the user clicked. */
  label?: string;
  /** When this attribution was first captured (ISO). */
  captured_at?: string;
}

export interface EditSession {
  id: number;
  clip_key: string;
  title?: string | null;
  source_video_url: string;
  source_clip_index: number;
  source_clip_path?: string | null;
  source_start_time?: number | null;
  source_end_time?: number | null;
  spec: EditSpec;
  last_render_status: "idle" | "queued" | "rendering" | "done" | "failed";
  last_render_url?: string | null;
  last_render_error?: string | null;
  last_rendered_at?: string | null;
  created_at: string;
  updated_at: string;
  /** Week 10: originating recommendation, if any. ``null`` for
   *  sessions opened directly from Drafts or the demo. */
  cta_provenance?: CtaProvenance | null;
}

export interface RenderStatus {
  job_id?: string | null;
  status: "idle" | "queued" | "rendering" | "done" | "failed";
  last_render_url?: string | null;
  /** Backend-assigned session row id; the frontend uses it to call the
   *  /studio/render/{id}/status polling endpoint. */
  session_id?: number | null;
  /** Coarse render progress, 0-100, written by the render job. */
  progress?: number | null;
  /** Short human-readable status ("Encoding 42%", "Uploading to storage"). */
  progress_message?: string | null;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

export function defaultCaptions(): Captions {
  return {
    enabled: true,
    style: "capcut",
    position: "bottom",
    highlight_mode: "word",
    font_family: "Montserrat",
    font_size: 72,
    color_primary: "#FFFFFF",
    color_highlight: "#00FF99",
    stroke_width: 4,
    stroke_color: "#000000",
    uppercase: false,
    emoji_enabled: false,
  };
}

export function defaultSpec(clip: SourceClip): EditSpec {
  return {
    version: SPEC_VERSION,
    clip,
    aspect_ratio: "9:16",
    crop: null,
    captions: defaultCaptions(),
    broll: { enabled: true, auto_suggest: false, clips: [] },
    transitions: { enabled: false, type: "cut", duration_ms: 300, sfx_enabled: false },
    boundary_transitions: [],
    brand_kit: { logo_position: "br", logo_opacity: 0.85 },
    auto_zoom: { enabled: false, max_scale: 1.15, timestamps: [] },
    camera: { tracks: [], bbox_overlay_enabled: false, ease_pan: false, n_subjects_requested: 4 },
    layout: { mode: "single", pip_corner: "br", pip_size: 0.30, main_weight: 0.50 },
    background_loop: null,
    template: null,
  };
}

// ---------------------------------------------------------------------------
// Aspect ratio helpers (mirror render.get_output_dimensions)
// ---------------------------------------------------------------------------

export const ASPECT_DIMENSIONS: Record<AspectRatio, { width: number; height: number }> = {
  "9:16": { width: 1080, height: 1920 },
  "1:1": { width: 1080, height: 1080 },
  "4:5": { width: 1080, height: 1350 },
  "16:9": { width: 1920, height: 1080 },
};

export const ASPECT_LABELS: Record<AspectRatio, string> = {
  "9:16": "Portrait (Shorts/Reels)",
  "1:1": "Square (IG feed)",
  "4:5": "Tall (IG feed)",
  "16:9": "Landscape (YouTube)",
};

// ---------------------------------------------------------------------------
// Stable clip key (mirror src/api/routers/studio.py _stable_clip_key)
// ---------------------------------------------------------------------------

export async function computeClipKey(
  sourceUrl: string,
  clipIndex: number,
  start: number,
  end: number,
): Promise<string> {
  const raw = `${sourceUrl}|${clipIndex}|${start.toFixed(3)}|${end.toFixed(3)}`;
  const encoder = new TextEncoder();
  const data = encoder.encode(raw);
  const hashBuf = await crypto.subtle.digest("SHA-256", data);
  const hex = Array.from(new Uint8Array(hashBuf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return hex.slice(0, 48);
}

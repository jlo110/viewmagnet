/**
 * Studio API client — thin wrappers around /studio/* endpoints.
 *
 * Reuses the existing axios instance from lib/api.ts (so auth headers,
 * baseURL, and error handling are consistent with the rest of the app).
 */

import axios from "axios";

import { api } from "@/lib/api";

import type {
  BackgroundLoop,
  CameraCut,
  EditSession,
  EditSpec,
  PeaksResponse,
  RenderStatus,
  TrackingData,
  TrackingStatus,
  TransitionCategory,
  TransitionInstance,
  TransitionType,
} from "./types";

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export async function listSessions(): Promise<
  Array<Pick<EditSession, "id" | "clip_key" | "title" | "source_video_url" | "last_render_status" | "last_render_url" | "updated_at">>
> {
  const { data } = await api.get("/studio/sessions");
  return data;
}

export async function getSession(clipKey: string): Promise<EditSession | null> {
  try {
    const { data } = await api.get<EditSession>(`/studio/sessions/${clipKey}`);
    return data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return null;
    }
    throw err;
  }
}

export async function saveSession(
  clipKey: string,
  spec: EditSpec,
  title?: string,
  options?: {
    /** Week 10: when present, stamps the originating recommendation
     *  on the session so post-publish metrics can attribute the
     *  outcome to a specific CTA. The backend ignores the field on
     *  subsequent saves if the row already has a provenance (first-
     *  attribution-wins), so passing it on every save is safe. */
    ctaProvenance?: Record<string, unknown> | null;
  },
): Promise<EditSession> {
  const { data } = await api.put<EditSession>(`/studio/sessions/${clipKey}`, {
    spec,
    title,
    cta_provenance: options?.ctaProvenance ?? undefined,
  });
  return data;
}

export async function deleteSession(clipKey: string): Promise<void> {
  await api.delete(`/studio/sessions/${clipKey}`);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

export async function renderSession(
  clipKey: string,
  spec?: EditSpec,
  title?: string,
): Promise<RenderStatus & { session_id?: number }> {
  const { data } = await api.post<RenderStatus & { session_id?: number }>(
    "/studio/render",
    { clip_key: clipKey, spec, title },
  );
  return data;
}

export async function getRenderStatus(sessionId: number): Promise<RenderStatus> {
  const { data } = await api.get<RenderStatus>(`/studio/render/${sessionId}/status`);
  return data;
}

/** Cancel an in-flight single-clip render. Returns the
 *  post-cancellation status; throws on 409 (nothing to cancel) so the
 *  caller can show a "render already finished" toast. */
export async function cancelSessionRender(
  sessionId: number,
): Promise<RenderStatus & { session_id?: number }> {
  const { data } = await api.post<RenderStatus & { session_id?: number }>(
    `/studio/render/${sessionId}/cancel`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Audio peaks (waveform background for the source-video lane)
// ---------------------------------------------------------------------------

/**
 * Fetch pre-computed audio peaks for the timeline waveform.
 *
 * Returns `null` when the backend is still computing (HTTP 503) so callers
 * can retry without throwing. All other errors propagate.
 */
export async function getPeaks(
  clipKey: string,
  bins = 2000,
): Promise<PeaksResponse | null> {
  try {
    const { data } = await api.get<PeaksResponse>(
      `/studio/sessions/${clipKey}/peaks`,
      { params: { bins } },
    );
    return data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 503) {
      return null;
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Multi-subject tracking (Camera lane, Week 4)
// ---------------------------------------------------------------------------

/** Either a fully-loaded TrackingData (status "done") or a status-only
 *  payload (status "computing" | "idle" | "failed"). Use the `status` field
 *  to discriminate. */
export type TrackingResult =
  | ({ status: "done" } & TrackingData)
  | TrackingStatus;

/**
 * Fetch cached multi-subject tracking for a Studio session. Triggers the
 * precompute job on the backend if the cache is empty/stale — the first
 * call after opening a session will return `{ status: "computing" }` and
 * subsequent polls return the same until the worker finishes.
 *
 * Never throws on a 503 — caller's polling loop is expected to retry.
 */
export async function getTracking(
  clipKey: string,
  n = 4,
): Promise<TrackingResult> {
  try {
    const { data } = await api.get<{ status: "done" } & TrackingData>(
      `/studio/sessions/${clipKey}/tracking`,
      { params: { n } },
    );
    return data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 503) {
      const body = err.response.data as TrackingStatus | undefined;
      return body ?? { status: "computing", retry_after: 2 };
    }
    throw err;
  }
}

/** Server-side auto-switch heuristic: pick the speaking subject per
 *  transcript word window, coalesce + enforce min cut length. */
export async function postAutoSwitch(clipKey: string): Promise<CameraCut[]> {
  const { data } = await api.post<{ tracks: CameraCut[]; reasoning: string }>(
    `/studio/sessions/${clipKey}/camera/auto-switch`,
  );
  return data.tracks;
}

// ---------------------------------------------------------------------------
// Auto-zoom (Week 5) — LLM picks punch-in timestamps from the transcript
// ---------------------------------------------------------------------------

export interface AutoZoomResult {
  timestamps: number[];
  count: number;
  cached: boolean;
}

/** Ask the backend to LLM-detect punch-in zoom moments for this session.
 *  Persists the result into spec.auto_zoom.{enabled,timestamps}; the
 *  caller should re-fetch the session (or rely on the auto-save round
 *  trip) to pick up the new spec state. */
export async function detectAutoZoom(clipKey: string): Promise<AutoZoomResult> {
  const { data } = await api.post<AutoZoomResult>(
    `/studio/sessions/${clipKey}/auto-zoom`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Templates (Week 5) — one-click "Apply Template" presets
// ---------------------------------------------------------------------------

export interface TemplateInfo {
  name: string;
  description: string;
  caption_style: string;
  transition_type: string;
  auto_zoom_enabled: boolean;
}

export async function listTemplates(): Promise<TemplateInfo[]> {
  const { data } = await api.get<TemplateInfo[]>("/studio/templates");
  return data;
}

/** Apply the named template (deep-merge preset over current spec) and
 *  return the updated session row. */
export async function applyTemplate(
  clipKey: string,
  name: string,
): Promise<EditSession> {
  const { data } = await api.post<EditSession>(
    `/studio/sessions/${clipKey}/apply-template`,
    { name },
  );
  return data;
}

// ---------------------------------------------------------------------------
// B-roll (reuses existing /broll endpoints)
// ---------------------------------------------------------------------------

export type BRollMediaType = "video" | "image" | "gif";

export interface BRollSearchResult {
  id: string;
  source: "pexels" | "pixabay" | "tenor" | "giphy";
  title: string;
  duration: number;
  preview_url: string;
  download_url: string;
  thumbnail_url: string;
  quality: string;
  /** Mirrors backend ``StockClip.media_type``. Defaults to "video" for
   *  backwards compat with cached responses that don't carry the field. */
  media_type?: BRollMediaType;
}

export interface BRollSearchResponse {
  clips: BRollSearchResult[];
  available_sources: string[];
  media_type: BRollMediaType;
}

export async function searchBRoll(
  query: string,
  maxResults = 10,
  mediaType: BRollMediaType = "video",
): Promise<BRollSearchResponse> {
  const { data } = await api.post<{
    clips: BRollSearchResult[];
    available_sources?: string[];
    media_type?: BRollMediaType;
  }>("/broll/search", {
    query,
    max_results: maxResults,
    media_type: mediaType,
  });
  return {
    clips: data.clips ?? [],
    available_sources: data.available_sources ?? [],
    media_type: data.media_type ?? mediaType,
  };
}

/** Convert a still-image URL into a short MP4 the timeline can render
 *  as B-roll. Returns the cached MP4 URL (idempotent — same image +
 *  same duration returns the same URL across calls). */
export interface PromotedImage {
  download_url: string;
  duration_seconds: number;
  cached: boolean;
}

export async function promoteImageToVideo(
  imageUrl: string,
  durationSeconds = 4.0,
): Promise<PromotedImage> {
  const { data } = await api.post<PromotedImage>("/broll/promote-image", {
    image_url: imageUrl,
    duration_seconds: durationSeconds,
  });
  return data;
}

export async function suggestBRollForText(
  text: string,
  maxClips = 5,
): Promise<BRollSearchResult[]> {
  const { data } = await api.post<{ clips: BRollSearchResult[] }>(
    "/broll/suggest",
    { text, max_clips: maxClips },
  );
  return data.clips;
}

/** Bundled procedural B-roll library — works with no API key, lives at
 *  /studio/assets/broll/<id>.mp4. Used by the "Featured" tab in the
 *  B-roll panel so users can drop something onto the timeline instantly
 *  to play with transitions. */
export interface FeaturedBRollItem {
  id: string;
  label: string;
  category: string;
  description: string;
  preview_thumbnail: string;
  download_url: string;
  duration_seconds: number;
  source: "bundled";
}

export async function listFeaturedBRoll(): Promise<FeaturedBRollItem[]> {
  const { data } = await api.get<FeaturedBRollItem[]>("/studio/broll/featured");
  return data;
}

// ---------------------------------------------------------------------------
// Transitions catalog (Week 6) — 15 effects with metadata for the grid UI
// ---------------------------------------------------------------------------

export interface TransitionInfo {
  name: TransitionType;
  category: TransitionCategory;
  label: string;
  description: string;
  default_duration_ms: number;
  has_sfx: boolean;
  thumbnail: string; // filename in /transitions/, see scripts/render_transition_thumbnails.py
}

export async function listTransitions(): Promise<TransitionInfo[]> {
  const { data } = await api.get<TransitionInfo[]>("/studio/transitions");
  return data;
}

// ---------------------------------------------------------------------------
// Per-boundary transition overrides (Week 6 Phase 4)
// ---------------------------------------------------------------------------

/** Upsert a per-boundary transition by ``boundary_id``. The backend's
 *  request body matches the ``TransitionInstance`` Pydantic model. */
export async function upsertBoundaryTransition(
  clipKey: string,
  instance: TransitionInstance,
): Promise<EditSession> {
  const { data } = await api.post<EditSession>(
    `/studio/sessions/${clipKey}/boundary-transitions`,
    instance,
  );
  return data;
}

export async function deleteBoundaryTransition(
  clipKey: string,
  boundaryId: string,
): Promise<EditSession> {
  const { data } = await api.delete<EditSession>(
    `/studio/sessions/${clipKey}/boundary-transitions/${encodeURIComponent(boundaryId)}`,
  );
  return data;
}

/** Bulk-apply the current global transition to every boundary in the
 *  timeline. Used by the "Apply to all" button in the Effects panel. */
export async function applyTransitionToAllBoundaries(
  clipKey: string,
): Promise<EditSession> {
  const { data } = await api.post<EditSession>(
    `/studio/sessions/${clipKey}/boundary-transitions/apply-all`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// Background loops (Week 6 Phase 2)
// ---------------------------------------------------------------------------

export interface BackgroundCatalogEntry {
  id: string;
  category: string;
  label: string;
  preview_thumbnail: string;
  download_url: string;
  duration_seconds: number;
  attribution: string | null;
}

export async function listBackgrounds(): Promise<BackgroundCatalogEntry[]> {
  const { data } = await api.get<BackgroundCatalogEntry[]>("/studio/backgrounds");
  return data;
}

export interface BackgroundSearchResult {
  id: string;
  source: "pexels";
  label: string;
  preview_thumbnail: string;
  download_url: string;
  duration_seconds: number;
  width: number;
  height: number;
}

export async function searchBackgrounds(
  query: string,
  perPage = 12,
): Promise<BackgroundSearchResult[]> {
  const { data } = await api.post<{ results: BackgroundSearchResult[] }>(
    "/studio/backgrounds/search",
    { query, per_page: perPage },
  );
  return data.results;
}

// ---------------------------------------------------------------------------
// User brand kit (Week 6 polish) — per-user logo + colors + font that
// auto-applies to every new Studio session.
// ---------------------------------------------------------------------------

export interface UserBrandKit {
  logo_url: string | null;
  logo_position: "tl" | "tr" | "bl" | "br";
  logo_opacity: number;
  primary_color: string | null;
  accent_color: string | null;
  font_family: string | null;
  // Brand *voice* fields — auto-applied to Distribution publishes so
  // the user's stock sign-off + hashtags get merged into every cross-post
  // without retyping. See backend's BrandKitResponse for details.
  caption_signature: string | null;
  default_hashtags: string | null;
  exists: boolean;
}

export type UserBrandKitPatch = Partial<
  Omit<UserBrandKit, "exists" | "logo_url"> & { logo_url: string | null }
>;

export async function getUserBrandKit(): Promise<UserBrandKit> {
  const { data } = await api.get<UserBrandKit>("/studio/user/brand-kit");
  return data;
}

export async function saveUserBrandKit(
  patch: UserBrandKitPatch,
): Promise<UserBrandKit> {
  const { data } = await api.put<UserBrandKit>("/studio/user/brand-kit", patch);
  return data;
}

export async function uploadUserBrandLogo(file: File): Promise<UserBrandKit> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<UserBrandKit>(
    "/studio/user/brand-kit/logo",
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function deleteUserBrandLogo(): Promise<UserBrandKit> {
  const { data } = await api.delete<UserBrandKit>("/studio/user/brand-kit/logo");
  return data;
}

// ---------------------------------------------------------------------------
// Emoji suggester (Week 6) — POST .../emojis/suggest
// ---------------------------------------------------------------------------

export interface EmojiSuggestResult {
  n_suggestions: number;
  spec: EditSpec;
}

export async function suggestEmojis(
  clipKey: string,
): Promise<EmojiSuggestResult> {
  const { data } = await api.post<EmojiSuggestResult>(
    `/studio/sessions/${clipKey}/emojis/suggest`,
  );
  return data;
}

/** Re-export the spec types frontend panels need to pass to the API. */
export type { BackgroundLoop, TransitionInstance };

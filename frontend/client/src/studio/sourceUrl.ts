/**
 * Source-video URL helper for the Studio preview.
 *
 * Routes every remote http(s) source through the backend's
 * ``/studio/source-proxy`` endpoint, which lazily downloads and rewrites the
 * MP4 with its moov atom at the start ("faststart"). This is the only way
 * to guarantee Safari paints the first frame of `<video>` — Chrome and
 * Firefox tolerate moov-at-end via aggressive range requests, but Safari
 * silently shows a black frame instead.
 *
 * The proxy is a no-op for:
 *   - falsy / empty URLs
 *   - blob:/data:/file: URIs (already local)
 *   - same-origin paths (already served by us, presumed faststart)
 *
 * Server-side, the first request for a given URL triggers a download +
 * ``ffmpeg -movflags +faststart`` (a few seconds for a typical clip). All
 * subsequent requests are served straight from the on-disk cache via
 * Starlette's StaticFiles, which gives us proper HTTP Range support for
 * `<video>` seeking and scrubbing.
 */

const API_BASE = "/api";

/** URL scheme used by the AI Script-to-Project scaffold for clips
 *  that don't have real footage yet (Week 9 Connected Tools). The
 *  Studio detects these client-side so the ``<video>`` element
 *  doesn't blow up trying to load a non-URL, and the editor can
 *  surface a friendly "replace with your footage" empty state
 *  instead. Kept as a stable constant so the backend (Python) and
 *  frontend (TS) agree on the scheme prefix. */
export const PLACEHOLDER_SOURCE_SCHEME = "placeholder://";

/** True when the supplied source URL is one of our deliberate
 *  placeholders (no real footage attached yet). Used by the editor
 *  shell to suppress the video player and prompt the user to
 *  upload or paste a real source. */
const YT_HOSTS = ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"];

/** True for any YouTube watch/share URL — matches the backend's ``is_youtube_url``. */
export function isYouTubeUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  const lower = url.toLowerCase();
  return YT_HOSTS.some((h) => lower.includes(h));
}

export function isPlaceholderSource(
  rawUrl: string | null | undefined,
): boolean {
  return !!rawUrl && rawUrl.startsWith(PLACEHOLDER_SOURCE_SCHEME);
}

/**
 * Convert a raw source URL into a Safari-safe playback URL. Returns the
 * input unchanged when no proxying is needed.
 */
export function proxyVideoUrl(rawUrl: string | null | undefined): string {
  if (!rawUrl) return "";
  // Placeholder sources have no playable bytes — return an empty
  // string so the ``<video>`` element renders empty instead of
  // throwing a NetworkError trying to fetch ``placeholder://...``.
  if (isPlaceholderSource(rawUrl)) return "";
  // Already-local URIs play directly without normalization.
  if (
    rawUrl.startsWith("blob:") ||
    rawUrl.startsWith("data:") ||
    rawUrl.startsWith("file:") ||
    rawUrl.startsWith("/")
  ) {
    return rawUrl;
  }
  // Only normalize http(s) — anything else (e.g. YouTube watch URLs) the
  // user shouldn't be feeding to `<video>` directly anyway.
  if (!/^https?:\/\//i.test(rawUrl)) {
    return rawUrl;
  }
  return `${API_BASE}/studio/source-proxy?url=${encodeURIComponent(rawUrl)}`;
}

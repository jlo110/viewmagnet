/**
 * Cross-tool deep-link conventions for ViewMagnet.
 *
 * The breadth strategy only becomes a moat if the tools are *connected*.
 * Every dashboard page that accepts external context should read its
 * params using the same convention here, and every page that links *into*
 * another tool should use the builder fns below.
 *
 * Why URL params and not Wouter `location.state` / sessionStorage:
 *   - Wouter has no `location.state` API.
 *   - sessionStorage breaks shareable / deep-link URLs.
 *   - URL params survive refresh, get bookmarkable, and round-trip through
 *     redirects (e.g., the OAuth dance).
 *
 * If a target route needs a *lot* of context that wouldn't fit in a URL
 * (e.g., a 50KB transcript), the page should accept a small handoff key
 * via the URL and look up the payload from sessionStorage. We use a
 * "context bag" helper below for that case.
 */

import { computeClipKey } from "@/studio/types";

// ---------------------------------------------------------------------------
// Studio  (`/dashboard/studio/:clipKey?source=&start=&end=&title=&transcript=`)
// ---------------------------------------------------------------------------

export interface StudioDeepLinkOptions {
  /** Source video URL the Studio will load (yt-dlp / Pexels / direct MP4). */
  sourceUrl: string;
  /** Trim window into the source, in seconds. Used both for the clip-key
   *  hash and for the initial main-clip timeline window.
   *
   *  Optional because some entry points (e.g. Analyzer's "Re-edit in
   *  Studio") don't know the source duration yet — we'd be guessing. In
   *  that case both omit to ``0`` and Studio falls back to a sensible
   *  default (auto-detected from the loaded <video> element) on mount. */
  startSeconds?: number;
  endSeconds?: number;
  /** Human title shown in the Studio header — usually the originating
   *  Shorts highlight title or the video title. */
  title?: string;
  /** Optional clip index for users who edit multiple regions of the same
   *  source video; default 0 is fine for single-clip flows. */
  clipIndex?: number;
  /** sessionStorage handoff for big payloads (transcript, hooks, etc.).
   *  Stored under a stable key so the target page can fetch it once on
   *  mount and discard. */
  contextBag?: StudioContextBag | null;
  /** Week 10 shortcut: the originating tool the user clicked from
   *  ("hook_lab", "script_writer", ...). Folded into ``contextBag.cta``
   *  so call sites don't have to construct the envelope themselves.
   *  Use this whenever a "Re-edit in Studio" / "Open in Studio"
   *  button is rendered on a tool-specific recommendation. */
  cta?: {
    tool: string;
    reason?: string;
    from?: string;
    label?: string;
  };
}

/** Heavy payloads we don't want in the URL bar. The Studio reads this from
 *  sessionStorage during its first mount and clears it. */
export interface StudioContextBag {
  /** Pre-detected transcript words (Shorts → Studio handoff). Shape mirrors
   *  `TranscriptWord` in `studio/types.ts` so the Studio can drop the
   *  payload straight into `SourceClip.transcript` without remapping. */
  transcript?: Array<{ start: number; end: number; text: string }>;
  /** Hook variations from the Shorts highlight; user can drop them in
   *  as text overlays. */
  hooks?: string[];
  /** Origin tool for analytics + breadcrumbs ("shorts", "velocity", etc.). */
  origin?: string;
  /** Origin video id, useful for cross-references / analytics. */
  originVideoId?: string;
  /** Week 10: recommendation envelope captured when the user clicked a
   *  CTA elsewhere ("hook_lab", "script_writer", …). Stamped onto the
   *  EditSession on first save so post-publish metrics can attribute
   *  outcomes back to the originating recommendation. */
  cta?: {
    tool: string;
    reason?: string;
    from?: string;
    label?: string;
  };
}

const STUDIO_CONTEXT_STORAGE_KEY = "viewmagnet.studio.deeplink";
const STUDIO_CTA_PENDING_KEY = "viewmagnet.studio.pendingCta";

/** Stash a CTA envelope for a clipKey so that the next session save
 *  for that key can ship it as ``cta_provenance``. The contextBag
 *  itself is single-use (cleared on read), so we mirror just the
 *  CTA into a separate, durable-across-refresh key. The backend
 *  applies first-attribution-wins, so re-sending on subsequent
 *  saves is safe. */
export function stashPendingCta(
  clipKey: string,
  cta: NonNullable<StudioContextBag["cta"]>,
): void {
  try {
    sessionStorage.setItem(
      `${STUDIO_CTA_PENDING_KEY}.${clipKey}`,
      JSON.stringify({
        ...cta,
        captured_at: new Date().toISOString(),
      }),
    );
  } catch {
    // sessionStorage unavailable — attribution is best-effort.
  }
}

/** Read (but do NOT clear) the pending CTA for a clipKey. Callers
 *  that successfully save the session should follow up with
 *  ``clearPendingCta`` so subsequent saves don't keep shipping a
 *  stale envelope. */
export function readPendingCta(
  clipKey: string,
): NonNullable<StudioContextBag["cta"]> | null {
  try {
    const raw = sessionStorage.getItem(
      `${STUDIO_CTA_PENDING_KEY}.${clipKey}`,
    );
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.tool === "string"
    ) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

export function clearPendingCta(clipKey: string): void {
  try {
    sessionStorage.removeItem(`${STUDIO_CTA_PENDING_KEY}.${clipKey}`);
  } catch {
    // ignore
  }
}

/** Build a `/dashboard/studio/...` URL with deep-link params. Side effect:
 *  if `contextBag` is provided, stashes it in sessionStorage for the
 *  target Studio mount to pick up. Returns the URL to navigate to.
 *
 *  Async because clip-key derivation goes through SubtleCrypto SHA-256
 *  (see `computeClipKey` in `studio/types.ts`) — same hash as the
 *  backend so a refresh resumes the session from the DB. */
export async function buildStudioLink(opts: StudioDeepLinkOptions): Promise<string> {
  const start = opts.startSeconds ?? 0;
  const end = opts.endSeconds ?? 0;
  const clipKey = await computeClipKey(
    opts.sourceUrl,
    opts.clipIndex ?? 0,
    start,
    end,
  );
  // Fold the optional ``cta`` shortcut into the contextBag so the
  // Studio entry effect only has to read one place for attribution.
  // We don't overwrite an explicit ``contextBag.cta`` if the caller
  // already supplied one — that lets a richer envelope coexist with
  // the simple shortcut.
  const ctx: StudioContextBag | null =
    opts.contextBag || opts.cta
      ? {
          ...(opts.contextBag ?? {}),
          cta: opts.contextBag?.cta ?? opts.cta,
        }
      : null;
  if (ctx) {
    try {
      sessionStorage.setItem(
        `${STUDIO_CONTEXT_STORAGE_KEY}.${clipKey}`,
        JSON.stringify(ctx),
      );
    } catch {
      // sessionStorage can throw in private-browsing mode; we just lose
      // the heavy payload but the URL params still let the page hydrate.
    }
  }
  const params = new URLSearchParams();
  params.set("source", opts.sourceUrl);
  params.set("start", start.toFixed(2));
  params.set("end", end.toFixed(2));
  if (opts.title) params.set("title", opts.title);
  if (opts.clipIndex && opts.clipIndex > 0) {
    params.set("clipIndex", String(opts.clipIndex));
  }
  return `/dashboard/studio/${clipKey}?${params.toString()}`;
}

/** Parse Studio URL params + pull the matching context bag. Returns null
 *  when no deep-link params are present (i.e., resumed session or demo). */
export function readStudioDeepLink(
  clipKey: string,
  search: string = window.location.search,
): {
  sourceUrl: string;
  startSeconds: number;
  endSeconds: number;
  title?: string;
  clipIndex: number;
  context: StudioContextBag | null;
} | null {
  const params = new URLSearchParams(search);
  const source = params.get("source");
  const start = params.get("start");
  const end = params.get("end");
  if (!source || start == null || end == null) return null;

  let context: StudioContextBag | null = null;
  const storageKey = `${STUDIO_CONTEXT_STORAGE_KEY}.${clipKey}`;
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (raw) {
      context = JSON.parse(raw) as StudioContextBag;
      // Single-use: clear so a refresh of the page resumes the session
      // from the DB rather than re-seeding from the originating tool.
      sessionStorage.removeItem(storageKey);
    }
  } catch {
    context = null;
  }
  return {
    sourceUrl: source,
    startSeconds: Number(start),
    endSeconds: Number(end),
    title: params.get("title") ?? undefined,
    clipIndex: Number(params.get("clipIndex") ?? 0),
    context,
  };
}

/** Distribute a free-text transcript across a duration window as
 *  word-level entries. Used by tools that have full text but no
 *  word timings (Shorts highlight clips, manually pasted scripts)
 *  so the Studio handoff can still seed captions.
 *
 *  Approximation: each word gets ``duration / wordCount`` seconds
 *  and butts up against the next word. Not perfect, but good enough
 *  to drive the caption preview and let the user nudge timings.
 *
 *  Returns ``[]`` for empty/whitespace-only input or zero duration,
 *  matching the ``TranscriptWord[]`` empty-state Studio already
 *  handles gracefully. */
export function approximateTranscriptTimings(
  text: string | undefined | null,
  startSeconds: number,
  endSeconds: number,
): Array<{ start: number; end: number; text: string }> {
  if (!text) return [];
  const clean = text.trim();
  if (!clean) return [];
  const duration = Math.max(0, endSeconds - startSeconds);
  if (duration <= 0) return [];

  // Tokenize on whitespace; preserve punctuation glued to words so
  // captions render naturally. We don't try to split on punctuation
  // because the resulting per-word timings would be more wrong, not
  // less — Studio's caption renderer expects readable tokens.
  const words = clean.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  const perWord = duration / words.length;
  return words.map((word, i) => ({
    start: startSeconds + i * perWord,
    end: startSeconds + (i + 1) * perWord,
    text: word,
  }));
}

// ---------------------------------------------------------------------------
// Analyzer  (`/dashboard/analyzer?url=...`)
// ---------------------------------------------------------------------------

/** Deep-link into the Video Analyzer pre-filled with a YouTube URL.
 *  Used by Velocity Tracker, Smart Alerts, and any "re-analyze this video"
 *  CTA across the app. */
export function buildAnalyzerLink(youtubeUrl: string): string {
  const params = new URLSearchParams({ url: youtubeUrl, autoRun: "1" });
  return `/dashboard/analyzer?${params.toString()}`;
}

export function readAnalyzerDeepLink(
  search: string = window.location.search,
): { url: string; autoRun: boolean } | null {
  const params = new URLSearchParams(search);
  const url = params.get("url");
  if (!url) return null;
  return { url, autoRun: params.get("autoRun") === "1" };
}

// ---------------------------------------------------------------------------
// Script Writer  (`/dashboard/scripts?tab=&framework=&topic=&title=`)
// ---------------------------------------------------------------------------

/** Frameworks the Script Writer understands. Mirrors `ScriptFrameworkId`
 *  in `lib/api.ts` so deep-link callers can be type-checked. */
export type ScriptFrameworkSlug =
  | "authority_myth_buster"
  | "delta_shift"
  | "progressive_debunking"
  | "hype_heit";

export interface ScriptWriterDeepLinkOptions {
  framework?: ScriptFrameworkSlug;
  topic?: string;
  title?: string;
  /** When true, the Script Writer will auto-run generate on mount.
   *  Use sparingly — only when the upstream tool already has a confident
   *  framework recommendation (e.g., Algorithm Signals → Lead Magnet). */
  autoRun?: boolean;
}

export function buildScriptWriterLink(opts: ScriptWriterDeepLinkOptions): string {
  const params = new URLSearchParams();
  if (opts.framework) {
    params.set("tab", "frameworks");
    params.set("framework", opts.framework);
  }
  if (opts.topic) params.set("topic", opts.topic);
  if (opts.title) params.set("title", opts.title);
  if (opts.autoRun) params.set("autoRun", "1");
  return `/dashboard/scripts?${params.toString()}`;
}

export function readScriptWriterDeepLink(
  search: string = window.location.search,
): {
  tab?: "standard" | "frameworks";
  framework?: ScriptFrameworkSlug;
  topic?: string;
  title?: string;
  autoRun: boolean;
} {
  const params = new URLSearchParams(search);
  const tab = params.get("tab");
  const fw = params.get("framework");
  return {
    tab: tab === "frameworks" || tab === "standard" ? tab : undefined,
    framework: fw && /^(authority_myth_buster|delta_shift|progressive_debunking|hype_heit)$/.test(fw)
      ? (fw as ScriptFrameworkSlug)
      : undefined,
    topic: params.get("topic") ?? undefined,
    title: params.get("title") ?? undefined,
    autoRun: params.get("autoRun") === "1",
  };
}

// ---------------------------------------------------------------------------
// Algorithm Signals recommendation → tool mapping
// ---------------------------------------------------------------------------

export interface RecommendationCta {
  /** The original recommendation text (always shown). */
  label: string;
  /** When present, the recommendation renders as a button that deep-links
   *  to the relevant tool with context already filled in. */
  href?: string;
  /** Short button label, e.g. "Open Script Writer". */
  actionLabel?: string;
}

/** Backend-emitted structured CTA from /analyze's
 *  `algorithm_signals.recommendation_ctas`. Matches
 *  `RecommendationCta` in `src/features/llm_analyzer.py`. */
export interface BackendRecommendationCta {
  label: string;
  tool: string;
  href: string;
  context?: Record<string, unknown>;
}

/** Pick a button label for a structured backend CTA. The backend already
 *  ships ``label`` (the short call-to-action text); for renderers that
 *  prefer a shorter "Open X" affordance we shape it from the ``tool`` id. */
function actionLabelForTool(tool: string, fallback: string): string {
  switch (tool) {
    case "script_writer": return fallback || "Open Script Writer";
    case "hook_lab":       return "Open Hook Lab";
    case "thumbnail_generator": return "Open Thumbnails";
    case "ab_tester":      return "Open A/B Tester";
    case "loop_designer":  return "Open Loop Designer";
    case "velocity":       return "Open Velocity";
    case "writer":         return "Open AI Writer";
    default:               return fallback || "Open tool";
  }
}

/** Convert a backend structured CTA into the frontend's shape. Trivial,
 *  but kept as a function so future fields (preview thumbnails, icon
 *  hints, etc.) are added in one place. */
export function structuredCtaToFrontend(
  backend: BackendRecommendationCta,
): RecommendationCta {
  return {
    label: backend.label,
    href: backend.href,
    actionLabel: actionLabelForTool(backend.tool, backend.label),
  };
}

/** Map a free-text Algorithm-Signals or SHAP recommendation to a
 *  deep-link CTA.
 *
 *  This is the *fallback* path when the backend hasn't shipped a
 *  structured ``recommendation_ctas`` entry alongside the free text
 *  (the primary path is :func:`structuredCtaToFrontend`).
 *
 *  In practice almost every recommendation the analyzer produces is
 *  free text (the long-form SHAP and feature-driven recs in
 *  ``src/api/analyze.py::_generate_recommendations``), so this
 *  regex matcher is the only thing keeping the "Recommendations"
 *  section from being a wall of dead bullet points.
 *
 *  Matching is ordered specific → general:
 *    1. Named frameworks (Lead Magnet, Delta Shift, etc.)
 *    2. Tool-specific keywords (thumbnail, hook lab, A/B test…)
 *    3. Broad keyword fallbacks (share, promote, pacing…)
 *
 *  Anything that doesn't match still renders, just without a button.
 */
export function mapRecommendationToCta(
  text: string,
  context: { title?: string } = {},
): RecommendationCta {
  const lower = text.toLowerCase();

  // ---- 1. Named viral frameworks → Script Writer (with framework
  //         pre-selected and autoRun=1 on landing) -----------------
  //
  // We match both the public "Lead Magnet" display name AND the legacy
  // "hype/heit" terminology because older LLM responses, persisted
  // analysis blobs, and any third-party content the user might paste
  // still use the original Girbu framework label. Both route to the
  // same backend slug ``hype_heit`` so the deep link works either way.
  if (
    lower.includes("lead magnet") ||
    lower.includes("hype/heit") ||
    lower.includes("hype heit")
  ) {
    return {
      label: text,
      href: buildScriptWriterLink({
        framework: "hype_heit",
        topic: context.title,
      }),
      actionLabel: "Try Lead Magnet",
    };
  }
  if (lower.includes("myth-buster") || lower.includes("authority myth")) {
    return {
      label: text,
      href: buildScriptWriterLink({
        framework: "authority_myth_buster",
        topic: context.title,
      }),
      actionLabel: "Open Script Writer",
    };
  }
  if (lower.includes("delta shift")) {
    return {
      label: text,
      href: buildScriptWriterLink({
        framework: "delta_shift",
        topic: context.title,
      }),
      actionLabel: "Try Delta Shift",
    };
  }
  if (lower.includes("progressive debunking")) {
    return {
      label: text,
      href: buildScriptWriterLink({
        framework: "progressive_debunking",
        topic: context.title,
      }),
      actionLabel: "Try Progressive Debunking",
    };
  }

  // ---- 2. Tool-specific keyword routing -------------------------
  //
  // ORDERING NOTE: rules are checked top-to-bottom and the first
  // match wins. Order is "most specific intent first" so that
  // multi-keyword recs route to the right verb:
  //
  //   * "A/B test a new hook"  → A/B Tester (not Hook Lab)
  //   * "Boost with promotion (title & thumbnail solid)" → Distribution (not Thumbnails)
  //   * "Tweak title hook"     → Hook Lab (hook beats generic title edit)
  //
  // If you add a new rule, slot it by intent specificity, not by
  // alphabetical/file order.

  // A/B Tester — packaging variations & pre-publish testing.
  // Matched FIRST because A/B test recs almost always also contain
  // "hook" or "title" keywords that would otherwise pull them into
  // the title/hook buckets.
  if (
    lower.includes("a/b test") ||
    lower.includes("ab test") ||
    lower.includes("packaging variation") ||
    lower.includes("before publishing") ||
    /test.*(hook|title|thumbnail).*before/.test(lower) ||
    /test.*new\s+(hook|title|thumbnail)/.test(lower)
  ) {
    return {
      label: text,
      href: "/dashboard/ab-test",
      actionLabel: "Open A/B Tester",
    };
  }

  // Distribution Hub — social promotion, cross-posting. Matched
  // before Thumbnails because "title & thumbnail are solid—boost with
  // promotion" should land on Distribution, not Thumbnails.
  if (
    lower.includes("share to social") ||
    lower.includes("social media") ||
    lower.includes("instagram/twitter/tiktok") ||
    lower.includes("instagram/twitter") ||
    lower.includes("cross-post") ||
    lower.includes("post to ") ||
    lower.includes("promote this video") ||
    lower.includes("promote on social") ||
    lower.includes("boost with promotion") ||
    lower.includes("distribute")
  ) {
    return {
      label: text,
      href: "/dashboard/distribution",
      actionLabel: "Open Distribution Hub",
    };
  }

  // Shorts Creator — "Create a YouTube Short", "Short teaser".
  // Before Hook Lab because "Create a Short with your hook" should
  // route to Shorts.
  if (
    lower.includes("youtube short") ||
    lower.includes("short teaser") ||
    /(create|make).*short/.test(lower)
  ) {
    return {
      label: text,
      href: "/dashboard/shorts",
      actionLabel: "Open Shorts Creator",
    };
  }

  // Hook Lab (titles tab=hooks). Catches "hook" combined with any
  // edit verb: rewrite/score/stronger/strengthen/engineer/tweak/example.
  if (
    (lower.includes("hook") &&
      (lower.includes("rewrite") ||
        lower.includes("score") ||
        lower.includes("stronger") ||
        lower.includes("strengthen") ||
        lower.includes("engineer") ||
        lower.includes("tweak") ||
        lower.includes("example hook"))) ||
    lower.includes("hook lab")
  ) {
    return {
      label: text,
      href: "/dashboard/titles?tab=hooks",
      actionLabel: "Open Hook Lab",
    };
  }

  // Title generator (titles tab=titles). Catches "title" combined
  // with edit verbs, character-count advice (which mentions
  // characters/chars but often drops the word "title" because it's
  // already context-implied by a header), "power words", and
  // "curiosity gap" recs that don't otherwise route.
  if (
    (lower.includes("title") &&
      (lower.includes("rewrite") ||
        lower.includes("shorten") ||
        lower.includes("expand") ||
        lower.includes("compare") ||
        lower.includes("strengthen") ||
        lower.includes("phrasing") ||
        /score:?\s*\d/.test(lower))) ||
    lower.includes("power word") ||
    lower.includes("curiosity gap") ||
    lower.includes("number or question") ||
    lower.includes("emotional language") ||
    // Character-count advice — these recs come out of
    // ``_generate_recommendations`` without the word "title"
    // because they're already nested inside a "Title:" header.
    /shorten.*(character|char)/.test(lower) ||
    /expand.*(context|character|char)/.test(lower) ||
    /\d+[-–]\d+\s*char/.test(lower)
  ) {
    return {
      label: text,
      href: "/dashboard/titles",
      actionLabel: "Open Title Generator",
    };
  }

  // Thumbnail — face/brightness/saturation/contrast advice all
  // land here. Comes AFTER A/B test + Distribution + Title checks
  // so combined recs ("...title & thumbnail are weak—A/B test...")
  // route by the more actionable verb.
  if (
    lower.includes("thumbnail") ||
    lower.includes("add a face") ||
    lower.includes("reaction face") ||
    (lower.includes("brightness") && !lower.includes("title")) ||
    (lower.includes("saturation") && !lower.includes("title")) ||
    (lower.includes("contrast") && !lower.includes("title")) ||
    lower.includes("brighter")
  ) {
    return {
      label: text,
      href: "/dashboard/thumbnails",
      actionLabel: "Open Thumbnails",
    };
  }

  // Velocity / pacing / dead-air / speaking pace / WPM.
  if (
    lower.includes("pacing") ||
    lower.includes("dead air") ||
    lower.includes("speaking pace") ||
    lower.includes("pick up the") ||
    lower.includes("slow down") ||
    lower.includes("wpm") ||
    lower.includes("dead-air")
  ) {
    return {
      label: text,
      href: "/dashboard/velocity",
      actionLabel: "Open Velocity Tracker",
    };
  }

  // Loop Designer — loop endings, callbacks.
  if (
    lower.includes("loop") ||
    lower.includes("ending") ||
    lower.includes("callback") ||
    lower.includes("close the loop")
  ) {
    return {
      label: text,
      href: "/dashboard/loop-designer",
      actionLabel: "Open Loop Designer",
    };
  }

  // AI Writer — descriptions, chapters, hashtags, SEO.
  if (
    lower.includes("description") ||
    lower.includes("chapter") ||
    lower.includes("hashtag") ||
    lower.includes("seo")
  ) {
    return {
      label: text,
      href: "/dashboard/writer",
      actionLabel: "Open AI Writer",
    };
  }

  // Studio — editing-specific advice (cuts, face-on-camera timing,
  // music intro, b-roll).
  if (
    lower.includes("cuts in the first") ||
    lower.includes("show your face earlier") ||
    lower.includes("music intro") ||
    lower.includes("b-roll") ||
    lower.includes("re-edit")
  ) {
    return {
      label: text,
      href: "/dashboard/studio",
      actionLabel: "Open Studio",
    };
  }

  // Trends dashboard — trending topics / niche signals.
  if (lower.includes("trending topic") || lower.includes("trend ")) {
    return {
      label: text,
      href: "/dashboard/trends",
      actionLabel: "Open Trends",
    };
  }

  // Unmatched recs render as plain text (no CTA).
  return { label: text };
}

// ---------------------------------------------------------------------------
// Distribution  (`/dashboard/distribution?renderUrl=&title=&clipKey=`)
// ---------------------------------------------------------------------------

export interface DistributionDeepLinkOptions {
  /** R2 URL of a finished Studio render the user wants to publish. */
  renderUrl?: string;
  /** Suggested title / caption — pre-filled in the publish form. */
  title?: string;
  /** Studio clip key so Distribution can pull brand-kit context back. */
  clipKey?: string;
  /** Studio Project id (alternative to ``clipKey`` for multi-clip
   *  renders). When present, Distribution Hub fetches the project's
   *  description and brand-kit hashtags as fallback caption seeds. */
  projectId?: number;
  /** Long-form caption / post body seed. Used by the Distribution
   *  Hub when the source-tool has more text than a title (e.g. a
   *  Studio Project with a description, or an analyzer-suggested
   *  caption). */
  description?: string;
  /** Optional thumbnail URL to attach to the publish — surfaces in
   *  the Distribution Hub's media field. */
  thumbnailUrl?: string;
}

export function buildDistributionLink(opts: DistributionDeepLinkOptions): string {
  const params = new URLSearchParams();
  if (opts.renderUrl) params.set("renderUrl", opts.renderUrl);
  if (opts.title) params.set("title", opts.title);
  if (opts.clipKey) params.set("clipKey", opts.clipKey);
  if (opts.projectId != null) params.set("projectId", String(opts.projectId));
  if (opts.description) params.set("description", opts.description);
  if (opts.thumbnailUrl) params.set("thumbnailUrl", opts.thumbnailUrl);
  return `/dashboard/distribution?${params.toString()}`;
}

export function readDistributionDeepLink(
  search: string = window.location.search,
): {
  renderUrl?: string;
  title?: string;
  clipKey?: string;
  projectId?: number;
  description?: string;
  thumbnailUrl?: string;
} {
  const params = new URLSearchParams(search);
  const projectIdRaw = params.get("projectId");
  const projectId =
    projectIdRaw != null && /^\d+$/.test(projectIdRaw)
      ? Number(projectIdRaw)
      : undefined;
  return {
    renderUrl: params.get("renderUrl") ?? undefined,
    title: params.get("title") ?? undefined,
    clipKey: params.get("clipKey") ?? undefined,
    projectId,
    description: params.get("description") ?? undefined,
    thumbnailUrl: params.get("thumbnailUrl") ?? undefined,
  };
}

/**
 * ViewMagnet API Client
 *
 * Handles all communication with the FastAPI backend.
 * Uses /api prefix which Vite proxies to localhost:8000
 */

import axios, { AxiosError } from "axios";

// API base URL - configurable via environment variable
const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

// Exported so feature modules (e.g. ./studio/api.ts) can share the same
// configured axios instance + auth/refresh interceptors instead of
// duplicating the token plumbing.
export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Render-budget header relay. The backend stamps
// ``X-Render-Budget-Remaining-Minutes`` on every successful render
// enqueue (single-clip + project). We forward it as a custom DOM
// event so any mounted quota card can refresh its number without
// re-fetching ``/studio/budget`` on a timer. Value is the literal
// string the header carried (a number-as-string OR "unlimited").
export const RENDER_BUDGET_HEADER_EVENT = "viewmagnet:render-budget-header";
// Soft-cap relay (Week 8 hybrid Pro gating). Backend signals which
// reason(s) tripped the soft cap on free-plan renders that we
// still processed (e.g. ``duration_over_2min``). Frontend reads
// this and opens the upgrade modal with the ``render_softcap``
// reason so the user sees the upsell without being blocked.
export const RENDER_SOFTCAP_HEADER_EVENT = "viewmagnet:render-softcap-header";
// Queue surge relay (P3 polish). Backend stamps
// ``X-Render-Queue-Surge`` ("busy" | "slammed") + the matching
// ``X-Render-Queue-Wait-Seconds`` integer whenever an enqueue lands
// during a backed-up window. The Studio / Renders pages listen for
// this and surface a toast so the user knows their progress bar
// will sit at 0% for a bit. The header is *informational* — the
// render still queues normally; we just give the user honest
// signaling instead of letting them stare at a frozen UI.
export const RENDER_SURGE_HEADER_EVENT = "viewmagnet:render-queue-surge";
export interface RenderSurgeHeaderDetail {
  level: "busy" | "slammed";
  estimatedWaitSeconds: number;
}
api.interceptors.response.use((response) => {
  const remaining = response.headers?.["x-render-budget-remaining-minutes"];
  if (typeof remaining === "string" && remaining.length > 0) {
    try {
      window.dispatchEvent(
        new CustomEvent(RENDER_BUDGET_HEADER_EVENT, { detail: remaining }),
      );
    } catch {
      // No window (SSR / test) — header relay is a UI niceity, drop it.
    }
  }
  const softcap = response.headers?.["x-render-softcap"];
  if (typeof softcap === "string" && softcap.length > 0) {
    try {
      window.dispatchEvent(
        new CustomEvent(RENDER_SOFTCAP_HEADER_EVENT, { detail: softcap }),
      );
    } catch {
      // see above
    }
  }
  const surgeLevel = response.headers?.["x-render-queue-surge"];
  const surgeWait = response.headers?.["x-render-queue-wait-seconds"];
  if (
    (surgeLevel === "busy" || surgeLevel === "slammed") &&
    typeof surgeWait === "string"
  ) {
    const waitSeconds = Number.parseInt(surgeWait, 10);
    if (Number.isFinite(waitSeconds)) {
      try {
        window.dispatchEvent(
          new CustomEvent(RENDER_SURGE_HEADER_EVENT, {
            detail: {
              level: surgeLevel,
              estimatedWaitSeconds: waitSeconds,
            } satisfies RenderSurgeHeaderDetail,
          }),
        );
      } catch {
        // see above
      }
    }
  }
  return response;
});

// Types matching backend schemas
export interface AnalyzeRequest {
  url: string;
  channel_id?: string;
}

export interface FeatureExplanation {
  feature: string;
  value: string;
  impact: string;
  direction: "positive" | "negative" | "neutral";
  explanation?: string;
  contribution?: number;
}

export interface ActualPerformance {
  views: number;
  vs_median: number;
  view_sub_ratio: number;
  engagement?: {
    like_rate: number;
    comment_rate: number;
  };
}

export interface VelocityPrediction {
  predicted_views_day30: number;
  trajectory: string;
  percentile: number;
  confidence: number;
  views_per_hour: number;
  vs_expected: number;
  expected_at_this_point: number;
}

export interface NicheComparison {
  niche: string;
  your_score: number;
  niche_average: number;
  top_10_threshold: number;
  top_1_threshold: number;
  percentile: number;
  analysis_mode?: "prediction" | "velocity" | "evaluation";
  mode_description?: string;
  video_age_days?: number;
  actual_performance?: ActualPerformance;
  velocity_prediction?: VelocityPrediction;
}

export interface StabilityWarning {
  level: "medium" | "high";
  message: string;
  recommendation: string;
  analysis_count: number;
}

export interface AlgorithmSignals {
  start_score: number;
  keep_score: number;
  repeat_score: number;
  overall_score: number;
  bottleneck: "start" | "keep" | "repeat" | "balanced";
  bottleneck_message: string;
  recommendations: string[];
  // Backend-emitted structured CTAs that already encode the deep link
  // for each recommendation. Optional for back-compat — older analyses
  // saved before this field existed will simply omit it and the frontend
  // falls back to regex-matching ``recommendations``.
  recommendation_ctas?: Array<{
    label: string;
    tool: string;
    href: string;
    context?: Record<string, unknown>;
  }>;
}

export interface AnalyzeResponse {
  video_id: string;
  title: string;
  prediction_score: number;
  prediction_tier: string;  // mode-scoped label (see `mode`)
  title_score: number;
  thumbnail_score: number;
  channel_score?: number;
  explanations: FeatureExplanation[];
  recommendations: string[];
  niche_comparison: NicheComparison;
  // Honest framing of what this analysis actually claims
  mode?: "coaching" | "detection" | "evaluation";
  score_label?: string;
  headline?: string;
  disclaimer?: string;
  stability_warning?: StabilityWarning;
  algorithm_signals?: AlgorithmSignals;
}

export interface AnalysisHistoryItem {
  id: number;
  video_id: string;
  video_url: string;
  title: string;
  prediction_score: number;
  prediction_tier: string;
  title_score?: number;
  thumbnail_score?: number;
  channel_score?: number;
  explanations?: FeatureExplanation[];
  recommendations?: string[];
  analyzed_at: string;
}

export interface AnalysisHistoryResponse {
  analyses: AnalysisHistoryItem[];
  total: number;
}

export interface NicheBenchmark {
  metric: string;
  yours: string;
  niche: string;
  status: "good" | "neutral" | "warning";
}

export interface TitleSuggestion {
  title: string;
  score: number;
  reason: string;
}

// ============================================================
// HOOK LAB
// ============================================================

export type HookType =
  | "summary"
  | "mistake_callout"
  | "belief_destruction"
  | "authority_anchor"
  | "stake_reversal"
  | "specificity";

export interface HookScoreResponse {
  hook: string;
  overall_score: number;
  detected_type: HookType;
  type_description: string;
  belief_challenge: number;
  mistake_callout: number;
  urgency: number;
  specificity: number;
  weakest_dimension: string;
  strongest_dimension: string;
  is_summary_pattern: boolean;
  rationale: string;
}

export interface HookTypeInfo {
  value: HookType;
  description: string;
  is_strong: boolean;
}

export async function scoreHook(hook: string): Promise<HookScoreResponse> {
  const response = await api.post<HookScoreResponse>("/hooks/score", { hook });
  return response.data;
}

export async function rewriteHook(
  hook: string,
  topic: string,
  target_type?: HookType,
  count: number = 5,
): Promise<string[]> {
  const response = await api.post<{ rewrites: string[] }>("/hooks/rewrite", {
    hook,
    topic,
    target_type,
    count,
  });
  return response.data.rewrites;
}

export async function getHookTypes(): Promise<HookTypeInfo[]> {
  const response = await api.get<{ types: HookTypeInfo[] }>("/hooks/types");
  return response.data.types;
}

export interface NichePattern {
  pattern: string;
  impact: string;
  sample_size: number;
  confidence: string;
}

export interface NicheInsights {
  category: string;
  video_count: number;
  validated_phrases: NichePattern[];
  avoid_patterns: NichePattern[];
  power_words: string[];
  avg_title_length: number;
  avg_description_length: number;
}

export interface ChannelAnalytics {
  channel_name: string;
  total_views: number;
  watch_time_hours: number;
  subscribers_gained: number;
  avg_ctr: number;
  avg_view_duration: number;
  top_videos: {
    video_id: string;
    title: string;
    views: number;
    ctr: number;
    avg_duration: number;
  }[];
}

export interface VideoAnalytics {
  video_id: string;
  title: string;
  views: number;
  watch_time_minutes: number;
  avg_view_duration: number;
  avg_view_percentage: number;
  impressions: number;
  ctr: number;
  ctr_comparison: {
    vs_channel_avg: number;
    vs_niche_avg: number;
  };
  traffic_sources: Record<string, number>;
  engagement: {
    likes: number;
    comments: number;
    shares: number;
  };
}

export interface UserDashboardStats {
  avg_prediction_score: number;
  total_views_30d: number;
  videos_analyzed: number;
  analyses_remaining: number;
  /** Number of analyses consumed in the current billing period. */
  analyses_this_month?: number;
  /** Plan limit for analyses; null/undefined means unlimited. */
  analyses_limit?: number | null;
  above_baseline_pct: number;
  recent_analyses: {
    video_id: string;
    title: string;
    score: number;
    status: "above" | "below";
    views: string;
    date: string;
  }[];
  performance_trend: {
    date: string;
    score: number;
    title?: string;
  }[];
}

export interface ChannelOverview {
  channel_id: string;
  channel_name: string;
  subscriber_count: number;
  total_views: number;
  video_count: number;
  thumbnail_url?: string;
  recent_views: number;
  recent_videos: {
    video_id: string;
    title: string;
    view_count: number;
    published_at?: string;
    thumbnail_url?: string;
  }[];
  avg_views_per_video: number;
}

export interface YouTubeAuthResponse {
  auth_url: string;
  state: string;
}

export interface YouTubeConnection {
  channel_id: string;
  channel_name: string;
  subscriber_count: number;
  connected_at?: string;
  last_synced?: string;
}

// Thumbnail Generation Types
export interface ThumbnailGenerateRequest {
  title: string;
  style_description?: string;
  template?: string;
  category?: string;
  primary_color?: string;
  text_color?: string;
  include_face?: boolean;
  face_position?: string;
  text_position?: string;
  face_image_base64?: string;
  background_image_base64?: string;
  variations?: number;
}

export interface ThumbnailVariation {
  id: number;
  style: string;
  image_url: string;
  prompt_used?: string;
  template?: string;
  colors?: string[];
}

export interface ThumbnailGenerateResponse {
  success: boolean;
  variations: ThumbnailVariation[];
  generation_id: string;
  credits_used: number;
  template_used?: string;
}

// Script Writer Types
export interface ScriptGenerateRequest {
  title: string;
  style: string;
  target_length_minutes: number;
  key_points?: string[];
  tone: string;
}

export interface ScriptSection {
  name: string;
  duration: string;
  content: string;
  notes: string;
}

export interface GeneratedScript {
  title: string;
  estimated_duration: string;
  word_count: number;
  sections: ScriptSection[];
  hooks: string[];
}

// AI Writer Types
export interface AIWriterRequest {
  title: string;
  category: string;
  tone: string;
}

export interface AIWriterResponse {
  description: {
    text: string;
    word_count: number;
    has_cta: boolean;
    has_timestamps: boolean;
  };
  tags: {
    tags: string[];
    primary_tags: string[];
    secondary_tags: string[];
  };
  hooks: {
    text: string;
    style: string;
    score: number;
  }[];
}

// Animated Captions Types
export interface CaptionGenerateRequest {
  video_url?: string;
  transcript?: string;
  style: string;
  font: string;
  position: string;
  primary_color: string;
  secondary_color: string;
}

export interface CaptionSegment {
  start: number;
  end: number;
  text: string;
}

export interface GeneratedCaptions {
  srt_content: string;
  ass_content: string;
  html_preview: string;
  segments: CaptionSegment[];
  word_count: number;
  style_used: string;
}

// Shorts Creator Types
export interface ShortsHighlight {
  start_time: number;
  end_time: number;
  duration: number;
  text: string;
  score: number;
  reason: string;
  hook_type: string;
  suggested_title?: string;
}

export interface ShortsAnalysis {
  highlights: ShortsHighlight[];
  total_found: number;
  best_moment?: ShortsHighlight;
}

// Keyword Research Types
export interface KeywordResult {
  keyword: string;
  search_volume: number;
  competition: string;
  trend: string;
  difficulty: number;
  opportunity_score: number;
}

export interface KeywordResearchResponse {
  seed_keyword: string;
  keywords: KeywordResult[];
  total_found: number;
}

// Trend Analyzer Types
export interface TrendDataPoint {
  month: string;
  interest: number;
}

export interface OptimalUploadTime {
  day: string;
  time: string;
  score: number;
  reason?: string;
}

export interface TrendAnalysis {
  topic: string;
  trend_score: number;
  trend_direction: string;
  peak_interest: number;
  current_interest: number;
  seasonality?: string;
  related_topics: string[];
  timing: {
    best_time_to_post?: string;
    urgency: string;
  };
  /** Optional time-series interest data (added when backend supports it). */
  trend_data?: TrendDataPoint[];
  /** Optional pre-computed best upload windows. */
  optimal_upload_times?: OptimalUploadTime[];
}

// Competitor Analysis Types
export interface CompetitorMetric {
  metric: string;
  yours: string;
  competitor: string;
  difference: string;
  status: string;
}

export interface CompetitorReport {
  competitor: {
    name: string;
    channel_id?: string;
    subscribers?: number;
    total_views?: number;
    avg_views?: number;
  };
  your_channel?: {
    name: string;
    channel_id: string;
  };
  metrics: {
    metric: string;
    yours: string | number;
    competitor: string | number;
    difference?: string;
    winner?: string;
    insight?: string;
  }[];
  strategy_differences: {
    strategy?: string;
    area?: string;
    description?: string;
    your_approach: string;
    their_approach: string;
    recommendation?: string;
    impact?: string;
  }[];
  opportunities: {
    opportunity?: string;
    gap?: string;
    description?: string;
    potential?: string;
    competitor_does?: string;
    potential_impact?: string;
    action_item?: string;
    difficulty?: string;
  }[];
  competitor_strengths?: string[];
  your_advantages?: string[];
}

// A/B Test Types
export interface ABTestRequest {
  variation_a: string;
  variation_b: string;
  test_type: string;
  sample_size: number;
}

export interface ABTestResult {
  winner: string;  // strongest BY THE RUBRIC (not a predicted-CTR winner)
  confidence: number;  // rubric-score gap, not statistical confidence
  disclaimer?: string;
  variation_a: {
    name: string;
    value: string;
    score: number;
    strengths?: string[];
    weaknesses?: string[];
  };
  variation_b: {
    name: string;
    value: string;
    score: number;
    strengths?: string[];
    weaknesses?: string[];
  };
  recommendation: string;
  insights?: string[];
}

// Smart Alerts Types
export interface Alert {
  id: string;
  type: string;
  priority: string;
  title: string;
  message: string;
  action: string;
  action_url?: string;
  data: Record<string, unknown>;
  created_at: string;
  dismissed: boolean;
}

export interface AlertSettings {
  enabled: boolean;
  underperformance_alerts: boolean;
  optimal_time_alerts: boolean;
  competitor_alerts: boolean;
  consistency_alerts: boolean;
  trend_alerts: boolean;
  milestone_alerts: boolean;
  underperformance_threshold: number;
  consistency_days: number;
  competitor_channels: string[];
}

export interface AlertSummary {
  total: number;
  by_priority: Record<string, number>;
  by_type: Record<string, number>;
  actionable: number;
  /** Unread alert count surfaced on the sidebar badge. */
  unread?: number;
}

// Winning Formula Types
export interface TitlePattern {
  pattern: string;
  example: string;
  frequency: number;
  avg_performance: number;
  recommendation: string;
}

export interface ThumbnailPattern {
  element: string;
  frequency: number;
  impact: number;
  description: string;
}

export interface ContentPattern {
  aspect: string;
  optimal_value: string;
  current_avg: string;
  impact: number;
}

export interface WinningFormula {
  channel_name: string;
  channel_id: string;
  total_videos_analyzed: number;
  avg_views: number;
  median_views?: number;
  hit_rate: number;
  subscriber_count?: number;
  title_patterns: TitlePattern[];
  losing_patterns?: Array<{
    pattern: string;
    impact: string;
    example: string;
  }>;
  thumbnail_patterns: ThumbnailPattern[];
  content_patterns?: ContentPattern[];
  radar_data?: Array<{
    factor: string;
    hits: number;
    flops: number;
  }>;
  optimal_title_length?: [number, number];
  optimal_video_length?: [number, number];
  best_posting_times?: string[];
  top_videos?: Record<string, unknown>[];
  top_performing_videos?: Array<{
    title: string;
    views: number;
    video_id: string;
  }>;
  bottom_performing_videos?: Array<{
    title: string;
    views: number;
    video_id: string;
  }>;
  key_insights: string[];
  source?: string;
}

// API Error handling
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function handleError(error: unknown): never {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<any>;
    const data = axiosError.response?.data;
    // The API returns a unified envelope: { error: { code, message, ... } }.
    // Older/legacy paths may still send { detail: "..." }. Read both so the
    // real, actionable message reaches the UI instead of "An error occurred".
    const detail =
      data?.error?.message ||
      (typeof data?.detail === "string" ? data.detail : undefined) ||
      data?.message ||
      axiosError.message ||
      "An error occurred";
    throw new ApiError(axiosError.response?.status || 500, detail);
  }
  throw error;
}

// ============================================================
// API Functions
// ============================================================

/**
 * Health check
 */
export async function healthCheck(): Promise<{ status: string; version: string }> {
  try {
    const response = await api.get("/");
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Analyze a YouTube video. The user is resolved server-side from the JWT.
 */
export async function analyzeVideo(request: AnalyzeRequest): Promise<AnalyzeResponse> {
  try {
    const response = await api.post<AnalyzeResponse>("/analyze", request);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get user's analysis history.
 *
 * The backend now derives `user_id` from the JWT (no `?user_id=` query),
 * so we no longer accept it as an argument.
 */
export async function getAnalysisHistory(limit: number = 20): Promise<AnalysisHistoryResponse> {
  try {
    const response = await api.get<AnalysisHistoryResponse>("/analyses/history", {
      params: { limit }
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Real before/after impact summary computed by the backend from the
 * caller's analysis history. Always returns 200 — when the user
 * hasn't cleared the readiness thresholds the response carries
 * ``ready=false`` and the lists are empty, so the Impact page can
 * fall back to its sample preview without an extra round-trip.
 *
 * Shape mirrors ``ImpactSummaryResponse`` in
 * ``src/api/routers/impact.py``. Optional fields (e.g. real CTR,
 * 7-day views) are present only when populated by the outcome
 * checker, which is why the metrics list can shrink to just
 * prediction/title/thumbnail score for new accounts.
 */
export interface ImpactSummaryMetric {
  name: string;
  before: number;
  after: number;
  change: number;
  change_percent: number;
  unit: string;
  icon: string;
}

export interface ImpactSummaryVideo {
  video_id: string;
  title: string;
  used_view_magnet: boolean;
  views: number;
  engagement_rate: number;
  published_at: string | null;
  magnet_score: number | null;
}

export interface ImpactSummaryTrendPoint {
  date: string;
  before_avg: number;
  after_avg: number;
  actual: number;
}

export interface ImpactSummary {
  ready: boolean;
  video_count: number;
  days_of_history: number;
  first_analyzed_at: string | null;
  metrics: ImpactSummaryMetric[];
  videos: ImpactSummaryVideo[];
  trend: ImpactSummaryTrendPoint[];
}

// ---------------------------------------------------------------------------
// Studio multi-clip Projects (Week 7)
// ---------------------------------------------------------------------------

/** Mirror of ``src.features.studio.project_spec.ProjectClipSpec``. */
export interface StudioProjectClip {
  id: number;
  edit_session_id: number;
  position: number;
  clip_key: string;
  title: string | null;
  source_url: string;
  source_start_time: number;
  source_end_time: number;
  session_render_url: string | null;
  session_render_status: "idle" | "queued" | "rendering" | "done" | "failed";
  trim_in_seconds: number | null;
  trim_out_seconds: number | null;
  transition_in_type: string | null;
  transition_in_ms: number | null;
}

/** Mirror of ``src.features.studio.spec.BrandKit`` so the project UI
 *  can show/edit the project-level overlay independently of the
 *  user's global brand kit. */
export interface StudioProjectBrandKit {
  logo_url?: string | null;
  logo_position?: "tl" | "tr" | "bl" | "br";
  logo_opacity?: number;
  primary_color?: string | null;
  accent_color?: string | null;
  font_family?: string | null;
  default_hashtags?: string | null;
}

/** Mirror of ``src.features.studio.project_spec.ProjectSpec``. */
export interface StudioProjectSpec {
  version: number;
  id: number;
  user_id: number;
  title: string;
  /** Long-form project description. Seed caption when the project is
   *  handed off to the Distribution Hub (Week 9 Connected Tools). */
  description: string | null;
  default_aspect: "9:16" | "1:1" | "4:5" | "16:9";
  default_transition_type: string;
  default_transition_ms: number;
  brand_kit: StudioProjectBrandKit;
  last_render_status: "idle" | "queued" | "rendering" | "done" | "failed";
  last_render_url: string | null;
  last_render_error: string | null;
  render_progress: number | null;
  render_progress_message: string | null;
  clips: StudioProjectClip[];
}

export interface StudioProjectListItem {
  id: number;
  title: string;
  default_aspect: "9:16" | "1:1" | "4:5" | "16:9";
  clip_count: number;
  last_render_status: "idle" | "queued" | "rendering" | "done" | "failed";
  last_render_url: string | null;
  updated_at: string;
}

export interface StudioProjectRenderStatus {
  job_id?: string | null;
  project_id: number;
  status: "idle" | "queued" | "rendering" | "done" | "failed";
  last_render_url?: string | null;
  progress?: number | null;
  progress_message?: string | null;
}

/** Mirror of ``src.api.routers.projects.RenderQueueItem``. One row in
 *  the unified Renders queue covering both single-clip and project
 *  renders. The frontend Renders tab pairs each row with live
 *  WebSocket events (matched by ``kind + render_id``) so the list
 *  stays in sync without polling. */
export interface RenderQueueItem {
  kind: "session" | "project";
  render_id: number;
  title: string;
  status: "idle" | "queued" | "rendering" | "done" | "failed";
  progress: number | null;
  progress_message: string | null;
  download_url: string | null;
  error: string | null;
  updated_at: string;
  open_path: string;
  /** Session-only: the underlying clip key. Used by the Renders UI to
   *  fire ``POST /studio/render`` for a one-click retry that re-uses
   *  the stored spec. ``null`` for project rows. */
  clip_key: string | null;
}

export async function listUserRenders(
  limit = 50,
): Promise<RenderQueueItem[]> {
  try {
    const response = await api.get<RenderQueueItem[]>(
      `/studio/renders?limit=${limit}`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Worker queue surge snapshot (P3 polish). Mirrors
 *  ``src.api.routers.usage.QueueSurge`` — piggybacked on the budget
 *  poll so the UI can render a "queue is busier than usual" banner
 *  without a second round-trip. ``available`` is false when Redis
 *  isn't configured (dev/test); the UI hides the banner in that
 *  case. */
export interface RenderQueueSurge {
  available: boolean;
  level: "normal" | "busy" | "slammed";
  queue_depth: number;
  started: number;
  estimated_wait_seconds: number;
}

/** Current-month render-minute budget (Week 8). Mirrors
 *  ``src.api.routers.usage.RenderBudget``. ``minutes_limit`` /
 *  ``minutes_remaining`` are ``-1`` when ``unlimited`` is true (JSON
 *  can't carry Infinity); the UI keys off the boolean instead. */
export interface RenderBudget {
  plan: string;
  minutes_used: number;
  minutes_limit: number;
  minutes_remaining: number;
  percent_used: number;
  unlimited: boolean;
  month_start: string;
  surge?: RenderQueueSurge | null;
}

export async function getRenderBudget(): Promise<RenderBudget> {
  try {
    const response = await api.get<RenderBudget>("/usage/renders");
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function listStudioProjects(): Promise<StudioProjectListItem[]> {
  try {
    const response = await api.get<StudioProjectListItem[]>("/studio/projects");
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function createStudioProject(opts: {
  title?: string;
  description?: string;
  default_aspect?: StudioProjectListItem["default_aspect"];
}): Promise<StudioProjectSpec> {
  try {
    const response = await api.post<StudioProjectSpec>("/studio/projects", opts);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Section payload accepted by ``POST /scripts/to-project``. Mirrors
 *  the backend ``ScriptSectionInput``. */
export interface ScriptToProjectSection {
  name: string;
  content?: string;
  duration_seconds?: number;
}

/** Scaffold a StudioProject from a generated script. Each section
 *  becomes a placeholder clip in the project; the user replaces the
 *  placeholder source with real footage section-by-section in
 *  Studio. Week 9 Connected Tools — Script Writer → Project. */
export async function scriptToProject(opts: {
  title: string;
  sections: ScriptToProjectSection[];
  default_aspect?: StudioProjectListItem["default_aspect"];
  framework?: string;
  source_script_id?: string;
}): Promise<StudioProjectSpec> {
  try {
    const response = await api.post<StudioProjectSpec>(
      "/scripts/to-project",
      opts,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function getStudioProject(
  projectId: number,
): Promise<StudioProjectSpec> {
  try {
    const response = await api.get<StudioProjectSpec>(
      `/studio/projects/${projectId}`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function updateStudioProject(
  projectId: number,
  body: {
    title?: string;
    description?: string;
    default_aspect?: StudioProjectListItem["default_aspect"];
    default_transition_type?: string;
    default_transition_ms?: number;
    brand_kit?: StudioProjectBrandKit;
  },
): Promise<StudioProjectSpec> {
  try {
    const response = await api.patch<StudioProjectSpec>(
      `/studio/projects/${projectId}`,
      body,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function deleteStudioProject(projectId: number): Promise<void> {
  try {
    await api.delete(`/studio/projects/${projectId}`);
  } catch (error) {
    handleError(error);
  }
}

export async function appendStudioProjectClip(
  projectId: number,
  body: {
    edit_session_id: number;
    trim_in_seconds?: number;
    trim_out_seconds?: number;
    transition_in_type?: string;
    transition_in_ms?: number;
  },
): Promise<StudioProjectSpec> {
  try {
    const response = await api.post<StudioProjectSpec>(
      `/studio/projects/${projectId}/clips`,
      body,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function updateStudioProjectClip(
  projectId: number,
  clipId: number,
  body: {
    position?: number;
    trim_in_seconds?: number;
    trim_out_seconds?: number;
    transition_in_type?: string;
    transition_in_ms?: number;
  },
): Promise<StudioProjectSpec> {
  try {
    const response = await api.patch<StudioProjectSpec>(
      `/studio/projects/${projectId}/clips/${clipId}`,
      body,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function deleteStudioProjectClip(
  projectId: number,
  clipId: number,
): Promise<StudioProjectSpec> {
  try {
    const response = await api.delete<StudioProjectSpec>(
      `/studio/projects/${projectId}/clips/${clipId}`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function renderStudioProject(
  projectId: number,
): Promise<StudioProjectRenderStatus> {
  try {
    const response = await api.post<StudioProjectRenderStatus>(
      `/studio/projects/${projectId}/render`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function getStudioProjectRenderStatus(
  projectId: number,
): Promise<StudioProjectRenderStatus> {
  try {
    const response = await api.get<StudioProjectRenderStatus>(
      `/studio/projects/${projectId}/render/status`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Cancel an in-flight project render. Returns the post-cancel
 *  status snapshot; the backend marks the row ``failed`` with a
 *  ``"cancelled by user"`` error blurb and tells the worker to stop
 *  after the current ffmpeg call. */
export async function cancelStudioProjectRender(
  projectId: number,
): Promise<StudioProjectRenderStatus> {
  try {
    const response = await api.post<StudioProjectRenderStatus>(
      `/studio/projects/${projectId}/render/cancel`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// ============================================================
// ADMIN: DEAD-LETTER QUEUE
// ============================================================

/** One row in the worker DLQ. ``index`` is the row's position in
 *  the Redis list (0 = newest) so the UI can render a stable
 *  "row N" label even when re-enqueues compact the list. */
export interface DlqEntry {
  index: number;
  job_id: string | null;
  func_name: string | null;
  args: unknown[];
  kwargs: Record<string, unknown>;
  error: string | null;
  error_type: string | null;
  failed_at: string | null;
}

export interface DlqListResponse {
  entries: DlqEntry[];
  total: number;
}

export interface DlqMutationResponse {
  status: "ok" | "not_found";
  job_id: string | null;
  detail: string | null;
}

export interface DlqPruneResponse {
  dropped: number;
}

/** List the most-recent DLQ entries (admin only). 403 if the caller
 *  is not on the ``ADMIN_EMAILS`` allow-list. */
export async function listDlqEntries(limit: number = 50): Promise<DlqListResponse> {
  try {
    const response = await api.get<DlqListResponse>(`/admin/queue/dlq`, {
      params: { limit },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Re-enqueue a single DLQ entry under its original
 *  ``func_name``/``args``/``kwargs``. The DLQ row is removed only
 *  after the enqueue succeeds so a Redis blip can't lose the
 *  failure record. Returns ``{status: "ok", job_id: <new>}`` on
 *  success or ``{status: "not_found"}`` if the row was already
 *  pruned by another operator. */
export async function reenqueueDlqEntry(jobId: string): Promise<DlqMutationResponse> {
  try {
    const response = await api.post<DlqMutationResponse>(
      `/admin/queue/dlq/${jobId}/reenqueue`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Drop a DLQ entry without re-running it. */
export async function deleteDlqEntry(jobId: string): Promise<DlqMutationResponse> {
  try {
    const response = await api.delete<DlqMutationResponse>(
      `/admin/queue/dlq/${jobId}`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Drop all DLQ entries older than ``ageDays`` (default 30). */
export async function pruneDlq(ageDays: number = 30): Promise<DlqPruneResponse> {
  try {
    const response = await api.post<DlqPruneResponse>(`/admin/queue/dlq/prune`, null, {
      params: { age_days: ageDays },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// ============================================================
// ADMIN: USER & DATA MANAGEMENT
// ============================================================

/** Platform-wide stats for admin dashboard. */
export interface AdminStats {
  total_users: number;
  active_users_7d: number;
  new_users_7d: number;
  total_analyses: number;
  analyses_7d: number;
  total_renders: number;
  renders_7d: number;
  total_distribution_jobs: number;
  distribution_jobs_7d: number;
  users_by_plan: Record<string, number>;
  revenue_estimate_monthly: number;
}

/** User summary for admin user list. */
export interface AdminUserSummary {
  id: number;
  email: string;
  name: string | null;
  plan: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  last_login: string | null;
  analyses_this_month: number;
  total_analyses: number;
  total_renders: number;
  stripe_customer_id: string | null;
}

/** Detailed user info for admin. */
export interface AdminUserDetail extends AdminUserSummary {
  subscription_status: string | null;
  subscription_expires_at: string | null;
  referral_code: string | null;
  referral_bonus_analyses: number;
  youtube_connections: number;
}

/** Request body for updating a user. */
export interface AdminUserUpdate {
  plan?: string;
  is_active?: boolean;
  name?: string;
  analyses_this_month?: number;
  referral_bonus_analyses?: number;
}

/** Analysis summary for admin. */
export interface AdminAnalysisSummary {
  id: number;
  user_id: number;
  user_email: string | null;
  video_id: string;
  title: string | null;
  prediction_score: number | null;
  analyzed_at: string | null;
}

/** Render summary for admin. */
export interface AdminRenderSummary {
  id: number;
  user_id: number;
  user_email: string | null;
  render_type: string;
  status: string;
  duration_minutes: number;
  created_at: string | null;
}

/** Distribution job summary for admin. */
export interface AdminDistributionSummary {
  id: number;
  user_id: number;
  user_email: string | null;
  status: string;
  target_count: number;
  completed_count: number;
  created_at: string | null;
}

/** Project summary for admin. */
export interface AdminProjectSummary {
  id: number;
  user_id: number;
  user_email: string | null;
  title: string | null;
  clip_count: number;
  last_render_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Paginated response for admin lists. */
export interface AdminPaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** Get platform-wide admin stats. */
export async function getAdminStats(): Promise<AdminStats> {
  try {
    const response = await api.get<AdminStats>("/admin/stats");
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** List all users (admin only). */
export async function listAdminUsers(params: {
  page?: number;
  page_size?: number;
  search?: string;
  plan?: string;
}): Promise<AdminPaginatedResponse<AdminUserSummary>> {
  try {
    const response = await api.get<AdminPaginatedResponse<AdminUserSummary>>("/admin/users", {
      params,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Get detailed user info (admin only). */
export async function getAdminUser(userId: number): Promise<AdminUserDetail> {
  try {
    const response = await api.get<AdminUserDetail>(`/admin/users/${userId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Update user details (admin only). */
export async function updateAdminUser(
  userId: number,
  data: AdminUserUpdate
): Promise<{ status: string; user_id: number }> {
  try {
    const response = await api.patch(`/admin/users/${userId}`, data);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Delete user (admin only). */
export async function deleteAdminUser(
  userId: number
): Promise<{ status: string; user_id: number }> {
  try {
    const response = await api.delete(`/admin/users/${userId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** List all analyses (admin only). */
export async function listAdminAnalyses(params: {
  page?: number;
  page_size?: number;
  user_id?: number;
}): Promise<AdminPaginatedResponse<AdminAnalysisSummary>> {
  try {
    const response = await api.get<AdminPaginatedResponse<AdminAnalysisSummary>>("/admin/analyses", {
      params,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Delete analysis (admin only). */
export async function deleteAdminAnalysis(
  analysisId: number
): Promise<{ status: string; analysis_id: number }> {
  try {
    const response = await api.delete(`/admin/analyses/${analysisId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** List all renders (admin only). */
export async function listAdminRenders(params: {
  page?: number;
  page_size?: number;
  user_id?: number;
}): Promise<AdminPaginatedResponse<AdminRenderSummary>> {
  try {
    const response = await api.get<AdminPaginatedResponse<AdminRenderSummary>>("/admin/renders", {
      params,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** List all distribution jobs (admin only). */
export async function listAdminDistribution(params: {
  page?: number;
  page_size?: number;
  user_id?: number;
  status?: string;
}): Promise<AdminPaginatedResponse<AdminDistributionSummary>> {
  try {
    const response = await api.get<AdminPaginatedResponse<AdminDistributionSummary>>("/admin/distribution", {
      params,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** List all projects (admin only). */
export async function listAdminProjects(params: {
  page?: number;
  page_size?: number;
  user_id?: number;
}): Promise<AdminPaginatedResponse<AdminProjectSummary>> {
  try {
    const response = await api.get<AdminPaginatedResponse<AdminProjectSummary>>("/admin/projects", {
      params,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Delete project (admin only). */
export async function deleteAdminProject(
  projectId: number
): Promise<{ status: string; project_id: number }> {
  try {
    const response = await api.delete(`/admin/projects/${projectId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/** Grant or revoke admin access for a user. */
export async function setUserAdmin(
  userId: number,
  isAdmin: boolean
): Promise<{ status: string; user_id: number; is_admin: boolean }> {
  try {
    const response = await api.patch(`/admin/users/${userId}/set-admin`, { is_admin: isAdmin });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// ============================================================
// ADMIN: RENDER TELEMETRY (P3 polish)
// ============================================================

/** Rolled-up render funnel for the admin telemetry dashboard.
 *  Mirrors ``src.api.routers.admin_telemetry.RenderTelemetryResponse``. */
export interface RenderTelemetrySummary {
  window: {
    since: string;
    until: string;
    lookback_seconds: number;
  };
  counts: {
    queued: number;
    started: number;
    completed: number;
    failed: number;
    dlq: number;
    cancelled: number;
    budget_blocked: number;
    retried: number;
  };
  rates: {
    success_rate: number;
    failure_rate: number;
    cancel_rate: number;
  };
  wait_seconds: {
    p50: number | null;
    p95: number | null;
    samples: number;
  };
  render_seconds: {
    p50: number | null;
    p95: number | null;
    samples: number;
  };
  top_errors: Array<{ error_type: string; count: number }>;
  by_day: Array<{
    date: string;
    queued: number;
    completed: number;
    failed: number;
  }>;
}

/** Live worker queue snapshot. ``available`` is false when Redis
 *  isn't configured — the UI should hide the queue card in that
 *  case rather than show zeros. */
export interface AdminQueueSnapshot {
  available: boolean;
  level: "normal" | "busy" | "slammed";
  queue_depth: number;
  started: number;
  deferred: number;
  scheduled: number;
  estimated_wait_seconds: number;
}

export async function getRenderTelemetry(
  lookbackHours: number = 24,
  topErrors: number = 5,
): Promise<RenderTelemetrySummary> {
  try {
    const response = await api.get<RenderTelemetrySummary>(
      `/admin/telemetry/renders`,
      { params: { lookback_hours: lookbackHours, top_errors: topErrors } },
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function getAdminQueueSnapshot(): Promise<AdminQueueSnapshot> {
  try {
    const response = await api.get<AdminQueueSnapshot>(
      `/admin/telemetry/queue`,
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// ============================================================
// DISTRIBUTION OUTCOMES (Week 10 — post-publish analytics loop)
// ============================================================

/** One published-post snapshot for a fixed window (1h / 24h / 7d /
 *  30d). All metric fields are nullable because no platform exposes
 *  all of them; the UI prefers "—" to a fake zero. */
export interface PublishOutcomeSnapshot {
  window_key: string;
  sampled_at: string;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  watch_time_seconds: number | null;
  avg_view_percentage: number | null;
  click_through_rate: number | null;
}

/** Recommendation envelope captured at Studio entry. ``null`` when
 *  the user opened Studio directly. */
export interface OutcomeCtaProvenance {
  tool: string;
  reason?: string | null;
  from?: string | null;
  label?: string | null;
  captured_at?: string | null;
}

export interface PublishedOutcome {
  distribution_job_id: number;
  distribution_result_id: number;
  platform: string;
  posted_url: string | null;
  published_at: string;
  title: string;
  source_video_url: string | null;
  snapshots: Record<string, PublishOutcomeSnapshot>;
  latest: PublishOutcomeSnapshot | null;
  cta_provenance: OutcomeCtaProvenance | null;
}

/** "Did following the recommendation help?" rollup. The dashboard
 *  compares each tool group against ``tool === "baseline"``. Any
 *  field can be ``null`` when the group has zero samples with that
 *  metric — the UI renders ``—`` rather than ``0``. */
export interface RecommendationEffectivenessGroup {
  tool: string;
  label: string;
  sample_count: number;
  avg_views: number | null;
  avg_likes: number | null;
  avg_engagement_rate: number | null;
  avg_retention: number | null;
}

export interface OutcomesResponse {
  outcomes: PublishedOutcome[];
  recommendation_effectiveness: RecommendationEffectivenessGroup[];
}

export async function getDistributionOutcomes(
  limit: number = 50,
): Promise<OutcomesResponse> {
  try {
    const response = await api.get<OutcomesResponse>(
      "/distribution/outcomes",
      { params: { limit } },
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

export async function getImpactSummary(): Promise<ImpactSummary> {
  try {
    const response = await api.get<ImpactSummary>("/impact/summary");
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get a specific analysis by video ID (user resolved from JWT server-side).
 */
export async function getAnalysisByVideoId(videoId: string): Promise<AnalysisHistoryItem> {
  try {
    const response = await api.get<AnalysisHistoryItem>(`/analyses/${videoId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get niche insights/patterns
 */
export async function getNicheInsights(category: string): Promise<NicheInsights> {
  try {
    const response = await api.get<NicheInsights>(`/niche/${category}/insights`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Generate title suggestions
 */
export async function generateTitles(
  topic: string,
  niche: string,
  style?: string
): Promise<TitleSuggestion[]> {
  try {
    const response = await api.post<TitleSuggestion[]>("/titles/generate", {
      topic,
      niche,
      style,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get channel analytics (requires YouTube OAuth)
 */
export async function getChannelAnalytics(
  userId: number,
  channelId: string,
  days: number = 28
): Promise<ChannelAnalytics> {
  try {
    const response = await api.get<ChannelAnalytics>("/analytics/channel", {
      params: { user_id: userId, channel_id: channelId, days },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get video analytics (requires YouTube OAuth)
 */
export async function getVideoAnalytics(
  videoId: string,
  userId: number,
  channelId: string
): Promise<VideoAnalytics> {
  try {
    const response = await api.get<VideoAnalytics>(`/analytics/video/${videoId}`, {
      params: { user_id: userId, channel_id: channelId },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Start YouTube OAuth flow - returns URL to redirect user to.
 * User is resolved from the JWT on the server.
 */
export async function startYouTubeAuth(): Promise<YouTubeAuthResponse> {
  // OAuth callback goes directly to backend, not through Vite proxy.
  const redirectUri = `${window.location.origin.replace(/:\d+$/, ":8000")}/auth/youtube/callback`;
  const response = await api.get<YouTubeAuthResponse>("/auth/youtube", {
    params: { redirect_uri: redirectUri },
  });
  return response.data;
}

/**
 * Disconnect a connected YouTube channel.
 */
export async function disconnectYouTube(channelId: string): Promise<void> {
  await api.get("/auth/youtube/disconnect", {
    params: { channel_id: channelId },
  });
}

export interface TikTokAuthResponse {
  auth_url: string;
  state: string;
}

/**
 * Start TikTok OAuth flow — redirects user to TikTok Login Kit.
 * Returns 503 when TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET are not set.
 */
export async function startTikTokAuth(): Promise<TikTokAuthResponse> {
  const redirectUri = `${window.location.origin.replace(/:\d+$/, ":8000")}/auth/tiktok/callback`;
  const response = await api.get<TikTokAuthResponse>("/auth/tiktok", {
    params: { redirect_uri: redirectUri },
  });
  return response.data;
}

export interface InstagramAuthResponse {
  auth_url: string;
  state: string;
}

/**
 * Start Instagram Business Login OAuth flow (via Meta).
 * Returns 503 when INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET are not set.
 */
export async function startInstagramAuth(): Promise<InstagramAuthResponse> {
  const redirectUri = `${window.location.origin.replace(/:\d+$/, ":8000")}/auth/instagram/callback`;
  const response = await api.get<InstagramAuthResponse>("/auth/instagram", {
    params: { redirect_uri: redirectUri },
  });
  return response.data;
}

/**
 * Generate AI thumbnails
 */
export async function generateAIThumbnails(
  request: ThumbnailGenerateRequest
): Promise<ThumbnailGenerateResponse> {
  try {
    const response = await api.post<ThumbnailGenerateResponse>(
      "/thumbnails/generate",
      request
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Generate thumbnails from template
 */
export async function generateTemplateThumbnails(
  request: ThumbnailGenerateRequest
): Promise<ThumbnailGenerateResponse> {
  try {
    // Use the main generate endpoint with template specified
    const response = await api.post<ThumbnailGenerateResponse>(
      "/thumbnails/generate",
      request
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Generate a video script
 */
export async function generateScript(
  request: ScriptGenerateRequest
): Promise<GeneratedScript> {
  try {
    const response = await api.post<GeneratedScript>("/scripts/generate", request);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// ============================================================
// VIRAL FRAMEWORKS (Script Writer)
// ============================================================

export type ScriptFrameworkId =
  | "authority_myth_buster"
  | "delta_shift"
  | "progressive_debunking"
  | "hype_heit";

export interface FrameworkSectionSpec {
  key: string;
  label: string;
  duration: number;
}

export interface FrameworkInfo {
  id: ScriptFrameworkId;
  name: string;
  primary_goal: string;
  goal_description: string;
  sections: FrameworkSectionSpec[];
}

export interface FrameworkScriptSection {
  key: string;
  label: string;
  content: string;
  duration: number;
}

export interface FrameworkScriptResponse {
  framework: ScriptFrameworkId;
  framework_name: string;
  primary_goal: string;
  goal_description: string;
  topic: string;
  estimated_duration_sec: number;
  word_count: number;
  sections: FrameworkScriptSection[];
  full_script: string;
}

export async function listFrameworks(): Promise<FrameworkInfo[]> {
  const response = await api.get<{ frameworks: FrameworkInfo[] }>(
    "/scripts/frameworks",
  );
  return response.data.frameworks;
}

// ============================================================
// LOOP DESIGNER
// ============================================================

export interface LoopAnalysisResult {
  overall_score: number;
  text_score: number;
  visual_score: number;
  audio_score: number;
  has_stop_signals: boolean;
  stop_signals_found: string[];
  first_words: string;
  last_words: string;
  issues: string[];
  recommendations: string[];
  text_method: "embedding" | "lexical" | "none";
  visual_method: "ssim" | "histogram" | "none";
  audio_method: "rms" | "ffmpeg" | "none";
}

export async function analyzeLoop(
  transcript?: string,
  video_url?: string,
): Promise<LoopAnalysisResult> {
  const response = await api.post<LoopAnalysisResult>("/loop/analyze", {
    transcript,
    video_url,
  });
  return response.data;
}

export async function generateLoopEndings(
  opening: string,
  topic: string,
  count: number = 5,
  style: "natural" | "callback" | "question" | "cliffhanger" = "natural",
): Promise<string[]> {
  const response = await api.post<{ endings: string[] }>(
    "/loop/generate-endings",
    { opening, topic, count, style },
  );
  return response.data.endings;
}

// ============================================================
// PACING ANALYZER
// ============================================================

export interface DeadAirSegment {
  start_sec: number;
  end_sec: number;
  duration_sec: number;
}

export interface CutSuggestion {
  timestamp_sec: number;
  issue: "long_silence" | "no_visual_change" | "slow_pace" | string;
  duration_sec: number;
  recommendation: string;
}

export interface PacingReportResult {
  total_duration_sec: number;
  cut_count: number;
  avg_cut_interval_sec: number;
  longest_no_cut_sec: number;
  dead_air_segments: DeadAirSegment[];
  total_dead_air_sec: number;
  dead_air_percent: number;
  visual_pacing_score: number;
  dead_air_score: number;
  overall_score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  cut_suggestions: CutSuggestion[];
  issues: string[];
}

export async function analyzePacing(video_url: string): Promise<PacingReportResult> {
  const response = await api.post<PacingReportResult>("/pacing/analyze", {
    video_url,
  });
  return response.data;
}

// ============================================================
// DISTRIBUTION HUB
// ============================================================

export type DistributionPlatform = "youtube" | "tiktok" | "instagram" | "twitter";

export interface ConnectedAccountSummary {
  id: number;
  platform: DistributionPlatform;
  handle: string;
  display_name: string | null;
  avatar_url: string | null;
  follower_count: number | null;
  is_active: boolean;
  auto_publish: boolean;
  default_caption_variation: boolean;
  connected_at: string;
  last_used_at: string | null;
}

export interface DistributionResultSummary {
  id: number;
  account_id: number;
  platform: string;
  handle: string | null;
  status: "pending" | "running" | "success" | "failed";
  posted_url: string | null;
  posted_id: string | null;
  caption_used: string | null;
  error_message: string | null;
  completed_at: string | null;
}

export interface DistributionJobSummary {
  id: number;
  title: string;
  status: "pending" | "running" | "completed" | "failed" | "partial";
  target_count: number;
  success_count: number;
  failure_count: number;
  base_caption: string | null;
  video_url: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  results: DistributionResultSummary[];
}

export interface PlatformSetupStatus {
  name: string;
  oauth_path: string;
  docs: string;
  connected_count: number;
  accounts: ConnectedAccountSummary[];
}

export type SetupStatusResponse = Record<string, PlatformSetupStatus>;

export interface ConnectAccountInput {
  platform: DistributionPlatform;
  platform_account_id: string;
  handle: string;
  access_token: string;
  refresh_token?: string;
  display_name?: string;
  avatar_url?: string;
  follower_count?: number;
}

export async function listConnectedAccounts(
  active_only = false,
): Promise<ConnectedAccountSummary[]> {
  const response = await api.get<{ accounts: ConnectedAccountSummary[] }>(
    `/distribution/accounts${active_only ? "?active_only=true" : ""}`,
  );
  return response.data.accounts;
}

export async function connectAccount(
  input: ConnectAccountInput,
): Promise<ConnectedAccountSummary> {
  const response = await api.post<ConnectedAccountSummary>(
    "/distribution/accounts",
    input,
  );
  return response.data;
}

export async function updateConnectedAccount(
  accountId: number,
  updates: { auto_publish?: boolean; default_caption_variation?: boolean },
): Promise<ConnectedAccountSummary> {
  const response = await api.patch<ConnectedAccountSummary>(
    `/distribution/accounts/${accountId}`,
    updates,
  );
  return response.data;
}

export async function removeConnectedAccount(accountId: number): Promise<boolean> {
  const response = await api.delete<{ success: boolean }>(
    `/distribution/accounts/${accountId}`,
  );
  return response.data.success;
}

export async function getDistributionSetupStatus(): Promise<SetupStatusResponse> {
  const response = await api.get<SetupStatusResponse>("/distribution/setup-status");
  return response.data;
}

export async function listDistributionJobs(
  limit = 20,
): Promise<DistributionJobSummary[]> {
  const response = await api.get<{ jobs: DistributionJobSummary[] }>(
    `/distribution/jobs?limit=${limit}`,
  );
  return response.data.jobs;
}

export async function getDistributionJob(
  jobId: number,
): Promise<DistributionJobSummary> {
  const response = await api.get<DistributionJobSummary>(
    `/distribution/jobs/${jobId}`,
  );
  return response.data;
}

export interface DistributionPublishInput {
  title: string;
  base_caption: string;
  target_account_ids: number[];
  video_url?: string;
  source_video_url?: string;
  clip_start_sec?: number;
  clip_end_sec?: number;
  thumbnail_url?: string;
  hashtags?: string[];
  vary_captions?: boolean;
}

export async function publishDistribution(
  input: DistributionPublishInput,
): Promise<{ job_id: number; status: string; target_count: number; message: string }> {
  const response = await api.post<{
    job_id: number;
    status: string;
    target_count: number;
    message: string;
  }>("/distribution/publish", input);
  return response.data;
}

export async function generateFrameworkScript(
  topic: string,
  framework: ScriptFrameworkId,
  target_duration: number = 60,
  additional_context?: string,
): Promise<FrameworkScriptResponse> {
  const response = await api.post<FrameworkScriptResponse>(
    "/scripts/generate-framework",
    {
      topic,
      framework,
      target_duration,
      additional_context,
    },
  );
  return response.data;
}

/**
 * Generate AI content (description, tags, hooks)
 */
export async function generateAIContent(
  request: AIWriterRequest
): Promise<AIWriterResponse> {
  try {
    const response = await api.post<AIWriterResponse>("/ai-writer/generate", request);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Generate animated captions
 */
export async function generateCaptions(
  request: CaptionGenerateRequest
): Promise<GeneratedCaptions> {
  try {
    const response = await api.post<GeneratedCaptions>("/captions/generate", request);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Export video with burned-in captions
 * Returns an MP4 file as a Blob for download
 */
export async function exportCaptionedVideo(params: {
  assContent: string;
  videoUrl?: string;
  videoFile?: File;
}): Promise<Blob> {
  const formData = new FormData();
  formData.append("ass_content", params.assContent);
  
  if (params.videoUrl) {
    formData.append("video_url", params.videoUrl);
  }
  
  if (params.videoFile) {
    formData.append("video_file", params.videoFile);
  }
  
  try {
    const response = await api.post("/captions/export-video", formData, {
      responseType: "blob",
      headers: {
        "Content-Type": "multipart/form-data",
      },
      timeout: 300000, // 5 minute timeout for video processing
    });
    return response.data;
  } catch (error) {
    handleError(error);
    throw error;
  }
}

/**
 * Detect Shorts highlights
 */
/**
 * Upload a local video file as the Studio source. Returns the backend URL
 * to use as clip.source_url so the render pipeline can access it.
 */
export async function uploadSourceFile(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<{ url: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await api.post<{ url: string; filename: string }>(
    "/studio/source-upload",
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
      },
    },
  );
  return response.data;
}

export async function detectShortsHighlights(
  videoUrl?: string,
  transcript?: string,
  maxHighlights: number = 5
): Promise<ShortsAnalysis> {
  try {
    const response = await api.post<ShortsAnalysis>("/shorts/detect-highlights", {
      video_url: videoUrl,
      transcript: transcript,
      max_highlights: maxHighlights,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Extract a clip from a YouTube video
 * Returns a blob that can be downloaded
 */
export async function extractClip(
  videoUrl: string,
  startTime: number,
  endTime: number,
  format: "mp4" | "vertical" = "mp4"
): Promise<Blob> {
  try {
    const response = await api.post(
      "/shorts/extract-clip",
      {
        video_url: videoUrl,
        start_time: startTime,
        end_time: endTime,
        format: format,
      },
      {
        responseType: "blob",
        timeout: 180000, // 3 minute timeout for extraction
      }
    );
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Research keywords
 */
export async function researchKeywords(
  query: string,
  category: string = "general",
  maxResults: number = 20
): Promise<KeywordResearchResponse> {
  try {
    const response = await api.get<KeywordResearchResponse>("/keywords/research", {
      params: { query, category, max_results: maxResults },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Analyze trends for a topic
 */
export async function analyzeTrends(
  topic: string,
  category: string = "general"
): Promise<TrendAnalysis> {
  try {
    const response = await api.get<TrendAnalysis>("/trends/analyze", {
      params: { topic, category },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

// Topic Momentum (2.1) — GET /trends/momentum. Which topics are heating up
// right now from our own breakout feed (market timing, not a packaging predictor).
export interface TopicMomentumItem {
  label: string;
  topic_size: number;
  breakout_count: number;
  breakout_rate: number;
  channel_count: number;
  total_views: number;
  trend: "new" | "rising" | "peaking" | "fading" | "steady";
  prev_breakout_rate: number | null;
  example_titles: string[];
}

export interface TopicMomentumResponse {
  computed_at: string | null;
  topics: TopicMomentumItem[];
}

export async function getTopicMomentum(limit = 12): Promise<TopicMomentumResponse> {
  const res = await api.get<TopicMomentumResponse>("/trends/momentum", { params: { limit } });
  return res.data;
}

/**
 * Analyze a competitor channel
 */
export async function analyzeCompetitor(
  channelUrl: string,
  yourChannelId?: string
): Promise<CompetitorReport> {
  try {
    const response = await api.post<CompetitorReport>("/competitors/analyze", null, {
      params: { channel_url: channelUrl, your_channel_id: yourChannelId },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Simulate an A/B test
 */
export async function simulateABTest(
  request: ABTestRequest
): Promise<ABTestResult> {
  try {
    const response = await api.post<ABTestResult>("/ab-test/simulate", request);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get smart alerts for a channel. User is resolved server-side from JWT.
 */
export async function getAlerts(channelId: string): Promise<Alert[]> {
  try {
    const response = await api.get<Alert[]>("/alerts", {
      params: { channel_id: channelId },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Update alert settings for the current user.
 */
export async function updateAlertSettings(
  settings: Partial<AlertSettings>
): Promise<{ status: string }> {
  try {
    const response = await api.post("/alerts/settings", settings);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Dismiss an alert (current user resolved server-side).
 */
export async function dismissAlert(alertId: string): Promise<{ status: string }> {
  try {
    const response = await api.post(`/alerts/${alertId}/dismiss`, null);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get alert summary for a channel (current user resolved server-side).
 */
export async function getAlertSummary(channelId: string): Promise<AlertSummary> {
  try {
    const response = await api.get<AlertSummary>("/alerts/summary", {
      params: { channel_id: channelId },
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get winning formula for a channel
 */
export async function getWinningFormula(channelId: string): Promise<WinningFormula> {
  try {
    const response = await api.get<WinningFormula>(`/winning-formula/${channelId}`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Compare channel engagement
 */
export async function compareEngagement(
  channelId: string,
  videoId?: string
): Promise<{
  views: { current: number; baseline: number; vs_baseline: number };
  likes: { current_ratio: number; baseline_ratio: number; vs_baseline: number };
  comments: { current_ratio: number; baseline_ratio: number; vs_baseline: number };
  performance_tier: string;
}> {
  try {
    const response = await api.get(`/winning-formula/${channelId}/engagement`, {
      params: videoId ? { video_id: videoId } : undefined,
    });
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get dashboard stats for the authenticated user (resolved server-side from JWT).
 */
export async function getDashboardStats(): Promise<UserDashboardStats> {
  try {
    const response = await api.get<UserDashboardStats>(`/dashboard/stats`);
    return response.data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get channel overview stats from a channel URL or ID
 */
export async function getChannelOverview(channelUrl: string): Promise<ChannelOverview> {
  const response = await api.get<ChannelOverview>(`/channel/overview`, {
    params: { channel_url: channelUrl },
  });
  return response.data;
}

/**
 * Get the current user's connected YouTube channels (resolved server-side from JWT).
 */
export async function getYouTubeConnections(): Promise<{ connections: YouTubeConnection[] }> {
  const response = await api.get<{ connections: YouTubeConnection[] }>(`/auth/youtube/connections`);
  return response.data;
}

// ============================================================
// VELOCITY MONITORING
// ============================================================

export interface VelocityMonitorResponse {
  status: string;
  channel_id: string;
  channel_name?: string;
  subscriber_count?: number;
  video_added?: {
    video_id: string;
    title: string;
  };
  error?: string;
}

export interface TrackedVideo {
  video_id: string;
  title: string;
  channel_id: string;
  channel_name: string;
  published_at: string;
  age_hours: number;
  current_checkpoint: string;
  current_views: number;
  magnet_score: number | null;  // Magnet Score (0-100) if analyzed
  predictions: { [key: string]: number };  // {timeframe: views} e.g., {"3d": 5000, "7d": 10000, ...}
  actuals: { [key: string]: number };  // {timeframe: views} for completed timeframes
  predicted_30d: number | null;  // Backward compat
  actual_30d: number | null;
  accuracy: number | null;
  trajectory: "above" | "on_track" | "below";
  snapshots: { checkpoint: string; views: number }[];
}

export interface TrackedChannel {
  channel_id: string;
  channel_name: string;
  subscriber_count: number;
  videos_tracked: number;
  added_at: string | null;
  avg_accuracy: number | null;
  growth_pattern: number | null;
}

export interface VideoPrediction {
  video_id: string;
  title: string;
  channel_id: string;
  channel_name: string;
  published_at: string;
  hours_since_publish: number;
  current_checkpoint: string;
  current_views: number;
  predictions: {
    "3d": number | null;
    "7d": number | null;
    "14d": number | null;
    "30d": number | null;
  };
  actuals: {
    "3d": number | null;
    "7d": number | null;
    "14d": number | null;
    "30d": number | null;
  };
  accuracy: {
    "3d": number | null;
    "7d": number | null;
    "14d": number | null;
    "30d": number | null;
  };
  channel_growth_pattern: number | null;
  snapshots: { checkpoint: string; views: number }[];
}

/**
 * Add a video or channel to velocity monitoring
 */
export async function addToVelocityMonitor(url: string): Promise<VelocityMonitorResponse> {
  const response = await api.post<VelocityMonitorResponse>("/velocity/monitor", { url });
  return response.data;
}

/**
 * Get all tracked channels
 */
export async function getTrackedChannels(): Promise<{ channels: TrackedChannel[] }> {
  const response = await api.get<{ channels: TrackedChannel[] }>("/velocity/channels");
  return response.data;
}

/**
 * Get all tracked videos
 */
export async function getTrackedVideos(options?: {
  channelId?: string;
  activeOnly?: boolean;
}): Promise<{ videos: TrackedVideo[] }> {
  const response = await api.get<{ videos: TrackedVideo[] }>("/velocity/videos", {
    params: {
      channel_id: options?.channelId,
      active_only: options?.activeOnly ?? true,
    },
  });
  return response.data;
}

/**
 * Get detailed prediction for a specific video
 */
export async function getVideoPrediction(videoId: string): Promise<VideoPrediction> {
  const response = await api.get<VideoPrediction>(`/velocity/video/${videoId}`);
  return response.data;
}

/**
 * Get overall velocity accuracy report
 */
export async function getVelocityAccuracy(): Promise<{
  total_complete_videos: number;
  [key: string]: unknown;
}> {
  const response = await api.get("/velocity/accuracy");
  return response.data;
}

// ============================================================
// AUTHENTICATION
// ============================================================

export interface User {
  id: number;
  email: string;
  name: string | null;
  plan: string;
  avatar_url: string | null;
  is_verified?: boolean;
  referral_code?: string;
  referral_count?: number;
  referral_bonus_analyses?: number;
  is_admin?: boolean;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface SignupRequest {
  email: string;
  password: string;
  name?: string;
  referral_code?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

const TOKEN_KEY = "ViewMagnet_access_token";
const REFRESH_KEY = "ViewMagnet_refresh_token";
const USER_KEY = "ViewMagnet_user";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  const userStr = localStorage.getItem(USER_KEY);
  return userStr ? JSON.parse(userStr) : null;
}

export function storeAuth(response: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, response.access_token);
  localStorage.setItem(REFRESH_KEY, response.refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify(response.user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function signup(data: SignupRequest): Promise<AuthResponse> {
  const response = await api.post<AuthResponse>("/auth/signup", data);
  storeAuth(response.data);
  return response.data;
}

export async function login(data: LoginRequest): Promise<AuthResponse> {
  const response = await api.post<AuthResponse>("/auth/login", data);
  storeAuth(response.data);
  return response.data;
}

// Module-level in-flight refresh promise. The page-load flood of Studio
// requests (sessions / tracking / templates / transitions / backgrounds /
// peaks fire in parallel) used to trigger one independent /auth/refresh
// call per request. The backend rate-limiter would 429 some of them, and
// the 429 catch-block would call clearAuth() — wiping the FRESH token the
// OTHER concurrent refresh just wrote to localStorage. Result: all
// subsequent requests 401 forever with no recovery.
//
// Coalescing all concurrent callers onto the same promise means we hit
// /auth/refresh exactly once per token-expiry event regardless of how
// many requests are in flight.
let _refreshInflight: Promise<AuthResponse | null> | null = null;

export async function refreshToken(): Promise<AuthResponse | null> {
  if (_refreshInflight) return _refreshInflight;

  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return null;

  _refreshInflight = (async () => {
    try {
      // IMPORTANT: bypass the request interceptor's stale Authorization
      // header (the access token is what just expired). The refresh
      // endpoint authenticates the user from the body, not the header.
      const response = await axios.post<AuthResponse>(
        `${API_BASE_URL}/auth/refresh`,
        { refresh_token: refresh },
      );
    storeAuth(response.data);
    return response.data;
    } catch (err) {
      // Only treat HARD failures as "refresh dead" — a 429 just means
      // we hit the rate limit and should leave the existing token
      // intact (a sibling call may have already refreshed it, or the
      // user can retry in a moment). Distinguishing 429 vs. real 401
      // here is what kept clobbering the freshly-written token.
      const status = (err as AxiosError | undefined)?.response?.status;
      if (status === 429) {
        // Re-read whatever the most-recent successful refresh wrote so
        // queued callers still get a usable token.
        const token = localStorage.getItem(TOKEN_KEY);
        const userStr = localStorage.getItem(USER_KEY);
        const refreshNow = localStorage.getItem(REFRESH_KEY);
        if (token && refreshNow && userStr) {
          return {
            access_token: token,
            refresh_token: refreshNow,
            token_type: "bearer",
            user: JSON.parse(userStr),
          } as AuthResponse;
        }
        return null;
      }
      // Real auth failure (401/403/invalid refresh token) → tear down
      // the session so the AuthContext can route the user back to
      // /login instead of leaving them on a forever-401 page.
    clearAuth();
    return null;
    } finally {
      _refreshInflight = null;
  }
  })();

  return _refreshInflight;
}

export async function getCurrentUser(): Promise<User | null> {
  const token = getStoredToken();
  if (!token) return null;
  
  try {
    const response = await api.get<User>("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.data;
  } catch {
    return null;
  }
}

export function logout(): void {
  clearAuth();
  window.location.href = "/login";
}

// ============================================================
// AUTH — email verification, password reset, account deletion
// ============================================================

export async function verifyEmail(token: string): Promise<{ success: boolean; message: string }> {
  const response = await api.post("/auth/verify-email", { token });
  return response.data;
}

export async function resendVerification(): Promise<{ success: boolean; message: string }> {
  const response = await api.post("/auth/resend-verification");
  return response.data;
}

export async function forgotPassword(email: string): Promise<{ success: boolean; message: string }> {
  const response = await api.post("/auth/forgot-password", { email });
  return response.data;
}

export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ success: boolean; message: string }> {
  const response = await api.post("/auth/reset-password", {
    token,
    new_password: newPassword,
  });
  return response.data;
}

export async function deleteAccount(password?: string): Promise<{ success: boolean; message: string }> {
  const response = await api.delete("/auth/me", {
    data: { password },
  });
  return response.data;
}

// ============================================================
// BILLING (Stripe subscriptions)
// ============================================================

export interface SubscriptionInfo {
  plan: string;
  plan_display: string;
  status: string | null;
  expires_at: string | null;
  price_cents: number;
  cancel_at_period_end: boolean;
  has_stripe_customer: boolean;
  analyses_per_month: number;
  analyses_used_this_month: number;
}

/** Start a Stripe Checkout for a paid plan. Returns the hosted URL to redirect to. */
export async function createCheckout(plan: string): Promise<string> {
  const response = await api.post<{ checkout_url: string }>("/billing/checkout", { plan });
  return response.data.checkout_url;
}

/** Open the Stripe Customer Portal. Returns the hosted URL to redirect to. */
export async function openBillingPortal(): Promise<string> {
  const response = await api.post<{ portal_url: string }>("/billing/portal");
  return response.data.portal_url;
}

export async function getSubscription(): Promise<SubscriptionInfo> {
  const response = await api.get<SubscriptionInfo>("/billing/subscription");
  return response.data;
}

// ============================================================
// DEMO / TEST AUTH (development only)
// ============================================================

/**
 * Fixed demo credentials used by the landing page CTAs in dev/local
 * environments so a click on "Get Started Free" / "Start Free Trial"
 * lands the user inside the dashboard, already authenticated, without
 * any forms. This is gated server-side by ENVIRONMENT != production
 * via the regular signup flow (no special backend route needed) and
 * client-side by `import.meta.env.DEV`.
 */
export const DEMO_EMAIL = "demo@viewmagnet.dev";
export const DEMO_PASSWORD = "DemoUser2026!";
export const DEMO_NAME = "Demo Creator";

export function isDemoLoginEnabled(): boolean {
  // Vite injects DEV=true for `vite dev`; production builds set DEV=false.
  // Allow override via VITE_ENABLE_DEMO_LOGIN for staging-style envs.
  const flag = (import.meta.env as Record<string, string | undefined>).VITE_ENABLE_DEMO_LOGIN;
  if (flag === "1" || flag === "true") return true;
  if (flag === "0" || flag === "false") return false;
  return Boolean(import.meta.env.DEV);
}

/**
 * Logs the user into a shared demo account, creating it on first use.
 * Returns the AuthResponse with stored tokens, or throws if the demo
 * flow is not available (e.g. production build).
 */
export async function loginAsDemo(): Promise<AuthResponse> {
  if (!isDemoLoginEnabled()) {
    throw new Error("Demo login is disabled in this environment");
  }

  // Try the existing account first; this is the common case.
  try {
    return await login({ email: DEMO_EMAIL, password: DEMO_PASSWORD });
  } catch (err) {
    const status = (err as AxiosError | undefined)?.response?.status;
    // 5xx is fatal — server is broken, no point falling through.
    // 4xx (including 401/404/422) → assume the account doesn't exist
    // yet and try signup. The signup error (if any) will surface below.
    if (status && status >= 500) throw err;
  }

  try {
    return await signup({ email: DEMO_EMAIL, password: DEMO_PASSWORD, name: DEMO_NAME });
  } catch (err) {
    // Race: another tab created the account between our login and signup
    // attempts (signup returns 400 "Email already registered").
    const status = (err as AxiosError | undefined)?.response?.status;
    if (status === 400) {
      return await login({ email: DEMO_EMAIL, password: DEMO_PASSWORD });
    }
    throw err;
  }
}

// ============================================================
// REFERRAL SYSTEM
// ============================================================

export interface ReferralStats {
  referral_code: string;
  referral_link: string;
  referral_count: number;
  bonus_analyses_earned: number;
}

export async function getReferralCode(): Promise<{ referral_code: string; referral_link: string }> {
  const response = await api.get("/auth/referral-code");
  return response.data;
}

export async function getReferralStats(): Promise<ReferralStats> {
  const response = await api.get<ReferralStats>("/auth/referral-stats");
  return response.data;
}

// ============================================================
// PERSONAL ACCESS TOKENS (Personal API tokens for the MCP server,
// CI scripts, and anything else that wants to call ViewMagnet on
// behalf of a user without holding their password.)
// ============================================================

export interface PatScope {
  id: "read" | "write" | "admin";
  label: string;
  description: string;
}

/** Canonical scope catalog mirrored from the backend's
 * `VALID_SCOPES` constant. Kept here so the create-token dialog can
 * render checkboxes without a network round-trip. */
export const PAT_SCOPES: PatScope[] = [
  {
    id: "read",
    label: "Read",
    description:
      "Call analysis & lookup tools (analyze video, list frameworks, get outcomes).",
  },
  {
    id: "write",
    label: "Write",
    description:
      "Generate scripts, score hooks, detect highlights — anything that produces new content.",
  },
  {
    id: "admin",
    label: "Admin",
    description:
      "Manage other tokens. Only use for token-rotation automation.",
  },
];

export interface PersonalAccessToken {
  id: number;
  name: string;
  /** Searchable prefix (e.g. `vm_pat_a1b2c3d4`). Safe to display. */
  prefix: string;
  scopes: ("read" | "write" | "admin")[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

/** The create response shape. ``token`` is the full plaintext PAT and
 * is ONLY ever returned here — once. The dashboard surfaces it in a
 * "copy now, you won't see it again" panel. */
export interface PersonalAccessTokenWithSecret extends PersonalAccessToken {
  token: string;
}

export interface CreatePersonalAccessTokenRequest {
  name: string;
  scopes?: ("read" | "write" | "admin")[];
  /** 1 ≤ N ≤ 1825. Omit for a never-expiring token. */
  expires_in_days?: number;
}

export async function listPersonalAccessTokens(): Promise<PersonalAccessToken[]> {
  const response = await api.get<PersonalAccessToken[]>("/auth/tokens");
  return response.data;
}

export async function createPersonalAccessToken(
  body: CreatePersonalAccessTokenRequest,
): Promise<PersonalAccessTokenWithSecret> {
  const response = await api.post<PersonalAccessTokenWithSecret>(
    "/auth/tokens",
    body,
  );
  return response.data;
}

export async function revokePersonalAccessToken(tokenId: number): Promise<void> {
  await api.delete(`/auth/tokens/${tokenId}`);
}

/**
 * DEV MODE: Set up a mock user profile for testing UI without backend auth
 * Call this from browser console: window.setupMockUser()
 */
export function setupMockUser(): void {
  const mockUser: User = {
    id: 1,
    email: "demo@viewmagnet.io",
    name: "Demo User",
    plan: "pro",
    avatar_url: null,
  };
  
  const mockAuth: AuthResponse = {
    access_token: "mock-token-for-testing-12345",
    refresh_token: "mock-refresh-token-67890",
    token_type: "bearer",
    user: mockUser,
  };
  
  storeAuth(mockAuth);
  console.log("✅ Mock user set up! Refresh the page to access dashboard.");
  console.log("   Email:", mockUser.email);
  console.log("   Plan:", mockUser.plan);
}

// Expose to window for console access in dev mode
if (typeof window !== "undefined") {
  (window as unknown as { setupMockUser: typeof setupMockUser }).setupMockUser = setupMockUser;
}

// ============================================================
// HOOK TEXT OVERLAYS
// ============================================================

export interface HookPreviewRequest {
  text: string;
  position?: "top" | "center" | "bottom";
  font_scale?: number;
  target_width?: number;
}

/**
 * Preview a hook overlay image
 */
export async function previewHook(request: HookPreviewRequest): Promise<Blob> {
  const response = await api.post("/hooks/preview", request, {
    responseType: "blob",
  });
  return response.data;
}

/**
 * Apply hook overlay to a video
 */
export async function applyHookToVideo(
  text: string,
  position: string,
  fontScale: number,
  videoUrl?: string,
  videoFile?: File,
  duration?: number
): Promise<Blob> {
  const formData = new FormData();
  formData.append("text", text);
  formData.append("position", position);
  formData.append("font_scale", fontScale.toString());
  
  if (videoUrl) {
    formData.append("video_url", videoUrl);
  }
  if (videoFile) {
    formData.append("video_file", videoFile);
  }
  if (duration !== undefined) {
    formData.append("duration", duration.toString());
  }
  
  const response = await api.post("/hooks/apply", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    responseType: "blob",
    timeout: 180000, // 3 min timeout
  });
  return response.data;
}

// ============================================================
// AI VIDEO EFFECTS
// ============================================================

export interface VideoEffectsAnalyzeRequest {
  transcript: string;
  duration: number;
  fps?: number;
  width?: number;
  height?: number;
  intensity?: "subtle" | "medium" | "dramatic";
}

export interface EffectSegment {
  start_sec: number;
  end_sec: number;
  zoom: number;
  zoom_center_x: number;
  zoom_center_y: number;
  brightness: number;
  contrast: number;
  saturate: number;
  description: string;
}

export interface VideoEffectsAnalyzeResponse {
  segments: EffectSegment[];
  filter_string: string;
  intensity: string;
  segment_count: number;
}

/**
 * Analyze video and generate AI effects
 */
export async function analyzeVideoEffects(
  request: VideoEffectsAnalyzeRequest
): Promise<VideoEffectsAnalyzeResponse> {
  const response = await api.post<VideoEffectsAnalyzeResponse>("/effects/analyze", request);
  return response.data;
}

/**
 * Apply effects filter to video
 */
export async function applyVideoEffects(
  filterString: string,
  videoUrl?: string,
  videoFile?: File
): Promise<Blob> {
  const formData = new FormData();
  formData.append("filter_string", filterString);
  
  if (videoUrl) {
    formData.append("video_url", videoUrl);
  }
  if (videoFile) {
    formData.append("video_file", videoFile);
  }
  
  const response = await api.post("/effects/apply", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    responseType: "blob",
    timeout: 300000, // 5 min timeout
  });
  return response.data;
}

// ============================================================
// VOICE DUBBING
// ============================================================

export interface DubbingLanguage {
  code: string;
  name: string;
}

export interface DubbingStatus {
  dubbing_id: string;
  status: "pending" | "dubbing" | "dubbed" | "failed";
  target_language: string;
  source_language?: string;
  expected_duration_sec?: number;
  error?: string;
}

/**
 * Get supported dubbing languages
 */
export async function getDubbingLanguages(): Promise<{
  languages: DubbingLanguage[];
  count: number;
}> {
  const response = await api.get("/dubbing/languages");
  return response.data;
}

/**
 * Start a dubbing job
 */
export async function startDubbingJob(
  targetLanguage: string,
  videoUrl?: string,
  videoFile?: File,
  sourceLanguage?: string
): Promise<DubbingStatus> {
  const formData = new FormData();
  formData.append("target_language", targetLanguage);
  
  if (sourceLanguage) {
    formData.append("source_language", sourceLanguage);
  }
  if (videoUrl) {
    formData.append("video_url", videoUrl);
  }
  if (videoFile) {
    formData.append("video_file", videoFile);
  }
  
  const response = await api.post<DubbingStatus>("/dubbing/translate", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 180000, // 3 min timeout for upload
  });
  return response.data;
}

/**
 * Check dubbing job status
 */
export async function checkDubbingStatus(dubbingId: string): Promise<DubbingStatus> {
  const response = await api.get<DubbingStatus>(`/dubbing/status/${dubbingId}`);
  return response.data;
}

/**
 * Download dubbed video
 */
export async function downloadDubbedVideo(dubbingId: string): Promise<Blob> {
  const response = await api.get(`/dubbing/download/${dubbingId}`, {
    responseType: "blob",
    timeout: 180000, // 3 min timeout
  });
  return response.data;
}

// ============================================================
// YOUTUBE DESCRIPTION GENERATOR
// ============================================================

export interface DescriptionGenerateRequest {
  title: string;
  transcript?: string;
  transcript_segments?: Array<{ start: number; end: number; text: string }>;
  language?: string;
  video_duration?: number;
  include_chapters?: boolean;
  include_hashtags?: boolean;
}

export interface DescriptionChapter {
  timestamp: string;
  title: string;
  start_seconds: number;
}

export interface GeneratedDescription {
  description: string;
  chapters: DescriptionChapter[];
  hashtags: string[];
  summary: string;
  language: string;
}

/**
 * Generate YouTube description with chapters and hashtags
 */
export async function generateYouTubeDescription(
  request: DescriptionGenerateRequest
): Promise<GeneratedDescription> {
  const response = await api.post<GeneratedDescription>("/descriptions/generate", request);
  return response.data;
}

// Add auth header interceptor
api.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Add response interceptor for token refresh.
//
// The flow is intentionally narrow: on a 401 from a normal endpoint we
// try ONE refresh + ONE retry. We never recurse into the interceptor
// from /auth/refresh itself (would deadlock), and a failed refresh
// kicks the user back to /login (an interceptor that silently rejects
// leaves the Studio page hung on permanent 401s with no UX clue).
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config;
    const url = originalRequest?.url || "";
    const isAuthEndpoint =
      url.includes("/auth/refresh") ||
      url.includes("/auth/login") ||
      url.includes("/auth/signup");

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest.headers["X-Retry"] &&
      !isAuthEndpoint
    ) {
      const refreshed = await refreshToken();
      
      if (refreshed) {
        originalRequest.headers["X-Retry"] = "true";
        originalRequest.headers.Authorization = `Bearer ${refreshed.access_token}`;
        return api(originalRequest);
      }

      // Refresh failed for real (not just rate-limited). The session is
      // dead — bounce the user to /login so the AuthContext can re-init
      // cleanly instead of leaving every Studio fetch silently 401'ing.
      // We avoid logout() here on auth-endpoint failures so the login
      // form can show its own error message.
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        clearAuth();
        window.location.href = "/login";
      }
    }
    
    return Promise.reject(error);
  }
);

export default api;

// ============================================================
// VOICEOVER
// ============================================================

export interface VoiceInfo {
  voice_id: string;
  name: string;
  category: string;
  description?: string;
}

export async function getVoiceoverVoices(): Promise<VoiceInfo[]> {
  const response = await api.get<{ voices: VoiceInfo[] }>("/voiceover/voices");
  return response.data.voices;
}

export async function generateVoiceover(payload: {
  text: string;
  voice_id: string;
  stability: number;
  similarity_boost: number;
}): Promise<Blob> {
  const response = await api.post("/voiceover/generate", payload, {
    responseType: "blob",
    timeout: 120_000,
  });
  return response.data;
}

// ============================================================
// FACELESS GENERATOR
// ============================================================

export interface FacelessScriptSection {
  name: string;
  content: string;
  duration_seconds: number;
  start_time: number;
  end_time: number;
}

export interface FacelessParseResponse {
  sections: FacelessScriptSection[];
  estimated_total_seconds: number;
  word_count: number;
}

export interface FacelessProjectOut {
  project_id: string;
  title: string;
  status: string;
  sections: FacelessScriptSection[];
  estimated_duration_seconds: number;
  voice_id: string;
  caption_style: string;
  output_path?: string;
}

export async function parseFacelessScript(script: string): Promise<FacelessParseResponse> {
  const response = await api.post<FacelessParseResponse>("/faceless/parse-script", { script });
  return response.data;
}

export async function generateFacelessVideo(payload: {
  title: string;
  script: string;
  voice_id: string;
  caption_style: string;
  include_broll: boolean;
}): Promise<FacelessProjectOut> {
  const response = await api.post<FacelessProjectOut>("/faceless/generate", payload, {
    timeout: 600_000, // 10 min — this is a long pipeline
  });
  return response.data;
}

// ===========================================================================
// Candidate Ranker (TODO #9 / plan 6.4) — POST /rank/candidates
// Rank 2-4 title(+thumbnail) candidates for one video: reach-model scores +
// the MrBeast packaging rubric per title, blended into a winner.
// ===========================================================================
export interface RankCandidate {
  index: number;
  title: string;
  rank: number;
  rank_score: number;
  reach_score: number | null;
  has_thumbnail: boolean;
  rubric_score: number | null;
  packaging: {
    overall_score: number | null;
    under_50_chars: boolean;
    biggest_weakness: string;
    principles: Record<string, { score: number; note: string } | null>;
  };
}

export interface RankResponse {
  ranking_basis: "rubric+reach_prior" | "rubric_only";
  reach_model: string | null;
  disclaimer?: string;
  winner_index: number | null;
  candidates: RankCandidate[];
}

export async function rankCandidates(
  candidates: { title: string; thumbnail?: File | null }[],
  idea?: string,
): Promise<RankResponse> {
  const form = new FormData();
  for (const c of candidates) {
    form.append("titles", c.title);
  }
  // Thumbnails are position-aligned with titles; an empty Blob holds a slot
  // so a candidate without a thumbnail doesn't shift the others.
  const anyThumb = candidates.some((c) => c.thumbnail);
  if (anyThumb) {
    for (const c of candidates) {
      if (c.thumbnail) {
        form.append("thumbnails", c.thumbnail, c.thumbnail.name);
      } else {
        form.append("thumbnails", new Blob([]), ""); // empty slot
      }
    }
  }
  if (idea && idea.trim()) form.append("idea", idea.trim());

  const res = await api.post<RankResponse>("/rank/candidates", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return res.data;
}

// ===========================================================================
// Breakout Radar (plan 9.1) — GET /breakouts
// Live cross-channel breakout feed: what's taking off across the tracked
// ecosystem right now, with calibrated P(breakout), topic saturation, and
// niche-conditioned detection confidence.
// ===========================================================================
export interface BreakoutItem {
  video_id: string;
  channel_id: string;
  title: string;
  views: number;
  age_hours: number | null;
  score: number;
  probability: number;
  level: string; // breakout | heating_up | normal
  niche: string;
  confidence: string; // high | moderate | lower
  thumbnail_url: string;
  watch_url: string;
  topic: { label: string; size: number; channel_count: number } | null;
}

export interface BreakoutRadarResponse {
  checkpoint: string;
  count: number;
  updated_at: string;
  breakouts: BreakoutItem[];
}

export async function getBreakoutRadar(params?: {
  checkpoint?: "1h" | "6h" | "24h";
  min_probability?: number;
  max_age_hours?: number;
  english_only?: boolean;
  limit?: number;
}): Promise<BreakoutRadarResponse> {
  const res = await api.get<BreakoutRadarResponse>("/breakouts", { params });
  return res.data;
}

// ===========================================================================
// Connect Your Own Channel (3.1) — the validated detector on YOUR uploads,
// plus a durability-driven sequel recommendation. GET /my-channel/breakouts
// ===========================================================================
export interface SequelRecommendation {
  action: string;
  why: string;
  urgency: "high" | "medium" | "low";
}

export interface MyChannelBreakout extends BreakoutItem {
  durability?: DurabilityBadge;
  recommendation?: SequelRecommendation;
  channel_name?: string | null;
}

export interface MyChannelBreakoutsResponse {
  connected: boolean;
  checkpoint: string;
  count: number;
  updated_at: string;
  breakouts: MyChannelBreakout[];
}

export async function getMyChannelBreakouts(params?: {
  checkpoint?: "1h" | "6h" | "24h";
}): Promise<MyChannelBreakoutsResponse> {
  const res = await api.get<MyChannelBreakoutsResponse>("/my-channel/breakouts", { params });
  return res.data;
}

export async function enrollMyChannels(): Promise<{ enrolled: string[]; count: number }> {
  const res = await api.post("/my-channel/enroll");
  return res.data;
}

// Owner analytics (3.2 display half) — real CTR + retention from the user's OAuth.
export interface OwnerVideoAnalytics {
  video_id: string;
  title: string | null;
  views: number;
  impressions: number;
  ctr: number; // 0-1
  avg_view_percentage: number;
  avg_view_duration_seconds: number;
  retention_curve: number[] | null;
  watch_url: string;
}

export interface MyChannelAnalyticsResponse {
  connected: boolean;
  channel_avg_ctr: number | null;
  fetched_at: string | null;
  videos: OwnerVideoAnalytics[];
}

export async function getMyChannelAnalytics(): Promise<MyChannelAnalyticsResponse> {
  const res = await api.get<MyChannelAnalyticsResponse>("/my-channel/analytics");
  return res.data;
}

export async function refreshMyChannelAnalytics(): Promise<{ connections: number; videos: number }> {
  const res = await api.post("/my-channel/analytics/refresh", undefined, { timeout: 60000 });
  return res.data;
}

// ===========================================================================
// Competitive Watchlist — track any public channel, get breakout + durability
// alerts on it (the wedge Studio can't match). GET/POST/DELETE /watchlist
// ===========================================================================
export interface WatchlistChannel {
  channel_id: string;
  channel_title: string | null;
  label: string | null;
  added_at: string;
}

export interface DurabilityBadge {
  // likely_to_sustain | could_flash | uncertain | too_early
  label: string;
  probability: number | null;
}

export interface WatchlistBreakout extends BreakoutItem {
  durability?: DurabilityBadge;
}

export interface WatchlistBreakoutsResponse {
  checkpoint: string;
  count: number;
  updated_at: string;
  breakouts: WatchlistBreakout[];
}

export async function getWatchlist(): Promise<{ channels: WatchlistChannel[] }> {
  const res = await api.get<{ channels: WatchlistChannel[] }>("/watchlist");
  return res.data;
}

export async function addWatchlistChannel(
  url: string,
  label?: string,
): Promise<{ channel_id: string; channel_title: string | null; added: boolean }> {
  const res = await api.post("/watchlist", { url, label }, { timeout: 30000 });
  return res.data;
}

export async function removeWatchlistChannel(channelId: string): Promise<{ removed: boolean }> {
  const res = await api.delete(`/watchlist/${encodeURIComponent(channelId)}`);
  return res.data;
}

export async function getWatchlistBreakouts(params?: {
  checkpoint?: "1h" | "6h" | "24h";
  mode?: "precise" | "balanced" | "sensitive";
  limit?: number;
}): Promise<WatchlistBreakoutsResponse> {
  const res = await api.get<WatchlistBreakoutsResponse>("/watchlist/breakouts", { params });
  return res.data;
}

export interface LeaderboardChannel {
  channel_id: string;
  channel_title: string;
  breakout_count: number;
  avg_durability: number | null;
  top_video: { video_id: string; title: string | null; probability: number; watch_url: string } | null;
}

export interface WatchlistLeaderboardResponse {
  window_days: number;
  updated_at: string;
  channels: LeaderboardChannel[];
}

export async function getWatchlistLeaderboard(params?: {
  window_days?: number;
  checkpoint?: "1h" | "6h" | "24h";
}): Promise<WatchlistLeaderboardResponse> {
  const res = await api.get<WatchlistLeaderboardResponse>("/watchlist/leaderboard", { params });
  return res.data;
}

export interface WatchlistSettings {
  email_alerts: boolean;
  weekly_digest: boolean;
  alert_webhook_url: string;
}

export async function getWatchlistSettings(): Promise<WatchlistSettings> {
  const res = await api.get<WatchlistSettings>("/watchlist/settings");
  return res.data;
}

export async function updateWatchlistSettings(
  patch: Partial<WatchlistSettings>,
): Promise<WatchlistSettings> {
  const res = await api.patch<WatchlistSettings>("/watchlist/settings", patch);
  return res.data;
}

// Format Radar (Emerging Formats) — GET /formats
export interface FormatExample {
  video_id: string;
  title: string;
  outlier: number;
  views: number;
  niche: string | null;
  age_days: number | null;
}
export interface EmergingFormat {
  slug: string;
  template: string;
  name: string;
  psychology_type: string;
  niche: string | null;
  count: number;
  avg_outlier: number;
  median_outlier: number;
  avg_views: number;
  momentum: number;
  unique_channels: number;
  openness: "open" | "warming" | "crowded";
  reliability: "low" | "medium" | "high";
  examples: FormatExample[];
}
export interface FormatRadarResponse {
  count: number;
  updated_at: string | null;
  formats: EmergingFormat[];
  locked?: number;
  plan_gated?: boolean;
}

export async function getFormatRadar(params?: {
  niche?: string;
  sort?: "momentum" | "outlier" | "views" | "count";
  openness?: "open" | "warming" | "crowded";
  min_reliability?: "low" | "medium" | "high";
  limit?: number;
}): Promise<FormatRadarResponse> {
  const res = await api.get<FormatRadarResponse>("/formats", { params });
  return res.data;
}

// Breakout explainer (plan 8.7) — GET /breakouts/{video_id}/explain
export interface BreakoutExplanation {
  why?: string;
  packaging_takeaway?: string;
  your_angle?: string;
  caveat?: string;
  error?: string;
  evidence?: Record<string, unknown>;
}

export async function explainBreakout(
  videoId: string,
  idea?: string,
): Promise<BreakoutExplanation> {
  const res = await api.get<BreakoutExplanation>(
    `/breakouts/${encodeURIComponent(videoId)}/explain`,
    { params: idea ? { idea } : undefined, timeout: 60000 },
  );
  return res.data;
}

// Breakout Teardown — the full "reverse-engineer this breakout" composition.
export interface BreakoutTeardown {
  video_id: string;
  title: string;
  explanation: BreakoutExplanation;
  format: { key: string; template: string; psychology: string } | null;
  comments: {
    summary?: string;
    sentiment?: { positive: number; neutral: number; negative: number };
    top_questions?: string[];
    next_video_ideas?: string[];
    praise_themes?: string[];
    criticism_themes?: string[];
  } | null;
  retention: { points: { start_time: number; end_time: number; value: number }[]; duration_seconds: number | null } | null;
}

export async function getBreakoutTeardown(videoId: string, idea?: string): Promise<BreakoutTeardown> {
  const res = await api.get<BreakoutTeardown>(
    `/breakouts/${encodeURIComponent(videoId)}/teardown`,
    { params: idea ? { idea } : undefined, timeout: 90000 },
  );
  return res.data;
}

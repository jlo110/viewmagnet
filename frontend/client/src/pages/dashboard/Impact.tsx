/**
 * Impact Dashboard — Before/After Tracking
 *
 * Two readiness thresholds gate what this page shows:
 *
 *   - ≥ 5 videos analyzed (so the comparison cohort isn't statistically
 *     meaningless — 1 video tells you nothing about lift).
 *   - ≥ 30 days of usage history (so we can plot a real before/after
 *     trend instead of pretending a week of data is causal).
 *
 * When both thresholds are met we render the real impact view. Until
 * then we render an honest unlock card that shows progress toward each
 * threshold and a *clearly labeled* "Sample data — not your numbers"
 * preview chart so the user can see what they'll unlock without us
 * lying to them about their channel.
 *
 * The fabricated before/after data that used to live here in the
 * isDev branch ("from 4,200 to 18,400 views!") was actively harmful:
 * it churns serious creators the moment they realize the numbers
 * don't match their actual channel.
 */
import { useState, useEffect, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Link } from "wouter";
import {
  TrendingUp,
  Eye,
  Users,
  Clock,
  BarChart3,
  ArrowUp,
  ArrowDown,
  Minus,
  Sparkles,
  Calendar,
  Video,
  ThumbsUp,
  MessageSquare,
  Loader2,
  Lock,
  CheckCircle2,
  Magnet,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  AreaChart,
  Area,
  Legend,
} from "recharts";
import { useAuth } from "@/contexts/AuthContext";
import {
  getAnalysisHistory,
  getImpactSummary,
  type AnalysisHistoryItem,
  type ImpactSummary,
} from "@/lib/api";
import {
  pickPersonaFor,
  PERSONA_ORDER,
  SAMPLE_PERSONAS,
  type PersonaId,
} from "@/lib/samplePersonas";

// ---------------------------------------------------------------------------
// Readiness thresholds. Centralized so we can tune them and they appear
// consistently in both the UI strings and the gating logic.
// ---------------------------------------------------------------------------
const MIN_VIDEOS_FOR_IMPACT = 5;
const MIN_DAYS_FOR_IMPACT = 30;
const DAY_MS = 86_400_000;

interface ImpactMetric {
  name: string;
  before: number;
  after: number;
  change: number;
  changePercent: number;
  unit: string;
  icon: React.ReactNode;
}

interface VideoComparison {
  title: string;
  usedViewMagnet: boolean;
  views: number;
  likes: number;
  comments: number;
  engagementRate: number;
  publishedAt: string;
  magnetScore?: number;
}

interface TrendDataPoint {
  date: string;
  beforeAvg: number;
  afterAvg: number;
  actual: number;
}

// ---------------------------------------------------------------------------
// Sample-data fixtures live in ``lib/samplePersonas.ts`` so they can be
// rotated per-niche (tech / finance / fitness / gaming). Reviewer
// pushback was that a single tech sample bounced cold users from other
// niches; the persona picker on the preview now lets each user see
// numbers that look like theirs. The badge above the chart always
// clearly marks the content as synthetic.
// ---------------------------------------------------------------------------

interface ImpactReadiness {
  loading: boolean;
  unlocked: boolean;
  videoCount: number;
  daysOfHistory: number;
  /** First analysis timestamp (epoch ms) — null when no analyses exist. */
  firstAnalyzedAt: number | null;
}

/** Compute whether the user qualifies for a real impact view. The two
 *  thresholds intentionally live here, not in component state, so this
 *  hook can be reused on Overview or anywhere else we want to gate a
 *  "Look at your growth!" widget. */
function useImpactReadiness(): ImpactReadiness {
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<AnalysisHistoryItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 200 is enough headroom — we only care about the count and the
        // earliest timestamp, both stable beyond ~50 records.
        const result = await getAnalysisHistory(200);
        if (!cancelled) setItems(result.analyses ?? []);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return useMemo(() => {
    const videoCount = items.length;
    let firstAnalyzedAt: number | null = null;
    for (const a of items) {
      const t = new Date(a.analyzed_at).getTime();
      if (!Number.isFinite(t)) continue;
      if (firstAnalyzedAt === null || t < firstAnalyzedAt) {
        firstAnalyzedAt = t;
      }
    }
    const daysOfHistory =
      firstAnalyzedAt !== null
        ? Math.floor((Date.now() - firstAnalyzedAt) / DAY_MS)
        : 0;
    const unlocked =
      videoCount >= MIN_VIDEOS_FOR_IMPACT &&
      daysOfHistory >= MIN_DAYS_FOR_IMPACT;
    return { loading, unlocked, videoCount, daysOfHistory, firstAnalyzedAt };
  }, [items, loading]);
}

export default function Impact() {
  const { user } = useAuth();
  const readiness = useImpactReadiness();
  const [timeRange, setTimeRange] = useState<"30d" | "90d" | "all">("30d");
  // Tracks whether the user explicitly opted to preview the sample
  // dashboard from the unlock card. Without the opt-in the page stays
  // honest by default — sample numbers never look like real numbers.
  const [showSamplePreview, setShowSamplePreview] = useState(false);
  // Stable per-user default persona so the same user keeps seeing the
  // same demo channel across reloads (hash of user.id picks the niche).
  const defaultPersonaId = useMemo(
    () => pickPersonaFor(user?.id ?? user?.email ?? null).copy.id,
    [user?.id, user?.email],
  );

  // Lucide icon names returned by the backend → React element. Kept
  // local to the page so the API layer stays JSX-free.
  const iconForMetric = useMemo<Record<string, React.ReactNode>>(
    () => ({
      Eye: <Eye className="w-5 h-5" />,
      ThumbsUp: <ThumbsUp className="w-5 h-5" />,
      Users: <Users className="w-5 h-5" />,
      Clock: <Clock className="w-5 h-5" />,
      MessageSquare: <MessageSquare className="w-5 h-5" />,
      TrendingUp: <TrendingUp className="w-5 h-5" />,
    }),
    [],
  );

  // Real before/after summary from the backend. Always returns 200,
  // so we only fire the request once we know the user has cleared
  // the readiness gates locally — otherwise the payload would just
  // be ``ready=false`` with empty lists and we'd waste a round trip.
  const [summary, setSummary] = useState<ImpactSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  useEffect(() => {
    if (!readiness.unlocked) return;
    let cancelled = false;
    setSummaryLoading(true);
    (async () => {
      try {
        const data = await getImpactSummary();
        if (!cancelled) setSummary(data);
      } catch {
        if (!cancelled) setSummary(null);
      } finally {
        if (!cancelled) setSummaryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [readiness.unlocked]);

  // Backend payload → the page's render types. We let the backend
  // own the math (cohort split, lift %, etc.) so the UI is purely
  // presentational and a future server-side change doesn't require
  // touching React.
  const realMetricsLoaded = !!summary?.ready && (summary?.metrics.length ?? 0) > 0;
  const metrics: ImpactMetric[] = useMemo(
    () =>
      (summary?.metrics ?? []).map((m) => ({
        name: m.name,
        before: m.before,
        after: m.after,
        change: m.change,
        changePercent: m.change_percent,
        unit: m.unit,
        icon: iconForMetric[m.icon] ?? <TrendingUp className="w-5 h-5" />,
      })),
    [summary, iconForMetric],
  );
  const videoComparisons: VideoComparison[] = useMemo(
    () =>
      (summary?.videos ?? []).map((v) => ({
        title: v.title,
        usedViewMagnet: v.used_view_magnet,
        views: v.views,
        likes: 0,
        comments: 0,
        engagementRate: v.engagement_rate,
        publishedAt: v.published_at ?? "",
        magnetScore: v.magnet_score ?? undefined,
      })),
    [summary],
  );
  const trendData: TrendDataPoint[] = useMemo(
    () =>
      (summary?.trend ?? []).map((p) => ({
        date: p.date,
        beforeAvg: p.before_avg,
        afterAvg: p.after_avg,
        actual: p.actual,
      })),
    [summary],
  );

  if (readiness.loading || summaryLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Locked state — primary surface for almost every new user. Shows
  // exact progress toward each threshold and a CTA to keep analyzing.
  // Optionally lets them peek at a clearly-labeled sample dashboard.
  // ---------------------------------------------------------------------
  if (!readiness.unlocked) {
    const videosLeft = Math.max(0, MIN_VIDEOS_FOR_IMPACT - readiness.videoCount);
    const daysLeft = Math.max(0, MIN_DAYS_FOR_IMPACT - readiness.daysOfHistory);
    return (
      <div className="space-y-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-cyan-glow" />
            Your ViewMagnet Impact
          </h1>
          <p className="text-muted-foreground">
            See how ViewMagnet improves your channel performance over time
          </p>
        </div>

        <Card className="bg-gradient-to-br from-cyan-glow/5 to-violet-500/5 border-cyan-glow/20">
          <CardContent className="py-8 space-y-6">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-full bg-cyan-glow/10">
                <Lock className="w-6 h-6 text-cyan-glow" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold">
                  Your Impact chart unlocks at{" "}
                  <span className="text-cyan-glow">
                    {MIN_VIDEOS_FOR_IMPACT} videos analyzed
                  </span>{" "}
                  AND{" "}
                  <span className="text-cyan-glow">
                    {MIN_DAYS_FOR_IMPACT} days of history
                  </span>
                </h2>
                <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
                  We refuse to show you a growth chart based on three
                  data points — that's how SaaS dashboards lie. Once
                  there's enough signal to attribute lift honestly, your
                  real before/after view shows up here automatically.
                </p>
              </div>
            </div>

            {/* Per-threshold progress. Each row turns green once met
                so the user can see clearly which gate is still open. */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 rounded-lg bg-background/40 border border-border/40">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium flex items-center gap-2">
                    <Video className="w-4 h-4 text-muted-foreground" />
                    Videos analyzed
                  </p>
                  {videosLeft === 0 ? (
                    <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      Met
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-xs">
                      {videosLeft} to go
                    </Badge>
                  )}
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold">
                    {readiness.videoCount}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    / {MIN_VIDEOS_FOR_IMPACT}
                  </span>
                </div>
                <Progress
                  value={Math.min(
                    100,
                    (readiness.videoCount / MIN_VIDEOS_FOR_IMPACT) * 100,
                  )}
                  className="mt-2 h-1.5"
                />
                <div className="mt-3 flex gap-2">
                  <Link href="/dashboard/analyzer">
                    <Button
                      size="sm"
                      className="h-7 text-xs bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                    >
                      <Magnet className="w-3 h-3 mr-1" />
                      Analyze a video
                    </Button>
                  </Link>
                </div>
              </div>

              <div className="p-4 rounded-lg bg-background/40 border border-border/40">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-muted-foreground" />
                    Days of history
                  </p>
                  {daysLeft === 0 ? (
                    <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      Met
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-xs">
                      {daysLeft} more day{daysLeft === 1 ? "" : "s"}
                    </Badge>
                  )}
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold">
                    {readiness.daysOfHistory}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    / {MIN_DAYS_FOR_IMPACT}
                  </span>
                </div>
                <Progress
                  value={Math.min(
                    100,
                    (readiness.daysOfHistory / MIN_DAYS_FOR_IMPACT) * 100,
                  )}
                  className="mt-2 h-1.5"
                />
                <p className="text-[11px] text-muted-foreground mt-3">
                  {readiness.firstAnalyzedAt
                    ? `First analysis ${new Date(readiness.firstAnalyzedAt).toLocaleDateString()}`
                    : "Counted from your first analysis"}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowSamplePreview((v) => !v)}
              >
                {showSamplePreview ? "Hide" : "Preview"} sample dashboard
              </Button>
              <span className="text-[11px] text-muted-foreground">
                Curious what unlocks? See an example chart with synthetic data.
              </span>
            </div>
          </CardContent>
        </Card>

        {showSamplePreview && (
          <SampleImpactPreview
            timeRange={timeRange}
            onTimeRange={setTimeRange}
            defaultPersonaId={defaultPersonaId}
          />
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Unlocked but real metrics endpoint not wired yet. We're past the
  // "would be dishonest" gate, but we don't have a backed dataset to
  // render. Show a transparent "metrics rolling out" card instead of
  // backfilling with sample data — those users are most likely to
  // notice the numbers don't match their YouTube Studio.
  // ---------------------------------------------------------------------
  if (!realMetricsLoaded || metrics.length === 0) {
    return (
      <div className="space-y-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-cyan-glow" />
            Your ViewMagnet Impact
          </h1>
          <p className="text-muted-foreground">
            You're past the unlock threshold — your real chart is being computed.
          </p>
        </div>
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <BarChart3 className="w-10 h-10 text-muted-foreground/50 mx-auto mb-3" />
            <h3 className="font-semibold mb-1">
              We're aggregating your real metrics
            </h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              You have enough history for an honest before/after view.
              The summary endpoint is being wired up — your real chart
              will appear here as soon as it ships.
            </p>
            <p className="text-xs text-muted-foreground/70 mt-3">
              {readiness.videoCount} videos · {readiness.daysOfHistory} days of history
            </p>
          </CardContent>
        </Card>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowSamplePreview((v) => !v)}
        >
          {showSamplePreview ? "Hide" : "Show"} what the chart will look like
        </Button>
        {showSamplePreview && (
          <SampleImpactPreview
            timeRange={timeRange}
            onTimeRange={setTimeRange}
            defaultPersonaId={defaultPersonaId}
          />
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Real impact view — never reached today (realMetricsLoaded is false
  // until the backend endpoint ships). Kept here so the implementation
  // is ready to drop in the moment the data is available.
  // ---------------------------------------------------------------------
  return (
    <RealImpactView
      metrics={metrics}
      videoComparisons={videoComparisons}
      trendData={trendData}
      timeRange={timeRange}
      onTimeRange={setTimeRange}
    />
  );
}

// ---------------------------------------------------------------------------
// Sample preview. Identical visual to the real impact view but every
// surface is wrapped in a "Sample data" affordance so the user can't
// confuse it with their own performance.
// ---------------------------------------------------------------------------
function SampleImpactPreview({
  timeRange,
  onTimeRange,
  defaultPersonaId,
}: {
  timeRange: "30d" | "90d" | "all";
  onTimeRange: (r: "30d" | "90d" | "all") => void;
  // Stable per-user default so the same user keeps seeing the same demo
  // channel on reload — but a dropdown lets them switch niches so a
  // finance creator doesn't bounce because we picked the gaming sample.
  defaultPersonaId: PersonaId;
}) {
  const [personaId, setPersonaId] = useState<PersonaId>(defaultPersonaId);
  const persona = SAMPLE_PERSONAS[personaId];

  // Map persona metric icon names to the actual lucide elements.
  // Done here (not in samplePersonas.ts) so that file stays JSX-free.
  const iconFor: Record<string, React.ReactNode> = {
    Eye: <Eye className="w-5 h-5" />,
    ThumbsUp: <ThumbsUp className="w-5 h-5" />,
    Users: <Users className="w-5 h-5" />,
    Clock: <Clock className="w-5 h-5" />,
    MessageSquare: <MessageSquare className="w-5 h-5" />,
    TrendingUp: <TrendingUp className="w-5 h-5" />,
  };
  const metrics: ImpactMetric[] = persona.metrics.map((m) => ({
    name: m.name,
    before: m.before,
    after: m.after,
    change: m.change,
    changePercent: m.changePercent,
    unit: m.unit,
    icon: iconFor[m.icon] ?? <Eye className="w-5 h-5" />,
  }));

  return (
    <div className="space-y-4 relative">
      <div className="flex flex-wrap items-center gap-3">
        <Badge className="bg-amber-glow/15 text-amber-glow border-amber-glow/30 gap-1">
          <Lock className="w-3 h-3" />
          Sample data
        </Badge>
        <p className="text-xs text-muted-foreground flex-1 min-w-[200px]">
          {persona.copy.tagline} — synthetic numbers, for preview only.
        </p>
        {/* Persona picker. Reviewer feedback was that a single-niche
            sample bounces creators in other niches; rotating personas
            lets a finance/fitness/gaming creator see numbers that look
            like theirs without us claiming they are theirs. */}
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className="text-muted-foreground">Niche:</span>
          <select
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value as PersonaId)}
            className="rounded border border-border bg-background px-1.5 py-0.5 text-foreground hover:border-cyan-glow/40 focus:border-cyan-glow focus:outline-none"
            aria-label="Choose sample creator niche"
          >
            {PERSONA_ORDER.map((id) => (
              <option key={id} value={id}>
                {SAMPLE_PERSONAS[id].copy.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="opacity-90 pointer-events-none select-none">
        <RealImpactView
          metrics={metrics}
          videoComparisons={persona.videos}
          trendData={persona.trend}
          timeRange={timeRange}
          onTimeRange={onTimeRange}
          headerVariant="sample"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The actual impact dashboard. Pure render — accepts metrics and
// renders. Used by both the real (future) view and the sample preview.
// ---------------------------------------------------------------------------
function RealImpactView({
  metrics,
  videoComparisons,
  trendData,
  timeRange,
  onTimeRange,
  headerVariant,
}: {
  metrics: ImpactMetric[];
  videoComparisons: VideoComparison[];
  trendData: TrendDataPoint[];
  timeRange: "30d" | "90d" | "all";
  onTimeRange: (r: "30d" | "90d" | "all") => void;
  headerVariant?: "sample";
}) {
  const formatNumber = (num: number) => {
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
    return num.toString();
  };

  const getChangeIndicator = (change: number) => {
    if (change > 0) return <ArrowUp className="w-4 h-4 text-green-500" />;
    if (change < 0) return <ArrowDown className="w-4 h-4 text-red-500" />;
    return <Minus className="w-4 h-4 text-gray-500" />;
  };

  const videosWithViewMagnet = videoComparisons.filter((v) => v.usedViewMagnet);
  const videosWithoutViewMagnet = videoComparisons.filter((v) => !v.usedViewMagnet);
  const avgViewsWith =
    videosWithViewMagnet.length > 0
      ? videosWithViewMagnet.reduce((sum, v) => sum + v.views, 0) /
        videosWithViewMagnet.length
      : 0;
  const avgViewsWithout =
    videosWithoutViewMagnet.length > 0
      ? videosWithoutViewMagnet.reduce((sum, v) => sum + v.views, 0) /
        videosWithoutViewMagnet.length
      : 0;
  const viewsMultiplier =
    avgViewsWithout > 0 ? (avgViewsWith / avgViewsWithout).toFixed(1) : "N/A";

  return (
    <div className="space-y-6">
      {headerVariant !== "sample" && (
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-cyan-glow" />
            Your ViewMagnet Impact
          </h1>
          <p className="text-muted-foreground">
            See how ViewMagnet has improved your channel performance
          </p>
        </div>
      )}

      <div className="flex gap-2">
        <Button
          variant={timeRange === "30d" ? "default" : "outline"}
          size="sm"
          onClick={() => onTimeRange("30d")}
        >
          Last 30 Days
        </Button>
        <Button
          variant={timeRange === "90d" ? "default" : "outline"}
          size="sm"
          onClick={() => onTimeRange("90d")}
        >
          Last 90 Days
        </Button>
        <Button
          variant={timeRange === "all" ? "default" : "outline"}
          size="sm"
          onClick={() => onTimeRange("all")}
        >
          All Time
        </Button>
      </div>

      <Card className="bg-gradient-to-r from-cyan-500/10 to-purple-500/10 border-cyan-500/20">
        <CardContent className="py-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold">
                Your videos using ViewMagnet get{" "}
                <span className="text-cyan-glow">{viewsMultiplier}x</span> more views
              </h2>
              <p className="text-muted-foreground mt-1">
                Based on {videosWithViewMagnet.length} videos analyzed with ViewMagnet vs{" "}
                {videosWithoutViewMagnet.length} without
              </p>
            </div>
            <div className="flex items-center gap-2">
              <TrendingUp className="w-8 h-8 text-green-500" />
              <div className="text-right">
                <div className="text-2xl font-bold text-green-500">
                  {avgViewsWithout > 0
                    ? `+${Math.round(((avgViewsWith - avgViewsWithout) / avgViewsWithout) * 100)}%`
                    : "—"}
                </div>
                <div className="text-sm text-muted-foreground">Avg Views Increase</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((metric) => (
          <Card key={metric.name} className="relative overflow-hidden">
            <CardContent className="pt-6">
              <div className="flex items-start justify-between">
                <div className="p-2 rounded-lg bg-primary/10">{metric.icon}</div>
                <Badge
                  variant={metric.changePercent > 0 ? "default" : "destructive"}
                  className="bg-green-500/10 text-green-500 border-green-500/20"
                >
                  {getChangeIndicator(metric.change)}
                  {metric.changePercent > 0 ? "+" : ""}
                  {metric.changePercent}%
                </Badge>
              </div>
              <div className="mt-4">
                <p className="text-sm text-muted-foreground">{metric.name}</p>
                <div className="flex items-baseline gap-2 mt-1">
                  <span className="text-2xl font-bold">
                    {formatNumber(metric.after)}
                  </span>
                  <span className="text-sm text-muted-foreground">{metric.unit}</span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  was {formatNumber(metric.before)} {metric.unit}
                </p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs defaultValue="trend" className="space-y-4">
        <TabsList>
          <TabsTrigger value="trend">Performance Trend</TabsTrigger>
          <TabsTrigger value="comparison">Video Comparison</TabsTrigger>
        </TabsList>

        <TabsContent value="trend">
          <Card>
            <CardHeader>
              <CardTitle>Views Over Time</CardTitle>
              <CardDescription>
                Your video performance before and after using ViewMagnet
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trendData}>
                    <defs>
                      <linearGradient id="colorActual" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#00D4FF" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#00D4FF" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                    <XAxis dataKey="date" stroke="#666" />
                    <YAxis stroke="#666" />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1a1a2e",
                        border: "1px solid #333",
                        borderRadius: "8px",
                      }}
                    />
                    <Legend />
                    <Line
                      type="monotone"
                      dataKey="beforeAvg"
                      stroke="#666"
                      strokeDasharray="5 5"
                      name="Before ViewMagnet (Avg)"
                      dot={false}
                    />
                    <Area
                      type="monotone"
                      dataKey="actual"
                      stroke="#00D4FF"
                      fill="url(#colorActual)"
                      name="Actual Views"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="comparison">
          <Card>
            <CardHeader>
              <CardTitle>Video-by-Video Comparison</CardTitle>
              <CardDescription>
                Compare performance of videos analyzed with ViewMagnet vs without
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {videoComparisons.map((video, index) => (
                  <div
                    key={index}
                    className={`p-4 rounded-lg border ${
                      video.usedViewMagnet
                        ? "border-cyan-500/30 bg-cyan-500/5"
                        : "border-border bg-card"
                    }`}
                  >
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div className="flex items-start gap-3">
                        <div className="p-2 rounded-lg bg-primary/10">
                          <Video className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium">{video.title}</h4>
                            {video.usedViewMagnet && (
                              <Badge className="bg-cyan-500/20 text-cyan-400 border-cyan-500/30">
                                <Sparkles className="w-3 h-3 mr-1" />
                                ViewMagnet
                              </Badge>
                            )}
                          </div>
                          <p className="text-sm text-muted-foreground flex items-center gap-2 mt-1">
                            <Calendar className="w-3 h-3" />
                            {video.publishedAt}
                            {video.magnetScore && (
                              <>
                                <span className="mx-1">•</span>
                                <span className="text-cyan-400">
                                  Score: {video.magnetScore}
                                </span>
                              </>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex gap-6">
                        <div className="text-center">
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <Eye className="w-4 h-4" />
                            <span className="text-sm">Views</span>
                          </div>
                          <p className="font-bold">{formatNumber(video.views)}</p>
                        </div>
                        <div className="text-center">
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <ThumbsUp className="w-4 h-4" />
                            <span className="text-sm">Likes</span>
                          </div>
                          <p className="font-bold">{formatNumber(video.likes)}</p>
                        </div>
                        <div className="text-center">
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <MessageSquare className="w-4 h-4" />
                            <span className="text-sm">Comments</span>
                          </div>
                          <p className="font-bold">{formatNumber(video.comments)}</p>
                        </div>
                        <div className="text-center">
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <BarChart3 className="w-4 h-4" />
                            <span className="text-sm">Engagement</span>
                          </div>
                          <p className="font-bold">{video.engagementRate}%</p>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Card className="border-dashed">
        <CardContent className="py-6">
          <div className="flex items-start gap-4">
            <div className="p-3 rounded-full bg-primary/10">
              <BarChart3 className="w-6 h-6 text-cyan-glow" />
            </div>
            <div>
              <h3 className="font-semibold">How we track impact</h3>
              <p className="text-sm text-muted-foreground mt-1">
                We compare videos you analyzed with ViewMagnet against your channel's
                historical average performance. Videos are marked as
                "ViewMagnet-optimized" if you used our analyzer, title generator, or
                thumbnail creator before publishing.
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                For the most accurate tracking, connect your YouTube Analytics so we
                can attribute view lift to specific optimizations.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

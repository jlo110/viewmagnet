/*
 * Video Analyzer: Paste URL → get ML prediction with SHAP explanations
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { ToolHandoffButton } from "@/components/ToolHandoffButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import {
  BarChart3,
  Search,
  TrendingUp,
  TrendingDown,
  ThumbsUp,
  Clock,
  Eye,
  Loader2,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Shield,
  Info,
  Magnet,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  Type,
  Image,
  Users,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useState, useEffect, useRef, useCallback } from "react";
import { Link, useLocation } from "wouter";
import { useAnalyzeVideo } from "@/hooks/useApi";
import { getAnalysisHistory, getAnalysisByVideoId, type FeatureExplanation, type AnalysisHistoryItem } from "@/lib/api";
import {
  buildStudioLink,
  mapRecommendationToCta,
  readAnalyzerDeepLink,
  structuredCtaToFrontend,
} from "@/lib/deepLinks";
import { Wand2, Film, Scissors } from "lucide-react";

const ANALYSIS_STAGES = [
  { label: "Fetching video data", duration: 800 },
  { label: "Analyzing thumbnail", duration: 1200 },
  { label: "Analyzing title & metadata", duration: 1000 },
  { label: "Running ML prediction", duration: 1500 },
  { label: "Generating insights", duration: 800 },
] as const;

export default function VideoAnalyzer() {
  const [url, setUrl] = useState("");
  const { analyze, data, loading, error } = useAnalyzeVideo();
  const [currentStage, setCurrentStage] = useState(0);
  const [stageProgress, setStageProgress] = useState(0);
  const progressRef = useRef<NodeJS.Timeout | null>(null);
  const stageRef = useRef<NodeJS.Timeout | null>(null);
  const [history, setHistory] = useState<AnalysisHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<AnalysisHistoryItem | null>(null);
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(false);

  const loadHistoryItem = async (videoId: string) => {
    // Set URL and trigger fresh analysis for complete data
    const videoUrl = `https://youtube.com/watch?v=${videoId}`;
    setUrl(videoUrl);
    setSelectedHistoryItem(null);
    // Trigger analysis to get full data with niche benchmarks
    await analyze({ url: videoUrl });
  };

  const loadHistory = useCallback(async () => {
    try {
      const result = await getAnalysisHistory(10);
      setHistory(result.analyses);
    } catch (err) {
      console.error("Failed to load analysis history:", err);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (data && !loading) {
      loadHistory();
    }
  }, [data, loading, loadHistory]);

  // Deep-link entry: other tools (Velocity Tracker, Smart Alerts,
  // Overview, etc.) can pre-fill the URL via `?url=<youtube>` and
  // auto-run the analysis with `&autoRun=1`. See `lib/deepLinks.ts`.
  const [, navigate] = useLocation();
  const autoRanRef = useRef(false);
  useEffect(() => {
    if (autoRanRef.current) return;
    const link = readAnalyzerDeepLink();
    if (!link) return;
    autoRanRef.current = true;
    setUrl(link.url);
    if (link.autoRun) {
      analyze({ url: link.url }).catch(() => {
        // Swallow — the analyze hook surfaces its own error UI.
      });
    }
    // We intentionally don't strip the query params here — that way a
    // refresh re-runs the same analysis. The user can edit the URL field
    // and re-analyze, which uses the input value not the URL params.
  }, [analyze]);

  // Simulate progress through stages while loading
  useEffect(() => {
    if (loading) {
      setCurrentStage(0);
      setStageProgress(0);
      
      let stage = 0;
      const advanceStage = () => {
        if (stage < ANALYSIS_STAGES.length - 1) {
          stage++;
          setCurrentStage(stage);
          setStageProgress(0);
          stageRef.current = setTimeout(advanceStage, ANALYSIS_STAGES[stage].duration);
        }
      };
      
      // Start stage advancement
      stageRef.current = setTimeout(advanceStage, ANALYSIS_STAGES[0].duration);
      
      // Progress within each stage
      progressRef.current = setInterval(() => {
        setStageProgress(prev => Math.min(prev + 8, 95));
      }, 100);
      
    } else {
      // Analysis complete - show 100%
      if (progressRef.current) clearInterval(progressRef.current);
      if (stageRef.current) clearTimeout(stageRef.current);
      if (data) {
        setCurrentStage(ANALYSIS_STAGES.length - 1);
        setStageProgress(100);
      }
    }
    
    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
      if (stageRef.current) clearTimeout(stageRef.current);
    };
  }, [loading, data]);

  const handleAnalyze = async () => {
    if (!url.trim()) return;
    setSelectedHistoryItem(null);
    await analyze({ url: url.trim() });
  };

  const overallProgress = loading 
    ? Math.round(((currentStage / ANALYSIS_STAGES.length) * 100) + (stageProgress / ANALYSIS_STAGES.length))
    : (data ? 100 : 0);

  // Generate niche benchmarks from comparison data with explanations
  // Mode-aware explanation for Magnet Score
  const getMagnetScoreExplanation = () => {
    const mode = data?.niche_comparison?.analysis_mode;
    if (mode === "velocity") {
      return "Performance momentum (70%) + packaging quality (30%)";
    } else if (mode === "evaluation") {
      return "Actual performance compared to your channel average";
    }
    return "Predicted click-attraction potential before upload";
  };
  
  const nicheBenchmarks = data?.niche_comparison
    ? [
        {
          metric: "Magnet Score",
          yours: Math.round(data.prediction_score),
          nicheAvg: data.niche_comparison.niche_average || 50,
          top10: data.niche_comparison.top_10_threshold || 75,
          status: data.prediction_score > (data.niche_comparison.top_10_threshold || 75) ? "excellent" : 
                  data.prediction_score > (data.niche_comparison.niche_average || 50) ? "good" : "below" as const,
          explanation: getMagnetScoreExplanation(),
        },
        {
          metric: "Title Effectiveness",
          yours: Math.round(data.title_score),
          nicheAvg: 50,
          top10: 70,
          status: data.title_score >= 70 ? "excellent" : data.title_score >= 50 ? "good" : "below" as const,
          explanation: "Hook strength, emotional appeal, and keyword optimization",
        },
        {
          metric: "Thumbnail Impact",
          yours: Math.round(data.thumbnail_score),
          nicheAvg: 50,
          top10: 70,
          status: data.thumbnail_score >= 70 ? "excellent" : data.thumbnail_score >= 50 ? "good" : "below" as const,
          explanation: "Visual appeal, face presence, color contrast, and composition",
        },
        {
          metric: "Niche Ranking",
          yours: 100 - (data.niche_comparison.percentile || 50),
          nicheAvg: 50,
          top10: 10,
          status: (data.niche_comparison.percentile || 50) >= 90 ? "excellent" : 
                  (data.niche_comparison.percentile || 50) >= 70 ? "good" : "below" as const,
          explanation: `Where you rank among all ${data.niche_comparison.niche || "niche"} videos analyzed`,
          isPercentile: true,
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Video Analyzer
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Get ML-powered predictions with SHAP explanations for any YouTube video.
        </p>
      </div>

      {/* URL Input */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <label htmlFor="video-analyzer-url" className="sr-only">YouTube video URL</label>
              <Input
                id="video-analyzer-url"
                aria-label="YouTube video URL"
                placeholder="Paste a YouTube video URL..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
                className="pl-10 bg-secondary/50 border-border/50 h-11"
              />
            </div>
            <Button
              onClick={handleAnalyze}
              disabled={loading}
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <BarChart3 className="w-4 h-4 mr-2" />
                  Analyze
                </>
              )}
            </Button>
          </div>
          
          {/* Progress Bar */}
          {loading && (
            <div className="mt-5 space-y-3" aria-live="polite" aria-busy="true">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {ANALYSIS_STAGES[currentStage].label}...
                </span>
                <span className="text-cyan-glow font-medium">{overallProgress}%</span>
              </div>
              <Progress
                value={overallProgress}
                className="h-2 bg-secondary"
                aria-label={`Analysis progress: ${overallProgress}%, ${ANALYSIS_STAGES[currentStage].label}`}
              />
              <div className="flex gap-2">
                {ANALYSIS_STAGES.map((stage, idx) => (
                  <div key={stage.label} className="flex items-center gap-1.5">
                    {idx < currentStage ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : idx === currentStage ? (
                      <Loader2 className="w-3.5 h-3.5 text-cyan-glow animate-spin" />
                    ) : (
                      <div className="w-3.5 h-3.5 rounded-full border border-muted-foreground/30" />
                    )}
                    <span className={`text-[10px] ${
                      idx <= currentStage ? "text-foreground" : "text-muted-foreground"
                    }`}>
                      {stage.label.split(" ").slice(0, 2).join(" ")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Error State */}
      {error && (
        <Card className="bg-destructive/10 border-destructive/30">
          <CardContent className="p-5 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-destructive" />
            <div>
              <p className="text-sm font-medium text-destructive">Analysis Failed</p>
              <p className="text-xs text-muted-foreground">{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Selected History Item (when viewing past analysis) */}
      {selectedHistoryItem && !data && !loading && (
        <>
          {/* Score + Summary */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main Score */}
            <Card className="bg-card border-border/50">
              <CardContent className="p-6 flex flex-col items-center text-center">
                <div className="flex items-center gap-1.5 mb-3">
                  <Magnet className="w-3.5 h-3.5 text-cyan-glow" />
                  <p className="text-xs font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground">
                    Magnet Score
                  </p>
                </div>
                <div className="relative w-32 h-32 mb-4">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
                    <circle
                      cx="60" cy="60" r="52"
                      fill="none"
                      stroke="oklch(0.22 0.01 260)"
                      strokeWidth="8"
                    />
                    <circle
                      cx="60" cy="60" r="52"
                      fill="none"
                      stroke={
                        selectedHistoryItem.prediction_score >= 70 ? "oklch(0.76 0.15 160)" :
                        selectedHistoryItem.prediction_score >= 50 ? "oklch(0.82 0.15 80)" : "oklch(0.65 0.2 25)"
                      }
                      strokeWidth="8"
                      strokeLinecap="round"
                      strokeDasharray={`${(selectedHistoryItem.prediction_score / 100) * 327} 327`}
                    />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className={`text-4xl font-bold font-[var(--font-display)] ${
                      selectedHistoryItem.prediction_score >= 70 ? "text-emerald-400" :
                      selectedHistoryItem.prediction_score >= 50 ? "text-amber-glow" : "text-destructive"
                    }`}>
                      {selectedHistoryItem.prediction_score}
                    </span>
                  </div>
                </div>
                <Badge className={`${
                  selectedHistoryItem.prediction_score >= 70 ? "bg-emerald-400/20 text-emerald-400" :
                  selectedHistoryItem.prediction_score >= 50 ? "bg-amber-glow/20 text-amber-glow" :
                  "bg-destructive/20 text-destructive"
                }`}>
                  {selectedHistoryItem.prediction_tier?.replace(/_/g, " ").toUpperCase()}
                </Badge>
                <p className="text-xs text-muted-foreground mt-3 max-w-[200px]">
                  {selectedHistoryItem.prediction_score >= 70 ? "Strong vs this channel's norm" :
                   selectedHistoryItem.prediction_score >= 50 ? "On track vs this channel" : "Below this channel's norm"}
                </p>
              </CardContent>
            </Card>

            {/* Video Info */}
            <Card className="lg:col-span-2 bg-card border-border/50">
              <CardContent className="p-6">
                <div className="flex gap-4">
                  <img
                    src={`https://i.ytimg.com/vi/${selectedHistoryItem.video_id}/mqdefault.jpg`}
                    alt={selectedHistoryItem.title}
                    className="w-40 h-24 object-cover rounded-lg shrink-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <h3 className="font-semibold text-foreground line-clamp-2">
                          {selectedHistoryItem.title}
                        </h3>
                        <p className="text-xs text-muted-foreground mt-1">
                          Analyzed {selectedHistoryItem.analyzed_at ? new Date(selectedHistoryItem.analyzed_at).toLocaleDateString() : "Unknown"}
                        </p>
                      </div>
                      {/* Week 9 Connected Tools: history items are
                          dead-ends today — you can read the past
                          analysis but can't act on it. Re-edit jumps
                          you to Studio with the original YouTube URL
                          pre-loaded so the recommendations are one
                          click away from being applied. */}
                      <ReEditInStudioButton
                        videoUrl={`https://youtube.com/watch?v=${selectedHistoryItem.video_id}`}
                        title={selectedHistoryItem.title}
                      />
                    </div>
                    <div className="flex gap-6 mt-4">
                      <div>
                        <p className="text-xs text-muted-foreground">Title Score</p>
                        <p className={`text-xl font-bold ${
                          (selectedHistoryItem.title_score || 0) >= 70 ? "text-emerald-400" :
                          (selectedHistoryItem.title_score || 0) >= 50 ? "text-amber-glow" : "text-destructive"
                        }`}>
                          {selectedHistoryItem.title_score || "—"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Thumbnail Score</p>
                        <p className={`text-xl font-bold ${
                          (selectedHistoryItem.thumbnail_score || 0) >= 70 ? "text-emerald-400" :
                          (selectedHistoryItem.thumbnail_score || 0) >= 50 ? "text-amber-glow" : "text-destructive"
                        }`}>
                          {selectedHistoryItem.thumbnail_score || "—"}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Explanations */}
          {selectedHistoryItem.explanations && selectedHistoryItem.explanations.length > 0 && (
            <Card className="bg-card border-border/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">What's Driving This Score</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {selectedHistoryItem.explanations.slice(0, 8).map((exp, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <div className={`w-2 h-2 rounded-full ${
                        exp.direction === "positive" ? "bg-emerald-400" :
                        exp.direction === "negative" ? "bg-destructive" : "bg-muted-foreground"
                      }`} />
                      <span className="text-sm flex-1">{exp.feature}</span>
                      <span className={`text-xs font-medium ${
                        exp.direction === "positive" ? "text-emerald-400" :
                        exp.direction === "negative" ? "text-destructive" : "text-muted-foreground"
                      }`}>
                        {exp.impact || exp.value}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Recommendations */}
          {selectedHistoryItem.recommendations && selectedHistoryItem.recommendations.length > 0 && (
            <Card className="bg-card border-border/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Recommendations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {selectedHistoryItem.recommendations.map((rec, i) => (
                    <li key={i} className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                      <span className="w-5 h-5 rounded-full bg-cyan-glow/20 text-cyan-glow text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-sm text-foreground">{rec}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* No explanations/recommendations - show re-analyze prompt */}
          {(!selectedHistoryItem.explanations || selectedHistoryItem.explanations.length === 0) && (
            <Card className="bg-card border-border/50">
              <CardContent className="p-6 text-center">
                <p className="text-sm text-muted-foreground mb-3">
                  This analysis was saved before full insights were recorded.
                </p>
                <Button
                  onClick={handleAnalyze}
                  className="bg-cyan-glow hover:bg-cyan-glow/90 text-black"
                >
                  <BarChart3 className="w-4 h-4 mr-2" />
                  Re-analyze for Full Insights
                </Button>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {data && (
        <>
          {/* Niche Context Banner - Tailored Analysis Messaging */}
          <Card className="bg-gradient-to-r from-cyan-glow/5 via-purple-500/5 to-amber-glow/5 border-cyan-glow/20">
            <CardContent className="p-4">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                    <BarChart3 className="w-5 h-5 text-cyan-glow" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">Analysis Tailored for</span>
                      <Badge className="bg-cyan-glow/20 text-cyan-glow border-cyan-glow/30 font-semibold">
                        {data.niche_comparison?.niche || "General"}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Scored against {data.niche_comparison?.niche || "general"} best practices, not generic advice
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <div className="text-center">
                    <p className="text-muted-foreground">Your Rank</p>
                    <p className={`font-bold text-lg ${
                      (data.niche_comparison?.percentile || 50) > 70 ? "text-emerald-400" :
                      (data.niche_comparison?.percentile || 50) > 40 ? "text-cyan-glow" : "text-amber-glow"
                    }`}>
                      Top {100 - (data.niche_comparison?.percentile || 50)}%
                    </p>
                  </div>
                  <Separator orientation="vertical" className="h-8 bg-border/30" />
                  <div className="text-center">
                    <p className="text-muted-foreground">vs Niche Avg</p>
                    <p className={`font-bold text-lg ${
                      data.prediction_score > (data.niche_comparison?.niche_average || 50) ? "text-emerald-400" : "text-amber-glow"
                    }`}>
                      {data.prediction_score > (data.niche_comparison?.niche_average || 50) ? "+" : ""}
                      {Math.round(data.prediction_score - (data.niche_comparison?.niche_average || 50))}
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Stability Warning Banner - Anti-Over-Optimization */}
          {data.stability_warning && (
            <Card className={`border ${
              data.stability_warning.level === "high" 
                ? "bg-red-500/5 border-red-500/30" 
                : "bg-amber-500/5 border-amber-500/30"
            }`}>
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
                    data.stability_warning.level === "high" 
                      ? "bg-red-500/10" 
                      : "bg-amber-500/10"
                  }`}>
                    {data.stability_warning.level === "high" ? (
                      <AlertTriangle className="w-5 h-5 text-red-400" />
                    ) : (
                      <Shield className="w-5 h-5 text-amber-400" />
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-semibold ${
                        data.stability_warning.level === "high" ? "text-red-400" : "text-amber-400"
                      }`}>
                        {data.stability_warning.level === "high" ? "Over-Optimization Warning" : "Stability Notice"}
                      </span>
                      <Badge variant="outline" className={`text-[10px] ${
                        data.stability_warning.level === "high" 
                          ? "border-red-500/30 text-red-400" 
                          : "border-amber-500/30 text-amber-400"
                      }`}>
                        {data.stability_warning.analysis_count} analyses
                      </Badge>
                    </div>
                    <p className={`text-xs mt-1 ${
                      data.stability_warning.level === "high" ? "text-red-300/80" : "text-amber-300/80"
                    }`}>
                      {data.stability_warning.message}
                    </p>
                    <div className="mt-3 p-2 rounded bg-secondary/30">
                      <p className="text-xs text-muted-foreground">
                        <strong className="text-foreground">Our advice:</strong> {data.stability_warning.recommendation}
                      </p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Score + Summary */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main Score */}
            <Card className="bg-card border-border/50">
              <CardContent className="p-6 flex flex-col items-center text-center">
                <div className="flex items-center gap-1.5 mb-3">
                  <Magnet className="w-3.5 h-3.5 text-cyan-glow" />
                  <p className="text-xs font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground">
                    Magnet Score
                  </p>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger>
                        <Info className="w-3 h-3 text-muted-foreground/60 hover:text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[300px]">
                        <p className="text-xs">
                          {data.niche_comparison?.analysis_mode === "velocity" ? (
                            <>
                              <strong>Magnet Score (Velocity Mode)</strong> combines early performance momentum (70%) with packaging quality (30%). High scores mean the video is gaining traction AND has good title/thumbnail.
                            </>
                          ) : data.niche_comparison?.analysis_mode === "evaluation" ? (
                            <>
                              <strong>Magnet Score (Evaluation Mode)</strong> shows actual performance compared to your channel average. Based on real views and engagement data.
                            </>
                          ) : (
                            <>
                              <strong>Packaging Strength (Coaching)</strong> scores your title/thumbnail against proven packaging principles. It is NOT a performance prediction—packaging doesn't decide views. Post it and we detect breakouts within hours.
                            </>
                          )}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
                <div className="relative w-32 h-32 mb-4">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
                    <circle
                      cx="60" cy="60" r="52"
                      fill="none"
                      stroke="oklch(0.22 0.01 260)"
                      strokeWidth="8"
                    />
                    <circle
                      cx="60" cy="60" r="52"
                      fill="none"
                      stroke={data.prediction_score >= 70 ? "oklch(0.72 0.17 160)" : data.prediction_score >= 50 ? "oklch(0.82 0.15 200)" : "oklch(0.65 0.2 25)"}
                      strokeWidth="8"
                      strokeLinecap="round"
                      strokeDasharray={`${(data.prediction_score / 100) * 327} 327`}
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className={`text-3xl font-bold font-[var(--font-display)] ${
                      data.prediction_score >= 70 ? "text-emerald-400" : data.prediction_score >= 50 ? "text-cyan-glow" : "text-amber-glow"
                    }`}>
                      {Math.round(data.prediction_score)}
                    </span>
                    <span className="text-[10px] text-muted-foreground">/ 100</span>
                  </div>
                </div>
                <Badge className={
                  data.prediction_score >= 70
                    ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20"
                    : data.prediction_score >= 50
                    ? "bg-amber-glow/10 text-amber-glow border-amber-glow/20"
                    : "bg-destructive/10 text-destructive border-destructive/20"
                }>
                  {data.prediction_score >= 50 ? (
                  <TrendingUp className="w-3 h-3 mr-1" />
                  ) : (
                    <TrendingDown className="w-3 h-3 mr-1" />
                  )}
                  {data.score_label || "Performance vs your channel"}
                </Badge>
                {data.headline && (
                  <p className="text-sm font-semibold mt-2">{data.headline}</p>
                )}
                {data.disclaimer && (
                  <p className="text-[11px] text-amber-glow/80 mt-2 max-w-[280px] leading-snug">
                    {data.disclaimer}
                  </p>
                )}
                <p className="text-xs text-muted-foreground mt-3">
                  {data.niche_comparison?.analysis_mode === "velocity" ? (
                    data.prediction_score >= 70
                      ? "Strong momentum + good packaging—video is performing well."
                      : data.prediction_score >= 50
                      ? "Decent traction—check title/thumbnail scores for improvement opportunities."
                      : "Slow start—see recommendations below for packaging and promotion tips."
                  ) : data.niche_comparison?.analysis_mode === "evaluation" ? (
                    data.prediction_score >= 70
                      ? "This video outperformed your channel average."
                      : data.prediction_score >= 50
                      ? "This video matched your typical performance."
                      : "This video underperformed your channel average."
                  ) : (
                    data.prediction_score >= 70
                      ? "Strong packaging by the rubric. Packaging isn't what decides performance—post it and we'll detect within hours."
                      : data.prediction_score >= 50
                      ? "Solid packaging. See the rubric notes below to sharpen it before posting."
                      : "Packaging needs work—see the rubric weaknesses and rewrites below."
                  )}
                </p>
                {/* Credibility link: methodology page explains the
                    XGBoost model, balanced accuracy, training data,
                    and what the score does NOT guarantee. Surfaced
                    next to the headline number so any sceptical
                    creator can verify the claim instead of just
                    taking the number at face value. */}
                <a
                  href="/methodology"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block mt-2 text-[10px] text-cyan-glow hover:underline"
                >
                  How is this score calculated? →
                </a>
              </CardContent>
            </Card>

            {/* Video Details */}
            <Card className="lg:col-span-2 bg-card border-border/50">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm font-semibold">Video Details</CardTitle>
                  {/* "Re-edit in Studio" handoff. Routes the original
                      YouTube watch URL into the Studio editor, which
                      now resolves YT URLs to faststart MP4s via the
                      backend source-proxy (so Safari can play the
                      preview natively). Hidden when ``url`` is empty
                      because the user is viewing a history item. */}
                  {url.trim() && (
                    <ReEditInStudioButton
                      videoUrl={url.trim()}
                      title={data.title}
                    />
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-4">
                  <div className="w-40 h-24 rounded-lg bg-secondary/50 overflow-hidden shrink-0">
                    <div className="w-full h-full bg-gradient-to-br from-cyan-glow/20 to-amber-glow/20 flex items-center justify-center">
                      <Eye className="w-6 h-6 text-muted-foreground" />
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-foreground text-sm leading-tight">
                      {data.title}
                    </h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      {data.niche_comparison?.niche || "General"}
                    </p>
                    <div className="flex flex-wrap gap-3 mt-3">
                      <div className="flex items-center gap-1.5">
                        <ThumbsUp className="w-3.5 h-3.5 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Title: {data.title_score}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Thumb: {data.thumbnail_score}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <Separator className="bg-border/30" />

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  <div>
                    <p className="text-[10px] font-[var(--font-mono)] text-muted-foreground uppercase tracking-wider">
                      Prediction Tier
                    </p>
                    <p className="text-sm font-medium text-foreground mt-1 capitalize">
                      {data.prediction_tier}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] font-[var(--font-mono)] text-muted-foreground uppercase tracking-wider">
                      Niche
                    </p>
                    <p className="text-sm font-medium text-cyan-glow mt-1">
                      {data.niche_comparison?.niche || "General"}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] font-[var(--font-mono)] text-muted-foreground uppercase tracking-wider">
                      Percentile
                    </p>
                    <p className={`text-sm font-medium mt-1 ${
                      (data.niche_comparison?.percentile || 0) > 70 ? "text-emerald-400" : "text-foreground"
                    }`}>
                      Top {100 - (data.niche_comparison?.percentile || 50)}%
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Algorithm Signals (Start / Keep / Repeat) */}
          {data.algorithm_signals && (
            <Card className="bg-gradient-to-br from-cyan-glow/5 to-purple-500/5 border-cyan-glow/20">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-cyan-glow" />
                    Algorithm Signals
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger>
                          <Info className="w-3 h-3 text-muted-foreground/60 hover:text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-[320px]">
                          <p className="text-xs">
                            <strong>The 3 signals that determine reach:</strong><br />
                            <strong>START</strong> = clickability (title + thumbnail).<br />
                            <strong>KEEP</strong> = retention quality.<br />
                            <strong>REPEAT</strong> = saves, shares, return-viewer signal.<br />
                            The lowest signal is your bottleneck - fix it first.
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </CardTitle>
                  <Badge variant="outline" className="text-[10px] border-cyan-glow/30 text-cyan-glow">
                    Overall: {Math.round(data.algorithm_signals.overall_score)}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {[
                    { key: "start", label: "START", value: data.algorithm_signals.start_score, sub: "Click-through" },
                    { key: "keep", label: "KEEP", value: data.algorithm_signals.keep_score, sub: "Retention" },
                    { key: "repeat", label: "REPEAT", value: data.algorithm_signals.repeat_score, sub: "Return Viewers" },
                  ].map((s) => {
                    const isBottleneck = data.algorithm_signals?.bottleneck === s.key;
                    const valColor =
                      s.value >= 70 ? "text-emerald-400 bg-emerald-400" :
                      s.value >= 40 ? "text-cyan-glow bg-cyan-glow" :
                      "text-amber-glow bg-amber-glow";
                    const [textColor, barColor] = valColor.split(" ");
                    return (
                      <div
                        key={s.key}
                        className={`p-4 rounded-lg border ${
                          isBottleneck
                            ? "bg-amber-glow/5 border-amber-glow/30"
                            : "bg-secondary/30 border-border/30"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                              {s.label}
                            </p>
                            <p className="text-[9px] text-muted-foreground">{s.sub}</p>
                          </div>
                          {isBottleneck && (
                            <Badge className="bg-amber-glow/10 text-amber-glow border-amber-glow/30 text-[9px]">
                              Bottleneck
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-baseline gap-1 mb-2">
                          <span className={`text-2xl font-bold font-[var(--font-display)] ${textColor}`}>
                            {Math.round(s.value)}
                          </span>
                          <span className="text-[10px] text-muted-foreground">/ 100</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-secondary/40 overflow-hidden">
                          <div
                            className={`h-full ${barColor} transition-all`}
                            style={{ width: `${Math.max(2, Math.min(100, s.value))}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
                
                <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-glow/10 border border-amber-glow/20">
                  <AlertTriangle className="w-4 h-4 text-amber-glow shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-xs text-foreground font-medium mb-1">
                      {data.algorithm_signals.bottleneck === "balanced"
                        ? "Balanced signals"
                        : `${data.algorithm_signals.bottleneck.toUpperCase()} is the bottleneck`}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {data.algorithm_signals.bottleneck_message}
                    </p>
                    {/* Deep link into the dedicated bottleneck page.
                        We anchor on the specific bottleneck slug so
                        a user clicking "Learn more" while looking at
                        a Repeat bottleneck lands on the Repeat
                        section, not the top of the guide. */}
                    <a
                      href={
                        data.algorithm_signals.bottleneck === "balanced"
                          ? "/analyzer-guide"
                          : `/analyzer-guide#${data.algorithm_signals.bottleneck}`
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block mt-2 text-[10px] text-cyan-glow hover:underline"
                    >
                      What does this mean? Read the bottleneck guide →
                    </a>
                  </div>
                </div>

                {data.algorithm_signals.recommendations.length > 0 && (
                  <div>
                    <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
                      Recommended Actions
                    </p>
                    <ul className="space-y-1.5">
                      {/* Prefer the backend's structured CTAs when
                          present — they encode the deep link for each
                          rec without any regex matching. Fall back to
                          ``mapRecommendationToCta`` against the free
                          text for analyses produced by older backends. */}
                      {(() => {
                        const sig = data.algorithm_signals!;
                        const ctas = sig.recommendation_ctas?.length
                          ? sig.recommendation_ctas.map(structuredCtaToFrontend)
                          : sig.recommendations.map((rec) =>
                              mapRecommendationToCta(rec, { title: data.title }),
                            );
                        return ctas.map((cta, i) => (
                          <li
                            key={i}
                            className="flex items-start gap-2 text-xs text-foreground group"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5 text-cyan-glow shrink-0 mt-0.5" />
                            <span className="flex-1">{cta.label}</span>
                            <ToolHandoffButton cta={cta} size="xs" />
                          </li>
                        ));
                      })()}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Score Breakdown - Why This Score? (Mode-Aware) */}
          <Card className="bg-card border-border/50">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <HelpCircle className="w-4 h-4 text-cyan-glow" />
                    Why This Score?
                  </CardTitle>
                  {data.niche_comparison?.analysis_mode && (
                    <Badge 
                      variant="outline" 
                      className={`text-[10px] ${
                        data.niche_comparison.analysis_mode === "evaluation" 
                          ? "border-emerald-500/50 text-emerald-400 bg-emerald-500/10" 
                          : data.niche_comparison.analysis_mode === "velocity"
                          ? "border-amber-500/50 text-amber-400 bg-amber-500/10"
                          : "border-cyan-500/50 text-cyan-400 bg-cyan-500/10"
                      }`}
                    >
                      {data.niche_comparison.analysis_mode === "evaluation" 
                        ? "Actual Performance" 
                        : data.niche_comparison.analysis_mode === "velocity"
                        ? "Early Signals"
                        : "Prediction"}
                    </Badge>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowScoreBreakdown(!showScoreBreakdown)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {showScoreBreakdown ? (
                    <ChevronUp className="w-4 h-4" />
                  ) : (
                    <ChevronDown className="w-4 h-4" />
                  )}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {data.niche_comparison?.mode_description || "Transparent score calculation"}
              </p>
            </CardHeader>
            <CardContent>
              {/* EVALUATION MODE: Score based on actual performance */}
              {data.niche_comparison?.analysis_mode === "evaluation" ? (
                <div className="space-y-4">
                  {/* Performance-based scoring explanation */}
                  <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div className="flex items-center gap-2 mb-3">
                      <BarChart3 className="w-5 h-5 text-emerald-400" />
                      <span className="text-sm font-semibold text-emerald-400">Score Based on Actual Views</span>
                    </div>
                    <p className="text-xs text-muted-foreground mb-4">
                      This video is <strong className="text-foreground">{data.niche_comparison?.video_age_days || 7}+ days old</strong>, 
                      so your score reflects <strong className="text-foreground">actual performance</strong> rather than predictions.
                    </p>
                    
                    {data.niche_comparison?.actual_performance && (
                      <div className="grid grid-cols-2 gap-4">
                        <div className="p-3 rounded bg-background/50">
                          <div className="text-xs text-muted-foreground">Total Views</div>
                          <div className="text-xl font-bold text-foreground">
                            {data.niche_comparison.actual_performance.views.toLocaleString()}
                          </div>
                        </div>
                        <div className="p-3 rounded bg-background/50">
                          <div className="text-xs text-muted-foreground">vs Channel Median</div>
                          <div className={`text-xl font-bold ${
                            data.niche_comparison.actual_performance.vs_median >= 1 
                              ? "text-emerald-400" 
                              : "text-amber-400"
                          }`}>
                            {data.niche_comparison.actual_performance.vs_median.toFixed(1)}x
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Score breakdown for evaluation mode */}
                  <div className="p-4 rounded-lg bg-secondary/30">
                    <p className="text-xs font-semibold text-foreground mb-2">How the score is calculated:</p>
                    <ul className="space-y-1.5 text-xs text-muted-foreground">
                      <li className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        <span><strong className="text-foreground">3x+ median views</strong> → Score 95 (Viral Hit)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
                        <span><strong className="text-foreground">2x+ median views</strong> → Score 85 (Strong Performer)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                        <span><strong className="text-foreground">1.5x+ median views</strong> → Score 75 (Above Average)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        <span><strong className="text-foreground">At median views</strong> → Score 60 (Average)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
                        <span><strong className="text-foreground">Below median</strong> → Score decreases accordingly</span>
                      </li>
                    </ul>
                  </div>

                  {/* Note about title/thumbnail scores */}
                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <p className="text-xs text-amber-300">
                      <strong>Note:</strong> Title/Thumbnail scores are shown for reference but don't affect the final score 
                      in evaluation mode. For older videos, actual performance is the only metric that matters.
                    </p>
                  </div>
                </div>
              ) : data.niche_comparison?.analysis_mode === "velocity" ? (
                /* VELOCITY MODE: Score based on early trajectory */
                <div className="space-y-4">
                  <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="flex items-center gap-2 mb-3">
                      <TrendingUp className="w-5 h-5 text-amber-400" />
                      <span className="text-sm font-semibold text-amber-400">Early Performance Tracking</span>
                    </div>
                    <p className="text-xs text-muted-foreground mb-4">
                      This video is <strong className="text-foreground">{data.niche_comparison?.video_age_days || 1}-7 days old</strong>. 
                      Your score is based on <strong className="text-foreground">early view velocity</strong> and projected trajectory.
                    </p>
                    
                    {data.niche_comparison?.velocity_prediction && (
                      <div className="grid grid-cols-2 gap-4">
                        <div className="p-3 rounded bg-background/50">
                          <div className="text-xs text-muted-foreground">Predicted 30-day Views</div>
                          <div className="text-xl font-bold text-foreground">
                            {data.niche_comparison.velocity_prediction.predicted_views_day30.toLocaleString()}
                          </div>
                        </div>
                        <div className="p-3 rounded bg-background/50">
                          <div className="text-xs text-muted-foreground">Trajectory</div>
                          <div className={`text-xl font-bold ${
                            data.niche_comparison.velocity_prediction.trajectory === "viral" || 
                            data.niche_comparison.velocity_prediction.trajectory === "strong"
                              ? "text-emerald-400" 
                              : data.niche_comparison.velocity_prediction.trajectory === "normal"
                              ? "text-amber-400"
                              : "text-red-400"
                          }`}>
                            {data.niche_comparison.velocity_prediction.trajectory.charAt(0).toUpperCase() + 
                             data.niche_comparison.velocity_prediction.trajectory.slice(1)}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="p-3 rounded-lg bg-secondary/30">
                    <p className="text-xs text-muted-foreground">
                      <strong className="text-foreground">How velocity scoring works:</strong> We compare your video's 
                      views-per-hour against the channel's historical patterns to predict final performance. 
                      Check back after 7 days for the final evaluation score.
                    </p>
                  </div>
                </div>
              ) : (
                /* PREDICTION MODE: Score based on title/thumbnail/channel */
                <>
                  {/* Score Contribution Donut Chart */}
                  <div className="flex flex-col lg:flex-row gap-6 items-center">
                    {/* Donut Chart */}
                    <div className="relative w-40 h-40 shrink-0">
                      <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
                        {/* Background circle */}
                        <circle
                          cx="60" cy="60" r="45"
                          fill="none"
                          stroke="oklch(0.22 0.01 260)"
                          strokeWidth="20"
                        />
                        {/* Title contribution (40% weight) - Purple */}
                        <circle
                          cx="60" cy="60" r="45"
                          fill="none"
                          stroke="oklch(0.65 0.25 300)"
                          strokeWidth="20"
                          strokeDasharray={`${0.40 * 283} 283`}
                          strokeDashoffset="0"
                        />
                        {/* Thumbnail contribution (45% weight) - Cyan */}
                        <circle
                          cx="60" cy="60" r="45"
                          fill="none"
                          stroke="oklch(0.75 0.15 200)"
                          strokeWidth="20"
                          strokeDasharray={`${0.45 * 283} 283`}
                          strokeDashoffset={`${-0.40 * 283}`}
                        />
                        {/* Channel contribution (15% weight) - Amber */}
                        <circle
                          cx="60" cy="60" r="45"
                          fill="none"
                          stroke="oklch(0.82 0.15 80)"
                          strokeWidth="20"
                          strokeDasharray={`${0.15 * 283} 283`}
                          strokeDashoffset={`${-0.85 * 283}`}
                        />
                      </svg>
                      <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <span className="text-2xl font-bold font-[var(--font-display)] text-foreground">
                          {Math.round(data.prediction_score)}
                        </span>
                        <span className="text-[10px] text-muted-foreground">TOTAL</span>
                      </div>
                    </div>

                    {/* Score Components */}
                    <div className="flex-1 grid grid-cols-1 sm:grid-cols-3 gap-4 w-full">
                      {/* Title Score */}
                      <div className="p-4 rounded-lg bg-purple-500/10 border border-purple-500/20">
                        <div className="flex items-center gap-2 mb-2">
                          <Type className="w-4 h-4 text-purple-400" />
                          <span className="text-xs font-medium text-purple-400">Title</span>
                          <Badge variant="outline" className="ml-auto text-[10px] border-purple-500/30 text-purple-400">
                            40% weight
                          </Badge>
                        </div>
                        <div className="text-2xl font-bold text-foreground">
                          {Math.round(data.title_score)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Contributes {Math.round(data.title_score * 0.40)} points
                        </div>
                      </div>

                      {/* Thumbnail Score */}
                      <div className="p-4 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                        <div className="flex items-center gap-2 mb-2">
                          <Image className="w-4 h-4 text-cyan-400" />
                          <span className="text-xs font-medium text-cyan-400">Thumbnail</span>
                          <Badge variant="outline" className="ml-auto text-[10px] border-cyan-500/30 text-cyan-400">
                            45% weight
                          </Badge>
                        </div>
                        <div className="text-2xl font-bold text-foreground">
                          {Math.round(data.thumbnail_score)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Contributes {Math.round(data.thumbnail_score * 0.45)} points
                        </div>
                      </div>

                      {/* Channel Score */}
                      <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20">
                        <div className="flex items-center gap-2 mb-2">
                          <Users className="w-4 h-4 text-amber-400" />
                          <span className="text-xs font-medium text-amber-400">Channel</span>
                          <Badge variant="outline" className="ml-auto text-[10px] border-amber-500/30 text-amber-400">
                            15% weight
                          </Badge>
                        </div>
                        <div className="text-2xl font-bold text-foreground">
                          {Math.round(data.channel_score || 50)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          Contributes {Math.round((data.channel_score || 50) * 0.15)} points
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {showScoreBreakdown && (
                    <div className="mt-6 pt-4 border-t border-border/30">
                      <p className="text-xs text-muted-foreground mb-4">
                        <strong>How we calculate your score:</strong> Each component is evaluated independently, 
                        then combined using fixed weights: Title (40%) + Thumbnail (45%) + Channel Context (15%) = Final Score
                      </p>
                      
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {/* Title Details */}
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-purple-400">Title Score Factors</p>
                          <ul className="space-y-1 text-xs text-muted-foreground">
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                              Hook pattern strength
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                              Emotional appeal
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                              Length optimization
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                              Keyword relevance
                            </li>
                          </ul>
                        </div>

                        {/* Thumbnail Details */}
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-cyan-400">Thumbnail Score Factors</p>
                          <ul className="space-y-1 text-xs text-muted-foreground">
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                              Face detection & emotion
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                              Color & contrast
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                              Text overlay clarity
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                              Composition quality
                            </li>
                          </ul>
                        </div>

                        {/* Channel Details */}
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-amber-400">Channel Context Factors</p>
                          <ul className="space-y-1 text-xs text-muted-foreground">
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                              Historical performance
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                              Recent momentum
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                              Engagement rate
                            </li>
                            <li className="flex items-center gap-2">
                              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                              Niche positioning
                            </li>
                          </ul>
                        </div>
                      </div>

                      <div className="mt-4 p-3 rounded-lg bg-secondary/30">
                        <p className="text-xs text-muted-foreground">
                          <strong className="text-foreground">Consistency guarantee:</strong> Unlike other tools, 
                          your score is deterministic—the same video will always receive the same score. 
                          No random variation, no mysterious changes.
                        </p>
                      </div>
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          {/* SHAP + Benchmarks */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Feature Breakdown */}
            <CollapsibleCard
              title="What's Driving This Score"
              subtitle="Factors helping and hurting performance"
              icon={<BarChart3 className="w-4 h-4 text-cyan-glow" />}
            >
                {data?.explanations && data.explanations.length > 0 ? (
                  <div className="space-y-2">
                    {data.explanations.map((exp: FeatureExplanation, index: number) => {
                      const impact = parseFloat(String(exp.impact).replace('+', ''));
                      const isPositive = exp.direction === "positive";
                      const isNeutral = exp.direction === "neutral" || impact === 0;
                      
                      // Determine label and color based on impact
                      let label: string;
                      let bgColor: string;
                      let textColor: string;
                      
                      if (isNeutral) {
                        label = "Neutral";
                        bgColor = "bg-slate-500/20";
                        textColor = "text-slate-400";
                      } else if (isPositive) {
                        if (impact >= 8) {
                          label = "Strong Boost";
                          bgColor = "bg-emerald-500/20";
                          textColor = "text-emerald-400";
                        } else if (impact >= 5) {
                          label = "Boost";
                          bgColor = "bg-green-500/20";
                          textColor = "text-green-400";
                        } else {
                          label = "Slight Boost";
                          bgColor = "bg-green-500/10";
                          textColor = "text-green-300";
                        }
                      } else {
                        if (impact <= -6) {
                          label = "Strong Drag";
                          bgColor = "bg-red-500/20";
                          textColor = "text-red-400";
                        } else if (impact <= -3) {
                          label = "Drag";
                          bgColor = "bg-orange-500/20";
                          textColor = "text-orange-400";
                        } else {
                          label = "Slight Drag";
                          bgColor = "bg-orange-500/10";
                          textColor = "text-orange-300";
                        }
                      }
                      
                      return (
                        <div
                          key={index}
                          className="flex items-center justify-between p-3 rounded-lg bg-secondary/30 hover:bg-secondary/50 transition-colors"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              {isPositive && !isNeutral && (
                                <TrendingUp className="h-3.5 w-3.5 text-emerald-400 flex-shrink-0" />
                              )}
                              {!isPositive && !isNeutral && (
                                <TrendingDown className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />
                              )}
                              {isNeutral && (
                                <div className="h-3.5 w-3.5 rounded-full bg-slate-500/50 flex-shrink-0" />
                              )}
                              <span className="text-sm font-medium text-foreground truncate">
                                {exp.feature}
                              </span>
                            </div>
                            <p className="text-xs text-muted-foreground mt-0.5 truncate">
                              {exp.value}
                            </p>
                          </div>
                          <Badge 
                            variant="outline" 
                            className={`ml-2 ${bgColor} ${textColor} border-0 text-[10px] font-medium`}
                          >
                            {label}
                          </Badge>
                        </div>
                      );
                    })}
                </div>
                ) : (
                  <p className="text-sm text-muted-foreground py-8 text-center">
                    Analyze a video to see feature breakdown
                  </p>
                )}
            </CollapsibleCard>

            {/* Niche Benchmarks - Enhanced */}
            <CollapsibleCard
              title={`How You Compare in ${data.niche_comparison?.niche || "Your Niche"}`}
              subtitle="Your video vs niche average and top performers"
              icon={<TrendingUp className="w-4 h-4 text-cyan-glow" />}
              badge={
                <Badge variant="outline" className="text-[10px] border-cyan-glow/30 text-cyan-glow">
                  Niche-Specific
                </Badge>
              }
            >
                <div className="space-y-4">
                  {/* Legend */}
                  <div className="flex items-center gap-4 text-[10px] text-muted-foreground pb-2 border-b border-border/30">
                    <span className="flex items-center gap-1">
                      <div className="w-2 h-2 rounded-full bg-cyan-glow" />
                      You
                    </span>
                    <span className="flex items-center gap-1">
                      <div className="w-2 h-2 rounded-full bg-muted-foreground/50" />
                      Niche Avg
                    </span>
                    <span className="flex items-center gap-1">
                      <div className="w-2 h-2 rounded-full bg-emerald-400" />
                      Top 10%
                    </span>
                  </div>

                  {nicheBenchmarks.map((item) => (
                    <div key={item.metric} className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium text-foreground">{item.metric}</p>
                          <p className="text-[10px] text-muted-foreground">{item.explanation}</p>
                        </div>
                        <Badge 
                          variant="outline" 
                          className={`text-[10px] ${
                            item.status === "excellent" 
                              ? "border-emerald-400/30 text-emerald-400 bg-emerald-400/10" 
                              : item.status === "good"
                              ? "border-cyan-glow/30 text-cyan-glow bg-cyan-glow/10"
                              : "border-amber-glow/30 text-amber-glow bg-amber-glow/10"
                          }`}
                        >
                          {item.status === "excellent" ? "Top 10%" : item.status === "good" ? "Above Avg" : "Below Avg"}
                        </Badge>
                      </div>
                      
                      {/* Visual comparison bar */}
                      <div className="relative h-6 bg-secondary/50 rounded-full overflow-hidden">
                        {/* Niche average marker */}
                        <div 
                          className="absolute top-0 bottom-0 w-0.5 bg-muted-foreground/50 z-10"
                          style={{ left: `${item.isPercentile ? 50 : item.nicheAvg}%` }}
                        />
                        {/* Top 10% marker */}
                        <div 
                          className="absolute top-0 bottom-0 w-0.5 bg-emerald-400 z-10"
                          style={{ left: `${item.isPercentile ? 90 : item.top10}%` }}
                        />
                        {/* Your score bar */}
                        <div 
                          className={`absolute top-0 bottom-0 left-0 rounded-full ${
                            item.status === "excellent" ? "bg-emerald-400/60" : 
                            item.status === "good" ? "bg-cyan-glow/60" : "bg-amber-glow/60"
                          }`}
                          style={{ width: `${item.isPercentile ? (100 - item.yours) : Math.min(item.yours, 100)}%` }}
                        />
                        {/* Your score indicator */}
                        <div 
                          className={`absolute top-1 bottom-1 w-4 rounded-full flex items-center justify-center text-[8px] font-bold ${
                            item.status === "excellent" ? "bg-emerald-400 text-black" : 
                            item.status === "good" ? "bg-cyan-glow text-black" : "bg-amber-glow text-black"
                          }`}
                          style={{ left: `calc(${item.isPercentile ? (100 - item.yours) : Math.min(item.yours, 100)}% - 8px)` }}
                        >
                          {item.isPercentile ? `${item.yours}%` : item.yours}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Niche-specific disclaimer */}
                <div className="mt-4 pt-3 border-t border-border/30">
                  <p className="text-[10px] text-muted-foreground">
                    <strong className="text-foreground">Niche-aware analysis:</strong> These benchmarks are calculated 
                    specifically for <span className="text-cyan-glow">{data.niche_comparison?.niche || "your niche"}</span>, 
                    not generic advice that ignores your content category.
                  </p>
                </div>
            </CollapsibleCard>
          </div>

          {/* Recommendations */}
          {data.recommendations && data.recommendations.length > 0 && (
            <CollapsibleCard
              title="Recommendations"
              subtitle="Actionable improvements for better performance"
              icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}
            >
              <ul className="space-y-2">
                {data.recommendations.map((rec, i) => {
                  // Same CTA mapping as Algorithm Signals — keeps the
                  // "click-through to the right tool with this video's
                  // title pre-filled" behavior consistent everywhere.
                  const cta = mapRecommendationToCta(rec, { title: data.title });
                  return (
                    <li
                      key={i}
                      className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30"
                    >
                      <span className="w-5 h-5 rounded-full bg-cyan-glow/20 text-cyan-glow text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-sm text-foreground flex-1">{cta.label}</span>
                      <ToolHandoffButton cta={cta} size="sm" />
                    </li>
                  );
                })}
              </ul>
            </CollapsibleCard>
          )}
        </>
      )}

      {/* Analysis History */}
      {history.length > 0 && (
        <CollapsibleCard
          title="Previously Analyzed"
          subtitle="Your recent video analyses"
          icon={<Clock className="w-4 h-4 text-cyan-glow" />}
          defaultOpen={false}
        >
          {historyLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-2">
              {history.map((item) => (
                <div
                  key={item.id}
                  onClick={() => loadHistoryItem(item.video_id)}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                    selectedHistoryItem?.video_id === item.video_id 
                      ? 'bg-cyan-glow/10 border border-cyan-glow/30' 
                      : 'bg-secondary/30 hover:bg-secondary/50'
                  }`}
                >
                  <img
                    src={`https://i.ytimg.com/vi/${item.video_id}/mqdefault.jpg`}
                    alt={item.title}
                    className="w-24 h-14 object-cover rounded"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{item.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.analyzed_at ? new Date(item.analyzed_at).toLocaleDateString() : "Unknown date"}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <div className={`text-lg font-bold ${
                      item.prediction_score >= 70 ? "text-emerald-400" :
                      item.prediction_score >= 50 ? "text-amber-glow" : "text-destructive"
                    }`}>
                      {item.prediction_score}
                    </div>
                    <Badge 
                      variant="outline" 
                      className={`text-[10px] ${
                        item.prediction_tier === "viral" ? "border-emerald-400/50 text-emerald-400" :
                        item.prediction_tier === "high" ? "border-cyan-glow/50 text-cyan-glow" :
                        item.prediction_tier === "medium" ? "border-amber-glow/50 text-amber-glow" :
                        "border-muted-foreground/50 text-muted-foreground"
                      }`}
                    >
                      {item.prediction_tier}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CollapsibleCard>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Re-edit in Studio" deep-link button.
//
// ``buildStudioLink`` returns a Promise (it hashes the source URL to
// derive a stable clipKey) so we wrap it in a small async-aware
// component instead of forcing every call site to manage that
// lifecycle. Resolves to a plain ``<Link>`` once the URL is ready;
// shows a disabled placeholder in the meantime so the layout doesn't
// shift when the link slots in.
// ---------------------------------------------------------------------------
function ReEditInStudioButton({
  videoUrl,
  title,
}: {
  videoUrl: string;
  title?: string;
}) {
  const [href, setHref] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // No start/end here — the Analyzer doesn't know the source
        // duration; Studio will fall back to a placeholder window
        // and the user can trim once the preview loads.
        const link = await buildStudioLink({
          sourceUrl: videoUrl,
          title,
          // Week 10 attribution: tag this hop with the Analyzer
          // origin so when the resulting render is published, the
          // post-publish metrics roll up into the "edits initiated
          // from the Analyzer" cohort. No specific tool key because
          // the Analyzer's "Re-edit" button is generic — the cohort
          // is more interesting as a baseline than as a per-tool
          // attribution.
          cta: { tool: "analyzer_reedit", from: "analyzer" },
        });
        if (!cancelled) setHref(link);
      } catch {
        if (!cancelled) setHref(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoUrl, title]);

  if (!href) {
    return (
      <Button
        size="sm"
        variant="outline"
        disabled
        className="h-7 text-xs border-cyan-glow/30 text-cyan-glow/50"
      >
        <Scissors className="w-3 h-3 mr-1" />
        Re-edit in Studio
      </Button>
    );
  }

  return (
    <Link href={href}>
      <Button
        size="sm"
        variant="outline"
        className="h-7 text-xs border-cyan-glow/40 text-cyan-glow hover:bg-cyan-glow/10"
      >
        <Scissors className="w-3 h-3 mr-1" />
        Re-edit in Studio
      </Button>
    </Link>
  );
}

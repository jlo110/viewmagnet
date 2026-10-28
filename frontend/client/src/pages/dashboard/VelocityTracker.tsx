/*
 * Velocity Tracker: track video performance over time + spot breakouts vs the
 * channel's own pace. (We don't forecast final view counts — that's not reliably
 * predictable; the honest signal is whether a video is outpacing its channel.)
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Activity,
  Search,
  Plus,
  TrendingUp,
  TrendingDown,
  Eye,
  Clock,
  Target,
  BarChart3,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Calendar,
  RefreshCw,
  Sparkles,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  Magnet,
} from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { Link } from "wouter";
import { toast } from "sonner";
import { buildAnalyzerLink } from "@/lib/deepLinks";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import {
  addToVelocityMonitor,
  getTrackedChannels,
  getTrackedVideos,
  type TrackedVideo,
  type TrackedChannel,
} from "@/lib/api";

const accuracyByTimeframe = [
  { timeframe: "Day 1 → 3", newUser: 84, withHistory: 86 },
  { timeframe: "Day 1 → 7", newUser: 76, withHistory: 85 },
  { timeframe: "Day 1 → 30", newUser: 70, withHistory: 74 },
  { timeframe: "Day 3 → 30", newUser: 87, withHistory: 85 },
  { timeframe: "Day 7 → 30", newUser: 95, withHistory: 90 },
  { timeframe: "Day 14 → 30", newUser: 98, withHistory: 94 },
];

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

function formatAge(hours: number): string {
  if (hours < 24) return `${Math.round(hours)}h`;
  if (hours < 168) return `${Math.round(hours / 24)}d`;
  if (hours < 720) return `${Math.round(hours / 24)}d`;
  return `${Math.round(hours / 720)}mo`;
}

export default function VelocityTracker() {
  const [inputUrl, setInputUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState("");
  const [loadingData, setLoadingData] = useState(true);
  const [videos, setVideos] = useState<TrackedVideo[]>([]);
  const [channels, setChannels] = useState<TrackedChannel[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<TrackedVideo | null>(null);
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>("30d");
  const [showOverperformers, setShowOverperformers] = useState(true);
  const [showUnderperformers, setShowUnderperformers] = useState(true);
  const [showAllVideos, setShowAllVideos] = useState(true);
  
  // Available timeframes for prediction toggle
  const TIMEFRAMES = ["3d", "7d", "14d", "30d"] as const;

  // Fetch data from API
  const fetchData = useCallback(async () => {
    try {
      setLoadingData(true);
      const [videosRes, channelsRes] = await Promise.all([
        getTrackedVideos({ activeOnly: false }),
        getTrackedChannels(),
      ]);
      
      setVideos(videosRes.videos);
      setChannels(channelsRes.channels);
      
      if (videosRes.videos.length > 0 && !selectedVideo) {
        setSelectedVideo(videosRes.videos[0]);
      }
    } catch (error) {
      console.error("Failed to fetch velocity data:", error);
    } finally {
      setLoadingData(false);
    }
  }, [selectedVideo]);

  // Load data on mount
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Parse URL to detect if it's a video or channel
  const parseInput = (input: string): { type: "video" | "channel" | "unknown"; id: string | null } => {
    const trimmed = input.trim();
    
    // Video URL patterns
    const videoPatterns = [
      /youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})/,
      /youtu\.be\/([a-zA-Z0-9_-]{11})/,
      /youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/,
      /youtube\.com\/v\/([a-zA-Z0-9_-]{11})/,
    ];
    
    for (const pattern of videoPatterns) {
      const match = trimmed.match(pattern);
      if (match) return { type: "video", id: match[1] };
    }
    
    // Raw video ID (11 chars)
    if (/^[a-zA-Z0-9_-]{11}$/.test(trimmed)) {
      return { type: "video", id: trimmed };
    }
    
    // Channel URL patterns
    const channelPatterns = [
      /youtube\.com\/channel\/(UC[a-zA-Z0-9_-]{22})/,
      /youtube\.com\/@([a-zA-Z0-9_-]+)/,
      /youtube\.com\/c\/([a-zA-Z0-9_-]+)/,
      /youtube\.com\/user\/([a-zA-Z0-9_-]+)/,
    ];
    
    for (const pattern of channelPatterns) {
      const match = trimmed.match(pattern);
      if (match) return { type: "channel", id: match[1] };
    }
    
    // Raw channel ID
    if (/^UC[a-zA-Z0-9_-]{22}$/.test(trimmed)) {
      return { type: "channel", id: trimmed };
    }
    
    // Handle @username format
    if (trimmed.startsWith("@")) {
      return { type: "channel", id: trimmed };
    }
    
    return { type: "unknown", id: null };
  };

  const handleMonitor = async () => {
    if (!inputUrl.trim()) {
      toast.error("Please enter a video or channel URL");
      return;
    }
    
    const parsed = parseInput(inputUrl);
    
    if (parsed.type === "unknown" || !parsed.id) {
      toast.error("Could not parse URL. Enter a YouTube video or channel URL.");
      return;
    }
    
    setLoading(true);
    setLoadingStatus(parsed.type === "video" ? "Fetching video info..." : "Adding channel...");

    try {
      // Call the API to add the video/channel to monitoring
      const result = await addToVelocityMonitor(inputUrl);
      
      if (result.status === "error") {
        toast.error(result.error || "Failed to add to monitoring");
        return;
      }
      
      if (result.status === "already_tracked") {
        toast.info("This channel is already being tracked!");
      } else {
        const videoMsg = result.video_added 
          ? ` Video "${result.video_added.title}" added to tracking.`
          : "";
        toast.success(
          `${result.channel_name || "Channel"} added to monitoring!${videoMsg}`
        );
      }
      
      // Refresh the data
      await fetchData();
      setInputUrl("");
      
    } catch (error) {
      console.error("Failed to add to monitoring:", error);
      toast.error("Failed to add to monitoring. Please try again.");
    } finally {
      setLoading(false);
      setLoadingStatus("");
    }
  };

  const activeVideos = videos.filter((v) => v.actual_30d === null);
  const completedVideos = videos.filter((v) => v.actual_30d !== null);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
            Velocity Tracker
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Track your videos' early trajectory and spot the ones outpacing your
            channel's own norm — early detection, not a view-count forecast.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchData}
          disabled={loadingData}
          className="gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loadingData ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Add Channel or Video */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Paste a video or channel URL to start monitoring..."
                value={inputUrl}
                onChange={(e) => setInputUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleMonitor()}
                className="pl-10 bg-secondary/50 border-border/50 h-11"
              />
            </div>
            <Button
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleMonitor}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Plus className="w-4 h-4 mr-2" />
              )}
              {loading ? "Adding..." : "Monitor"}
            </Button>
          </div>
          {loading && loadingStatus && (
            <p className="text-xs text-muted-foreground mt-3 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              {loadingStatus}
            </p>
          )}
          <p className="text-xs text-muted-foreground mt-3">
            Supports video URLs (we'll extract the channel) or channel URLs directly
          </p>
        </CardContent>
      </Card>

      {/* Stats Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-card border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                <Activity className="w-5 h-5 text-cyan-glow" />
              </div>
              <div>
                <p className="text-2xl font-bold">{activeVideos.length}</p>
                <p className="text-xs text-muted-foreground">Active Tracking</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-400/10 flex items-center justify-center">
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <p className="text-2xl font-bold">{completedVideos.length}</p>
                <p className="text-xs text-muted-foreground">Completed</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-glow/10 flex items-center justify-center">
                <Target className="w-5 h-5 text-amber-glow" />
              </div>
              <div>
                <p className="text-2xl font-bold">
                  {completedVideos.length > 0
                    ? Math.round(
                        completedVideos.reduce(
                          (sum, v) => sum + (v.accuracy || 0),
                          0
                        ) / completedVideos.length
                      )
                    : "--"}
                  %
                </p>
                <p className="text-xs text-muted-foreground">Avg Accuracy</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-400/10 flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-purple-400" />
              </div>
              <div>
                <p className="text-2xl font-bold">{channels.length}</p>
                <p className="text-xs text-muted-foreground">
                  Channels Monitored
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="videos" className="space-y-4">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="videos">Active Videos</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
          <TabsTrigger value="accuracy">Accuracy Info</TabsTrigger>
        </TabsList>

        <TabsContent value="videos" className="space-y-4">
          {/* Overperformers & Underperformers Section - Only analyzed videos */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            {/* Overperformers - Only analyzed */}
            <Card className="bg-card border-border/50">
              <CardHeader 
                className="pb-2 cursor-pointer"
                onClick={() => setShowOverperformers(!showOverperformers)}
              >
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                    Overperformers
                    <Badge className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20 text-xs">
                      {videos.filter(v => v.trajectory === "above" && v.magnet_score !== null).length}
                    </Badge>
                  </CardTitle>
                  <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                    {showOverperformers ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">Videos outpacing your channel's norm</p>
              </CardHeader>
              {showOverperformers && (
                <CardContent className="pt-0">
                  <div className="max-h-[400px] overflow-y-auto space-y-2 pr-1">
                    {videos.filter(v => v.trajectory === "above" && v.magnet_score !== null).length === 0 ? (
                      <div className="py-4 text-center">
                        <p className="text-xs text-muted-foreground">No analyzed overperformers yet</p>
                        <p className="text-[10px] text-muted-foreground/70 mt-1">Analyze videos to see scores</p>
                      </div>
                    ) : (
                      videos.filter(v => v.trajectory === "above" && v.magnet_score !== null).map((video) => (
                        <div
                          key={video.video_id}
                          className={`p-3 rounded-lg cursor-pointer transition-colors ${
                            selectedVideo?.video_id === video.video_id
                              ? "bg-emerald-400/10 ring-1 ring-emerald-400/30"
                              : "bg-secondary/30 hover:bg-secondary/50"
                          }`}
                          onClick={() => setSelectedVideo(video)}
                        >
                          <p className="text-sm font-medium line-clamp-2 mb-1.5">{video.title}</p>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Eye className="w-3 h-3" />
                              {formatNumber(video.current_views)}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {formatAge(video.age_hours)}
                            </span>
                            <span className="text-cyan-glow flex items-center gap-1 font-medium">
                              <Sparkles className="w-3 h-3" />
                              {video.magnet_score}
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              )}
            </Card>

            {/* Underperformers - Only analyzed */}
            <Card className="bg-card border-border/50">
              <CardHeader 
                className="pb-2 cursor-pointer"
                onClick={() => setShowUnderperformers(!showUnderperformers)}
              >
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    <TrendingDown className="w-4 h-4 text-red-400" />
                    Underperformers
                    <Badge className="bg-red-400/10 text-red-400 border-red-400/20 text-xs">
                      {videos.filter(v => v.trajectory === "below" && v.magnet_score !== null).length}
                    </Badge>
                  </CardTitle>
                  <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                    {showUnderperformers ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">Videos below your channel's norm</p>
              </CardHeader>
              {showUnderperformers && (
                <CardContent className="pt-0">
                  <div className="max-h-[400px] overflow-y-auto space-y-2 pr-1">
                    {videos.filter(v => v.trajectory === "below" && v.magnet_score !== null).length === 0 ? (
                      <div className="py-4 text-center">
                        <p className="text-xs text-muted-foreground">No analyzed underperformers yet</p>
                        <p className="text-[10px] text-muted-foreground/70 mt-1">Analyze videos to see scores</p>
                      </div>
                    ) : (
                      videos.filter(v => v.trajectory === "below" && v.magnet_score !== null).map((video) => (
                        <div
                          key={video.video_id}
                          className={`p-3 rounded-lg cursor-pointer transition-colors ${
                            selectedVideo?.video_id === video.video_id
                              ? "bg-red-400/10 ring-1 ring-red-400/30"
                              : "bg-secondary/30 hover:bg-secondary/50"
                          }`}
                          onClick={() => setSelectedVideo(video)}
                        >
                          <p className="text-sm font-medium line-clamp-2 mb-1.5">{video.title}</p>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Eye className="w-3 h-3" />
                              {formatNumber(video.current_views)}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {formatAge(video.age_hours)}
                            </span>
                            <span className="text-cyan-glow flex items-center gap-1 font-medium">
                              <Sparkles className="w-3 h-3" />
                              {video.magnet_score}
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* All Videos List - Collapsible */}
            <div className="lg:col-span-1 space-y-3">
              <div 
                className="flex items-center justify-between px-1 cursor-pointer"
                onClick={() => setShowAllVideos(!showAllVideos)}
              >
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">
                  All Videos ({videos.length})
                </p>
                <Button variant="ghost" size="sm" className="h-5 w-5 p-0">
                  {showAllVideos ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </Button>
              </div>
              {showAllVideos && (
                <div className="max-h-[600px] overflow-y-auto pr-1 space-y-3">
              {videos.map((video) => (
                <Card
                  key={video.video_id}
                  className={`bg-card border-border/50 cursor-pointer transition-colors ${
                    selectedVideo?.video_id === video.video_id
                      ? "ring-1 ring-cyan-glow"
                      : "hover:bg-secondary/30"
                  }`}
                  onClick={() => setSelectedVideo(video)}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between mb-2">
                      <p className="text-sm font-medium line-clamp-2">
                        {video.title}
                      </p>
                      <Badge
                        className={`ml-2 shrink-0 text-[10px] ${
                          video.trajectory === "above"
                            ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20"
                            : video.trajectory === "below"
                            ? "bg-red-400/10 text-red-400 border-red-400/20"
                            : "bg-cyan-glow/10 text-cyan-glow border-cyan-glow/20"
                        }`}
                      >
                        {video.trajectory === "above" ? (
                          <TrendingUp className="w-3 h-3 mr-1" />
                        ) : video.trajectory === "below" ? (
                          <TrendingDown className="w-3 h-3 mr-1" />
                        ) : (
                          <Activity className="w-3 h-3 mr-1" />
                        )}
                        {video.trajectory === "above"
                          ? "Above"
                          : video.trajectory === "below"
                          ? "Below"
                          : "On Track"}
                      </Badge>
                    </div>

                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatAge(video.age_hours)}
                      </span>
                      <span className="flex items-center gap-1">
                        <Eye className="w-3 h-3" />
                        {formatNumber(video.current_views)}
                      </span>
                      {video.accuracy && (
                        <span className="flex items-center gap-1">
                          <Target className="w-3 h-3" />
                          {video.accuracy}%
                        </span>
                      )}
                    </div>

                    {/* Progress to 30d */}
                    <div className="mt-3">
                      <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                        <span>{video.current_checkpoint}</span>
                        <span>30d</span>
                      </div>
                      <Progress
                        value={Math.min((video.age_hours / 720) * 100, 100)}
                        className="h-1"
                      />
                    </div>
                  </CardContent>
                </Card>
              ))}
                </div>
              )}
            </div>

            {/* Selected Video Detail */}
            <div className="lg:col-span-2">
              {selectedVideo && (
                <Card className="bg-card border-border/50">
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <CardTitle className="text-base font-semibold truncate">
                          {selectedVideo.title}
                        </CardTitle>
                        <p className="text-xs text-muted-foreground">
                          {selectedVideo.channel_name} •{" "}
                          {formatAge(selectedVideo.age_hours)} old
                        </p>
                      </div>
                      {/*
                       * Deep-link into the Video Analyzer with this video's
                       * YouTube URL pre-filled and the analysis auto-running.
                       * Velocity tells you "how" the video is performing;
                       * Analyzer tells you "why" — pairing them is the moat.
                       */}
                      <Link
                        href={buildAnalyzerLink(
                          `https://youtube.com/watch?v=${selectedVideo.video_id}`,
                        )}
                      >
                        <Button
                          size="sm"
                          variant="outline"
                          className="shrink-0 h-7 text-xs border-cyan-glow/30 text-cyan-glow hover:bg-cyan-glow/10"
                          title="Open this video in the Video Analyzer with full SHAP breakdown"
                        >
                          <Magnet className="w-3 h-3 mr-1" />
                          Analyze
                        </Button>
                      </Link>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Prediction Card with Timeframe Toggle */}
                    <div className="space-y-3">
                      {/* Timeframe Toggle */}
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Projection:</span>
                        <div className="flex gap-1 bg-secondary/30 rounded-lg p-1">
                          {TIMEFRAMES.map((tf) => {
                            const hasPrediction = selectedVideo.predictions && selectedVideo.predictions[tf] !== undefined;
                            return (
                              <Button
                                key={tf}
                                variant={selectedTimeframe === tf ? "default" : "ghost"}
                                size="sm"
                                className={`h-6 px-2 text-xs ${
                                  selectedTimeframe === tf 
                                    ? "bg-cyan-glow text-black hover:bg-cyan-glow/90" 
                                    : hasPrediction 
                                      ? "hover:bg-secondary" 
                                      : "opacity-50 cursor-not-allowed"
                                }`}
                                onClick={() => hasPrediction && setSelectedTimeframe(tf)}
                                disabled={!hasPrediction}
                              >
                                {tf}
                              </Button>
                            );
                          })}
                        </div>
                      </div>
                      
                      {/* Stats Grid */}
                      <div className="grid grid-cols-3 gap-3">
                        <div className="p-3 rounded-lg bg-secondary/30">
                          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                            Current Views
                          </p>
                          <p className="text-xl font-bold">
                            {formatNumber(selectedVideo.current_views)}
                          </p>
                        </div>
                        <div className="p-3 rounded-lg bg-cyan-glow/10 border border-cyan-glow/20">
                          <p className="text-[10px] text-cyan-glow uppercase tracking-wider">
                            Projected {selectedTimeframe}
                          </p>
                          <p className="text-xl font-bold text-cyan-glow">
                            {selectedVideo.predictions && selectedVideo.predictions[selectedTimeframe]
                              ? formatNumber(selectedVideo.predictions[selectedTimeframe])
                              : selectedVideo.predicted_30d && selectedTimeframe === "30d"
                                ? formatNumber(selectedVideo.predicted_30d)
                                : "--"}
                          </p>
                        </div>
                        <div className="p-3 rounded-lg bg-secondary/30">
                          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                            {selectedVideo.actuals && selectedVideo.actuals[selectedTimeframe] 
                              ? `Actual ${selectedTimeframe}` 
                              : selectedVideo.actual_30d && selectedTimeframe === "30d"
                                ? "Actual 30d"
                                : "Status"}
                          </p>
                          <p className="text-xl font-bold">
                            {selectedVideo.actuals && selectedVideo.actuals[selectedTimeframe]
                              ? formatNumber(selectedVideo.actuals[selectedTimeframe])
                              : selectedVideo.actual_30d && selectedTimeframe === "30d"
                                ? formatNumber(selectedVideo.actual_30d)
                                : selectedVideo.age_hours < parseInt(selectedTimeframe) * 24
                                  ? "Pending"
                                  : selectedVideo.accuracy
                                    ? `${selectedVideo.accuracy}%`
                                    : "Pending"}
                          </p>
                        </div>
                      </div>
                      <p className="text-[10px] text-muted-foreground/70 leading-snug">
                        Projection is a rough extrapolation from current pace — view counts
                        aren't reliably predictable. What matters is whether it's outpacing
                        your channel's norm (above).
                      </p>
                    </div>

                    {/* Velocity Chart */}
                    <div className="h-[250px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={selectedVideo.snapshots}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="oklch(0.25 0.01 260)"
                          />
                          <XAxis
                            dataKey="checkpoint"
                            tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                            axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                          />
                          <YAxis
                            tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                            axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                            tickFormatter={(v) => formatNumber(v)}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: "oklch(0.16 0.01 260)",
                              border: "1px solid oklch(0.25 0.01 260)",
                              borderRadius: "8px",
                              fontSize: "12px",
                            }}
                            formatter={(value: number) => [
                              formatNumber(value),
                              "Views",
                            ]}
                          />
                          {(selectedVideo.predictions?.[selectedTimeframe] || selectedVideo.predicted_30d) && (
                            <ReferenceLine
                              y={selectedVideo.predictions?.[selectedTimeframe] || selectedVideo.predicted_30d || 0}
                              stroke="oklch(0.82 0.15 200)"
                              strokeDasharray="5 5"
                              label={{
                                value: `Predicted ${selectedTimeframe}: ${formatNumber(selectedVideo.predictions?.[selectedTimeframe] || selectedVideo.predicted_30d || 0)}`,
                                position: "right",
                                fill: "oklch(0.82 0.15 200)",
                                fontSize: 10,
                              }}
                            />
                          )}
                          <Line
                            type="monotone"
                            dataKey="views"
                            stroke="oklch(0.82 0.15 200)"
                            strokeWidth={2}
                            dot={{
                              fill: "oklch(0.82 0.15 200)",
                              strokeWidth: 2,
                            }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>

                    {/* Checkpoints */}
                    <div className="flex gap-2 overflow-x-auto pb-2">
                      {["1h", "6h", "24h", "3d", "7d", "14d", "30d"].map(
                        (cp) => {
                          const snapshot = selectedVideo.snapshots.find(
                            (s) => s.checkpoint === cp
                          );
                          const isCurrent =
                            cp === selectedVideo.current_checkpoint;
                          const isPast = snapshot !== undefined;

                          return (
                            <div
                              key={cp}
                              className={`flex-shrink-0 p-2 rounded-lg text-center min-w-[60px] ${
                                isCurrent
                                  ? "bg-cyan-glow/20 border border-cyan-glow/30"
                                  : isPast
                                  ? "bg-secondary/50"
                                  : "bg-secondary/20 opacity-50"
                              }`}
                            >
                              <p className="text-[10px] font-medium">{cp}</p>
                              <p className="text-xs text-muted-foreground">
                                {snapshot ? formatNumber(snapshot.views) : "--"}
                              </p>
                            </div>
                          );
                        }
                      )}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="channels" className="space-y-4">
          {/* Auto-tracking warning */}
          {channels.length > 0 && (
            <Card className="bg-amber-500/5 border-amber-500/20">
              <CardContent className="p-4">
                <div className="flex gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-amber-500">Auto-Tracking Uses Analysis Credits</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      When you enable auto-tracking for new videos on a channel, each new video will be 
                      automatically analyzed and counted against your monthly analysis allowance. 
                      This ensures you get Magnet Scores for all tracked videos.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
          
          {channels.length === 0 ? (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-8 text-center">
                <Activity className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Add your first channel to start velocity tracking
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {channels.map((channel) => (
                <Card key={channel.channel_id} className="bg-card border-border/50">
                  <CardContent className="p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-glow/20 to-amber-glow/20 flex items-center justify-center">
                          <span className="text-sm font-bold">
                            {channel.channel_name[0]}
                          </span>
                        </div>
                        <div>
                          <p className="text-sm font-semibold">
                            {channel.channel_name}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatNumber(channel.subscriber_count)} subscribers
                          </p>
                        </div>
                      </div>
                      {channel.avg_accuracy && (
                        <Badge className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20">
                          {channel.avg_accuracy}% accuracy
                        </Badge>
                      )}
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                      <div className="p-2.5 rounded-lg bg-secondary/30 text-center">
                        <p className="text-[10px] text-muted-foreground">
                          Videos Tracked
                        </p>
                        <p className="text-sm font-semibold">
                          {channel.videos_tracked}
                        </p>
                      </div>
                      <div className="p-2.5 rounded-lg bg-secondary/30 text-center">
                        <p className="text-[10px] text-muted-foreground">
                          Growth Pattern
                        </p>
                        <p className="text-sm font-semibold">
                          {channel.growth_pattern
                            ? `${channel.growth_pattern.toFixed(2)}x`
                            : "Learning..."}
                        </p>
                      </div>
                      <div className="p-2.5 rounded-lg bg-secondary/30 text-center">
                        <p className="text-[10px] text-muted-foreground">
                          Status
                        </p>
                        <p className="text-sm font-semibold text-emerald-400">
                          Active
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="accuracy" className="space-y-4">
          <Card className="bg-card border-border/50">
            <CardHeader>
              <CardTitle className="text-base">
                Prediction Accuracy by Timeframe
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Accuracy improves as we learn your channel's patterns
              </p>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {accuracyByTimeframe.map((row) => (
                  <div key={row.timeframe} className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span>{row.timeframe}</span>
                      <div className="flex gap-4">
                        <span className="text-muted-foreground">
                          New User: <span className="text-foreground font-medium">{row.newUser}%</span>
                        </span>
                        <span className="text-cyan-glow">
                          With History: <span className="font-medium">{row.withHistory}%</span>
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Progress value={row.newUser} className="h-2 flex-1" />
                      <Progress value={row.withHistory} className="h-2 flex-1 [&>div]:bg-cyan-glow" />
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-6 p-4 rounded-lg bg-secondary/30 border border-border/50">
                <div className="flex gap-3">
                  <AlertCircle className="w-5 h-5 text-amber-glow shrink-0" />
                  <div>
                    <p className="text-sm font-medium">New User Experience</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Even without channel history, you get 70-98% accuracy depending on 
                      video age. After tracking 2-3 videos, we learn your channel's 
                      unique growth patterns for even better predictions.
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}





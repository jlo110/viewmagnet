/*
 * Dashboard Overview: Key metrics, performance chart, recent analyses, quick actions
 * Design: Signal Flow dark theme with cyan/amber accents
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  ArrowRight,
  Sparkles,
  Zap,
  Eye,
  FileText,
  Image,
  Target,
  Loader2,
  Youtube,
  Link as LinkIcon,
  Users,
  PlayCircle,
  X,
  Info,
  Magnet,
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Pencil,
} from "lucide-react";
import {
  Tooltip as UITooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Link, useLocation } from "wouter";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useEffect, useState, useCallback } from "react";
import { 
  getDashboardStats, 
  getChannelOverview, 
  startYouTubeAuth,
  getYouTubeConnections,
  disconnectYouTube,
  analyzeVideo,
  type UserDashboardStats, 
  type ChannelOverview,
  type YouTubeConnection,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { listSessions } from "@/studio/api";
import { proxyVideoUrl } from "@/studio/sourceUrl";
import type { EditSession } from "@/studio/types";

type RecentEdit = Pick<
  EditSession,
  | "clip_key"
  | "title"
  | "source_video_url"
  | "last_render_status"
  | "last_render_url"
  | "updated_at"
>;

// Same compact relative-time formatter the Drafts page uses, inlined to
// avoid adding date-fns just for this widget.
function recentEditTimeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

const quickActions = [
  { title: "Analyze Video", icon: BarChart3, href: "/dashboard/analyzer", color: "cyan" },
  { title: "Generate Title", icon: Sparkles, href: "/dashboard/titles", color: "amber" },
  { title: "Create Thumbnail", icon: Image, href: "/dashboard/thumbnails", color: "cyan" },
  { title: "Write Script", icon: FileText, href: "/dashboard/scripts", color: "amber" },
];

export default function Overview() {
  const [, navigate] = useLocation();
  const { user } = useAuth();
  const [stats, setStats] = useState<UserDashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [channelData, setChannelData] = useState<ChannelOverview | null>(null);
  const [youtubeConnection, setYoutubeConnection] = useState<YouTubeConnection | null>(null);
  const [channelInput, setChannelInput] = useState("");
  const [connectingChannel, setConnectingChannel] = useState(false);
  const [connectingYouTube, setConnectingYouTube] = useState(false);
  const [showChannelInput, setShowChannelInput] = useState(false);
  const [selectedVideos, setSelectedVideos] = useState<Set<string>>(new Set());
  const [analyzingVideos, setAnalyzingVideos] = useState(false);
  const [analyzingProgress, setAnalyzingProgress] = useState({ current: 0, total: 0 });
  const [recentUploadsExpanded, setRecentUploadsExpanded] = useState(true);
  const [recentEdits, setRecentEdits] = useState<RecentEdit[] | null>(null);

  const loadChannelData = useCallback(async (channelUrl: string) => {
    try {
      setConnectingChannel(true);
      const data = await getChannelOverview(channelUrl);
      setChannelData(data);
      localStorage.setItem("connectedChannel", JSON.stringify(data));
      toast.success(`Connected to ${data.channel_name}`);
      setShowChannelInput(false);
      setChannelInput("");
    } catch (error) {
      console.error("Failed to connect channel:", error);
      toast.error("Failed to connect channel. Check the URL and try again.");
    } finally {
      setConnectingChannel(false);
    }
  }, []);

  const handleYouTubeConnect = async () => {
    if (!user?.id) {
      toast.error("Please log in to connect your YouTube account.");
      return;
    }
    try {
      setConnectingYouTube(true);
      const { auth_url } = await startYouTubeAuth();
      // Redirect to YouTube OAuth
      window.location.href = auth_url;
    } catch (error) {
      console.error("Failed to start YouTube auth:", error);
      toast.error("Failed to connect to YouTube. Please try again.");
      setConnectingYouTube(false);
    }
  };

  const handleYouTubeDisconnect = async () => {
    if (!youtubeConnection || !user?.id) return;
    try {
      await disconnectYouTube(youtubeConnection.channel_id);
      setYoutubeConnection(null);
      setChannelData(null);
      localStorage.removeItem("youtubeConnection");
      localStorage.removeItem("connectedChannel");
      toast.success("YouTube account disconnected");
    } catch (error) {
      console.error("Failed to disconnect:", error);
      toast.error("Failed to disconnect. Please try again.");
    }
  };

  const disconnectChannel = () => {
    setChannelData(null);
    setYoutubeConnection(null);
    setSelectedVideos(new Set());
    localStorage.removeItem("connectedChannel");
    localStorage.removeItem("youtubeConnection");
    toast.success("Channel disconnected");
  };

  const toggleVideoSelection = (videoId: string) => {
    setSelectedVideos(prev => {
      const newSet = new Set(prev);
      if (newSet.has(videoId)) {
        newSet.delete(videoId);
      } else {
        newSet.add(videoId);
      }
      return newSet;
    });
  };

  const selectAllVideos = () => {
    if (channelData?.recent_videos) {
      setSelectedVideos(new Set(channelData.recent_videos.map(v => v.video_id)));
    }
  };

  const deselectAllVideos = () => {
    setSelectedVideos(new Set());
  };

  const analyzeSelectedVideos = async () => {
    if (selectedVideos.size === 0) {
      toast.error("Please select at least one video to analyze");
      return;
    }

    setAnalyzingVideos(true);
    setAnalyzingProgress({ current: 0, total: selectedVideos.size });

    const videoIds = Array.from(selectedVideos);
    let successCount = 0;

    for (let i = 0; i < videoIds.length; i++) {
      const videoId = videoIds[i];
      setAnalyzingProgress({ current: i + 1, total: videoIds.length });
      
      try {
        await analyzeVideo({ url: `https://youtube.com/watch?v=${videoId}` });
        successCount++;
      } catch (error) {
        console.error(`Failed to analyze video ${videoId}:`, error);
      }
    }

    setAnalyzingVideos(false);
    setSelectedVideos(new Set());
    
    if (successCount > 0) {
      toast.success(`Analyzed ${successCount} video${successCount > 1 ? 's' : ''} successfully! Redirecting to view results...`);
      // Refresh stats
      try {
        const data = await getDashboardStats();
        setStats(data);
      } catch (error) {
        console.error("Failed to refresh stats:", error);
      }
      // Navigate to Video Analyzer to see results
      setTimeout(() => {
        navigate("/dashboard/analyzer");
      }, 500);
    } else {
      toast.error("Failed to analyze videos. Please try again.");
    }
  };

  useEffect(() => {
    const fetchStats = async () => {
      if (!user?.id) {
        setLoading(false);
        return;
      }
      setStatsError(null);
      try {
        const data = await getDashboardStats();
        setStats(data);
      } catch (error) {
        console.error("Failed to fetch dashboard stats:", error);
        setStatsError("Failed to load dashboard stats. Please try again later.");
      } finally {
        setLoading(false);
      }
    };
    fetchStats();

    // Check for YouTube OAuth connection
    const checkYouTubeConnection = async () => {
      if (!user?.id) return;
      try {
        const { connections } = await getYouTubeConnections();
        if (connections.length > 0) {
          const conn = connections[0];
          setYoutubeConnection(conn);
          localStorage.setItem("youtubeConnection", JSON.stringify(conn));
          // Load full channel data
          loadChannelData(conn.channel_id);
        }
      } catch (error) {
        console.error("Failed to check YouTube connections:", error);
      }
    };

    // Check URL params for OAuth callback success
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get("connected") === "true") {
      toast.success("YouTube account connected successfully!");
      // Clean up URL
      window.history.replaceState({}, "", window.location.pathname);
      if (user?.id) checkYouTubeConnection();
    } else {
      // Load saved connection or channel
      const savedConnection = localStorage.getItem("youtubeConnection");
      const savedChannel = localStorage.getItem("connectedChannel");
      
      if (savedConnection) {
        try {
          const parsed = JSON.parse(savedConnection);
          setYoutubeConnection(parsed);
          loadChannelData(parsed.channel_id);
        } catch (e) {
          console.error("Failed to parse saved connection:", e);
          checkYouTubeConnection();
        }
      } else if (savedChannel) {
        try {
          const parsed = JSON.parse(savedChannel);
          setChannelData(parsed);
          loadChannelData(parsed.channel_id);
        } catch (e) {
          console.error("Failed to parse saved channel:", e);
        }
      } else {
        checkYouTubeConnection();
      }
    }
  }, [loadChannelData, user?.id]);

  // Load the user's three most-recent Studio drafts. Best-effort; if
  // the endpoint is unavailable we just hide the widget.
  useEffect(() => {
    if (!user?.id) {
      setRecentEdits([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const items = await listSessions();
        if (!cancelled) setRecentEdits(items.slice(0, 3));
      } catch {
        if (!cancelled) setRecentEdits([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
      </div>
    );
  }

  if (statsError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-destructive">{statsError}</p>
        <Button 
          variant="outline" 
          onClick={() => window.location.reload()}
        >
          Retry
        </Button>
      </div>
    );
  }

  const performanceData = stats?.performance_trend || [];
  const recentAnalyses = stats?.recent_analyses || [];

  const formatNumber = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Dashboard
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {channelData 
            ? `Welcome back! Here's how ${channelData.channel_name} is performing.`
            : "Connect your channel to see personalized insights."}
        </p>
      </div>

      {/* Channel Connection Card */}
      {!channelData ? (
        <Card className="bg-gradient-to-r from-cyan-glow/5 to-amber-glow/5 border-cyan-glow/20">
          <CardContent className="p-6">
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-full bg-cyan-glow/10 flex items-center justify-center">
                  <Youtube className="w-6 h-6 text-cyan-glow" />
                </div>
                <div>
                  <h3 className="font-semibold">Connect Your Channel</h3>
                  <p className="text-sm text-muted-foreground">
                    Get personalized insights for your YouTube channel
                  </p>
                </div>
              </div>
              
              <div className="flex flex-col sm:flex-row gap-3">
                {/* YouTube OAuth Connect */}
                <Button
                  onClick={handleYouTubeConnect}
                  disabled={connectingYouTube}
                  className="bg-red-600 hover:bg-red-700 text-white flex-1 sm:flex-none"
                >
                  {connectingYouTube ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Youtube className="w-4 h-4 mr-2" />
                  )}
                  Connect with YouTube
                </Button>
                
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">or</span>
                </div>
                
                {/* Manual Channel Link */}
                {showChannelInput ? (
                  <div className="flex gap-2 flex-1">
                    <Input
                      placeholder="Paste channel URL or @handle..."
                      value={channelInput}
                      onChange={(e) => setChannelInput(e.target.value)}
                      className="flex-1"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && channelInput.trim()) {
                          loadChannelData(channelInput.trim());
                        }
                      }}
                    />
                    <Button
                      onClick={() => loadChannelData(channelInput.trim())}
                      disabled={!channelInput.trim() || connectingChannel}
                      variant="secondary"
                    >
                      {connectingChannel ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <LinkIcon className="w-4 h-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setShowChannelInput(false)}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    onClick={() => setShowChannelInput(true)}
                  >
                    <LinkIcon className="w-4 h-4 mr-2" />
                    Add Channel Link
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-card border-border/50">
          <CardContent className="p-6">
            <div className="flex flex-col md:flex-row md:items-center gap-4">
              <div className="flex items-center gap-4">
                {channelData.thumbnail_url ? (
                  <img
                    src={channelData.thumbnail_url}
                    alt={channelData.channel_name}
                    className="w-14 h-14 rounded-full"
                  />
                ) : (
                  <div className="w-14 h-14 rounded-full bg-cyan-glow/10 flex items-center justify-center">
                    <Youtube className="w-7 h-7 text-cyan-glow" />
                  </div>
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-lg">{channelData.channel_name}</h3>
                    {youtubeConnection && (
                      <Badge className="bg-red-600/10 text-red-500 border-red-600/20 text-[10px]">
                        <Youtube className="w-3 h-3 mr-1" />
                        Connected
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground mt-1">
                    <span className="flex items-center gap-1">
                      <Users className="w-3.5 h-3.5" />
                      {formatNumber(channelData.subscriber_count)} subscribers
                    </span>
                    <span className="flex items-center gap-1">
                      <PlayCircle className="w-3.5 h-3.5" />
                      {channelData.video_count} videos
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex-1 flex flex-wrap gap-4 md:justify-center">
                <div className="text-center px-4">
                  <p className="text-2xl font-bold text-cyan-glow">
                    {formatNumber(channelData.total_views)}
                  </p>
                  <p className="text-xs text-muted-foreground">Total Views</p>
                </div>
                <div className="text-center px-4">
                  <p className="text-2xl font-bold text-amber-glow">
                    {formatNumber(channelData.avg_views_per_video)}
                  </p>
                  <p className="text-xs text-muted-foreground">Avg Views (Recent)</p>
                </div>
              </div>
              <div className="md:ml-auto">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={youtubeConnection ? handleYouTubeDisconnect : disconnectChannel}
                  className="text-muted-foreground hover:text-destructive"
                >
                  Disconnect
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Videos Selection - shown when channel is connected */}
      {channelData && channelData.recent_videos && channelData.recent_videos.length > 0 && (
        <Card className="bg-card border-border/50">
          <CardHeader 
            className={`${recentUploadsExpanded ? 'pb-3' : 'pb-0'} cursor-pointer`}
            onClick={() => setRecentUploadsExpanded(!recentUploadsExpanded)}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div>
                  <CardTitle className="text-base font-medium flex items-center gap-2">
                    <PlayCircle className="w-4 h-4 text-cyan-glow" />
                    Recent Uploads
                    <Badge variant="outline" className="text-[10px] ml-1">
                      {channelData.recent_videos.length}
                    </Badge>
                  </CardTitle>
                  <p className="text-xs text-muted-foreground mt-1">
                    {recentUploadsExpanded 
                      ? "Select videos to analyze and get Magnet Scores" 
                      : "Click to expand and select videos"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                {recentUploadsExpanded && (
                  <>
                    {selectedVideos.size > 0 ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={deselectAllVideos}
                        className="text-xs h-7"
                      >
                        Deselect All
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={selectAllVideos}
                        className="text-xs h-7"
                      >
                        Select All
                      </Button>
                    )}
                    <Button
                      size="sm"
                      onClick={analyzeSelectedVideos}
                      disabled={selectedVideos.size === 0 || analyzingVideos}
                      className="bg-cyan-glow hover:bg-cyan-glow/90 text-black h-7"
                    >
                      {analyzingVideos ? (
                        <>
                          <Loader2 className="w-3 h-3 mr-1.5 animate-spin" />
                          Analyzing {analyzingProgress.current}/{analyzingProgress.total}
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-3 h-3 mr-1.5" />
                          Analyze Selected ({selectedVideos.size})
                        </>
                      )}
                    </Button>
                  </>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    setRecentUploadsExpanded(!recentUploadsExpanded);
                  }}
                >
                  {recentUploadsExpanded ? (
                    <ChevronUp className="w-4 h-4" />
                  ) : (
                    <ChevronDown className="w-4 h-4" />
                  )}
                </Button>
              </div>
            </div>
          </CardHeader>
          {recentUploadsExpanded && (
          <CardContent className="pt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {channelData.recent_videos.map((video) => (
                <div
                  key={video.video_id}
                  onClick={() => !analyzingVideos && toggleVideoSelection(video.video_id)}
                  className={`
                    flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all
                    ${selectedVideos.has(video.video_id) 
                      ? 'border-cyan-glow/50 bg-cyan-glow/5' 
                      : 'border-border/50 hover:border-border bg-card/50 hover:bg-card'
                    }
                    ${analyzingVideos ? 'opacity-50 cursor-not-allowed' : ''}
                  `}
                >
                  <Checkbox
                    checked={selectedVideos.has(video.video_id)}
                    onCheckedChange={() => !analyzingVideos && toggleVideoSelection(video.video_id)}
                    className="mt-0.5 data-[state=checked]:bg-cyan-glow data-[state=checked]:border-cyan-glow"
                  />
                  <div className="flex-1 min-w-0">
                    {video.thumbnail_url && (
                      <img
                        src={video.thumbnail_url}
                        alt={video.title}
                        className="w-full h-20 object-cover rounded mb-2"
                      />
                    )}
                    <p className="text-sm font-medium line-clamp-2 leading-tight">
                      {video.title}
                    </p>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Eye className="w-3 h-3" />
                        {formatNumber(video.view_count)}
                      </span>
                      <span>•</span>
                      <span>{video.published_at}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
          )}
        </Card>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="bg-card border-border/50">
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-xs text-muted-foreground font-medium">Avg. Magnet Score</p>
                  <TooltipProvider>
                    <UITooltip>
                      <TooltipTrigger>
                        <Info className="w-3 h-3 text-muted-foreground/60 hover:text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[250px]">
                        <p className="text-xs">
                          Measures how well your video's title, thumbnail, and timing are optimized to attract clicks relative to your channel's typical performance.
                        </p>
                      </TooltipContent>
                    </UITooltip>
                  </TooltipProvider>
                </div>
                <p className="text-2xl font-bold font-[var(--font-display)] mt-1 text-cyan-glow">
                  {stats?.avg_prediction_score?.toFixed(1) || "—"}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                <Magnet className="w-5 h-5 text-cyan-glow" />
              </div>
            </div>
            <div className="flex items-center gap-1 mt-3">
              <TrendingUp className="w-3 h-3 text-emerald-400" />
              <span className="text-xs text-muted-foreground">based on {stats?.videos_analyzed || 0} videos</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground font-medium">
                  {channelData ? "Recent 10 Videos" : "Total Views (30d)"}
                </p>
                <p className="text-2xl font-bold font-[var(--font-display)] mt-1">
                  {channelData 
                    ? formatNumber(channelData.recent_views)
                    : stats?.total_views_30d 
                      ? `${(stats.total_views_30d / 1000).toFixed(1)}K` 
                      : "—"}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-amber-glow/10 flex items-center justify-center">
                <Eye className="w-5 h-5 text-amber-glow" />
              </div>
            </div>
            <div className="flex items-center gap-1 mt-3">
              <span className="text-xs text-muted-foreground">
                {channelData ? "Combined views" : "Connect channel for live data"}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground font-medium">Videos Analyzed</p>
                <p className="text-2xl font-bold font-[var(--font-display)] mt-1">
                  {stats?.videos_analyzed || 0}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-cyan-glow" />
              </div>
            </div>
            <div className="mt-3">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground">{stats?.analyses_remaining || 500} / 500 remaining</span>
              </div>
              <Progress value={((500 - (stats?.analyses_remaining || 500)) / 500) * 100} className="h-1.5" />
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardContent className="p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-1">
                  <p className="text-xs text-muted-foreground font-medium">High Performers</p>
                  <TooltipProvider>
                    <UITooltip>
                      <TooltipTrigger>
                        <Info className="w-3 h-3 text-muted-foreground/60 hover:text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-[220px]">
                        <p className="text-xs">
                          Percentage of your analyzed videos with a Magnet Score above 50 (the baseline average).
                        </p>
                      </TooltipContent>
                    </UITooltip>
                  </TooltipProvider>
                </div>
                <p className="text-2xl font-bold font-[var(--font-display)] mt-1 text-emerald-400">
                  {stats?.above_baseline_pct || 0}%
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-400/10 flex items-center justify-center">
                <Zap className="w-5 h-5 text-emerald-400" />
              </div>
            </div>
            <div className="flex items-center gap-1 mt-3">
              {(stats?.above_baseline_pct || 0) > 50 ? (
              <TrendingUp className="w-3 h-3 text-emerald-400" />
              ) : (
                <TrendingDown className="w-3 h-3 text-amber-glow" />
              )}
              <span className="text-xs text-muted-foreground">score &gt;50 of {stats?.videos_analyzed || 0} videos</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Chart + Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Performance Chart */}
        <Card className="lg:col-span-2 bg-card border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold">Performance Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={performanceData}>
                  <defs>
                    <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="oklch(0.82 0.15 200)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="oklch(0.82 0.15 200)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.25 0.01 260)" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                    axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                    axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                    tickLine={false}
                    domain={[40, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.16 0.01 260)",
                      border: "1px solid oklch(0.25 0.01 260)",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                    labelStyle={{ color: "oklch(0.92 0.01 260)" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="score"
                    stroke="oklch(0.82 0.15 200)"
                    strokeWidth={2}
                    fill="url(#scoreGradient)"
                    name="Magnet Score"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {quickActions.map((action) => (
              <Link key={action.href} href={action.href}>
                <button className="w-full flex items-center gap-3 p-3 rounded-lg bg-secondary/50 hover:bg-secondary transition-colors text-left group">
                  <div
                    className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                      action.color === "cyan"
                        ? "bg-cyan-glow/10 group-hover:bg-cyan-glow/20"
                        : "bg-amber-glow/10 group-hover:bg-amber-glow/20"
                    } transition-colors`}
                  >
                    <action.icon
                      className={`w-4 h-4 ${
                        action.color === "cyan" ? "text-cyan-glow" : "text-amber-glow"
                      }`}
                    />
                  </div>
                  <span className="text-sm font-medium text-foreground">{action.title}</span>
                  <ArrowRight className="w-4 h-4 text-muted-foreground ml-auto group-hover:translate-x-0.5 transition-transform" />
                </button>
              </Link>
            ))}

            <div className="pt-3 mt-3 border-t border-border/30">
              <p className="text-xs text-muted-foreground mb-2">Your Niche</p>
              <Badge className="bg-cyan-glow/10 text-cyan-glow border-cyan-glow/20 hover:bg-cyan-glow/20">
                Technology
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recent Analyses */}
      <CollapsibleCard
        title="Recent Analyses"
        icon={<BarChart3 className="w-4 h-4 text-cyan-glow" />}
        badge={
          <Link href="/dashboard/analyzer" onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground h-6 px-2">
              View All <ArrowRight className="w-3 h-3 ml-1" />
            </Button>
          </Link>
        }
      >
        <div className="space-y-1">
          {recentAnalyses.map((analysis, i) => (
            <Link
              key={i}
              href="/dashboard/analyzer"
              className="flex items-center gap-4 p-3 rounded-lg hover:bg-secondary/30 transition-colors cursor-pointer"
            >
              {/* Thumbnail */}
              <img
                src={`https://i.ytimg.com/vi/${analysis.video_id}/mqdefault.jpg`}
                alt={analysis.title}
                className="w-16 h-9 object-cover rounded shrink-0"
              />

              {/* Score */}
              <div
                className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 font-bold font-[var(--font-display)] text-sm ${
                  analysis.score >= 75
                    ? "bg-emerald-400/10 text-emerald-400"
                    : analysis.score >= 60
                    ? "bg-amber-glow/10 text-amber-glow"
                    : "bg-destructive/10 text-destructive"
                }`}
              >
                {analysis.score}
              </div>

              {/* Title & meta */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">
                  {analysis.title}
                </p>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-xs text-muted-foreground">{analysis.date}</span>
                </div>
              </div>

              {/* Status */}
              <Badge
                variant="outline"
                className={`text-[10px] shrink-0 ${
                  analysis.status === "above"
                    ? "border-emerald-400/30 text-emerald-400"
                    : "border-destructive/30 text-destructive"
                }`}
              >
                {analysis.status === "above" ? (
                  <TrendingUp className="w-3 h-3 mr-1" />
                ) : (
                  <TrendingDown className="w-3 h-3 mr-1" />
                )}
                {analysis.status === "above" ? "Above" : "Below"} Baseline
              </Badge>
            </Link>
          ))}
        </div>
      </CollapsibleCard>

      {/* Recent edits — quick affordance back to the Studio for in-progress
          drafts. Hides itself when the user has no sessions yet so the
          dashboard stays uncluttered for new users. */}
      {recentEdits && recentEdits.length > 0 && (
        <CollapsibleCard
          title="Recent edits"
          icon={<Clapperboard className="w-4 h-4 text-violet-400" />}
          badge={
            <Link href="/dashboard/drafts" onClick={(e) => e.stopPropagation()}>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-muted-foreground hover:text-foreground h-6 px-2"
              >
                View all <ArrowRight className="w-3 h-3 ml-1" />
              </Button>
            </Link>
          }
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {recentEdits.map((edit) => {
              const posterUrl = edit.last_render_url || edit.source_video_url;
              const playbackUrl = proxyVideoUrl(posterUrl);
              return (
                <Link
                  key={edit.clip_key}
                  href={`/dashboard/studio/${edit.clip_key}`}
                  className="group rounded-lg overflow-hidden border border-border/50 bg-secondary/30 hover:border-violet-500/40 transition-colors"
                >
                  <div className="aspect-video bg-black/60 relative overflow-hidden">
                    {playbackUrl ? (
                      <video
                        src={playbackUrl}
                        preload="metadata"
                        muted
                        playsInline
                        className="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Clapperboard className="w-8 h-8 opacity-40" />
                      </div>
                    )}
                    <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
                      <div className="flex items-center gap-1 text-[11px] text-white">
                        <Pencil className="w-3 h-3" />
                        Continue editing
                      </div>
                    </div>
                  </div>
                  <div className="p-2.5">
                    <div
                      className="text-sm font-medium truncate"
                      title={edit.title || "Untitled draft"}
                    >
                      {edit.title || "Untitled draft"}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {recentEditTimeAgo(edit.updated_at)}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </CollapsibleCard>
      )}
    </div>
  );
}

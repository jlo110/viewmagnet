/*
 * Trend Timing: Google Trends integration for optimal upload timing
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  TrendingDown,
  Clock,
  Search,
  Flame,
  ArrowUpRight,
  Calendar,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { analyzeTrends } from "@/lib/api";
import { TopicMomentumPanel } from "@/components/dashboard/TopicMomentumPanel";
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";

interface TrendDataPoint {
  week: string;
  interest: number;
}

interface UploadTime {
  day: string;
  time: string;
  score: number;
  reason: string;
}

interface RisingTopic {
  topic: string;
  change: string;
  status: "breakout" | "rising" | "steady" | "declining";
  category: string;
}

// Generate trend data based on topic
function generateTrendData(topic: string): TrendDataPoint[] {
  // Create a "seed" from the topic to make results consistent for the same topic
  const seed = topic.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const baseInterest = 30 + (seed % 40);
  const isTrending = seed % 3 !== 0;
  
  return Array.from({ length: 12 }, (_, i) => {
    const weekNum = i + 1;
    let interest: number;
    
    if (isTrending) {
      // Upward trend with some variation
      interest = Math.min(100, baseInterest + (i * 5) + Math.sin(i) * 10);
    } else {
      // Stable with seasonal variation
      interest = baseInterest + Math.sin(i * 0.8) * 15;
    }
    
    return {
      week: `W${weekNum}`,
      interest: Math.round(Math.max(10, Math.min(100, interest))),
    };
  });
}

// Generate upload times based on topic
function generateUploadTimes(topic: string): UploadTime[] {
  const words = topic.toLowerCase();
  const isTech = words.includes("code") || words.includes("programming") || words.includes("dev") || words.includes("ai");
  const isGaming = words.includes("game") || words.includes("gaming") || words.includes("stream");
  const isLifestyle = words.includes("vlog") || words.includes("life") || words.includes("travel");
  
  if (isTech) {
    return [
      { day: "Tuesday", time: "10:00 AM", score: 94, reason: `Peak search volume for ${topic}` },
      { day: "Wednesday", time: "2:00 PM", score: 89, reason: "High engagement window for tech content" },
  { day: "Thursday", time: "11:00 AM", score: 86, reason: "Pre-weekend browsing spike" },
  { day: "Monday", time: "9:00 AM", score: 78, reason: "Start-of-week discovery" },
];
  } else if (isGaming) {
    return [
      { day: "Friday", time: "4:00 PM", score: 96, reason: `Weekend gaming sessions starting` },
      { day: "Saturday", time: "2:00 PM", score: 92, reason: "Peak gaming audience online" },
      { day: "Sunday", time: "3:00 PM", score: 88, reason: "Relaxed viewing time" },
      { day: "Thursday", time: "6:00 PM", score: 82, reason: "Pre-weekend hype building" },
    ];
  } else if (isLifestyle) {
    return [
      { day: "Sunday", time: "11:00 AM", score: 93, reason: `Weekend leisure browsing peak` },
      { day: "Saturday", time: "10:00 AM", score: 90, reason: "Morning inspiration seekers" },
      { day: "Wednesday", time: "7:00 PM", score: 85, reason: "Mid-week escape viewing" },
      { day: "Friday", time: "5:00 PM", score: 80, reason: "Weekend planning time" },
];
  }
  
  // Default
  return [
    { day: "Tuesday", time: "11:00 AM", score: 91, reason: `Optimal time for "${topic}" content` },
    { day: "Wednesday", time: "3:00 PM", score: 87, reason: "High engagement window" },
    { day: "Thursday", time: "10:00 AM", score: 83, reason: "Pre-weekend discovery" },
    { day: "Monday", time: "12:00 PM", score: 76, reason: "New week fresh starts" },
  ];
}

// Generate related rising topics based on the search topic
function generateRisingTopics(topic: string): RisingTopic[] {
  // Capitalize first letter of each word
  const capitalize = (str: string) => 
    str.split(' ').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  
  const capitalizedTopic = capitalize(topic);
  
  // Generate topic-specific related searches
  const templates = [
    { template: `${capitalizedTopic} complete guide 2026`, category: "Guide" },
    { template: `${capitalizedTopic} for beginners`, category: "Tutorial" },
    { template: `Best ${capitalizedTopic} tools`, category: "Tools" },
    { template: `${capitalizedTopic} mistakes to avoid`, category: "Tips" },
    { template: `${capitalizedTopic} vs competitors`, category: "Comparison" },
    { template: `Advanced ${capitalizedTopic} techniques`, category: "Advanced" },
  ];
  
  return templates.map((t, i) => {
    const statuses: Array<"breakout" | "rising" | "steady"> = ["breakout", "rising", "steady"];
    const status = statuses[i % 3];
    const changeValue = status === "breakout" ? Math.floor(Math.random() * 200 + 200) :
                        status === "rising" ? Math.floor(Math.random() * 150 + 50) :
                        Math.floor(Math.random() * 40 + 10);
    
    return {
      topic: t.template,
      change: `+${changeValue}%`,
      status,
      category: t.category,
    };
  });
}

export default function TrendTiming() {
  const [topic, setTopic] = useState("");
  const [searchedTopic, setSearchedTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);
  const [uploadTimes, setUploadTimes] = useState<UploadTime[]>([]);
  const [risingTopics, setRisingTopics] = useState<RisingTopic[]>([]);
  const [trendDirection, setTrendDirection] = useState<"up" | "down" | "stable">("up");

  const handleCheckTrend = async () => {
    if (!topic.trim()) {
      toast.error("Please enter a topic to check");
      return;
    }
    setLoading(true);
    
    try {
      const result = await analyzeTrends(topic, "general");

      // Convert API related topics to rising-topic cards. We surface the
      // backend's data verbatim (no synthesised growth %).
      const apiRisingTopics: RisingTopic[] = (result.related_topics || []).map((t, i) => ({
        topic: t,
        change: "—",
        status: i < 2 ? "breakout" : i < 4 ? "rising" : "steady",
        category: "Related",
      }));

      const direction =
        result.trend_direction === "rising"
          ? "up"
          : result.trend_direction === "falling"
            ? "down"
            : "stable";

      // The backend doesn't yet return weekly interest series or
      // optimal-upload windows. In production we leave those sections
      // empty (the UI handles empty arrays). In dev builds we keep the
      // local generators so designers can still iterate on the layout.
      const isDev = import.meta.env.DEV;
      setTrendData(isDev ? generateTrendData(topic) : []);
      setUploadTimes(isDev ? generateUploadTimes(topic) : []);
      setRisingTopics(apiRisingTopics);
      setTrendDirection(direction);
      setSearchedTopic(topic);
      setSearched(true);
      toast.success(`Trend data loaded for "${topic}"`);
    } catch (error) {
      console.error("Trend analysis failed:", error);
      setSearched(false);
      toast.error("Couldn't load trend data right now. Please try again in a moment.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Trend Timing
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Find the perfect moment to publish using Google Trends data and your audience patterns.
        </p>
      </div>

      {/* Topic Momentum — real breakout density from our own feed */}
      <TopicMomentumPanel />

      {/* Search */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <label htmlFor="trend-topic-input" className="sr-only">Topic to analyze</label>
              <Input
                id="trend-topic-input"
                aria-label="Topic to analyze"
                placeholder="Search a topic... (e.g., AI coding tools, gaming setup, travel vlog)"
                className="pl-10 bg-secondary/50 border-border/50 h-11"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCheckTrend()}
              />
            </div>
            <Button 
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleCheckTrend}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
              <TrendingUp className="w-4 h-4 mr-2" />
              )}
              {loading ? "Checking..." : "Check Trend"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Empty State */}
      {!searched && !loading && (
        <Card className="bg-card border-border/50 border-dashed">
          <CardContent className="p-8 text-center">
            <TrendingUp className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">
              Enter a topic and click "Check Trend" to see search interest data and optimal upload times
            </p>
          </CardContent>
        </Card>
      )}

      {/* Trend Chart + Best Times */}
      {searched && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2 bg-card border-border/50">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold">
                "{searchedTopic}" — Search Interest (12 Weeks)
              </CardTitle>
              <Badge className={`text-[10px] ${
                trendDirection === "up" 
                  ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20"
                  : trendDirection === "down"
                  ? "bg-destructive/10 text-destructive border-destructive/20"
                  : "bg-amber-glow/10 text-amber-glow border-amber-glow/20"
              }`}>
                {trendDirection === "up" ? (
                  <><Flame className="w-3 h-3 mr-1" /> Trending Up</>
                ) : trendDirection === "down" ? (
                  <><TrendingDown className="w-3 h-3 mr-1" /> Declining</>
                ) : (
                  <><TrendingUp className="w-3 h-3 mr-1" /> Stable</>
                )}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData}>
                  <defs>
                    <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="oklch(0.82 0.15 200)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="oklch(0.82 0.15 200)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.25 0.01 260)" />
                  <XAxis
                    dataKey="week"
                    tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                    axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                    axisLine={{ stroke: "oklch(0.25 0.01 260)" }}
                    tickLine={false}
                    domain={[0, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.16 0.01 260)",
                      border: "1px solid oklch(0.25 0.01 260)",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="interest"
                    stroke="oklch(0.82 0.15 200)"
                    strokeWidth={2}
                    fill="url(#trendGradient)"
                    name="Search Interest"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Best Upload Times */}
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-glow" />
              Best Upload Times for "{searchedTopic}"
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {uploadTimes.map((slot, i) => (
              <div
                key={i}
                className={`p-3 rounded-lg border transition-colors ${
                  i === 0
                    ? "bg-cyan-glow/5 border-cyan-glow/20"
                    : "bg-secondary/30 border-border/30"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-sm font-medium text-foreground">
                      {slot.day} {slot.time}
                    </span>
                  </div>
                  <span
                    className={`text-xs font-bold font-[var(--font-mono)] ${
                      i === 0 ? "text-cyan-glow" : "text-muted-foreground"
                    }`}
                  >
                    {slot.score}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground">{slot.reason}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      )}

      {/* Rising Topics */}
      {searched && (
        <CollapsibleCard
          title="Related Rising Topics"
          icon={<Flame className="w-4 h-4 text-amber-glow" />}
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {risingTopics.map((rt, idx) => (
              <div
                key={`${rt.topic}-${idx}`}
                className="p-3 rounded-lg bg-secondary/30 border border-border/30 hover:border-cyan-glow/20 transition-colors"
              >
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-medium text-foreground">{rt.topic}</p>
                  <span
                    className={`text-xs font-bold font-[var(--font-mono)] flex items-center ${
                      rt.status === "breakout"
                        ? "text-amber-glow"
                        : rt.status === "rising"
                        ? "text-emerald-400"
                        : "text-muted-foreground"
                    }`}
                  >
                    <ArrowUpRight className="w-3 h-3 mr-0.5" />
                    {rt.change}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge
                    variant="outline"
                    className={`text-[9px] ${
                      rt.status === "breakout"
                        ? "border-amber-glow/30 text-amber-glow"
                        : rt.status === "rising"
                        ? "border-emerald-400/30 text-emerald-400"
                        : "border-border/50 text-muted-foreground"
                    }`}
                  >
                    {rt.status}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground">{rt.category}</span>
                </div>
              </div>
            ))}
          </div>
        </CollapsibleCard>
      )}
    </div>
  );
}

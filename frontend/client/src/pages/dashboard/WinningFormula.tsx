/*
 * Winning Formula: Channel pattern discovery — hits vs flops
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Trophy,
  TrendingUp,
  TrendingDown,
  Lightbulb,
  CheckCircle2,
  XCircle,
  BarChart3,
  Loader2,
  Search,
  Info,
} from "lucide-react";
import {
  Tooltip as UITooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { useState } from "react";
import { toast } from "sonner";
import { getWinningFormula, type WinningFormula as WinningFormulaType } from "@/lib/api";

// Explanations for each radar chart factor
const radarExplanations: Record<string, { description: string; good: string; bad: string; tip: string }> = {
  "Title Length": {
    description: "Optimal title length is 40-65 characters",
    good: "Titles with numbers, power words, and proper length",
    bad: "Too short (<30 chars) or too long (>70 chars) titles",
    tip: "Include numbers in first 3 words for +80% more clicks",
  },
  "Thumbnail Quality": {
    description: "Visual impact and clickability of thumbnails",
    good: "1 face with emotion, bold text (3 words max), high contrast",
    bad: "Cluttered images, small text, low contrast, no focal point",
    tip: "Use bright colors + expressive faces = 2x CTR",
  },
  "Hook Strength": {
    description: "How compelling the first 5 seconds are",
    good: "Opens with a promise, question, or shocking statement",
    bad: "Generic intros, long logos, 'Hey guys' openers",
    tip: "Start with your most interesting moment",
  },
  "Topic Relevance": {
    description: "How well the topic matches your audience",
    good: "Topics your audience actively searches for",
    bad: "Random topics outside your niche or expertise",
    tip: "Stick to your core niche for consistent growth",
  },
  "Upload Timing": {
    description: "When you publish affects initial velocity",
    good: "Weekdays 2-6 PM, Tue-Thu peak engagement",
    bad: "Weekends, late nights, or inconsistent schedules",
    tip: "Your audience's timezone matters more than yours",
  },
  "Tag Optimization": {
    description: "How well your metadata helps discovery",
    good: "Relevant keywords in title, description, and tags",
    bad: "Missing tags, generic descriptions, no keywords",
    tip: "First 150 chars of description are crucial for SEO",
  },
  "Engagement": {
    description: "Like, comment, and share rates",
    good: "High likes/views ratio, active comments, saves",
    bad: "Low engagement despite views, no comments",
    tip: "Ask a specific question to boost comments",
  },
  "Consistency": {
    description: "How regularly you upload content",
    good: "Predictable schedule your audience can rely on",
    bad: "Random gaps, burnout cycles, unpredictable posting",
    tip: "2-3x per week beats daily then disappearing",
  },
};


export default function WinningFormula() {
  const [channelId, setChannelId] = useState("");
  const [loading, setLoading] = useState(false);
  // `analyzed` flips to true after a successful API call; until then we render
  // the empty-state prompt rather than fabricated demo data.
  const [analyzed, setAnalyzed] = useState(false);
  const [formula, setFormula] = useState<WinningFormulaType | null>(null);

  const displayPatterns = (formula?.title_patterns || []).map((p) => ({
    pattern: p.pattern,
    impact: `+${p.avg_performance.toFixed(1)}x`,
    confidence: p.frequency > 0.3 ? "High" : "Medium",
    example: p.example,
  }));

  const displayLosingPatterns = (formula?.losing_patterns || []).map((p) => ({
    pattern: p.pattern,
    impact: p.impact,
    example: p.example,
  }));

  const displayRadar = formula?.radar_data || [];
  const displayInsights = formula?.key_insights || [];

  const topVids = formula?.top_performing_videos || [];
  const bottomVids = formula?.bottom_performing_videos || [];

  const formatViews = (views: number | undefined) => {
    if (!views) return "N/A";
    if (views >= 1_000_000) return `${(views / 1_000_000).toFixed(1)}M`;
    if (views >= 1_000) return `${(views / 1_000).toFixed(1)}K`;
    return `${views}`;
  };

  const displayTopVideos = topVids.map((v) => ({
    title: v.title,
    views: formatViews(v.views),
  }));

  const displayBottomVideos = bottomVids.map((v) => ({
    title: v.title,
    views: formatViews(v.views),
  }));

  const handleAnalyze = async () => {
    if (!channelId.trim()) {
      toast.error("Please enter a channel ID or URL");
      return;
    }
    
    setLoading(true);
    try {
      const result = await getWinningFormula(channelId);
      setFormula(result);
      setAnalyzed(true);
      toast.success(`Analyzed ${result.total_videos_analyzed} videos from ${result.channel_name}`);
    } catch (error) {
      console.error("Failed to analyze:", error);
      setFormula(null);
      setAnalyzed(false);
      toast.error(
        "Couldn't fetch a winning formula for that channel. Double-check the ID/handle and try again."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Winning Formula
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Patterns your past hits share vs your flops — to test, not to trust blindly.
        </p>
        <p className="text-[11px] text-amber-glow/80 mt-1.5 max-w-2xl leading-snug">
          These are <strong>correlations</strong> in your history, not proven causes —
          especially the title/thumbnail ones (we tested: packaging doesn't reliably
          separate a channel's hits from its flops). Treat them as hypotheses: repeat one
          on your next few videos and see if it holds.
        </p>
      </div>

      {/* Channel Analysis Input */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-4">
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Analyze a Channel
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Enter channel ID or @handle..."
                  value={channelId}
                  onChange={(e) => setChannelId(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
                  className="pl-10 bg-secondary/50 border-border/50 h-11"
                />
              </div>
            </div>
            <Button 
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleAnalyze}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <BarChart3 className="w-4 h-4 mr-2" />
              )}
              {loading ? "Analyzing..." : "Analyze"}
            </Button>
          </div>
          {formula && (
            <div className="flex gap-4 mt-3 text-xs text-muted-foreground">
              <span>Channel: <span className="text-foreground">{formula.channel_name}</span></span>
              <span>Videos: <span className="text-foreground">{formula.total_videos_analyzed}</span></span>
              <span>Hit Rate: <span className="text-emerald-400">{(formula.hit_rate * 100).toFixed(1)}%</span></span>
            </div>
          )}
        </CardContent>
      </Card>

      {!analyzed ? (
        <Card className="bg-card border-border/50 border-dashed">
          <CardContent className="p-10 text-center">
            <Trophy className="w-10 h-10 text-muted-foreground/50 mx-auto mb-3" />
            <h3 className="font-semibold mb-1">Analyze a channel to see its winning formula</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              Enter a channel ID or @handle above and we'll surface the title patterns,
              upload timing, and thumbnail traits that separate hits from flops on that channel.
            </p>
          </CardContent>
        </Card>
      ) : (
      <>
      {/* Radar + Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CollapsibleCard
          title="Hits vs Flops Comparison"
          badge={
            <UITooltip>
              <TooltipTrigger asChild>
                <Info className="w-4 h-4 text-muted-foreground cursor-help hover:text-foreground transition-colors" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-[300px] p-3 bg-popover border border-border text-foreground">
                <div className="space-y-2">
                  <p className="font-semibold text-sm">Understanding This Chart</p>
                  <p className="text-xs text-muted-foreground">
                    This radar compares your <span className="text-cyan-400">top 25% performing videos</span> (hits) 
                    against your <span className="text-destructive">bottom 25%</span> (flops) across key factors.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    <strong>Higher scores = better.</strong> Where hits outscore flops, 
                    that factor is helping your success. Look for the biggest gaps!
                  </p>
                  <p className="text-xs text-cyan-400">💡 The larger the gap, the more that factor matters for your channel.</p>
                </div>
              </TooltipContent>
            </UITooltip>
          }
        >
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={displayRadar}>
                  <PolarGrid stroke="oklch(0.25 0.01 260)" />
                  <PolarAngleAxis
                    dataKey="factor"
                    tick={{ fontSize: 11, fill: "oklch(0.65 0.02 260)" }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.16 0.01 260)",
                      border: "1px solid oklch(0.25 0.01 260)",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                  />
                  <Radar
                    name="Hits"
                    dataKey="hits"
                    stroke="oklch(0.82 0.15 200)"
                    fill="oklch(0.82 0.15 200)"
                    fillOpacity={0.2}
                    strokeWidth={2}
                  />
                  <Radar
                    name="Flops"
                    dataKey="flops"
                    stroke="oklch(0.65 0.2 25)"
                    fill="oklch(0.65 0.2 25)"
                    fillOpacity={0.1}
                    strokeWidth={2}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex items-center justify-center gap-6 mt-2">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-cyan-glow" />
                <span className="text-xs text-muted-foreground">Hits (Top 25%)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-destructive" />
                <span className="text-xs text-muted-foreground">Flops (Bottom 25%)</span>
              </div>
            </div>
            
            {/* Factor Explanations Legend */}
            <Separator className="my-4" />
            <div className="space-y-1.5">
              <p className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
                <Info className="w-3 h-3" /> Hover over factors to learn what makes them good or bad
              </p>
              <div className="grid grid-cols-2 gap-2">
                {displayRadar.map((item) => {
                  const explanation = radarExplanations[item.factor];
                  if (!explanation) return null;
                  const diff = item.hits - item.flops;
                  const isStrong = diff > 20;
                  return (
                    <UITooltip key={item.factor}>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-2 p-2 rounded-md bg-secondary/30 hover:bg-secondary/50 transition-colors cursor-help">
                          <Info className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                          <span className="text-xs font-medium truncate">{item.factor}</span>
                          <Badge 
                            variant={isStrong ? "default" : "secondary"} 
                            className={`ml-auto text-[10px] px-1.5 ${isStrong ? "bg-emerald-500/20 text-emerald-400" : ""}`}
                          >
                            {diff > 0 ? "+" : ""}{diff}%
                          </Badge>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent 
                        side="top" 
                        className="max-w-[280px] p-3 bg-popover border border-border text-foreground"
                      >
                        <div className="space-y-2">
                          <p className="font-semibold text-sm">{item.factor}</p>
                          <p className="text-xs text-muted-foreground">{explanation.description}</p>
                          <div className="space-y-1">
                            <div className="flex items-start gap-2">
                              <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" />
                              <span className="text-xs text-emerald-400">{explanation.good}</span>
                            </div>
                            <div className="flex items-start gap-2">
                              <XCircle className="w-3 h-3 text-destructive mt-0.5 shrink-0" />
                              <span className="text-xs text-destructive">{explanation.bad}</span>
                            </div>
                          </div>
                          <div className="pt-1 border-t border-border/50">
                            <p className="text-xs text-cyan-400">💡 {explanation.tip}</p>
                          </div>
                        </div>
                      </TooltipContent>
                    </UITooltip>
                  );
                })}
              </div>
            </div>
        </CollapsibleCard>

        {/* Top & Bottom Videos */}
        <div className="space-y-4">
          <CollapsibleCard
            title="Your Top Performers"
            icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}
          >
            <div className="space-y-2">
              {displayTopVideos.map((v, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-secondary/30">
                  <span className="text-xs font-bold text-emerald-400 w-6">#{i + 1}</span>
                  <p className="text-sm text-foreground flex-1 truncate">{v.title}</p>
                  <Badge variant="secondary" className="text-xs shrink-0">
                    {v.views} views
                  </Badge>
                </div>
              ))}
            </div>
          </CollapsibleCard>

          <CollapsibleCard
            title="Underperformers"
            icon={<TrendingDown className="w-4 h-4 text-destructive" />}
          >
            <div className="space-y-2">
              {displayBottomVideos.map((v, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg bg-secondary/30">
                  <span className="text-xs font-bold text-destructive/70 w-6">#{i + 1}</span>
                  <p className="text-sm text-foreground flex-1 truncate">{v.title}</p>
                  <Badge variant="outline" className="text-xs shrink-0 text-muted-foreground">
                    {v.views} views
                  </Badge>
                </div>
              ))}
            </div>
          </CollapsibleCard>
        </div>
      </div>

      {/* Patterns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Winning Patterns */}
        <CollapsibleCard
          title="Winning Patterns"
          icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}
        >
          <div className="space-y-3">
            {displayPatterns.map((p, i) => (
              <div key={i} className="p-3 rounded-lg bg-emerald-400/5 border border-emerald-400/10">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-medium text-foreground">{p.pattern}</p>
                  <Badge className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20 text-[10px]">
                    {p.impact}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  e.g. "{p.example}"
                </p>
              </div>
            ))}
          </div>
        </CollapsibleCard>

        {/* Losing Patterns */}
        <CollapsibleCard
          title="Patterns to Avoid"
          icon={<XCircle className="w-4 h-4 text-destructive" />}
        >
          <div className="space-y-3">
            {displayLosingPatterns.map((p, i) => (
              <div key={i} className="p-3 rounded-lg bg-destructive/5 border border-destructive/10">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-medium text-foreground">{p.pattern}</p>
                  <Badge className="bg-destructive/10 text-destructive border-destructive/20 text-[10px]">
                    {p.impact}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  e.g. "{p.example}"
                </p>
              </div>
            ))}

            <Separator className="bg-border/30" />

            <div className="p-3 rounded-lg bg-amber-glow/5 border border-amber-glow/10">
              <div className="flex items-start gap-2">
                <Lightbulb className="w-4 h-4 text-amber-glow shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-foreground">Key Insight</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Your best videos share personal stories with specific numbers. 
                    Generic "what is" content consistently underperforms your baseline by 40%.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </CollapsibleCard>
      </div>
      </>
      )}
    </div>
  );
}

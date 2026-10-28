/*
 * Competitor Analysis: Head-to-head channel comparison
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sword,
  Search,
  Plus,
  Loader2,
  Lightbulb,
  Target,
  Zap,
  User,
} from "lucide-react";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { analyzeCompetitor, getTrackedChannels } from "@/lib/api";

interface Competitor {
  name: string;
  channelId: string;
  subs: string;
  avgViews: string;
  strengths: string[];
  weaknesses: string[];
  yourAdvantages: string[];
  metrics: { metric: string; yours: string; competitor: string; winner?: string }[];
  opportunities: { opportunity: string; description: string; action_item?: string }[];
  strategyDiffs: { strategy: string; your_approach: string; their_approach: string; recommendation?: string }[];
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

interface YourChannel {
  channel_id: string;
  channel_name: string;
  subscriber_count?: number;
}

export default function CompetitorAnalysis() {
  const [channelUrl, setChannelUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [selectedCompetitor, setSelectedCompetitor] = useState<Competitor | null>(null);
  const [yourChannels, setYourChannels] = useState<YourChannel[]>([]);
  const [selectedYourChannel, setSelectedYourChannel] = useState<string>("");

  // Load available channels on mount
  useEffect(() => {
    const loadChannels = async () => {
      const channels: YourChannel[] = [];
      
      // Load from connected channel in localStorage
      const savedChannel = localStorage.getItem("connectedChannel");
      if (savedChannel) {
        try {
          const parsed = JSON.parse(savedChannel);
          if (parsed.channel_id && parsed.channel_name) {
            channels.push({
              channel_id: parsed.channel_id,
              channel_name: parsed.channel_name,
              subscriber_count: parsed.subscriber_count,
            });
          }
        } catch (e) {
          console.error("Failed to parse saved channel:", e);
        }
      }
      
      // Load tracked channels from velocity tracker
      try {
        const trackedRes = await getTrackedChannels();
        for (const ch of trackedRes.channels) {
          if (!channels.find(c => c.channel_id === ch.channel_id)) {
            channels.push({
              channel_id: ch.channel_id,
              channel_name: ch.channel_name,
              subscriber_count: ch.subscriber_count,
            });
          }
        }
      } catch (e) {
        console.error("Failed to load tracked channels:", e);
      }
      
      setYourChannels(channels);
      if (channels.length > 0 && !selectedYourChannel) {
        setSelectedYourChannel(channels[0].channel_id);
      }
    };
    
    loadChannels();
  }, []);

  const handleAddCompetitor = async () => {
    if (!channelUrl.trim()) {
      toast.error("Please enter a competitor channel URL or name");
      return;
    }
    setLoading(true);
    
    try {
      const report = await analyzeCompetitor(channelUrl, selectedYourChannel || undefined);
      
      const newCompetitor: Competitor = {
        name: report.competitor?.name || "Competitor",
        channelId: report.competitor?.channel_id || channelUrl,
        subs: report.competitor?.subscribers 
          ? formatNumber(report.competitor.subscribers)
          : "N/A",
        avgViews: report.competitor?.avg_views
          ? formatNumber(report.competitor.avg_views)
          : "N/A",
        strengths: report.competitor_strengths || [],
        weaknesses: report.opportunities?.map(o => o.opportunity || o.gap || "Unknown").slice(0, 3) || [],
        yourAdvantages: report.your_advantages || [],
        metrics: report.metrics?.map(m => ({
          metric: m.metric,
          yours: String(m.yours),
          competitor: String(m.competitor),
          winner: m.winner,
        })) || [],
        opportunities: report.opportunities?.map(o => ({
          opportunity: o.opportunity || o.gap || "Opportunity",
          description: o.description || o.potential || "",
          action_item: o.action_item,
        })) || [],
        strategyDiffs: report.strategy_differences?.map(s => ({
          strategy: s.strategy || s.area || "Strategy",
          your_approach: s.your_approach || "",
          their_approach: s.their_approach || "",
          recommendation: s.recommendation,
        })) || [],
      };
      
      setCompetitors(prev => [...prev, newCompetitor]);
      setSelectedCompetitor(newCompetitor);
      toast.success(`${newCompetitor.name} added! Analysis complete.`);
      setChannelUrl("");
    } catch (error) {
      console.error("Competitor analysis failed:", error);
      toast.error("Failed to analyze competitor. Please check the channel URL.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Competitor Analysis
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Compare your channel head-to-head with competitors to find gaps and opportunities.
        </p>
      </div>

      {/* Your Channel Selection */}
      {yourChannels.length > 0 && (
        <Card className="bg-card border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <User className="w-4 h-4 text-cyan-glow" />
                <span className="text-sm font-medium">Your Channel:</span>
              </div>
              <Select value={selectedYourChannel} onValueChange={setSelectedYourChannel}>
                <SelectTrigger className="w-[280px] bg-secondary/50 border-border/50">
                  <SelectValue placeholder="Select your channel" />
                </SelectTrigger>
                <SelectContent>
                  {yourChannels.map((ch) => (
                    <SelectItem key={ch.channel_id} value={ch.channel_id}>
                      {ch.channel_name}
                      {ch.subscriber_count && (
                        <span className="text-muted-foreground ml-2">
                          ({formatNumber(ch.subscriber_count)} subs)
                        </span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Metrics will compare against this channel
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Competitor */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Enter competitor channel URL or @handle..."
                value={channelUrl}
                onChange={(e) => setChannelUrl(e.target.value)}
                className="pl-10 bg-secondary/50 border-border/50 h-11"
              />
            </div>
            <Button 
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleAddCompetitor}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
              <Plus className="w-4 h-4 mr-2" />
              )}
              {loading ? "Analyzing..." : "Add Competitor"}
            </Button>
          </div>
          {!selectedYourChannel && yourChannels.length === 0 && (
            <p className="text-xs text-muted-foreground mt-3">
              <span className="text-amber-glow">Tip:</span> Connect your channel in the Overview tab to compare metrics head-to-head
            </p>
          )}
        </CardContent>
      </Card>

      {/* Empty State */}
      {competitors.length === 0 && !loading && (
        <Card className="bg-card border-border/50 border-dashed">
          <CardContent className="p-8 text-center">
            <Sword className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">
              Add your first competitor to start tracking and comparing channel performance
            </p>
          </CardContent>
        </Card>
      )}

      {/* Tracked Competitors */}
      {competitors.length > 0 && (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {competitors.map((comp) => (
          <Card 
            key={comp.channelId} 
            className={`bg-card border-border/50 cursor-pointer transition-all ${
              selectedCompetitor?.channelId === comp.channelId 
                ? "ring-1 ring-cyan-glow" 
                : "hover:bg-secondary/30"
            }`}
            onClick={() => setSelectedCompetitor(comp)}
          >
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-glow/20 to-amber-glow/20 flex items-center justify-center">
                    <span className="text-sm font-bold">{comp.name[0]}</span>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">{comp.name}</p>
                    <p className="text-xs text-muted-foreground">{comp.subs} subscribers</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="p-2.5 rounded-lg bg-secondary/30">
                  <p className="text-[10px] text-muted-foreground">Avg Views</p>
                  <p className="text-sm font-semibold">{comp.avgViews}</p>
                </div>
                <div className="p-2.5 rounded-lg bg-secondary/30">
                  <p className="text-[10px] text-muted-foreground">Metrics</p>
                  <p className="text-sm font-semibold">{comp.metrics.length} compared</p>
                </div>
              </div>

              {comp.strengths.length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] font-[var(--font-mono)] text-emerald-400 uppercase tracking-wider">
                    Their Strengths
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {comp.strengths.slice(0, 3).map((s, i) => (
                      <Badge key={i} variant="outline" className="text-[10px] border-emerald-400/20 text-emerald-400">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      )}

      {/* Selected Competitor Detail */}
      {selectedCompetitor && (
        <>
          {/* Metrics Comparison */}
          {selectedCompetitor.metrics.length > 0 && (
            <CollapsibleCard
              title={`You vs ${selectedCompetitor.name} — Key Metrics`}
              icon={<Target className="w-4 h-4 text-cyan-glow" />}
            >
              <div className="space-y-3">
                {selectedCompetitor.metrics.map((m, i) => (
                  <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-secondary/30">
                    <span className="text-sm font-medium">{m.metric}</span>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">You</p>
                        <p className={`text-sm font-semibold ${m.winner === "you" ? "text-emerald-400" : ""}`}>
                          {m.yours}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">Them</p>
                        <p className={`text-sm font-semibold ${m.winner === "competitor" ? "text-amber-glow" : ""}`}>
                          {m.competitor}
                        </p>
                      </div>
                      {m.winner && (
                        <Badge className={`text-[10px] ${
                          m.winner === "you" 
                            ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20" 
                            : "bg-amber-glow/10 text-amber-glow border-amber-glow/20"
                        }`}>
                          {m.winner === "you" ? "You win" : "They win"}
                        </Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CollapsibleCard>
          )}

          {/* Your Advantages */}
          {selectedCompetitor.yourAdvantages.length > 0 && (
            <CollapsibleCard
              title="Your Advantages"
              icon={<Target className="w-4 h-4 text-emerald-400" />}
            >
              <div className="flex flex-wrap gap-2">
                {selectedCompetitor.yourAdvantages.map((adv, i) => (
                  <Badge key={i} className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20 text-xs py-1.5 px-3">
                    {adv}
                  </Badge>
                ))}
              </div>
            </CollapsibleCard>
          )}

          {/* Opportunities */}
          {selectedCompetitor.opportunities.length > 0 && (
            <CollapsibleCard
              title="Opportunities to Exploit"
              icon={<Lightbulb className="w-4 h-4 text-amber-glow" />}
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {selectedCompetitor.opportunities.map((o, i) => (
                  <div key={i} className="p-4 rounded-lg bg-amber-glow/5 border border-amber-glow/20">
                    <p className="text-sm font-semibold text-amber-glow mb-1">{o.opportunity}</p>
                    <p className="text-xs text-muted-foreground mb-2">{o.description}</p>
                    {o.action_item && (
                      <p className="text-xs text-foreground">
                        <span className="text-cyan-glow font-medium">Action:</span> {o.action_item}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </CollapsibleCard>
          )}

          {/* Strategy Differences */}
          {selectedCompetitor.strategyDiffs.length > 0 && (
            <CollapsibleCard
              title="Strategy Differences"
              icon={<Zap className="w-4 h-4 text-purple-400" />}
            >
              <div className="space-y-3">
                {selectedCompetitor.strategyDiffs.map((s, i) => (
                  <div key={i} className="p-4 rounded-lg bg-secondary/30">
                    <p className="text-sm font-semibold mb-2">{s.strategy}</p>
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div>
                        <p className="text-cyan-glow font-medium mb-1">Your Approach</p>
                        <p className="text-muted-foreground">{s.your_approach || "Not detected"}</p>
                      </div>
                      <div>
                        <p className="text-amber-glow font-medium mb-1">Their Approach</p>
                        <p className="text-muted-foreground">{s.their_approach || "Not detected"}</p>
                      </div>
                    </div>
                    {s.recommendation && (
                      <p className="text-xs mt-2 pt-2 border-t border-border/50">
                        <span className="text-emerald-400 font-medium">Recommendation:</span> {s.recommendation}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </CollapsibleCard>
          )}
        </>
      )}
    </div>
  );
}

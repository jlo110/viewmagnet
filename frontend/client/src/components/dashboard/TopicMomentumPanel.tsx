import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Flame, TrendingUp, TrendingDown, Minus, Sparkles, Loader2 } from "lucide-react";
import { getTopicMomentum, type TopicMomentumItem } from "@/lib/api";

const TREND: Record<string, { label: string; cls: string; Icon: typeof Flame }> = {
  rising: { label: "Rising", cls: "bg-emerald-400/15 text-emerald-400", Icon: TrendingUp },
  peaking: { label: "Peaking", cls: "bg-orange-500/15 text-orange-400", Icon: Flame },
  fading: { label: "Fading", cls: "bg-muted/40 text-muted-foreground", Icon: TrendingDown },
  new: { label: "New", cls: "bg-cyan-glow/15 text-cyan-glow", Icon: Sparkles },
  steady: { label: "Steady", cls: "bg-muted/30 text-muted-foreground/80", Icon: Minus },
};

/** Topic Momentum (2.1): which topics are heating up RIGHT NOW from our own
 *  breakout feed — breakout density per topic + its trend. Market timing, not a
 *  packaging predictor. Self-loading; hides itself until a snapshot exists. */
export function TopicMomentumPanel() {
  const [topics, setTopics] = useState<TopicMomentumItem[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTopicMomentum(12)
      .then((r) => setTopics(r.topics))
      .catch(() => setTopics([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Card className="bg-card border-border/50">
        <CardContent className="p-5 flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Reading what's heating up…
        </CardContent>
      </Card>
    );
  }
  if (!topics || topics.length === 0) return null; // nothing computed yet — stay quiet

  return (
    <Card className="bg-card border-border/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Flame className="w-4 h-4 text-orange-400" /> Topics heating up right now
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          From our live breakout feed — the share of each topic's videos that are breaking out,
          and whether that's rising or fading. Where audiences are rewarding content right now
          (market timing — we measure it, we don't predict your packaging).
        </p>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {topics.map((t, i) => {
            const tr = TREND[t.trend] || TREND.steady;
            return (
              <div key={i} className="flex items-start justify-between gap-2 rounded-lg border border-border/40 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{t.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {Math.round(t.breakout_rate * 100)}% breaking out
                    <span className="text-muted-foreground/60"> · {t.breakout_count}/{t.topic_size} videos · {t.channel_count} channels</span>
                  </p>
                </div>
                <Badge className={`${tr.cls} gap-1 shrink-0`}>
                  <tr.Icon className="w-3 h-3" /> {tr.label}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

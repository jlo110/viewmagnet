/*
 * Connect Your Own Channel (3.1) — the validated breakout detector + durability
 * grader pointed at YOUR uploads, with a durability-driven "make a sequel /
 * capture the spike" recommendation. Studio shows your numbers; this tells you
 * what to DO when one of your videos takes off. Design: Signal Flow dark theme.
 */
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Youtube, TrendingUp, ExternalLink, Loader2, Rocket, Zap, Clock, RefreshCw } from "lucide-react";
import {
  getMyChannelBreakouts,
  startYouTubeAuth,
  type MyChannelBreakout,
} from "@/lib/api";
import { BreakoutTeardown } from "@/components/dashboard/BreakoutTeardown";
import { OwnerAnalytics } from "@/components/dashboard/OwnerAnalytics";

const DURABILITY: Record<string, { label: string; cls: string }> = {
  likely_to_sustain: { label: "Likely to sustain", cls: "bg-emerald-400/15 text-emerald-400" },
  could_flash: { label: "Could flash", cls: "bg-amber-glow/15 text-amber-glow" },
  uncertain: { label: "Uncertain", cls: "bg-muted/40 text-muted-foreground" },
  too_early: { label: "Too early to grade", cls: "bg-muted/30 text-muted-foreground/70" },
};

const URGENCY_ICON = { high: Rocket, medium: Zap, low: Clock } as const;

export default function MyChannel() {
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [breakouts, setBreakouts] = useState<MyChannelBreakout[]>([]);
  const [connecting, setConnecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getMyChannelBreakouts({ checkpoint: "6h" });
      setConnected(res.connected);
      setBreakouts(res.breakouts);
    } catch {
      toast.error("Couldn't load your channel right now.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const connect = async () => {
    setConnecting(true);
    try {
      const { auth_url } = await startYouTubeAuth();
      window.location.href = auth_url;
    } catch {
      toast.error("Couldn't start the YouTube connection.");
      setConnecting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
            <Youtube className="w-6 h-6 text-red-500" /> Your Channel
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            We run the same breakout detector and durability grader on your own uploads — and when
            one takes off, we tell you what to do about it: ship a sequel while it's hot, or capture
            the spike before it cools. We detect and coach; we don't predict that a sequel will also
            break out.
          </p>
        </div>
        {connected && (
          <Button variant="outline" size="sm" onClick={load} disabled={loading} className="gap-2">
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : !connected ? (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center space-y-4">
            <Youtube className="w-10 h-10 mx-auto text-red-500/80" />
            <div>
              <p className="font-medium">Connect your YouTube channel</p>
              <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
                We'll enroll it into our live collection and start watching your uploads for
                breakouts. New detections appear here within hours of one taking off.
              </p>
            </div>
            <Button onClick={connect} disabled={connecting} className="gap-2">
              {connecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Youtube className="w-4 h-4" />}
              Connect YouTube
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-8">
          {breakouts.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="py-12 text-center text-muted-foreground">
                <TrendingUp className="w-8 h-8 mx-auto mb-3 opacity-40" />
                Nothing of yours is breaking out right now. We're watching your uploads — a detection
                shows up here within hours of one taking off.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {breakouts.map((b) => {
            const d = DURABILITY[b.durability?.label || "too_early"] || DURABILITY.too_early;
            const rec = b.recommendation;
            const UIcon = rec ? URGENCY_ICON[rec.urgency] : Rocket;
            return (
              <Card key={b.video_id}>
                <CardContent className="p-4">
                  <div className="flex gap-4 items-start">
                    {b.thumbnail_url && (
                      <img src={b.thumbnail_url} alt="" className="w-28 h-16 object-cover rounded shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge className="bg-cyan-glow/15 text-cyan-glow gap-1"
                          title={`P(breakout) ${Math.round((b.probability || 0) * 100)}%`}>
                          <TrendingUp className="w-3 h-3" /> {b.level === "heating_up" ? "Heating up" : "Breaking out"}
                        </Badge>
                        <Badge className={d.cls}>{d.label}</Badge>
                      </div>
                      <a href={b.watch_url} target="_blank" rel="noreferrer"
                        className="block mt-1.5 font-medium hover:text-cyan-glow truncate">
                        {b.title} <ExternalLink className="inline w-3 h-3" />
                      </a>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {b.views.toLocaleString()} views
                        {b.age_hours != null && ` · ${Math.round(b.age_hours)}h old`}
                      </p>
                    </div>
                  </div>

                  {rec && (
                    <div className="mt-3 rounded-lg border border-cyan-glow/20 bg-cyan-glow/[0.04] p-3">
                      <p className="text-sm font-medium text-cyan-glow flex items-center gap-1.5">
                        <UIcon className="w-4 h-4" /> {rec.action}
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">{rec.why}</p>
                    </div>
                  )}

                  <div className="mt-2">
                    <BreakoutTeardown videoId={b.video_id} />
                  </div>
                </CardContent>
              </Card>
            );
              })}
            </div>
          )}

          <OwnerAnalytics />
        </div>
      )}
    </div>
  );
}

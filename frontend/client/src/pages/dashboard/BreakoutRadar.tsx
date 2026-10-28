/*
 * Breakout Radar — the live, cross-channel breakout feed (plan 9.1 flagship).
 *
 * The wedge a static-index competitor can't match: what's taking off across
 * the YouTube ecosystem RIGHT NOW, from our live velocity collection — with
 * calibrated P(breakout), the topic each one is riding (and how crowded it is),
 * and niche-conditioned detection confidence. Real-time sensing, not a static
 * report.
 *
 * Design: Signal Flow dark theme.
 */
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Radar,
  Flame,
  TrendingUp,
  Loader2,
  RefreshCw,
  ExternalLink,
  Users,
  Clock,
  ShieldCheck,
  Microscope,
  ChevronDown,
} from "lucide-react";
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  getBreakoutRadar,
  type BreakoutItem,
  type BreakoutRadarResponse,
} from "@/lib/api";
import { BreakoutTeardown } from "@/components/dashboard/BreakoutTeardown";

const CHECKPOINTS: { value: "1h" | "6h" | "24h"; label: string }[] = [
  { value: "1h", label: "1h — earliest" },
  { value: "6h", label: "6h — most accurate" },
  { value: "24h", label: "24h" },
];

export default function BreakoutRadar() {
  const [checkpoint, setCheckpoint] = useState<"1h" | "6h" | "24h">("6h");
  const [englishOnly, setEnglishOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<BreakoutRadarResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getBreakoutRadar({ checkpoint, min_probability: 0.7, english_only: englishOnly, limit: 40 });
      setData(res);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Couldn't load the radar.");
    } finally {
      setLoading(false);
    }
  }, [checkpoint, englishOnly]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
            <Radar className="w-6 h-6 text-cyan-glow" />
            Breakout Radar
          </h1>
          <p className="text-muted-foreground mt-1 max-w-2xl">
            What's breaking out across YouTube right now — detected live from our velocity
            collection the moment a video outpaces its channel, while it's still early enough
            to act on. Not a report on what already happened.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} className="gap-2">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-muted-foreground">Detection window:</span>
        {CHECKPOINTS.map((cp) => (
          <button
            key={cp.value}
            onClick={() => setCheckpoint(cp.value)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              checkpoint === cp.value
                ? "border-cyan-glow/60 bg-cyan-glow/10 text-cyan-glow"
                : "border-border/60 text-muted-foreground hover:border-border"
            }`}
          >
            {cp.label}
          </button>
        ))}
        <button
          onClick={() => setEnglishOnly((v) => !v)}
          className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
            englishOnly
              ? "border-cyan-glow/40 bg-cyan-glow/5 text-cyan-glow"
              : "border-border/60 text-muted-foreground hover:border-border"
          }`}
          title="The product is English-first; toggle to see the global feed"
        >
          {englishOnly ? "English only" : "All languages"}
        </button>
        {data && (
          <span className="text-xs text-muted-foreground ml-auto">
            {data.count} breaking out · updated {timeAgo(data.updated_at)}
          </span>
        )}
      </div>

      {/* Feed */}
      {loading && !data ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : data && data.breakouts.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {data.breakouts.map((b) => (
            <RadarCard key={b.video_id} b={b} />
          ))}
        </div>
      ) : (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center text-muted-foreground">
            <Radar className="w-8 h-8 mx-auto mb-3 opacity-40" />
            Nothing clearing the breakout threshold in this window right now. Try the 6h window,
            or check back — the radar updates as the collection samples new uploads.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function RadarCard({ b }: { b: BreakoutItem }) {
  const pct = Math.round(b.probability * 100);
  const [open, setOpen] = useState(false);

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        <div className="flex">
          {/* Thumbnail */}
          <a
            href={b.watch_url}
            target="_blank"
            rel="noreferrer"
            className="relative w-40 shrink-0 aspect-video bg-secondary/30 group"
          >
            <img
              src={b.thumbnail_url}
              alt=""
              className="w-full h-full object-cover"
              onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0")}
            />
            <span className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
              <ExternalLink className="w-5 h-5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
            </span>
          </a>

          {/* Body */}
          <div className="flex-1 min-w-0 p-3 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium leading-snug line-clamp-2">{b.title || "(untitled)"}</p>
              <Badge
                title={`P(breakout) ${pct}% — a yes/no confidence, not a ranking`}
                className={
                  b.level === "breakout"
                    ? "bg-orange-500/90 hover:bg-orange-500 shrink-0"
                    : "bg-amber-500/80 hover:bg-amber-500 shrink-0"
                }
              >
                {b.level === "breakout" ? (
                  <Flame className="w-3 h-3 mr-1" />
                ) : (
                  <TrendingUp className="w-3 h-3 mr-1" />
                )}
                {b.level === "breakout" ? "Breaking out" : "Heating up"}
              </Badge>
            </div>

            <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
              <span>{compact(b.views)} views</span>
              {b.age_hours != null && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {Math.round(b.age_hours)}h old
                </span>
              )}
              <span className="px-1.5 py-0.5 rounded bg-secondary/40">{b.niche}</span>
              <span
                className={`flex items-center gap-1 ${
                  b.confidence === "high"
                    ? "text-emerald-400"
                    : b.confidence === "moderate"
                      ? "text-amber-400"
                      : "text-muted-foreground"
                }`}
                title="How reliable early breakout calls are for this niche (measured AUC)"
              >
                <ShieldCheck className="w-3 h-3" /> {b.confidence} confidence
              </span>
            </div>

            {b.topic && (
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Users className="w-3 h-3 shrink-0" />
                <span className="truncate">
                  Riding <span className="text-foreground/80">{b.topic.label}</span> —{" "}
                  {b.topic.size} uploads / {b.topic.channel_count} channels
                  {b.topic.channel_count >= 10 ? " (crowded — differentiate)" : " (open ground)"}
                </span>
              </p>
            )}

            <button
              onClick={() => setOpen((o) => !o)}
              className="text-xs text-cyan-glow hover:underline flex items-center gap-1 pt-0.5"
            >
              <Microscope className="w-3 h-3" />
              Reverse-engineer this breakout
              <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} />
            </button>
          </div>
        </div>

        {open && (
          <div className="border-t border-border/50 p-3 bg-background/40 text-sm">
            <BreakoutTeardown videoId={b.video_id} autoLoad />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function compact(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(Math.round(n));
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

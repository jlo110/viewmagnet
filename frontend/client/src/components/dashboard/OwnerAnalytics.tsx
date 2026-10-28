import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BarChart3, MousePointerClick, RefreshCw, Loader2, Activity } from "lucide-react";
import {
  getMyChannelAnalytics,
  refreshMyChannelAnalytics,
  type OwnerVideoAnalytics,
} from "@/lib/api";

/** Owner analytics (3.2 display half): the user's REAL CTR + retention from
 *  their OAuth — not the dead packaging proxy. Pure display; no prediction. */
export function OwnerAnalytics() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [videos, setVideos] = useState<OwnerVideoAnalytics[]>([]);
  const [avgCtr, setAvgCtr] = useState<number | null>(null);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await getMyChannelAnalytics();
      setVideos(r.videos);
      setAvgCtr(r.channel_avg_ctr);
      setFetchedAt(r.fetched_at);
    } catch {
      /* silent — section just stays empty */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await refreshMyChannelAnalytics();
      toast.success(`Pulled analytics for ${r.videos} video${r.videos === 1 ? "" : "s"}`);
      await load();
    } catch {
      toast.error("Couldn't pull analytics right now.");
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground flex items-center gap-1.5">
          <BarChart3 className="w-4 h-4" /> Your real analytics
          <span className="font-normal text-muted-foreground/60">
            · actual CTR &amp; retention from YouTube{fetchedAt ? ` · updated ${timeAgo(fetchedAt)}` : ""}
          </span>
        </h2>
        <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing} className="gap-2">
          {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          {videos.length ? "Refresh" : "Pull analytics"}
        </Button>
      </div>

      {videos.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            <MousePointerClick className="w-7 h-7 mx-auto mb-2 opacity-40" />
            No analytics pulled yet. Hit “Pull analytics” to fetch your real CTR and audience
            retention for recent uploads.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border/50">
                  <th className="text-left font-medium px-4 py-2">Video</th>
                  <th className="text-right font-medium px-4 py-2">CTR</th>
                  <th className="text-right font-medium px-4 py-2 hidden sm:table-cell">Impressions</th>
                  <th className="text-right font-medium px-4 py-2">Avg view</th>
                  <th className="text-left font-medium px-4 py-2 hidden md:table-cell">Retention</th>
                </tr>
              </thead>
              <tbody>
                {videos.map((v) => {
                  const above = avgCtr != null && v.impressions > 0 && v.ctr >= avgCtr;
                  return (
                    <tr key={v.video_id} className="border-b border-border/30 last:border-0">
                      <td className="px-4 py-2 max-w-[240px]">
                        <a href={v.watch_url} target="_blank" rel="noreferrer"
                           className="hover:text-cyan-glow truncate inline-block max-w-full align-middle">
                          {v.title || v.video_id}
                        </a>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {v.impressions > 0 ? (
                          <span className={above ? "text-emerald-400" : "text-amber-glow"}>
                            {(v.ctr * 100).toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-muted-foreground/50">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums hidden sm:table-cell text-muted-foreground">
                        {v.impressions ? v.impressions.toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {v.avg_view_percentage ? `${Math.round(v.avg_view_percentage)}%` : "—"}
                      </td>
                      <td className="px-4 py-2 hidden md:table-cell">
                        <RetentionSparkline curve={v.retention_curve} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
      {avgCtr != null && (
        <p className="text-[11px] text-muted-foreground/60 mt-1.5">
          CTR is green when at/above your channel average ({(avgCtr * 100).toFixed(1)}%). Real click data —
          we show it, we don't predict from it yet (that's gated on validation).
        </p>
      )}
    </div>
  );
}

function RetentionSparkline({ curve }: { curve: number[] | null }) {
  if (!curve || curve.length === 0) {
    return <span className="text-muted-foreground/40 text-xs inline-flex items-center gap-1"><Activity className="w-3 h-3" /> —</span>;
  }
  const max = Math.max(...curve, 0.0001);
  return (
    <div className="flex items-end gap-px h-6 w-32">
      {curve.map((p, i) => (
        <div key={i} className="flex-1 bg-cyan-glow/50 rounded-sm" style={{ height: `${(p / max) * 100}%` }} />
      ))}
    </div>
  );
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

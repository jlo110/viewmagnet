import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Activity,
  ArrowUpRight,
  Flame,
  Layers,
  Lock,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getFormatRadar,
  type EmergingFormat,
  type FormatRadarResponse,
} from "@/lib/api";

/* Format Radar — emerging title/packaging formats mined from live breakouts.
   The live answer to a static format archive: default sort = momentum, default
   filter = "open" so creators catch formats while they're still uncrowded. */

const CAT: Record<string, string> = {
  "1": "Film", "2": "Autos", "10": "Music", "15": "Pets", "17": "Sports",
  "19": "Travel", "20": "Gaming", "22": "People", "23": "Comedy",
  "24": "Entertainment", "25": "News", "26": "Howto", "27": "Education",
  "28": "Science & Tech", "29": "Nonprofit",
};

const SORTS = [
  { key: "momentum", label: "Rising", icon: TrendingUp },
  { key: "outlier", label: "Top outlier", icon: Flame },
  { key: "views", label: "Most views", icon: Activity },
  { key: "count", label: "Most used", icon: Layers },
] as const;

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return `${Math.round(n)}`;
}

function opennessStyle(o: EmergingFormat["openness"]) {
  if (o === "open") return { label: "Open ground", className: "text-primary border-primary/30 bg-primary/10" };
  if (o === "warming") return { label: "Warming up", className: "text-accent border-accent/30 bg-accent/10" };
  return { label: "Crowded", className: "text-muted-foreground border-border bg-secondary" };
}

function FormatCard({ f }: { f: EmergingFormat }) {
  const open = opennessStyle(f.openness);
  const rising = f.momentum >= 1.3;
  return (
    <div className="group relative overflow-hidden rounded-xl border border-border bg-card/60 p-5 transition-colors hover:border-primary/40">
      <div className="flex items-start justify-between gap-3">
        <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-wide">{f.psychology_type}</Badge>
        {rising && (
          <span className="inline-flex items-center gap-1 font-mono text-xs font-semibold text-primary">
            <TrendingUp className="h-3.5 w-3.5" /> {f.momentum.toFixed(1)}×
          </span>
        )}
      </div>

      <h3 className="font-display mt-3 text-lg font-bold leading-snug">{f.template}</h3>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
        <span><b className="text-accent">{f.avg_outlier.toFixed(1)}×</b> avg outlier</span>
        <span><b className="text-foreground">{fmt(f.avg_views)}</b> avg views</span>
        <span>{f.count} uses</span>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] ${open.className}`}>
          ● {open.label} ({f.unique_channels})
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">reliability: {f.reliability}</span>
      </div>

      {f.examples.length > 0 && (
        <div className="mt-4 space-y-1.5 border-t border-border/60 pt-3">
          {f.examples.slice(0, 3).map((ex) => (
            <div key={ex.video_id} className="flex items-center gap-2 text-xs">
              <span className="w-12 shrink-0 font-mono font-semibold text-accent">{ex.outlier.toFixed(1)}×</span>
              <a href={`https://www.youtube.com/watch?v=${ex.video_id}`} target="_blank" rel="noreferrer"
                className="min-w-0 flex-1 truncate text-muted-foreground transition-colors hover:text-foreground">
                {ex.title}
              </a>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">{fmt(ex.views)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FormatRadar() {
  const [data, setData] = useState<FormatRadarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<(typeof SORTS)[number]["key"]>("momentum");
  // Default OFF: filtering to "open" only hides the strongest (warming/crowded)
  // formats — most users want to see everything that's breaking out, then opt
  // into "open only" to find uncrowded patterns.
  const [openOnly, setOpenOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getFormatRadar({
        sort,
        openness: openOnly ? "open" : undefined,
        limit: 60,
      });
      setData(res);
    } catch {
      toast.error("Couldn't load the format radar.");
    } finally {
      setLoading(false);
    }
  }, [sort, openOnly]);

  useEffect(() => {
    load();
  }, [load]);

  const formats = data?.formats ?? [];

  return (
    <div className="mx-auto max-w-6xl p-6">
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-2xl font-bold">Format Radar</h1>
            <Badge className="bg-primary text-primary-foreground">LIVE</Badge>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Title formats breaking out across YouTube right now — ranked by momentum, so you catch a
            pattern while it's still rising and uncrowded. Mined from live breakouts, not a static archive.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </Button>
      </div>

      {/* controls */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {SORTS.map((s) => (
            <Button key={s.key} size="sm" variant={sort === s.key ? "default" : "outline"} onClick={() => setSort(s.key)}>
              <s.icon className="mr-1.5 h-3.5 w-3.5" /> {s.label}
            </Button>
          ))}
        </div>
        <div className="ml-auto">
          <Button size="sm" variant={openOnly ? "default" : "outline"} onClick={() => setOpenOnly((v) => !v)}>
            {openOnly ? "Open ground only" : "All formats"}
          </Button>
        </div>
      </div>

      {/* body */}
      {loading ? (
        <div className="mt-16 text-center text-sm text-muted-foreground">Scanning the radar…</div>
      ) : formats.length === 0 ? (
        <div className="mt-16 rounded-xl border border-dashed border-border p-10 text-center">
          <p className="text-sm text-muted-foreground">
            No formats yet — the radar recomputes daily from the breakout window. Check back soon.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {formats.map((f) => <FormatCard key={f.slug} f={f} />)}
          </div>

          {data?.plan_gated && (data.locked ?? 0) > 0 && (
            <div className="mt-6 flex flex-col items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 p-8 text-center">
              <Lock className="h-6 w-6 text-primary" />
              <p className="text-sm">
                <b>{data.locked} more formats</b> are updating live right now.
              </p>
              <Button onClick={() => (window.location.href = "/dashboard/settings")}>
                Unlock all formats <ArrowUpRight className="ml-1.5 h-4 w-4" />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

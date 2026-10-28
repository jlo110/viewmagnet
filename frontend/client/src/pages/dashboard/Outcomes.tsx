/**
 * Outcomes — Week 10 post-publish analytics loop.
 *
 * Surfaces the data the backend's ``/distribution/outcomes`` endpoint
 * returns: per-published-post snapshots (1h / 24h / 7d / 30d) plus a
 * "recommendation effectiveness" rollup that compares each tool
 * cohort against the no-recommendation baseline.
 *
 * Design choices worth knowing:
 *
 *  - **Empty state is honest.** Before the user publishes anything we
 *    don't show a sample chart with "your metrics will appear here"
 *    placeholder bars — that pattern is the chart equivalent of fake
 *    growth numbers. We point at Distribution Hub and explain when
 *    real data shows up (after the first publish + 1h sample window).
 *
 *  - **Null-respecting formatting.** A platform that doesn't expose
 *    retention should render `—`, not `0%`. The backend already
 *    threads `null` through every absent metric; the formatter
 *    bubbles that through to the cell.
 *
 *  - **Recommendation cohort comparison.** Each tool group is shown
 *    with its sample count + averages alongside a delta vs. the
 *    baseline group. The delta is omitted when either side has zero
 *    samples — better than showing "+∞%".
 */
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getDistributionOutcomes,
  type OutcomesResponse,
  type PublishedOutcome,
  type RecommendationEffectivenessGroup,
} from "@/lib/api";
import { Link } from "wouter";
import {
  Activity,
  BarChart3,
  Eye,
  ExternalLink,
  Heart,
  MessageCircle,
  Network,
  RefreshCw,
} from "lucide-react";

const WINDOW_LABELS: Record<string, string> = {
  "1h": "1h",
  "24h": "24h",
  "7d": "7d",
  "30d": "30d",
};

const WINDOW_ORDER = ["1h", "24h", "7d", "30d"] as const;

function formatNumber(value: number | null | undefined): string {
  // Null-respecting formatter: an absent metric renders as ``—`` so
  // the table doesn't lie about a "0 views" snapshot when the truth
  // is "platform didn't expose this metric yet".
  if (value === null || value === undefined) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(1);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}%`;
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function formatRelative(iso: string): string {
  // We compute relative time ourselves rather than pulling in a date
  // library — the rest of the codebase doesn't use one and adding
  // one for a single timestamp would bloat the bundle.
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  if (seconds < 30 * 86400)
    return `${Math.round(seconds / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

function platformBadge(platform: string) {
  const palette: Record<string, string> = {
    youtube: "bg-red-500/10 text-red-200 border-red-500/30",
    tiktok: "bg-pink-500/10 text-pink-200 border-pink-500/30",
    instagram: "bg-purple-500/10 text-purple-200 border-purple-500/30",
    twitter: "bg-sky-500/10 text-sky-200 border-sky-500/30",
  };
  const cls = palette[platform] ?? "bg-muted text-foreground";
  return (
    <Badge variant="outline" className={cls}>
      {platform}
    </Badge>
  );
}

function ctaChip(provenance: PublishedOutcome["cta_provenance"]) {
  if (!provenance?.tool) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        baseline
      </Badge>
    );
  }
  // Show the tool name + the originating dashboard so the user can
  // tell apart "edits from a Hook Lab recommendation" vs "edits
  // re-opened from the Analyzer history".
  const tag = provenance.from
    ? `${provenance.tool} · ${provenance.from}`
    : provenance.tool;
  return (
    <Badge
      variant="outline"
      className="bg-cyan-glow/10 text-cyan-glow border-cyan-glow/30"
    >
      {tag}
    </Badge>
  );
}

interface DeltaCell {
  display: string;
  positive: boolean | null;
}

function deltaVsBaseline(
  group: number | null,
  baseline: number | null,
): DeltaCell {
  // Both sides have to have a real number for a delta to mean
  // anything — otherwise we'd be showing "+∞%" for divide-by-zero or
  // a misleading "0" when one side is missing.
  if (
    group === null ||
    baseline === null ||
    group === undefined ||
    baseline === undefined ||
    baseline === 0
  ) {
    return { display: "—", positive: null };
  }
  const ratio = (group - baseline) / baseline;
  const pct = Math.round(ratio * 100);
  const sign = pct >= 0 ? "+" : "";
  return { display: `${sign}${pct}%`, positive: pct >= 0 };
}

function deltaClass(d: DeltaCell): string {
  if (d.positive === null) return "text-muted-foreground";
  return d.positive
    ? "text-emerald-300 font-semibold"
    : "text-rose-300 font-semibold";
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="py-12 text-center space-y-4">
        <BarChart3 className="w-10 h-10 mx-auto text-muted-foreground" />
        <div>
          <p className="text-base font-medium">No outcomes yet</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            Publish a render through the Distribution Hub. We'll
            start sampling its performance an hour later and you'll
            see your 1h / 24h / 7d / 30d numbers here, attributed
            back to the recommendation (if any) that drove the edit.
          </p>
        </div>
        <Link href="/dashboard/distribution">
          <Button className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90">
            <Network className="w-4 h-4 mr-2" />
            Go to Distribution Hub
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function EffectivenessCard({
  groups,
}: {
  groups: RecommendationEffectivenessGroup[];
}) {
  // The baseline group anchors every comparison. If we don't even
  // have a baseline yet (e.g. user has only ever published from
  // recommendation deep links), we render the rows without deltas
  // so the table still carries information.
  const baseline = groups.find((g) => g.tool === "baseline");

  if (groups.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-glow" />
          Recommendation effectiveness
        </CardTitle>
        <CardDescription>
          Average performance per originating tool, with the delta
          vs. your baseline (posts you started without a
          recommendation). A sample of fewer than 5 posts is shown
          but the delta should be read with a grain of salt.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead className="text-right">Posts</TableHead>
              <TableHead className="text-right">
                Avg views
              </TableHead>
              <TableHead className="text-right">
                vs. baseline
              </TableHead>
              <TableHead className="text-right">
                Avg engagement
              </TableHead>
              <TableHead className="text-right">
                Avg retention
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((g) => {
              const viewsDelta = baseline
                ? deltaVsBaseline(g.avg_views, baseline.avg_views)
                : { display: "—", positive: null };
              return (
                <TableRow key={g.tool}>
                  <TableCell className="font-medium">
                    {g.label}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {g.sample_count}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatNumber(g.avg_views)}
                  </TableCell>
                  <TableCell
                    className={`text-right tabular-nums ${deltaClass(viewsDelta)}`}
                  >
                    {g.tool === "baseline"
                      ? "—"
                      : viewsDelta.display}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatRate(g.avg_engagement_rate)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPercent(g.avg_retention)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function OutcomeRow({ outcome }: { outcome: PublishedOutcome }) {
  const snapshotByWindow = WINDOW_ORDER.map((key) => ({
    key,
    snap: outcome.snapshots[key] ?? null,
  }));
  return (
    <TableRow>
      <TableCell className="font-medium max-w-[280px]">
        <div className="flex items-center gap-2">
          <span className="truncate" title={outcome.title}>
            {outcome.title}
          </span>
          {outcome.posted_url ? (
            <a
              href={outcome.posted_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-cyan-glow hover:text-cyan-glow/80"
              aria-label="open on platform"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          {formatRelative(outcome.published_at)}
        </p>
      </TableCell>
      <TableCell>{platformBadge(outcome.platform)}</TableCell>
      <TableCell>{ctaChip(outcome.cta_provenance)}</TableCell>
      {snapshotByWindow.map(({ key, snap }) => (
        <TableCell key={key} className="text-right tabular-nums">
          {snap === null ? (
            <span className="text-muted-foreground">{WINDOW_LABELS[key]} pending</span>
          ) : (
            <div className="flex flex-col items-end leading-tight">
              <span className="flex items-center gap-1 text-foreground">
                <Eye className="w-3 h-3" />
                {formatNumber(snap.views)}
              </span>
              <span className="flex items-center gap-1 text-muted-foreground text-xs">
                <Heart className="w-3 h-3" />
                {formatNumber(snap.likes)}
                <MessageCircle className="w-3 h-3 ml-1" />
                {formatNumber(snap.comments)}
              </span>
            </div>
          )}
        </TableCell>
      ))}
    </TableRow>
  );
}

export default function OutcomesPage() {
  const [data, setData] = useState<OutcomesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOutcomes = useMemo(
    () => async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await getDistributionOutcomes(100);
        setData(response);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load outcomes",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void fetchOutcomes();
  }, [fetchOutcomes]);

  const outcomes = data?.outcomes ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
            <Activity className="w-6 h-6 text-cyan-glow" />
            Outcomes
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Did the edit actually move the needle? See your
            published posts at 1h / 24h / 7d / 30d, with
            performance attributed back to the recommendation (if
            any) that started the edit.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void fetchOutcomes()}
          disabled={loading}
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      {error ? (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-rose-300">{error}</p>
          </CardContent>
        </Card>
      ) : null}

      {!loading && outcomes.length === 0 && !error ? <EmptyState /> : null}

      {outcomes.length > 0 ? (
        <>
          <EffectivenessCard
            groups={data?.recommendation_effectiveness ?? []}
          />

          <Card>
            <CardHeader>
              <CardTitle>Recent posts</CardTitle>
              <CardDescription>
                One row per platform post — a publish to YouTube +
                TikTok appears as two rows so the per-platform
                breakdown stays honest.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead>Platform</TableHead>
                    <TableHead>Source</TableHead>
                    {WINDOW_ORDER.map((key) => (
                      <TableHead key={key} className="text-right">
                        {WINDOW_LABELS[key]}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {outcomes.map((o) => (
                    <OutcomeRow
                      key={`${o.distribution_result_id}-${o.platform}`}
                      outcome={o}
                    />
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

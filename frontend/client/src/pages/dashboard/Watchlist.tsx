import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Eye, Plus, X, TrendingUp, ExternalLink, Trophy, Webhook, LayoutGrid } from "lucide-react";
import {
  getWatchlist,
  addWatchlistChannel,
  removeWatchlistChannel,
  getWatchlistBreakouts,
  getWatchlistLeaderboard,
  getWatchlistSettings,
  updateWatchlistSettings,
  type WatchlistChannel,
  type WatchlistBreakout,
  type LeaderboardChannel,
} from "@/lib/api";
import { BreakoutTeardown } from "@/components/dashboard/BreakoutTeardown";

const DURABILITY: Record<string, { label: string; cls: string }> = {
  likely_to_sustain: { label: "Likely to sustain", cls: "bg-emerald-400/15 text-emerald-400" },
  could_flash: { label: "Could flash", cls: "bg-amber-glow/15 text-amber-glow" },
  uncertain: { label: "Uncertain", cls: "bg-muted/40 text-muted-foreground" },
  too_early: { label: "Too early to grade", cls: "bg-muted/30 text-muted-foreground/70" },
};

export default function Watchlist() {
  const [channels, setChannels] = useState<WatchlistChannel[]>([]);
  const [breakouts, setBreakouts] = useState<WatchlistBreakout[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardChannel[]>([]);
  const [url, setUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"precise" | "balanced" | "sensitive">("balanced");
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [weeklyDigest, setWeeklyDigest] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [savedWebhook, setSavedWebhook] = useState("");
  const [groupByChannel, setGroupByChannel] = useState(false);
  useEffect(() => {
    getWatchlistSettings()
      .then((s) => {
        setEmailAlerts(s.email_alerts);
        setWeeklyDigest(s.weekly_digest);
        setWebhookUrl(s.alert_webhook_url);
        setSavedWebhook(s.alert_webhook_url);
      })
      .catch(() => {});
  }, []);

  const saveWebhook = async () => {
    try {
      const s = await updateWatchlistSettings({ alert_webhook_url: webhookUrl.trim() });
      setSavedWebhook(s.alert_webhook_url);
      setWebhookUrl(s.alert_webhook_url);
      toast.success(s.alert_webhook_url ? "War-room webhook saved" : "Webhook cleared");
    } catch {
      toast.error("That doesn't look like a valid https:// Slack/Discord webhook.");
    }
  };

  const toggleEmail = async () => {
    const next = !emailAlerts;
    setEmailAlerts(next);
    try {
      await updateWatchlistSettings({ email_alerts: next });
      toast.success(next ? "Email alerts on" : "Email alerts off");
    } catch {
      setEmailAlerts(!next);
      toast.error("Couldn't update that.");
    }
  };

  const toggleDigest = async () => {
    const next = !weeklyDigest;
    setWeeklyDigest(next);
    try {
      await updateWatchlistSettings({ weekly_digest: next });
      toast.success(next ? "Weekly digest on" : "Weekly digest off");
    } catch {
      setWeeklyDigest(!next);
      toast.error("Couldn't update that.");
    }
  };

  const refresh = useCallback(async (m: "precise" | "balanced" | "sensitive") => {
    setLoading(true);
    try {
      const [w, b, lb] = await Promise.all([
        getWatchlist(),
        getWatchlistBreakouts({ mode: m, limit: 40 }),
        getWatchlistLeaderboard({ window_days: 30 }).catch(() => ({ channels: [] as LeaderboardChannel[] })),
      ]);
      setChannels(w.channels);
      setBreakouts(b.breakouts);
      setLeaderboard(lb.channels);
    } catch {
      toast.error("Couldn't load your watchlist right now.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(mode); }, [refresh, mode]);

  const add = async () => {
    if (!url.trim()) return;
    setAdding(true);
    try {
      const res = await addWatchlistChannel(url.trim());
      toast.success(res.added ? `Watching ${res.channel_title || res.channel_id}` : "Already on your watchlist");
      setUrl("");
      await refresh(mode);
    } catch {
      toast.error("Couldn't resolve that to a YouTube channel.");
    } finally {
      setAdding(false);
    }
  };

  const remove = async (channelId: string) => {
    await removeWatchlistChannel(channelId);
    await refresh(mode);
  };

  const channelName = (cid: string) => {
    const c = channels.find((x) => x.channel_id === cid);
    return c?.label || c?.channel_title || cid;
  };

  const renderCard = (b: WatchlistBreakout) => {
    const d = DURABILITY[b.durability?.label || "too_early"] || DURABILITY.too_early;
    return (
      <Card key={b.video_id}>
        <CardContent className="p-4 flex gap-4 items-start">
          {b.thumbnail_url && (
            <img src={b.thumbnail_url} alt="" className="w-28 h-16 object-cover rounded shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge
                className="bg-cyan-glow/15 text-cyan-glow gap-1"
                title={`P(breakout) ${Math.round((b.probability || 0) * 100)}% — a yes/no confidence, not a ranking`}
              >
                <TrendingUp className="w-3 h-3" /> {b.level === "heating_up" ? "Heating up" : "Breaking out"}
              </Badge>
              <Badge className={d.cls}>{d.label}</Badge>
              {b.topic && (
                <span className="text-xs text-muted-foreground">riding: {b.topic.label}</span>
              )}
            </div>
            <a
              href={b.watch_url}
              target="_blank"
              rel="noreferrer"
              className="block mt-1.5 font-medium hover:text-cyan-glow truncate"
            >
              {b.title} <ExternalLink className="inline w-3 h-3" />
            </a>
            <p className="text-xs text-muted-foreground mt-0.5">
              {b.views.toLocaleString()} views
              {b.age_hours != null && ` · ${Math.round(b.age_hours)}h old`}
              {b.confidence && ` · ${b.confidence} confidence`}
            </p>
            <div className="mt-1.5">
              <BreakoutTeardown videoId={b.video_id} />
            </div>
          </div>
        </CardContent>
      </Card>
    );
  };

  // Portfolio view: group the feed by channel (preserving the rank order in
  // which each channel first appears), so an agency sees breakouts per client.
  const groupedBreakouts = (): [string, WatchlistBreakout[]][] => {
    const order: string[] = [];
    const groups: Record<string, WatchlistBreakout[]> = {};
    for (const b of breakouts) {
      if (!groups[b.channel_id]) { groups[b.channel_id] = []; order.push(b.channel_id); }
      groups[b.channel_id].push(b);
    }
    return order.map((cid) => [cid, groups[cid]]);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Eye className="w-6 h-6 text-cyan-glow" /> Competitive Watchlist
        </h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
          Track any public channel — competitors, your niche — and we'll tell you within hours
          when one of their videos is breaking out, and whether it's likely to last. This works on
          channels YouTube Studio can't show you. New channels are picked up from their next upload.
        </p>
      </div>

      {/* Add channel */}
      <Card>
        <CardContent className="p-4 flex gap-2">
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="Paste a channel URL, @handle, or UC… id"
            className="flex-1"
          />
          <Button onClick={add} disabled={adding}>
            <Plus className="w-4 h-4 mr-1" /> {adding ? "Adding…" : "Watch"}
          </Button>
        </CardContent>
      </Card>

      {/* How it works + email opt-out */}
      <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-muted-foreground">
        <span>
          We start watching from a channel's next upload — breakouts appear here (and by email)
          within hours of one taking off.
        </span>
        <div className="flex items-center gap-4 shrink-0">
          <button onClick={toggleEmail} className="flex items-center gap-1.5 hover:text-foreground" title="Real-time email when a watched channel breaks out">
            <span className={`w-8 h-4 rounded-full transition-colors ${emailAlerts ? "bg-cyan-glow/60" : "bg-muted"} relative`}>
              <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${emailAlerts ? "left-4" : "left-0.5"}`} />
            </span>
            Real-time alerts {emailAlerts ? "on" : "off"}
          </button>
          <button onClick={toggleDigest} className="flex items-center gap-1.5 hover:text-foreground" title="A Monday roundup of the week's biggest breakouts on your watchlist">
            <span className={`w-8 h-4 rounded-full transition-colors ${weeklyDigest ? "bg-cyan-glow/60" : "bg-muted"} relative`}>
              <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${weeklyDigest ? "left-4" : "left-0.5"}`} />
            </span>
            Weekly digest {weeklyDigest ? "on" : "off"}
          </button>
        </div>
      </div>

      {/* War-room delivery (2.2): Slack/Discord webhook */}
      <Card>
        <CardContent className="p-4">
          <label className="text-xs font-medium text-muted-foreground flex items-center gap-1.5 mb-2">
            <Webhook className="w-3.5 h-3.5" /> War-room delivery (Slack / Discord)
          </label>
          <div className="flex gap-2">
            <Input
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://hooks.slack.com/… or https://discord.com/api/webhooks/…"
              className="flex-1 text-sm"
            />
            <Button variant="outline" onClick={saveWebhook} disabled={webhookUrl.trim() === savedWebhook}>
              Save
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground/70 mt-1.5">
            Pipe breakout alerts straight into a team channel — for agencies running a client war room.
            Paste an incoming-webhook URL; we'll post the same alert there as it fires.
          </p>
        </CardContent>
      </Card>

      {/* Watched channels */}
      {channels.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {channels.map((c) => (
            <Badge key={c.channel_id} variant="secondary" className="gap-1.5 py-1">
              {c.channel_title || c.channel_id}
              <button onClick={() => remove(c.channel_id)} className="hover:text-destructive">
                <X className="w-3 h-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Leaderboard — who breaks out most (last 30d) */}
      {leaderboard.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground mb-3 flex items-center gap-1.5">
            <Trophy className="w-4 h-4 text-amber-glow" /> Who breaks out most
            <span className="font-normal text-muted-foreground/70">· last 30 days · who's worth studying</span>
          </h2>
          <Card>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-border/50">
                    <th className="text-left font-medium px-4 py-2">Channel</th>
                    <th className="text-right font-medium px-4 py-2">Breakouts</th>
                    <th className="text-right font-medium px-4 py-2">Avg. durability</th>
                    <th className="text-left font-medium px-4 py-2 hidden sm:table-cell">Biggest hit</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((c, i) => (
                    <tr key={c.channel_id} className="border-b border-border/30 last:border-0">
                      <td className="px-4 py-2 font-medium truncate max-w-[180px]">
                        <span className="text-muted-foreground/60 mr-1.5">{i + 1}</span>
                        {c.channel_title}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{c.breakout_count}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {c.avg_durability != null ? (
                          <span className={c.avg_durability >= 0.6 ? "text-emerald-400" : c.avg_durability < 0.4 ? "text-amber-glow" : ""}>
                            {Math.round(c.avg_durability * 100)}%
                          </span>
                        ) : (
                          <span className="text-muted-foreground/50">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 hidden sm:table-cell">
                        {c.top_video ? (
                          <a href={c.top_video.watch_url} target="_blank" rel="noreferrer"
                             className="text-muted-foreground hover:text-cyan-glow truncate inline-block max-w-[260px] align-middle">
                            {c.top_video.title} <ExternalLink className="inline w-3 h-3" />
                          </a>
                        ) : (
                          <span className="text-muted-foreground/50">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Breakouts on watched channels */}
      <div>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            Breaking out on your watchlist
          </h2>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setGroupByChannel((v) => !v)}
              className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-md ${
                groupByChannel ? "bg-cyan-glow/20 text-cyan-glow" : "text-muted-foreground hover:bg-muted/40"
              }`}
              title="Group breakouts by channel — a portfolio view for agencies"
            >
              <LayoutGrid className="w-3 h-3" /> By channel
            </button>
            <div className="flex gap-1 text-xs">
              {(["precise", "balanced", "sensitive"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`px-2.5 py-1 rounded-md capitalize ${
                    mode === m ? "bg-cyan-glow/20 text-cyan-glow" : "text-muted-foreground hover:bg-muted/40"
                  }`}
                  title={m === "precise" ? "Only high-confidence calls" : m === "sensitive" ? "Catch more, lower precision" : "Default"}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : channels.length === 0 ? (
          <p className="text-sm text-muted-foreground">Add a channel above to start watching.</p>
        ) : breakouts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing breaking out right now. We're collecting their uploads — check back as new videos post.
          </p>
        ) : groupByChannel ? (
          <div className="space-y-5">
            {groupedBreakouts().map(([cid, items]) => (
              <div key={cid}>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground/80 mb-2 flex items-center gap-2">
                  {channelName(cid)}
                  <span className="font-normal normal-case text-muted-foreground/50">
                    {items.length} breaking out
                  </span>
                </h3>
                <div className="space-y-3">{items.map(renderCard)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">{breakouts.map(renderCard)}</div>
        )}
      </div>
    </div>
  );
}

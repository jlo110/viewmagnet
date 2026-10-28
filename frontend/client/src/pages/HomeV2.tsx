import { useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Check,
  Crosshair,
  Gauge,
  Radar,
  ShieldCheck,
  Signal,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import Footer from "@/components/sections/Footer";

/* ============================================================
   ViewMagnet — Homepage v2
   Concept: the site as a live signal-intelligence instrument.
   Lead with the wedge — the live, cross-channel Breakout Radar —
   not a generic "predict / create / publish" workflow pitch.
   ============================================================ */

const CYAN = "oklch(0.82 0.15 200)";
const AMBER = "oklch(0.82 0.15 80)";

type Blip = {
  channel: string;
  niche: string;
  title: string;
  mult: number; // x its own channel's norm
  prob: number; // calibrated P(breakout)
  ageMin: number; // minutes since first detected
  spark: number[];
};

const SEED: Blip[] = [
  { channel: "Nullbyte Labs", niche: "Tech", title: "I rebuilt my whole PC inside a fish tank", mult: 11.4, prob: 0.94, ageMin: 38, spark: [2, 3, 5, 6, 9, 14, 22] },
  { channel: "Midnight Tactics", niche: "Gaming", title: "The patch nobody noticed just broke the meta", mult: 7.8, prob: 0.91, ageMin: 52, spark: [3, 4, 4, 7, 9, 12, 18] },
  { channel: "Plainspoken", niche: "News", title: "What the earnings call actually admitted", mult: 6.1, prob: 0.88, ageMin: 26, spark: [1, 2, 4, 5, 6, 9, 13] },
  { channel: "Atlas & Co", niche: "Education", title: "Why this 1970s engine design is coming back", mult: 5.3, prob: 0.85, ageMin: 71, spark: [2, 3, 3, 5, 6, 7, 10] },
  { channel: "Saffron Kitchen", niche: "Food", title: "The 4-ingredient bread that broke my comments", mult: 4.7, prob: 0.83, ageMin: 19, spark: [1, 1, 3, 4, 5, 8, 11] },
  { channel: "Off-Grid Mara", niche: "Lifestyle", title: "30 days in a cabin I built for $900", mult: 4.2, prob: 0.81, ageMin: 64, spark: [2, 2, 3, 4, 5, 6, 8] },
  { channel: "Quant Daily", niche: "Finance", title: "The boring trade that beat every fund this month", mult: 3.9, prob: 0.79, ageMin: 33, spark: [1, 2, 2, 4, 5, 6, 8] },
];

const INCOMING: Blip[] = [
  { channel: "Deadzone FM", niche: "Comedy", title: "We let the intern script the whole episode", mult: 9.2, prob: 0.92, ageMin: 4, spark: [1, 3, 6, 9, 12, 16, 21] },
  { channel: "Verge of Space", niche: "Science", title: "This launch failure taught us more than success", mult: 6.6, prob: 0.87, ageMin: 7, spark: [2, 3, 5, 6, 8, 11, 15] },
  { channel: "Trailhead", niche: "Travel", title: "The border town that runs on one road", mult: 5.0, prob: 0.84, ageMin: 3, spark: [1, 2, 4, 5, 7, 9, 12] },
  { channel: "Bench & Bolt", niche: "DIY", title: "I fixed the 'unfixable' tool everyone throws out", mult: 4.4, prob: 0.82, ageMin: 6, spark: [1, 2, 3, 5, 6, 8, 10] },
];

const nicheHue: Record<string, string> = {
  Tech: CYAN, Gaming: AMBER, News: CYAN, Education: CYAN, Food: AMBER,
  Lifestyle: AMBER, Finance: CYAN, Comedy: AMBER, Science: CYAN, Travel: AMBER, DIY: AMBER,
};

function Sparkline({ points, color }: { points: number[]; color: string }) {
  const w = 56, h = 18;
  const max = Math.max(...points), min = Math.min(...points);
  const span = Math.max(1, max - min);
  const d = points
    .map((p, i) => `${(i / (points.length - 1)) * w},${h - ((p - min) / span) * h}`)
    .join(" ");
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline points={d} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={w} cy={h - ((points[points.length - 1] - min) / span) * h} r="2" fill={color} />
    </svg>
  );
}

/** The hero showpiece — a live, ticking breakout feed. */
function LiveRadar() {
  const [rows, setRows] = useState<Blip[]>(SEED);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1);
      setRows((prev) => {
        const next = prev.map((r) => ({
          ...r,
          ageMin: r.ageMin + 1,
          // tiny believable jitter on the live probability
          prob: Math.min(0.97, Math.max(0.74, r.prob + (Math.random() - 0.5) * 0.012)),
        }));
        // every few ticks, a fresh detection flashes in at the top
        if (Math.random() < 0.45) {
          const fresh = INCOMING[Math.floor(Math.random() * INCOMING.length)];
          return [{ ...fresh, ageMin: 1, prob: fresh.prob }, ...next].slice(0, 7);
        }
        return next;
      });
    }, 2200);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative v2-float">
      {/* glow base */}
      <div aria-hidden className="absolute -inset-6 rounded-[2rem] blur-2xl opacity-40"
        style={{ background: `radial-gradient(60% 60% at 70% 0%, ${CYAN}, transparent 70%)` }} />
      <div className="relative rounded-2xl border border-border/80 bg-[oklch(0.15_0.01_260_/_0.85)] backdrop-blur-xl shadow-2xl overflow-hidden">
        {/* scanline */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px v2-scan"
          style={{ background: `linear-gradient(90deg, transparent, ${CYAN}, transparent)` }} />
        {/* header */}
        <div className="flex items-center justify-between gap-3 border-b border-border/70 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="v2-ping absolute inline-flex h-full w-full rounded-full" style={{ background: CYAN }} />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ background: CYAN }} />
            </span>
            <span className="font-mono text-xs tracking-widest text-primary uppercase">Breakout Radar · Live</span>
          </div>
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {7612 + (tick % 9)} channels · 6h
          </span>
        </div>
        {/* column headers */}
        <div className="grid grid-cols-[1fr_auto_auto] gap-3 px-5 pt-3 pb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          <span>Breaking now</span>
          <span className="text-right">vs channel</span>
          <span className="text-right pr-1">P(break)</span>
        </div>
        {/* rows */}
        <div className="px-2 pb-2">
          {rows.map((r, i) => {
            const hue = nicheHue[r.niche] ?? CYAN;
            return (
              <div key={`${r.channel}-${i}-${r.ageMin}`}
                className={`grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-lg px-3 py-2.5 ${i === 0 ? "v2-flash-in" : ""}`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded"
                      style={{ color: hue, background: `${hue.replace(")", " / 0.12)")}`, border: `1px solid ${hue.replace(")", " / 0.25)")}` }}>
                      {r.niche}
                    </span>
                    <span className="truncate text-[13px] font-medium text-foreground/95">{r.title}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                    <span className="truncate">{r.channel}</span>
                    <span className="opacity-40">·</span>
                    <span className="tabular-nums">{r.ageMin}m ago</span>
                  </div>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <Sparkline points={r.spark} color={hue} />
                  <span className="font-mono text-sm font-semibold tabular-nums" style={{ color: AMBER }}>
                    {r.mult.toFixed(1)}×
                  </span>
                </div>
                <div className="text-right pr-1">
                  <span className="font-mono text-sm font-semibold tabular-nums text-primary">
                    {r.prob.toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        {/* footer */}
        <div className="flex items-center justify-between border-t border-border/70 px-5 py-3">
          <span className="font-mono text-[11px] text-muted-foreground">
            calibrated · channel-grouped eval
          </span>
          <span className="flex items-center gap-1.5 font-mono text-[11px] text-primary">
            <Gauge className="h-3.5 w-3.5" /> AUC 0.93 @6h
          </span>
        </div>
      </div>
    </div>
  );
}

function RadarDial() {
  return (
    <div aria-hidden className="relative h-72 w-72 sm:h-96 sm:w-96">
      {[1, 0.66, 0.33].map((s) => (
        <div key={s} className="absolute rounded-full border border-primary/15"
          style={{ inset: `${(1 - s) * 50}%` }} />
      ))}
      <div className="absolute left-1/2 top-0 h-1/2 w-px -translate-x-1/2 bg-primary/15" />
      <div className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-primary/15" />
      {/* sweep */}
      <div className="absolute inset-0 v2-sweep" style={{ transformOrigin: "50% 50%" }}>
        <div className="absolute left-1/2 top-1/2 h-1/2 w-1/2 -translate-y-full origin-bottom-left"
          style={{ background: `conic-gradient(from 0deg, ${CYAN.replace(")", " / 0.28)")}, transparent 60%)` }} />
      </div>
      {/* blips */}
      {[[68, 30], [40, 62], [75, 70], [30, 38]].map(([x, y], i) => (
        <span key={i} className="absolute h-2 w-2 rounded-full" style={{ left: `${x}%`, top: `${y}%`, background: i % 2 ? AMBER : CYAN }}>
          <span className="v2-ping absolute inset-0 rounded-full" style={{ background: i % 2 ? AMBER : CYAN }} />
        </span>
      ))}
    </div>
  );
}

function V2Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={`sticky top-0 z-50 transition-colors duration-300 ${scrolled ? "border-b border-border/70 bg-[oklch(0.13_0.01_260_/_0.8)] backdrop-blur-xl" : "border-b border-transparent"}`}>
      <nav className="container mx-auto flex h-16 items-center justify-between">
        <Link href="/v2" className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md" style={{ background: CYAN }}>
            <Radar className="h-4 w-4 text-background" />
          </span>
          <span className="font-display-2 text-lg font-extrabold tracking-tight">ViewMagnet</span>
        </Link>
        <div className="hidden items-center gap-8 md:flex">
          {["Radar", "How it works", "Proof", "Pricing"].map((l) => (
            <a key={l} href={`#${l.toLowerCase().replace(/\s+/g, "-")}`}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground">{l}</a>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Link href="/login" className="hidden text-sm text-muted-foreground transition-colors hover:text-foreground sm:block">Sign in</Link>
          <Link href="/signup"
            className="group inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-background transition-transform hover:scale-[1.03]"
            style={{ background: CYAN }}>
            Start free <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </nav>
    </header>
  );
}

function Ticker() {
  const items = useMemo(
    () => [...SEED, ...INCOMING].map((b) => `${b.channel} · ${b.niche} · ${b.mult.toFixed(1)}× · P ${b.prob.toFixed(2)}`),
    [],
  );
  const tape = [...items, ...items];
  return (
    <div className="relative overflow-hidden border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.5)] py-2.5">
      <div className="v2-marquee flex w-max gap-8 whitespace-nowrap">
        {tape.map((t, i) => (
          <span key={i} className="flex items-center gap-8 font-mono text-[11px] text-muted-foreground">
            <span className="inline-flex h-1.5 w-1.5 rounded-full" style={{ background: i % 3 ? CYAN : AMBER }} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/5 px-3 py-1 font-mono text-[11px] uppercase tracking-widest text-primary">
      {children}
    </span>
  );
}

function SectionHeading({ kicker, title, sub }: { kicker: string; title: React.ReactNode; sub?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <span className="font-mono text-xs uppercase tracking-widest text-primary">{kicker}</span>
      <h2 className="font-display-2 mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">{title}</h2>
      {sub && <p className="mt-4 text-base text-muted-foreground">{sub}</p>}
    </div>
  );
}

export default function HomeV2() {
  useEffect(() => {
    document.title = "ViewMagnet — See it break out before it peaks";
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      {/* ambient backdrop */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 v2-grid v2-radial-fade opacity-60" />
        <div className="absolute left-1/2 top-[-10%] h-[42rem] w-[42rem] -translate-x-1/2 rounded-full blur-[120px] opacity-25"
          style={{ background: `radial-gradient(circle, ${CYAN}, transparent 60%)` }} />
        <div className="absolute right-[-5%] top-[30%] h-[30rem] w-[30rem] rounded-full blur-[120px] opacity-15"
          style={{ background: `radial-gradient(circle, ${AMBER}, transparent 60%)` }} />
        <div className="absolute inset-0 v2-grain opacity-[0.04] mix-blend-overlay" />
      </div>

      <V2Nav />

      {/* ---------------- HERO ---------------- */}
      <section id="radar" className="relative overflow-hidden">
        <div className="container mx-auto grid items-center gap-12 py-16 lg:grid-cols-[1.05fr_1fr] lg:py-24">
          <div>
            <div className="v2-rise" style={{ animationDelay: "0.05s" }}>
              <Eyebrow><Signal className="h-3 w-3" /> Live across 7,600+ channels</Eyebrow>
            </div>
            <h1 className="font-display-2 mt-6 text-[2.6rem] font-extrabold leading-[1.04] tracking-tight sm:text-6xl v2-rise"
              style={{ animationDelay: "0.12s" }}>
              See it break out
              <br />
              <span className="gradient-text">before it peaks.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground v2-rise" style={{ animationDelay: "0.2s" }}>
              Other tools show you what already went viral — a museum of last month's winners.
              ViewMagnet watches the live velocity of the YouTube ecosystem and flags videos
              <span className="text-foreground"> as they break out</span>, with a calibrated probability you can act on while the wave is still rising.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4 v2-rise" style={{ animationDelay: "0.28s" }}>
              <Link href="/signup"
                className="group inline-flex items-center gap-2 rounded-xl px-6 py-3.5 text-base font-semibold text-background transition-transform hover:scale-[1.03] glow-cyan"
                style={{ background: CYAN }}>
                Open the radar <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
              <a href="#how-it-works"
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/40 px-6 py-3.5 text-base font-medium text-foreground transition-colors hover:bg-card">
                How it works
              </a>
            </div>
            <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-xs text-muted-foreground v2-rise" style={{ animationDelay: "0.36s" }}>
              <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> No card to start</span>
              <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> ~30s detection latency</span>
              <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> Honest metrics, shown</span>
            </div>
          </div>
          <div className="v2-rise" style={{ animationDelay: "0.22s" }}>
            <LiveRadar />
          </div>
        </div>
      </section>

      <Ticker />

      {/* ---------------- WEDGE ---------------- */}
      <section className="container mx-auto py-20 sm:py-28">
        <SectionHeading
          kicker="The difference"
          title={<>A static index is a rear-view mirror.<br /><span className="gradient-text">The radar is the windshield.</span></>}
          sub="Indexed-search tools answer 'what already won?' That's history. The only question that grows a channel is 'what's winning right now, and is the wave still open?'"
        />
        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {[
            { icon: Activity, t: "Live, not archived", d: "We sample the velocity of every tracked video at fixed checkpoints (1h → 30d). Breakouts surface in seconds, not after they've already topped out." },
            { icon: Crosshair, t: "Channel-relative", d: "A breakout isn't 'lots of views' — it's a video outpacing its own channel's norm. We measure each video against its baseline, so small channels register too." },
            { icon: TrendingUp, t: "A move, not a metric", d: "Every blip comes with the topic it's riding, how crowded that topic is, and a concrete 'your version of this angle' — grounded only in measured evidence." },
          ].map((c, i) => (
            <div key={i}
              className="group relative overflow-hidden rounded-2xl border border-border bg-card/40 p-6 transition-colors hover:border-primary/40">
              <div aria-hidden className="absolute -right-8 -top-8 h-24 w-24 rounded-full blur-2xl opacity-0 transition-opacity group-hover:opacity-30"
                style={{ background: CYAN }} />
              <c.icon className="h-6 w-6 text-primary" />
              <h3 className="font-display-2 mt-4 text-lg font-bold">{c.t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------- HOW IT WORKS ---------------- */}
      <section id="how-it-works" className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.4)]">
        <div className="container mx-auto py-20 sm:py-28">
          <SectionHeading kicker="How it works" title="Three steps, running continuously." />
          <div className="mt-14 grid gap-8 lg:grid-cols-3">
            {[
              { n: "01", icon: Signal, t: "Collect", d: "A zero-quota push pipeline (WebSub) plus reconciliation tracks ~7,600 channels and time-stamps every video's view trajectory at each checkpoint." },
              { n: "02", icon: Gauge, t: "Calibrate", d: "An isotonic-calibrated model scores how far each video is outpacing its own channel's baseline and converts that into an honest probability of breakout." },
              { n: "03", icon: Zap, t: "Call it", d: "The radar ranks live breakouts by niche, surfaces the topic and its saturation, and hands you a do-it-this-week angle to ride the same wave." },
            ].map((s, i) => (
              <div key={i} className="relative">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-3xl font-bold text-primary/30">{s.n}</span>
                  <span className="h-px flex-1 bg-border" />
                  <s.icon className="h-5 w-5 text-primary" />
                </div>
                <h3 className="font-display-2 mt-5 text-xl font-bold">{s.t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- PROOF / HONEST METRICS ---------------- */}
      <section id="proof" className="container mx-auto py-20 sm:py-28">
        <div className="grid items-center gap-12 lg:grid-cols-[1fr_1.1fr]">
          <div className="flex justify-center">
            <div className="relative">
              <RadarDial />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="font-mono text-5xl font-bold tabular-nums text-primary text-glow-cyan">0.93</div>
                  <div className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">AUC · 6h checkpoint</div>
                </div>
              </div>
            </div>
          </div>
          <div>
            <span className="font-mono text-xs uppercase tracking-widest text-primary">We show our work</span>
            <h2 className="font-display-2 mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">
              Measured honestly, or it doesn't count.
            </h2>
            <p className="mt-4 text-muted-foreground">
              Most "AI for creators" tools quote an accuracy number with no methodology. We publish ours — evaluated
              the hard way, grouped by channel so the model can't cheat by memorising a creator's baseline.
            </p>
            <div className="mt-8 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
              {[
                { k: "Breakout detector", v: "AUC 0.93", note: "calibrated · 6h · channel-grouped" },
                { k: "Detection latency", v: "~30s", note: "WebSub push, not polling" },
                { k: "Channels tracked", v: "7,600+", note: "and auto-expanding weekly" },
                { k: "Evaluation", v: "GroupKFold", note: "lift-over-baseline, never raw R²" },
              ].map((m, i) => (
                <div key={i} className="bg-card/60 p-5">
                  <div className="font-mono text-2xl font-bold tabular-nums text-foreground">{m.v}</div>
                  <div className="mt-1 text-sm font-medium">{m.k}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{m.note}</div>
                </div>
              ))}
            </div>
            <p className="mt-5 flex items-center gap-2 font-mono text-xs text-muted-foreground">
              <ShieldCheck className="h-4 w-4 text-primary" /> No "94% accuracy" theatre. When a model loses to baseline, we say so.
            </p>
          </div>
        </div>
      </section>

      {/* ---------------- TOOLKIT ---------------- */}
      <section className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.4)]">
        <div className="container mx-auto py-20 sm:py-28">
          <SectionHeading
            kicker="Beyond the radar"
            title="Once you've spotted the wave, ride it."
            sub="The radar finds the opening. The rest of the toolkit helps you ship the video that takes it — all grounded in the same live data."
          />
          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { icon: Sparkles, t: "Breakout Explainer", d: "Why this is winning + your concrete angle — grounded only in measured evidence." },
              { icon: Gauge, t: "Candidate Ranker", d: "Score your title + thumbnail options against a fine-tuned reach model before you publish." },
              { icon: Activity, t: "Video Analyzer", d: "Run any video through the content classifier for an honest read on packaging." },
              { icon: Bell, t: "Smart Alerts", d: "Get pinged the moment a video in your niche — or your own — starts to break out." },
            ].map((c, i) => (
              <div key={i} className="rounded-2xl border border-border bg-card/40 p-5 transition-transform hover:-translate-y-1">
                <c.icon className="h-5 w-5 text-primary" />
                <h3 className="font-display-2 mt-4 font-bold">{c.t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- PRICING ---------------- */}
      <section id="pricing" className="container mx-auto py-20 sm:py-28">
        <SectionHeading kicker="Pricing" title="Start on the free tier. Upgrade when the radar earns it." />
        <div className="mx-auto mt-14 grid max-w-4xl gap-6 md:grid-cols-2">
          {/* Free */}
          <div className="rounded-2xl border border-border bg-card/40 p-8">
            <h3 className="font-display-2 text-xl font-bold">Scout</h3>
            <p className="mt-1 text-sm text-muted-foreground">For finding your footing.</p>
            <div className="mt-6 font-display-2 text-4xl font-extrabold">$0<span className="text-base font-normal text-muted-foreground">/mo</span></div>
            <Link href="/signup" className="mt-6 block rounded-lg border border-border bg-card py-3 text-center text-sm font-semibold transition-colors hover:bg-secondary">
              Start free
            </Link>
            <ul className="mt-6 space-y-3 text-sm">
              {["Live Breakout Radar (6h)", "Daily breakout digest", "Video Analyzer", "1 niche watchlist"].map((f) => (
                <li key={f} className="flex items-center gap-2.5 text-muted-foreground">
                  <Check className="h-4 w-4 shrink-0 text-primary" /> {f}
                </li>
              ))}
            </ul>
          </div>
          {/* Pro */}
          <div className="relative rounded-2xl border border-primary/50 bg-card/60 p-8 glow-cyan">
            <span className="absolute right-6 top-6 rounded-full bg-primary/15 px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-primary">Most popular</span>
            <h3 className="font-display-2 text-xl font-bold">Operator</h3>
            <p className="mt-1 text-sm text-muted-foreground">For creators racing the wave.</p>
            <div className="mt-6 font-display-2 text-4xl font-extrabold">$29<span className="text-base font-normal text-muted-foreground">/mo</span></div>
            <Link href="/signup" className="mt-6 block rounded-lg py-3 text-center text-sm font-semibold text-background transition-transform hover:scale-[1.02]" style={{ background: CYAN }}>
              Open the radar
            </Link>
            <ul className="mt-6 space-y-3 text-sm">
              {["Everything in Scout", "All checkpoints (1h–30d)", "Breakout Explainer + your-angle", "Candidate Ranker", "Real-time alerts on your videos", "Unlimited watchlists"].map((f) => (
                <li key={f} className="flex items-center gap-2.5 text-foreground/90">
                  <Check className="h-4 w-4 shrink-0 text-primary" /> {f}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ---------------- FINAL CTA ---------------- */}
      <section className="container mx-auto pb-24">
        <div className="relative overflow-hidden rounded-3xl border border-primary/30 bg-[oklch(0.16_0.01_260_/_0.8)] px-8 py-16 text-center sm:py-20">
          <div aria-hidden className="absolute inset-0 v2-grid opacity-40" />
          <div aria-hidden className="absolute left-1/2 top-0 h-64 w-64 -translate-x-1/2 rounded-full blur-[100px] opacity-30" style={{ background: CYAN }} />
          <div className="relative">
            <h2 className="font-display-2 mx-auto max-w-2xl text-3xl font-extrabold tracking-tight sm:text-5xl">
              The next breakout in your niche is happening <span className="gradient-text">right now.</span>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-muted-foreground">
              You can read about it next month, or you can be early. Open the radar free — no card, ~30 seconds to your first live feed.
            </p>
            <Link href="/signup"
              className="group mt-9 inline-flex items-center gap-2 rounded-xl px-8 py-4 text-base font-semibold text-background transition-transform hover:scale-[1.03] glow-cyan"
              style={{ background: CYAN }}>
              Start tracking free <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}

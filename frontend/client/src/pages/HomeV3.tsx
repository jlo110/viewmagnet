import { useEffect, useState } from "react";
import { Link } from "wouter";
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  Check,
  Clapperboard,
  Compass,
  Gauge,
  LineChart,
  Radar,
  Rocket,
  Scissors,
  Search,
  Sparkles,
  Star,
  Target,
  TrendingUp,
  Wand2,
  Zap,
} from "lucide-react";
import Footer from "@/components/sections/Footer";

/* ============================================================
   ViewMagnet — Homepage v3
   Goal: easy to understand, eye-catching, conversion-focused.
   Spine = the product's closed loop (from the Product Catalog):
   Find → Decide → Make → Publish → Learn.
   Lead with the wedge (live Breakout Radar), then make the full
   offering digestible so visitors GET it and WANT it.
   ============================================================ */

const CYAN = "oklch(0.82 0.15 200)";
const AMBER = "oklch(0.82 0.15 80)";

/* ---------- small reusable bits ---------- */
function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/5 px-3 py-1 font-mono text-[11px] uppercase tracking-widest text-primary">
      {children}
    </span>
  );
}

function PrimaryCTA({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <Link href="/signup"
      className={`group inline-flex items-center gap-2 rounded-xl px-6 py-3.5 text-base font-semibold text-background transition-transform hover:scale-[1.03] glow-cyan ${className}`}
      style={{ background: CYAN }}>
      {children}
      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
    </Link>
  );
}

function Heading({ kicker, title, sub }: { kicker: string; title: React.ReactNode; sub?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <span className="font-mono text-xs uppercase tracking-widest text-primary">{kicker}</span>
      <h2 className="font-display-2 mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">{title}</h2>
      {sub && <p className="mt-4 text-base leading-relaxed text-muted-foreground">{sub}</p>}
    </div>
  );
}

/* ---------- hero product visual: compact live radar ---------- */
const FEED = [
  { niche: "Tech", title: "I rebuilt my PC inside a fish tank", mult: "11.4×", prob: "0.94", hue: CYAN },
  { niche: "Gaming", title: "The patch nobody noticed broke the meta", mult: "7.8×", prob: "0.91", hue: AMBER },
  { niche: "News", title: "What the earnings call actually admitted", mult: "6.1×", prob: "0.88", hue: CYAN },
  { niche: "Food", title: "The 4-ingredient bread that broke my comments", mult: "4.7×", prob: "0.83", hue: AMBER },
  { niche: "Finance", title: "The boring trade that beat every fund", mult: "3.9×", prob: "0.79", hue: CYAN },
];

function RadarShowpiece() {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((x) => x + 1), 2000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="relative">
      <div aria-hidden className="absolute -inset-6 rounded-[2rem] blur-2xl opacity-40"
        style={{ background: `radial-gradient(60% 60% at 70% 0%, ${CYAN}, transparent 70%)` }} />
      <div className="relative overflow-hidden rounded-2xl border border-border/80 bg-[oklch(0.15_0.01_260_/_0.9)] shadow-2xl backdrop-blur-xl">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px v2-scan"
          style={{ background: `linear-gradient(90deg, transparent, ${CYAN}, transparent)` }} />
        <div className="flex items-center justify-between border-b border-border/70 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="v2-ping absolute inline-flex h-full w-full rounded-full" style={{ background: CYAN }} />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ background: CYAN }} />
            </span>
            <span className="font-mono text-xs uppercase tracking-widest text-primary">Breaking out now</span>
          </div>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{7612 + (n % 7)} channels</span>
        </div>
        <div className="divide-y divide-border/40">
          {FEED.map((r, i) => (
            <div key={i} className={`flex items-center gap-3 px-5 py-3 ${i === (n % FEED.length) ? "bg-primary/5" : ""}`}>
              <span className="font-mono text-[10px] rounded px-1.5 py-0.5"
                style={{ color: r.hue, background: r.hue.replace(")", " / 0.12)"), border: `1px solid ${r.hue.replace(")", " / 0.25)")}` }}>
                {r.niche}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground/95">{r.title}</span>
              <span className="font-mono text-sm font-semibold tabular-nums" style={{ color: AMBER }}>{r.mult}</span>
              <span className="font-mono text-sm font-semibold tabular-nums text-primary">{r.prob}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between border-t border-border/70 px-5 py-3 font-mono text-[11px] text-muted-foreground">
          <span>vs the channel's own norm · P(breakout)</span>
          <span className="flex items-center gap-1.5 text-primary"><Gauge className="h-3.5 w-3.5" /> AUC 0.93</span>
        </div>
      </div>
    </div>
  );
}

/* ---------- mock product visuals for feature rows ---------- */
function RankerMock() {
  const rows = [
    { label: "Thumbnail A · \"I tried it for 30 days\"", score: 92, win: true },
    { label: "Thumbnail B · \"The truth about…\"", score: 74, win: false },
    { label: "Thumbnail C · \"My honest review\"", score: 61, win: false },
  ];
  return (
    <div className="rounded-2xl border border-border bg-card/50 p-5">
      <div className="mb-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">Predicted reach</div>
      <div className="space-y-3">
        {rows.map((r, i) => (
          <div key={i}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className={r.win ? "font-semibold text-foreground" : "text-muted-foreground"}>{r.label}</span>
              <span className="font-mono font-semibold" style={{ color: r.win ? CYAN : "var(--muted-foreground)" }}>{r.score}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full" style={{ width: `${r.score}%`, background: r.win ? CYAN : "oklch(0.4 0.01 260)" }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs" style={{ borderColor: CYAN.replace(")", " / 0.3)"), background: CYAN.replace(")", " / 0.06)") }}>
        <Star className="h-3.5 w-3.5" style={{ color: CYAN }} /> <span className="text-foreground/90">Ship <b>A</b> — strongest packaging before you publish.</span>
      </div>
    </div>
  );
}

function StudioMock() {
  return (
    <div className="rounded-2xl border border-border bg-card/50 p-5">
      <div className="mb-3 flex items-center justify-between font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        <span>Studio · timeline</span><span style={{ color: CYAN }}>9:16</span>
      </div>
      <div className="aspect-video rounded-lg border border-border bg-background/60 flex items-center justify-center">
        <Clapperboard className="h-8 w-8 text-muted-foreground/40" />
      </div>
      <div className="mt-3 space-y-1.5">
        {[["Clip", CYAN, "70%"], ["Captions", AMBER, "100%"], ["B-roll", CYAN, "40%"]].map(([l, c, w], i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-14 font-mono text-[10px] text-muted-foreground">{l as string}</span>
            <div className="h-3 flex-1 rounded bg-secondary overflow-hidden">
              <div className="h-full rounded" style={{ width: w as string, background: c as string, opacity: 0.7 }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyzerMock() {
  return (
    <div className="rounded-2xl border border-border bg-card/50 p-5">
      <div className="mb-4 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">Packaging read</div>
      <div className="flex items-center gap-5">
        <div className="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 36 36" className="h-24 w-24 -rotate-90">
            <circle cx="18" cy="18" r="15.9" fill="none" stroke="oklch(0.25 0.01 260)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.9" fill="none" stroke={CYAN} strokeWidth="3" strokeDasharray="100" strokeDashoffset="26" strokeLinecap="round" />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center font-mono text-xl font-bold text-primary">74</div>
        </div>
        <ul className="space-y-2 text-sm">
          {[["Hook clarity", true], ["Curiosity gap", true], ["Title length", false]].map(([l, ok], i) => (
            <li key={i} className="flex items-center gap-2 text-muted-foreground">
              <Check className="h-3.5 w-3.5" style={{ color: ok ? CYAN : AMBER }} /> {l as string}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------- nav ---------- */
function V3Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={`sticky top-0 z-50 transition-colors duration-300 ${scrolled ? "border-b border-border/70 bg-[oklch(0.13_0.01_260_/_0.8)] backdrop-blur-xl" : "border-b border-transparent"}`}>
      <nav className="container mx-auto flex h-16 items-center justify-between">
        <Link href="/v3" className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md" style={{ background: CYAN }}>
            <Radar className="h-4 w-4 text-background" />
          </span>
          <span className="font-display-2 text-lg font-extrabold tracking-tight">ViewMagnet</span>
        </Link>
        <div className="hidden items-center gap-8 md:flex">
          {[["How it works", "#loop"], ["Features", "#features"], ["Proof", "#proof"], ["Pricing", "#pricing"]].map(([l, h]) => (
            <a key={l} href={h} className="text-sm text-muted-foreground transition-colors hover:text-foreground">{l}</a>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Link href="/login" className="hidden text-sm text-muted-foreground transition-colors hover:text-foreground sm:block">Sign in</Link>
          <Link href="/signup" className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-background transition-transform hover:scale-[1.03]" style={{ background: CYAN }}>
            Start free
          </Link>
        </div>
      </nav>
    </header>
  );
}

/* ---------- the loop stages ---------- */
const LOOP = [
  { icon: Search, stage: "Find", line: "What's breaking out in your niche right now", tools: ["Breakout Radar", "Trend Timing", "Keyword Research"], hue: CYAN },
  { icon: Target, stage: "Decide", line: "Will your idea & packaging actually land", tools: ["Candidate Ranker", "Video Analyzer", "A/B Tester"], hue: AMBER },
  { icon: Wand2, stage: "Make", line: "Script, edit, and produce the video", tools: ["Script Writer", "Studio", "Shorts", "Captions"], hue: CYAN },
  { icon: Rocket, stage: "Publish", line: "Ship it everywhere from one place", tools: ["Distribution Hub", "Smart Alerts"], hue: AMBER },
  { icon: LineChart, stage: "Learn", line: "See what worked and feed it back in", tools: ["Outcomes", "Impact"], hue: CYAN },
];

export default function HomeV3() {
  useEffect(() => { document.title = "ViewMagnet — Know your next video before you film it"; }, []);

  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      {/* ambient backdrop */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 v2-grid v2-radial-fade opacity-50" />
        <div className="absolute left-1/2 top-[-12%] h-[40rem] w-[40rem] -translate-x-1/2 rounded-full blur-[120px] opacity-25" style={{ background: `radial-gradient(circle, ${CYAN}, transparent 60%)` }} />
        <div className="absolute inset-0 v2-grain opacity-[0.035] mix-blend-overlay" />
      </div>

      <V3Nav />

      {/* ---------------- HERO ---------------- */}
      <section className="container mx-auto grid items-center gap-12 py-16 lg:grid-cols-[1.05fr_1fr] lg:py-24">
        <div>
          <div className="v2-rise" style={{ animationDelay: "0.05s" }}><Pill><Zap className="h-3 w-3" /> YouTube growth intelligence</Pill></div>
          <h1 className="font-display-2 mt-6 text-[2.7rem] font-extrabold leading-[1.05] tracking-tight sm:text-6xl v2-rise" style={{ animationDelay: "0.12s" }}>
            Know your next video <span className="gradient-text">before you film it.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground v2-rise" style={{ animationDelay: "0.2s" }}>
            ViewMagnet watches YouTube's live velocity across <span className="text-foreground">7,600+ channels</span>, spots what's
            breaking out <span className="text-foreground">right now</span>, tells you why — then helps you make and publish your
            version before the wave peaks. The whole workflow, one app.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4 v2-rise" style={{ animationDelay: "0.28s" }}>
            <PrimaryCTA>Start free</PrimaryCTA>
            <a href="#loop" className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/40 px-6 py-3.5 text-base font-medium transition-colors hover:bg-card">
              See how it works
            </a>
          </div>
          <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-xs text-muted-foreground v2-rise" style={{ animationDelay: "0.36s" }}>
            <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> Free to start, no card</span>
            <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> Live in 30 seconds</span>
          </div>
        </div>
        <div className="v2-rise v2-float" style={{ animationDelay: "0.22s" }}><RadarShowpiece /></div>
      </section>

      {/* ---------------- STAT BAR ---------------- */}
      <section className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.5)]">
        <div className="container mx-auto grid grid-cols-2 gap-6 py-8 sm:grid-cols-4">
          {[
            ["7,600+", "channels tracked live"],
            ["~30s", "breakout detection"],
            ["0.93", "AUC, calibrated"],
            ["30+", "tools, one workflow"],
          ].map(([v, l], i) => (
            <div key={i} className="text-center">
              <div className="font-display-2 text-3xl font-extrabold tabular-nums text-foreground sm:text-4xl">{v}</div>
              <div className="mt-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------- PROBLEM ---------------- */}
      <section className="container mx-auto py-20 text-center sm:py-24">
        <h2 className="font-display-2 mx-auto max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
          The #1 reason channels stall isn't editing.<br />
          It's <span className="gradient-text">making videos nobody was looking for.</span>
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-muted-foreground">
          Every other tool shows you what <i>already</i> went viral — last month's winners, in a museum.
          By the time you copy it, the wave's gone. ViewMagnet shows you what's rising <i>now</i>, while you can still catch it.
        </p>
      </section>

      {/* ---------------- THE LOOP (the offering, made simple) ---------------- */}
      <section id="loop" className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.4)]">
        <div className="container mx-auto py-20 sm:py-28">
          <Heading kicker="How it works" title={<>One simple loop, run for you.</>}
            sub="Most creators stitch this together across five different tools. ViewMagnet runs the whole loop in one place — each step feeds the next." />
          <div className="mt-14 grid gap-4 lg:grid-cols-5">
            {LOOP.map((s, i) => (
              <div key={i} className="relative rounded-2xl border border-border bg-card/40 p-5">
                {i < LOOP.length - 1 && (
                  <ArrowRight aria-hidden className="absolute -right-3 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-border lg:block" />
                )}
                <div className="flex items-center gap-2">
                  <span className="font-mono text-2xl font-bold" style={{ color: s.hue, opacity: 0.4 }}>{i + 1}</span>
                  <s.icon className="h-5 w-5" style={{ color: s.hue }} />
                </div>
                <h3 className="font-display-2 mt-3 text-lg font-bold">{s.stage}</h3>
                <p className="mt-1 text-sm leading-snug text-muted-foreground">{s.line}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.tools.map((t) => (
                    <span key={t} className="rounded-md bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-8 flex items-center justify-center gap-2 font-mono text-xs text-muted-foreground">
            <span className="h-px w-8 bg-border" /> and the loop repeats, smarter each time <span className="h-px w-8 bg-border" />
          </div>
        </div>
      </section>

      {/* ---------------- FEATURE SPOTLIGHTS ---------------- */}
      <section id="features" className="container mx-auto py-20 sm:py-28">
        <Heading kicker="The good stuff" title="See it, decide it, make it." />
        <div className="mt-16 space-y-20">
          {/* 1 — Radar */}
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div>
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-primary"><Radar className="h-4 w-4" /> Breakout Radar</span>
              <h3 className="font-display-2 mt-3 text-2xl font-bold sm:text-3xl">Catch the wave while it's still rising.</h3>
              <p className="mt-4 text-muted-foreground">
                A live feed of videos breaking out across YouTube right now — ranked by how far each is outpacing its <i>own</i> channel's
                norm, with a calibrated probability and the topic it's riding. Small channel? You'll still show up — we measure breakouts
                relative to baseline, not raw views.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                {["Filter by your niche", "See if the topic is crowded or open", "Get a do-it-this-week angle, grounded in real evidence"].map((f) => (
                  <li key={f} className="flex items-center gap-2.5 text-foreground/90"><Check className="h-4 w-4 shrink-0 text-primary" /> {f}</li>
                ))}
              </ul>
            </div>
            <RadarShowpiece />
          </div>
          {/* 2 — Ranker (reverse) */}
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div className="lg:order-2">
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-primary"><Target className="h-4 w-4" /> Ranker + Analyzer</span>
              <h3 className="font-display-2 mt-3 text-2xl font-bold sm:text-3xl">Pick the winning packaging before you post.</h3>
              <p className="mt-4 text-muted-foreground">
                Drop in your title and thumbnail options and get a predicted-reach score for each — so you publish the strongest one, not
                your favorite one. Run any video through the analyzer for an honest read on its hook and packaging.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                {["Score 2–4 options head to head", "Honest model, real metrics — no hype", "Diagnose competitors the same way"].map((f) => (
                  <li key={f} className="flex items-center gap-2.5 text-foreground/90"><Check className="h-4 w-4 shrink-0 text-primary" /> {f}</li>
                ))}
              </ul>
            </div>
            <div className="lg:order-1 space-y-4"><RankerMock /><AnalyzerMock /></div>
          </div>
          {/* 3 — Studio */}
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div>
              <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-primary"><Clapperboard className="h-4 w-4" /> Studio</span>
              <h3 className="font-display-2 mt-3 text-2xl font-bold sm:text-3xl">Make the video without leaving the app.</h3>
              <p className="mt-4 text-muted-foreground">
                Turn a long video into vertical Shorts, add word-level animated captions, smart-crop to follow the subject, drop in B-roll,
                and render — then publish. The recommendation you acted on rides all the way through, so outcomes attribute back to it.
              </p>
              <ul className="mt-5 space-y-2 text-sm">
                {["Auto-detect highlights → Shorts", "Animated captions + subject tracking", "Voiceover, dubbing & faceless workflows"].map((f) => (
                  <li key={f} className="flex items-center gap-2.5 text-foreground/90"><Check className="h-4 w-4 shrink-0 text-primary" /> {f}</li>
                ))}
              </ul>
            </div>
            <StudioMock />
          </div>
        </div>
      </section>

      {/* ---------------- PROOF ---------------- */}
      <section id="proof" className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.4)]">
        <div className="container mx-auto py-20 text-center sm:py-24">
          <Pill><Sparkles className="h-3 w-3" /> We show our work</Pill>
          <h2 className="font-display-2 mx-auto mt-5 max-w-2xl text-3xl font-extrabold tracking-tight sm:text-4xl">
            Real numbers. Measured the honest way.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
            No "94% accuracy" theatre. Our models are evaluated grouped by channel — so they can't cheat by memorizing a creator —
            and when a model loses to baseline, we say so.
          </p>
          <div className="mx-auto mt-10 grid max-w-3xl gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-3">
            {[
              ["AUC 0.93", "Breakout detector @6h"],
              ["~30s", "Detection latency"],
              ["7,600+", "Channels, auto-expanding"],
            ].map(([v, l], i) => (
              <div key={i} className="bg-card/60 p-6">
                <div className="font-mono text-3xl font-bold tabular-nums text-primary">{v}</div>
                <div className="mt-1 text-sm text-muted-foreground">{l}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- FULL TOOLKIT (breadth, digestible) ---------------- */}
      <section className="container mx-auto py-20 sm:py-28">
        <Heading kicker="Everything included" title="30+ tools. Two jobs." sub="Figure out what works — then make it. Every plan includes the whole toolkit; you grow into it." />
        <div className="mt-14 grid gap-6 md:grid-cols-2">
          <div className="rounded-2xl border border-border bg-card/40 p-7">
            <div className="flex items-center gap-2 text-primary"><Compass className="h-5 w-5" /><h3 className="font-display-2 text-lg font-bold">Intelligence — what to make</h3></div>
            <div className="mt-4 flex flex-wrap gap-2">
              {["Breakout Radar", "Breakout Explainer", "Candidate Ranker", "Video Analyzer", "Velocity Tracker", "Winning Formula", "Competitor Analysis", "Trend Timing", "A/B Tester", "Keyword Research", "Impact"].map((t) => (
                <span key={t} className="rounded-lg border border-border bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90">{t}</span>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-border bg-card/40 p-7">
            <div className="flex items-center gap-2" style={{ color: AMBER }}><Scissors className="h-5 w-5" /><h3 className="font-display-2 text-lg font-bold text-foreground">Create — make &amp; ship it</h3></div>
            <div className="mt-4 flex flex-wrap gap-2">
              {["Title Generator", "Script Writer", "AI Writer", "Hook Lab", "Thumbnail Creator", "Studio", "Shorts Creator", "Animated Captions", "Voiceover", "Voice Dubbing", "Faceless Generator", "Distribution Hub", "Smart Alerts", "Outcomes"].map((t) => (
                <span key={t} className="rounded-lg border border-border bg-secondary/60 px-3 py-1.5 text-xs text-foreground/90">{t}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- PRICING ---------------- */}
      <section id="pricing" className="border-y border-border/60 bg-[oklch(0.15_0.01_260_/_0.4)]">
        <div className="container mx-auto py-20 sm:py-28">
          <Heading kicker="Pricing" title="Start free. Upgrade when it pays for itself." />
          <div className="mx-auto mt-14 grid max-w-4xl gap-6 md:grid-cols-2">
            <div className="rounded-2xl border border-border bg-card/40 p-8">
              <h3 className="font-display-2 text-xl font-bold">Free</h3>
              <p className="mt-1 text-sm text-muted-foreground">Find your footing.</p>
              <div className="mt-6 font-display-2 text-4xl font-extrabold">$0<span className="text-base font-normal text-muted-foreground">/mo</span></div>
              <Link href="/signup" className="mt-6 block rounded-lg border border-border bg-card py-3 text-center text-sm font-semibold transition-colors hover:bg-secondary">Start free</Link>
              <ul className="mt-6 space-y-3 text-sm">
                {["Live Breakout Radar", "Daily breakout digest", "Video Analyzer", "1 niche watchlist"].map((f) => (
                  <li key={f} className="flex items-center gap-2.5 text-muted-foreground"><Check className="h-4 w-4 shrink-0 text-primary" /> {f}</li>
                ))}
              </ul>
            </div>
            <div className="relative rounded-2xl border border-primary/50 bg-card/60 p-8 glow-cyan">
              <span className="absolute right-6 top-6 rounded-full bg-primary/15 px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-primary">Most popular</span>
              <h3 className="font-display-2 text-xl font-bold">Pro</h3>
              <p className="mt-1 text-sm text-muted-foreground">Race the wave, every week.</p>
              <div className="mt-6 font-display-2 text-4xl font-extrabold">$29<span className="text-base font-normal text-muted-foreground">/mo</span></div>
              <Link href="/signup" className="mt-6 block rounded-lg py-3 text-center text-sm font-semibold text-background transition-transform hover:scale-[1.02]" style={{ background: CYAN }}>Get Pro</Link>
              <ul className="mt-6 space-y-3 text-sm">
                {["Everything in Free", "All checkpoints + explainers", "Candidate Ranker + full Studio", "Real-time alerts on your videos", "Distribution to YouTube, TikTok, IG", "All 30+ tools, unlimited"].map((f) => (
                  <li key={f} className="flex items-center gap-2.5 text-foreground/90"><Check className="h-4 w-4 shrink-0 text-primary" /> {f}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------- FAQ ---------------- */}
      <section className="container mx-auto py-20 sm:py-24">
        <Heading kicker="Questions" title="Good to know." />
        <div className="mx-auto mt-12 max-w-3xl divide-y divide-border">
          {[
            ["Do I need to connect my YouTube channel?", "No. The radar works on the whole tracked ecosystem out of the box. Connecting your channel unlocks alerts and outcome tracking for your own videos."],
            ["How is this different from TubeBuddy / vidIQ / a 'viral videos' site?", "Those are keyword tools and static archives of what already won. ViewMagnet detects breakouts live — relative to each channel's own baseline — so you catch waves while they're still rising."],
            ["Is the 'AI' real or hype?", "We publish our metrics and evaluate honestly (channel-grouped, lift over baseline). The breakout detector is calibrated at AUC 0.93 @6h. When something doesn't beat a simple baseline, we don't ship it as a number."],
            ["Can I actually make videos in it?", "Yes — Studio handles Shorts, captions, subject-tracked crops, voiceover, and rendering, then publishes. It's the whole loop, not just analytics."],
          ].map(([q, a], i) => (
            <details key={i} className="group py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
                <span className="font-display-2 font-semibold">{q}</span>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* ---------------- FINAL CTA ---------------- */}
      <section className="container mx-auto pb-24">
        <div className="relative overflow-hidden rounded-3xl border border-primary/30 bg-[oklch(0.16_0.01_260_/_0.8)] px-8 py-16 text-center sm:py-20">
          <div aria-hidden className="absolute inset-0 v2-grid opacity-40" />
          <div aria-hidden className="absolute left-1/2 top-0 h-64 w-64 -translate-x-1/2 rounded-full blur-[100px] opacity-30" style={{ background: CYAN }} />
          <div className="relative">
            <h2 className="font-display-2 mx-auto max-w-2xl text-3xl font-extrabold tracking-tight sm:text-5xl">
              Your next breakout is happening <span className="gradient-text">right now.</span>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-muted-foreground">Be early, not late. Open the radar free — no card, 30 seconds to your first live feed.</p>
            <div className="mt-9 flex justify-center">
              <Link href="/signup" className="group inline-flex items-center gap-2 rounded-xl px-8 py-4 text-base font-semibold text-background transition-transform hover:scale-[1.03] glow-cyan" style={{ background: CYAN }}>
                Start free <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </Link>
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 font-mono text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5"><Check className="h-3.5 w-3.5 text-primary" /> No credit card</span>
              <span className="flex items-center gap-1.5"><Bell className="h-3.5 w-3.5 text-primary" /> Cancel anytime</span>
              <span className="flex items-center gap-1.5"><BarChart3 className="h-3.5 w-3.5 text-primary" /> Honest metrics</span>
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}

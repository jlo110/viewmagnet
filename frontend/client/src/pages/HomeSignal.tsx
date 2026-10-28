/*
 * HomeSignal: ViewMagnet v2 "Signal" landing. ADDITIVE: lives at /signal,
 * wrapped in `.theme-v2` so it does not affect v1 (Home / HomeV2 / HomeV3).
 *
 * Design read: B2B video-intelligence SaaS landing for creator/agency buyers.
 * Dark-locked, single signal-lime accent, Bricolage display. Dials 8 / 7 / 4.
 * Positioning is the brand's real integrity line: we DETECT what's breaking out
 * live, we do not predict your packaging or forecast views.
 */
import { Link } from "wouter";
import { motion, useReducedMotion } from "framer-motion";
import {
  Radar,
  Eye,
  Activity,
  Microscope,
  Flame,
  ArrowUpRight,
  Webhook,
  ShieldCheck,
} from "lucide-react";

const ease = [0.16, 1, 0.3, 1] as const;

export default function HomeSignal() {
  return (
    <div className="theme-v2 min-h-[100dvh] bg-background text-foreground antialiased selection:bg-primary/25">
      <SignalNav />
      <Hero />
      <ScaleStrip />
      <Wedge />
      <RadarFeature />
      <Capabilities />
      <HowItWorks />
      <Honesty />
      <CtaClose />
      <SignalFooter />
    </div>
  );
}

/* ───────────────────────── Nav (single line, ≤72px) ───────────────────── */
function SignalNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5">
        <Link href="/signal" className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-primary text-primary-foreground">
            <Radar className="h-4 w-4" />
          </span>
          <span className="font-[var(--font-display)] text-[17px] font-semibold tracking-tight">
            ViewMagnet
          </span>
        </Link>
        <div className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
          <a href="#radar" className="transition-colors hover:text-foreground">Radar</a>
          <a href="#capabilities" className="transition-colors hover:text-foreground">Capabilities</a>
          <a href="#how" className="transition-colors hover:text-foreground">How it works</a>
          <a href="#honesty" className="transition-colors hover:text-foreground">Our stance</a>
        </div>
        <Link
          href="/dashboard"
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-transform active:translate-y-px"
        >
          Start watching
        </Link>
      </nav>
    </header>
  );
}

/* ───────────────────────────── Hero ───────────────────────────────────── */
function Hero() {
  const reduce = useReducedMotion();
  const rise = (delay: number) => ({
    initial: reduce ? false : { opacity: 0, y: 22 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.7, delay, ease },
  });

  return (
    <section className="relative overflow-hidden">
      <BackdropGlow />
      <div className="mx-auto grid max-w-7xl items-center gap-12 px-5 pb-24 pt-20 lg:grid-cols-[1.05fr_0.95fr] lg:pt-24">
        <div>
          <motion.div
            {...rise(0)}
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-border/70 bg-card/60 px-3 py-1.5 text-xs text-muted-foreground"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/70" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            Live across 7,700+ channels
          </motion.div>

          <motion.h1
            {...rise(0.06)}
            className="font-[var(--font-display)] text-[2.6rem] font-semibold leading-[1.04] tracking-tight sm:text-6xl"
          >
            See what's breaking out
            <br />
            <span className="text-primary">before the dust settles.</span>
          </motion.h1>

          <motion.p {...rise(0.12)} className="mt-6 max-w-[34rem] text-lg leading-relaxed text-muted-foreground">
            We flag videos the moment they outrun their channel. Detection you can act on, not a
            thumbnail guess.
          </motion.p>

          <motion.div {...rise(0.18)} className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              href="/dashboard"
              className="group inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-transform active:translate-y-px"
            >
              Start watching
              <ArrowUpRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>
            <a
              href="#radar"
              className="inline-flex items-center gap-2 rounded-lg border border-border px-5 py-3 text-sm font-medium text-foreground transition-colors hover:bg-accent"
            >
              See the radar
            </a>
          </motion.div>
        </div>

        <motion.div
          initial={reduce ? false : { opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.9, delay: 0.1, ease }}
          className="relative"
        >
          <RadarViz />
        </motion.div>
      </div>
    </section>
  );
}

function BackdropGlow() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
      <div className="absolute left-1/2 top-[-10%] h-[42rem] w-[42rem] -translate-x-1/2 rounded-full bg-primary/[0.07] blur-[120px]" />
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px)",
          backgroundSize: "56px 56px",
          maskImage: "radial-gradient(ellipse 70% 60% at 50% 30%, #000 40%, transparent 75%)",
        }}
      />
    </div>
  );
}

/* A real radar data-viz (not a fake product screenshot): sweep + breakout blips. */
function RadarViz() {
  const reduce = useReducedMotion();
  const blips = [
    { cx: 168, cy: 96, r: 5, d: "0s" },
    { cx: 232, cy: 150, r: 4, d: "0.6s" },
    { cx: 120, cy: 190, r: 6, d: "1.1s" },
    { cx: 205, cy: 214, r: 3.5, d: "1.7s" },
    { cx: 96, cy: 132, r: 3, d: "2.2s" },
  ];
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[460px]">
      <svg viewBox="0 0 300 300" className="h-full w-full">
        <defs>
          <radialGradient id="rg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.18" />
            <stop offset="70%" stopColor="var(--color-primary)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0.5" />
          </linearGradient>
        </defs>
        <circle cx="150" cy="150" r="148" fill="url(#rg)" />
        {[40, 80, 120, 148].map((r) => (
          <circle key={r} cx="150" cy="150" r={r} fill="none" stroke="var(--color-border)" strokeOpacity="0.6" />
        ))}
        <line x1="2" y1="150" x2="298" y2="150" stroke="var(--color-border)" strokeOpacity="0.5" />
        <line x1="150" y1="2" x2="150" y2="298" stroke="var(--color-border)" strokeOpacity="0.5" />
        {!reduce && (
          <g style={{ transformOrigin: "150px 150px", animation: "vm-sweep 4s linear infinite" }}>
            <path d="M150 150 L150 2 A148 148 0 0 1 268 80 Z" fill="url(#sweep)" />
          </g>
        )}
        {blips.map((b, i) => (
          <g key={i}>
            <circle cx={b.cx} cy={b.cy} r={b.r} fill="var(--color-primary)" />
            {!reduce && (
              <circle cx={b.cx} cy={b.cy} r={b.r} fill="none" stroke="var(--color-primary)" strokeOpacity="0.6">
                <animate attributeName="r" from={b.r} to={b.r + 14} dur="2.4s" begin={b.d} repeatCount="indefinite" />
                <animate attributeName="stroke-opacity" from="0.6" to="0" dur="2.4s" begin={b.d} repeatCount="indefinite" />
              </circle>
            )}
          </g>
        ))}
      </svg>
      <div className="absolute bottom-3 left-3 rounded-lg border border-border/70 bg-card/80 px-3 py-2 backdrop-blur">
        <p className="font-mono text-[11px] text-muted-foreground">DETECTED · 6h window</p>
        <p className="font-[var(--font-display)] text-lg font-semibold text-foreground">
          14 <span className="text-primary">breaking out</span>
        </p>
      </div>
    </div>
  );
}

/* ───────────────────────── Scale strip (under hero) ───────────────────── */
function ScaleStrip() {
  const stats = [
    { k: "7,700+", v: "channels watched live" },
    { k: "Hourly", v: "breakout sweeps" },
    { k: "Sustain vs flash", v: "durability on every call" },
    { k: "0", v: "packaging predictions sold" },
  ];
  return (
    <section className="border-y border-border/60 bg-card/30">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-px overflow-hidden md:grid-cols-4">
        {stats.map((s) => (
          <div key={s.v} className="bg-background px-5 py-7">
            <p className="font-[var(--font-display)] text-2xl font-semibold tracking-tight text-foreground">{s.k}</p>
            <p className="mt-1 text-sm text-muted-foreground">{s.v}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ───────────────────────── Wedge (manifesto) ─────────────────────────── */
function Wedge() {
  return (
    <Reveal>
      <section className="mx-auto max-w-5xl px-5 py-28 text-center">
        <h2 className="font-[var(--font-display)] text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">
          We detect. We don't predict.
        </h2>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
          Most tools promise to score your title and forecast your views. We tested that and it
          doesn't hold up. So we sell the thing that does: catching real breakouts across the
          ecosystem early, and telling you whether they'll last.
        </p>
      </section>
    </Reveal>
  );
}

/* ───────────────────────── Radar feature (split) ─────────────────────── */
function RadarFeature() {
  return (
    <Reveal>
      <section id="radar" className="mx-auto grid max-w-7xl items-center gap-12 px-5 py-20 lg:grid-cols-2">
        <div className="order-2 lg:order-1">
          <RadarViz />
        </div>
        <div className="order-1 lg:order-2">
          <h2 className="font-[var(--font-display)] text-3xl font-semibold tracking-tight sm:text-4xl">
            Breakout Radar, in real time
          </h2>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
            The instant a tracked video outruns its channel's own baseline, it lights up the radar
            with a calibrated confidence and the topic it's riding. You're early enough to make your
            own version while the wave is still building.
          </p>
          <ul className="mt-7 space-y-3 text-sm">
            {[
              "Channel-relative detection, not raw view counts",
              "Calibrated probability for every call",
              "Topic saturation, so you know if the lane is crowded",
            ].map((t) => (
              <li key={t} className="flex items-start gap-3">
                <Flame className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span className="text-foreground/90">{t}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </Reveal>
  );
}

/* ───────────────────────── Capabilities (bento) ─────────────────────── */
function Capabilities() {
  return (
    <Reveal>
      <section id="capabilities" className="mx-auto max-w-7xl px-5 py-20">
        <h2 className="max-w-2xl font-[var(--font-display)] text-3xl font-semibold tracking-tight sm:text-4xl">
          One instrument for the whole signal
        </h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          <BentoCard
            className="md:col-span-2 md:row-span-1"
            icon={Eye}
            title="Competitive Watchlist"
            body="Track any public channel (competitors, your whole niche) and get told within hours when one of their videos breaks out. The view Studio can't give you."
            featured
          />
          <BentoCard icon={Activity} title="Durability grading" body="Every breakout comes with a sustain-vs-flash read, so you know what's worth chasing." />
          <BentoCard icon={Microscope} title="Breakout Teardown" body="Reverse-engineer any hit: the format it used, what viewers are saying, and where they re-watched." />
          <BentoCard
            className="md:col-span-2"
            icon={Webhook}
            title="War-room delivery"
            body="Pipe live breakouts straight into Slack or Discord, and group them by client in a portfolio view built for agencies."
            tint
          />
        </div>
      </section>
    </Reveal>
  );
}

function BentoCard({
  icon: Icon,
  title,
  body,
  className = "",
  featured = false,
  tint = false,
}: {
  icon: typeof Eye;
  title: string;
  body: string;
  className?: string;
  featured?: boolean;
  tint?: boolean;
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-xl border border-border/70 p-6 ${
        featured ? "bg-gradient-to-br from-primary/[0.12] via-card to-card" : tint ? "bg-card/80" : "bg-card/50"
      } ${className}`}
    >
      {featured && (
        <div aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-primary/20 blur-3xl" />
      )}
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-primary/15 text-primary">
        <Icon className="h-5 w-5" />
      </span>
      <h3 className="mt-4 font-[var(--font-display)] text-lg font-semibold tracking-tight">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

/* ───────────────────────── How it works (steps) ─────────────────────── */
function HowItWorks() {
  const steps = [
    { n: "Watch", body: "We sample ~7,700 channels around the clock, building each one's own performance baseline." },
    { n: "Detect", body: "When a fresh upload outruns its channel's norm, it clears the breakout threshold and lights up." },
    { n: "Grade", body: "A durability model reads its early trajectory and calls sustain or flash." },
    { n: "Act", body: "You get the teardown and the lane, early enough to ship your own version." },
  ];
  return (
    <Reveal>
      <section id="how" className="border-y border-border/60 bg-card/30">
        <div className="mx-auto max-w-7xl px-5 py-20">
          <h2 className="font-[var(--font-display)] text-3xl font-semibold tracking-tight sm:text-4xl">
            From signal to your next upload
          </h2>
          <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-border/70 bg-border/70 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((s, i) => (
              <div key={s.n} className="bg-background p-6">
                <span className="font-mono text-sm text-primary">0{i + 1}</span>
                <h3 className="mt-3 font-[var(--font-display)] text-xl font-semibold tracking-tight">{s.n}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </Reveal>
  );
}

/* ───────────────────────── Honesty (stance) ─────────────────────────── */
function Honesty() {
  return (
    <Reveal>
      <section id="honesty" className="mx-auto max-w-5xl px-5 py-28">
        <div className="rounded-2xl border border-border/70 bg-gradient-to-br from-card to-background p-9 sm:p-12">
          <ShieldCheck className="h-8 w-8 text-primary" />
          <blockquote className="mt-5 font-[var(--font-display)] text-2xl font-medium leading-snug tracking-tight sm:text-3xl">
            "If a number can't survive an honest test, we won't put it on a dashboard and call it a
            prediction."
          </blockquote>
          <p className="mt-6 max-w-2xl leading-relaxed text-muted-foreground">
            No packaging-to-performance score. No view-count forecast. When we connect your own
            channel we show your real click-through and retention, and we coach from it. We don't
            dress a guess up as a model.
          </p>
        </div>
      </section>
    </Reveal>
  );
}

/* ───────────────────────── Closing CTA ──────────────────────────────── */
function CtaClose() {
  return (
    <Reveal>
      <section className="relative overflow-hidden border-t border-border/60">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute left-1/2 top-1/2 h-[30rem] w-[30rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/[0.08] blur-[110px]" />
        </div>
        <div className="mx-auto max-w-3xl px-5 py-28 text-center">
          <h2 className="font-[var(--font-display)] text-4xl font-semibold tracking-tight sm:text-5xl">
            Catch the next one early.
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-lg text-muted-foreground">
            Point the radar at your niche and your competitors. The first breakout you act on pays
            for the year.
          </p>
          <Link
            href="/dashboard"
            className="mt-9 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3.5 text-sm font-semibold text-primary-foreground transition-transform active:translate-y-px"
          >
            Start watching
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </Reveal>
  );
}

function SignalFooter() {
  return (
    <footer className="border-t border-border/60">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-5 py-10 sm:flex-row">
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded bg-primary text-primary-foreground">
            <Radar className="h-3.5 w-3.5" />
          </span>
          <span className="font-[var(--font-display)] text-sm font-semibold">ViewMagnet</span>
        </div>
        <p className="text-xs text-muted-foreground">Real-time YouTube breakout intelligence.</p>
        <Link href="/" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
          View the v1 site
        </Link>
      </div>
    </footer>
  );
}

/* ───────────────────────── Scroll reveal wrapper ────────────────────── */
function Reveal({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.7, ease }}
    >
      {children}
    </motion.div>
  );
}

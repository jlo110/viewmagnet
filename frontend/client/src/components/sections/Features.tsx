/*
 * Design: Signal Flow — Kinetic Minimalism
 * Features: Staggered grid with glass cards, cyan/amber accents
 */
import SectionReveal from "@/components/SectionReveal";
import {
  Activity,
  BarChart3,
  Bell,
  FileText,
  FlaskConical,
  Image,
  KeyRound,
  Pen,
  Scissors,
  ScrollText,
  Sparkles,
  Sword,
  TrendingUp,
  Trophy,
} from "lucide-react";

const AI_TOOLS_IMG = "https://private-us-east-1.manuscdn.com/sessionFile/pj36B0BzIZ7Osio6X1a34c/sandbox/CwHSCmBUP1IcP4HpneKu4a-img-3_1770792162000_na1fn_YWktdG9vbHMtdmlzdWFs.png?x-oss-process=image/resize,w_1920,h_1920/format,webp/quality,q_80&Expires=1798761600&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvcGozNkIwQnpJWjdPc2lvNlgxYTM0Yy9zYW5kYm94L0N3SFNDbUJVUDFJY1A0SHBuZUt1NGEtaW1nLTNfMTc3MDc5MjE2MjAwMF9uYTFmbl9ZV2t0ZEc5dmJITXRkbWx6ZFdGcy5wbmc~eC1vc3MtcHJvY2Vzcz1pbWFnZS9yZXNpemUsd18xOTIwLGhfMTkyMC9mb3JtYXQsd2VicC9xdWFsaXR5LHFfODAiLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTg3NjE2MDB9fX1dfQ__&Key-Pair-Id=K2HSFNDJXOU9YS&Signature=i-AYUM-wuZ01jISuE~XeqGGyAXqjJYXIGmGO1160VXAZMmg~Ud2I4oKsS30s2fPAtl5LPvM8fOHqjZ889r9rgll70kcNOe4x60A3v5Qp7C~LSJ~4Xf~xErt6GlnUXGrmxpg-wKA1zMuZ7bs2~N1vOrwxQceJWAY1l-iDKKFdq1gA0Vwy1bPN3WfQmE0wCx444c0R~G6Zv-Euf0QU-B44KZDEch3aqwrPpKlOU3uIpEidrRZObNNFCLZSbWV6rZNTZdU3ys-8e~ShXgQR13nGXg6lhLR5E8IRNDCZzl18e0VZ6iYopAaGW6EY-XNSqqonzV5QpETFyxVmG~wNwISgqg__";

const tools = [
  {
    icon: BarChart3,
    name: "Video Analyzer",
    desc: "Magnet Score with SHAP explanations. Know your content potential before upload.",
    accent: "cyan",
  },
  {
    icon: Activity,
    name: "Velocity Tracker",
    desc: "90-94% accuracy. Track channels, predict views at 3d, 7d, 14d, 30d milestones.",
    accent: "amber",
  },
  {
    icon: Pen,
    name: "Title Generator",
    desc: "Content-aware, niche-specific title suggestions with scoring.",
    accent: "cyan",
  },
  {
    icon: Trophy,
    name: "Winning Formula",
    desc: "Discover what makes YOUR hits vs flops — patterns, timing, length.",
    accent: "amber",
  },
  {
    icon: Sword,
    name: "Competitor Analysis",
    desc: "Head-to-head comparison. Find gaps and steal strategies.",
    accent: "cyan",
  },
  {
    icon: TrendingUp,
    name: "Trend Timing",
    desc: "Google Trends integration. Post when topics are rising.",
    accent: "amber",
  },
  {
    icon: FlaskConical,
    name: "A/B Tester",
    desc: "Compare title and thumbnail variations before publishing.",
    accent: "cyan",
  },
  {
    icon: FileText,
    name: "AI Writer",
    desc: "Descriptions, tags, and hooks powered by LLM + your niche data.",
    accent: "amber",
  },
  {
    icon: Bell,
    name: "Smart Alerts",
    desc: "Underperformance warnings, timing notifications, competitor alerts.",
    accent: "cyan",
  },
  {
    icon: Image,
    name: "Thumbnail Creator",
    desc: "AI backgrounds, 6 pro templates, face compositing with color grading.",
    accent: "amber",
  },
  {
    icon: Scissors,
    name: "Shorts Creator",
    desc: "AI highlight detection + vertical reframe + caption generation.",
    accent: "cyan",
  },
  {
    icon: KeyRound,
    name: "Keyword Research",
    desc: "Rising keywords, competitor tags, auto-tag generation.",
    accent: "amber",
  },
  {
    icon: ScrollText,
    name: "Script Writer",
    desc: "Full video scripts with Claude. 6 hook types, niche-aware prompts.",
    accent: "cyan",
  },
  {
    icon: Sparkles,
    name: "Animated Captions",
    desc: "7 styles including MrBeast & CapCut. Word-by-word animations.",
    accent: "amber",
  },
];

export default function Features() {
  return (
    <section id="features" className="relative py-24 md:py-32">
      {/* Section header */}
      <div className="container">
        <SectionReveal>
          <div className="max-w-2xl">
            <span className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-cyan-glow">
              14 AI-Powered Tools
            </span>
            <h2 className="mt-4 text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight leading-tight">
              Everything You Need to{" "}
              <span className="gradient-text">Dominate Your Niche</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground leading-relaxed">
              From pre-upload predictions to AI content creation — every tool is
              optimized for your specific niche using real data from top performers.
            </p>
          </div>
        </SectionReveal>

        {/* AI Tools Visual */}
        <SectionReveal delay={0.2}>
          <div className="mt-12 relative rounded-xl overflow-hidden border border-border/30">
            <img
              src={AI_TOOLS_IMG}
              alt="ViewMagnet AI creation tools showing thumbnail generation, script writing, animated captions, and keyword research"
              className="w-full h-auto"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-background via-background/20 to-transparent" />
          </div>
        </SectionReveal>

        {/* Tools Grid */}
        <div className="mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tools.map((tool, i) => (
            <SectionReveal key={tool.name} delay={i * 0.05}>
              <div className="glass-card rounded-xl p-5 h-full hover:border-cyan-glow/30 transition-all duration-300 group">
                <div className="flex items-start gap-4">
                  <div
                    className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
                      tool.accent === "cyan"
                        ? "bg-cyan-glow/10 group-hover:bg-cyan-glow/20"
                        : "bg-amber-glow/10 group-hover:bg-amber-glow/20"
                    } transition-colors`}
                  >
                    <tool.icon
                      className={`w-5 h-5 ${
                        tool.accent === "cyan" ? "text-cyan-glow" : "text-amber-glow"
                      }`}
                    />
                  </div>
                  <div>
                    <h3 className="font-semibold text-foreground text-sm">{tool.name}</h3>
                    <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
                      {tool.desc}
                    </p>
                  </div>
                </div>
              </div>
            </SectionReveal>
          ))}
        </div>
      </div>
    </section>
  );
}

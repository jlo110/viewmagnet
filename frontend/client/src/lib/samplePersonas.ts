/**
 * Sample personas for dashboard preview surfaces.
 *
 * Reviewer pushback: the original sample preview used a single
 * tech/coding persona ("5 Python Tips You NEED to Know", etc.). Cold
 * users from finance, fitness, gaming, etc. immediately bounce because
 * the numbers don't look like theirs.
 *
 * This module exposes a rotating catalog of personas + the same shape
 * of fixture data the Impact page already uses. Pages can:
 *
 *   1. Let the user pick a persona explicitly (e.g. dropdown).
 *   2. Auto-rotate based on user id so the same user keeps seeing the
 *      same persona across reloads (avoids flicker) but different
 *      users see different ones.
 *
 * Numbers across personas are intentionally on the same order of
 * magnitude — we're showcasing the *lift*, not the absolute audience
 * size of any niche.
 */

export type PersonaId = "tech" | "finance" | "fitness" | "gaming";

export interface PersonaCopy {
  id: PersonaId;
  label: string;
  /** One-line tagline shown under the sample-data badge. */
  tagline: string;
  /** Channel-style name to show in headers (faux). */
  channelName: string;
}

export interface PersonaMetric {
  name: string;
  before: number;
  after: number;
  change: number;
  changePercent: number;
  unit: string;
  /** Lucide icon name. Looked up by the consuming view so this module
   *  stays free of React/JSX. */
  icon:
    | "Eye"
    | "ThumbsUp"
    | "Users"
    | "Clock"
    | "MessageSquare"
    | "TrendingUp";
}

export interface PersonaVideo {
  title: string;
  usedViewMagnet: boolean;
  views: number;
  likes: number;
  comments: number;
  engagementRate: number;
  publishedAt: string;
  magnetScore?: number;
}

export interface PersonaTrendPoint {
  date: string;
  beforeAvg: number;
  afterAvg: number;
  actual: number;
}

export interface Persona {
  copy: PersonaCopy;
  metrics: PersonaMetric[];
  videos: PersonaVideo[];
  trend: PersonaTrendPoint[];
}

// ---------------------------------------------------------------------------
// Persona definitions. Numbers picked so they:
//   - sit at realistic-but-impressive scale for each niche
//   - show a clear "before/after" delta that matches the page's pitch
//   - keep the *percentage* lift comparable across personas
// ---------------------------------------------------------------------------

const TECH: Persona = {
  copy: {
    id: "tech",
    label: "Tech / Coding",
    tagline: "How a tech creator's channel grew after switching to ViewMagnet",
    channelName: "DevByteDaily",
  },
  metrics: [
    { name: "Average Views",     before: 4200, after: 12800, change: 8600, changePercent: 205, unit: "views",   icon: "Eye" },
    { name: "Engagement Rate",   before: 3.2,  after: 5.8,   change: 2.6,  changePercent: 81,  unit: "%",       icon: "ThumbsUp" },
    { name: "Subscriber Growth", before: 45,   after: 187,   change: 142,  changePercent: 316, unit: "/month",  icon: "Users" },
    { name: "Watch Time",        before: 2.4,  after: 4.1,   change: 1.7,  changePercent: 71,  unit: "min avg", icon: "Clock" },
  ],
  videos: [
    { title: "5 Python Tips You NEED to Know",     usedViewMagnet: true,  views: 18400, likes: 1240, comments: 156, engagementRate: 7.6, publishedAt: "2 weeks ago",  magnetScore: 87 },
    { title: "How I Learn Programming",            usedViewMagnet: false, views: 3200,  likes: 180,  comments: 24,  engagementRate: 6.4, publishedAt: "1 month ago" },
    { title: "Building a SaaS in 30 Days",         usedViewMagnet: true,  views: 24600, likes: 1890, comments: 234, engagementRate: 8.6, publishedAt: "3 weeks ago",  magnetScore: 92 },
    { title: "My Coding Setup Tour",               usedViewMagnet: false, views: 4800,  likes: 320,  comments: 45,  engagementRate: 7.6, publishedAt: "2 months ago" },
    { title: "React vs Vue — The REAL Difference", usedViewMagnet: true,  views: 15200, likes: 980,  comments: 189, engagementRate: 7.7, publishedAt: "1 week ago",   magnetScore: 84 },
  ],
  trend: trendCurve(4200, 8500, 18400),
};

const FINANCE: Persona = {
  copy: {
    id: "finance",
    label: "Finance / Investing",
    tagline: "How a finance creator's channel grew after switching to ViewMagnet",
    channelName: "MoneyMomentum",
  },
  metrics: [
    { name: "Average Views",     before: 5800, after: 17900, change: 12100, changePercent: 209, unit: "views",   icon: "Eye" },
    { name: "Engagement Rate",   before: 2.8,  after: 5.1,   change: 2.3,   changePercent: 82,  unit: "%",       icon: "ThumbsUp" },
    { name: "Subscriber Growth", before: 62,   after: 248,   change: 186,   changePercent: 300, unit: "/month",  icon: "Users" },
    { name: "Watch Time",        before: 3.1,  after: 5.4,   change: 2.3,   changePercent: 74,  unit: "min avg", icon: "Clock" },
  ],
  videos: [
    { title: "Why I'm Selling My Index Funds",     usedViewMagnet: true,  views: 22500, likes: 1610, comments: 312, engagementRate: 8.5, publishedAt: "1 week ago",   magnetScore: 89 },
    { title: "My Roth IRA Update",                 usedViewMagnet: false, views: 4200,  likes: 240,  comments: 38,  engagementRate: 6.6, publishedAt: "1 month ago" },
    { title: "The Truth About Dividend Investing", usedViewMagnet: true,  views: 31200, likes: 2450, comments: 410, engagementRate: 9.2, publishedAt: "2 weeks ago",  magnetScore: 94 },
    { title: "How Much I Saved This Month",        usedViewMagnet: false, views: 6100,  likes: 380,  comments: 52,  engagementRate: 7.1, publishedAt: "2 months ago" },
    { title: "5 Stocks I'm Watching for 2026",     usedViewMagnet: true,  views: 19800, likes: 1480, comments: 286, engagementRate: 8.9, publishedAt: "3 weeks ago",  magnetScore: 86 },
  ],
  trend: trendCurve(5800, 11200, 22500),
};

const FITNESS: Persona = {
  copy: {
    id: "fitness",
    label: "Fitness / Wellness",
    tagline: "How a fitness creator's channel grew after switching to ViewMagnet",
    channelName: "ReppingProgress",
  },
  metrics: [
    { name: "Average Views",     before: 3600, after: 11400, change: 7800, changePercent: 217, unit: "views",   icon: "Eye" },
    { name: "Engagement Rate",   before: 4.1,  after: 7.2,   change: 3.1,  changePercent: 76,  unit: "%",       icon: "ThumbsUp" },
    { name: "Subscriber Growth", before: 38,   after: 162,   change: 124,  changePercent: 326, unit: "/month",  icon: "Users" },
    { name: "Watch Time",        before: 1.9,  after: 3.4,   change: 1.5,  changePercent: 79,  unit: "min avg", icon: "Clock" },
  ],
  videos: [
    { title: "I Tried This Workout for 30 Days",   usedViewMagnet: true,  views: 16800, likes: 1820, comments: 234, engagementRate: 12.2, publishedAt: "2 weeks ago",  magnetScore: 88 },
    { title: "My Morning Routine",                 usedViewMagnet: false, views: 2900,  likes: 210,  comments: 28,  engagementRate: 8.2,  publishedAt: "1 month ago" },
    { title: "The Truth About Protein Powder",     usedViewMagnet: true,  views: 21400, likes: 2310, comments: 312, engagementRate: 12.3, publishedAt: "3 weeks ago",  magnetScore: 91 },
    { title: "What I Eat in a Day",                usedViewMagnet: false, views: 4100,  likes: 360,  comments: 41,  engagementRate: 9.8,  publishedAt: "2 months ago" },
    { title: "5 Stretches Everyone Should Do",     usedViewMagnet: true,  views: 13900, likes: 1480, comments: 192, engagementRate: 12.0, publishedAt: "1 week ago",   magnetScore: 83 },
  ],
  trend: trendCurve(3600, 7900, 16800),
};

const GAMING: Persona = {
  copy: {
    id: "gaming",
    label: "Gaming",
    tagline: "How a gaming creator's channel grew after switching to ViewMagnet",
    channelName: "FragLab",
  },
  metrics: [
    { name: "Average Views",     before: 7400, after: 24800, change: 17400, changePercent: 235, unit: "views",   icon: "Eye" },
    { name: "Engagement Rate",   before: 5.2,  after: 8.4,   change: 3.2,   changePercent: 62,  unit: "%",       icon: "ThumbsUp" },
    { name: "Subscriber Growth", before: 84,   after: 412,   change: 328,   changePercent: 390, unit: "/month",  icon: "Users" },
    { name: "Watch Time",        before: 4.3,  after: 7.1,   change: 2.8,   changePercent: 65,  unit: "min avg", icon: "Clock" },
  ],
  videos: [
    { title: "I Beat This Boss Without Taking Damage",     usedViewMagnet: true,  views: 38400, likes: 4120, comments: 612, engagementRate: 12.3, publishedAt: "1 week ago",   magnetScore: 91 },
    { title: "Random Gameplay #47",                        usedViewMagnet: false, views: 5800,  likes: 410,  comments: 62,  engagementRate: 8.1,  publishedAt: "1 month ago" },
    { title: "The Best Loadout No One Is Using",           usedViewMagnet: true,  views: 47200, likes: 5210, comments: 812, engagementRate: 12.8, publishedAt: "2 weeks ago",  magnetScore: 95 },
    { title: "My Gaming Setup Tour",                       usedViewMagnet: false, views: 8200,  likes: 580,  comments: 88,  engagementRate: 8.1,  publishedAt: "2 months ago" },
    { title: "Why This Patch Changed Everything",          usedViewMagnet: true,  views: 28600, likes: 3140, comments: 486, engagementRate: 12.7, publishedAt: "3 weeks ago",  magnetScore: 87 },
  ],
  trend: trendCurve(7400, 15200, 38400),
};

// 10-week before/after trend curve generated from three anchor numbers
// (pre-magnet baseline, post-magnet average, recent peak) so each
// persona's chart has consistent shape across views.
function trendCurve(beforeAvg: number, afterAvg: number, peak: number): PersonaTrendPoint[] {
  return [
    { date: "Week 1",  beforeAvg, afterAvg: 0,        actual: Math.round(beforeAvg * 0.90) },
    { date: "Week 2",  beforeAvg, afterAvg: 0,        actual: Math.round(beforeAvg * 0.98) },
    { date: "Week 3",  beforeAvg, afterAvg: 0,        actual: Math.round(beforeAvg * 0.93) },
    { date: "Week 4",  beforeAvg, afterAvg: 0,        actual: Math.round(beforeAvg * 1.07) },
    { date: "Week 5",  beforeAvg, afterAvg,           actual: Math.round(afterAvg * 0.85) },
    { date: "Week 6",  beforeAvg, afterAvg,           actual: Math.round(afterAvg * 1.15) },
    { date: "Week 7",  beforeAvg, afterAvg,           actual: Math.round(afterAvg * 1.32) },
    { date: "Week 8",  beforeAvg, afterAvg,           actual: peak },
    { date: "Week 9",  beforeAvg, afterAvg,           actual: Math.round(peak * 0.82) },
    { date: "Week 10", beforeAvg, afterAvg,           actual: Math.round(peak * 0.70) },
  ];
}

export const SAMPLE_PERSONAS: Record<PersonaId, Persona> = {
  tech: TECH,
  finance: FINANCE,
  fitness: FITNESS,
  gaming: GAMING,
};

export const PERSONA_ORDER: PersonaId[] = ["tech", "finance", "fitness", "gaming"];

/**
 * Pick a persona for the user. Stable across reloads — same ``key``
 * always returns the same persona. Use ``user.id`` (or any short stable
 * identifier) as the key so a given user keeps seeing the same demo
 * channel until they explicitly switch.
 */
export function pickPersonaFor(key: string | number | null | undefined): Persona {
  const k = String(key ?? "anon");
  let h = 0;
  for (let i = 0; i < k.length; i++) h = (h * 31 + k.charCodeAt(i)) >>> 0;
  return SAMPLE_PERSONAS[PERSONA_ORDER[h % PERSONA_ORDER.length]];
}

export function getPersona(id: PersonaId): Persona {
  return SAMPLE_PERSONAS[id];
}

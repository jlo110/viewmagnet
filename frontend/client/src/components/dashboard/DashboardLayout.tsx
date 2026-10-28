/*
 * Dashboard Layout: Signal Flow dark theme
 * Persistent sidebar with collapsible navigation
 * Uses shadcn/ui Sidebar components
 */
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Link, useLocation } from "wouter";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Bell,
  ChevronUp,
  Clapperboard,
  CloudUpload,
  FileStack,
  FileText,
  Film,
  FlaskConical,
  Image,
  KeyRound,
  Languages,
  LayoutDashboard,
  LineChart,
  LogOut,
  Mic,
  Network,
  Pen,
  Repeat,
  Scissors,
  ScrollText,
  Settings,
  ShieldAlert,
  Sparkles,
  Sword,
  TrendingUp,
  Trophy,
  Zap,
  Radar,
  Layers,
  Eye,
  Youtube,
} from "lucide-react";
import { useUpgrade } from "@/contexts/UpgradeContext";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { getDashboardStats, getYouTubeConnections, getAlertSummary } from "@/lib/api";
import { RenderNotifier } from "@/components/RenderNotifier";
import { RenderSoftcapWatcher } from "@/components/RenderSoftcapWatcher";
import { RenderSurgeWatcher } from "@/components/RenderSurgeWatcher";
import VerificationBanner from "@/components/dashboard/VerificationBanner";

const analyzeTools = [
  { title: "Breakout Radar", icon: Radar, href: "/dashboard/radar", badge: "LIVE" },
  { title: "Watchlist", icon: Eye, href: "/dashboard/watchlist", badge: "NEW" },
  { title: "Your Channel", icon: Youtube, href: "/dashboard/my-channel", badge: "NEW" },
  { title: "Format Radar", icon: Layers, href: "/dashboard/formats", badge: "NEW" },
  { title: "Video Analyzer", icon: BarChart3, href: "/dashboard/analyzer" },
  { title: "Velocity Tracker", icon: Activity, href: "/dashboard/velocity" },
  { title: "Impact", icon: LineChart, href: "/dashboard/impact" },
  { title: "Winning Formula", icon: Trophy, href: "/dashboard/formula" },
  { title: "Competitor Analysis", icon: Sword, href: "/dashboard/competitors" },
  { title: "Trend Timing", icon: TrendingUp, href: "/dashboard/trends" },
  { title: "A/B Tester", icon: FlaskConical, href: "/dashboard/ab-test" },
  { title: "Candidate Ranker", icon: Trophy, href: "/dashboard/ranker", badge: "NEW" },
  { title: "Keyword Research", icon: KeyRound, href: "/dashboard/keywords" },
];

const createTools = [
  { title: "Title Generator", icon: Pen, href: "/dashboard/titles" },
  { title: "AI Writer", icon: FileText, href: "/dashboard/writer" },
  { title: "Script Writer", icon: ScrollText, href: "/dashboard/scripts" },
  { title: "Thumbnail Creator", icon: Image, href: "/dashboard/thumbnails" },
  { title: "Shorts Creator", icon: Scissors, href: "/dashboard/shorts" },
  { title: "Studio", icon: Clapperboard, href: "/dashboard/studio", badge: "NEW" },
  { title: "Drafts", icon: FileStack, href: "/dashboard/drafts" },
  { title: "Renders", icon: CloudUpload, href: "/dashboard/renders" },
  { title: "Loop Designer", icon: Repeat, href: "/dashboard/loop-designer" },
  { title: "Distribution Hub", icon: Network, href: "/dashboard/distribution" },
  { title: "Outcomes", icon: Activity, href: "/dashboard/outcomes" },
  { title: "Animated Captions", icon: Sparkles, href: "/dashboard/captions" },
  { title: "Voice Dubbing", icon: Languages, href: "/dashboard/dubbing" },
  { title: "Voiceover", icon: Mic, href: "/dashboard/voiceover" },
  { title: "Faceless Generator", icon: Film, href: "/dashboard/faceless", badge: "NEW" },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const { user, logout, isAuthenticated } = useAuth();
  const { openUpgrade } = useUpgrade();

  // Live alert badge + quota counter. Both are best-effort: if the API call
  // fails (e.g. user has no connected channel yet), we just hide the badge
  // and fall back to the plan label rather than blocking the layout.
  const [alertCount, setAlertCount] = useState<number | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number | null } | null>(null);

  // Opt-in v2 "Signal" theme preview. Default OFF (the live dashboard stays v1);
  // toggling wraps the whole shell in `.theme-v2`, which re-points the accent to
  // signal-lime and swaps the display font across every tool page at once.
  const [themeV2, setThemeV2] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("vm_theme_v2") === "1",
  );
  const toggleThemeV2 = () =>
    setThemeV2((v) => {
      const next = !v;
      try { localStorage.setItem("vm_theme_v2", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });

  useEffect(() => {
    if (!isAuthenticated) {
      setAlertCount(null);
      setQuota(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const stats = await getDashboardStats();
        if (cancelled) return;
        setQuota({
          used: stats.analyses_this_month ?? 0,
          limit: stats.analyses_limit ?? null,
        });
      } catch {
        // Quota is non-critical; leave as null and the plan badge stays generic.
      }
      try {
        const { connections } = await getYouTubeConnections();
        const channelId = connections[0]?.channel_id;
        if (channelId) {
          const summary = await getAlertSummary(channelId);
          if (!cancelled) setAlertCount(summary?.unread ?? null);
        }
      } catch {
        // No connection or alerts endpoint failed -> hide badge.
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated]);

  const userInitials = user?.name 
    ? user.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() || 'U';

  const displayName = user?.name || user?.email?.split('@')[0] || 'User';
  const planLabel = user?.plan === 'free' ? 'Free Plan' : user?.plan === 'pro' ? 'Pro Plan' : 'Enterprise';

  // Quota → upgrade nudge state. Reviewer pushback: the passive
  // "0/10 analyses" counter was wasting prime real-estate. We now treat
  // it as a conversion surface — once usage crosses 70% the badge
  // turns amber and dangles the Pro number; at 100% it goes red and
  // becomes an explicit upgrade button.
  const usagePct =
    quota && quota.limit != null && quota.limit > 0
      ? Math.min(1, quota.used / quota.limit)
      : 0;
  const isFreePlan = (user?.plan ?? 'free') === 'free';
  const showQuotaNudge = isFreePlan && quota != null && quota.limit != null;
  const remaining = showQuotaNudge ? Math.max(0, (quota?.limit ?? 0) - (quota?.used ?? 0)) : null;
  const quotaState: 'ok' | 'low' | 'out' =
    !showQuotaNudge ? 'ok' : usagePct >= 1 ? 'out' : usagePct >= 0.7 ? 'low' : 'ok';

  return (
    <SidebarProvider className={themeV2 ? "theme-v2" : undefined}>
      <Sidebar collapsible="icon" className="border-r border-sidebar-border">
        <SidebarHeader className="p-4">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center shrink-0">
              <Zap className="w-4.5 h-4.5 text-deep-charcoal" strokeWidth={2.5} />
            </div>
            <span className="text-base font-bold font-[var(--font-display)] tracking-tight text-sidebar-foreground group-data-[collapsible=icon]:hidden">
              View<span className="text-cyan-glow">Magnet</span>
            </span>
          </Link>
        </SidebarHeader>

        <SidebarContent className="overflow-y-auto">
          {/* Overview */}
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location === "/dashboard"}
                    tooltip="Overview"
                  >
                    <Link href="/dashboard">
                      <LayoutDashboard className="w-4 h-4" />
                      <span>Overview</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    asChild
                    isActive={location === "/dashboard/alerts"}
                    tooltip="Smart Alerts"
                  >
                    <Link href="/dashboard/alerts">
                      <Bell className="w-4 h-4" aria-hidden="true" />
                      <span>Smart Alerts</span>
                      {alertCount != null && alertCount > 0 ? (
                        <Badge
                          variant="destructive"
                          className="ml-auto text-[10px] px-1.5 py-0 h-4"
                          aria-label={`${alertCount} unread alerts`}
                        >
                          {alertCount > 99 ? '99+' : alertCount}
                        </Badge>
                      ) : null}
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <Separator className="mx-3 w-auto bg-sidebar-border" />

          {/* Analyze */}
          <SidebarGroup>
            <SidebarGroupLabel className="text-[10px] font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground">
              Analyze
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {analyzeTools.map((tool) => (
                  <SidebarMenuItem key={tool.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={location === tool.href}
                      tooltip={tool.title}
                    >
                      <Link href={tool.href}>
                        <tool.icon className="w-4 h-4" />
                        <span>{tool.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <Separator className="mx-3 w-auto bg-sidebar-border" />

          {/* Create */}
          <SidebarGroup>
            <SidebarGroupLabel className="text-[10px] font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground">
              Create
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {createTools.map((tool) => (
                  <SidebarMenuItem key={tool.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={
                        location === tool.href ||
                        location.startsWith(tool.href + "/")
                      }
                      tooltip={tool.title}
                    >
                      <Link href={tool.href}>
                        <tool.icon className="w-4 h-4" />
                        <span className="flex-1">{tool.title}</span>
                        {"badge" in tool && tool.badge && (
                          <Badge
                            variant="default"
                            className="ml-auto h-4 px-1.5 text-[9px] font-bold bg-violet-500 hover:bg-violet-500 text-white group-data-[collapsible=icon]:hidden"
                          >
                            {tool.badge}
                          </Badge>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          {/* Admin — only visible to operators on ADMIN_EMAILS. The
              flag is sourced from /auth/me so we don't show a broken
              link to anyone else. */}
          {user?.is_admin ? (
            <>
              <Separator className="mx-3 w-auto bg-sidebar-border" />
              <SidebarGroup>
                <SidebarGroupLabel className="text-[10px] font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground">
                  Admin
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        asChild
                        isActive={location === "/dashboard/admin/telemetry"}
                        tooltip="Render telemetry"
                      >
                        <Link href="/dashboard/admin/telemetry">
                          <Activity className="w-4 h-4" />
                          <span>Render Telemetry</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        asChild
                        isActive={location === "/dashboard/admin/queue"}
                        tooltip="Worker DLQ"
                      >
                        <Link href="/dashboard/admin/queue">
                          <ShieldAlert className="w-4 h-4" />
                          <span>Worker DLQ</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            </>
          ) : null}
        </SidebarContent>

        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                asChild
                isActive={location === "/dashboard/settings"}
                tooltip="Settings"
              >
                <Link href="/dashboard/settings">
                  <Settings className="w-4 h-4" />
                  <span>Settings</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              {isAuthenticated ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <SidebarMenuButton className="h-10">
                      <Avatar className="w-6 h-6">
                        <AvatarFallback className="bg-cyan-glow/20 text-cyan-glow text-xs font-bold">
                          {userInitials}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex flex-col text-left leading-tight">
                        <span className="text-xs font-semibold">{displayName}</span>
                        <span className="text-[10px] text-muted-foreground">{planLabel}</span>
                      </div>
                      <ChevronUp className="ml-auto w-4 h-4 text-muted-foreground" />
                    </SidebarMenuButton>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent side="top" align="start" className="w-48">
                    <DropdownMenuItem asChild>
                      <Link href="/dashboard/settings">
                        <Settings className="w-4 h-4 mr-2" />
                        Account Settings
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
                      <LogOut className="w-4 h-4 mr-2" />
                      Log Out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <SidebarMenuButton asChild tooltip="Sign In">
                  <Link href="/login">
                    <LogOut className="w-4 h-4" />
                    <span>Sign In</span>
                  </Link>
                </SidebarMenuButton>
              )}
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset>
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex items-center gap-3 h-14 px-4 border-b border-border bg-background/80 backdrop-blur-lg">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="h-5" />
          <div className="flex-1" />
          <button
            type="button"
            onClick={toggleThemeV2}
            aria-pressed={themeV2}
            title={themeV2 ? "Switch back to the classic theme" : "Preview the v2 Signal theme"}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
              themeV2
                ? "border-cyan-glow/50 bg-cyan-glow/10 text-cyan-glow"
                : "border-border text-muted-foreground hover:text-foreground hover:border-border/80"
            }`}
          >
            <FlaskConical className="h-3.5 w-3.5" />
            {themeV2 ? "v2 Signal" : "Try v2"}
          </button>
          <div className="flex items-center gap-2">
            {isAuthenticated ? (
              showQuotaNudge ? (
                /* Conversion nudge for Free users — was a passive
                   counter, now an active CTA. Color escalates as the
                   user approaches their cap; at 100% it becomes an
                   explicit upgrade button. Reviewer feedback: this
                   real-estate was being wasted. */
                <button
                  type="button"
                  onClick={() =>
                    openUpgrade(quotaState === "out" ? "quota_out" : "quota_low")
                  }
                  aria-label={
                    quotaState === "out"
                      ? "You're out of analyses this month. Click to upgrade."
                      : `${remaining} analyses left this month. Click to upgrade for 500.`
                  }
                  className={`group inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs transition-colors hover-elevate active-elevate-2 ${
                    quotaState === "out"
                      ? "border-red-500/40 bg-red-500/10 text-red-300 hover:border-red-400/70"
                      : quotaState === "low"
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-200 hover:border-amber-400/70"
                      : "border-cyan-glow/30 bg-transparent text-muted-foreground hover:border-cyan-glow/60 hover:text-foreground"
                  }`}
                >
                  <span className="font-[var(--font-mono)] text-[10px] uppercase tracking-wider opacity-80">
                    Free
                  </span>
                  <span className="font-semibold tabular-nums">
                    {quotaState === "out"
                      ? "Out — Upgrade for 500/mo"
                      : `${remaining} left · Upgrade for 500/mo`}
                  </span>
                  <ArrowUpRight className="w-3 h-3 opacity-70 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </button>
              ) : (
                /* Paid users get the original quiet badge — they don't
                   need to be sold. */
                <>
                  <Badge variant="outline" className="text-[10px] font-[var(--font-mono)] border-cyan-glow/30 text-cyan-glow">
                    {planLabel}
                  </Badge>
                  {quota && quota.limit != null ? (
                    <span
                      className="text-xs text-muted-foreground tabular-nums"
                      aria-live="polite"
                    >
                      {quota.used} / {quota.limit} analyses
                    </span>
                  ) : null}
                </>
              )
            ) : (
              <Link href="/login" className="text-xs text-cyan-glow hover:underline">
                Sign in
              </Link>
            )}
          </div>
        </header>

        {/* Soft email-verification nudge (dismissible, full access retained). */}
        <VerificationBanner />

        {/* Page content */}
        <main className="flex-1 p-6">
          {children}
        </main>

        {/* Global cross-page render lifecycle toasts (Week 8). */}
        <RenderNotifier />
        {/* Free-plan soft-cap watcher — surfaces the upgrade modal
            when the backend signals a render exceeded a polite
            threshold (e.g. >2 min output). Render still completes. */}
        <RenderSoftcapWatcher />
        {/* P3 polish: queue surge watcher — toasts a "queue is busier
            than usual, your render will start in ~X minutes" notice
            when the backend stamps the surge header. Informational;
            the render still queues normally. */}
        <RenderSurgeWatcher />
      </SidebarInset>
    </SidebarProvider>
  );
}

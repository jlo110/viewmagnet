import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { AuthProvider } from "./contexts/AuthContext";
import { UpgradeProvider } from "./contexts/UpgradeContext";
import Home from "./pages/Home";
import HomeV2 from "./pages/HomeV2";
import HomeV3 from "./pages/HomeV3";
import HomeSignal from "./pages/HomeSignal";
import DashboardLayout from "./components/dashboard/DashboardLayout";
import { lazy as reactLazy, Suspense, useEffect, type ComponentType } from "react";
import { Loader2 } from "lucide-react";

// After a new frontend deploy, Vite emits new hashed chunk filenames. Tabs that
// were already open still reference the old hashes, so lazy-loaded routes 404
// with "Failed to fetch dynamically imported module". Wrap React.lazy so a
// failed import triggers a single full reload to pull the fresh index + chunks.
// A short sessionStorage guard prevents reload loops if the asset is truly gone.
function lazy<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
) {
  return reactLazy(async () => {
    try {
      return await factory();
    } catch (err) {
      const KEY = "vm_chunk_reloaded_at";
      const last = Number(sessionStorage.getItem(KEY) || 0);
      if (Date.now() - last > 10000) {
        sessionStorage.setItem(KEY, String(Date.now()));
        window.location.reload();
        // Never resolve so React doesn't flash the error boundary pre-reload.
        return await new Promise<{ default: T }>(() => {});
      }
      throw err;
    }
  });
}

// Capture referral code from URL on app load
function useReferralCapture() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const refCode = params.get('ref');
    if (refCode) {
      localStorage.setItem('ViewMagnet_referral_code', refCode.toUpperCase());
      // Clean URL without reload
      const url = new URL(window.location.href);
      url.searchParams.delete('ref');
      window.history.replaceState({}, '', url.toString());
    }
    
    // Signal to prerenderer that app is ready
    document.dispatchEvent(new Event('render-event'));
  }, []);
}

// Lazy load auth pages
const Login = lazy(() => import("./pages/auth/Login"));
const Signup = lazy(() => import("./pages/auth/Signup"));
const ForgotPassword = lazy(() => import("./pages/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("./pages/auth/ResetPassword"));
const VerifyEmail = lazy(() => import("./pages/auth/VerifyEmail"));

// Lazy load legal pages
const TermsOfService = lazy(() => import("./pages/legal/TermsOfService"));
const PrivacyPolicy = lazy(() => import("./pages/legal/PrivacyPolicy"));

// Lazy load static pages
const About = lazy(() => import("./pages/About"));
const Contact = lazy(() => import("./pages/Contact"));
const Blog = lazy(() => import("./pages/Blog"));
const Frameworks = lazy(() => import("./pages/Frameworks"));
const Methodology = lazy(() => import("./pages/Methodology"));
const AnalyzerGuide = lazy(() => import("./pages/AnalyzerGuide"));
const Mcp = lazy(() => import("./pages/Mcp"));
const Docs = lazy(() => import("./pages/Docs"));
const Changelog = lazy(() => import("./pages/Changelog"));
const Status = lazy(() => import("./pages/Status"));

// Lazy load blog articles
const ThumbnailPsychology2026 = lazy(() => import("./pages/blog/articles/thumbnail-psychology-2026"));
const AlgorithmChangesFebruary = lazy(() => import("./pages/blog/articles/algorithm-changes-february"));
const TitleFormulasThatWork = lazy(() => import("./pages/blog/articles/title-formulas-that-work"));
const ShortsVsLongform = lazy(() => import("./pages/blog/articles/shorts-vs-longform"));
const PostingTimeMyths = lazy(() => import("./pages/blog/articles/posting-time-myths"));
const CreatorBurnoutPrevention = lazy(() => import("./pages/blog/articles/creator-burnout-prevention"));

// Lazy load dashboard pages
const Overview = lazy(() => import("./pages/dashboard/Overview"));
const VideoAnalyzer = lazy(() => import("./pages/dashboard/VideoAnalyzer"));
const BreakoutRadar = lazy(() => import("./pages/dashboard/BreakoutRadar"));
const Watchlist = lazy(() => import("./pages/dashboard/Watchlist"));
const MyChannel = lazy(() => import("./pages/dashboard/MyChannel"));
const FormatRadar = lazy(() => import("./pages/dashboard/FormatRadar"));
const TitleGenerator = lazy(() => import("./pages/dashboard/TitleGenerator"));
const CandidateRanker = lazy(() => import("./pages/dashboard/CandidateRanker"));
const WinningFormula = lazy(() => import("./pages/dashboard/WinningFormula"));
const CompetitorAnalysis = lazy(() => import("./pages/dashboard/CompetitorAnalysis"));
const TrendTiming = lazy(() => import("./pages/dashboard/TrendTiming"));
const ABTester = lazy(() => import("./pages/dashboard/ABTester"));
const AIWriter = lazy(() => import("./pages/dashboard/AIWriter"));
const SmartAlerts = lazy(() => import("./pages/dashboard/SmartAlerts"));
const ThumbnailCreator = lazy(() => import("./pages/dashboard/ThumbnailCreator"));
const ShortsCreator = lazy(() => import("./pages/dashboard/ShortsCreator"));
const KeywordResearch = lazy(() => import("./pages/dashboard/KeywordResearch"));
const ScriptWriter = lazy(() => import("./pages/dashboard/ScriptWriter"));
const Impact = lazy(() => import("./pages/dashboard/Impact"));
const AnimatedCaptions = lazy(() => import("./pages/dashboard/AnimatedCaptions"));
const VelocityTracker = lazy(() => import("./pages/dashboard/VelocityTracker"));
const VoiceDubbing = lazy(() => import("./pages/dashboard/VoiceDubbing"));
const LoopDesigner = lazy(() => import("./pages/dashboard/LoopDesigner"));
const DistributionHub = lazy(() => import("./pages/dashboard/DistributionHub"));
const Outcomes = lazy(() => import("./pages/dashboard/Outcomes"));
const SettingsPage = lazy(() => import("./pages/dashboard/SettingsPage"));
const ApiTokens = lazy(() => import("./pages/dashboard/ApiTokens"));
const Studio = lazy(() => import("./pages/dashboard/Studio"));
const StudioProject = lazy(() => import("./pages/dashboard/StudioProject"));
const Drafts = lazy(() => import("./pages/dashboard/Drafts"));
const Renders = lazy(() => import("./pages/dashboard/Renders"));
const AdminQueue = lazy(() => import("./pages/dashboard/AdminQueue"));
const AdminTelemetry = lazy(() => import("./pages/dashboard/AdminTelemetry"));
const AdminDashboard = lazy(() => import("./pages/dashboard/AdminDashboard"));
const AdminLogin = lazy(() => import("./pages/auth/AdminLogin"));
const Voiceover = lazy(() => import("./pages/dashboard/Voiceover"));
const FacelessGenerator = lazy(() => import("./pages/dashboard/FacelessGenerator"));

function DashboardFallback() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
    </div>
  );
}

function DashboardRouter() {
  return (
    <DashboardLayout>
      <Suspense fallback={<DashboardFallback />}>
        <Switch>
          <Route path="/dashboard" component={Overview} />
          <Route path="/dashboard/analyzer" component={VideoAnalyzer} />
          <Route path="/dashboard/radar" component={BreakoutRadar} />
          <Route path="/dashboard/watchlist" component={Watchlist} />
          <Route path="/dashboard/my-channel" component={MyChannel} />
          <Route path="/dashboard/formats" component={FormatRadar} />
          <Route path="/dashboard/titles" component={TitleGenerator} />
          <Route path="/dashboard/ranker" component={CandidateRanker} />
          <Route path="/dashboard/formula" component={WinningFormula} />
          <Route path="/dashboard/competitors" component={CompetitorAnalysis} />
          <Route path="/dashboard/trends" component={TrendTiming} />
          <Route path="/dashboard/ab-test" component={ABTester} />
          <Route path="/dashboard/writer" component={AIWriter} />
          <Route path="/dashboard/alerts" component={SmartAlerts} />
          <Route path="/dashboard/thumbnails" component={ThumbnailCreator} />
          <Route path="/dashboard/shorts" component={ShortsCreator} />
          <Route path="/dashboard/keywords" component={KeywordResearch} />
          <Route path="/dashboard/scripts" component={ScriptWriter} />
          <Route path="/dashboard/captions" component={AnimatedCaptions} />
          <Route path="/dashboard/velocity" component={VelocityTracker} />
          <Route path="/dashboard/dubbing" component={VoiceDubbing} />
          <Route path="/dashboard/loop-designer" component={LoopDesigner} />
          <Route path="/dashboard/distribution" component={DistributionHub} />
          <Route path="/dashboard/outcomes" component={Outcomes} />
          <Route path="/dashboard/impact" component={Impact} />
          <Route path="/dashboard/settings" component={SettingsPage} />
          <Route path="/dashboard/api-tokens" component={ApiTokens} />
          <Route path="/dashboard/studio" component={Studio} />
          <Route path="/dashboard/studio/project/:projectId" component={StudioProject} />
          <Route path="/dashboard/studio/:clipKey" component={Studio} />
          <Route path="/dashboard/drafts" component={Drafts} />
          <Route path="/dashboard/renders" component={Renders} />
          <Route path="/dashboard/voiceover" component={Voiceover} />
          <Route path="/dashboard/faceless" component={FacelessGenerator} />
          <Route path="/dashboard/admin" component={AdminDashboard} />
          <Route path="/dashboard/admin/queue" component={AdminQueue} />
          <Route path="/dashboard/admin/telemetry" component={AdminTelemetry} />
          {/* Unknown dashboard path -> NotFound rather than silently rendering Overview */}
          <Route component={NotFound} />
        </Switch>
      </Suspense>
    </DashboardLayout>
  );
}

function AuthFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-deep-charcoal">
      <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
    </div>
  );
}

function Router() {
  return (
    <Switch>
      <Route path={"/"} component={Home} />
      <Route path="/v2" component={HomeV2} />
      <Route path="/v3" component={HomeV3} />
      <Route path="/signal" component={HomeSignal} />
      <Route path="/login">
        <Suspense fallback={<AuthFallback />}>
          <Login />
        </Suspense>
      </Route>
      <Route path="/admin/login">
        <Suspense fallback={<AuthFallback />}>
          <AdminLogin />
        </Suspense>
      </Route>
      <Route path="/signup">
        <Suspense fallback={<AuthFallback />}>
          <Signup />
        </Suspense>
      </Route>
      <Route path="/forgot-password">
        <Suspense fallback={<AuthFallback />}>
          <ForgotPassword />
        </Suspense>
      </Route>
      <Route path="/reset-password">
        <Suspense fallback={<AuthFallback />}>
          <ResetPassword />
        </Suspense>
      </Route>
      <Route path="/verify-email">
        <Suspense fallback={<AuthFallback />}>
          <VerifyEmail />
        </Suspense>
      </Route>
      <Route path="/terms">
        <Suspense fallback={<AuthFallback />}>
          <TermsOfService />
        </Suspense>
      </Route>
      <Route path="/privacy">
        <Suspense fallback={<AuthFallback />}>
          <PrivacyPolicy />
        </Suspense>
      </Route>
      <Route path="/about">
        <Suspense fallback={<AuthFallback />}>
          <About />
        </Suspense>
      </Route>
      <Route path="/frameworks">
        <Suspense fallback={<AuthFallback />}>
          <Frameworks />
        </Suspense>
      </Route>
      <Route path="/methodology">
        <Suspense fallback={<AuthFallback />}>
          <Methodology />
        </Suspense>
      </Route>
      <Route path="/analyzer-guide">
        <Suspense fallback={<AuthFallback />}>
          <AnalyzerGuide />
        </Suspense>
      </Route>
      <Route path="/mcp">
        <Suspense fallback={<AuthFallback />}>
          <Mcp />
        </Suspense>
      </Route>
      <Route path="/contact">
        <Suspense fallback={<AuthFallback />}>
          <Contact />
        </Suspense>
      </Route>
      <Route path="/blog">
        <Suspense fallback={<AuthFallback />}>
          <Blog />
        </Suspense>
      </Route>
      <Route path="/blog/thumbnail-psychology-2026">
        <Suspense fallback={<AuthFallback />}>
          <ThumbnailPsychology2026 />
        </Suspense>
      </Route>
      <Route path="/blog/algorithm-changes-february">
        <Suspense fallback={<AuthFallback />}>
          <AlgorithmChangesFebruary />
        </Suspense>
      </Route>
      <Route path="/blog/title-formulas-that-work">
        <Suspense fallback={<AuthFallback />}>
          <TitleFormulasThatWork />
        </Suspense>
      </Route>
      <Route path="/blog/shorts-vs-longform">
        <Suspense fallback={<AuthFallback />}>
          <ShortsVsLongform />
        </Suspense>
      </Route>
      <Route path="/blog/posting-time-myths">
        <Suspense fallback={<AuthFallback />}>
          <PostingTimeMyths />
        </Suspense>
      </Route>
      <Route path="/blog/creator-burnout-prevention">
        <Suspense fallback={<AuthFallback />}>
          <CreatorBurnoutPrevention />
        </Suspense>
      </Route>
      <Route path="/docs">
        <Suspense fallback={<AuthFallback />}>
          <Docs />
        </Suspense>
      </Route>
      <Route path="/changelog">
        <Suspense fallback={<AuthFallback />}>
          <Changelog />
        </Suspense>
      </Route>
      <Route path="/status">
        <Suspense fallback={<AuthFallback />}>
          <Status />
        </Suspense>
      </Route>
      {/* wouter v3 wildcard syntax: `*` matches any sub-path. Note: `:rest*` in
          regexparam@3 is parsed as a single-segment param literally named "rest*",
          so it would NOT match /dashboard/studio/<key> and fall through to 404. */}
      <Route path="/dashboard" component={DashboardRouter} />
      <Route path="/dashboard/*" component={DashboardRouter} />
      <Route path={"/404"} component={NotFound} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  // Capture referral code from URL (?ref=CODE)
  useReferralCapture();
  
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="dark">
        <AuthProvider>
          <UpgradeProvider>
            <TooltipProvider>
              <Toaster />
              <Router />
            </TooltipProvider>
          </UpgradeProvider>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;

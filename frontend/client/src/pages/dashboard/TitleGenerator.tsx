/*
 * Title Generator + Hook Lab: Generate niche-optimized titles AND
 * engineer competence-gap hooks (Chris Girbu virality framework).
 * Design: Signal Flow dark theme
 */
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sparkles,
  Copy,
  Check,
  RefreshCw,
  Loader2,
  AlertCircle,
  Target,
  Zap,
  AlertTriangle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  generateTitles,
  scoreHook,
  rewriteHook,
  type TitleSuggestion,
  type HookScoreResponse,
  type HookType,
} from "@/lib/api";

interface GeneratedTitle {
  title: string;
  score: number;
  reason: string;
  tags: string[];
}

const HOOK_TYPE_OPTIONS: { value: HookType | "auto"; label: string; goal: string }[] = [
  { value: "auto", label: "Auto (mix of strong types)", goal: "Best variety" },
  { value: "mistake_callout", label: "Mistake Callout", goal: "Calls out viewer error" },
  { value: "belief_destruction", label: "Belief Destruction", goal: "Challenges assumption" },
  { value: "authority_anchor", label: "Authority Anchor", goal: "Credentials + contrarian" },
  { value: "stake_reversal", label: "Stake Reversal", goal: "Inverts expectation" },
  { value: "specificity", label: "Specificity Hook", goal: "Named system / asset" },
];

function ScoreBar({ label, value }: { label: string; value: number }) {
  const colorClass =
    value >= 70
      ? "bg-emerald-400"
      : value >= 40
      ? "bg-cyan-glow"
      : "bg-amber-glow";
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono text-foreground">{Math.round(value)}</span>
      </div>
      <div className="h-2 rounded-full bg-secondary/40 overflow-hidden">
        <div
          className={`h-full ${colorClass} transition-all`}
          style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  );
}

export default function TitleGenerator() {
  // Tab state — URL-controlled so deep links like
  // ``/dashboard/titles?tab=hooks`` (used by Algorithm Signals CTAs
  // from the Analyzer) land directly on Hook Lab instead of the
  // default Titles tab. Falls back to "titles" if the param is
  // missing or unknown.
  const [activeTab, setActiveTab] = useState<"titles" | "hooks">(() => {
    if (typeof window === "undefined") return "titles";
    const param = new URLSearchParams(window.location.search).get("tab");
    return param === "hooks" ? "hooks" : "titles";
  });

  useEffect(() => {
    // Listen for in-app navigation that changes the query (wouter
    // doesn't unmount the page on same-route navigation, so we have
    // to react to the URL ourselves). Cheap — we only run on
    // ``popstate`` and on mount.
    const sync = () => {
      const param = new URLSearchParams(window.location.search).get("tab");
      setActiveTab(param === "hooks" ? "hooks" : "titles");
    };
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  // Title generator state
  const [topic, setTopic] = useState("");
  const [niche, setNiche] = useState("tech_reviews");
  const [loading, setLoading] = useState(false);
  const [error] = useState<string | null>(null);
  const [generatedTitles, setGeneratedTitles] = useState<GeneratedTitle[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  // Hook lab state
  const [hookInput, setHookInput] = useState("");
  const [hookTopic, setHookTopic] = useState("");
  const [hookScoring, setHookScoring] = useState(false);
  const [hookAnalysis, setHookAnalysis] = useState<HookScoreResponse | null>(null);
  const [rewriteType, setRewriteType] = useState<HookType | "auto">("auto");
  const [rewriting, setRewriting] = useState(false);
  const [rewrites, setRewrites] = useState<string[]>([]);
  const [copiedRewrite, setCopiedRewrite] = useState<number | null>(null);

  const handleGenerate = async () => {
    if (!topic.trim()) {
      toast.error("Please enter a topic");
      return;
    }
    setLoading(true);
    try {
      const suggestions = await generateTitles(topic, niche);
      setGeneratedTitles(
        suggestions.map((s: TitleSuggestion) => ({
          title: s.title,
          score: Math.round(s.score),
          reason: s.reason,
          tags: extractTags(s.title),
        })),
      );
    } catch {
      setGeneratedTitles([
        {
          title: `I Built a ${topic} — Here's What Happened`,
          score: 85,
          reason: "Personal story format performs well",
          tags: ["Personal", "Story"],
        },
        {
          title: `The Truth About ${topic} Nobody Tells You`,
          score: 82,
          reason: "Curiosity gap + contrarian angle",
          tags: ["Curiosity", "Contrarian"],
        },
        {
          title: `${topic}: Complete Guide (2026)`,
          score: 78,
          reason: "Evergreen format with year tag",
          tags: ["Guide", "Evergreen"],
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  function extractTags(title: string): string[] {
    const tags: string[] = [];
    if (/\d/.test(title)) tags.push("Number");
    if (/\?/.test(title)) tags.push("Question");
    if (/!/.test(title)) tags.push("Emotional");
    if (/how|why|what/i.test(title)) tags.push("Educational");
    if (/I\s/i.test(title)) tags.push("Personal");
    if (/secret|truth|nobody/i.test(title)) tags.push("Curiosity");
    return tags.slice(0, 3);
  }

  const handleCopy = (title: string, idx: number) => {
    navigator.clipboard.writeText(title);
    setCopiedIdx(idx);
    toast.success("Title copied to clipboard");
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const handleScoreHook = async () => {
    if (!hookInput.trim()) {
      toast.error("Please enter a hook to score");
      return;
    }
    setHookScoring(true);
    setRewrites([]);
    try {
      const analysis = await scoreHook(hookInput);
      setHookAnalysis(analysis);
    } catch (err) {
      toast.error("Failed to score hook");
      setHookAnalysis(null);
    } finally {
      setHookScoring(false);
    }
  };

  const handleRewrite = async () => {
    if (!hookInput.trim()) {
      toast.error("Please enter a hook to rewrite");
      return;
    }
    if (!hookTopic.trim()) {
      toast.error("Please enter a video topic for context");
      return;
    }
    setRewriting(true);
    try {
      const target = rewriteType === "auto" ? undefined : rewriteType;
      const result = await rewriteHook(hookInput, hookTopic, target, 5);
      setRewrites(result);
    } catch (err) {
      toast.error("Failed to generate rewrites");
    } finally {
      setRewriting(false);
    }
  };

  const handleCopyRewrite = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedRewrite(idx);
    toast.success("Hook copied to clipboard");
    setTimeout(() => setCopiedRewrite(null), 2000);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Title Generator
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Generate niche-optimized titles, or engineer competence-gap hooks.
        </p>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const next = value === "hooks" ? "hooks" : "titles";
          setActiveTab(next);
          // Keep the URL in sync so a refresh / shared link stays on
          // the same tab. ``replaceState`` so we don't pollute the
          // history stack with every tab click.
          if (typeof window !== "undefined") {
            const url = new URL(window.location.href);
            if (next === "titles") {
              url.searchParams.delete("tab");
            } else {
              url.searchParams.set("tab", next);
            }
            window.history.replaceState({}, "", url.toString());
          }
        }}
        className="space-y-6"
      >
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="titles" className="gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            Titles
          </TabsTrigger>
          <TabsTrigger value="hooks" className="gap-1.5">
            <Target className="w-3.5 h-3.5" />
            Hook Lab
          </TabsTrigger>
        </TabsList>

        {/* TITLES TAB */}
        <TabsContent value="titles" className="space-y-6">
          {/* Input */}
          <Card className="bg-card border-border/50">
            <CardContent className="p-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Video Topic or Description
                </label>
                <Textarea
                  placeholder="Describe what your video is about..."
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  className="bg-secondary/50 border-border/50 min-h-[80px] resize-none"
                />
              </div>
              <div className="flex gap-3 items-end">
                <div className="flex-1">
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Niche
                  </label>
                  <Select value={niche} onValueChange={setNiche}>
                    <SelectTrigger className="bg-secondary/50 border-border/50">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="tech_reviews">Technology</SelectItem>
                      <SelectItem value="gaming">Gaming</SelectItem>
                      <SelectItem value="sports">Sports</SelectItem>
                      <SelectItem value="education_howto">Education</SelectItem>
                      <SelectItem value="entertainment_vlogs">Entertainment</SelectItem>
                      <SelectItem value="lifestyle">Lifestyle</SelectItem>
                      <SelectItem value="music_creative">Music & Creative</SelectItem>
                      <SelectItem value="news_politics">News & Politics</SelectItem>
                      <SelectItem value="commentary_essay">Commentary</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  onClick={handleGenerate}
                  disabled={loading}
                  className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-10 px-6"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Sparkles className="w-4 h-4 mr-2" />
                  )}
                  Generate Titles
                </Button>
              </div>
            </CardContent>
          </Card>

          {error && (
            <Card className="bg-destructive/10 border-destructive/30">
              <CardContent className="p-5 flex items-center gap-3">
                <AlertCircle className="w-5 h-5 text-destructive" />
                <p className="text-sm text-destructive">{error}</p>
              </CardContent>
            </Card>
          )}

          {generatedTitles.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-foreground">Generated Titles</h2>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs text-muted-foreground"
                  onClick={handleGenerate}
                >
                  <RefreshCw className="w-3 h-3 mr-1" />
                  Regenerate
                </Button>
              </div>
              {generatedTitles.map((item, i) => (
                <Card
                  key={i}
                  className="bg-card border-border/50 hover:border-cyan-glow/20 transition-colors"
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-4">
                      <div
                        className={`w-12 h-12 rounded-lg flex items-center justify-center shrink-0 font-bold font-[var(--font-display)] text-sm ${
                          item.score >= 85
                            ? "bg-emerald-400/10 text-emerald-400"
                            : item.score >= 75
                            ? "bg-cyan-glow/10 text-cyan-glow"
                            : "bg-amber-glow/10 text-amber-glow"
                        }`}
                      >
                        {item.score}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground leading-relaxed">
                          {item.title}
                        </p>
                        <div className="flex items-center gap-2 mt-2 flex-wrap">
                          <span className="text-[10px] font-[var(--font-mono)] text-muted-foreground">
                            {item.reason}
                          </span>
                          {item.tags.map((tag) => (
                            <Badge
                              key={tag}
                              variant="outline"
                              className="text-[10px] border-border/50 text-muted-foreground"
                            >
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="shrink-0 h-8 w-8"
                        onClick={() => handleCopy(item.title, i)}
                      >
                        {copiedIdx === i ? (
                          <Check className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <Copy className="w-4 h-4 text-muted-foreground" />
                        )}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {!loading && generatedTitles.length === 0 && (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-8 text-center">
                <Sparkles className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Enter a topic and click "Generate Titles" to get started
                </p>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* HOOK LAB TAB */}
        <TabsContent value="hooks" className="space-y-6">
          {/* Hook input */}
          <Card className="bg-gradient-to-br from-cyan-glow/5 to-purple-500/5 border-cyan-glow/20">
            <CardContent className="p-5 space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Target className="w-4 h-4 text-cyan-glow" />
                  <h3 className="text-sm font-semibold text-foreground">
                    Engineer the Competence Gap
                  </h3>
                  <a
                    href="/frameworks#hooks"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-auto text-[10px] text-cyan-glow hover:underline inline-flex items-center gap-1"
                  >
                    What are these hook types?
                  </a>
                </div>
                <p className="text-xs text-muted-foreground mb-3">
                  Strong hooks open a psychological gap. Weak hooks summarize. Score yours
                  and rewrite into mistake callouts, belief destruction, or stake reversals.
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Your Hook
                </label>
                <Textarea
                  placeholder='e.g. "Here are 3 tips to grow your Instagram"'
                  value={hookInput}
                  onChange={(e) => setHookInput(e.target.value)}
                  className="bg-secondary/50 border-border/50 min-h-[60px] resize-none"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Video Topic (for rewrite context)
                </label>
                <Input
                  placeholder="e.g. Instagram growth, content strategy"
                  value={hookTopic}
                  onChange={(e) => setHookTopic(e.target.value)}
                  className="bg-secondary/50 border-border/50"
                />
              </div>

              <div className="flex gap-3">
                <Button
                  onClick={handleScoreHook}
                  disabled={hookScoring}
                  variant="outline"
                  className="flex-1 border-border/50"
                >
                  {hookScoring ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Target className="w-4 h-4 mr-2" />
                  )}
                  Score Gap
                </Button>
                <Button
                  onClick={handleRewrite}
                  disabled={rewriting}
                  className="flex-1 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                >
                  {rewriting ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Zap className="w-4 h-4 mr-2" />
                  )}
                  Rewrite
                </Button>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Rewrite as
                </label>
                <Select
                  value={rewriteType}
                  onValueChange={(v) => setRewriteType(v as HookType | "auto")}
                >
                  <SelectTrigger className="bg-secondary/50 border-border/50">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HOOK_TYPE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          {/* Score results */}
          {hookAnalysis && (
            <Card className="bg-card border-border/50">
              <CardContent className="p-5 space-y-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Overall Gap Score</p>
                    <div className="flex items-baseline gap-2">
                      <span
                        className={`text-4xl font-bold font-[var(--font-display)] ${
                          hookAnalysis.overall_score >= 70
                            ? "text-emerald-400"
                            : hookAnalysis.overall_score >= 40
                            ? "text-cyan-glow"
                            : "text-amber-glow"
                        }`}
                      >
                        {hookAnalysis.overall_score}
                      </span>
                      <span className="text-xs text-muted-foreground">/ 100</span>
                    </div>
                  </div>
                  <Badge
                    className={`${
                      hookAnalysis.is_summary_pattern
                        ? "bg-amber-glow/10 text-amber-glow border-amber-glow/30"
                        : "bg-cyan-glow/10 text-cyan-glow border-cyan-glow/30"
                    }`}
                  >
                    {hookAnalysis.detected_type.replace(/_/g, " ")}
                  </Badge>
                </div>

                {hookAnalysis.is_summary_pattern && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-glow/10 border border-amber-glow/20">
                    <AlertTriangle className="w-4 h-4 text-amber-glow shrink-0 mt-0.5" />
                    <p className="text-xs text-amber-glow">
                      Summary pattern detected. Rewrite to open a gap instead of describing what's coming.
                    </p>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <ScoreBar label="Belief Challenge" value={hookAnalysis.belief_challenge} />
                  <ScoreBar label="Mistake Callout" value={hookAnalysis.mistake_callout} />
                  <ScoreBar label="Urgency" value={hookAnalysis.urgency} />
                  <ScoreBar label="Specificity" value={hookAnalysis.specificity} />
                </div>

                <div className="text-xs text-muted-foreground border-t border-border/30 pt-3">
                  <span className="font-semibold text-foreground">Why: </span>
                  {hookAnalysis.rationale}
                </div>

                <div className="flex gap-2 text-[10px]">
                  <Badge variant="outline" className="border-border/50">
                    Weakest: {hookAnalysis.weakest_dimension.replace(/_/g, " ")}
                  </Badge>
                  <Badge variant="outline" className="border-border/50">
                    Strongest: {hookAnalysis.strongest_dimension.replace(/_/g, " ")}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Rewrites */}
          {rewrites.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-foreground">Gap-Engineered Rewrites</h2>
              {rewrites.map((text, i) => (
                <Card
                  key={i}
                  className="bg-card border-border/50 hover:border-cyan-glow/20 transition-colors"
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-4">
                      <div className="w-8 h-8 rounded-lg bg-cyan-glow/10 text-cyan-glow flex items-center justify-center shrink-0 font-bold text-xs">
                        {i + 1}
                      </div>
                      <p className="flex-1 text-sm font-medium text-foreground leading-relaxed">
                        {text}
                      </p>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="shrink-0 h-8 w-8"
                        onClick={() => handleCopyRewrite(text, i)}
                      >
                        {copiedRewrite === i ? (
                          <Check className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <Copy className="w-4 h-4 text-muted-foreground" />
                        )}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {!hookAnalysis && rewrites.length === 0 && !hookScoring && !rewriting && (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-8 text-center">
                <Target className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Paste a hook above to score its competence gap or generate rewrites.
                </p>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

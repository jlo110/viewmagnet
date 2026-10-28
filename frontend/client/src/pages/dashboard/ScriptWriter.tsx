/*
 * Script Writer: Standard scripts + 4 viral frameworks (Chris Girbu)
 * Design: Signal Flow dark theme
 */
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
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
  Clock,
  RefreshCw,
  Download,
  ChevronDown,
  ChevronRight,
  Loader2,
  Zap,
  Shield,
  TrendingUp,
  Layers,
  Magnet,
  ExternalLink,
} from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { useLocation } from "wouter";
import { toast } from "sonner";
import { readScriptWriterDeepLink } from "@/lib/deepLinks";
import {
  generateScript,
  listFrameworks,
  generateFrameworkScript,
  scriptToProject,
  type ScriptSection as APIScriptSection,
  type ScriptToProjectSection,
  type FrameworkInfo,
  type FrameworkScriptResponse,
  type ScriptFrameworkId,
} from "@/lib/api";

// ====== Standard script defaults ======
const defaultScriptSections = [
  {
    section: "Hook (0:00 - 0:30)",
    content: `[FACE TO CAMERA — excited energy]

"What if I told you that you could build a SaaS product making $10,000 a month — in just 30 days? Sounds impossible, right? Well, 30 days ago, that's exactly what I set out to do. And today, I'm going to show you the exact blueprint I used."`,
    duration: "~30 seconds",
    expanded: true,
  },
  {
    section: "Problem Setup (0:30 - 2:00)",
    content: `[B-ROLL: Frustrated developer montage]\n\n"Here's the thing most people get wrong about building a SaaS..."`,
    duration: "~1.5 minutes",
    expanded: false,
  },
];

// ====== Framework metadata for icons + colors ======
/**
 * Built-in framework metadata used when the ``/scripts/frameworks``
 * API call hasn't returned yet (or has failed). Kept in sync with
 * ``src/features/script_writer.py::FRAMEWORK_TEMPLATES`` —
 * structurally identical to what the backend returns so the rest of
 * the Viral Frameworks tab code doesn't need a branch for fallback
 * vs. fetched data.
 *
 * Section ``duration`` values mirror the backend templates so the
 * "Structure" preview shows realistic timings before the API
 * resolves. ``primary_goal`` matches the backend enum string so
 * downstream filtering by goal works against either source.
 */
const FRAMEWORKS_FALLBACK: FrameworkInfo[] = [
  {
    id: "authority_myth_buster",
    name: "Authority Myth-Buster",
    primary_goal: "trust",
    goal_description: "Build trust fast with new audiences",
    sections: [
      { key: "contrarian_hook", label: "Contrarian Hook", duration: 8 },
      { key: "authority_anchor", label: "Authority Anchor", duration: 10 },
      { key: "solution_part_1", label: "Solution Part 1", duration: 30 },
      { key: "solution_part_2", label: "Solution Part 2", duration: 30 },
      { key: "solution_part_3", label: "Solution Part 3", duration: 30 },
      { key: "ideological_cta", label: "Ideological CTA", duration: 15 },
    ],
  },
  {
    id: "delta_shift",
    name: "Delta Shift",
    primary_goal: "saves",
    goal_description:
      "Drive saves and shares (highest save rate format)",
    sections: [
      { key: "baseline", label: "Baseline", duration: 15 },
      { key: "delta", label: "Delta (The Top 1% Move)", duration: 25 },
      { key: "single_takeaway", label: "Single Takeaway", duration: 15 },
      { key: "save_cta", label: "Save CTA", duration: 5 },
    ],
  },
  {
    id: "progressive_debunking",
    name: "Progressive Debunking (Iceberg)",
    primary_goal: "retention",
    goal_description:
      "Maximize watch time - the viewer keeps expecting the next revelation",
    sections: [
      { key: "polarizing_topic", label: "Polarizing Topic", duration: 10 },
      { key: "dismiss_surface", label: "Dismiss the Surface", duration: 25 },
      { key: "reveal_layer_1", label: "Reveal Layer 1", duration: 25 },
      { key: "reveal_layer_2", label: "Reveal Layer 2", duration: 25 },
      { key: "final_revelation", label: "Final Revelation", duration: 25 },
      { key: "loop_back", label: "Loop Back", duration: 5 },
    ],
  },
  {
    id: "hype_heit",
    name: "Lead Magnet Framework",
    primary_goal: "leads",
    goal_description:
      "Lead generation - fills auto-DM funnels with keyword CTAs",
    sections: [
      { key: "named_system_promise", label: "Named System Promise", duration: 8 },
      { key: "blurred_asset_tease", label: "Blurred Asset Tease", duration: 10 },
      { key: "rapid_breakdown_1", label: "Rapid Breakdown 1", duration: 15 },
      { key: "rapid_breakdown_2", label: "Rapid Breakdown 2", duration: 15 },
      { key: "rapid_breakdown_3", label: "Rapid Breakdown 3", duration: 15 },
      { key: "keyword_cta", label: "Keyword CTA", duration: 7 },
    ],
  },
];

const FRAMEWORK_VISUALS: Record<
  ScriptFrameworkId,
  { icon: typeof Shield; gradient: string; tagline: string }
> = {
  authority_myth_buster: {
    icon: Shield,
    gradient: "from-blue-500/20 to-cyan-glow/20",
    tagline: "Best for: Building trust fast",
  },
  delta_shift: {
    icon: TrendingUp,
    gradient: "from-emerald-400/20 to-cyan-glow/20",
    tagline: "Best for: Saves and shares",
  },
  progressive_debunking: {
    icon: Layers,
    gradient: "from-purple-500/20 to-amber-glow/20",
    tagline: "Best for: Maximum watch time",
  },
  hype_heit: {
    icon: Magnet,
    gradient: "from-amber-glow/20 to-pink-500/20",
    tagline: "Best for: Lead generation",
  },
};

export default function ScriptWriter() {
  // Standard script state
  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set([0]));
  const [copiedSection, setCopiedSection] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [title, setTitle] = useState("I Built a $10K/mo SaaS in 30 Days");
  const [targetLength, setTargetLength] = useState("15");
  const [style, setStyle] = useState("storytelling");
  const [keyPoints, setKeyPoints] = useState(
    "Idea validation, tech stack choice, MVP build, launch strategy, revenue results",
  );
  const [scriptSections, setScriptSections] = useState(defaultScriptSections);
  const [hasGenerated, setHasGenerated] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);

  const [, navigate] = useLocation();

  // Framework state.
  //
  // We seed ``frameworks`` with a hardcoded fallback list (mirror of
  // ``src/features/script_writer.py::FRAMEWORK_TEMPLATES``) so the
  // Viral Frameworks tab is NEVER blank even if the API call fails,
  // is slow, or the user is offline. The API call still runs to pick
  // up any backend-added frameworks; on success it overwrites the
  // fallback. On failure the user keeps a working UI with the four
  // built-in frameworks instead of staring at an empty tab.
  const [frameworks, setFrameworks] = useState<FrameworkInfo[]>(
    FRAMEWORKS_FALLBACK,
  );
  const [frameworksLoadError, setFrameworksLoadError] = useState<string | null>(
    null,
  );
  const [selectedFramework, setSelectedFramework] = useState<ScriptFrameworkId | null>(null);
  const [fwTopic, setFwTopic] = useState("");
  const [fwDuration, setFwDuration] = useState("60");
  const [fwContext, setFwContext] = useState("");
  const [fwLoading, setFwLoading] = useState(false);
  const [fwResult, setFwResult] = useState<FrameworkScriptResponse | null>(null);
  const [fwExpanded, setFwExpanded] = useState<Set<number>>(new Set([0, 1, 2, 3, 4, 5]));
  const [fwCopied, setFwCopied] = useState<number | null>(null);

  useEffect(() => {
    listFrameworks()
      .then((rows) => {
        // Defensive: if the backend ever returns an empty array we
        // keep the fallback rather than letting the tab go blank.
        if (Array.isArray(rows) && rows.length > 0) {
          setFrameworks(rows);
        }
        setFrameworksLoadError(null);
      })
      .catch((err) => {
        console.error("Failed to load frameworks:", err);
        setFrameworksLoadError(
          err instanceof Error
            ? err.message
            : "Could not refresh framework list — showing built-in defaults.",
        );
      });
  }, []);

  // Controlled tab so we can honor `?tab=frameworks` deep links.
  const [activeTab, setActiveTab] = useState<"standard" | "frameworks">("standard");

  // Deep-link entry from Video Analyzer recommendations and elsewhere.
  // See `lib/deepLinks.ts` for the URL convention. We read once on mount,
  // pre-fill the form, switch tabs if requested, and optionally auto-run
  // the framework generator if the upstream tool was confident enough.
  const deepLinkAppliedRef = useRef(false);
  useEffect(() => {
    if (deepLinkAppliedRef.current) return;
    const link = readScriptWriterDeepLink();
    let touched = false;
    if (link.tab) {
      setActiveTab(link.tab);
      touched = true;
    }
    if (link.framework) {
      setSelectedFramework(link.framework);
      touched = true;
    }
    if (link.topic) {
      setFwTopic(link.topic);
      touched = true;
    }
    if (link.title) {
      setTitle(link.title);
      // If a title arrived but no framework was specified, the upstream
      // tool likely wants the standard generator — leave the tab alone.
      touched = true;
    }
    if (touched) {
      deepLinkAppliedRef.current = true;
      toast.info("Pre-loaded context from your previous tool", {
        duration: 3000,
      });
    }
    // autoRun is honored in a separate effect below so it runs after the
    // controlled state has actually committed.
  }, []);

  // Honor `autoRun=1` once the framework state is ready. We wait for the
  // frameworks list to load (so the validation in handleFrameworkGenerate
  // doesn't trip on a missing framework definition) and for both
  // `selectedFramework` + `fwTopic` to be present.
  const autoRanRef = useRef(false);
  useEffect(() => {
    if (autoRanRef.current) return;
    const link = readScriptWriterDeepLink();
    if (!link.autoRun) return;
    if (!selectedFramework || !fwTopic.trim()) return;
    if (frameworks.length === 0) return;
    autoRanRef.current = true;
    handleFrameworkGenerate();
    // We intentionally exclude handleFrameworkGenerate from deps to
    // avoid re-running the generation if it's recreated each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFramework, fwTopic, frameworks.length]);

  const handleGenerate = async () => {
    if (!title.trim()) {
      toast.error("Please enter a video title");
      return;
    }
    setLoading(true);
    try {
      const result = await generateScript({
        title,
        style,
        target_length_minutes: parseInt(targetLength),
        key_points: keyPoints.split(",").map((p) => p.trim()).filter(Boolean),
        tone: "professional",
      });
      const sections = result.sections.map((s: APIScriptSection, idx: number) => ({
        section: s.name,
        content: s.content,
        duration: s.duration,
        expanded: idx === 0,
      }));
      setScriptSections(sections.length > 0 ? sections : defaultScriptSections);
      setHasGenerated(true);
      toast.success("Script generated successfully!");
    } catch (error) {
      console.error("Script generation failed:", error);
      setScriptSections(defaultScriptSections);
      setHasGenerated(true);
      toast.error("Using example script - API unavailable");
    } finally {
      setLoading(false);
    }
  };

  const handleFrameworkGenerate = async () => {
    if (!selectedFramework) {
      toast.error("Select a framework first");
      return;
    }
    if (!fwTopic.trim()) {
      toast.error("Enter a topic");
      return;
    }
    setFwLoading(true);
    try {
      const result = await generateFrameworkScript(
        fwTopic,
        selectedFramework,
        parseInt(fwDuration),
        fwContext || undefined,
      );
      setFwResult(result);
      // Expand all sections by default
      setFwExpanded(new Set(result.sections.map((_, i) => i)));
      toast.success(`${result.framework_name} script generated!`);
    } catch (error) {
      console.error("Framework script failed:", error);
      toast.error("Failed to generate framework script");
    } finally {
      setFwLoading(false);
    }
  };

  const toggleSection = (idx: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleFwSection = (idx: number) => {
    setFwExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedSection(idx);
    toast.success("Section copied");
    setTimeout(() => setCopiedSection(null), 2000);
  };

  const handleFwCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setFwCopied(idx);
    toast.success("Section copied");
    setTimeout(() => setFwCopied(null), 2000);
  };

  const copyFullScript = () => {
    if (!fwResult) return;
    navigator.clipboard.writeText(fwResult.full_script);
    toast.success("Full script copied!");
  };

  /** Best-effort parser for the standard script's "duration" field.
   *  The backend `duration_estimate` is an int (seconds) but the
   *  default placeholder sections use strings like "~30 seconds" or
   *  "~1.5 minutes". Returns the duration in seconds, clamped to
   *  the backend's accepted range so the API request doesn't fail. */
  const parseDurationSeconds = (raw: unknown): number => {
    if (typeof raw === "number" && Number.isFinite(raw)) {
      return Math.max(1, Math.min(600, Math.round(raw)));
    }
    if (typeof raw !== "string") return 30;
    const match = raw.match(/(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)?/i);
    if (!match) return 30;
    const value = parseFloat(match[1]);
    const unit = (match[2] || "s").toLowerCase();
    const seconds = /^m/.test(unit) ? value * 60 : value;
    return Math.max(1, Math.min(600, Math.round(seconds)));
  };

  /** Build a project from the currently-generated standard script.
   *  Routes through the shared scaffold endpoint so the Project
   *  Editor lands ready-to-go with one placeholder clip per
   *  section (script text surfaced as Studio "notes" / teleprompter).
   */
  const handleCreateProjectFromStandard = async () => {
    if (!hasGenerated || scriptSections.length === 0) {
      toast.error("Generate a script first");
      return;
    }
    setCreatingProject(true);
    try {
      const sections: ScriptToProjectSection[] = scriptSections.map((s) => ({
        name: s.section,
        content: s.content,
        duration_seconds: parseDurationSeconds(s.duration),
      }));
      const project = await scriptToProject({
        title: title || "Untitled script project",
        sections,
        default_aspect: "16:9", // standard scripts are usually long-form
        source_script_id: title,
      });
      toast.success(
        `Project created with ${project.clips.length} placeholder clips`,
      );
      navigate(`/dashboard/studio/project/${project.id}`);
    } catch (error) {
      console.error("Script-to-project failed:", error);
      toast.error("Couldn't create the project — see console for details");
    } finally {
      setCreatingProject(false);
    }
  };

  /** Build a project from the framework-generated script. Framework
   *  scripts target shorter durations so they default to 9:16. */
  const handleCreateProjectFromFramework = async () => {
    if (!fwResult || !selectedFramework) {
      toast.error("Generate a framework script first");
      return;
    }
    setCreatingProject(true);
    try {
      const sections: ScriptToProjectSection[] = fwResult.sections.map((s) => ({
        name: s.label,
        content: s.content,
        duration_seconds: parseDurationSeconds(s.duration),
      }));
      const project = await scriptToProject({
        title: `${fwResult.framework_name}: ${fwResult.topic}`.slice(0, 200),
        sections,
        default_aspect: "9:16",
        framework: fwResult.framework,
        source_script_id: fwResult.topic,
      });
      toast.success(
        `Project created with ${project.clips.length} placeholder clips`,
      );
      navigate(`/dashboard/studio/project/${project.id}`);
    } catch (error) {
      console.error("Script-to-project failed:", error);
      toast.error("Couldn't create the project — see console for details");
    } finally {
      setCreatingProject(false);
    }
  };

  const selectedFrameworkInfo = frameworks.find((f) => f.id === selectedFramework);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Script Writer
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Generate full video scripts with AI, or use one of 4 viral frameworks engineered for trust, saves, retention, or leads.
        </p>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as "standard" | "frameworks")}
        className="space-y-6"
      >
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="standard" className="gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            Standard
          </TabsTrigger>
          <TabsTrigger value="frameworks" className="gap-1.5">
            <Zap className="w-3.5 h-3.5" />
            Viral Frameworks
          </TabsTrigger>
        </TabsList>

        {/* STANDARD SCRIPT TAB */}
        <TabsContent value="standard" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardContent className="p-5 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Video Title
                  </label>
                  <Input
                    className="bg-secondary/50 border-border/50"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Enter your video title..."
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Target Length
                    </label>
                    <Select value={targetLength} onValueChange={setTargetLength}>
                      <SelectTrigger className="bg-secondary/50 border-border/50">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="5">~5 minutes</SelectItem>
                        <SelectItem value="10">~10 minutes</SelectItem>
                        <SelectItem value="15">~15 minutes</SelectItem>
                        <SelectItem value="20">~20 minutes</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Style
                    </label>
                    <Select value={style} onValueChange={setStyle}>
                      <SelectTrigger className="bg-secondary/50 border-border/50">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="storytelling">Storytelling</SelectItem>
                        <SelectItem value="tutorial">Tutorial</SelectItem>
                        <SelectItem value="listicle">Listicle</SelectItem>
                        <SelectItem value="review">Review</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Key Points to Cover (optional)
                </label>
                <Textarea
                  className="bg-secondary/50 border-border/50 min-h-[60px] resize-none"
                  placeholder="List the main topics or points you want to cover..."
                  value={keyPoints}
                  onChange={(e) => setKeyPoints(e.target.value)}
                />
              </div>
              <Button
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                onClick={handleGenerate}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4 mr-2" />
                )}
                {loading ? "Generating..." : "Generate Script"}
              </Button>
            </CardContent>
          </Card>

          {hasGenerated && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-sm font-semibold text-foreground">Generated Script</h2>
                  <Badge variant="outline" className="text-[10px] border-border/50 text-muted-foreground">
                    <Clock className="w-3 h-3 mr-1" />
                    ~{targetLength} min
                  </Badge>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground"
                    onClick={handleGenerate}
                  >
                    <RefreshCw className="w-3 h-3 mr-1" />
                    Regenerate
                  </Button>
                  {/* Week 9 Connected Tools: take the just-generated
                      script straight into the Studio multi-clip
                      editor. Each section becomes a placeholder
                      clip with the script text pre-loaded as
                      teleprompter notes, so the user can film and
                      drop footage in section-by-section without
                      rebuilding the structure by hand. */}
                  <Button
                    size="sm"
                    className="text-xs bg-cyan-glow/10 text-cyan-glow border border-cyan-glow/30 hover:bg-cyan-glow/20"
                    onClick={handleCreateProjectFromStandard}
                    disabled={creatingProject || !hasGenerated}
                  >
                    {creatingProject ? (
                      <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                    ) : (
                      <Layers className="w-3 h-3 mr-1" />
                    )}
                    Create Studio Project
                  </Button>
                  <Button variant="ghost" size="sm" className="text-xs text-muted-foreground">
                    <Download className="w-3 h-3 mr-1" />
                    Export
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                {scriptSections.map((section, i) => (
                  <Card key={i} className="bg-card border-border/50">
                    <div
                      className="flex items-center justify-between p-4 cursor-pointer hover:bg-secondary/20 transition-colors"
                      onClick={() => toggleSection(i)}
                    >
                      <div className="flex items-center gap-3">
                        {expandedSections.has(i) ? (
                          <ChevronDown className="w-4 h-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-muted-foreground" />
                        )}
                        <span className="text-sm font-medium text-foreground">{section.section}</span>
                        <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground">
                          {section.duration}
                        </Badge>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCopy(section.content, i);
                        }}
                      >
                        {copiedSection === i ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3 text-muted-foreground" />
                        )}
                      </Button>
                    </div>
                    {expandedSections.has(i) && (
                      <CardContent className="pt-0 pb-4 px-4">
                        <div className="ml-7 p-4 rounded-lg bg-secondary/20 border border-border/20">
                          <pre className="text-sm text-foreground whitespace-pre-wrap font-[var(--font-body)] leading-relaxed">
                            {section.content}
                          </pre>
                        </div>
                      </CardContent>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          )}
        </TabsContent>

        {/* VIRAL FRAMEWORKS TAB */}
        <TabsContent value="frameworks" className="space-y-6">
          {/* Header with link to public definition page. This is the
              fix for "what does Lead Magnet mean?" — instead of
              forcing users to leave the app and Google it, we
              point at the /frameworks deep dive which defines all
              four with structure, example openings, and a "which
              one should I pick?" decision tree. */}
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="text-xs text-muted-foreground max-w-2xl">
              Pick a framework, give it a topic, and we'll draft a
              full script using the framework's proven structure —
              every section generated against the template the
              format requires.
            </div>
            <a
              href="/frameworks"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-cyan-glow hover:underline inline-flex items-center gap-1 shrink-0"
            >
              Learn about these frameworks
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {frameworksLoadError && (
            <div className="text-xs text-amber-glow border border-amber-glow/30 bg-amber-glow/5 rounded-md p-2">
              {frameworksLoadError}
            </div>
          )}

          {/* Framework Selection */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {frameworks.map((fw) => {
              const visual = FRAMEWORK_VISUALS[fw.id];
              const Icon = visual?.icon || Sparkles;
              const isSelected = selectedFramework === fw.id;
              return (
                <Card
                  key={fw.id}
                  onClick={() => setSelectedFramework(fw.id)}
                  className={`cursor-pointer transition-all hover:scale-[1.02] ${
                    isSelected
                      ? "border-cyan-glow ring-2 ring-cyan-glow/20"
                      : "border-border/50 hover:border-cyan-glow/30"
                  } bg-gradient-to-br ${visual?.gradient || "from-secondary/20 to-secondary/40"}`}
                >
                  <CardContent className="p-5">
                    <div className="flex items-start gap-3 mb-3">
                      <div className="w-10 h-10 rounded-lg bg-background/30 flex items-center justify-center shrink-0">
                        <Icon className="w-5 h-5 text-foreground" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-sm font-bold text-foreground">{fw.name}</h3>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {visual?.tagline}
                        </p>
                      </div>
                      {isSelected && (
                        <Check className="w-4 h-4 text-cyan-glow shrink-0" />
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {fw.goal_description}
                    </p>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Structure Preview */}
          {selectedFrameworkInfo && (
            <Card className="bg-card border-border/50">
              <CardContent className="p-5">
                <div className="flex items-center gap-2 mb-3">
                  <Layers className="w-4 h-4 text-cyan-glow" />
                  <h3 className="text-sm font-semibold text-foreground">
                    {selectedFrameworkInfo.name} Structure
                  </h3>
                </div>
                <div className="space-y-1.5">
                  {selectedFrameworkInfo.sections.map((s, i) => (
                    <div
                      key={s.key}
                      className="flex items-center gap-3 p-2 rounded bg-secondary/30"
                    >
                      <span className="w-5 h-5 rounded-full bg-cyan-glow/10 text-cyan-glow text-[10px] font-bold flex items-center justify-center">
                        {i + 1}
                      </span>
                      <span className="text-xs text-foreground flex-1">{s.label}</span>
                      <Badge variant="outline" className="text-[9px] border-border/50">
                        ~{s.duration}s
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Topic + Generate */}
          {selectedFramework && (
            <Card className="bg-card border-border/50">
              <CardContent className="p-5 space-y-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Topic
                  </label>
                  <Input
                    className="bg-secondary/50 border-border/50"
                    value={fwTopic}
                    onChange={(e) => setFwTopic(e.target.value)}
                    placeholder="e.g. Why most YouTube channels never grow past 1000 subs"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Target Duration
                    </label>
                    <Select value={fwDuration} onValueChange={setFwDuration}>
                      <SelectTrigger className="bg-secondary/50 border-border/50">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="30">30 seconds</SelectItem>
                        <SelectItem value="60">60 seconds</SelectItem>
                        <SelectItem value="90">90 seconds</SelectItem>
                        <SelectItem value="180">3 minutes</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Additional Context (optional)
                  </label>
                  <Textarea
                    className="bg-secondary/50 border-border/50 min-h-[60px] resize-none"
                    value={fwContext}
                    onChange={(e) => setFwContext(e.target.value)}
                    placeholder="Niche specifics, target audience, key claims to include..."
                  />
                </div>
                <Button
                  className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                  onClick={handleFrameworkGenerate}
                  disabled={fwLoading}
                >
                  {fwLoading ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Zap className="w-4 h-4 mr-2" />
                  )}
                  {fwLoading ? "Engineering script..." : "Generate Framework Script"}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Result */}
          {fwResult && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-sm font-semibold text-foreground">
                    {fwResult.framework_name}
                  </h2>
                  <Badge className="bg-cyan-glow/10 text-cyan-glow border-cyan-glow/30 text-[10px]">
                    Goal: {fwResult.primary_goal}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] border-border/50 text-muted-foreground">
                    <Clock className="w-3 h-3 mr-1" />
                    {fwResult.estimated_duration_sec}s · {fwResult.word_count} words
                  </Badge>
                </div>
                <div className="flex gap-2">
                  {/* Take this framework script straight into a new
                      Studio Project — placeholders per section so
                      the editor opens with the structure intact. */}
                  <Button
                    size="sm"
                    className="text-xs bg-cyan-glow/10 text-cyan-glow border border-cyan-glow/30 hover:bg-cyan-glow/20"
                    onClick={handleCreateProjectFromFramework}
                    disabled={creatingProject}
                  >
                    {creatingProject ? (
                      <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                    ) : (
                      <Layers className="w-3 h-3 mr-1" />
                    )}
                    Create Studio Project
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground"
                    onClick={copyFullScript}
                  >
                    <Copy className="w-3 h-3 mr-1" />
                    Copy Full Script
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                {fwResult.sections.map((section, i) => (
                  <Card key={i} className="bg-card border-border/50">
                    <div
                      className="flex items-center justify-between p-4 cursor-pointer hover:bg-secondary/20 transition-colors"
                      onClick={() => toggleFwSection(i)}
                    >
                      <div className="flex items-center gap-3">
                        {fwExpanded.has(i) ? (
                          <ChevronDown className="w-4 h-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-muted-foreground" />
                        )}
                        <span className="text-sm font-medium text-foreground">{section.label}</span>
                        <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground">
                          ~{section.duration}s
                        </Badge>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleFwCopy(section.content, i);
                        }}
                      >
                        {fwCopied === i ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3 text-muted-foreground" />
                        )}
                      </Button>
                    </div>
                    {fwExpanded.has(i) && (
                      <CardContent className="pt-0 pb-4 px-4">
                        <div className="ml-7 p-4 rounded-lg bg-secondary/20 border border-border/20">
                          <p className="text-sm text-foreground whitespace-pre-wrap font-[var(--font-body)] leading-relaxed">
                            {section.content}
                          </p>
                        </div>
                      </CardContent>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

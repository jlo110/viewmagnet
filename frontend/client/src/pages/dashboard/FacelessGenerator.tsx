/**
 * Faceless Video Generator Page
 *
 * Full pipeline: script → AI voiceover (ElevenLabs) → B-roll (Pexels)
 * → animated captions → FFmpeg render.
 *
 * Steps:
 *  1. Paste / write script
 *  2. Parse to preview sections + timing
 *  3. Configure voice, caption style, B-roll toggle
 *  4. Generate (long-running — shows progress by status)
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Loader2,
  Film,
  Wand2,
  CheckCircle2,
  Clock,
  FileText,
  Mic,
  Video,
  Captions,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import {
  parseFacelessScript,
  generateFacelessVideo,
  type FacelessScriptSection,
  type FacelessParseResponse,
  type FacelessProjectOut,
} from "@/lib/api";

type ScriptSection = FacelessScriptSection;
type ParseResponse = FacelessParseResponse;
type FacelessProject = FacelessProjectOut;

const VOICES = [
  { id: "21m00Tcm4TlvDq8ikWAM", name: "Rachel", desc: "Calm female — narration" },
  { id: "TxGEqnHWrfWFTfGW9XjX", name: "Josh",   desc: "Deep male — professional" },
  { id: "ErXwobaYiN019PkySvjV", name: "Antoni", desc: "Natural male — storytelling" },
  { id: "EXAVITQu4vr4xnSDxMaL", name: "Bella",  desc: "Soft female — meditation" },
  { id: "AZnzlk1XvdvUeBnXmlld", name: "Domi",   desc: "Strong female — tutorials" },
  { id: "pNInz6obpgDQGcFmaJgB", name: "Adam",   desc: "Warm male — conversational" },
];

const CAPTION_STYLES = [
  { value: "capcut",    label: "CapCut Style",  desc: "Bold, word-by-word highlights" },
  { value: "subtitles", label: "Subtitles",     desc: "Classic SRT-style bottom bar" },
  { value: "dynamic",   label: "Dynamic",       desc: "Animated fade-in per line" },
];

const PIPELINE_STEPS = [
  { icon: FileText, label: "Parse script",     key: "parsing" },
  { icon: Mic,      label: "Generate voices",  key: "generating_voiceover" },
  { icon: Video,    label: "Find B-roll",      key: "finding_broll" },
  { icon: Captions, label: "Generate captions",key: "generating_captions" },
  { icon: Film,     label: "Render video",     key: "combining" },
  { icon: CheckCircle2, label: "Complete",     key: "completed" },
];

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function FacelessGenerator() {
  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [voiceId, setVoiceId] = useState("21m00Tcm4TlvDq8ikWAM");
  const [captionStyle, setCaptionStyle] = useState("capcut");
  const [includeBroll, setIncludeBroll] = useState(true);

  const [isParsing, setIsParsing] = useState(false);
  const [parsed, setParsed] = useState<ParseResponse | null>(null);

  const [isGenerating, setIsGenerating] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [project, setProject] = useState<FacelessProject | null>(null);

  async function handleParse() {
    if (!script.trim()) {
      toast.error("Enter a script first");
      return;
    }
    setIsParsing(true);
    setParsed(null);
    try {
      const data = await parseFacelessScript(script);
      setParsed(data);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to parse script");
    } finally {
      setIsParsing(false);
    }
  }

  async function handleGenerate() {
    if (!title.trim()) { toast.error("Enter a video title"); return; }
    if (!script.trim()) { toast.error("Enter a script");     return; }

    setIsGenerating(true);
    setProject(null);
    setCurrentStep("parsing");

    // Simulate step progress while the real request runs
    const steps = PIPELINE_STEPS.map((s) => s.key);
    let stepIdx = 0;
    const stepTimer = setInterval(() => {
      stepIdx = Math.min(stepIdx + 1, steps.length - 2);
      setCurrentStep(steps[stepIdx]);
    }, 8000);

    try {
      const data = await generateFacelessVideo({
        title,
        script,
        voice_id: voiceId,
        caption_style: captionStyle,
        include_broll: includeBroll,
      });
      clearInterval(stepTimer);
      setCurrentStep("completed");
      setProject(data);
      toast.success("Faceless video generated!");
    } catch (err: any) {
      clearInterval(stepTimer);
      setCurrentStep(null);
      const msg = err?.response?.data?.detail ?? err?.message ?? "Generation failed";
      toast.error(msg);
    } finally {
      setIsGenerating(false);
    }
  }

  const stepIndex = currentStep
    ? PIPELINE_STEPS.findIndex((s) => s.key === currentStep)
    : -1;

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
            <Film className="w-5 h-5 text-cyan-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Faceless Video Generator</h1>
          <Badge variant="outline" className="text-cyan-400 border-cyan-500/30">
            Beta
          </Badge>
        </div>
        <p className="text-slate-400">
          Turn a script into a fully rendered faceless video: AI voiceover, Pexels B-roll,
          animated captions — all combined with FFmpeg.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Script + title ──────────────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader>
              <CardTitle className="text-base text-white">Script</CardTitle>
              <CardDescription className="text-slate-400">
                Write or paste your full video script. Supports ## headings and [Section] markers for splitting.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="text-slate-300 text-xs mb-1.5 block">Video title</Label>
                <Input
                  placeholder="e.g. 5 Productivity Hacks That Changed My Life"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="bg-slate-800/50 border-slate-600 text-white placeholder:text-slate-500"
                />
              </div>
              <div>
                <Label className="text-slate-300 text-xs mb-1.5 block">Script</Label>
                <Textarea
                  placeholder="## Introduction&#10;Welcome to today's video...&#10;&#10;## Main Point&#10;The first thing you need to know..."
                  value={script}
                  onChange={(e) => { setScript(e.target.value); setParsed(null); }}
                  className="min-h-[260px] bg-slate-800/50 border-slate-600 text-white placeholder:text-slate-500 resize-none font-mono text-sm"
                />
                <div className="flex items-center justify-between mt-2">
                  <span className="text-xs text-slate-500">{script.split(/\s+/).filter(Boolean).length} words</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleParse}
                    disabled={isParsing || !script.trim()}
                    className="border-slate-600 text-slate-300 hover:text-white hover:bg-slate-800"
                  >
                    {isParsing ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : null}
                    Preview sections
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Parsed preview */}
          {parsed && (
            <Card className="bg-slate-900/50 border-slate-700/50">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base text-white">
                    Script Preview — {parsed.sections.length} section{parsed.sections.length !== 1 ? "s" : ""}
                  </CardTitle>
                  <Badge variant="outline" className="text-green-400 border-green-500/30">
                    ~{formatDuration(parsed.estimated_total_seconds)} total
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {parsed.sections.map((s, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-700/30"
                    >
                      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
                        <span className="text-[10px] font-bold text-cyan-400">{i + 1}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-medium text-white">{s.name}</span>
                          <span className="text-xs text-slate-500">~{formatDuration(s.duration_seconds)}</span>
                        </div>
                        <p className="text-xs text-slate-400 line-clamp-2">{s.content}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Generation progress */}
          {isGenerating && (
            <Card className="bg-slate-900/50 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-base text-white flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
                  Generating…
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-1 flex-wrap">
                  {PIPELINE_STEPS.map((step, i) => {
                    const Icon = step.icon;
                    const done = i < stepIndex;
                    const active = i === stepIndex;
                    return (
                      <div key={step.key} className="flex items-center gap-1">
                        <div
                          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs ${
                            done    ? "bg-green-500/10 text-green-400 border border-green-500/20" :
                            active  ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/30" :
                                      "bg-slate-800 text-slate-500 border border-slate-700"
                          }`}
                        >
                          {done ? (
                            <CheckCircle2 className="w-3 h-3" />
                          ) : active ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            <Icon className="w-3 h-3" />
                          )}
                          {step.label}
                        </div>
                        {i < PIPELINE_STEPS.length - 1 && (
                          <ChevronRight className="w-3 h-3 text-slate-600" />
                        )}
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-slate-500 mt-3">
                  This can take several minutes depending on script length and B-roll availability.
                </p>
              </CardContent>
            </Card>
          )}

          {/* Result */}
          {project && project.status === "completed" && (
            <Card className="bg-green-900/20 border-green-700/30">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-green-400" />
                  <CardTitle className="text-base text-white">Video Ready</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-slate-400 text-xs">Project ID</span>
                    <p className="text-white font-mono text-xs">{project.project_id}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-xs">Duration</span>
                    <p className="text-white">{formatDuration(project.estimated_duration_seconds)}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-xs">Voice</span>
                    <p className="text-white">{VOICES.find(v => v.id === project.voice_id)?.name ?? project.voice_id}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-xs">Caption style</span>
                    <p className="text-white capitalize">{project.caption_style}</p>
                  </div>
                </div>
                {project.output_path && (
                  <div className="mt-2 p-2 rounded bg-slate-800/50 border border-slate-700">
                    <span className="text-xs text-slate-400 block mb-1">Output path (server-side)</span>
                    <code className="text-xs text-green-300 break-all">{project.output_path}</code>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Settings ────────────────────────────────────────────────────── */}
        <div className="space-y-4">
          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base text-white">Voice</CardTitle>
            </CardHeader>
            <CardContent>
              <Select value={voiceId} onValueChange={setVoiceId}>
                <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-600">
                  {VOICES.map((v) => (
                    <SelectItem key={v.id} value={v.id} className="text-white">
                      <div>
                        <span className="font-medium">{v.name}</span>
                        <span className="ml-2 text-xs text-slate-400">{v.desc}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>

          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base text-white">Captions</CardTitle>
            </CardHeader>
            <CardContent>
              <Select value={captionStyle} onValueChange={setCaptionStyle}>
                <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-600">
                  {CAPTION_STYLES.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-white">
                      <div>
                        <span className="font-medium">{s.label}</span>
                        <span className="ml-2 text-xs text-slate-400">{s.desc}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>

          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base text-white">B-Roll</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-white">Include B-roll footage</p>
                  <p className="text-xs text-slate-400 mt-0.5">Sources clips from Pexels per section</p>
                </div>
                <Switch
                  checked={includeBroll}
                  onCheckedChange={setIncludeBroll}
                  className="data-[state=checked]:bg-cyan-500"
                />
              </div>
              {!includeBroll && (
                <p className="text-xs text-slate-500 mt-2 italic">
                  Video will use a solid black background.
                </p>
              )}
            </CardContent>
          </Card>

          <Separator className="bg-slate-700/50" />

          <Button
            onClick={handleGenerate}
            disabled={isGenerating || !title.trim() || !script.trim()}
            className="w-full bg-cyan-600 hover:bg-cyan-700 text-white"
          >
            {isGenerating ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Generating…</>
            ) : (
              <><Wand2 className="w-4 h-4 mr-2" /> Generate Video</>
            )}
          </Button>

          <div className="text-xs text-slate-500 space-y-1 px-1">
            <p className="flex items-center gap-1.5">
              <Clock className="w-3 h-3 flex-shrink-0" />
              Generation takes 2–10 min depending on script length.
            </p>
            <p>Requires ElevenLabs API key configured in your account settings.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

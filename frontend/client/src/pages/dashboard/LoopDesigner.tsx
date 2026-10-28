/*
 * Loop Designer: Score loop quality and engineer perfect-loop endings.
 * Based on the Chris Girbu virality framework.
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  Repeat,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Check,
  Type,
  Image as ImageIcon,
  Volume2,
  Sparkles,
  RotateCw,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  analyzeLoop,
  generateLoopEndings,
  type LoopAnalysisResult,
} from "@/lib/api";

function ScoreRing({ value, size = 140 }: { value: number; size?: number }) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (Math.max(0, Math.min(100, value)) / 100) * circumference;
  const color =
    value >= 70 ? "oklch(0.72 0.17 160)"
    : value >= 40 ? "oklch(0.82 0.15 200)"
    : "oklch(0.65 0.2 25)";
  const textColor =
    value >= 70 ? "text-emerald-400"
    : value >= 40 ? "text-cyan-glow"
    : "text-amber-glow";
  return (
    <div className="relative inline-block" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="oklch(0.22 0.01 260)"
          strokeWidth="10"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          className="transition-all"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-bold font-[var(--font-display)] ${textColor}`}>
          {Math.round(value)}
        </span>
        <span className="text-[10px] text-muted-foreground">Loop Score</span>
      </div>
    </div>
  );
}

function SubScoreBar({
  icon: Icon,
  label,
  value,
  method,
}: {
  icon: typeof Type;
  label: string;
  value: number;
  method: string;
}) {
  const isAvailable = method !== "none";
  const colorClass =
    !isAvailable ? "bg-muted-foreground/30"
    : value >= 70 ? "bg-emerald-400"
    : value >= 40 ? "bg-cyan-glow"
    : "bg-amber-glow";
  return (
    <div className="space-y-2 p-4 rounded-lg bg-secondary/30 border border-border/30">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs text-foreground font-medium">{label}</span>
        </div>
        {isAvailable ? (
          <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground">
            {method}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground/60">
            n/a
          </Badge>
        )}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-lg font-bold text-foreground">
          {isAvailable ? Math.round(value) : "—"}
        </span>
        {isAvailable && <span className="text-[10px] text-muted-foreground">/ 100</span>}
      </div>
      <div className="h-1.5 rounded-full bg-secondary/40 overflow-hidden">
        <div
          className={`h-full ${colorClass} transition-all`}
          style={{ width: isAvailable ? `${Math.max(2, Math.min(100, value))}%` : "0%" }}
        />
      </div>
    </div>
  );
}

export default function LoopDesigner() {
  // Analyze state
  const [transcript, setTranscript] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<LoopAnalysisResult | null>(null);

  // Generator state
  const [opening, setOpening] = useState("");
  const [topic, setTopic] = useState("");
  const [endingStyle, setEndingStyle] = useState<
    "natural" | "callback" | "question" | "cliffhanger"
  >("natural");
  const [generating, setGenerating] = useState(false);
  const [endings, setEndings] = useState<string[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const handleAnalyze = async () => {
    if (!transcript.trim() && !videoUrl.trim()) {
      toast.error("Provide a transcript or video URL");
      return;
    }
    setAnalyzing(true);
    try {
      const result = await analyzeLoop(
        transcript.trim() || undefined,
        videoUrl.trim() || undefined,
      );
      setAnalysis(result);
      toast.success("Loop analyzed");
    } catch (err) {
      console.error("Loop analysis failed:", err);
      toast.error("Loop analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleGenerate = async () => {
    if (!opening.trim()) {
      toast.error("Enter the opening of your video");
      return;
    }
    if (!topic.trim()) {
      toast.error("Enter the video topic");
      return;
    }
    setGenerating(true);
    try {
      const result = await generateLoopEndings(opening, topic, 5, endingStyle);
      setEndings(result);
    } catch (err) {
      console.error("Failed to generate endings:", err);
      toast.error("Failed to generate endings");
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = (text: string, idx: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    toast.success("Ending copied");
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
          <Repeat className="w-6 h-6 text-cyan-glow" />
          Loop Designer
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Engineer the perfect loop. Strong loops get massive replay credit from the algorithm - the ending must flow back to the opening.
        </p>
      </div>

      <Tabs defaultValue="analyze" className="space-y-6">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="analyze" className="gap-1.5">
            <RotateCw className="w-3.5 h-3.5" />
            Analyze Loop
          </TabsTrigger>
          <TabsTrigger value="generate" className="gap-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            Generate Endings
          </TabsTrigger>
        </TabsList>

        {/* ANALYZE TAB */}
        <TabsContent value="analyze" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardContent className="p-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Transcript (recommended)
                </label>
                <Textarea
                  className="bg-secondary/50 border-border/50 min-h-[120px] resize-none font-mono text-xs"
                  placeholder="Paste your full video transcript here..."
                  value={transcript}
                  onChange={(e) => setTranscript(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Video URL (optional - enables visual + audio analysis)
                </label>
                <Input
                  className="bg-secondary/50 border-border/50"
                  placeholder="https://youtube.com/watch?v=..."
                  value={videoUrl}
                  onChange={(e) => setVideoUrl(e.target.value)}
                />
              </div>
              <Button
                onClick={handleAnalyze}
                disabled={analyzing}
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold w-full"
              >
                {analyzing ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <RotateCw className="w-4 h-4 mr-2" />
                )}
                {analyzing ? "Analyzing loop..." : "Analyze Loop Quality"}
              </Button>
            </CardContent>
          </Card>

          {analysis && (
            <>
              {/* Overall Score + Sub-scores */}
              <Card className="bg-gradient-to-br from-cyan-glow/5 to-purple-500/5 border-cyan-glow/20">
                <CardContent className="p-6">
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-center">
                    <div className="flex justify-center lg:justify-start">
                      <ScoreRing value={analysis.overall_score} size={140} />
                    </div>
                    <div className="lg:col-span-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <SubScoreBar
                        icon={Type}
                        label="Text"
                        value={analysis.text_score}
                        method={analysis.text_method}
                      />
                      <SubScoreBar
                        icon={ImageIcon}
                        label="Visual"
                        value={analysis.visual_score}
                        method={analysis.visual_method}
                      />
                      <SubScoreBar
                        icon={Volume2}
                        label="Audio"
                        value={analysis.audio_score}
                        method={analysis.audio_method}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Stop signals warning */}
              {analysis.has_stop_signals && (
                <Card className="bg-destructive/10 border-destructive/30">
                  <CardContent className="p-4 flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-destructive">
                        Stop signals detected
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        These phrases tell viewers the video is over and kill the loop:
                      </p>
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {analysis.stop_signals_found.map((s, i) => (
                          <Badge
                            key={i}
                            variant="outline"
                            className="text-[10px] border-destructive/30 text-destructive font-mono"
                          >
                            "{s}"
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* First/Last words comparison */}
              {(analysis.first_words || analysis.last_words) && (
                <Card className="bg-card border-border/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold">
                      Loop Boundary
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
                        Opening (first 15 words)
                      </p>
                      <p className="text-sm text-foreground p-3 rounded bg-secondary/30 border border-border/30">
                        {analysis.first_words || "—"}
                      </p>
                    </div>
                    <div className="flex justify-center">
                      <RotateCw className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
                        Ending (last 15 words)
                      </p>
                      <p className="text-sm text-foreground p-3 rounded bg-secondary/30 border border-border/30">
                        {analysis.last_words || "—"}
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Issues */}
              {analysis.issues.length > 0 && (
                <Card className="bg-card border-border/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-amber-glow" />
                      Issues Found
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {analysis.issues.map((issue, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                          <span className="text-amber-glow shrink-0 mt-0.5">•</span>
                          <span>{issue}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {/* Recommendations */}
              {analysis.recommendations.length > 0 && (
                <Card className="bg-card border-border/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-semibold flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-cyan-glow" />
                      Recommendations
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {analysis.recommendations.map((rec, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                          <CheckCircle2 className="w-3.5 h-3.5 text-cyan-glow shrink-0 mt-0.5" />
                          <span>{rec}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </TabsContent>

        {/* GENERATE TAB */}
        <TabsContent value="generate" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardContent className="p-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Video Opening (first 1-2 sentences)
                </label>
                <Textarea
                  className="bg-secondary/50 border-border/50 min-h-[80px] resize-none"
                  placeholder={`e.g. "You've been doing Instagram captions wrong. Here's why."`}
                  value={opening}
                  onChange={(e) => setOpening(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Topic
                  </label>
                  <Input
                    className="bg-secondary/50 border-border/50"
                    placeholder="e.g. Instagram caption writing"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Ending Style
                  </label>
                  <Select
                    value={endingStyle}
                    onValueChange={(v) => setEndingStyle(v as typeof endingStyle)}
                  >
                    <SelectTrigger className="bg-secondary/50 border-border/50">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="natural">Natural (seamless)</SelectItem>
                      <SelectItem value="callback">Callback (explicit)</SelectItem>
                      <SelectItem value="question">Question (open loop)</SelectItem>
                      <SelectItem value="cliffhanger">Cliffhanger (mid-thought)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button
                onClick={handleGenerate}
                disabled={generating}
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold w-full"
              >
                {generating ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4 mr-2" />
                )}
                {generating ? "Engineering endings..." : "Generate 5 Loop-Back Endings"}
              </Button>
            </CardContent>
          </Card>

          {endings.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-foreground">Loop-Back Endings</h2>
              {endings.map((ending, i) => (
                <Card
                  key={i}
                  className="bg-card border-border/50 hover:border-cyan-glow/20 transition-colors"
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-4">
                      <div className="w-8 h-8 rounded-lg bg-cyan-glow/10 text-cyan-glow flex items-center justify-center shrink-0 font-bold text-xs">
                        {i + 1}
                      </div>
                      <p className="flex-1 text-sm text-foreground leading-relaxed">
                        {ending}
                      </p>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="shrink-0 h-8 w-8"
                        onClick={() => handleCopy(ending, i)}
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
        </TabsContent>
      </Tabs>
    </div>
  );
}

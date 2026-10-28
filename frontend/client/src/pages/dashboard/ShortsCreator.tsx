/*
 * Shorts Creator: Highlight detection, clip extraction from long-form
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Scissors,
  Upload,
  Sparkles,
  Play,
  Clock,
  Zap,
  Download,
  Search,
  Loader2,
  X,
  CheckCircle2,
  Circle,
  Copy,
  ExternalLink,
  Type,
  Wand2,
  FileText,
  Activity,
  Volume2,
  AlertTriangle,
  Network,
  Send,
} from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import {
  detectShortsHighlights,
  extractClip,
  analyzePacing,
  listConnectedAccounts,
  publishDistribution,
  type PacingReportResult,
  type ConnectedAccountSummary,
} from "@/lib/api";
import { Link, useLocation } from "wouter";
import {
  approximateTranscriptTimings,
  buildStudioLink,
} from "@/lib/deepLinks";
import { HookOverlayEditor } from "@/components/HookOverlayEditor";
import { VideoEffectsDialog } from "@/components/VideoEffectsDialog";
import { DescriptionGeneratorDialog } from "@/components/DescriptionGeneratorDialog";

interface HighlightDisplay {
  timestamp: string;
  title: string;
  engagement: number;
  reason: string;
  duration: string;
  durationSeconds: number; // For FFmpeg extraction
  hookType: string;
  startSeconds: number; // For video preview
  endSeconds: number; // For clip extraction
  /** Full transcript snippet for this clip — captured from the API so
   *  that the Studio handoff can seed ``SourceClip.transcript`` with
   *  word-level entries (approximated from word count). Without this
   *  field Studio shows the clip with an empty transcript and the user
   *  has to re-transcribe to get captions. */
  transcriptText?: string;
}

// Progress stages for detection (with realistic time estimates)
const DETECTION_STAGES = [
  { id: "fetch", label: "Fetching video data", minTime: 2 },
  { id: "transcribe", label: "Transcribing audio (may take 1-2 min)", minTime: 30 },
  { id: "analyze", label: "AI analyzing content", minTime: 10 },
  { id: "highlights", label: "Finding viral moments", minTime: 5 },
];

export default function ShortsCreator() {
  const [videoUrl, setVideoUrl] = useState("");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [detected, setDetected] = useState(false);
  const [highlights, setHighlights] = useState<HighlightDisplay[]>([]);
  const [currentStage, setCurrentStage] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [previewClip, setPreviewClip] = useState<HighlightDisplay | null>(null);
  const [sourceVideoId, setSourceVideoId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);
  
  // New feature dialogs
  const [hookEditorOpen, setHookEditorOpen] = useState(false);
  const [effectsDialogOpen, setEffectsDialogOpen] = useState(false);
  const [descriptionDialogOpen, setDescriptionDialogOpen] = useState(false);
  const [selectedClipForHook, setSelectedClipForHook] = useState<HighlightDisplay | null>(null);

  // Pacing analysis state
  const [pacing, setPacing] = useState<PacingReportResult | null>(null);
  const [pacingLoading, setPacingLoading] = useState(false);

  // Distribution state
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccountSummary[]>([]);
  const [distributingClip, setDistributingClip] = useState<number | null>(null);

  // Wouter navigator for the "Edit in Studio" deep-link handoff.
  const [, navigate] = useLocation();

  useEffect(() => {
    listConnectedAccounts(true)
      .then(setConnectedAccounts)
      .catch(() => setConnectedAccounts([]));
  }, []);

  /**
   * Hand the clip off to the Studio editor. Uses the cross-tool deep-link
   * convention (see `lib/deepLinks.ts`) so Studio seeds a new session
   * with the YouTube source URL + trim window the user just discovered.
   *
   * Distinct from "Download Clip" (which exports an MP4 via ffmpeg) —
   * this opens the full multi-track editor so the creator can add
   * captions, b-roll, zooms, and brand before publishing.
   */
  const handleEditInStudio = async (clip: HighlightDisplay) => {
    if (!videoUrl.trim()) {
      toast.error("Need the source video URL to open Studio");
      return;
    }
    // Seed Studio's transcript from the highlight text — without word
    // timings the captions still render and the user can drag the
    // boundaries (vs. starting from a fully empty transcript and
    // having to re-transcribe inside Studio).
    const seededTranscript = approximateTranscriptTimings(
      clip.transcriptText,
      clip.startSeconds,
      clip.endSeconds,
    );
    const link = await buildStudioLink({
      sourceUrl: videoUrl,
      startSeconds: clip.startSeconds,
      endSeconds: clip.endSeconds,
      title: clip.title,
      // Week 10 attribution: tag the cohort as "shorts" so the
      // outcomes dashboard can ask "do edits extracted from Shorts
      // outperform direct uploads?"
      cta: { tool: "shorts", from: "shorts" },
      contextBag: {
        origin: "shorts",
        originVideoId: sourceVideoId ?? undefined,
        transcript: seededTranscript,
        // Pre-load the suggested hook type so the editor can surface
        // a hook-overlay suggestion (consumed by the StudioEditor's
        // mount handler). hook_type is a label like "curiosity" or
        // "shock" — short, fine to ship.
        hooks: clip.hookType ? [clip.hookType] : [],
      },
    });
    navigate(link);
  };

  const handleClipAndDistribute = async (clip: HighlightDisplay, idx: number) => {
    if (!videoUrl.trim()) {
      toast.error("Need the source video URL to distribute");
      return;
    }
    if (connectedAccounts.length === 0) {
      toast.error("Connect a social account first in Distribution Hub");
      return;
    }
    setDistributingClip(idx);
    try {
      const result = await publishDistribution({
        title: clip.title,
        base_caption: clip.reason || clip.title,
        target_account_ids: connectedAccounts.map((a) => a.id),
        video_url: videoUrl,
        source_video_url: videoUrl,
        clip_start_sec: clip.startSeconds,
        clip_end_sec: clip.endSeconds,
        vary_captions: true,
      });
      toast.success(
        `Distributing to ${result.target_count} accounts (job #${result.job_id})`,
      );
    } catch (err) {
      console.error("Distribution failed:", err);
      toast.error("Failed to start distribution");
    } finally {
      setDistributingClip(null);
    }
  };

  const handleAnalyzePacing = async () => {
    if (!videoUrl.trim()) {
      toast.error("Enter a video URL to analyze pacing");
      return;
    }
    setPacingLoading(true);
    try {
      const result = await analyzePacing(videoUrl);
      setPacing(result);
      toast.success(`Pacing graded: ${result.grade}`);
    } catch (err) {
      console.error("Pacing analysis failed:", err);
      toast.error("Pacing analysis failed - is the URL valid?");
    } finally {
      setPacingLoading(false);
    }
  };

  // Extract YouTube video ID from URL
  const extractVideoId = (url: string): string | null => {
    const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|v\/))([^?&]+)/);
    return match ? match[1] : null;
  };

  // Track elapsed time and estimate stage based on realistic timing
  useEffect(() => {
    if (loading) {
      startTimeRef.current = Date.now();
      
      const tick = () => {
        const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
        setElapsedTime(elapsed);
        
        // Estimate current stage based on elapsed time
        // Stage timing: fetch (0-2s), transcribe (2-32s), analyze (32-42s), highlights (42s+)
        let cumulative = 0;
        for (let i = 0; i < DETECTION_STAGES.length; i++) {
          cumulative += DETECTION_STAGES[i].minTime;
          if (elapsed < cumulative) {
            setCurrentStage(i);
            break;
          } else if (i === DETECTION_STAGES.length - 1) {
            // Stay on last stage
            setCurrentStage(i);
          }
        }
      };
      
      timerRef.current = setInterval(tick, 500);
      
      return () => {
        if (timerRef.current) {
          clearInterval(timerRef.current);
        }
      };
    } else {
      setCurrentStage(0);
      setElapsedTime(0);
    }
  }, [loading]);

  // Format elapsed time as MM:SS
  const formatElapsedTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // State for extraction loading
  const [extractingClip, setExtractingClip] = useState<number | null>(null);

  // Extract and download clip from server
  const handleExtractClip = async (clip: HighlightDisplay, index: number, format: "mp4" | "vertical" = "mp4") => {
    if (!sourceVideoId) {
      toast.error("No video URL available for extraction");
      return;
    }
    
    setExtractingClip(index);
    const toastId = toast.loading(`Extracting ${clip.duration} clip...`, {
      description: "This may take 30-60 seconds",
    });
    
    try {
      const youtubeUrl = `https://youtube.com/watch?v=${sourceVideoId}`;
      const blob = await extractClip(youtubeUrl, clip.startSeconds, clip.endSeconds, format);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `clip_${sourceVideoId}_${clip.startSeconds}-${clip.endSeconds}s${format === "vertical" ? "_vertical" : ""}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      
      toast.success("Clip downloaded!", {
        id: toastId,
        description: `${clip.duration} clip saved to your downloads`,
      });
    } catch (error: any) {
      console.error("Extraction failed:", error);
      toast.error("Failed to extract clip", {
        id: toastId,
        description: error?.response?.data?.detail || error?.message || "Try again or use manual download",
      });
    } finally {
      setExtractingClip(null);
    }
  };

  // Download as vertical (9:16) format for Shorts
  const handleDownloadVertical = (clip: HighlightDisplay, index: number) => {
    handleExtractClip(clip, index, "vertical");
  };

  // Open YouTube at exact timestamp
  const handleOpenInYouTube = (clip: HighlightDisplay) => {
    if (!sourceVideoId) return;
    const url = `https://youtube.com/watch?v=${sourceVideoId}&t=${clip.startSeconds}`;
    window.open(url, "_blank");
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validTypes = ["video/mp4", "video/webm", "video/quicktime", "video/mov"];
      if (!validTypes.some(type => file.type.includes(type.split("/")[1]))) {
        toast.error("Please upload a valid video file (MP4, MOV, WebM)");
        return;
      }
      setVideoFile(file);
      setVideoUrl("");
      toast.success(`Video uploaded: ${file.name}`);
    }
  };

  const handleDetect = async () => {
    if (!videoUrl.trim() && !videoFile && !transcript.trim()) {
      toast.error("Please enter a URL, upload a video, or paste a transcript");
      return;
    }
    setLoading(true);
    setCurrentStage(0);
    setElapsedTime(0);
    
    // Extract and save video ID for preview
    if (videoUrl) {
      const vid = extractVideoId(videoUrl);
      setSourceVideoId(vid);
    }
    
    try {
      // Use transcript if provided, otherwise use URL
      const result = await detectShortsHighlights(
        transcript.trim() ? undefined : (videoUrl || undefined),
        transcript.trim() || undefined,
        5
      );
      
      // Convert API response to component format
      if (result.highlights && result.highlights.length > 0) {
        setHighlights(result.highlights.map(h => {
          const formatTime = (seconds: number) => {
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
          };
          
          return {
            timestamp: `${formatTime(h.start_time)} - ${formatTime(h.end_time)}`,
            title: h.suggested_title || h.text?.slice(0, 40) || "Highlight",
            engagement: Math.round(h.score),
            reason: h.reason || "High viral potential detected",
            duration: `${Math.round(h.duration)}s`,
            durationSeconds: Math.round(h.duration),
            hookType: h.hook_type || "medium",
            startSeconds: Math.floor(h.start_time),
            endSeconds: Math.floor(h.end_time),
            // Capture the clip transcript so the Studio handoff has
            // text to seed captions with. The API gives us the full
            // text for the clip (no word timings), so the handoff
            // helper distributes words evenly across the duration.
            transcriptText: h.text ?? undefined,
          };
        }));
        setDetected(true);
        toast.success(`Found ${result.total_found} highlight moments!`);
      } else {
        // API returned but no highlights found - show helpful message
        setDetected(true);
        setHighlights([]);
        const msg = (result as any).message || "No viral moments detected. Try a video with more spoken content, or paste the transcript directly.";
        toast.info(msg);
      }
    } catch (error: any) {
      console.error("Shorts detection failed:", error);
      setDetected(false);
      // Show the actual error message if available
      const errorMsg = error?.response?.data?.detail || error?.message || "Failed to analyze video";
      toast.error(errorMsg);
    } finally {
      setLoading(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Shorts Creator
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Automatically detect highlight moments and extract viral-worthy Shorts from your long-form content.
        </p>
      </div>

      {/* Upload / URL */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5 space-y-4">
          <div className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Paste YouTube video URL..."
                className="pl-10 bg-secondary/50 border-border/50 h-11"
                value={videoUrl}
                onChange={(e) => { setVideoUrl(e.target.value); setVideoFile(null); }}
              />
            </div>
            <Button 
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleDetect}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
              <Scissors className="w-4 h-4 mr-2" />
              )}
              {loading ? "Detecting..." : "Detect Highlights"}
            </Button>
          </div>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept="video/mp4,video/webm,video/quicktime,.mov,.mp4,.webm"
            className="hidden"
          />
          <div 
            className="border-2 border-dashed border-border/50 rounded-lg p-4 text-center hover:border-cyan-glow/30 transition-colors cursor-pointer"
            onClick={() => fileInputRef.current?.click()}
          >
            {videoFile ? (
              <div className="flex items-center justify-center gap-2">
                <span className="text-xs text-cyan-glow">{videoFile.name}</span>
                <button 
                  onClick={(e) => { e.stopPropagation(); setVideoFile(null); }}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <>
            <Upload className="w-5 h-5 text-muted-foreground mx-auto mb-1" />
            <p className="text-xs text-muted-foreground">
                  Click to upload or drag & drop a video file (MP4, MOV, WebM)
            </p>
              </>
            )}
          </div>
          
          {/* Transcript input option */}
          <div className="pt-3 border-t border-border/30">
            <details className="group">
              <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1">
                <span className="group-open:rotate-90 transition-transform">▶</span>
                Or paste transcript directly (more reliable)
              </summary>
              <textarea
                className="mt-2 w-full h-24 p-3 text-xs bg-secondary/50 border border-border/50 rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-cyan-glow/50"
                placeholder="Paste your video transcript here... The AI will analyze it to find the most viral-worthy moments."
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
              />
            </details>
          </div>
        </CardContent>
      </Card>

      {/* Pacing Analyzer */}
      <Card className="bg-gradient-to-br from-cyan-glow/5 to-purple-500/5 border-cyan-glow/20">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Activity className="w-4 h-4 text-cyan-glow" />
                Pacing Analyzer
              </h3>
              <p className="text-xs text-muted-foreground mt-1">
                Detect dead air and slow visual pacing - the two biggest retention killers.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="border-cyan-glow/30"
              onClick={handleAnalyzePacing}
              disabled={pacingLoading || !videoUrl.trim()}
            >
              {pacingLoading ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Activity className="w-3.5 h-3.5 mr-1.5" />
              )}
              {pacingLoading ? "Analyzing..." : "Analyze Pacing"}
            </Button>
          </div>

          {pacing && (
            <div className="space-y-4 mt-4 pt-4 border-t border-border/30">
              {/* Grade + summary stats */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-card border border-border/30">
                  <div className={`text-5xl font-bold font-[var(--font-display)] ${
                    pacing.grade === "A" ? "text-emerald-400" :
                    pacing.grade === "B" ? "text-cyan-glow" :
                    pacing.grade === "C" ? "text-amber-glow" :
                    "text-destructive"
                  }`}>
                    {pacing.grade}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1 uppercase tracking-wider">
                    Grade
                  </p>
                  <p className="text-xs text-foreground mt-0.5">
                    {Math.round(pacing.overall_score)} / 100
                  </p>
                </div>
                <div className="p-4 rounded-lg bg-card border border-border/30">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Scissors className="w-3 h-3 text-muted-foreground" />
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                      Cuts
                    </p>
                  </div>
                  <p className="text-xl font-bold text-foreground">
                    {pacing.cut_count}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    Avg every {pacing.avg_cut_interval_sec.toFixed(1)}s
                  </p>
                </div>
                <div className="p-4 rounded-lg bg-card border border-border/30">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Volume2 className="w-3 h-3 text-muted-foreground" />
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                      Dead Air
                    </p>
                  </div>
                  <p className={`text-xl font-bold ${
                    pacing.dead_air_percent > 10 ? "text-amber-glow" : "text-foreground"
                  }`}>
                    {pacing.dead_air_percent.toFixed(1)}%
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {pacing.total_dead_air_sec.toFixed(1)}s total
                  </p>
                </div>
                <div className="p-4 rounded-lg bg-card border border-border/30">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Clock className="w-3 h-3 text-muted-foreground" />
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                      Longest Static
                    </p>
                  </div>
                  <p className={`text-xl font-bold ${
                    pacing.longest_no_cut_sec > 15 ? "text-amber-glow" : "text-foreground"
                  }`}>
                    {pacing.longest_no_cut_sec.toFixed(1)}s
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    No visual change
                  </p>
                </div>
              </div>

              {/* Dead-air timeline */}
              {pacing.dead_air_segments.length > 0 && pacing.total_duration_sec > 0 && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
                    Dead-Air Timeline ({pacing.dead_air_segments.length} segments)
                  </p>
                  <div className="relative h-6 rounded-md bg-secondary/30 border border-border/30 overflow-hidden">
                    {pacing.dead_air_segments.map((seg, i) => {
                      const left = (seg.start_sec / pacing.total_duration_sec) * 100;
                      const width = Math.max(0.5, (seg.duration_sec / pacing.total_duration_sec) * 100);
                      return (
                        <div
                          key={i}
                          className="absolute top-0 bottom-0 bg-amber-glow/60 hover:bg-amber-glow transition-colors"
                          style={{ left: `${left}%`, width: `${width}%` }}
                          title={`${seg.start_sec.toFixed(1)}s → ${seg.end_sec.toFixed(1)}s (${seg.duration_sec.toFixed(1)}s silence)`}
                        />
                      );
                    })}
                  </div>
                  <div className="flex justify-between mt-1">
                    <span className="text-[9px] text-muted-foreground font-mono">0:00</span>
                    <span className="text-[9px] text-muted-foreground font-mono">
                      {Math.floor(pacing.total_duration_sec / 60)}:
                      {Math.floor(pacing.total_duration_sec % 60).toString().padStart(2, "0")}
                    </span>
                  </div>
                </div>
              )}

              {/* Issues */}
              {pacing.issues.length > 0 && (
                <div className="p-3 rounded-lg bg-amber-glow/5 border border-amber-glow/20">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-glow shrink-0 mt-0.5" />
                    <ul className="space-y-1 flex-1">
                      {pacing.issues.map((issue, i) => (
                        <li key={i} className="text-xs text-foreground">
                          {issue}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {/* Cut suggestions */}
              {pacing.cut_suggestions.length > 0 && (
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
                    Cut Suggestions ({pacing.cut_suggestions.length})
                  </p>
                  <div className="space-y-1.5 max-h-[280px] overflow-y-auto pr-1">
                    {pacing.cut_suggestions.map((s, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-3 p-2.5 rounded-md bg-secondary/30 border border-border/30"
                      >
                        <Badge variant="outline" className="text-[10px] font-mono border-border/50 text-cyan-glow shrink-0">
                          {Math.floor(s.timestamp_sec / 60)}:
                          {Math.floor(s.timestamp_sec % 60).toString().padStart(2, "0")}
                        </Badge>
                        <p className="text-xs text-foreground flex-1 leading-relaxed">
                          {s.recommendation}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Progress Bar During Detection */}
      {loading && (
        <Card className="bg-card border-cyan-glow/30 overflow-hidden">
          <CardContent className="p-5">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-foreground flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin text-cyan-glow" />
                  Analyzing Video...
                </h3>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">
                    Elapsed: <span className="font-mono text-foreground">{formatElapsedTime(elapsedTime)}</span>
                  </span>
                </div>
              </div>
              
              {/* Indeterminate Progress Bar */}
              <div className="h-2 bg-secondary rounded-full overflow-hidden relative">
                <div 
                  className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-cyan-glow to-transparent animate-[shimmer_1.5s_infinite]"
                  style={{
                    animation: "shimmer 1.5s infinite linear",
                  }}
                />
                <style>{`
                  @keyframes shimmer {
                    0% { transform: translateX(-100%); }
                    100% { transform: translateX(400%); }
                  }
                `}</style>
              </div>
              
              {/* Stage indicators */}
              <div className="grid grid-cols-4 gap-2">
                {DETECTION_STAGES.map((stage, i) => (
                  <div 
                    key={stage.id}
                    className={`flex items-center gap-2 p-2 rounded-lg transition-all ${
                      i < currentStage 
                        ? "bg-emerald-500/10 border border-emerald-500/20" 
                        : i === currentStage 
                          ? "bg-cyan-glow/10 border border-cyan-glow/30 animate-pulse"
                          : "bg-secondary/30 border border-border/20"
                    }`}
                  >
                    {i < currentStage ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : i === currentStage ? (
                      <Loader2 className="w-4 h-4 text-cyan-glow animate-spin shrink-0" />
                    ) : (
                      <Circle className="w-4 h-4 text-muted-foreground/50 shrink-0" />
                    )}
                    <div className="flex flex-col">
                      <span className={`text-[10px] leading-tight ${
                        i <= currentStage ? "text-foreground" : "text-muted-foreground/50"
                      }`}>
                        {stage.label}
                      </span>
                      {i === currentStage && (
                        <span className="text-[9px] text-muted-foreground">~{stage.minTime}s+</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              
              {/* Helpful message */}
              <p className="text-[11px] text-muted-foreground text-center">
                {currentStage === 1 
                  ? "⏳ Whisper transcription can take 1-2 minutes for longer videos..."
                  : currentStage === 2
                    ? "🧠 AI is analyzing the transcript for viral moments..."
                    : "Processing your video..."}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detected Highlights */}
      {detected && (
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-foreground">
            Detected Highlights
            <Badge variant="outline" className="ml-2 text-[10px] border-cyan-glow/30 text-cyan-glow">
              {highlights.length} found
            </Badge>
          </h2>
          {highlights.length > 0 && (
          <Button variant="ghost" size="sm" className="text-xs text-muted-foreground">
            <Sparkles className="w-3 h-3 mr-1" />
            Auto-generate all
          </Button>
          )}
        </div>

        {highlights.length === 0 ? (
          <Card className="bg-card border-border/50">
            <CardContent className="p-8 text-center">
              <Scissors className="w-10 h-10 text-muted-foreground mx-auto mb-3 opacity-50" />
              <h3 className="text-sm font-medium text-foreground mb-2">No Highlights Detected</h3>
              <p className="text-xs text-muted-foreground max-w-md mx-auto">
                This video may not have enough spoken content, or the transcript wasn't available.
                <br /><br />
                <strong>Try:</strong> Paste the video transcript directly in the text area below, 
                or try a different video with more dialogue/narration.
              </p>
            </CardContent>
          </Card>
        ) : (
        <div className="space-y-3">
          {highlights.map((clip, i) => (
            <Card key={i} className="bg-card border-border/50 hover:border-cyan-glow/20 transition-colors">
              <CardContent className="p-4">
                <div className="flex items-start gap-4">
                  {/* Preview thumbnail - clickable */}
                  <button
                    onClick={() => setPreviewClip(clip)}
                    disabled={!sourceVideoId}
                    className="w-24 h-[136px] rounded-lg bg-gradient-to-b from-cyan-glow/10 to-amber-glow/10 border border-border/30 flex flex-col items-center justify-center shrink-0 relative overflow-hidden group hover:border-cyan-glow/50 transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Play className="w-6 h-6 text-muted-foreground mb-1 group-hover:text-cyan-glow transition-colors" />
                    <span className="text-[9px] text-muted-foreground group-hover:text-foreground">Preview</span>
                    <div className="absolute bottom-0 left-0 right-0 bg-background/80 py-1 text-center">
                      <span className="text-[9px] font-[var(--font-mono)] text-muted-foreground">{clip.duration}</span>
                    </div>
                    {/* Hover overlay */}
                    <div className="absolute inset-0 bg-cyan-glow/0 group-hover:bg-cyan-glow/5 transition-colors" />
                  </button>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-1">
                      <h3 className="text-sm font-medium text-foreground">{clip.title}</h3>
                      <Badge
                        className={`text-[10px] ${
                          clip.engagement >= 90
                            ? "bg-emerald-400/10 text-emerald-400 border-emerald-400/20"
                            : "bg-cyan-glow/10 text-cyan-glow border-cyan-glow/20"
                        }`}
                      >
                        <Zap className="w-3 h-3 mr-0.5" />
                        {clip.engagement}% viral potential
                      </Badge>
                    </div>

                    <div className="flex items-center gap-2 mb-2">
                      <Clock className="w-3 h-3 text-muted-foreground" />
                      <span className="text-xs font-[var(--font-mono)] text-muted-foreground">
                        {clip.timestamp}
                      </span>
                    </div>

                    <p className="text-xs text-muted-foreground mb-3">{clip.reason}</p>

                    <div className="flex items-center gap-2 flex-wrap">
                      <Button 
                        size="sm" 
                        className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 text-xs h-7"
                        onClick={() => handleExtractClip(clip, i)}
                        disabled={!sourceVideoId || extractingClip !== null}
                        title="Extract and download this clip"
                      >
                        {extractingClip === i ? (
                          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        ) : (
                          <Download className="w-3 h-3 mr-1" />
                        )}
                        {extractingClip === i ? "Extracting..." : "Download Clip"}
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="text-xs h-7"
                        onClick={() => handleDownloadVertical(clip, i)}
                        disabled={!sourceVideoId || extractingClip !== null}
                        title="Download as vertical 9:16 for Shorts"
                      >
                        <Scissors className="w-3 h-3 mr-1" />
                        Vertical
                      </Button>
                      <Button
                        size="sm"
                        className="bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 border border-purple-500/30 text-xs h-7"
                        onClick={() => handleEditInStudio(clip)}
                        disabled={!videoUrl.trim()}
                        title="Open this clip in the Studio editor with captions, b-roll, and zooms"
                      >
                        <Wand2 className="w-3 h-3 mr-1" />
                        Edit in Studio
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="text-xs h-7"
                        onClick={() => setPreviewClip(clip)}
                        disabled={!sourceVideoId}
                      >
                        <Play className="w-3 h-3 mr-1" />
                        Preview
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="text-xs h-7"
                        onClick={() => {
                          setSelectedClipForHook(clip);
                          setHookEditorOpen(true);
                        }}
                        disabled={!sourceVideoId}
                        title="Add hook text overlay"
                      >
                        <Type className="w-3 h-3 mr-1" />
                        Hook
                      </Button>
                      {connectedAccounts.length > 0 ? (
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs h-7 border-cyan-glow/30 text-cyan-glow hover:bg-cyan-glow/10"
                          onClick={() => handleClipAndDistribute(clip, i)}
                          disabled={!videoUrl.trim() || distributingClip !== null}
                          title={`Clip and distribute to ${connectedAccounts.length} account(s)`}
                        >
                          {distributingClip === i ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          ) : (
                            <Send className="w-3 h-3 mr-1" />
                          )}
                          Distribute to {connectedAccounts.length}
                        </Button>
                      ) : (
                        <Link href="/dashboard/distribution">
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-xs h-7 border-amber-glow/30 text-amber-glow hover:bg-amber-glow/10"
                            title="Connect accounts to enable distribution"
                          >
                            <Network className="w-3 h-3 mr-1" />
                            Connect Accounts
                          </Button>
                        </Link>
                      )}
                      {sourceVideoId && (
                        <Button 
                          size="sm" 
                          variant="ghost" 
                          className="text-xs h-7"
                          onClick={() => handleOpenInYouTube(clip)}
                          title="Open in YouTube at this timestamp"
                        >
                          <ExternalLink className="w-3 h-3 mr-1" />
                          YouTube
                      </Button>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        )}
      </div>
      )}

      {/* Video Preview Modal */}
      <Dialog open={!!previewClip} onOpenChange={(open) => !open && setPreviewClip(null)}>
        <DialogContent className="max-w-3xl bg-card border-border/50">
          <DialogHeader>
            <DialogTitle className="text-foreground flex items-center gap-2">
              <Play className="w-4 h-4 text-cyan-glow" />
              Preview: {previewClip?.title}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            {/* YouTube Embed */}
            {sourceVideoId && previewClip && (
              <div className="relative aspect-video w-full rounded-lg overflow-hidden bg-black">
                <iframe
                  src={`https://www.youtube.com/embed/${sourceVideoId}?start=${previewClip.startSeconds}&autoplay=1&rel=0`}
                  title="Video Preview"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                  className="absolute inset-0 w-full h-full"
                />
              </div>
            )}
            
            {/* Clip info */}
            {previewClip && (
              <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/50 border border-border/30">
                <div className="flex items-center gap-4">
                  <div>
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Timestamp</span>
                    <p className="text-sm font-mono text-foreground">{previewClip.timestamp}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Duration</span>
                    <p className="text-sm font-mono text-foreground">{previewClip.duration}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Viral Score</span>
                    <p className="text-sm font-mono text-cyan-glow">{previewClip.engagement}%</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button 
                    size="sm" 
                    className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                    onClick={() => previewClip && handleExtractClip(previewClip, -1)}
                    disabled={extractingClip !== null}
                  >
                    {extractingClip === -1 ? (
                      <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                    ) : (
                      <Download className="w-3 h-3 mr-1" />
                    )}
                    {extractingClip === -1 ? "Extracting..." : "Download Clip"}
                  </Button>
                  <Button 
                    size="sm" 
                    variant="outline"
                    onClick={() => previewClip && handleDownloadVertical(previewClip, -1)}
                    disabled={extractingClip !== null}
                  >
                    <Scissors className="w-3 h-3 mr-1" />
                    Download Vertical
                  </Button>
                </div>
              </div>
            )}
            
            {!sourceVideoId && (
              <div className="text-center py-8 text-muted-foreground">
                <p className="text-sm">Preview not available for transcript-only analysis.</p>
                <p className="text-xs mt-1">Provide a YouTube URL to enable video preview.</p>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Quick Actions Bar (shown when highlights are detected) */}
      {detected && highlights.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-card/95 backdrop-blur-sm border border-border/50 rounded-full px-6 py-3 shadow-lg z-40">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground mr-2">Quick Actions:</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEffectsDialogOpen(true)}
              disabled={!transcript}
              title="Generate AI video effects"
            >
              <Wand2 className="w-4 h-4 mr-1" />
              AI Effects
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDescriptionDialogOpen(true)}
              title="Generate YouTube description"
            >
              <FileText className="w-4 h-4 mr-1" />
              Description
            </Button>
          </div>
        </div>
      )}

      {/* Hook Overlay Editor Dialog */}
      <HookOverlayEditor
        open={hookEditorOpen}
        onOpenChange={setHookEditorOpen}
        videoUrl={sourceVideoId ? `https://youtube.com/watch?v=${sourceVideoId}` : undefined}
        suggestedHooks={selectedClipForHook ? [selectedClipForHook.title.toUpperCase()] : []}
      />

      {/* Video Effects Dialog */}
      <VideoEffectsDialog
        open={effectsDialogOpen}
        onOpenChange={setEffectsDialogOpen}
        transcript={transcript}
        duration={highlights.length > 0 ? highlights[0].endSeconds : 60}
        videoUrl={sourceVideoId ? `https://youtube.com/watch?v=${sourceVideoId}` : undefined}
      />

      {/* Description Generator Dialog */}
      <DescriptionGeneratorDialog
        open={descriptionDialogOpen}
        onOpenChange={setDescriptionDialogOpen}
        title={highlights.length > 0 ? highlights[0].title : "Video"}
        transcript={transcript}
      />
    </div>
  );
}

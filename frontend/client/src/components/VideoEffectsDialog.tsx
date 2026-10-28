/**
 * Video Effects Dialog Component
 * 
 * AI-powered video effects generator using Claude to create
 * contextual zooms, color grading, and dynamic adjustments.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Loader2, Sparkles, Wand2, Download, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";
import {
  analyzeVideoEffects,
  applyVideoEffects,
  VideoEffectsAnalyzeResponse,
  EffectSegment,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface VideoEffectsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript: string;
  duration: number;
  videoUrl?: string;
  videoFile?: File;
  width?: number;
  height?: number;
  fps?: number;
  onComplete?: (blob: Blob) => void;
}

type Intensity = "subtle" | "medium" | "dramatic";

const INTENSITY_INFO: Record<Intensity, { label: string; description: string }> = {
  subtle: {
    label: "Subtle",
    description: "Very light effects, barely noticeable",
  },
  medium: {
    label: "Medium",
    description: "Balanced effects, professional look",
  },
  dramatic: {
    label: "Dramatic",
    description: "Bold effects, high engagement",
  },
};

export function VideoEffectsDialog({
  open,
  onOpenChange,
  transcript,
  duration,
  videoUrl,
  videoFile,
  width = 1080,
  height = 1920,
  fps = 30,
  onComplete,
}: VideoEffectsDialogProps) {
  const [intensity, setIntensity] = useState<Intensity>("medium");
  const [analyzing, setAnalyzing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [effectsConfig, setEffectsConfig] = useState<VideoEffectsAnalyzeResponse | null>(null);
  const [showSegments, setShowSegments] = useState(false);

  const handleAnalyze = async () => {
    if (!transcript.trim()) {
      toast.error("Transcript is required for AI effects");
      return;
    }

    setAnalyzing(true);
    const toastId = toast.loading("Analyzing video content...", {
      description: "AI is generating contextual effects",
    });

    try {
      const config = await analyzeVideoEffects({
        transcript,
        duration,
        fps,
        width,
        height,
        intensity,
      });

      setEffectsConfig(config);
      toast.success(`Generated ${config.segment_count} effect segments`, { id: toastId });
    } catch (error) {
      console.error("Analysis failed:", error);
      toast.error("Failed to analyze video", { id: toastId });
    } finally {
      setAnalyzing(false);
    }
  };

  const handleApply = async () => {
    if (!effectsConfig?.filter_string) {
      toast.error("Please analyze the video first");
      return;
    }

    if (!videoUrl && !videoFile) {
      toast.error("No video source provided");
      return;
    }

    setApplying(true);
    const toastId = toast.loading("Applying video effects...", {
      description: "This may take 1-3 minutes",
    });

    try {
      const blob = await applyVideoEffects(
        effectsConfig.filter_string,
        videoUrl,
        videoFile
      );

      toast.success("Effects applied successfully!", { id: toastId });

      if (onComplete) {
        onComplete(blob);
      } else {
        // Download the video
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "video_with_effects.mp4";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }

      onOpenChange(false);
    } catch (error) {
      console.error("Apply failed:", error);
      toast.error("Failed to apply effects", { id: toastId });
    } finally {
      setApplying(false);
    }
  };

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wand2 className="h-5 w-5" />
            AI Video Effects
          </DialogTitle>
          <DialogDescription>
            Generate dynamic zooms, color grading, and visual enhancements based on your video content.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 py-4">
          {/* Intensity Selector */}
          <div className="space-y-2">
            <Label>Effect Intensity</Label>
            <Select
              value={intensity}
              onValueChange={(v) => {
                setIntensity(v as Intensity);
                setEffectsConfig(null); // Reset when intensity changes
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(INTENSITY_INFO) as Intensity[]).map((key) => (
                  <SelectItem key={key} value={key}>
                    <div className="flex flex-col items-start">
                      <span>{INTENSITY_INFO[key].label}</span>
                      <span className="text-xs text-muted-foreground">
                        {INTENSITY_INFO[key].description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Video Info */}
          <div className="flex gap-4 p-3 bg-muted/50 rounded-lg text-sm">
            <div>
              <span className="text-muted-foreground">Duration:</span>{" "}
              <span className="font-medium">{formatTime(duration)}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Resolution:</span>{" "}
              <span className="font-medium">{width}x{height}</span>
            </div>
            <div>
              <span className="text-muted-foreground">FPS:</span>{" "}
              <span className="font-medium">{fps}</span>
            </div>
          </div>

          {/* Analyze Button */}
          {!effectsConfig && (
            <Button onClick={handleAnalyze} disabled={analyzing} className="w-full">
              {analyzing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Sparkles className="mr-2 h-4 w-4" />
                  Analyze & Generate Effects
                </>
              )}
            </Button>
          )}

          {/* Effects Preview */}
          {effectsConfig && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">{effectsConfig.segment_count} segments</Badge>
                  <Badge variant="outline">{effectsConfig.intensity} intensity</Badge>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowSegments(!showSegments)}
                >
                  {showSegments ? (
                    <>
                      <ChevronUp className="mr-1 h-4 w-4" />
                      Hide Details
                    </>
                  ) : (
                    <>
                      <ChevronDown className="mr-1 h-4 w-4" />
                      Show Details
                    </>
                  )}
                </Button>
              </div>

              {/* Segment Details */}
              {showSegments && (
                <div className="border rounded-lg divide-y max-h-60 overflow-y-auto">
                  {effectsConfig.segments.map((segment, i) => (
                    <SegmentRow key={i} segment={segment} index={i} />
                  ))}
                </div>
              )}

              {/* Re-analyze Button */}
              <Button
                variant="outline"
                onClick={() => setEffectsConfig(null)}
                className="w-full"
              >
                Change Settings & Re-analyze
              </Button>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleApply}
            disabled={!effectsConfig || applying}
          >
            {applying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Applying...
              </>
            ) : (
              <>
                <Download className="mr-2 h-4 w-4" />
                Apply Effects
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface SegmentRowProps {
  segment: EffectSegment;
  index: number;
}

function SegmentRow({ segment, index }: SegmentRowProps) {
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="p-3 text-sm">
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium">
          Segment {index + 1}: {formatTime(segment.start_sec)} - {formatTime(segment.end_sec)}
        </span>
        <div className="flex gap-1">
          {segment.zoom !== 1 && (
            <Badge variant="outline" className="text-xs">
              {segment.zoom.toFixed(2)}x zoom
            </Badge>
          )}
          {segment.contrast !== 1 && (
            <Badge variant="outline" className="text-xs">
              {segment.contrast.toFixed(2)} contrast
            </Badge>
          )}
          {segment.saturate !== 1 && (
            <Badge variant="outline" className="text-xs">
              {segment.saturate.toFixed(2)} saturation
            </Badge>
          )}
        </div>
      </div>
      {segment.description && (
        <p className="text-muted-foreground text-xs">{segment.description}</p>
      )}
    </div>
  );
}

export default VideoEffectsDialog;

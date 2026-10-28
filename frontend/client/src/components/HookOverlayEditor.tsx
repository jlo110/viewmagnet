/**
 * Hook Overlay Editor Component
 * 
 * Allows users to add attention-grabbing text overlays to videos.
 */

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
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
  DialogFooter,
} from "@/components/ui/dialog";
import { Loader2, Type, Sparkles, Download } from "lucide-react";
import { toast } from "sonner";
import { previewHook, applyHookToVideo } from "@/lib/api";

interface HookOverlayEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  videoUrl?: string;
  videoFile?: File;
  onComplete?: (blob: Blob) => void;
  suggestedHooks?: string[];
}

const HOOK_SUGGESTIONS = [
  "WATCH THIS",
  "YOU NEED TO SEE THIS",
  "THIS CHANGES EVERYTHING",
  "WAIT FOR IT...",
  "NO ONE TALKS ABOUT THIS",
  "THE SECRET IS...",
  "HERE'S THE TRUTH",
  "DON'T SKIP THIS",
];

export function HookOverlayEditor({
  open,
  onOpenChange,
  videoUrl,
  videoFile,
  onComplete,
  suggestedHooks = [],
}: HookOverlayEditorProps) {
  const [hookText, setHookText] = useState("");
  const [position, setPosition] = useState<"top" | "center" | "bottom">("top");
  const [fontScale, setFontScale] = useState(1.0);
  const [duration, setDuration] = useState<number | undefined>(undefined);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  // Combine provided suggestions with defaults
  const allSuggestions = [...suggestedHooks, ...HOOK_SUGGESTIONS].slice(0, 8);

  // Generate preview when text changes
  useEffect(() => {
    if (!hookText.trim()) {
      setPreviewUrl(null);
      return;
    }

    const debounce = setTimeout(async () => {
      try {
        setLoading(true);
        const blob = await previewHook({
          text: hookText,
          position,
          font_scale: fontScale,
          target_width: 1080,
        });
        const url = URL.createObjectURL(blob);
        setPreviewUrl(url);
      } catch (error) {
        console.error("Preview failed:", error);
      } finally {
        setLoading(false);
      }
    }, 500);

    return () => clearTimeout(debounce);
  }, [hookText, position, fontScale]);

  // Cleanup preview URL on unmount
  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  const handleApply = async () => {
    if (!hookText.trim()) {
      toast.error("Please enter hook text");
      return;
    }

    if (!videoUrl && !videoFile) {
      toast.error("No video source provided");
      return;
    }

    setApplying(true);
    const toastId = toast.loading("Applying hook overlay...", {
      description: "This may take 30-60 seconds",
    });

    try {
      const blob = await applyHookToVideo(
        hookText,
        position,
        fontScale,
        videoUrl,
        videoFile,
        duration
      );

      toast.success("Hook applied successfully!", { id: toastId });

      if (onComplete) {
        onComplete(blob);
      } else {
        // Download the video
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "video_with_hook.mp4";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }

      onOpenChange(false);
    } catch (error) {
      console.error("Apply failed:", error);
      toast.error("Failed to apply hook overlay", { id: toastId });
    } finally {
      setApplying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Type className="h-5 w-5" />
            Add Hook Text Overlay
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-6 py-4">
          {/* Hook Text Input */}
          <div className="space-y-2">
            <Label htmlFor="hook-text">Hook Text</Label>
            <Input
              id="hook-text"
              placeholder="Enter attention-grabbing text..."
              value={hookText}
              onChange={(e) => setHookText(e.target.value.toUpperCase())}
              maxLength={100}
            />
            <p className="text-xs text-muted-foreground">
              Use short, impactful text. All caps recommended.
            </p>
          </div>

          {/* Quick Suggestions */}
          <div className="space-y-2">
            <Label>Quick Suggestions</Label>
            <div className="flex flex-wrap gap-2">
              {allSuggestions.map((suggestion, i) => (
                <Button
                  key={i}
                  variant="outline"
                  size="sm"
                  onClick={() => setHookText(suggestion)}
                  className="text-xs"
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>

          {/* Position Selector */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Position</Label>
              <Select value={position} onValueChange={(v) => setPosition(v as "top" | "center" | "bottom")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="top">Top (20%)</SelectItem>
                  <SelectItem value="center">Center</SelectItem>
                  <SelectItem value="bottom">Bottom (70%)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Font Scale: {fontScale.toFixed(1)}x</Label>
              <Slider
                value={[fontScale]}
                onValueChange={([v]) => setFontScale(v)}
                min={0.5}
                max={2.0}
                step={0.1}
              />
            </div>
          </div>

          {/* Duration (Optional) */}
          <div className="space-y-2">
            <Label>Display Duration (seconds, optional)</Label>
            <Input
              type="number"
              placeholder="Full video if empty"
              value={duration || ""}
              onChange={(e) => setDuration(e.target.value ? parseFloat(e.target.value) : undefined)}
              min={1}
              max={60}
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to show throughout the entire video
            </p>
          </div>

          {/* Preview */}
          <div className="space-y-2">
            <Label>Preview</Label>
            <div className="relative border rounded-lg bg-muted/50 min-h-[120px] flex items-center justify-center">
              {loading ? (
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              ) : previewUrl ? (
                <img
                  src={previewUrl}
                  alt="Hook preview"
                  className="max-w-full h-auto"
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  Enter text to see preview
                </p>
              )}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleApply} disabled={applying || !hookText.trim()}>
            {applying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Applying...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4" />
                Apply Hook
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default HookOverlayEditor;

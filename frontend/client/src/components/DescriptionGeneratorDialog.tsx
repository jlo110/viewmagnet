/**
 * Description Generator Dialog Component
 * 
 * AI-powered YouTube description generator with chapters and hashtags.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Loader2, FileText, Copy, Check, Clock, Hash } from "lucide-react";
import { toast } from "sonner";
import {
  generateYouTubeDescription,
  GeneratedDescription,
  DescriptionGenerateRequest,
} from "@/lib/api";

interface DescriptionGeneratorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  transcript?: string;
  transcriptSegments?: Array<{ start: number; end: number; text: string }>;
  videoDuration?: number;
  language?: string;
}

export function DescriptionGeneratorDialog({
  open,
  onOpenChange,
  title,
  transcript,
  transcriptSegments,
  videoDuration,
  language = "en",
}: DescriptionGeneratorDialogProps) {
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<GeneratedDescription | null>(null);
  const [includeChapters, setIncludeChapters] = useState(true);
  const [includeHashtags, setIncludeHashtags] = useState(true);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async () => {
    if (!title) {
      toast.error("Video title is required");
      return;
    }

    setGenerating(true);
    const toastId = toast.loading("Generating description...", {
      description: "AI is creating an SEO-optimized description",
    });

    try {
      const request: DescriptionGenerateRequest = {
        title,
        transcript,
        transcript_segments: transcriptSegments,
        video_duration: videoDuration,
        language,
        include_chapters: includeChapters,
        include_hashtags: includeHashtags,
      };

      const generated = await generateYouTubeDescription(request);
      setResult(generated);
      toast.success("Description generated!", { id: toastId });
    } catch (error) {
      console.error("Generation failed:", error);
      toast.error("Failed to generate description", { id: toastId });
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async () => {
    if (!result) return;

    try {
      await navigator.clipboard.writeText(result.description);
      setCopied(true);
      toast.success("Copied to clipboard!");
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      toast.error("Failed to copy");
    }
  };

  const handleReset = () => {
    setResult(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Generate YouTube Description
          </DialogTitle>
          <DialogDescription>
            Create an SEO-optimized description with chapters and hashtags
          </DialogDescription>
        </DialogHeader>

        {!result ? (
          <div className="grid gap-6 py-4">
            {/* Video Info */}
            <div className="p-4 bg-muted/50 rounded-lg space-y-2">
              <div>
                <span className="text-sm text-muted-foreground">Title:</span>
                <p className="font-medium">{title}</p>
              </div>
              {videoDuration && (
                <div>
                  <span className="text-sm text-muted-foreground">Duration:</span>
                  <span className="ml-2">
                    {Math.floor(videoDuration / 60)}:{String(Math.floor(videoDuration % 60)).padStart(2, "0")}
                  </span>
                </div>
              )}
              {transcript && (
                <div>
                  <span className="text-sm text-muted-foreground">Transcript:</span>
                  <span className="ml-2 text-green-500">Available</span>
                </div>
              )}
            </div>

            {/* Options */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="chapters">Include Chapters</Label>
                  <p className="text-xs text-muted-foreground">
                    Add timestamp chapters from transcript segments
                  </p>
                </div>
                <Switch
                  id="chapters"
                  checked={includeChapters}
                  onCheckedChange={setIncludeChapters}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="hashtags">Include Hashtags</Label>
                  <p className="text-xs text-muted-foreground">
                    Add relevant hashtags for discoverability
                  </p>
                </div>
                <Switch
                  id="hashtags"
                  checked={includeHashtags}
                  onCheckedChange={setIncludeHashtags}
                />
              </div>
            </div>

            {/* Generate Button */}
            <Button onClick={handleGenerate} disabled={generating} className="w-full">
              {generating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <FileText className="mr-2 h-4 w-4" />
                  Generate Description
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 py-4">
            {/* Generated Description */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Generated Description</Label>
                <Button variant="ghost" size="sm" onClick={handleCopy}>
                  {copied ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                  <span className="ml-1">{copied ? "Copied" : "Copy"}</span>
                </Button>
              </div>
              <Textarea
                value={result.description}
                readOnly
                className="min-h-[200px] font-mono text-sm"
              />
            </div>

            {/* Chapters */}
            {result.chapters.length > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Clock className="h-4 w-4" />
                    Chapters ({result.chapters.length})
                  </Label>
                  <div className="grid gap-1 max-h-32 overflow-y-auto">
                    {result.chapters.map((chapter, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-sm p-1 rounded hover:bg-muted/50"
                      >
                        <Badge variant="outline" className="font-mono">
                          {chapter.timestamp}
                        </Badge>
                        <span>{chapter.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Hashtags */}
            {result.hashtags.length > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <Hash className="h-4 w-4" />
                    Hashtags ({result.hashtags.length})
                  </Label>
                  <div className="flex flex-wrap gap-1">
                    {result.hashtags.map((tag, i) => (
                      <Badge key={i} variant="secondary">
                        #{tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Regenerate Button */}
            <Button variant="outline" onClick={handleReset} className="w-full">
              Generate Again
            </Button>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default DescriptionGeneratorDialog;

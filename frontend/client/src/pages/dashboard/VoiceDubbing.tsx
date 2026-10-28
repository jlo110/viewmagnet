/**
 * Voice Dubbing Page
 * 
 * Translate video audio to 30+ languages using ElevenLabs dubbing API.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Loader2,
  Upload,
  Link as LinkIcon,
  Languages,
  Download,
  CheckCircle,
  XCircle,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import {
  getDubbingLanguages,
  startDubbingJob,
  checkDubbingStatus,
  downloadDubbedVideo,
  DubbingLanguage,
  DubbingStatus,
} from "@/lib/api";

export default function VoiceDubbing() {
  const [languages, setLanguages] = useState<DubbingLanguage[]>([]);
  const [loadingLanguages, setLoadingLanguages] = useState(true);
  const [inputMode, setInputMode] = useState<"url" | "upload">("url");
  const [videoUrl, setVideoUrl] = useState("");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("auto");
  const [jobStatus, setJobStatus] = useState<DubbingStatus | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [estimatedProgress, setEstimatedProgress] = useState(0);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Load supported languages
  useEffect(() => {
    async function loadLanguages() {
      try {
        const data = await getDubbingLanguages();
        setLanguages(data.languages);
      } catch (error) {
        console.error("Failed to load languages:", error);
        toast.error("Failed to load supported languages");
      } finally {
        setLoadingLanguages(false);
      }
    }
    loadLanguages();
  }, []);

  // Poll for job status
  const pollStatus = useCallback(async (dubbingId: string) => {
    try {
      const status = await checkDubbingStatus(dubbingId);
      setJobStatus(status);

      if (status.status === "dubbed" || status.status === "failed") {
        // Stop polling
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        
        if (status.status === "dubbed") {
          toast.success("Dubbing complete! Ready to download.");
          setEstimatedProgress(100);
        } else {
          toast.error(`Dubbing failed: ${status.error || "Unknown error"}`);
        }
      } else {
        // Update progress estimate
        if (status.expected_duration_sec) {
          setEstimatedProgress((prev) => Math.min(prev + 5, 90));
        }
      }
    } catch (error) {
      console.error("Status check failed:", error);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith("video/")) {
        toast.error("Please select a video file");
        return;
      }
      if (file.size > 500 * 1024 * 1024) { // 500MB limit
        toast.error("File size must be under 500MB");
        return;
      }
      setVideoFile(file);
    }
  };

  const handleStart = async () => {
    if (!targetLanguage) {
      toast.error("Please select a target language");
      return;
    }

    if (inputMode === "url" && !videoUrl) {
      toast.error("Please enter a video URL");
      return;
    }

    if (inputMode === "upload" && !videoFile) {
      toast.error("Please upload a video file");
      return;
    }

    setIsStarting(true);
    setEstimatedProgress(0);
    const toastId = toast.loading("Starting dubbing job...", {
      description: "Uploading video to ElevenLabs",
    });

    try {
      const status = await startDubbingJob(
        targetLanguage,
        inputMode === "url" ? videoUrl : undefined,
        inputMode === "upload" ? videoFile || undefined : undefined,
        sourceLanguage === "auto" ? undefined : sourceLanguage
      );

      setJobStatus(status);
      toast.success("Dubbing started!", {
        id: toastId,
        description: `Expected duration: ${status.expected_duration_sec ? Math.ceil(status.expected_duration_sec / 60) + " minutes" : "calculating..."}`,
      });

      // Start polling
      pollIntervalRef.current = setInterval(() => {
        pollStatus(status.dubbing_id);
      }, 5000);
    } catch (error) {
      console.error("Start failed:", error);
      toast.error("Failed to start dubbing", { id: toastId });
    } finally {
      setIsStarting(false);
    }
  };

  const handleDownload = async () => {
    if (!jobStatus?.dubbing_id) return;

    setIsDownloading(true);
    const toastId = toast.loading("Downloading dubbed video...");

    try {
      const blob = await downloadDubbedVideo(jobStatus.dubbing_id);
      
      // Create download link
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dubbed_${jobStatus.target_language}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast.success("Download complete!", { id: toastId });
    } catch (error) {
      console.error("Download failed:", error);
      toast.error("Failed to download video", { id: toastId });
    } finally {
      setIsDownloading(false);
    }
  };

  const handleReset = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setJobStatus(null);
    setEstimatedProgress(0);
    setVideoUrl("");
    setVideoFile(null);
    setTargetLanguage("");
    setSourceLanguage("");
  };

  const getStatusIcon = () => {
    if (!jobStatus) return null;
    
    switch (jobStatus.status) {
      case "pending":
      case "dubbing":
        return <Loader2 className="h-5 w-5 animate-spin text-blue-500" />;
      case "dubbed":
        return <CheckCircle className="h-5 w-5 text-green-500" />;
      case "failed":
        return <XCircle className="h-5 w-5 text-red-500" />;
    }
  };

  const getStatusText = () => {
    if (!jobStatus) return "";
    
    switch (jobStatus.status) {
      case "pending":
        return "Initializing...";
      case "dubbing":
        return "Dubbing in progress...";
      case "dubbed":
        return "Complete - Ready to download";
      case "failed":
        return `Failed: ${jobStatus.error || "Unknown error"}`;
    }
  };

  return (
    <div className="container mx-auto px-6 py-8 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2 flex items-center gap-3">
          <Languages className="h-8 w-8 text-primary" />
          Voice Dubbing
        </h1>
        <p className="text-muted-foreground">
          Translate your video audio to 30+ languages with AI voice cloning
        </p>
      </div>

      {!jobStatus ? (
        <Card>
          <CardHeader>
            <CardTitle>Start Dubbing</CardTitle>
            <CardDescription>
              Upload a video or provide a URL to translate the audio
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Input Mode Tabs */}
            <Tabs value={inputMode} onValueChange={(v) => setInputMode(v as "url" | "upload")}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="url" className="flex items-center gap-2">
                  <LinkIcon className="h-4 w-4" />
                  URL
                </TabsTrigger>
                <TabsTrigger value="upload" className="flex items-center gap-2">
                  <Upload className="h-4 w-4" />
                  Upload
                </TabsTrigger>
              </TabsList>

              <TabsContent value="url" className="mt-4">
                <div className="space-y-2">
                  <Label htmlFor="video-url">Video URL (YouTube, etc.)</Label>
                  <Input
                    id="video-url"
                    placeholder="https://youtube.com/watch?v=..."
                    value={videoUrl}
                    onChange={(e) => setVideoUrl(e.target.value)}
                  />
                </div>
              </TabsContent>

              <TabsContent value="upload" className="mt-4">
                <div className="space-y-2">
                  <Label>Video File</Label>
                  <div
                    className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:bg-muted/50 transition-colors"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {videoFile ? (
                      <div className="flex items-center justify-center gap-2">
                        <CheckCircle className="h-5 w-5 text-green-500" />
                        <span>{videoFile.name}</span>
                        <Badge variant="secondary">
                          {(videoFile.size / 1024 / 1024).toFixed(1)} MB
                        </Badge>
                      </div>
                    ) : (
                      <>
                        <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                        <p className="text-muted-foreground">
                          Click to upload or drag and drop
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          MP4, MOV, WebM (max 500MB)
                        </p>
                      </>
                    )}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/*"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>
              </TabsContent>
            </Tabs>

            {/* Language Selection */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Target Language *</Label>
                <Select value={targetLanguage} onValueChange={setTargetLanguage}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select language..." />
                  </SelectTrigger>
                  <SelectContent>
                    {loadingLanguages ? (
                      <SelectItem value="loading" disabled>
                        Loading...
                      </SelectItem>
                    ) : (
                      languages.map((lang) => (
                        <SelectItem key={lang.code} value={lang.code}>
                          {lang.name}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Source Language (optional)</Label>
                <Select value={sourceLanguage} onValueChange={setSourceLanguage}>
                  <SelectTrigger>
                    <SelectValue placeholder="Auto-detect" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto-detect</SelectItem>
                    {languages.map((lang) => (
                      <SelectItem key={lang.code} value={lang.code}>
                        {lang.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Start Button */}
            <Button
              onClick={handleStart}
              disabled={isStarting || !targetLanguage}
              className="w-full"
              size="lg"
            >
              {isStarting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Languages className="mr-2 h-4 w-4" />
                  Start Dubbing
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {getStatusIcon()}
              Dubbing Status
            </CardTitle>
            <CardDescription>{getStatusText()}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Progress Bar */}
            {(jobStatus.status === "pending" || jobStatus.status === "dubbing") && (
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Progress</span>
                  <span>{estimatedProgress}%</span>
                </div>
                <Progress value={estimatedProgress} />
              </div>
            )}

            {/* Job Details */}
            <div className="grid grid-cols-2 gap-4 p-4 bg-muted/50 rounded-lg">
              <div>
                <p className="text-sm text-muted-foreground">Job ID</p>
                <p className="font-mono text-sm">{jobStatus.dubbing_id}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Target Language</p>
                <p className="font-medium">
                  {languages.find((l) => l.code === jobStatus.target_language)?.name || jobStatus.target_language}
                </p>
              </div>
              {jobStatus.source_language && (
                <div>
                  <p className="text-sm text-muted-foreground">Source Language</p>
                  <p className="font-medium">
                    {languages.find((l) => l.code === jobStatus.source_language)?.name || jobStatus.source_language}
                  </p>
                </div>
              )}
              {jobStatus.expected_duration_sec && (
                <div>
                  <p className="text-sm text-muted-foreground">Expected Duration</p>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4" />
                    {Math.ceil(jobStatus.expected_duration_sec / 60)} minutes
                  </p>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-4">
              {jobStatus.status === "dubbed" && (
                <Button onClick={handleDownload} disabled={isDownloading} className="flex-1">
                  {isDownloading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Downloading...
                    </>
                  ) : (
                    <>
                      <Download className="mr-2 h-4 w-4" />
                      Download Dubbed Video
                    </>
                  )}
                </Button>
              )}
              <Button variant="outline" onClick={handleReset} className="flex-1">
                Start New Translation
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Info Section */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-lg">How It Works</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="list-decimal list-inside space-y-2 text-muted-foreground">
            <li>Upload your video or provide a YouTube URL</li>
            <li>Select the target language for dubbing</li>
            <li>Our AI analyzes the audio and generates translated speech</li>
            <li>The original voice characteristics are preserved through AI cloning</li>
            <li>Download your dubbed video when complete</li>
          </ol>
          <p className="mt-4 text-sm text-muted-foreground">
            <strong>Note:</strong> Processing time varies based on video length. Typical processing is 2-5x the video duration.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

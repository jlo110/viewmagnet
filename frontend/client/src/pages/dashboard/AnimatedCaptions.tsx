/*
 * Animated Captions: 7 styles, word-by-word animations
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Upload,
  Download,
  Type,
  Settings,
  Wand2,
  Loader2,
  X,
  ChevronDown,
  ChevronUp,
  FileText,
  Video,
  Play,
  Eye,
} from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import { generateCaptions, exportCaptionedVideo } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";

const captionStyles = [
  {
    name: "capcut",
    label: "CapCut Style",
    description: "Bold word-by-word pop — the viral TikTok look",
    previewWords: [
      { text: "Each", highlight: false },
      { text: "WORD", highlight: true },
      { text: "pops", highlight: false },
      { text: "IN", highlight: true },
    ],
    popular: true,
    colors: ["#FFFFFF", "#00FF00"],
    font: "Montserrat",
  },
  {
    name: "mrbeast",
    label: "MrBeast Style",
    description: "Big, bold, yellow impact text",
    previewWords: [
      { text: "MASSIVE", highlight: true },
      { text: "Impact", highlight: false },
    ],
    popular: true,
    colors: ["#FFFF00", "#FF0000"],
    font: "Impact",
  },
  {
    name: "hormozi",
    label: "Hormozi Style",
    description: "Clean white with gold word highlights",
    previewWords: [
      { text: "Professional", highlight: false },
      { text: "HIGHLIGHT", highlight: true },
    ],
    popular: true,
    colors: ["#FFFFFF", "#FFD700"],
    font: "Inter",
  },
  {
    name: "tiktok",
    label: "TikTok Style",
    description: "White with pink bounce animation",
    previewWords: [
      { text: "Bouncy", highlight: false },
      { text: "playful", highlight: true },
      { text: "text", highlight: false },
    ],
    popular: false,
    colors: ["#FFFFFF", "#FF0050"],
    font: "Poppins",
  },
  {
    name: "gaming",
    label: "Gaming Style",
    description: "Neon cyan/magenta, futuristic feel",
    previewWords: [
      { text: "CYBER", highlight: true },
      { text: "NEON", highlight: true },
    ],
    popular: false,
    colors: ["#00FFFF", "#FF00FF"],
    font: "Oswald",
  },
  {
    name: "minimal",
    label: "Minimal Style",
    description: "Subtle, elegant fade animation",
    previewWords: [
      { text: "Clean", highlight: false },
      { text: "and", highlight: false },
      { text: "simple", highlight: true },
    ],
    popular: false,
    colors: ["#FFFFFF", "#AAAAAA"],
    font: "Inter",
  },
  {
    name: "educational",
    label: "Educational Style",
    description: "Readable, clean with green accents",
    previewWords: [
      { text: "Learn", highlight: false },
      { text: "with", highlight: false },
      { text: "clarity", highlight: true },
    ],
    popular: false,
    colors: ["#FFFFFF", "#4CAF50"],
    font: "Poppins",
  },
];

const fontOptions = [
  { value: "montserrat", label: "Montserrat Bold", fontFamily: "'Montserrat', sans-serif" },
  { value: "poppins", label: "Poppins Black", fontFamily: "'Poppins', sans-serif" },
  { value: "inter", label: "Inter Bold", fontFamily: "'Inter', sans-serif" },
  { value: "oswald", label: "Oswald Bold", fontFamily: "'Oswald', sans-serif" },
];

interface Caption {
  video: string;
  style: string;
  words: number;
  duration: string;
  date: string;
  srt_content?: string;
  ass_content?: string;
  html_preview?: string;
  video_url?: string;
  video_file?: File;
}

interface GeneratedCaptionResult {
  srt_content: string;
  ass_content: string;
  html_preview: string;
  word_count: number;
  style_used: string;
}

const GENERATION_STAGES = [
  { label: "Fetching video...", progress: 10 },
  { label: "Downloading audio...", progress: 25 },
  { label: "Transcribing with AI...", progress: 50 },
  { label: "Generating styled captions...", progress: 80 },
  { label: "Finalizing...", progress: 95 },
];

export default function AnimatedCaptions() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [transcript, setTranscript] = useState("");
  const [showTranscript, setShowTranscript] = useState(false);
  const [selectedStyle, setSelectedStyle] = useState(0);
  const [font, setFont] = useState("montserrat");
  const [position, setPosition] = useState("bottom");
  const [primaryColor, setPrimaryColor] = useState("white");
  const [secondaryColor, setSecondaryColor] = useState("cyan");
  const [size, setSize] = useState("large");
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [lastResult, setLastResult] = useState<GeneratedCaptionResult | null>(null);
  const [exportingIndex, setExportingIndex] = useState<number | null>(null);
  const [exportProgress, setExportProgress] = useState(0);
  const [genProgress, setGenProgress] = useState(0);
  const [genStage, setGenStage] = useState("");
  const [previewCaption, setPreviewCaption] = useState<Caption | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const genProgressInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const link = document.createElement("link");
    link.href = "https://fonts.googleapis.com/css2?family=Montserrat:wght@700&family=Poppins:wght@900&family=Inter:wght@700&family=Oswald:wght@700&display=swap";
    link.rel = "stylesheet";
    document.head.appendChild(link);
    return () => { document.head.removeChild(link); };
  }, []);

  const handleDownloadSRT = (caption: Caption) => {
    if (!caption.srt_content) {
      toast.error("No SRT content available");
      return;
    }
    
    const blob = new Blob([caption.srt_content], { type: "text/plain" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${caption.video.replace(/[^a-z0-9]/gi, "_")}_captions.srt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    toast.success("SRT file downloaded!");
  };

  const handleDownloadASS = (caption: Caption) => {
    if (!caption.ass_content) {
      toast.error("No ASS content available");
      return;
    }
    
    const blob = new Blob([caption.ass_content], { type: "text/plain" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${caption.video.replace(/[^a-z0-9]/gi, "_")}_captions.ass`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    toast.success("ASS file downloaded! (for FFmpeg burning)");
  };

  const handleExportMP4 = async (caption: Caption, index: number) => {
    if (!caption.ass_content) {
      toast.error("No caption data available");
      return;
    }
    
    if (!caption.video_url && !caption.video_file) {
      toast.error("Original video source not available. Please regenerate captions to export MP4.");
      return;
    }
    
    setExportingIndex(index);
    setExportProgress(0);
    toast.info("Processing video with captions... This may take 1-3 minutes.");
    
    const progressInterval = setInterval(() => {
      setExportProgress(prev => {
        if (prev >= 90) return prev;
        const increment = prev < 30 ? 8 : prev < 60 ? 4 : 2;
        return Math.min(prev + increment, 90);
      });
    }, 2000);
    
    try {
      const blob = await exportCaptionedVideo({
        assContent: caption.ass_content,
        videoUrl: caption.video_url,
        videoFile: caption.video_file,
      });
      
      clearInterval(progressInterval);
      setExportProgress(100);
      
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${caption.video.replace(/[^a-z0-9]/gi, "_")}_captioned.mp4`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("MP4 with captions downloaded!");
    } catch (error: unknown) {
      clearInterval(progressInterval);
      console.error("MP4 export failed:", error);
      let errorMessage = "Failed to export video";
      if (error && typeof error === 'object' && 'response' in error) {
        const axiosError = error as { response?: { data?: { detail?: string } } };
        errorMessage = axiosError.response?.data?.detail || errorMessage;
      } else if (error instanceof Error) {
        errorMessage = error.message;
      }
      toast.error(errorMessage);
    } finally {
      setExportingIndex(null);
      setExportProgress(0);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validTypes = ["video/mp4", "video/webm", "video/quicktime"];
      if (!validTypes.some(type => file.type.includes(type.split("/")[1]))) {
        toast.error("Please upload a valid video file (MP4, MOV, WebM)");
        return;
      }
      setVideoFile(file);
      setVideoUrl("");
      toast.success(`Video uploaded: ${file.name}`);
    }
  };

  const startProgressSimulation = (hasTranscript: boolean) => {
    setGenProgress(0);
    setGenStage(GENERATION_STAGES[0].label);
    
    if (hasTranscript) {
      setGenProgress(70);
      setGenStage("Generating styled captions...");
      return;
    }
    
    let stageIndex = 0;
    const avgDuration = 45000;
    const stageCount = GENERATION_STAGES.length;
    const stageInterval = avgDuration / stageCount;
    
    genProgressInterval.current = setInterval(() => {
      stageIndex++;
      if (stageIndex < stageCount) {
        setGenProgress(GENERATION_STAGES[stageIndex].progress);
        setGenStage(GENERATION_STAGES[stageIndex].label);
      }
    }, stageInterval);
  };

  const stopProgressSimulation = () => {
    if (genProgressInterval.current) {
      clearInterval(genProgressInterval.current);
      genProgressInterval.current = null;
    }
    setGenProgress(100);
    setGenStage("Complete!");
    setTimeout(() => {
      setGenProgress(0);
      setGenStage("");
    }, 1000);
  };

  const handleGenerate = async () => {
    if (!videoFile && !videoUrl.trim() && !transcript.trim()) {
      toast.error("Please upload a video, paste a URL, or enter a transcript");
      return;
    }
    
    setLoading(true);
    const hasTranscript = !!transcript.trim();
    startProgressSimulation(hasTranscript);
    
    const videoName = videoFile?.name?.replace(/\.[^/.]+$/, "") || 
      videoUrl.split("v=").pop()?.split("&")[0] || 
      "Transcript";
    
    try {
      const backendStyleName = captionStyles[selectedStyle].name;
      
      const result = await generateCaptions({
        video_url: videoUrl.trim() || undefined,
        transcript: transcript.trim() || undefined,
        style: backendStyleName,
        font: font,
        position: position,
        primary_color: primaryColor,
        secondary_color: secondaryColor,
      });
      
      setLastResult(result as GeneratedCaptionResult);
      
      const lastSegment = result.segments?.[result.segments.length - 1];
      const durationSeconds = lastSegment?.end || 0;
      const minutes = Math.floor(durationSeconds / 60);
      const seconds = Math.floor(durationSeconds % 60);
      
      const capturedVideoUrl = videoUrl.trim() || undefined;
      const capturedVideoFile = videoFile || undefined;
      
      const newCaption: Caption = {
        video: videoName,
        style: captionStyles[selectedStyle].label,
        words: result.word_count,
        duration: `${minutes}:${seconds.toString().padStart(2, '0')}`,
        date: "Just now",
        srt_content: (result as GeneratedCaptionResult).srt_content,
        ass_content: (result as GeneratedCaptionResult).ass_content,
        html_preview: (result as GeneratedCaptionResult).html_preview,
        video_url: capturedVideoUrl,
        video_file: capturedVideoFile,
      };
      
      setCaptions(prev => [newCaption, ...prev]);
      setVideoFile(null);
      setVideoUrl("");
      setTranscript("");
      toast.success(`Captions generated! ${result.word_count} words processed.`);
    } catch (error: unknown) {
      console.error("Caption generation failed:", error);
      
      let errorMessage = "Failed to generate captions";
      if (error && typeof error === 'object' && 'response' in error) {
        const axiosError = error as { response?: { data?: { detail?: string } } };
        errorMessage = axiosError.response?.data?.detail || errorMessage;
      } else if (error instanceof Error) {
        errorMessage = error.message;
      }
      
      toast.error(errorMessage);
    } finally {
      stopProgressSimulation();
      setLoading(false);
      setLoadingMessage("");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Animated Captions
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Add eye-catching word-by-word animated captions to your videos. 7 styles to choose from.
        </p>
      </div>

      {/* Upload */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5 space-y-4">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept="video/mp4,video/webm,video/quicktime,.mov,.mp4,.webm"
            className="hidden"
          />
          <div 
            className="border-2 border-dashed border-border/50 rounded-lg p-8 text-center hover:border-cyan-glow/30 transition-colors cursor-pointer"
            onClick={() => fileInputRef.current?.click()}
          >
            {videoFile ? (
              <div className="flex items-center justify-center gap-2">
                <span className="text-sm text-cyan-glow">{videoFile.name}</span>
                <button 
                  onClick={(e) => { e.stopPropagation(); setVideoFile(null); }}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <>
            <Upload className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
                <p className="text-sm font-medium text-foreground">Click to upload your video</p>
            <p className="text-xs text-muted-foreground mt-1">
              MP4, MOV, or WebM — up to 500MB
            </p>
              </>
            )}
          </div>
          <div className="text-center text-xs text-muted-foreground">or</div>
          <Input
            placeholder="Paste a YouTube video URL..."
            className="bg-secondary/50 border-border/50"
            value={videoUrl}
            onChange={(e) => { setVideoUrl(e.target.value); setVideoFile(null); setTranscript(""); }}
          />
          
          {/* Transcript Input Toggle */}
          <button
            type="button"
            onClick={() => setShowTranscript(!showTranscript)}
            className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors mx-auto"
          >
            <FileText className="w-3 h-3" />
            {showTranscript ? "Hide transcript input" : "Or paste transcript directly (faster)"}
            {showTranscript ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          
          {showTranscript && (
            <Textarea
              placeholder="Paste your video transcript here... (This is faster than video transcription)"
              className="bg-secondary/50 border-border/50 min-h-[100px]"
              value={transcript}
              onChange={(e) => { setTranscript(e.target.value); setVideoUrl(""); setVideoFile(null); }}
            />
          )}
        </CardContent>
      </Card>

      {/* Caption Styles */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3">Choose a Style</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {captionStyles.map((style, i) => (
            <Card
              key={style.name}
              className={`bg-card border-border/50 cursor-pointer transition-all hover:border-cyan-glow/30 ${
                i === selectedStyle ? "border-cyan-glow/50 ring-1 ring-cyan-glow/20" : ""
              }`}
              onClick={() => setSelectedStyle(i)}
            >
              <CardContent className="p-4">
                {/* Preview area with actual style colors and word-by-word */}
                <div 
                  className="h-24 rounded-lg border border-border/20 flex items-center justify-center mb-3 relative overflow-hidden px-3"
                  style={{ 
                    background: `linear-gradient(180deg, #0a0a0a 0%, #1a1a1a 100%)`,
                    borderColor: `${style.colors[0]}30`
                  }}
                >
                  <div className="flex flex-wrap items-center justify-center gap-1.5">
                    {style.previewWords.map((word, wi) => (
                      <span
                        key={wi}
                        className="text-base font-bold tracking-wide px-1"
                        style={{ 
                          fontFamily: style.font === "Impact" ? "Impact, sans-serif" : `'${style.font}', sans-serif`,
                          color: word.highlight ? style.colors[1] : style.colors[0],
                          textShadow: word.highlight 
                            ? `0 0 12px ${style.colors[1]}80, 0 0 20px ${style.colors[1]}40` 
                            : `2px 2px 0 #000`,
                          transform: word.highlight ? 'scale(1.1)' : 'scale(1)',
                          display: 'inline-block',
                        }}
                      >
                        {word.text}
                      </span>
                    ))}
                  </div>
                  {i === selectedStyle && (
                    <div className="absolute top-1.5 right-1.5">
                      <Badge className="bg-cyan-glow/20 text-cyan-glow border-cyan-glow/30 text-[8px]">
                        Selected
                      </Badge>
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">{style.label}</p>
                    <p className="text-[10px] text-muted-foreground">{style.description}</p>
                  </div>
                  {style.popular && (
                    <Badge variant="outline" className="text-[8px] border-amber-glow/30 text-amber-glow">
                      Popular
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Settings */}
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Settings className="w-4 h-4 text-muted-foreground" />
            Caption Settings
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Font
              </label>
              <Select value={font} onValueChange={setFont}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <span style={{ fontFamily: fontOptions.find(f => f.value === font)?.fontFamily }}>
                    {fontOptions.find(f => f.value === font)?.label}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {fontOptions.map((f) => (
                    <SelectItem key={f.value} value={f.value}>
                      <span style={{ fontFamily: f.fontFamily, fontWeight: 700 }}>
                        {f.label}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Position
              </label>
              <Select value={position} onValueChange={setPosition}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="top">Top</SelectItem>
                  <SelectItem value="center">Center</SelectItem>
                  <SelectItem value="bottom">Bottom</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Text Color
              </label>
              <Select value={primaryColor} onValueChange={setPrimaryColor}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="white">White</SelectItem>
                  <SelectItem value="cyan">Cyan</SelectItem>
                  <SelectItem value="yellow">Yellow</SelectItem>
                  <SelectItem value="green">Green</SelectItem>
                  <SelectItem value="pink">Pink</SelectItem>
                  <SelectItem value="orange">Orange</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Highlight Color
              </label>
              <Select value={secondaryColor} onValueChange={setSecondaryColor}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="cyan">Cyan</SelectItem>
                  <SelectItem value="yellow">Yellow</SelectItem>
                  <SelectItem value="green">Green</SelectItem>
                  <SelectItem value="red">Red</SelectItem>
                  <SelectItem value="pink">Pink</SelectItem>
                  <SelectItem value="orange">Orange</SelectItem>
                  <SelectItem value="purple">Purple</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Size
              </label>
              <Select value={size} onValueChange={setSize}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="small">Small</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="large">Large</SelectItem>
                  <SelectItem value="xlarge">Extra Large</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {loading ? (
            <div className="mt-4 space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{genStage}</span>
                <span>{genProgress}%</span>
              </div>
              <div className="h-2.5 bg-secondary/50 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-cyan-glow transition-all duration-700 ease-out"
                  style={{ width: `${genProgress}%` }}
                />
              </div>
              <p className="text-[10px] text-muted-foreground text-center">
                This may take 30-60 seconds for longer videos
              </p>
            </div>
          ) : (
            <Button 
              className="mt-4 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
              onClick={handleGenerate}
            >
              <Wand2 className="w-4 h-4 mr-2" />
              Generate Captions
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Recent */}
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">Generated Captions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {captions.length === 0 ? (
            <div className="p-6 text-center">
              <Type className="w-8 h-8 mx-auto text-muted-foreground/50 mb-2" />
              <p className="text-sm text-muted-foreground">
                Upload a video and generate captions to see them here
              </p>
            </div>
          ) : captions.map((cap, i) => (
            <div
              key={i}
              className="flex items-center justify-between p-3 rounded-lg bg-secondary/20 hover:bg-secondary/30 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                  <Type className="w-4 h-4 text-cyan-glow" />
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">{cap.video}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant="outline" className="text-[9px] border-border/50 text-muted-foreground">
                      {cap.style}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">{cap.words} words</span>
                    <span className="text-[10px] text-muted-foreground">{cap.duration}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted-foreground">{cap.date}</span>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="text-xs h-7"
                  onClick={() => setPreviewCaption(cap)}
                  disabled={!cap.html_preview}
                  title="Preview captions"
                >
                  <Eye className="w-3 h-3 mr-1" />
                  Preview
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="text-xs h-7"
                  onClick={() => handleDownloadSRT(cap)}
                  disabled={!cap.srt_content}
                >
                  <Download className="w-3 h-3 mr-1" />
                  SRT
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="text-xs h-7"
                  onClick={() => handleDownloadASS(cap)}
                  disabled={!cap.ass_content}
                >
                  <Download className="w-3 h-3 mr-1" />
                  ASS
                </Button>
                {exportingIndex === i ? (
                  <div className="flex items-center gap-2 min-w-[120px]">
                    <div className="flex-1 h-2 bg-secondary/50 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-cyan-glow transition-all duration-500 ease-out"
                        style={{ width: `${exportProgress}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-muted-foreground w-8">{exportProgress}%</span>
                  </div>
                ) : (
                  <Button 
                    variant="default" 
                    size="sm" 
                    className="text-xs h-7 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                    onClick={() => handleExportMP4(cap, i)}
                    disabled={!cap.ass_content || (!cap.video_url && !cap.video_file)}
                  >
                    <Video className="w-3 h-3 mr-1" />
                    MP4
                  </Button>
                )}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Preview Modal */}
      {previewCaption && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <div className="flex items-center gap-3">
                <Play className="w-5 h-5 text-cyan-glow" />
                <div>
                  <h3 className="font-semibold">Caption Preview</h3>
                  <p className="text-xs text-muted-foreground">{previewCaption.video} • {previewCaption.style}</p>
                </div>
              </div>
              <Button 
                variant="ghost" 
                size="sm"
                onClick={() => setPreviewCaption(null)}
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
            <div className="p-4">
              {previewCaption.html_preview ? (
                <>
                  <div className="bg-secondary/30 rounded-lg p-3 mb-3 flex items-center gap-2">
                    <Play className="w-4 h-4 text-cyan-glow" />
                    <p className="text-xs text-muted-foreground">
                      <strong>Click "Play" above</strong> to see word-by-word animation. Background is black for preview only.
                    </p>
                  </div>
                  <iframe
                    srcDoc={previewCaption.html_preview}
                    className="w-full h-[450px] rounded-lg border border-border/50"
                    title="Caption Preview"
                    sandbox="allow-scripts"
                  />
                </>
              ) : (
                <div className="bg-zinc-900 rounded-lg p-6 min-h-[400px] flex items-center justify-center">
                  <p className="text-muted-foreground text-center">No preview available</p>
                </div>
              )}
              <p className="text-xs text-muted-foreground text-center mt-4">
                Export as MP4 to see captions burned into your actual video.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

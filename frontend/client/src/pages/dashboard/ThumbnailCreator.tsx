/*
 * Thumbnail Creator: AI backgrounds, templates, face compositing
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Image,
  Upload,
  Sparkles,
  Download,
  Layers,
  Grid3X3,
  Wand2,
  Loader2,
  X,
  Check,
  User,
  DollarSign,
  ArrowLeftRight,
  Code,
  ListOrdered,
  AlertTriangle,
  Trophy,
  Clock,
  RefreshCw,
  Palette,
} from "lucide-react";
import { useState, useRef } from "react";
import { toast } from "sonner";
import { generateAIThumbnails, generateTemplateThumbnails, ThumbnailVariation } from "@/lib/api";

interface Template {
  name: string;
  style: string;
  description: string;
  score: number;
  colors: [string, string];
  icon: React.ReactNode;
}

const templates: Template[] = [
  { 
    name: "Face Reaction", 
    style: "Your face + bold text overlay",
    description: "High-converting format with expressive face and 2-3 word hook",
    score: 94, 
    colors: ["#FFB800", "#1a1a2e"],
    icon: <User className="w-6 h-6" />,
  },
  { 
    name: "Money Maker", 
    style: "Revenue numbers + success vibes",
    description: "Perfect for income reports, SaaS, and business content",
    score: 92, 
    colors: ["#00FF88", "#0D1117"],
    icon: <DollarSign className="w-6 h-6" />,
  },
  { 
    name: "VS Battle", 
    style: "Split comparison layout",
    description: "Side-by-side comparison with clear winner indication",
    score: 89, 
    colors: ["#FF4444", "#4488FF"],
    icon: <ArrowLeftRight className="w-6 h-6" />,
  },
  { 
    name: "Shocking Hook", 
    style: "Warning/alert attention grabber",
    description: "Creates urgency with warning elements and bold claims",
    score: 91, 
    colors: ["#FF3333", "#1a1a1a"],
    icon: <AlertTriangle className="w-6 h-6" />,
  },
  { 
    name: "Tech Dark", 
    style: "Clean code aesthetic",
    description: "Minimalist dark theme perfect for programming content",
    score: 86, 
    colors: ["#61DAFB", "#282c34"],
    icon: <Code className="w-6 h-6" />,
  },
  { 
    name: "Numbered List", 
    style: "Big number + icons",
    description: "Great for listicles and 'Top X' style videos",
    score: 87, 
    colors: ["#FF6B6B", "#4ECDC4"],
    icon: <ListOrdered className="w-6 h-6" />,
  },
  { 
    name: "Achievement", 
    style: "Trophy/milestone celebration",
    description: "Celebrate wins with gold accents and success imagery",
    score: 88, 
    colors: ["#FFD700", "#1a1a2e"],
    icon: <Trophy className="w-6 h-6" />,
  },
  { 
    name: "Speed Run", 
    style: "Timer + urgency elements",
    description: "Time-based content like challenges or quick tutorials",
    score: 85, 
    colors: ["#FF6B35", "#0D1117"],
    icon: <Clock className="w-6 h-6" />,
  },
];

interface GeneratedThumb {
  id: number;
  title: string;
  template: Template | null;
  variation: "bold" | "minimal" | "dramatic" | "clean";
  colors: [string, string];
  textPosition: "center" | "bottom" | "top" | "left";
  fontSize: "large" | "xlarge" | "medium";
  hasIcon: boolean;
  hasFace: boolean;
  faceUrl?: string;
  isAI?: boolean;
  imageUrl?: string; // Real AI-generated image URL
  promptUsed?: string;
}

const variationPresets = [
  { variation: "bold" as const, textPosition: "center" as const, fontSize: "xlarge" as const, hasIcon: true },
  { variation: "minimal" as const, textPosition: "bottom" as const, fontSize: "large" as const, hasIcon: false },
  { variation: "dramatic" as const, textPosition: "top" as const, fontSize: "xlarge" as const, hasIcon: true },
  { variation: "clean" as const, textPosition: "left" as const, fontSize: "medium" as const, hasIcon: false },
];

// Convert API response to our internal format
function apiVariationToThumb(
  v: ThumbnailVariation,
  title: string,
  template: Template | null,
  faceUrl?: string,
  isAI: boolean = false
): GeneratedThumb {
  const presetIndex = ["bold", "minimal", "dramatic", "clean"].indexOf(v.style);
  const preset = variationPresets[presetIndex >= 0 ? presetIndex : 0];
  const colors: [string, string] = v.colors 
    ? [v.colors[0], v.colors[1]] 
    : template?.colors || ["#00D4FF", "#0D1117"];
  
  return {
    id: v.id,
    title,
    template,
    colors,
    hasFace: !!faceUrl,
    faceUrl,
    isAI,
    imageUrl: v.image_url,
    promptUsed: v.prompt_used,
    ...preset,
  };
}

function getDisplayTitle(title: string, maxLength: number = 20): string {
  if (title.length <= maxLength) return title;
  const words = title.split(' ');
  let result = '';
  for (const word of words) {
    if ((result + ' ' + word).trim().length <= maxLength) {
      result = (result + ' ' + word).trim();
    } else {
      break;
    }
  }
  return result || title.substring(0, maxLength);
}

function extractHighlight(title: string): string {
  const moneyMatch = title.match(/\$[\d,]+[kKmM]?/);
  if (moneyMatch) return moneyMatch[0];
  const numMatch = title.match(/\d+/);
  if (numMatch) return numMatch[0];
  return title.split(' ').slice(0, 3).join(' ');
}

function ThumbnailPreview({ thumb, onDownload }: { thumb: GeneratedThumb; onDownload: () => void }) {
  const colors = thumb.colors;
  const highlight = extractHighlight(thumb.title);
  const displayTitle = getDisplayTitle(thumb.title, 25);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  
  // If we have a real AI-generated image URL, show it
  const hasRealImage = thumb.imageUrl && !imageError;

  const getLayout = () => {
    // If we have a real image, don't overlay text (the AI generated it with text)
    if (hasRealImage && imageLoaded) return null;
    
    switch (thumb.variation) {
      case "bold":
        return (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-3 text-center">
            {thumb.hasIcon && thumb.template?.icon && (
              <div 
                className="w-8 h-8 rounded-lg flex items-center justify-center mb-2"
                style={{ backgroundColor: colors[0] + "44", color: colors[0] }}
              >
                {thumb.template.icon}
              </div>
            )}
            <div 
              className="font-black text-lg leading-tight drop-shadow-lg"
              style={{ color: colors[0], textShadow: `2px 2px 4px ${colors[1]}` }}
            >
              {highlight}
            </div>
            <div className="text-[10px] text-white/80 mt-1 font-medium">
              {displayTitle !== highlight ? displayTitle.replace(highlight, '').trim() : ''}
            </div>
          </div>
        );
      case "minimal":
        return (
          <div className="absolute inset-0 flex flex-col justify-end p-3">
            <div className="text-sm font-bold leading-tight" style={{ color: colors[0] }}>
              {displayTitle}
            </div>
            <div className="w-12 h-1 rounded-full mt-2" style={{ backgroundColor: colors[0] }} />
          </div>
        );
      case "dramatic":
        return (
          <div className="absolute inset-0 flex flex-col p-3">
            <div 
              className="text-2xl font-black leading-none"
              style={{ color: colors[0], textShadow: `0 0 20px ${colors[0]}66` }}
            >
              {highlight}
            </div>
            {thumb.hasIcon && thumb.template?.icon && (
              <div 
                className="absolute bottom-3 right-3 w-10 h-10 rounded-full flex items-center justify-center"
                style={{ backgroundColor: colors[0], color: colors[1] }}
              >
                {thumb.template.icon}
              </div>
            )}
          </div>
        );
      case "clean":
        return (
          <div className="absolute inset-0 flex items-center p-3">
            <div className="flex-1">
              <div 
                className="text-xs font-bold uppercase tracking-wider mb-1"
                style={{ color: colors[0] + "aa" }}
              >
                {thumb.template?.name || "Custom AI"}
              </div>
              <div className="text-sm font-bold leading-tight" style={{ color: colors[0] }}>
                {displayTitle}
              </div>
            </div>
          </div>
        );
    }
  };

  const FaceOverlay = () => {
    if (!thumb.hasFace || !thumb.faceUrl) return null;
    // Don't show face overlay if we have a real AI image (face should be composited in)
    if (hasRealImage && imageLoaded) return null;
    
    const positions = {
      bold: "right-2 top-1/2 -translate-y-1/2",
      minimal: "right-2 top-2",
      dramatic: "left-2 bottom-2",
      clean: "right-2 top-1/2 -translate-y-1/2",
    };
    return (
      <div className={`absolute ${positions[thumb.variation]} w-12 h-12 rounded-full overflow-hidden border-2 shadow-lg`} style={{ borderColor: colors[0] }}>
        <img src={thumb.faceUrl} alt="Face" className="w-full h-full object-cover" />
      </div>
    );
  };

  return (
    <div 
      className="aspect-video rounded-lg relative overflow-hidden group cursor-pointer border border-border/30 hover:border-cyan-glow/50 transition-all hover:scale-[1.02]"
      style={{
        background: hasRealImage 
          ? 'transparent' 
          : `linear-gradient(${thumb.variation === 'dramatic' ? '180deg' : '135deg'}, ${colors[1]}, ${colors[0]}22)`,
      }}
    >
      {/* AI Generated Image */}
      {thumb.imageUrl && (
        <img 
          src={thumb.imageUrl}
          alt={`${thumb.variation} thumbnail variation`}
          className={`absolute inset-0 w-full h-full object-cover transition-opacity ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
          onLoad={() => setImageLoaded(true)}
          onError={() => setImageError(true)}
        />
      )}
      
      {/* Fallback gradient pattern if no image */}
      {(!hasRealImage || !imageLoaded) && (
        <div 
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: `linear-gradient(${colors[0]}22 1px, transparent 1px), linear-gradient(90deg, ${colors[0]}22 1px, transparent 1px)`,
            backgroundSize: '20px 20px',
          }}
        />
      )}
      
      {getLayout()}
      <FaceOverlay />
      
      {/* Badges */}
      <div className="absolute top-1 left-1 flex gap-1">
        <Badge className="text-[8px] px-1 py-0 h-4 bg-black/50 border-0 text-white/70 capitalize">
          {thumb.variation}
        </Badge>
        {thumb.isAI && (
          <Badge className="text-[8px] px-1 py-0 h-4 bg-purple-500/50 border-0 text-white/90">
            AI
          </Badge>
        )}
      </div>
      
      {/* Download overlay */}
      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
        <Button 
          size="sm" 
          className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 text-xs h-8 shadow-lg"
          onClick={(e) => { e.stopPropagation(); onDownload(); }}
        >
          <Download className="w-3 h-3 mr-1" />
          Download
        </Button>
      </div>
    </div>
  );
}

export default function ThumbnailCreator() {
  // Template tab state
  const [templateTitle, setTemplateTitle] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateResults, setTemplateResults] = useState<GeneratedThumb[]>([]);
  const [templateFaceFile, setTemplateFaceFile] = useState<File | null>(null);
  const [templateFacePreview, setTemplateFacePreview] = useState<string | null>(null);
  const [templateTextColor, setTemplateTextColor] = useState("#FFFFFF");
  const templateFaceInputRef = useRef<HTMLInputElement>(null);

  // AI tab state
  const [aiTitle, setAiTitle] = useState("");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiPrimaryColor, setAiPrimaryColor] = useState("#00D4FF");
  const [aiTextColor, setAiTextColor] = useState("#FFFFFF");
  const [faceFile, setFaceFile] = useState<File | null>(null);
  const [facePreview, setFacePreview] = useState<string | null>(null);
  const [bgFile, setBgFile] = useState<File | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResults, setAiResults] = useState<GeneratedThumb[]>([]);

  // Shared
  const [recentThumbnails, setRecentThumbnails] = useState<GeneratedThumb[]>([]);
  const faceInputRef = useRef<HTMLInputElement>(null);
  const bgInputRef = useRef<HTMLInputElement>(null);

  // Template face upload
  const handleTemplateFaceUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        toast.error("Please upload an image file");
        return;
      }
      setTemplateFaceFile(file);
      const url = URL.createObjectURL(file);
      setTemplateFacePreview(url);
      toast.success(`Face uploaded: ${file.name}`);
    }
  };

  const clearTemplateFace = () => {
    setTemplateFaceFile(null);
    if (templateFacePreview) {
      URL.revokeObjectURL(templateFacePreview);
      setTemplateFacePreview(null);
    }
  };

  // Template generation - uses backend API
  const handleTemplateGenerate = async () => {
    if (!templateTitle.trim()) {
      toast.error("Please enter a video title");
      return;
    }
    if (!selectedTemplate) {
      toast.error("Please select a template");
      return;
    }
    
    setTemplateLoading(true);
    try {
      // Convert face file to base64 if provided
      let faceBase64: string | undefined;
      if (templateFaceFile) {
        const reader = new FileReader();
        faceBase64 = await new Promise((resolve) => {
          reader.onload = () => resolve((reader.result as string).split(',')[1]);
          reader.readAsDataURL(templateFaceFile);
        });
      }

      const response = await generateTemplateThumbnails({
        title: templateTitle,
        template: selectedTemplate.name,
        category: "default",
        include_face: !!templateFaceFile,
        face_image_base64: faceBase64,
        primary_color: selectedTemplate.colors[0],
        text_color: templateTextColor,
        variations: 4,
      });
      
      const thumbs: GeneratedThumb[] = response.variations.map((v) => 
        apiVariationToThumb(v, templateTitle, selectedTemplate, templateFacePreview || undefined, false)
      );
      
      setTemplateResults(thumbs);
      setRecentThumbnails(prev => [thumbs[0], ...prev].slice(0, 8));
      toast.success(`Generated ${thumbs.length} "${selectedTemplate.name}" thumbnails!`);
    } catch (error: any) {
      console.error("Template generation failed:", error);
      toast.error(error.message || "Failed to generate thumbnails");
    } finally {
      setTemplateLoading(false);
    }
  };

  // AI generation - uses backend API with full customization
  const handleAIGenerate = async () => {
    if (!aiTitle.trim()) {
      toast.error("Please enter a video title");
      return;
    }
    if (!aiPrompt.trim()) {
      toast.error("Please describe the thumbnail style");
      return;
    }
    
    setAiLoading(true);
    try {
      // Convert files to base64 if provided
      let faceBase64: string | undefined;
      let bgBase64: string | undefined;
      
      if (faceFile) {
        const reader = new FileReader();
        faceBase64 = await new Promise((resolve) => {
          reader.onload = () => resolve((reader.result as string).split(',')[1]);
          reader.readAsDataURL(faceFile);
        });
      }
      
      if (bgFile) {
        const reader = new FileReader();
        bgBase64 = await new Promise((resolve) => {
          reader.onload = () => resolve((reader.result as string).split(',')[1]);
          reader.readAsDataURL(bgFile);
        });
      }

      const response = await generateAIThumbnails({
        title: aiTitle,
        style_description: aiPrompt,
        category: "default",
        include_face: !!faceFile,
        face_image_base64: faceBase64,
        background_image_base64: bgBase64,
        primary_color: aiPrimaryColor,
        text_color: aiTextColor,
        variations: 4,
      });
      
      const thumbs: GeneratedThumb[] = response.variations.map((v) => 
        apiVariationToThumb(v, aiTitle, null, facePreview || undefined, true)
      );
      
      setAiResults(thumbs);
      setRecentThumbnails(prev => [thumbs[0], ...prev].slice(0, 8));
      toast.success(`AI generated ${thumbs.length} custom thumbnails!`);
    } catch (error: any) {
      console.error("AI generation failed:", error);
      toast.error(error.message || "Failed to generate thumbnails");
    } finally {
      setAiLoading(false);
    }
  };

  const handleFaceUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        toast.error("Please upload an image file");
        return;
      }
      setFaceFile(file);
      const url = URL.createObjectURL(file);
      setFacePreview(url);
      toast.success(`Face uploaded: ${file.name}`);
    }
  };

  const handleBgUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        toast.error("Please upload an image file");
        return;
      }
      setBgFile(file);
      toast.success(`Background uploaded: ${file.name}`);
    }
  };

  const clearFace = () => {
    setFaceFile(null);
    if (facePreview) {
      URL.revokeObjectURL(facePreview);
      setFacePreview(null);
    }
  };

  const handleDownload = (thumb: GeneratedThumb) => {
    toast.success(`Downloading "${thumb.variation}" variation...`);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Thumbnail Creator
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Create click-worthy thumbnails with templates or custom AI generation.
        </p>
      </div>

      <Tabs defaultValue="templates" className="space-y-6">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="templates" className="gap-1.5">
            <Grid3X3 className="w-3.5 h-3.5" />
            Templates
          </TabsTrigger>
          <TabsTrigger value="ai" className="gap-1.5">
            <Wand2 className="w-3.5 h-3.5" />
            Custom AI
          </TabsTrigger>
          <TabsTrigger value="recent" className="gap-1.5">
            <Layers className="w-3.5 h-3.5" />
            Recent
            {recentThumbnails.length > 0 && (
              <Badge className="ml-1 bg-secondary text-muted-foreground text-[9px] px-1.5">
                {recentThumbnails.length}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Templates Tab - Quick Generation */}
        <TabsContent value="templates" className="space-y-6">
          {/* Title + Face Input */}
          <Card className="bg-card border-border/50">
            <CardContent className="p-4">
              <div className="flex gap-3 items-end">
                <div className="flex-1">
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Video Title
                  </label>
                  <Input
                    placeholder="e.g., I Built a $10K/mo SaaS in 30 Days"
                    className="bg-secondary/50 border-border/50"
                    value={templateTitle}
                    onChange={(e) => setTemplateTitle(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Text Color
                  </label>
                  <div className="flex gap-1.5 items-center">
                    <input 
                      type="color" 
                      value={templateTextColor}
                      onChange={(e) => setTemplateTextColor(e.target.value)}
                      className="w-10 h-10 rounded cursor-pointer border-0"
                    />
                    {["#FFFFFF", "#FFFF00", "#00FF88", "#FF4444", "#00D4FF"].map(color => (
                      <button
                        key={color}
                        className={`w-6 h-6 rounded-full transition-transform hover:scale-110 ${templateTextColor === color ? 'ring-2 ring-cyan-glow ring-offset-1 ring-offset-background' : ''}`}
                        style={{ backgroundColor: color, border: color === "#FFFFFF" ? "1px solid #444" : "none" }}
                        onClick={() => setTemplateTextColor(color)}
                      />
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Your Face
                  </label>
                  <input
                    type="file"
                    ref={templateFaceInputRef}
                    onChange={handleTemplateFaceUpload}
                    accept="image/*"
                    className="hidden"
                  />
                  <div 
                    className="border-2 border-dashed border-border/50 rounded-lg px-3 h-10 flex items-center justify-center hover:border-cyan-glow/30 transition-colors cursor-pointer min-w-[100px]"
                    onClick={() => templateFaceInputRef.current?.click()}
                  >
                    {templateFacePreview ? (
                      <div className="flex items-center gap-2">
                        <img src={templateFacePreview} alt="Face" className="w-6 h-6 rounded-full object-cover border border-cyan-glow" />
                        <span className="text-[10px] text-cyan-glow">Ready</span>
                        <button onClick={(e) => { e.stopPropagation(); clearTemplateFace(); }}>
                          <X className="w-3 h-3 text-muted-foreground hover:text-foreground" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <User className="w-4 h-4 text-muted-foreground" />
                        <span className="text-[10px] text-muted-foreground">+ Add</span>
                      </div>
                    )}
                  </div>
                </div>
                <Button 
                  className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold px-6"
                  onClick={handleTemplateGenerate}
                  disabled={templateLoading || !selectedTemplate}
                >
                  {templateLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4 mr-2" />
                      Generate
                    </>
                  )}
                </Button>
              </div>
              {!selectedTemplate && templateTitle && (
                <p className="text-[10px] text-amber-400 mt-2">
                  ↓ Select a template below to generate
                </p>
              )}
            </CardContent>
          </Card>

          {/* Template Grid */}
          <div>
            <h3 className="text-sm font-medium mb-3">Choose a Template</h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {templates.map((tmpl) => (
                <Card 
                  key={tmpl.name} 
                  className={`bg-card border-border/50 hover:border-cyan-glow/30 transition-all cursor-pointer ${
                    selectedTemplate?.name === tmpl.name ? "ring-2 ring-cyan-glow border-cyan-glow/50" : ""
                  }`}
                  onClick={() => setSelectedTemplate(tmpl)}
                >
                  <CardContent className="p-0">
                    <div
                      className="h-24 rounded-t-lg relative overflow-hidden"
                      style={{ background: `linear-gradient(135deg, ${tmpl.colors[0]}33, ${tmpl.colors[1]})` }}
                  >
                    <div className="absolute inset-0 flex items-center justify-center">
                        <div
                          className="w-12 h-12 rounded-xl flex items-center justify-center"
                          style={{ backgroundColor: tmpl.colors[0] + "44", color: tmpl.colors[0] }}
                        >
                          {tmpl.icon}
                        </div>
                      </div>
                      {selectedTemplate?.name === tmpl.name && (
                        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-cyan-glow flex items-center justify-center">
                          <Check className="w-3 h-3 text-deep-charcoal" />
                    </div>
                      )}
                    </div>
                    <div className="p-2">
                    <div className="flex items-center justify-between">
                        <p className="text-xs font-semibold">{tmpl.name}</p>
                      <Badge
                        variant="outline"
                          className={`text-[8px] px-1 ${
                            tmpl.score >= 90 ? "border-emerald-400/30 text-emerald-400" : "border-border/50 text-muted-foreground"
                          }`}
                        >
                          {tmpl.score}%
                      </Badge>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
          </div>

          {/* Template Results */}
          {templateResults.length > 0 && (
            <Card className="bg-card border-border/50">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold">
                    Generated from "{selectedTemplate?.name}"
                  </CardTitle>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    className="text-xs h-7"
                    onClick={() => { setTemplateResults([]); handleTemplateGenerate(); }}
                    disabled={templateLoading}
                  >
                    <RefreshCw className={`w-3 h-3 mr-1 ${templateLoading ? 'animate-spin' : ''}`} />
                    Regenerate
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {templateResults.map((thumb) => (
                    <ThumbnailPreview 
                      key={thumb.id} 
                      thumb={thumb} 
                      onDownload={() => handleDownload(thumb)}
                    />
                  ))}
                </div>
                <div className="mt-3 flex justify-end">
                  <Button 
                    variant="outline" 
                    size="sm" 
                    className="text-xs"
                    onClick={() => templateResults.forEach(t => handleDownload(t))}
                  >
                    <Download className="w-3 h-3 mr-1" />
                    Download All
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Custom AI Tab */}
        <TabsContent value="ai">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card className="bg-card border-border/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Wand2 className="w-4 h-4 text-purple-400" />
                  AI Generation
                </CardTitle>
                <p className="text-[10px] text-muted-foreground">
                  Describe exactly what you want — AI creates it from scratch
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Video Title *
                  </label>
                  <Input
                    placeholder="e.g., 5 AI Tools That Will Replace Your Job"
                    className="bg-secondary/50 border-border/50"
                    value={aiTitle}
                    onChange={(e) => setAiTitle(e.target.value)}
                  />
                </div>
                
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Style Description *
                  </label>
                  <Textarea
                    placeholder="e.g., Futuristic dark theme with glowing AI brain, robot hand reaching toward viewer, neon purple and cyan accents, dramatic lighting, tech aesthetic..."
                    className="bg-secondary/50 border-border/50 min-h-[80px] text-sm"
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Primary Color
                    </label>
                    <div className="flex gap-2">
                      <input 
                        type="color" 
                        value={aiPrimaryColor}
                        onChange={(e) => setAiPrimaryColor(e.target.value)}
                        className="w-10 h-10 rounded cursor-pointer border-0"
                      />
                      <div className="flex-1 flex flex-wrap gap-1">
                        {["#00D4FF", "#FF4444", "#00FF88", "#FFB800", "#FF66FF", "#8B5CF6"].map(color => (
                          <button
                            key={color}
                            className={`w-6 h-6 rounded-full transition-transform hover:scale-110 ${aiPrimaryColor === color ? 'ring-2 ring-white ring-offset-1 ring-offset-background' : ''}`}
                            style={{ backgroundColor: color }}
                            onClick={() => setAiPrimaryColor(color)}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Text Color
                    </label>
                    <div className="flex gap-2">
                      <input 
                        type="color" 
                        value={aiTextColor}
                        onChange={(e) => setAiTextColor(e.target.value)}
                        className="w-10 h-10 rounded cursor-pointer border-0"
                      />
                      <div className="flex-1 flex flex-wrap gap-1">
                        {["#FFFFFF", "#FFFF00", "#00FF88", "#FF4444", "#000000"].map(color => (
                          <button
                            key={color}
                            className={`w-6 h-6 rounded-full transition-transform hover:scale-110 ${aiTextColor === color ? 'ring-2 ring-cyan-glow ring-offset-1 ring-offset-background' : ''}`}
                            style={{ backgroundColor: color, border: color === "#FFFFFF" || color === "#FFFF00" ? "1px solid #444" : "none" }}
                            onClick={() => setAiTextColor(color)}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                      Your Face
                    </label>
                    <input
                      type="file"
                      ref={faceInputRef}
                      onChange={handleFaceUpload}
                      accept="image/*"
                      className="hidden"
                    />
                    <div 
                      className="border-2 border-dashed border-border/50 rounded-lg p-2 text-center hover:border-cyan-glow/30 transition-colors cursor-pointer h-10 flex items-center justify-center"
                      onClick={() => faceInputRef.current?.click()}
                    >
                      {facePreview ? (
                        <div className="flex items-center gap-2">
                          <img src={facePreview} alt="Face" className="w-6 h-6 rounded-full object-cover" />
                          <span className="text-[10px] text-cyan-glow">Uploaded</span>
                          <button onClick={(e) => { e.stopPropagation(); clearFace(); }}>
                            <X className="w-3 h-3 text-muted-foreground hover:text-foreground" />
                          </button>
                        </div>
                      ) : (
                        <span className="text-[10px] text-muted-foreground">+ Add face</span>
                      )}
                    </div>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    Background Image (optional)
                  </label>
                  <input
                    type="file"
                    ref={bgInputRef}
                    onChange={handleBgUpload}
                    accept="image/*"
                    className="hidden"
                  />
                  <div 
                    className="border-2 border-dashed border-border/50 rounded-lg p-3 text-center hover:border-cyan-glow/30 transition-colors cursor-pointer"
                    onClick={() => bgInputRef.current?.click()}
                  >
                    {bgFile ? (
                      <div className="flex items-center justify-center gap-2">
                        <Image className="w-4 h-4 text-cyan-glow" />
                        <span className="text-xs text-cyan-glow">{bgFile.name}</span>
                        <button onClick={(e) => { e.stopPropagation(); setBgFile(null); }}>
                          <X className="w-3 h-3 text-muted-foreground hover:text-foreground" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center gap-2">
                        <Upload className="w-4 h-4 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Upload custom background</span>
                      </div>
                    )}
                  </div>
                </div>

                <Button 
                  className="w-full bg-gradient-to-r from-purple-500 to-cyan-500 text-white hover:from-purple-600 hover:to-cyan-600 font-semibold h-11"
                  onClick={handleAIGenerate}
                  disabled={aiLoading}
                >
                  {aiLoading ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                  <Sparkles className="w-4 h-4 mr-2" />
                  )}
                  {aiLoading ? "AI is creating..." : "Generate with AI"}
                </Button>
              </CardContent>
            </Card>

            {/* AI Results */}
            <Card className="bg-card border-border/50">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold">AI Generated</CardTitle>
                  {aiResults.length > 0 && (
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      className="text-xs h-7"
                      onClick={() => { setAiResults([]); handleAIGenerate(); }}
                      disabled={aiLoading}
                    >
                      <RefreshCw className={`w-3 h-3 mr-1 ${aiLoading ? 'animate-spin' : ''}`} />
                      Regenerate
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {aiResults.length === 0 ? (
                  <div className="p-8 text-center">
                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-purple-500/20 to-cyan-500/20 flex items-center justify-center mx-auto mb-4">
                      <Wand2 className="w-8 h-8 text-purple-400/50" />
                    </div>
                    <p className="text-sm text-muted-foreground mb-2">
                      AI-generated thumbnails will appear here
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      Describe your vision and let AI create unique designs
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      {aiResults.map((thumb) => (
                        <ThumbnailPreview 
                          key={thumb.id} 
                          thumb={thumb} 
                          onDownload={() => handleDownload(thumb)}
                        />
                  ))}
                </div>
                    <div className="mt-3 flex items-center justify-between">
                      <p className="text-[10px] text-muted-foreground">
                        <span className="text-purple-400">AI</span> • 4 unique variations
                      </p>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        className="text-xs"
                        onClick={() => aiResults.forEach(t => handleDownload(t))}
                      >
                        <Download className="w-3 h-3 mr-1" />
                        Download All
                      </Button>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Recent */}
        <TabsContent value="recent">
          {recentThumbnails.length === 0 ? (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-8 text-center">
                <Layers className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Your generated thumbnails will appear here
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {recentThumbnails.map((thumb) => (
                <Card key={thumb.id} className="bg-card border-border/50 hover:border-border transition-colors">
                  <CardContent className="p-3">
                    <ThumbnailPreview 
                      thumb={thumb} 
                      onDownload={() => handleDownload(thumb)}
                    />
                    <div className="mt-2">
                      <p className="text-xs font-medium truncate">{thumb.title}</p>
                      <div className="flex items-center gap-1 mt-1">
                        {thumb.isAI ? (
                          <Badge className="text-[8px] px-1 bg-purple-500/20 text-purple-400 border-0">AI</Badge>
                        ) : (
                          <Badge variant="outline" className="text-[8px] px-1 border-border/50 text-muted-foreground">
                            {thumb.template?.name}
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-[8px] px-1 border-border/50 text-muted-foreground capitalize">
                          {thumb.variation}
                        </Badge>
                  </div>
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

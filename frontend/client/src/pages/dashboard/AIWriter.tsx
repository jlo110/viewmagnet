/*
 * AI Writer: Descriptions, tags, hooks with LLM
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  Hash,
  MessageSquare,
  AlignLeft,
  RefreshCw,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { generateAIContent } from "@/lib/api";

interface Hook {
  hook: string;
  style: string;
  score: number;
}

export default function AIWriter() {
  const [title, setTitle] = useState("");
  const [tone, setTone] = useState("professional");
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [generated, setGenerated] = useState(false);
  
  // Generated content state
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);

  const handleGenerateAll = async () => {
    if (!title.trim()) {
      toast.error("Please enter a video title");
      return;
    }
    setLoading(true);
    
    try {
      const result = await generateAIContent({
        title,
        category: "general",
        tone,
      });

      setDescription(result.description.text);
      setTags(result.tags.tags);
      setHooks(
        result.hooks.map((h) => ({ hook: h.text, style: h.style, score: h.score }))
      );
      setGenerated(true);
      toast.success("Content generated successfully!");
    } catch (error) {
      console.error("AI content generation failed:", error);
      setGenerated(false);
      toast.error("Couldn't generate content right now. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleRegenerateDescription = async () => {
    if (!title.trim()) return;
    setLoading(true);
    try {
      const result = await generateAIContent({ title, category: "general", tone });
      setDescription(result.description.text);
      toast.success("Description regenerated!");
    } catch (error) {
      console.error("Description regeneration failed:", error);
      toast.error("Couldn't regenerate description. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedField(null), 2000);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          AI Writer
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Generate optimized descriptions, tags, and hooks powered by AI and your niche data.
        </p>
      </div>

      {/* Input */}
      <Card className="bg-card border-border/50">
        <CardContent className="p-5">
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Video Title
              </label>
              <Input
                placeholder="Enter your video title..."
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="bg-secondary/50 border-border/50 h-11"
              />
            </div>
            <div className="w-40">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Tone
              </label>
              <Select value={tone} onValueChange={setTone}>
                <SelectTrigger className="bg-secondary/50 border-border/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="professional">Professional</SelectItem>
                  <SelectItem value="casual">Casual</SelectItem>
                  <SelectItem value="energetic">Energetic</SelectItem>
                  <SelectItem value="educational">Educational</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button 
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold h-11 px-6"
              onClick={handleGenerateAll}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
              <Sparkles className="w-4 h-4 mr-2" />
              )}
              {loading ? "Generating..." : "Generate All"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="description" className="space-y-4">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="description" className="gap-1.5">
            <AlignLeft className="w-3.5 h-3.5" />
            Description
          </TabsTrigger>
          <TabsTrigger value="tags" className="gap-1.5">
            <Hash className="w-3.5 h-3.5" />
            Tags
          </TabsTrigger>
          <TabsTrigger value="hooks" className="gap-1.5">
            <MessageSquare className="w-3.5 h-3.5" />
            Hooks
          </TabsTrigger>
        </TabsList>

        {/* Description */}
        <TabsContent value="description">
          <Card className="bg-card border-border/50">
            {!generated ? (
              <CardContent className="p-8 text-center">
                <AlignLeft className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Enter a video title and click "Generate All" to create an optimized description
                </p>
              </CardContent>
            ) : (
              <>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold">Generated Description</CardTitle>
                <div className="flex gap-2">
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        className="text-xs text-muted-foreground"
                        onClick={handleRegenerateDescription}
                        disabled={loading}
                      >
                        {loading ? (
                          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        ) : (
                    <RefreshCw className="w-3 h-3 mr-1" />
                        )}
                    Regenerate
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs"
                        onClick={() => handleCopy(description, "desc")}
                  >
                    {copiedField === "desc" ? (
                      <Check className="w-3 h-3 mr-1 text-emerald-400" />
                    ) : (
                      <Copy className="w-3 h-3 mr-1" />
                    )}
                    Copy
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="p-4 rounded-lg bg-secondary/30 border border-border/30">
                <pre className="text-sm text-foreground whitespace-pre-wrap font-[var(--font-body)] leading-relaxed">
                      {description}
                </pre>
              </div>
              <div className="flex items-center gap-3 mt-3">
                <Badge variant="outline" className="text-[10px] border-cyan-glow/20 text-cyan-glow">
                  SEO Optimized
                </Badge>
                <Badge variant="outline" className="text-[10px] border-border/50 text-muted-foreground">
                      {description.length} chars
                </Badge>
                <Badge variant="outline" className="text-[10px] border-emerald-400/20 text-emerald-400">
                  Timestamps included
                </Badge>
              </div>
            </CardContent>
              </>
            )}
          </Card>
        </TabsContent>

        {/* Tags */}
        <TabsContent value="tags">
          <Card className="bg-card border-border/50">
            {!generated ? (
              <CardContent className="p-8 text-center">
                <Hash className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Enter a video title and click "Generate All" to create optimized tags
                </p>
              </CardContent>
            ) : (
              <>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold">Generated Tags</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs"
                      onClick={() => handleCopy(tags.join(", "), "tags")}
                >
                  {copiedField === "tags" ? (
                    <Check className="w-3 h-3 mr-1 text-emerald-400" />
                  ) : (
                    <Copy className="w-3 h-3 mr-1" />
                  )}
                  Copy All
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                    {tags.map((tag, i) => (
                  <Badge
                    key={tag}
                    variant="outline"
                    className={`text-xs cursor-pointer hover:bg-cyan-glow/10 transition-colors ${
                      i < 5
                        ? "border-cyan-glow/30 text-cyan-glow"
                        : "border-border/50 text-muted-foreground"
                    }`}
                    onClick={() => handleCopy(tag, `tag-${i}`)}
                  >
                    #{tag}
                  </Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-3">
                    Top 5 tags highlighted based on search volume. {tags.length} tags total — YouTube allows up to 500 characters.
              </p>
            </CardContent>
              </>
            )}
          </Card>
        </TabsContent>

        {/* Hooks */}
        <TabsContent value="hooks">
          {!generated ? (
            <Card className="bg-card border-border/50">
              <CardContent className="p-8 text-center">
                <MessageSquare className="w-10 h-10 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">
                  Enter a video title and click "Generate All" to create engaging hooks
                </p>
              </CardContent>
            </Card>
          ) : (
          <div className="space-y-3">
              {hooks.map((item, i) => (
              <Card key={i} className="bg-card border-border/50">
                <CardContent className="p-4">
                  <div className="flex items-start gap-4">
                    <div
                      className={`w-11 h-11 rounded-lg flex items-center justify-center shrink-0 font-bold font-[var(--font-display)] text-sm ${
                        item.score >= 90
                          ? "bg-emerald-400/10 text-emerald-400"
                          : item.score >= 85
                          ? "bg-cyan-glow/10 text-cyan-glow"
                          : "bg-amber-glow/10 text-amber-glow"
                      }`}
                    >
                      {item.score}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm text-foreground leading-relaxed italic">
                        "{item.hook}"
                      </p>
                      <Badge
                        variant="outline"
                        className="text-[10px] border-border/50 text-muted-foreground mt-2"
                      >
                        {item.style}
                      </Badge>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="shrink-0 h-8 w-8"
                      onClick={() => handleCopy(item.hook, `hook-${i}`)}
                    >
                      {copiedField === `hook-${i}` ? (
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

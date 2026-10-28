/**
 * Voiceover Generator Page
 *
 * Text-to-speech via ElevenLabs. Pick a voice, enter text,
 * generate an MP3, then play or download it in-browser.
 */
import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
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
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  Mic,
  Download,
  Play,
  Pause,
  RefreshCw,
  Volume2,
  DollarSign,
} from "lucide-react";
import { toast } from "sonner";
import { getVoiceoverVoices, generateVoiceover, type VoiceInfo } from "@/lib/api";

interface CostEstimate {
  character_count: number;
  estimated_cost_usd: number;
  estimated_duration_seconds: number;
}

const CONTENT_TYPES = [
  { value: "general", label: "General" },
  { value: "tutorial", label: "Tutorial" },
  { value: "story", label: "Storytelling" },
  { value: "meditation", label: "Meditation" },
  { value: "professional", label: "Professional" },
  { value: "energetic", label: "Energetic" },
];

export default function Voiceover() {
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(true);

  const [text, setText] = useState("");
  const [selectedVoice, setSelectedVoice] = useState("21m00Tcm4TlvDq8ikWAM");
  const [stability, setStability] = useState(0.5);
  const [similarityBoost, setSimilarityBoost] = useState(0.75);
  const [contentType, setContentType] = useState("general");

  const [isGenerating, setIsGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Load available voices
  useEffect(() => {
    async function loadVoices() {
      try {
        const voices = await getVoiceoverVoices();
        setVoices(voices);
        if (voices.length > 0) {
          setSelectedVoice(voices[0].voice_id);
        }
      } catch {
        toast.error("Failed to load voices — using defaults");
      } finally {
        setLoadingVoices(false);
      }
    }
    loadVoices();
  }, []);

  // Live cost estimate whenever text changes
  useEffect(() => {
    if (!text.trim()) {
      setEstimate(null);
      return;
    }
    const charCount = text.length;
    setEstimate({
      character_count: charCount,
      estimated_cost_usd: parseFloat((charCount * 0.00018).toFixed(4)),
      estimated_duration_seconds: parseFloat((charCount / 15).toFixed(1)),
    });
  }, [text]);

  // Cleanup audio URL on unmount
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  async function handleGenerate() {
    if (!text.trim()) {
      toast.error("Enter some text to generate voiceover");
      return;
    }
    setIsGenerating(true);
    setAudioUrl(null);
    setIsPlaying(false);

    try {
      const blob = await generateVoiceover({
        text,
        voice_id: selectedVoice,
        stability,
        similarity_boost: similarityBoost,
      });
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);

      if (audioRef.current) {
        audioRef.current.src = url;
        audioRef.current.load();
      }
      toast.success("Voiceover generated");
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ??
        err?.message ??
        "Failed to generate voiceover";
      toast.error(msg);
    } finally {
      setIsGenerating(false);
    }
  }

  function togglePlay() {
    if (!audioRef.current || !audioUrl) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  }

  function handleDownload() {
    if (!audioUrl) return;
    const a = document.createElement("a");
    a.href = audioUrl;
    a.download = "voiceover.mp3";
    a.click();
  }

  const selectedVoiceInfo = voices.find((v) => v.voice_id === selectedVoice);

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/20">
            <Mic className="w-5 h-5 text-purple-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Voiceover Generator</h1>
          <Badge variant="outline" className="text-purple-400 border-purple-500/30">
            ElevenLabs
          </Badge>
        </div>
        <p className="text-slate-400">
          Convert your script to professional AI voiceover audio. Pick a voice,
          fine-tune settings, then download the MP3.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Script input ───────────────────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader>
              <CardTitle className="text-base text-white">Script</CardTitle>
              <CardDescription className="text-slate-400">
                Paste your script or type directly. Ideal length: 100–500 words.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Textarea
                placeholder="Welcome to this video. Today we're going to explore..."
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="min-h-[220px] bg-slate-800/50 border-slate-600 text-white placeholder:text-slate-500 resize-none"
              />
              <div className="flex items-center justify-between mt-2 text-xs text-slate-500">
                <span>{text.length} characters</span>
                {estimate && (
                  <span className="flex items-center gap-1">
                    <DollarSign className="w-3 h-3" />
                    ~${estimate.estimated_cost_usd} · ~{Math.round(estimate.estimated_duration_seconds)}s
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Playback */}
          {audioUrl && (
            <Card className="bg-slate-900/50 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-base text-white flex items-center gap-2">
                  <Volume2 className="w-4 h-4 text-green-400" />
                  Generated Audio
                </CardTitle>
              </CardHeader>
              <CardContent>
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <audio
                  ref={audioRef}
                  onEnded={() => setIsPlaying(false)}
                  className="hidden"
                />
                <div className="flex items-center gap-3">
                  <Button
                    onClick={togglePlay}
                    variant="outline"
                    className="border-slate-600 text-white hover:bg-slate-800"
                  >
                    {isPlaying ? (
                      <><Pause className="w-4 h-4 mr-2" /> Pause</>
                    ) : (
                      <><Play className="w-4 h-4 mr-2" /> Play</>
                    )}
                  </Button>
                  <Button
                    onClick={handleDownload}
                    variant="outline"
                    className="border-slate-600 text-white hover:bg-slate-800"
                  >
                    <Download className="w-4 h-4 mr-2" />
                    Download MP3
                  </Button>
                  <Button
                    onClick={handleGenerate}
                    variant="ghost"
                    className="text-slate-400 hover:text-white"
                    disabled={isGenerating}
                  >
                    <RefreshCw className="w-4 h-4 mr-2" />
                    Regenerate
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ── Settings panel ─────────────────────────────────────────────── */}
        <div className="space-y-4">
          {/* Voice selector */}
          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base text-white">Voice</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="text-slate-300 text-xs mb-1.5 block">Content type</Label>
                <Select value={contentType} onValueChange={setContentType}>
                  <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-600">
                    {CONTENT_TYPES.map((ct) => (
                      <SelectItem key={ct.value} value={ct.value} className="text-white">
                        {ct.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label className="text-slate-300 text-xs mb-1.5 block">Voice</Label>
                {loadingVoices ? (
                  <div className="flex items-center gap-2 text-slate-400 text-sm">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading voices…
                  </div>
                ) : (
                  <Select value={selectedVoice} onValueChange={setSelectedVoice}>
                    <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-600 max-h-60">
                      {voices.map((v) => (
                        <SelectItem key={v.voice_id} value={v.voice_id} className="text-white">
                          <div>
                            <span className="font-medium">{v.name}</span>
                            <span className="ml-2 text-xs text-slate-400 capitalize">{v.category}</span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              {selectedVoiceInfo?.description && (
                <p className="text-xs text-slate-400 italic">{selectedVoiceInfo.description}</p>
              )}
            </CardContent>
          </Card>

          {/* Voice tuning */}
          <Card className="bg-slate-900/50 border-slate-700/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base text-white">Fine-tuning</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <div className="flex justify-between items-center mb-2">
                  <Label className="text-slate-300 text-xs">Stability</Label>
                  <span className="text-xs text-slate-400">{stability.toFixed(2)}</span>
                </div>
                <Slider
                  value={[stability]}
                  onValueChange={([v]) => setStability(v)}
                  min={0} max={1} step={0.05}
                  className="[&_.slider-thumb]:border-purple-500 [&_.slider-range]:bg-purple-500"
                />
                <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                  <span>More variable</span>
                  <span>More stable</span>
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-2">
                  <Label className="text-slate-300 text-xs">Similarity boost</Label>
                  <span className="text-xs text-slate-400">{similarityBoost.toFixed(2)}</span>
                </div>
                <Slider
                  value={[similarityBoost]}
                  onValueChange={([v]) => setSimilarityBoost(v)}
                  min={0} max={1} step={0.05}
                  className="[&_.slider-thumb]:border-purple-500 [&_.slider-range]:bg-purple-500"
                />
                <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                  <span>Expressive</span>
                  <span>True to voice</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Generate */}
          <Button
            onClick={handleGenerate}
            disabled={isGenerating || !text.trim()}
            className="w-full bg-purple-600 hover:bg-purple-700 text-white"
          >
            {isGenerating ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Generating…</>
            ) : (
              <><Mic className="w-4 h-4 mr-2" /> Generate Voiceover</>
            )}
          </Button>

          {estimate && !isGenerating && (
            <p className="text-center text-xs text-slate-500">
              ~{Math.round(estimate.estimated_duration_seconds)}s audio
              · ~${estimate.estimated_cost_usd} cost
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

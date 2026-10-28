/*
 * Candidate Ranker — "which of these should I upload?"
 *
 * Drop 2-4 title(+thumbnail) options for the SAME video; get them ranked by
 * the reach model (fine-tuned CLIP, val AUC 0.668) blended with the MrBeast
 * packaging rubric, with the winner and the "why" surfaced. The user-facing
 * front of plan 6.4's generate->score->rank loop.
 *
 * Design: Signal Flow dark theme.
 */
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Trophy,
  ImagePlus,
  X,
  Plus,
  Loader2,
  Sparkles,
  AlertCircle,
  Crown,
  Info,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { rankCandidates, type RankResponse, type RankCandidate } from "@/lib/api";

interface Slot {
  id: number;
  title: string;
  file: File | null;
  preview: string | null;
}

let _nextId = 0;
const newSlot = (): Slot => ({ id: _nextId++, title: "", file: null, preview: null });

const MAX_SLOTS = 4;
const MIN_SLOTS = 2;

export default function CandidateRanker() {
  const [slots, setSlots] = useState<Slot[]>([newSlot(), newSlot()]);
  const [idea, setIdea] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RankResponse | null>(null);

  const filledTitles = slots.filter((s) => s.title.trim()).length;
  const canRank = filledTitles >= MIN_SLOTS && !loading;

  function update(id: number, patch: Partial<Slot>) {
    setSlots((s) => s.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  }

  function pickFile(id: number, file: File | null) {
    if (!file) return update(id, { file: null, preview: null });
    if (!file.type.startsWith("image/")) {
      toast.error("Thumbnails must be an image (jpg/png/webp).");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      toast.error("Thumbnail too large (max 8MB).");
      return;
    }
    update(id, { file, preview: URL.createObjectURL(file) });
  }

  async function run() {
    if (filledTitles < MIN_SLOTS) {
      toast.error("Add at least 2 titles to compare.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const candidates = slots
        .filter((s) => s.title.trim())
        .map((s) => ({ title: s.title.trim(), thumbnail: s.file }));
      const res = await rankCandidates(candidates, idea);
      setResult(res);
    } catch (e: any) {
      toast.error(
        e?.response?.data?.error?.message ||
          e?.response?.data?.detail ||
          "Ranking failed. Try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
          <Trophy className="w-6 h-6 text-cyan-glow" />
          Candidate Ranker
        </h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Have a few title or thumbnail ideas for the same video? Drop 2–4 of them
          and we'll rank them against proven packaging principles, with the reasoning —
          coaching to help you pick, not a performance prediction.
        </p>
      </div>

      {/* Inputs */}
      <Card>
        <CardContent className="p-5 space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {slots.map((s, i) => (
              <SlotCard
                key={s.id}
                slot={s}
                index={i}
                canRemove={slots.length > MIN_SLOTS}
                onTitle={(v) => update(s.id, { title: v })}
                onFile={(f) => pickFile(s.id, f)}
                onRemove={() => setSlots((arr) => arr.filter((x) => x.id !== s.id))}
              />
            ))}
          </div>

          {slots.length < MAX_SLOTS && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSlots((arr) => [...arr, newSlot()])}
              className="gap-2"
            >
              <Plus className="w-4 h-4" /> Add candidate ({slots.length}/{MAX_SLOTS})
            </Button>
          )}

          <div className="space-y-2">
            <label className="text-sm text-muted-foreground">
              Video idea / context <span className="opacity-60">(optional — sharpens the rubric)</span>
            </label>
            <Textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="e.g. I tested every budget mechanical keyboard under $50"
              className="resize-none"
              rows={2}
            />
          </div>

          <Button onClick={run} disabled={!canRank} className="gap-2">
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Ranking…
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" /> Rank candidates
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Results */}
      {result && <Results result={result} />}
    </div>
  );
}

function SlotCard({
  slot,
  index,
  canRemove,
  onTitle,
  onFile,
  onRemove,
}: {
  slot: Slot;
  index: number;
  canRemove: boolean;
  onTitle: (v: string) => void;
  onFile: (f: File | null) => void;
  onRemove: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const chars = slot.title.length;
  return (
    <div className="rounded-lg border border-border/60 bg-background/40 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground">
          Option {String.fromCharCode(65 + index)}
        </span>
        {canRemove && (
          <button onClick={onRemove} className="text-muted-foreground hover:text-destructive">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Thumbnail dropzone */}
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        className="relative w-full aspect-video rounded-md border border-dashed border-border/70 overflow-hidden flex items-center justify-center bg-secondary/20 hover:border-cyan-glow/50 transition-colors group"
      >
        {slot.preview ? (
          <>
            <img src={slot.preview} alt="" className="w-full h-full object-cover" />
            <span className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
          </>
        ) : (
          <span className="flex flex-col items-center gap-1 text-muted-foreground text-xs">
            <ImagePlus className="w-5 h-5" /> Thumbnail (optional)
          </span>
        )}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />

      {/* Title */}
      <div className="space-y-1">
        <Input
          value={slot.title}
          onChange={(e) => onTitle(e.target.value)}
          placeholder="Title…"
        />
        <div className="flex justify-end">
          <span className={`text-[10px] font-mono ${chars > 50 ? "text-amber-400" : "text-muted-foreground"}`}>
            {chars}/50
          </span>
        </div>
      </div>
    </div>
  );
}

function Results({ result }: { result: RankResponse }) {
  const ranked = [...result.candidates].sort((a, b) => a.rank - b.rank);
  const blended = result.ranking_basis === "rubric+reach_prior";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Info className="w-4 h-4" />
        {blended ? (
          <span>
            Ranked by the packaging rubric, with a weak experimental reach prior{" "}
            <span className="font-mono text-xs">({result.reach_model})</span>.
          </span>
        ) : (
          <span>
            Ranked by the packaging rubric — add a thumbnail to every option to factor in the reach prior.
          </span>
        )}
      </div>
      {result.disclaimer && (
        <p className="text-[11px] text-amber-glow/80 leading-snug">{result.disclaimer}</p>
      )}

      {ranked.map((c) => (
        <ResultRow key={c.index} c={c} blended={blended} winner={c.rank === 1} />
      ))}
    </div>
  );
}

function ResultRow({ c, blended, winner }: { c: RankCandidate; blended: boolean; winner: boolean }) {
  return (
    <Card className={winner ? "border-cyan-glow/50 bg-cyan-glow/5" : ""}>
      <CardContent className="p-4 flex gap-4">
        <div className="flex flex-col items-center justify-center w-10 shrink-0">
          {winner ? (
            <Crown className="w-6 h-6 text-cyan-glow" />
          ) : (
            <span className="text-lg font-bold text-muted-foreground">#{c.rank}</span>
          )}
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            {winner && (
              <Badge className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow">WINNER</Badge>
            )}
            <span className="font-medium truncate">{c.title || "(untitled)"}</span>
          </div>

          <div className="flex items-center gap-4 flex-wrap text-sm">
            {blended && c.reach_score !== null && (
              <Metric label="Reach" value={Math.round(c.reach_score * 100)} suffix="%" accent="cyan" />
            )}
            {c.rubric_score !== null && (
              <Metric label="Packaging" value={c.rubric_score} suffix="/100" accent="violet" />
            )}
            <span
              className={`text-xs px-2 py-0.5 rounded ${
                c.packaging.under_50_chars
                  ? "bg-emerald-500/15 text-emerald-400"
                  : "bg-amber-500/15 text-amber-400"
              }`}
            >
              {c.packaging.under_50_chars ? "≤50 chars" : "truncates on mobile"}
            </span>
          </div>

          {c.packaging.biggest_weakness && (
            <p className="text-xs text-muted-foreground flex items-start gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                <span className="font-medium text-foreground/80">Biggest weakness:</span>{" "}
                {c.packaging.biggest_weakness}
              </span>
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  suffix,
  accent,
}: {
  label: string;
  value: number;
  suffix: string;
  accent: "cyan" | "violet";
}) {
  const color = accent === "cyan" ? "text-cyan-glow" : "text-violet-400";
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono font-semibold ${color}`}>
        {value}
        <span className="text-xs opacity-70">{suffix}</span>
      </span>
    </span>
  );
}

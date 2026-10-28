import { useEffect, useState } from "react";
import { getBreakoutTeardown, type BreakoutTeardown as TD } from "@/lib/api";
import { Microscope, Hash, MessageSquare, Activity, Lightbulb } from "lucide-react";

/** "Reverse-engineer this breakout" — assembles why + format + comment themes +
 *  retention shape into one teardown. LLM-heavy: loads on demand, or on mount
 *  when ``autoLoad`` (e.g. when already inside an expanded card). */
export function BreakoutTeardown({ videoId, idea, autoLoad }: { videoId: string; idea?: string; autoLoad?: boolean }) {
  const [td, setTd] = useState<TD | "loading" | "error" | null>(null);

  const load = async () => {
    if (td) return;
    setTd("loading");
    try {
      setTd(await getBreakoutTeardown(videoId, idea));
    } catch {
      setTd("error");
    }
  };

  useEffect(() => { if (autoLoad) load(); /* eslint-disable-next-line */ }, [autoLoad]);

  if (!td) {
    return (
      <button onClick={load} className="text-xs text-cyan-glow/90 hover:text-cyan-glow flex items-center gap-1">
        <Microscope className="w-3.5 h-3.5" /> Reverse-engineer this breakout
      </button>
    );
  }
  if (td === "loading") return <p className="text-xs text-muted-foreground">Assembling the teardown…</p>;
  if (td === "error") return <p className="text-xs text-destructive">Couldn't build the teardown right now.</p>;

  const e = td.explanation;
  const c = td.comments;
  const r = td.retention;
  const maxV = r?.points?.length ? Math.max(...r.points.map((p) => p.value), 0.0001) : 1;

  return (
    <div className="mt-2 space-y-3 border-l-2 border-cyan-glow/30 pl-3 text-xs">
      {/* WHY */}
      {e?.why && (
        <div>
          <p className="font-semibold text-foreground/90 flex items-center gap-1"><Microscope className="w-3 h-3" /> Why it's breaking out</p>
          <p className="text-foreground/80 mt-0.5">{e.why}</p>
        </div>
      )}
      {/* FORMAT */}
      {td.format && (
        <div>
          <p className="font-semibold text-foreground/90 flex items-center gap-1"><Hash className="w-3 h-3" /> Format it used</p>
          <p className="text-cyan-glow/90 mt-0.5">{td.format.template} <span className="text-muted-foreground">· {td.format.psychology}</span></p>
        </div>
      )}
      {/* COMMENT THEMES */}
      {c && (
        <div>
          <p className="font-semibold text-foreground/90 flex items-center gap-1"><MessageSquare className="w-3 h-3" /> What viewers are saying</p>
          {c.summary && <p className="text-foreground/80 mt-0.5">{c.summary}</p>}
          {!!c.next_video_ideas?.length && (
            <p className="text-muted-foreground mt-1">Content gaps: {c.next_video_ideas.slice(0, 3).join(" · ")}</p>
          )}
        </div>
      )}
      {/* RETENTION SHAPE */}
      {r?.points?.length ? (
        <div>
          <p className="font-semibold text-foreground/90 flex items-center gap-1"><Activity className="w-3 h-3" /> Retention shape (most re-watched)</p>
          <div className="flex items-end gap-px h-8 mt-1">
            {r.points.map((p, i) => (
              <div key={i} className="flex-1 bg-cyan-glow/50 rounded-sm" style={{ height: `${(p.value / maxV) * 100}%` }} />
            ))}
          </div>
        </div>
      ) : null}
      {/* YOUR ANGLE + CAVEAT */}
      {e?.your_angle && (
        <p className="text-cyan-glow/90 flex items-start gap-1"><Lightbulb className="w-3 h-3 mt-0.5 shrink-0" /><span><span className="font-medium">Your version: </span>{e.your_angle}</span></p>
      )}
      {e?.caveat && <p className="text-[11px] text-muted-foreground/80 italic">{e.caveat}</p>}
    </div>
  );
}

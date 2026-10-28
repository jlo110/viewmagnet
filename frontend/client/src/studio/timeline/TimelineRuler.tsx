/**
 * TimelineRuler — second-marker ticks above the lanes. Click anywhere to
 * seek the player to that time.
 *
 * The tick density adapts to the available pixels-per-second so short clips
 * get finer half-second ticks and longer clips fall back to whole-second
 * (and eventually 5s / 10s) intervals.
 */
import type { TimelineController } from "./useTimelineController";

interface TimelineRulerProps {
  controller: TimelineController;
  height?: number;
}

export function TimelineRuler({ controller, height = 24 }: TimelineRulerProps) {
  const { pixelsPerSecond, durationSeconds, seekSeconds } = controller;

  // Pick a tick interval whose spacing is comfortable to read (~50-120px).
  const interval = pickInterval(pixelsPerSecond);

  const ticks: number[] = [];
  for (let t = 0; t <= durationSeconds + 0.0001; t += interval) {
    ticks.push(t);
  }

  return (
    <div
      className="relative w-full select-none border-b border-zinc-800 bg-zinc-950 text-[10px] text-zinc-500"
      style={{ height }}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left;
        seekSeconds(controller.pxToSeconds(x));
      }}
    >
      {ticks.map((t) => {
        const x = controller.secondsToPx(t);
        return (
          <div
            key={t}
            className="absolute top-0 bottom-0 border-l border-zinc-800"
            style={{ left: x }}
          >
            <span className="absolute left-1 top-0 tabular-nums">
              {formatTick(t)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function pickInterval(pxPerSec: number): number {
  if (pxPerSec >= 120) return 0.5;
  if (pxPerSec >= 50) return 1;
  if (pxPerSec >= 20) return 5;
  if (pxPerSec >= 10) return 10;
  return 30;
}

function formatTick(seconds: number): string {
  const total = Math.round(seconds * 10) / 10;
  const whole = Math.floor(total);
  const frac = Math.round((total - whole) * 10);
  if (frac === 0) {
    const mm = Math.floor(whole / 60);
    const ss = whole % 60;
    return `${mm}:${ss.toString().padStart(2, "0")}`;
  }
  return `${total.toFixed(1)}s`;
}

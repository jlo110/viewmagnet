/**
 * WaveformLane — canvas-based audio peaks background for the source-video
 * lane. Renders ~2000 vertical bars (one per cached peak), centered on the
 * lane baseline so the waveform reads symmetrically like every other DAW.
 *
 * Why a plain <canvas> instead of wavesurfer.js? wavesurfer pulls in 150+ KB
 * and gives us features (audio playback, regions, plugins) we don't need.
 * A static peak renderer is ~30 lines of code.
 */
import { useEffect, useRef, useState } from "react";

import { getPeaks } from "../api";
import type { PeaksResponse } from "../types";

interface WaveformLaneProps {
  clipKey: string | null;
  /** Used purely to invalidate the cached peaks fetch on trim. */
  clipStartTime: number;
  /** Same — when the user drags the trim handle this changes and we refetch. */
  clipEndTime: number;
  widthPx: number;
  heightPx: number;
  /** Hex color of the waveform fill. */
  color?: string;
  /** Default 2000 — finer than any reasonable lane width. */
  bins?: number;
}

export function WaveformLane({
  clipKey,
  clipStartTime,
  clipEndTime,
  widthPx,
  heightPx,
  color = "#94a3b8",
  bins = 2000,
}: WaveformLaneProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [peaksData, setPeaksData] = useState<PeaksResponse | null>(null);

  // Fetch peaks — refetches when the clip window changes (trim) or the key
  // changes (different clip loaded). 503s mean "in flight, try again"; we
  // retry up to a few times before giving up.
  useEffect(() => {
    if (!clipKey) {
      setPeaksData(null);
      return;
    }
    let cancelled = false;
    let attempts = 0;
    const fetchOnce = async () => {
      try {
        const data = await getPeaks(clipKey, bins);
        if (cancelled) return;
        if (data == null) {
          if (attempts < 5) {
            attempts += 1;
            setTimeout(fetchOnce, 1500);
          }
          return;
        }
        setPeaksData(data);
      } catch {
        // Best-effort: a missing waveform is fine.
      }
    };
    fetchOnce();
    return () => {
      cancelled = true;
    };
  }, [clipKey, clipStartTime, clipEndTime, bins]);

  // Paint the waveform whenever the peaks or layout size changes. Canvas is
  // sized in physical pixels (× devicePixelRatio) so the bars stay crisp on
  // retina displays.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(1, Math.floor(widthPx));
    const cssH = Math.max(1, Math.floor(heightPx));
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    if (!peaksData || peaksData.peaks.length === 0) {
      // Centerline only — gives the lane a subtle "we know there's audio
      // here, just haven't drawn it yet" feel without a layout shift.
      ctx.fillStyle = `${color}33`;
      ctx.fillRect(0, Math.floor(cssH / 2), cssW, 1);
      return;
    }

    const peaks = peaksData.peaks;
    const mid = cssH / 2;
    const maxBarHeight = cssH * 0.9;
    // Cap bar count to either the peak count or the lane width — we never
    // want sub-pixel bars (they alias badly) or huge gaps from upsampling.
    const barCount = Math.min(peaks.length, Math.max(1, Math.floor(cssW)));
    const barWidth = cssW / barCount;
    const drawWidth = Math.max(1, barWidth - 0.5);

    ctx.fillStyle = color;
    for (let i = 0; i < barCount; i += 1) {
      // When peaks has fewer bins than barCount we duplicate; when more,
      // we pick the max in the sampled window (preserves transients).
      const start = Math.floor((i * peaks.length) / barCount);
      const end = Math.max(start + 1, Math.floor(((i + 1) * peaks.length) / barCount));
      let peak = 0;
      for (let j = start; j < end; j += 1) {
        if (peaks[j] > peak) peak = peaks[j];
      }
      const h = Math.max(1, peak * maxBarHeight);
      ctx.fillRect(i * barWidth, mid - h / 2, drawWidth, h);
    }
  }, [peaksData, widthPx, heightPx, color]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0"
      aria-hidden
    />
  );
}

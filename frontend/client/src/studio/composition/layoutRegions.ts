/**
 * layoutRegions — TypeScript mirror of ``src/features/studio/layout.py``.
 *
 * Pure function for computing where the main video + background-loop
 * regions sit on the preview canvas, given a ``Layout`` spec and canvas
 * dimensions. Used by ``LayoutComposition.tsx`` so the in-browser preview
 * matches the ffmpeg render's pixel positions exactly.
 *
 * Keep this in sync with ``layout.py``: every change to the Python module
 * needs the matching TS update or preview/render parity drifts.
 */
import type { Layout } from "../types";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LayoutRegions {
  main: Rect;
  bg: Rect | null;
  canvasW: number;
  canvasH: number;
}

function evenPx(n: number): number {
  return Math.max(2, Math.floor(n) - (Math.floor(n) % 2));
}

export function regionsFor(
  layout: Layout,
  canvasW: number,
  canvasH: number,
): LayoutRegions {
  const cw = evenPx(canvasW);
  const ch = evenPx(canvasH);

  if (layout.mode === "single") {
    return { main: { x: 0, y: 0, w: cw, h: ch }, bg: null, canvasW: cw, canvasH: ch };
  }

  if (layout.mode === "split_horizontal") {
    let mainH = evenPx(Math.round(ch * layout.main_weight));
    mainH = Math.max(64, Math.min(ch - 64, mainH));
    const bgH = evenPx(ch - mainH);
    return {
      main: { x: 0, y: 0, w: cw, h: mainH },
      bg: { x: 0, y: mainH, w: cw, h: bgH },
      canvasW: cw,
      canvasH: ch,
    };
  }

  if (layout.mode === "split_vertical") {
    let mainW = evenPx(Math.round(cw * layout.main_weight));
    mainW = Math.max(64, Math.min(cw - 64, mainW));
    const bgW = evenPx(cw - mainW);
    return {
      main: { x: 0, y: 0, w: mainW, h: ch },
      bg: { x: mainW, y: 0, w: bgW, h: ch },
      canvasW: cw,
      canvasH: ch,
    };
  }

  if (layout.mode === "pip_corner") {
    let pipW = evenPx(Math.round(cw * layout.pip_size));
    let pipH = evenPx(Math.round((pipW * 9) / 16));
    pipW = Math.min(pipW, cw - 32);
    pipH = Math.min(pipH, ch - 32);
    const margin = Math.max(8, Math.floor(cw / 64));
    let x: number;
    let y: number;
    if (layout.pip_corner === "tl") {
      x = margin;
      y = margin;
    } else if (layout.pip_corner === "tr") {
      x = cw - pipW - margin;
      y = margin;
    } else if (layout.pip_corner === "bl") {
      x = margin;
      y = ch - pipH - margin;
    } else {
      x = cw - pipW - margin;
      y = ch - pipH - margin;
    }
    return {
      main: { x: 0, y: 0, w: cw, h: ch },
      bg: { x: evenPx(x), y: evenPx(y), w: pipW, h: pipH },
      canvasW: cw,
      canvasH: ch,
    };
  }

  return { main: { x: 0, y: 0, w: cw, h: ch }, bg: null, canvasW: cw, canvasH: ch };
}

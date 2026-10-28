/**
 * Tests for studio/composition/layoutRegions.ts
 *
 * This is the TypeScript mirror of layout.py. If these tests fail after
 * changing layoutRegions.ts it means the preview would diverge from the
 * rendered video output.  Keep all assertions as exact pixel values so
 * unintended drifts are caught immediately.
 */
import { describe, it, expect } from "vitest";
import { regionsFor, type LayoutRegions } from "../studio/composition/layoutRegions";
import type { Layout } from "../studio/types";

const CANVAS_W = 1080;
const CANVAS_H = 1920;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function evenPx(n: number) {
  return Math.max(2, Math.floor(n) - (Math.floor(n) % 2));
}

// ---------------------------------------------------------------------------
// single mode
// ---------------------------------------------------------------------------

describe("single layout", () => {
  const layout: Layout = { mode: "single" } as Layout;

  it("main fills the entire canvas", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.main.x).toBe(0);
    expect(r.main.y).toBe(0);
    expect(r.main.w).toBe(evenPx(CANVAS_W));
    expect(r.main.h).toBe(evenPx(CANVAS_H));
  });

  it("bg is null", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.bg).toBeNull();
  });

  it("returns even-pixel canvas dimensions", () => {
    const r = regionsFor(layout, 1081, 1921);
    expect(r.canvasW % 2).toBe(0);
    expect(r.canvasH % 2).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// split_horizontal mode
// ---------------------------------------------------------------------------

describe("split_horizontal layout", () => {
  const layout: Layout = { mode: "split_horizontal", main_weight: 0.6 } as Layout;

  it("main region is at top", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.main.x).toBe(0);
    expect(r.main.y).toBe(0);
  });

  it("bg region is directly below main", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.bg).not.toBeNull();
    expect(r.bg!.y).toBe(r.main.h);
  });

  it("heights sum to canvas height", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.main.h + r.bg!.h).toBe(r.canvasH);
  });

  it("main weight 0.6 → mainH ≈ 60% of canvas", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    const ratio = r.main.h / r.canvasH;
    expect(ratio).toBeGreaterThan(0.5);
    expect(ratio).toBeLessThan(0.75);
  });

  it("all dimensions are even pixels", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    for (const dim of [r.main.w, r.main.h, r.bg!.w, r.bg!.h]) {
      expect(dim % 2).toBe(0);
    }
  });

  it("clamps mainH to at least 64px", () => {
    const tiny: Layout = { mode: "split_horizontal", main_weight: 0.001 } as Layout;
    const r = regionsFor(tiny, CANVAS_W, CANVAS_H);
    expect(r.main.h).toBeGreaterThanOrEqual(64);
  });

  it("clamps mainH to at most canvasH - 64px", () => {
    const huge: Layout = { mode: "split_horizontal", main_weight: 0.999 } as Layout;
    const r = regionsFor(huge, CANVAS_W, CANVAS_H);
    expect(r.main.h).toBeLessThanOrEqual(r.canvasH - 64);
  });
});

// ---------------------------------------------------------------------------
// split_vertical mode
// ---------------------------------------------------------------------------

describe("split_vertical layout", () => {
  const layout: Layout = { mode: "split_vertical", main_weight: 0.5 } as Layout;

  it("main region is on the left", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.main.x).toBe(0);
    expect(r.main.y).toBe(0);
  });

  it("bg region is to the right of main", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.bg!.x).toBe(r.main.w);
  });

  it("widths sum to canvas width", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.main.w + r.bg!.w).toBe(r.canvasW);
  });

  it("all dimensions are even pixels", () => {
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    for (const dim of [r.main.w, r.main.h, r.bg!.w, r.bg!.h]) {
      expect(dim % 2).toBe(0);
    }
  });
});

// ---------------------------------------------------------------------------
// pip_corner mode
// ---------------------------------------------------------------------------

describe("pip_corner layout", () => {
  const baseLayout = (corner: string): Layout =>
    ({ mode: "pip_corner", pip_size: 0.3, pip_corner: corner } as Layout);

  it("main fills full canvas", () => {
    const r = regionsFor(baseLayout("br"), CANVAS_W, CANVAS_H);
    expect(r.main.w).toBe(r.canvasW);
    expect(r.main.h).toBe(r.canvasH);
  });

  it("pip is in top-left when pip_corner='tl'", () => {
    const r = regionsFor(baseLayout("tl"), CANVAS_W, CANVAS_H);
    expect(r.bg!.x).toBeGreaterThanOrEqual(0);
    expect(r.bg!.y).toBeGreaterThanOrEqual(0);
    // Top-left: x and y are small (margin)
    expect(r.bg!.x).toBeLessThan(r.canvasW / 2);
    expect(r.bg!.y).toBeLessThan(r.canvasH / 2);
  });

  it("pip is in bottom-right when pip_corner='br'", () => {
    const r = regionsFor(baseLayout("br"), CANVAS_W, CANVAS_H);
    expect(r.bg!.x).toBeGreaterThan(r.canvasW / 2);
    expect(r.bg!.y).toBeGreaterThan(r.canvasH / 2);
  });

  it("pip is in top-right when pip_corner='tr'", () => {
    const r = regionsFor(baseLayout("tr"), CANVAS_W, CANVAS_H);
    expect(r.bg!.x).toBeGreaterThan(r.canvasW / 2);
    expect(r.bg!.y).toBeLessThan(r.canvasH / 2);
  });

  it("pip is in bottom-left when pip_corner='bl'", () => {
    const r = regionsFor(baseLayout("bl"), CANVAS_W, CANVAS_H);
    expect(r.bg!.x).toBeLessThan(r.canvasW / 2);
    expect(r.bg!.y).toBeGreaterThan(r.canvasH / 2);
  });

  it("pip dimensions are even pixels", () => {
    const r = regionsFor(baseLayout("br"), CANVAS_W, CANVAS_H);
    expect(r.bg!.w % 2).toBe(0);
    expect(r.bg!.h % 2).toBe(0);
  });

  it("pip stays within canvas bounds", () => {
    const r = regionsFor(baseLayout("br"), CANVAS_W, CANVAS_H);
    expect(r.bg!.x + r.bg!.w).toBeLessThanOrEqual(r.canvasW);
    expect(r.bg!.y + r.bg!.h).toBeLessThanOrEqual(r.canvasH);
  });
});

// ---------------------------------------------------------------------------
// unknown mode falls back to single
// ---------------------------------------------------------------------------

describe("unknown layout mode", () => {
  it("falls back to single (bg is null)", () => {
    const layout = { mode: "unknown_mode" } as unknown as Layout;
    const r = regionsFor(layout, CANVAS_W, CANVAS_H);
    expect(r.bg).toBeNull();
    expect(r.main.w).toBe(evenPx(CANVAS_W));
  });
});

// ---------------------------------------------------------------------------
// edge cases
// ---------------------------------------------------------------------------

describe("edge cases", () => {
  it("handles odd canvas dimensions gracefully", () => {
    const r = regionsFor({ mode: "single" } as Layout, 1079, 1919);
    expect(r.canvasW % 2).toBe(0);
    expect(r.canvasH % 2).toBe(0);
  });

  it("minimum dimension is 2px", () => {
    const r = regionsFor({ mode: "single" } as Layout, 1, 1);
    expect(r.main.w).toBeGreaterThanOrEqual(2);
    expect(r.main.h).toBeGreaterThanOrEqual(2);
  });
});

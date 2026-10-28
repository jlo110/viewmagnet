/**
 * LayoutComposition (Week 6 Phase 3) — positions the main + background
 * region children using the rectangles computed by ``layoutRegions``.
 *
 * Mirrors the ffmpeg-side ``regions_for`` math in ``layout.py`` so the
 * in-browser preview lines up 1:1 with the server render's overlay
 * coordinates. The component is intentionally render-prop based: parents
 * supply the actual region contents (e.g. ``<VideoMain />``,
 * ``<BackgroundLoopLayer />``) and we just handle absolute-positioned
 * wrapping divs.
 *
 * For ``mode === "single"`` we forward straight through (no bg slot) so
 * the legacy preview path keeps its zero-overhead behavior.
 */
import type { ReactNode } from "react";

import type { Layout } from "../types";
import { regionsFor, type Rect } from "./layoutRegions";

export interface LayoutCompositionProps {
  layout: Layout;
  canvasW: number;
  canvasH: number;
  /** Main video region (always rendered). */
  main: ReactNode;
  /** Background-loop region (rendered when the layout has a bg rect). */
  background?: ReactNode;
  /**
   * Optional overlay slot — captions, brand logo, b-roll, etc. Rendered
   * full-canvas above both region children so layout-aware components can
   * use absolute positioning inside the main rect themselves.
   */
  overlay?: ReactNode;
}

export function LayoutComposition({
  layout,
  canvasW,
  canvasH,
  main,
  background,
  overlay,
}: LayoutCompositionProps) {
  const regions = regionsFor(layout, canvasW, canvasH);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        width: canvasW,
        height: canvasH,
        background: "#000",
        overflow: "hidden",
      }}
    >
      {/* Background-loop layer. For split / PiP layouts the bg gets its own
          rectangle. For ``single`` mode (regions.bg === null) we still
          render the bg full-canvas as an UNDERLAY so the main video covers
          it — handy when the user enables a bg loop without changing the
          layout. Matches the render.py ``bg_rect is None`` branch. */}
      {background && regions.bg && (
        <RegionBox rect={regions.bg}>{background}</RegionBox>
      )}
      {background && !regions.bg && (
        <RegionBox
          rect={{ x: 0, y: 0, w: regions.canvasW, h: regions.canvasH }}
        >
          {background}
        </RegionBox>
      )}
      <RegionBox rect={regions.main}>{main}</RegionBox>
      {overlay && (
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          {overlay}
        </div>
      )}
    </div>
  );
}

function RegionBox({ rect, children }: { rect: Rect; children: ReactNode }) {
  return (
    <div
      style={{
        position: "absolute",
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}

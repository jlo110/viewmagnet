/**
 * StudioComposition — the top-level Remotion <Composition> that renders one
 * edit session: source video + caption overlay + (future) B-roll + transitions.
 *
 * Used by the in-browser <Player> for live preview while editing. The
 * server-side ffmpeg render path in src/features/studio/render.py consumes
 * the SAME EditSpec, so what users see here is what they download.
 */
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { proxyVideoUrl } from "../sourceUrl";
import {
  ASPECT_DIMENSIONS,
  type BRollClip,
  type EditSpec,
  type TrackingData,
  type Transitions,
} from "../types";
import { AutoZoomLayer } from "./AutoZoomLayer";
import { BackgroundLoopLayer } from "./BackgroundLoopLayer";
import { BBoxOverlay } from "./BBoxOverlay";
import { CameraCropLayer } from "./CameraCropLayer";
import { CaptionLayer } from "./CaptionLayer";
import { LayoutComposition } from "./LayoutComposition";
import { regionsFor } from "./layoutRegions";
import { getRecipe, recipeFrameToStyle } from "./transitionRecipes";

export interface StudioCompositionProps {
  spec: EditSpec;
  /** URL of the source video. Either a public HTTPS URL, an /api/... proxy
   *  path, or a blob: URL from a local file the user uploaded. */
  videoUrl: string;
  /** Cached multi-subject tracking payload. When present AND
   *  ``spec.camera.tracks`` is non-empty, the source video is rendered via
   *  CameraCropLayer (per-frame transform). Otherwise we fall back to the
   *  static cropStyle path. */
  tracking?: TrackingData | null;
  /** Catalog-id → download-url map for background loops (Week 6). Populated
   *  by the Studio page after fetching ``GET /studio/backgrounds``. Empty
   *  by default — Pexels-sourced loops still work, only catalog-sourced
   *  ones fall back to the gradient placeholder. */
  backgroundCatalogUrlMap?: Record<string, string>;
}

export function StudioComposition({
  spec,
  videoUrl,
  tracking,
  backgroundCatalogUrlMap = {},
}: StudioCompositionProps) {
  const { width, height } = useVideoConfig();
  const targetAspect = ASPECT_DIMENSIONS[spec.aspect_ratio];

  // For the preview, we trim the source so seeking starts at the edit's
  // start_time. Remotion's OffthreadVideo + startFrom handles this natively.
  const fps = 30;
  const startFromFrame = Math.round(spec.clip.start_time * fps);
  const endAtFrame = Math.round(spec.clip.end_time * fps);

  // Compute a CSS object-fit-style cover that mimics the ffmpeg `crop=` we
  // do on the backend. When the spec carries an explicit crop, use it.
  // Otherwise, we let `object-fit: cover` center-crop to the canvas aspect.
  const cropStyle = computeCropStyle(spec, width, height);

  // Camera lane takes precedence over the static cropStyle when there are
  // cuts AND we have tracking data loaded. Matches the renderer's decision
  // tree in _crop_filter_for_aspect. ``spec.camera`` is optional-chained
  // for legacy sessions saved before Week 4 (server normalizes on read,
  // but the cached frontend bundle may briefly see the old shape).
  const useCameraCrop =
    (spec.camera?.tracks?.length ?? 0) > 0 &&
    tracking != null &&
    tracking.subjects.length > 0;

  // Phase 3 layout regions — the LayoutComposition wrapper positions the
  // main video and (optional) background-loop rectangles per the user's
  // Layout config. Single mode still fills the entire canvas, so the
  // legacy preview behavior is preserved. ``spec.layout`` is optional-chained
  // for sessions saved before Week 6 (server normalizes on read, but the
  // cached frontend bundle may briefly see the old shape).
  const layout = spec.layout ?? {
    mode: "single" as const,
    pip_corner: "br" as const,
    pip_size: 0.3,
    main_weight: 0.5,
  };
  const regions = regionsFor(layout, width, height);

  const mainContent = (
    <>
      {/* Auto-zoom (Week 5) pulses ONLY the base video subtree. B-roll and
          captions remain outside this layer (they live in the overlay
          slot so they don't get punched in). */}
      <AutoZoomLayer autoZoom={spec.auto_zoom}>
        {useCameraCrop ? (
          <CameraCropLayer
            spec={spec}
            tracking={tracking!}
            videoUrl={videoUrl}
            startFromFrame={startFromFrame}
            endAtFrame={endAtFrame}
          />
        ) : (
          // Plain absolutely-positioned <div> wrapper (NOT <AbsoluteFill>):
          // Remotion's AbsoluteFill is internally ``display: flex;
          // flex-direction: column``. Mounting <OffthreadVideo> as a direct
          // sibling of <BBoxOverlay> + <CaptionLayer> inside that flex column
          // turns the <video> into a flex item that fights with its siblings
          // for vertical space and ignores ``height: 100%``, producing the
          // upper-left letterboxed video we saw with the new demo clip.
          // A vanilla absolute div gives the <video> a stable positioning
          // context so ``object-fit: cover`` fills the full composition.
          <div
            style={{
              position: "absolute",
              inset: 0,
              overflow: "hidden",
            }}
          >
            <OffthreadVideo
              src={videoUrl}
              startFrom={startFromFrame}
              endAt={endAtFrame}
              muted={false}
              style={cropStyle}
            />
          </div>
        )}
      </AutoZoomLayer>

      {/* B-roll overlays — sized to the MAIN region (LayoutComposition
          clips us). Each clip mounts only during its [start, end] window
          via Remotion <Sequence>, mirroring the ffmpeg
          ``overlay=enable='between(t,S,E)'`` filter so preview == render. */}
      {spec.broll.enabled &&
        spec.broll.clips.map((clip, i) => (
          <BRollOverlay
            key={`${clip.clip_url}-${i}`}
            clip={clip}
            fps={fps}
            transitions={spec.transitions}
          />
        ))}
    </>
  );

  // Background-loop slot — only mounted when the user has configured one.
  // The LayoutComposition handles the rectangle sizing (full canvas for
  // single, slice for split, inset for PiP).
  const backgroundContent = spec.background_loop ? (
    <BackgroundLoopLayer
      backgroundLoop={spec.background_loop}
      catalogUrlMap={backgroundCatalogUrlMap}
      fps={fps}
    />
  ) : null;

  const overlayContent = (
    <>
      {/* Click-to-switch overlay for the Camera lane. Rendered above B-roll
          so users can click during a B-roll window too. Suppressed while
          a CameraCropLayer cut is active because the source video is then
          transformed (translate+scale) and our cover-scaling bbox math
          would draw rectangles in the wrong spots. */}
      <BBoxOverlay
        tracking={tracking ?? null}
        enabled={(spec.camera?.bbox_overlay_enabled ?? false) && !useCameraCrop}
      />

      {/* Captions anchored to the MAIN region so split / PiP layouts keep
          them inside the primary video instead of straying over the
          background loop. */}
      <CaptionLayer
        captions={spec.captions}
        words={spec.clip.transcript}
        timeOffsetSeconds={0}
        mainRegion={regions.main}
        brandKit={spec.brand_kit}
      />

      {/* Brand kit logo (Week 6) */}
      {spec.brand_kit.logo_url && (
        <BrandLogo
          url={spec.brand_kit.logo_url}
          position={spec.brand_kit.logo_position}
          opacity={spec.brand_kit.logo_opacity}
        />
      )}
    </>
  );

  return (
    <AbsoluteFill style={{ background: "#000", overflow: "hidden" }}>
      <LayoutComposition
        layout={layout}
        canvasW={width}
        canvasH={height}
        main={mainContent}
        background={backgroundContent}
        overlay={overlayContent}
      />
    </AbsoluteFill>
  );
}

function computeCropStyle(spec: EditSpec, canvasW: number, canvasH: number): React.CSSProperties {
  // Without an explicit crop, just object-fit cover so the video fills the
  // target aspect ratio — this matches the centered-crop ffmpeg fallback
  // in render._crop_filter_for_aspect.
  if (!spec.crop) {
    return {
      width: "100%",
      height: "100%",
      objectFit: "cover",
      objectPosition: "center",
    };
  }
  // With an explicit crop, scale the source so that the cropped region
  // exactly fills the canvas, then offset it accordingly. We do this in
  // percentages so it stays correct at any preview scale.
  const { x, y, width: cw, height: ch } = spec.crop;
  // assume the source is the natural size of the first video frame; we let
  // CSS scale it. The math is: source must be sized so that cw -> canvasW.
  const sourceScale = canvasW / cw;
  return {
    position: "absolute",
    transformOrigin: "top left",
    transform: `translate(${-x * sourceScale}px, ${-y * sourceScale}px) scale(${sourceScale.toFixed(4)})`,
    width: "auto",
    height: "auto",
  };
}

interface BrandLogoProps {
  url: string;
  position: "tl" | "tr" | "bl" | "br";
  opacity: number;
}

interface BRollOverlayProps {
  clip: BRollClip;
  fps: number;
  transitions?: Transitions;
}

function BRollOverlay({ clip, fps, transitions }: BRollOverlayProps) {
  const from = Math.max(0, Math.round(clip.start * fps));
  const durationInFrames = Math.max(
    1,
    Math.round((clip.end - clip.start) * fps),
  );
  return (
    <Sequence from={from} durationInFrames={durationInFrames} layout="none">
      <BRollFrame
        clip={clip}
        durationInFrames={durationInFrames}
        fps={fps}
        transitions={transitions}
      />
    </Sequence>
  );
}

/**
 * Inner B-roll frame — runs INSIDE the Sequence so it can use
 * ``useCurrentFrame`` (which returns sequence-local frames) to drive the
 * transition progress. Dispatches to a recipe in
 * ``transitionRecipes.ts`` so the preview matches whatever ffmpeg recipe
 * the catalog applies on render.
 */
function BRollFrame({
  clip,
  durationInFrames,
  fps,
  transitions,
}: {
  clip: BRollClip;
  durationInFrames: number;
  fps: number;
  transitions?: Transitions;
}) {
  const frame = useCurrentFrame();
  const tx = transitions;
  const type = tx?.enabled ? tx.type : "cut";
  // Cap the visible animation at 40% of the clip window, same as the
  // backend ``min(tx_dur, win * 0.4)`` clamp.
  const requestedDurFrames = tx?.enabled
    ? Math.round(((tx.duration_ms ?? 0) / 1000) * fps)
    : 0;
  const txFrames = Math.max(
    0,
    Math.min(requestedDurFrames, Math.floor(durationInFrames * 0.4)),
  );

  const recipe = getRecipe(type);
  const recipeFrame = recipe({
    frame,
    durationInFrames,
    txFrames,
    baseOpacity: clip.opacity,
  });
  const style = recipeFrameToStyle(recipeFrame);

  return (
    <AbsoluteFill style={style}>
      <OffthreadVideo
        src={proxyVideoUrl(clip.clip_url)}
        muted={clip.mute}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
}

function BrandLogo({ url, position, opacity }: BrandLogoProps) {
  const styleByCorner: Record<BrandLogoProps["position"], React.CSSProperties> = {
    tl: { top: 24, left: 24 },
    tr: { top: 24, right: 24 },
    bl: { bottom: 24, left: 24 },
    br: { bottom: 24, right: 24 },
  };
  return (
    <img
      src={url}
      alt="brand logo"
      style={{
        position: "absolute",
        width: "12%",
        opacity,
        ...styleByCorner[position],
      }}
    />
  );
}

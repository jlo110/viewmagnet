/**
 * Frontend mirror of `src/features/studio/transition_catalog.py`.
 *
 * Each recipe takes the current sequence-local frame plus window metadata
 * and returns the visual deltas to apply to a B-roll element so the live
 * Remotion preview matches the ffmpeg-rendered MP4.
 *
 * Naming + behaviour must stay in sync with the Python catalog — if you
 * add a new TransitionType in spec.py and a recipe in the Python catalog,
 * add the same key here too. The unit tests in
 * `frontend/client/__tests__/transitionRecipes.spec.ts` (when added) lock
 * the boundary frames (entry 0/last, exit 0/last) so drift gets caught.
 */
import { interpolate } from "remotion";

import type { TransitionType } from "../types";

/** Shape of the per-frame visual delta a recipe emits. The B-roll layer
 *  composes these into a single style object — keeping the recipe-side
 *  contract tight means new effects can be added without touching the
 *  layer code. */
export interface RecipeFrame {
  opacity: number;
  /** Horizontal translation as a percentage of the canvas width. */
  translateXPct: number;
  /** Vertical translation as a percentage of the canvas height. */
  translateYPct: number;
  /** CSS scale value (1 = no scaling). */
  scale: number;
  /** Optional CSS ``filter`` string, e.g. "blur(2px) hue-rotate(25deg)". */
  filter?: string;
}

/** Input to a recipe builder. ``txFrames`` is already clamped at 40% of
 *  the window so recipes don't have to repeat that math. */
export interface RecipeCtx {
  frame: number;
  durationInFrames: number;
  txFrames: number;
  baseOpacity: number;
}

type Recipe = (ctx: RecipeCtx) => RecipeFrame;

// ---------------------------------------------------------------------------
// Shared helpers (DRY for the common in/out window math)
// ---------------------------------------------------------------------------

function inOutEnvelope(frame: number, durationInFrames: number, txFrames: number) {
  // 1.0 at hold, 0.0 at the very edges of the window.
  const fadeIn = interpolate(frame, [0, txFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(
    frame,
    [durationInFrames - txFrames, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return Math.min(fadeIn, fadeOut);
}

function holdFrame(baseOpacity: number): RecipeFrame {
  return { opacity: baseOpacity, translateXPct: 0, translateYPct: 0, scale: 1 };
}

function fadeRecipe(ctx: RecipeCtx): RecipeFrame {
  const env = inOutEnvelope(ctx.frame, ctx.durationInFrames, ctx.txFrames);
  return {
    opacity: ctx.baseOpacity * env,
    translateXPct: 0,
    translateYPct: 0,
    scale: 1,
  };
}

function slideRecipe(axis: "x" | "y", sign: 1 | -1): Recipe {
  return ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    // Enter from +sign * 100%, slide to 0; hold; exit to -sign * 100%.
    // Matches the ffmpeg ``_slide_overlay_expr`` direction convention.
    const enter = interpolate(
      frame,
      [0, txFrames],
      [sign * 100, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
    const exit = interpolate(
      frame,
      [durationInFrames - txFrames, durationInFrames],
      [0, -sign * 100],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
    const pct = frame < durationInFrames / 2 ? enter : exit;
    return {
      opacity: baseOpacity,
      translateXPct: axis === "x" ? pct : 0,
      translateYPct: axis === "y" ? pct : 0,
      scale: 1,
    };
  };
}

function zoomRecipe(mode: "in" | "out", { blur }: { blur?: boolean } = {}): Recipe {
  return ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    let scale = 1;
    if (mode === "in") {
      // Entry: 1.5 → 1.0  ;  hold: 1.0  ;  exit: 1.0 → 1.5
      const enter = interpolate(frame, [0, txFrames], [1.5, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      const exit = interpolate(
        frame,
        [durationInFrames - txFrames, durationInFrames],
        [1.0, 1.5],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
      scale = frame < durationInFrames / 2 ? enter : exit;
    } else {
      // Entry: 1.0 → 1.5  ;  hold: 1.5  ;  exit: 1.5 → 1.0
      const enter = interpolate(frame, [0, txFrames], [1.0, 1.5], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
      const exit = interpolate(
        frame,
        [durationInFrames - txFrames, durationInFrames],
        [1.5, 1.0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
      scale = frame < durationInFrames / 2 ? enter : exit;
    }
    return {
      opacity: baseOpacity * env,
      translateXPct: 0,
      translateYPct: 0,
      scale,
      filter: blur ? "blur(2px)" : undefined,
    };
  };
}

function shakeRecipe(): Recipe {
  // Jittery overlay translation during entry & exit windows. Matches the
  // backend ``_shake_overlay_expr`` (sin at 25 Hz with linearly decaying
  // amplitude into the hold).
  return ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    const FREQ_HZ = 25;
    const FPS = 30;
    const AMP_PCT = 4; // 4% canvas width peak — visible but not nauseating
    let amp = 0;
    if (frame < txFrames) {
      amp = (1 - frame / Math.max(1, txFrames)) * AMP_PCT;
    } else if (frame > durationInFrames - txFrames) {
      amp = ((frame - (durationInFrames - txFrames)) / Math.max(1, txFrames)) * AMP_PCT;
    }
    const t = frame / FPS;
    return {
      opacity: baseOpacity * env,
      translateXPct: amp * Math.sin(2 * Math.PI * FREQ_HZ * t),
      translateYPct: 0,
      scale: 1,
    };
  };
}

// ---------------------------------------------------------------------------
// Recipe catalog — names match TransitionType / TRANSITION_CATALOG keys
// ---------------------------------------------------------------------------

const RECIPES: Record<TransitionType, Recipe> = {
  cut: ({ baseOpacity }) => holdFrame(baseOpacity),

  fade: fadeRecipe,
  dissolve: fadeRecipe, // visually identical envelope; only default duration differs

  swipe: slideRecipe("x", +1),       // slide left (legacy name)
  slide_up: slideRecipe("y", +1),
  slide_down: slideRecipe("y", -1),

  zoom_in: zoomRecipe("in"),
  zoom_out: zoomRecipe("out"),
  zoom_blur: zoomRecipe("in", { blur: true }),

  rgb_split: ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    return {
      opacity: baseOpacity * env,
      translateXPct: 0,
      translateYPct: 0,
      scale: 1,
      // Approximate the backend's constant colorbalance tint with hue-rotate
      // + extra saturation so preview reads "glitchy" without per-channel
      // shifts (which CSS can't express cheaply).
      filter: "hue-rotate(20deg) saturate(1.4) contrast(1.1)",
    };
  },

  glitch_shake: shakeRecipe(),

  vhs: ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    return {
      opacity: baseOpacity * env,
      translateXPct: 0,
      translateYPct: 0,
      scale: 1,
      filter: "hue-rotate(25deg) saturate(1.3) contrast(0.95)",
    };
  },

  flash_white: ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    // Brightness pulse at the window edges via CSS brightness filter — the
    // backend uses ``eq=brightness=...`` for the same look.
    let brightness = 1;
    if (frame < txFrames) {
      brightness = interpolate(frame, [0, txFrames], [3.0, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else if (frame > durationInFrames - txFrames) {
      brightness = interpolate(
        frame,
        [durationInFrames - txFrames, durationInFrames],
        [1.0, 3.0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
    }
    return {
      opacity: baseOpacity * env,
      translateXPct: 0,
      translateYPct: 0,
      scale: 1,
      filter: `brightness(${brightness.toFixed(3)})`,
    };
  },

  fade_to_black: ({ frame, durationInFrames, txFrames, baseOpacity }) => {
    const env = inOutEnvelope(frame, durationInFrames, txFrames);
    let brightness = 1;
    if (frame < txFrames) {
      brightness = interpolate(frame, [0, txFrames], [0.0, 1.0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    } else if (frame > durationInFrames - txFrames) {
      brightness = interpolate(
        frame,
        [durationInFrames - txFrames, durationInFrames],
        [1.0, 0.0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
    }
    return {
      opacity: baseOpacity * env,
      translateXPct: 0,
      translateYPct: 0,
      scale: 1,
      filter: `brightness(${brightness.toFixed(3)})`,
    };
  },

  whoosh: fadeRecipe, // visual envelope identical to fade; SFX is the differentiator
};

/** Look up a recipe by transition type. Unknown names fall through to
 *  ``cut`` so a frontend bundle that's a step behind the backend still
 *  renders something sensible. */
export function getRecipe(type: TransitionType | string | undefined): Recipe {
  if (!type) return RECIPES.cut;
  return RECIPES[type as TransitionType] ?? RECIPES.cut;
}

/** Compose a recipe frame into CSS for AbsoluteFill consumption. */
export function recipeFrameToStyle(rf: RecipeFrame): React.CSSProperties {
  const transforms: string[] = [];
  if (rf.translateXPct !== 0 || rf.translateYPct !== 0) {
    transforms.push(`translate(${rf.translateXPct}%, ${rf.translateYPct}%)`);
  }
  if (rf.scale !== 1) {
    transforms.push(`scale(${rf.scale.toFixed(4)})`);
  }
  return {
    opacity: rf.opacity,
    transform: transforms.length ? transforms.join(" ") : undefined,
    filter: rf.filter,
    willChange: transforms.length || rf.filter ? "transform, opacity, filter" : undefined,
  };
}

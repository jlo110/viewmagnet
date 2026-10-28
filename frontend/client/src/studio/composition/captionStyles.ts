/**
 * Caption style presets — visual settings for the 7 styles shown in the
 * Studio sidebar. These must stay in lock-step with the ASS style table in
 * `src/features/studio/ass_renderer.py` so the in-browser Remotion preview
 * matches the server-side render byte-for-byte (well, pixel-for-pixel).
 */
import type { CaptionStyleName } from "../types";

export interface CaptionStylePreset {
  name: CaptionStyleName;
  label: string;
  description: string;
  fontFamily: string;
  fontWeight: number;
  textTransform: "none" | "uppercase";
  letterSpacing: string;
  strokeColor: string;
  strokeWidth: number;        // px @ 1080p output
  shadowOffsetY: number;      // px @ 1080p output
  shadowBlur: number;
  shadowColor: string;
  // When `boxed`, each word is wrapped in a solid background block
  // (Hormozi-style). Otherwise, only stroke + shadow.
  boxed: boolean;
  boxColor?: string;
  boxPadding?: string;
  // Per-word "pop" animation parameters
  popScale: number;
  popDurationMs: number;
  popEase: string;
}

export const CAPTION_PRESETS: Record<CaptionStyleName, CaptionStylePreset> = {
  capcut: {
    name: "capcut",
    label: "CapCut",
    description: "Bold word-by-word pop — the viral TikTok look",
    fontFamily: "Montserrat, sans-serif",
    fontWeight: 800,
    textTransform: "none",
    letterSpacing: "0.5px",
    strokeColor: "#000000",
    strokeWidth: 6,
    shadowOffsetY: 4,
    shadowBlur: 0,
    shadowColor: "rgba(0,0,0,0.6)",
    boxed: false,
    popScale: 1.15,
    popDurationMs: 120,
    popEase: "cubic-bezier(.2,1.4,.4,1)",
  },
  mrbeast: {
    name: "mrbeast",
    label: "MrBeast",
    description: "Massive Impact font, yellow + black outline",
    fontFamily: "Impact, 'Arial Black', sans-serif",
    fontWeight: 900,
    textTransform: "uppercase",
    letterSpacing: "1px",
    strokeColor: "#000000",
    strokeWidth: 9,
    shadowOffsetY: 6,
    shadowBlur: 0,
    shadowColor: "rgba(0,0,0,0.85)",
    boxed: false,
    popScale: 1.08,
    popDurationMs: 100,
    popEase: "ease-out",
  },
  hormozi: {
    name: "hormozi",
    label: "Hormozi",
    description: "Solid box backgrounds, alternating colors",
    fontFamily: "'Arial Black', Impact, sans-serif",
    fontWeight: 900,
    textTransform: "uppercase",
    letterSpacing: "1px",
    strokeColor: "transparent",
    strokeWidth: 0,
    shadowOffsetY: 0,
    shadowBlur: 0,
    shadowColor: "transparent",
    boxed: true,
    boxColor: "rgba(0,0,0,0.85)",
    boxPadding: "8px 16px",
    popScale: 1.04,
    popDurationMs: 90,
    popEase: "ease-out",
  },
  neon: {
    name: "neon",
    label: "Neon Glow",
    description: "Glowing edges, retro arcade feel",
    fontFamily: "'Bebas Neue', Impact, sans-serif",
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "2px",
    strokeColor: "#000000",
    strokeWidth: 4,
    shadowOffsetY: 0,
    shadowBlur: 28,
    shadowColor: "currentColor",
    boxed: false,
    popScale: 1.12,
    popDurationMs: 140,
    popEase: "ease-out",
  },
  minimal: {
    name: "minimal",
    label: "Minimal",
    description: "Clean, no stroke, light shadow",
    fontFamily: "Inter, system-ui, sans-serif",
    fontWeight: 600,
    textTransform: "none",
    letterSpacing: "0px",
    strokeColor: "#000000",
    strokeWidth: 2,
    shadowOffsetY: 2,
    shadowBlur: 6,
    shadowColor: "rgba(0,0,0,0.4)",
    boxed: false,
    popScale: 1.03,
    popDurationMs: 110,
    popEase: "ease-out",
  },
  bounce: {
    name: "bounce",
    label: "Bounce",
    description: "Springy text that bounces in",
    fontFamily: "Poppins, sans-serif",
    fontWeight: 800,
    textTransform: "none",
    letterSpacing: "0.5px",
    strokeColor: "#000000",
    strokeWidth: 5,
    shadowOffsetY: 4,
    shadowBlur: 2,
    shadowColor: "rgba(0,0,0,0.5)",
    boxed: false,
    popScale: 1.25,
    popDurationMs: 220,
    popEase: "cubic-bezier(.3,2.2,.5,1)",
  },
  karaoke: {
    name: "karaoke",
    label: "Karaoke",
    description: "Word fills color as it's spoken",
    fontFamily: "Roboto, sans-serif",
    fontWeight: 700,
    textTransform: "none",
    letterSpacing: "0.5px",
    strokeColor: "#000000",
    strokeWidth: 4,
    shadowOffsetY: 3,
    shadowBlur: 4,
    shadowColor: "rgba(0,0,0,0.5)",
    boxed: false,
    popScale: 1.0,
    popDurationMs: 80,
    popEase: "linear",
  },
};

export function getCaptionPreset(name: CaptionStyleName): CaptionStylePreset {
  return CAPTION_PRESETS[name] ?? CAPTION_PRESETS.capcut;
}

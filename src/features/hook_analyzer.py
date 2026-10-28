"""Hook analyzer (Phase 8.6) — score the first seconds of a clip.

Research grounding (docs/research_notes_2026-06.md): ~55% of viewers are gone
by 60s, the scroll-past decision happens in the first ~3-8s, and multimodal
analysis of the "hooking period" is both published (arXiv 2602.22299) and
shipped in production (OpusClip's LLM-as-judge). This is the packaging-rubric
pattern applied to the opening: deterministic signal + LLM rubric + fixes.

Two layers, composed:
1. **Deterministic visual metrics** from sampled frames (cv2): motion energy,
   hard-cut count, brightness/contrast. Pure functions on numpy arrays —
   testable without video files, no LLM needed.
2. **LLM rubric** on the verbal/textual hook (transcript snippet + title),
   WITH the visual metrics injected as context so the judge reasons over both
   modalities despite the text-only LLM client. Degrades gracefully when the
   LLM is unavailable (visual metrics still returned).
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

HOOK_SECONDS = 8.0     # analysis window (3s is the scroll decision; 8s = grace)
FRAME_FPS = 2.0        # sample rate within the window
CUT_THRESHOLD = 0.35   # normalized inter-frame diff that counts as a hard cut

_SYSTEM = (
    "You are a short-form video editor who has studied thousands of viral "
    "openings. You judge ONLY the first seconds of a video — the hook — on "
    "whether a scrolling viewer would stop. Principles: instant clarity (what "
    "is this, in one second); a curiosity gap or stakes stated immediately "
    "(not a slow intro, never a logo); visual energy (motion, cuts, faces); "
    "and a payoff promise the rest of the video must deliver. Most hooks are "
    "weak — score honestly."
)

_DIMENSIONS = ("instant_clarity", "curiosity_or_stakes", "visual_energy", "payoff_promise")


# ---------------------------------------------------------------------------
# Layer 1: deterministic visual metrics (pure)
# ---------------------------------------------------------------------------
def frame_metrics(frames: List[np.ndarray]) -> Optional[dict]:
    """Visual-energy metrics from a sequence of grayscale (H, W) frames.

    - ``motion_score``: mean normalized abs-diff between consecutive frames
      (0 = static slideshow, ~0.1+ = energetic)
    - ``cut_count``: diffs above CUT_THRESHOLD (hard cuts / scene changes)
    - ``brightness``: mean luminance (0-1); very dark openings underperform
    - ``contrast``: mean per-frame std (0-1); flat gray frames don't pop
    """
    if not frames or len(frames) < 2:
        return None
    arr = [np.asarray(f, dtype=np.float32) / 255.0 for f in frames]
    diffs = [float(np.mean(np.abs(b - a))) for a, b in zip(arr, arr[1:])]
    return {
        "motion_score": round(float(np.mean(diffs)), 4),
        "cut_count": int(sum(d > CUT_THRESHOLD for d in diffs)),
        "brightness": round(float(np.mean([a.mean() for a in arr])), 4),
        "contrast": round(float(np.mean([a.std() for a in arr])), 4),
        "frames_analyzed": len(frames),
    }


def extract_frames(
    video_path: str, seconds: float = HOOK_SECONDS, fps: float = FRAME_FPS
) -> List[np.ndarray]:
    """Sample grayscale frames from the first ``seconds`` of a video file."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(native_fps / fps)))
        max_frames = int(seconds * native_fps)
        frames: List[np.ndarray] = []
        idx = 0
        while idx < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            idx += 1
        return frames
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Layer 2: LLM rubric (visual metrics injected as context)
# ---------------------------------------------------------------------------
def _visual_summary(metrics: Optional[dict]) -> str:
    if not metrics:
        return "No visual metrics available."
    energy = (
        "static/slideshow-like" if metrics["motion_score"] < 0.02
        else "moderate motion" if metrics["motion_score"] < 0.08
        else "high motion/energetic"
    )
    return (
        f"Measured visuals over the first {HOOK_SECONDS:.0f}s: {energy} "
        f"(motion={metrics['motion_score']}), {metrics['cut_count']} hard cut(s), "
        f"brightness={metrics['brightness']} (0-1), contrast={metrics['contrast']}."
    )


def analyze_hook(
    transcript: Optional[str] = None,
    title: Optional[str] = None,
    visual_metrics: Optional[dict] = None,
    user_id: Optional[int] = None,
    plan: str = "free",
) -> dict:
    """Score a hook from its opening transcript + title + measured visuals.

    Returns per-dimension scores, the biggest fix, and rewritten opening lines.
    ``visual_metrics`` (from :func:`frame_metrics`) are passed into the prompt;
    if the LLM is unavailable the metrics-only report is still returned.
    """
    from src.features.llm_client import get_llm_client

    transcript = (transcript or "").strip()[:1500]
    title = (title or "").strip()

    out: dict = {"visual_metrics": visual_metrics, "hook_seconds": HOOK_SECONDS}
    if not transcript and not title and not visual_metrics:
        out["error"] = "nothing_to_analyze"
        return out

    user_prompt = f"""Judge this video's HOOK (the first ~{HOOK_SECONDS:.0f} seconds).

Title: "{title or '(none provided)'}"
Opening transcript/spoken words: "{transcript or '(none provided)'}"
{_visual_summary(visual_metrics)}

Score each dimension 0-10 and respond with ONLY valid JSON:
{{
  "instant_clarity": {{"score": <0-10>, "note": "..."}},
  "curiosity_or_stakes": {{"score": <0-10>, "note": "..."}},
  "visual_energy": {{"score": <0-10>, "note": "..."}},
  "payoff_promise": {{"score": <0-10>, "note": "..."}},
  "biggest_fix": "the single highest-impact change to the first 3 seconds",
  "stronger_openings": ["2-3 rewritten opening lines that hook harder"]
}}"""

    llm = get_llm_client().generate_json(
        _SYSTEM, user_prompt, max_tokens=900, temperature=0.5,
        user_id=user_id, plan=plan, feature="hook_analyzer",
    )
    if not llm:
        logger.warning("hook_analyzer.empty_llm")
        out["overall_score"] = None
        out["error"] = "llm_unavailable"
        return out

    scores = []
    for d in _DIMENSIONS:
        try:
            scores.append(float(llm.get(d, {}).get("score", 0)))
        except (TypeError, ValueError):
            scores.append(0.0)
    out.update({
        "overall_score": round(sum(scores) / len(scores) * 10) if scores else 0,
        "dimensions": {d: llm.get(d) for d in _DIMENSIONS},
        "biggest_fix": llm.get("biggest_fix", ""),
        "stronger_openings": [s for s in (llm.get("stronger_openings") or []) if s][:3],
    })
    return out


def analyze_clip_file(
    video_path: str,
    transcript: Optional[str] = None,
    title: Optional[str] = None,
    user_id: Optional[int] = None,
    plan: str = "free",
) -> dict:
    """Full pipeline for an uploaded clip: frames → metrics → rubric."""
    try:
        frames = extract_frames(video_path)
        metrics = frame_metrics(frames)
    except Exception as e:  # frame extraction must not kill the rubric
        logger.warning("hook_analyzer.frames_failed", error=str(e)[:120])
        metrics = None
    return analyze_hook(
        transcript=transcript, title=title, visual_metrics=metrics,
        user_id=user_id, plan=plan,
    )

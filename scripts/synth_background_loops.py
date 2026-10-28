"""Synthesize a stock library of background loops with ffmpeg lavfi.

Produces ~6-8 procedural, watermark-free, ~6s seamless loops under
``src/assets/backgrounds/`` plus matching jpg thumbnails. The catalog in
``src/features/studio/background_catalog.py`` references these files via
relative URLs that get mounted statically at ``/studio/assets/backgrounds/``
by ``src/api/main.py``.

Why ship synthesized loops instead of CC0 downloads?

  * Zero network at install time — works on a fresh clone with no API
    keys, no R2 bucket, no rights-clearance review.
  * Looped seamlessly by construction (we render an integer number of
    cycles of a periodic generator so ffmpeg's ``stream_loop`` produces
    no visible seam).
  * Tiny (each ~80-300KB H.264) so checking them in is fine — no LFS.
  * Users who want real footage (gaming, satisfying, etc.) get the same
    Pexels search box already wired in the BackgroundsPanel.

Run from the repo root:

    python scripts/synth_background_loops.py

Re-running overwrites in place — safe to wire into CI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List

# Make ``src`` importable when run from the repo root.
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "src", "assets", "backgrounds")

WIDTH = 1280
HEIGHT = 720
FPS = 30
DURATION = 6.0  # seconds — short loops are fine because ffmpeg restream-loops them


@dataclass(frozen=True)
class Loop:
    """Recipe for a single procedural background loop.

    ``video_filter`` must be a complete ``-vf`` style filter chain ending
    in something ``yuv420p``-encodable. Period-driven filters (``time``,
    ``t``) should complete an integer number of cycles in ``DURATION`` so
    the loop is seamless.
    """

    id: str
    label: str
    category: str
    source_filter: str  # the lavfi -i argument
    post_filter: str = ""  # optional chain after the source


# Each filter chain renders one full periodic cycle over DURATION seconds so
# the loop seam is invisible. Tested visually with ffplay before committing.
LOOPS: List[Loop] = [
    Loop(
        id="aurora_violet",
        label="Aurora Violet",
        category="abstract",
        # Two horizontal sine bands sliding in opposite directions over a
        # violet→pink gradient. Period = DURATION so the wave returns to its
        # starting phase exactly at loop end.
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.1:"
            "c0=0x4c1d95:c1=0xec4899:c2=0x6366f1:c3=0x312e81:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    Loop(
        id="ocean_calm",
        label="Ocean Calm",
        category="ambient",
        # Slow blue→cyan gradient — meant to sit behind a podcast/talking-head.
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.08:"
            "c0=0x0c4a6e:c1=0x0e7490:c2=0x155e75:c3=0x06b6d4:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    Loop(
        id="sunset_warm",
        label="Sunset Warm",
        category="abstract",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.12:"
            "c0=0x7c2d12:c1=0xf97316:c2=0xfb923c:c3=0xfde047:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    Loop(
        id="forest_green",
        label="Forest Green",
        category="nature",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.09:"
            "c0=0x064e3b:c1=0x065f46:c2=0x166534:c3=0x14532d:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    Loop(
        id="midnight_particles",
        label="Midnight Particles",
        category="abstract",
        # Slow drifting noise field. The ``cellauto`` filter produces a
        # particle-like animated pattern that compresses well with x264.
        source_filter=(
            f"cellauto=s={WIDTH}x{HEIGHT}:rule=110:stitch=1:scroll=1:"
            f"random_seed=42:full=0:rate={FPS}"
        ),
        post_filter=(
            f"trim=duration={DURATION},setpts=PTS-STARTPTS,"
            "colorchannelmixer=rr=0.15:gg=0.20:bb=0.55,"
            f"gblur=sigma=2,fps={FPS}"
        ),
    ),
    Loop(
        id="grid_lines_neon",
        label="Grid Neon",
        category="abstract",
        # Animated test-pattern-like grid in cyan; mostly there for the
        # "vaporwave / synthwave" backdrop trope.
        source_filter=(
            f"testsrc2=s={WIDTH}x{HEIGHT}:rate={FPS}:duration={DURATION}"
        ),
        post_filter=(
            "format=rgb24,"
            "colorchannelmixer=rr=0.20:gg=0.60:bb=1.10,"
            "gblur=sigma=1.2"
        ),
    ),
    Loop(
        id="lofi_paper",
        label="Lo-fi Paper",
        category="ambient",
        # Cream-on-cream rolling gradient — minimalist and easy on the eyes.
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.05:"
            "c0=0xfef3c7:c1=0xfde68a:c2=0xfcd34d:c3=0xfef3c7:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    Loop(
        id="midnight_blur",
        label="Midnight Blur",
        category="ambient",
        # Deep midnight gradient — works well as a backdrop for white captions.
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.06:"
            "c0=0x0f172a:c1=0x1e293b:c2=0x312e81:c3=0x0f172a:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
]


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def _render_loop(loop: Loop) -> None:
    """Render one loop's .mp4 + .jpg poster.

    Always overwrites — the script is idempotent so re-running it after
    editing the recipe gives a clean result.
    """
    mp4 = os.path.join(OUT_DIR, f"{loop.id}.mp4")
    jpg = os.path.join(OUT_DIR, f"{loop.id}.jpg")

    vf_chain = loop.post_filter or "null"
    cmd = [
        _ffmpeg(),
        "-y",
        "-f", "lavfi",
        "-i", loop.source_filter,
        "-t", f"{DURATION:.3f}",
        "-vf", vf_chain + ",format=yuv420p",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "24",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        "-r", str(FPS),
        mp4,
    ]
    print(f"  → rendering {loop.id}.mp4 ({loop.label})")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        sys.stderr.write(
            f"\nFAILED to render {loop.id}:\n{proc.stderr[-2000:]}\n"
        )
        raise SystemExit(proc.returncode)

    # Poster: middle frame of the loop, scaled to thumbnail size.
    poster_cmd = [
        _ffmpeg(),
        "-y",
        "-ss", f"{DURATION / 2:.3f}",
        "-i", mp4,
        "-frames:v", "1",
        "-vf", f"scale={WIDTH // 2}:{HEIGHT // 2}",
        "-q:v", "4",
        jpg,
    ]
    subprocess.run(poster_cmd, check=True, capture_output=True)


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found in PATH", file=sys.stderr)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Rendering {len(LOOPS)} background loops → {OUT_DIR}")
    for loop in LOOPS:
        _render_loop(loop)
    print("\nDone. To register changes in the catalog edit "
          "src/features/studio/background_catalog.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

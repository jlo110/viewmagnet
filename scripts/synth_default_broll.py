"""Synthesize a default B-roll quick-pick library with ffmpeg lavfi.

Renders ~8 short procedural clips into ``src/assets/broll/`` plus jpg
posters. These are intentionally generic (color swatches, motion bands,
gradient sweeps, ticker shapes) so users can click any of them to instantly
have something on the B-roll lane to experiment with transitions.

The Pexels search box in the B-roll panel remains the primary path for
real footage; this set just removes the "blank page" problem (and the
need for a working PEXELS_API_KEY) when a user first opens Studio.

Run from repo root:

    python scripts/synth_default_broll.py

Idempotent — re-runs overwrite in place.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List

REPO_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "src", "assets", "broll")

WIDTH = 1280
HEIGHT = 720
FPS = 30
DURATION = 4.0


@dataclass(frozen=True)
class BRoll:
    """Recipe for one default B-roll quick-pick clip.

    Each one is short (4s) and self-contained so the transition between
    main + B-roll has clear visual contrast — this is the whole point of
    having a starter library bundled.
    """

    id: str
    label: str
    category: str
    description: str
    source_filter: str
    post_filter: str = ""


# Curated so the set spans different vibes: warm/cool/neon/dark/etc.
CLIPS: List[BRoll] = [
    BRoll(
        id="confetti_pop",
        label="Confetti Pop",
        category="celebration",
        description="High-energy multicolor swatch — great for milestones.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.6:"
            "c0=0xfb7185:c1=0xfacc15:c2=0x4ade80:c3=0x60a5fa:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    BRoll(
        id="city_motion",
        label="City Motion",
        category="urban",
        description="Cool slate sweep — works under a voiceover B-roll moment.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.5:"
            "c0=0x1e293b:c1=0x334155:c2=0x475569:c3=0x0f172a:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    BRoll(
        id="sunrise_warm",
        label="Sunrise Warm",
        category="ambient",
        description="Warm orange-to-pink sunrise palette.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.4:"
            "c0=0xb91c1c:c1=0xf59e0b:c2=0xfbbf24:c3=0xfb7185:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    BRoll(
        id="neon_cyber",
        label="Neon Cyber",
        category="tech",
        description="Magenta + cyan synthwave grid for tech / gaming clips.",
        source_filter=(
            f"testsrc2=s={WIDTH}x{HEIGHT}:rate={FPS}:duration={DURATION}"
        ),
        post_filter=(
            "format=rgb24,colorchannelmixer=rr=0.20:gg=0.55:bb=1.1,"
            "gblur=sigma=0.8"
        ),
    ),
    BRoll(
        id="forest_walk",
        label="Forest Walk",
        category="nature",
        description="Deep emerald gradient — nature / wellness vibes.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.35:"
            "c0=0x065f46:c1=0x166534:c2=0x14532d:c3=0x064e3b:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    BRoll(
        id="money_glow",
        label="Money Glow",
        category="finance",
        description="Emerald + gold gradient — finance / business context.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.45:"
            "c0=0x064e3b:c1=0x10b981:c2=0xfde047:c3=0x065f46:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
    BRoll(
        id="lava_lamp",
        label="Lava Lamp",
        category="ambient",
        description="Slow red/orange blob motion. Looks great muted.",
        source_filter=(
            f"cellauto=s={WIDTH}x{HEIGHT}:rule=30:stitch=1:scroll=1:"
            f"random_seed=7:full=0:rate={FPS}"
        ),
        post_filter=(
            f"trim=duration={DURATION},setpts=PTS-STARTPTS,"
            "colorchannelmixer=rr=1.2:gg=0.3:bb=0.1,"
            f"gblur=sigma=3,fps={FPS}"
        ),
    ),
    BRoll(
        id="paper_minimal",
        label="Paper Minimal",
        category="minimal",
        description="Warm cream tones — minimalist B-roll underneath text.",
        source_filter=(
            f"gradients=s={WIDTH}x{HEIGHT}:duration={DURATION}:speed=0.3:"
            "c0=0xfef3c7:c1=0xfde68a:c2=0xfcd34d:c3=0xfde68a:nb_colors=4:"
            f"r={FPS}"
        ),
    ),
]


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def _render(clip: BRoll) -> None:
    mp4 = os.path.join(OUT_DIR, f"{clip.id}.mp4")
    jpg = os.path.join(OUT_DIR, f"{clip.id}.jpg")
    vf_chain = clip.post_filter or "null"
    cmd = [
        _ffmpeg(),
        "-y",
        "-f", "lavfi",
        "-i", clip.source_filter,
        "-t", f"{DURATION:.3f}",
        "-vf", vf_chain + ",format=yuv420p",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        "-r", str(FPS),
        mp4,
    ]
    print(f"  → rendering {clip.id}.mp4 ({clip.label})")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        sys.stderr.write(f"\nFAILED {clip.id}:\n{proc.stderr[-2000:]}\n")
        raise SystemExit(proc.returncode)

    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-ss", f"{DURATION / 2:.3f}",
            "-i", mp4,
            "-frames:v", "1",
            "-vf", f"scale={WIDTH // 2}:{HEIGHT // 2}",
            "-q:v", "4",
            jpg,
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found in PATH", file=sys.stderr)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Rendering {len(CLIPS)} default B-roll clips → {OUT_DIR}")
    for clip in CLIPS:
        _render(clip)
    print("\nDone. Edit src/features/studio/broll_library.py to register changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

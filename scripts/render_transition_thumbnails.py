"""Render webm thumbnails for every entry in TRANSITION_CATALOG.

Outputs to ``frontend/client/public/transitions/<thumbnail>`` so the
Effects panel's TransitionGrid cards can play a real preview of each
effect (matching the catalog's ``thumbnail`` field).

Usage (one-shot):
    python scripts/render_transition_thumbnails.py

Notes:
  - Uses two short ffmpeg lavfi sources (red mandelbrot for the "main"
    track, colorful testsrc for the "b-roll") so every transition has
    visible contrast at its in/out edges.
  - Output: 320x180 (16:9 mini-preview), VP9 webm, ~1.6s duration, no
    audio. Small files (~30-80KB each) check into git fine.
  - Thumbnails are deterministic — re-running the script overwrites
    in-place so the panel keeps matching the catalog without manual
    intervention when a new transition is added.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from typing import Dict

# Make sure src/ is importable when running from the repo root.
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from src.features.studio.render import _cmd_unified, _ffmpeg_bin  # noqa: E402
from src.features.studio.spec import EditSpec  # noqa: E402
from src.features.studio.transition_catalog import TRANSITION_CATALOG  # noqa: E402

OUT_W, OUT_H = 320, 180
DURATION = 1.6
PUBLIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "client",
    "public",
    "transitions",
)


def _generate_sources(ff: str, workdir: str) -> tuple[str, str]:
    """Render the shared main+broll lavfi sources once per script run."""
    main_path = os.path.join(workdir, "main.mp4")
    broll_path = os.path.join(workdir, "broll.mp4")
    subprocess.run(
        [
            ff,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"mandelbrot=size={OUT_W * 4}x{OUT_H * 4}:rate=30",
            "-t",
            f"{DURATION + 0.5:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            main_path,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            ff,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={OUT_W * 4}x{OUT_H * 4}:rate=30",
            "-t",
            f"{DURATION + 0.5:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            broll_path,
        ],
        check=True,
        capture_output=True,
    )
    return main_path, broll_path


def _build_spec(tx_name: str) -> EditSpec:
    """Spec preconfigured to show ONE B-roll fade-in/out using ``tx_name``."""
    return EditSpec.model_validate(
        {
            "clip": {
                "key": "thumb",
                "source_url": "lavfi://noop",
                "start_time": 0.0,
                "end_time": DURATION,
                "duration_seconds": DURATION,
                "video_width": OUT_W * 4,
                "video_height": OUT_H * 4,
                "fps": 30.0,
            },
            "broll": {
                # Mount the b-roll for the FULL preview window so the
                # transition's in/out animations both play within the
                # visible duration (4:1 inset at start/end).
                "clips": [
                    {
                        "start": 0.0,
                        "end": DURATION,
                        "clip_url": "lavfi://noop",
                    }
                ],
            },
            "transitions": {
                "enabled": True,
                "type": tx_name,
                "duration_ms": 350,
                "sfx_enabled": False,
            },
            "captions": {"enabled": False},
        }
    )


def _render_one(ff: str, tx_name: str, thumbnail: str, main_src: str, broll_src: str) -> str:
    spec = _build_spec(tx_name)
    with tempfile.TemporaryDirectory(prefix=f"thumb_{tx_name}_") as workdir:
        out_mp4 = os.path.join(workdir, "thumb.mp4")
        cmd = _cmd_unified(
            input_path=main_src,
            ass_path=None,
            spec=spec,
            active_broll=[(0, spec.broll.clips[0], broll_src)],
            bg_local=None,
            out_w=OUT_W,
            out_h=OUT_H,
            output_path=out_mp4,
            tracking=None,
            duration=DURATION,
        )
        # Replace the libx264 output with VP9/webm so the panel can
        # autoplay loops cheaply in Chromium/Safari without an MP4 codec
        # dependency. Easiest path: render mp4 first, then transcode.
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg main pass failed for {tx_name}:\n{r.stderr.decode()[-800:]}"
            )

        os.makedirs(PUBLIC_DIR, exist_ok=True)
        out_webm = os.path.join(PUBLIC_DIR, thumbnail)
        r = subprocess.run(
            [
                ff,
                "-y",
                "-i",
                out_mp4,
                "-c:v",
                "libvpx-vp9",
                "-b:v",
                "300k",
                "-crf",
                "32",
                "-an",
                "-row-mt",
                "1",
                "-deadline",
                "realtime",
                "-cpu-used",
                "5",
                out_webm,
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg webm transcode failed for {tx_name}:\n{r.stderr.decode()[-800:]}"
            )
        return out_webm


def main(only: list[str] | None = None) -> None:
    ff = _ffmpeg_bin()
    targets: Dict[str, str] = {
        name: tdef.thumbnail
        for name, tdef in TRANSITION_CATALOG.items()
        if not only or name in only
    }
    print(f"Rendering {len(targets)} thumbnails to {PUBLIC_DIR}")

    with tempfile.TemporaryDirectory(prefix="studio_thumbnails_") as workdir:
        main_src, broll_src = _generate_sources(ff, workdir)
        for name, thumb in targets.items():
            print(f"  • {name:>14} → {thumb}", end="", flush=True)
            try:
                path = _render_one(ff, name, thumb, main_src, broll_src)
                size_kb = os.path.getsize(path) // 1024
                print(f"  ✓ ({size_kb}KB)")
            except Exception as exc:
                print(f"  ✗ {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        help="Only render these transition names (default: every entry).",
    )
    args = parser.parse_args()
    main(only=args.only or None)

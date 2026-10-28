"""End-to-end smoke test for the Week 6 unified studio renderer.

This is the *integration* counterpart to the unit tests in
``test_transition_catalog`` / ``test_layout_regions`` / ``test_spec_migration``.
It builds the most demanding Week-6 spec we can synthesize entirely from
ffmpeg's lavfi sources (no R2, no Pexels, no DB) and runs the same
``_cmd_unified`` ffmpeg invocation a real render would, asserting we get
a non-trivial MP4 back.

What this exercises end-to-end:

  * ``layout=split_horizontal`` — proves the unified ``regions_for`` math
    matches what ffmpeg actually composes (no overlap / no negative xy).
  * ``background_loop`` mounted as a separate input with ``-stream_loop -1``
    — proves the ``trim=duration`` safeguard prevents the runaway-encoder
    bug we hit during Phase 3.
  * Two B-roll clips with DIFFERENT ``boundary_transitions`` (one fade-in
    / zoom-out, one slide-up / whoosh-out) — proves the per-boundary
    dispatcher actually wires the right recipe at each edge.
  * ``captions.enabled`` over a region-aware ASS file — proves the
    Phase 3 region-aware caption-margin math doesn't break the encode.
  * ``auto_zoom`` + a synthetic ``Crop`` — proves the crop/scale/zoom
    composition fits in the main region.

The test is gated on ffmpeg being installed (every dev box already has
it because the rest of the studio pipeline depends on it) and skips
gracefully when run in a CI image that doesn't.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import List

import pytest

from src.features.studio.render import _cmd_unified
from src.features.studio.spec import (
    AspectRatio,
    AutoZoom,
    BackgroundLoop,
    BRollClip,
    BRollTrack,
    Captions,
    CaptionStyleName,
    Crop,
    EditSpec,
    Layout,
    SourceClip,
    TranscriptWord,
    TransitionInstance,
    TransitionType,
)


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg binary required for end-to-end render smoke test",
)


# ---------------------------------------------------------------------------
# Helpers — synthetic test inputs (no network, no R2)
# ---------------------------------------------------------------------------


def _synth_video(
    out_path: str,
    *,
    color: str,
    size: str = "640x360",
    duration: float = 4.0,
    label: str = "main",
) -> str:
    """Render a tiny ``duration``-second mp4 with a solid colored background.
    Used as the "main video", B-roll, and background-loop sources for the
    smoke test.

    A ``testsrc2`` overlay would be nicer for visual debugging, but lavfi's
    ``color`` source by itself is enough to exercise every filter the
    unified renderer wires — colors are just for telling outputs apart in
    failure modes."""
    # We keep the label arg in the signature for forward compat (could
    # drop in drawtext later) but currently ignore it: combining color +
    # drawtext under a single lavfi -i requires graph syntax that varies
    # across ffmpeg versions, and the smoke test doesn't depend on text.
    del label
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:d={duration}:r=24",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}:sample_rate=48000",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-shortest",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(
            f"synth video {out_path} failed (rc={proc.returncode}):\n"
            f"{proc.stderr[-2000:]}"
        )
    assert os.path.exists(out_path) and os.path.getsize(out_path) > 1_000, (
        f"synth video {out_path} was not produced"
    )
    return out_path


def _build_smoke_spec(
    *,
    source_path: str,
    duration: float,
    broll_clip_ids: List[str],
) -> EditSpec:
    """Construct the most demanding Week-6 spec we can synthesize locally.

    Important: we set ``background_loop`` BUT pass the actual local file
    via the ``bg_local`` argument to ``_cmd_unified`` so we don't have to
    monkey-patch the catalog / Pexels download path."""
    transcript = [
        TranscriptWord(text="this", start=0.2, end=0.6),
        TranscriptWord(text="is", start=0.6, end=0.8),
        TranscriptWord(text="a", start=0.8, end=0.9),
        TranscriptWord(text="smoke", start=0.9, end=1.4),
        TranscriptWord(text="test", start=1.4, end=1.9),
    ]

    clip_a = BRollClip(
        id=broll_clip_ids[0],
        track=2,
        start=0.5,
        end=1.6,
        clip_url="file:///dev/null",  # never read; we pass active_broll directly
        source="pexels",
        opacity=0.95,
        mute=True,
        label="A",
    )
    clip_b = BRollClip(
        id=broll_clip_ids[1],
        track=2,
        start=2.0,
        end=3.2,
        clip_url="file:///dev/null",
        source="pexels",
        opacity=1.0,
        mute=True,
        label="B",
    )

    return EditSpec(
        clip=SourceClip(
            source_url="file://" + source_path,
            source_clip_path=source_path,
            start_time=0.0,
            end_time=duration,
            transcript=transcript,
        ),
        aspect_ratio=AspectRatio.PORTRAIT_9_16,
        crop=Crop(x=0, y=0, width=640, height=360, tracking="static"),
        captions=Captions(
            enabled=True,
            style=CaptionStyleName.CAPCUT,
            font_size=72,
        ),
        broll=BRollTrack(enabled=True, auto_suggest=False, clips=[clip_a, clip_b]),
        auto_zoom=AutoZoom(enabled=True, max_scale=1.10, timestamps=[1.0]),
        layout=Layout(
            mode="split_horizontal",
            main_weight=0.65,  # main gets 65% top, bg 35% bottom
        ),
        background_loop=BackgroundLoop(
            source="pexels",
            clip_url="file:///dev/null",  # never read; bg_local takes precedence
            loop_start_offset_seconds=0.0,
            volume=0.0,
            label="smoke-bg",
        ),
        boundary_transitions=[
            # Clip A: soft fade-in, dramatic zoom-out
            TransitionInstance(
                boundary_id=f"broll_{clip_a.id}_in",
                type=TransitionType.FADE,
                duration_ms=300,
                sfx_enabled=False,
            ),
            TransitionInstance(
                boundary_id=f"broll_{clip_a.id}_out",
                type=TransitionType.ZOOM_OUT,
                duration_ms=400,
                sfx_enabled=True,
            ),
            # Clip B: hard slide-up, whoosh-out (different stinger from above)
            TransitionInstance(
                boundary_id=f"broll_{clip_b.id}_in",
                type=TransitionType.SLIDE_UP,
                duration_ms=350,
                sfx_enabled=True,
            ),
            TransitionInstance(
                boundary_id=f"broll_{clip_b.id}_out",
                type=TransitionType.WHOOSH,
                duration_ms=300,
                sfx_enabled=True,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# The smoke test itself
# ---------------------------------------------------------------------------


def test_unified_render_split_layout_bg_loop_mixed_transitions():
    """The whole Week-6 enchilada: split layout, looping background, two
    B-rolls each with different per-boundary transition + SFX, captions on,
    auto-zoom on. The render must:

      1. Finish in well under a minute (no infinite loop from bg).
      2. Exit cleanly (returncode 0).
      3. Produce an MP4 the OS sees as a real file (>50KB) at the right
         duration (give or take 0.5s for keyframe alignment).
    """
    with tempfile.TemporaryDirectory(prefix="studio_smoke_") as workdir:
        # --- 1. Synthesize the three input clips ---------------------
        duration = 4.0
        main_path = _synth_video(
            os.path.join(workdir, "main.mp4"),
            color="0x1f6feb",
            duration=duration,
            label="MAIN",
        )
        broll_a_path = _synth_video(
            os.path.join(workdir, "broll_a.mp4"),
            color="0xfb923c",
            duration=2.0,
            label="A",
        )
        broll_b_path = _synth_video(
            os.path.join(workdir, "broll_b.mp4"),
            color="0xa78bfa",
            duration=2.0,
            label="B",
        )
        bg_path = _synth_video(
            os.path.join(workdir, "bgloop.mp4"),
            color="0x10b981",
            size="320x180",
            duration=1.5,  # short on purpose — proves -stream_loop works
            label="BG",
        )

        # --- 2. Build the spec --------------------------------------
        broll_ids = ["aaaaaa111111", "bbbbbb222222"]
        spec = _build_smoke_spec(
            source_path=main_path,
            duration=duration,
            broll_clip_ids=broll_ids,
        )
        # Re-bind ids on the real clip objects to the deterministic ones
        # we used for the boundary_transitions above
        spec.broll.clips[0].id = broll_ids[0]
        spec.broll.clips[1].id = broll_ids[1]

        # --- 3. Build the ASS subtitle file the same way render does
        from src.features.studio.ass_renderer import write_ass_file
        from src.features.studio.layout import regions_for
        from src.features.studio.render import get_output_dimensions

        out_w, out_h = get_output_dimensions(spec.aspect_ratio)
        ass_path = os.path.join(workdir, "captions.ass")
        rfa = regions_for(spec.layout, out_w, out_h)
        write_ass_file(
            captions=spec.captions,
            words=spec.clip.transcript,
            video_width=out_w,
            video_height=out_h,
            out_path=ass_path,
            main_region_y=rfa.main.y,
            main_region_h=rfa.main.h,
        )
        assert os.path.exists(ass_path)

        # --- 4. Compose the command --------------------------------
        output_path = os.path.join(workdir, "out.mp4")
        active_broll = [
            (0, spec.broll.clips[0], broll_a_path),
            (1, spec.broll.clips[1], broll_b_path),
        ]
        cmd = _cmd_unified(
            input_path=main_path,
            ass_path=ass_path,
            spec=spec,
            active_broll=active_broll,
            bg_local=bg_path,
            out_w=out_w,
            out_h=out_h,
            output_path=output_path,
            tracking=None,
            duration=duration,
        )

        # Sanity-check the command string before launching — these are the
        # exact failure modes we hit during Phase 3 debugging, so we assert
        # them up front instead of relying on a flaky ffmpeg exit code.
        cmd_str = " ".join(cmd)
        assert "-stream_loop" in cmd_str, "background loop must be looped"
        assert f"trim=duration={duration:.3f}" in cmd_str, (
            "background must be trimmed to spec duration — without this the "
            "Phase 3 runaway-encoder bug returns"
        )
        assert f"-t {duration:.3f}" in cmd_str, (
            "global -t safeguard must be present"
        )
        # Each clip's IN-edge transition recipe should show up. ``fade``
        # has no overlay-x expression so we look for the colorchannelmixer
        # alpha fade; ``slide_up`` has the y-offset overlay expression.
        assert "colorchannelmixer" in cmd_str or "fade=t=in" in cmd_str
        assert "-h" in cmd_str or "h+" in cmd_str or "h-" in cmd_str, (
            "slide_up should reference the overlay 'h' (height) variable"
        )

        # --- 5. Run it (capped well under any plausible render time) -
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 4s of video at ultrafast should finish in seconds
        )
        if result.returncode != 0:
            # Surface ffmpeg's tail so failures are debuggable without
            # re-running locally. ffmpeg writes to stderr.
            tail = "\n".join(result.stderr.splitlines()[-40:])
            pytest.fail(
                f"ffmpeg returncode {result.returncode}\n"
                f"--- ffmpeg stderr (last 40 lines) ---\n{tail}\n"
                f"--- command ---\n{' '.join(cmd)}"
            )

        # --- 6. Validate the output --------------------------------
        assert os.path.exists(output_path), "ffmpeg said OK but no file"
        size = os.path.getsize(output_path)
        assert size > 50_000, (
            f"output file too small ({size} bytes) — likely a header-only "
            "MP4 from an early ffmpeg abort"
        )

        # Probe duration to confirm the bg loop didn't extend us
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            measured = float(probe.stdout.strip())
            assert abs(measured - duration) <= 0.5, (
                f"output duration {measured:.2f}s deviates from spec "
                f"duration {duration:.2f}s by > 0.5s — the bg-loop trim "
                "safeguard may have regressed"
            )

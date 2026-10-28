"""Clip extraction, enhancement, caption files and editor exports."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List, Optional

import structlog

from src.features.shorts.models import Highlight, ShortsAnalysis

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to an SRT-formatted timestamp."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(transcript_data: Dict) -> str:
    """Render an SRT caption file from a structured transcript."""
    segments = transcript_data.get("segments", [])
    if not segments:
        return ""

    srt_lines: List[str] = []
    counter = 0
    for segment in segments:
        text = segment["text"].strip()
        if not text:
            continue
        counter += 1
        start_ts = seconds_to_srt_time(segment["start"])
        end_ts = seconds_to_srt_time(segment["end"])
        srt_lines.append(str(counter))
        srt_lines.append(f"{start_ts} --> {end_ts}")
        srt_lines.append(text)
        srt_lines.append("")
    return "\n".join(srt_lines)


# ---------------------------------------------------------------------------
# Clip enhancement (crop coordinates + titles)
# ---------------------------------------------------------------------------


def _generate_clip_title(clip: Highlight, video_title: str, clip_num: int) -> str:
    text = clip.transcript
    if "?" in text:
        sentences = re.split(r"[.!]", text)
        for s in sentences:
            if "?" in s:
                return s.strip()[:50]

    sentences = re.split(r"[.!?]", text)
    if sentences:
        first = sentences[0].strip()
        if len(first) > 10:
            return first[:50] + ("..." if len(first) > 50 else "")

    return f"{video_title} - Part {clip_num}"


def enhance_clips(
    clips: List[Highlight],
    video_title: str,
    video_path: Optional[str] = None,
    use_smart_tracking: bool = False,
) -> List[Highlight]:
    """Populate crop coordinates and suggested titles, optionally via SubjectTracker."""
    import numpy as np

    original_width = 1920
    original_height = 1080
    crop_height = original_height
    crop_width = int(crop_height * 9 / 16)
    default_crop_x = (original_width - crop_width) // 2

    tracking_results = None
    if use_smart_tracking and video_path and os.path.exists(video_path):
        try:
            from src.features.subject_tracker import SubjectTracker, TrackingMode

            logger.info("shorts.clip.smart_tracking.start", clips=len(clips))
            tracker = SubjectTracker(
                mode=TrackingMode.SPEAKER,
                smoothing_window=15,
                max_velocity=50.0,
                detection_interval=5,
            )
            clip_times = [(clip.start_time, clip.end_time) for clip in clips]
            tracking_results = tracker.track_multiple_clips(
                video_path, clip_times, target_ratio=(9, 16)
            )
        except ImportError as exc:
            logger.warning(
                "shorts.clip.smart_tracking.unavailable", error=str(exc)
            )
            tracking_results = None
        except Exception as exc:
            logger.error("shorts.clip.smart_tracking.failed", error=str(exc))
            tracking_results = None

    for i, clip in enumerate(clips):
        clip.crop_width = crop_width
        clip.crop_height = crop_height

        if tracking_results and i < len(tracking_results):
            tracking = tracking_results[i]
            if tracking.smoothed_crop_positions:
                clip.crop_x = int(np.median(tracking.smoothed_crop_positions))
                clip.tracking_result = tracking
                clip.use_smart_tracking = True
            else:
                clip.crop_x = default_crop_x
                clip.use_smart_tracking = False
        else:
            clip.crop_x = default_crop_x
            clip.use_smart_tracking = False

        clip.suggested_title = _generate_clip_title(clip, video_title, i + 1)

    return clips


# ---------------------------------------------------------------------------
# ffmpeg extraction
# ---------------------------------------------------------------------------


def extract_clips(
    video_path: str,
    analysis: ShortsAnalysis,
    output_dir: str,
    create_vertical: bool = True,
    use_smart_tracking: bool = False,
) -> ShortsAnalysis:
    """Run ffmpeg to extract every highlight (and optional 9:16 versions)."""
    os.makedirs(output_dir, exist_ok=True)

    if use_smart_tracking:
        analysis.highlights = enhance_clips(
            analysis.highlights,
            analysis.video_title,
            video_path=video_path,
            use_smart_tracking=True,
        )

    clip_paths: List[Optional[str]] = []
    vertical_paths: List[Optional[str]] = []

    for i, clip in enumerate(analysis.highlights, 1):
        logger.info(
            "shorts.clip.extract.start",
            index=i,
            total=len(analysis.highlights),
            start=clip.start_time,
            end=clip.end_time,
        )

        clip_path = os.path.join(output_dir, f"clip_{i}.mp4")
        vertical_path = os.path.join(output_dir, f"clip_{i}_vertical.mp4")

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(clip.start_time),
                    "-i", video_path,
                    "-t", str(clip.duration),
                    "-c", "copy",
                    "-avoid_negative_ts", "1",
                    clip_path,
                ],
                capture_output=True,
                check=True,
            )
            clip_paths.append(clip_path)

            if create_vertical:
                if clip.use_smart_tracking and clip.tracking_result:
                    crop_filter = clip.tracking_result.to_ffmpeg_filter(
                        clip.crop_width, clip.crop_height
                    )
                else:
                    crop_filter = (
                        f"crop={clip.crop_width}:{clip.crop_height}:"
                        f"{clip.crop_x}:0"
                    )

                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", clip_path,
                        "-vf", crop_filter,
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-c:a", "aac",
                        vertical_path,
                    ],
                    capture_output=True,
                    check=True,
                )
                vertical_paths.append(vertical_path)

                if clip.use_smart_tracking and clip.tracking_result:
                    keyframe_path = os.path.join(
                        output_dir, f"clip_{i}_keyframes.json"
                    )
                    clip.tracking_result.export_keyframes(keyframe_path)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "shorts.clip.extract.failed", index=i, error=str(exc)
            )
            clip_paths.append(None)
            if create_vertical:
                vertical_paths.append(None)
        except FileNotFoundError:
            logger.error("shorts.clip.ffmpeg_missing")
            break

    analysis.clip_paths = clip_paths
    analysis.vertical_clip_paths = vertical_paths
    return analysis


def download_youtube_video(youtube_url: str, output_dir: str) -> str:
    """Download a YouTube video for clipping. Returns the local path."""
    os.makedirs(output_dir, exist_ok=True)
    video_path = os.path.join(output_dir, "source_video.mp4")
    logger.info("shorts.clip.download.start", url=youtube_url)

    try:
        cmd = [
            "yt-dlp",
            "-f",
            "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "--merge-output-format", "mp4",
            "-o", video_path,
            "--no-warnings",
            "--no-playlist",
            youtube_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("shorts.clip.download.retry", stderr=result.stderr)
            cmd_simple = [
                "yt-dlp",
                "-f", "best",
                "-o", video_path,
                "--no-playlist",
                youtube_url,
            ]
            subprocess.run(cmd_simple, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        logger.error("shorts.clip.yt_dlp_missing")
        raise
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr if hasattr(exc, "stderr") else str(exc)
        logger.error("shorts.clip.download.failed", error=str(error_msg))
        raise RuntimeError(
            "Could not download video. Make sure yt-dlp is updated: "
            "pip install -U yt-dlp"
        ) from exc

    return video_path


# ---------------------------------------------------------------------------
# Editor-friendly export bundles
# ---------------------------------------------------------------------------


def export_clips_info(analysis: ShortsAnalysis, output_dir: str) -> Dict[str, str]:
    """Write SRT, JSON, ffmpeg commands and a human-readable summary."""
    os.makedirs(output_dir, exist_ok=True)
    files: Dict[str, str] = {}

    srt_path = os.path.join(output_dir, "captions.srt")
    with open(srt_path, "w") as f:
        f.write(analysis.captions_srt)
    files["captions_srt"] = srt_path

    clips_data = {
        "video_title": analysis.video_title,
        "video_duration": analysis.video_duration,
        "clips": [h.to_dict() for h in analysis.highlights],
    }
    clips_path = os.path.join(output_dir, "clips.json")
    with open(clips_path, "w") as f:
        json.dump(clips_data, f, indent=2)
    files["clips_json"] = clips_path

    ffmpeg_path = os.path.join(output_dir, "ffmpeg_commands.txt")
    with open(ffmpeg_path, "w") as f:
        f.write(f"# FFmpeg commands for: {analysis.video_title}\n\n")
        for i, clip in enumerate(analysis.highlights, 1):
            f.write(f"# Clip {i}: {clip.suggested_title}\n")
            f.write(
                f"# Score: {clip.score:.0f}/100 | Reason: {clip.reason}\n"
            )
            f.write(f"# Hook Quality: {clip.hook_quality}\n\n")
            f.write("# Extract clip:\n")
            f.write(
                f"ffmpeg -i INPUT.mp4 -ss {clip.start_time:.2f} "
                f"-t {clip.duration:.2f} -c copy clip_{i}.mp4\n\n"
            )
            f.write("# Convert to vertical (9:16):\n")
            f.write(
                f"ffmpeg -i clip_{i}.mp4 -vf "
                f"\"{clip.to_dict()['ffmpeg_crop']}\" "
                f"clip_{i}_vertical.mp4\n\n"
            )
            f.write("# Add captions:\n")
            f.write(
                f"ffmpeg -i clip_{i}_vertical.mp4 -vf "
                f"\"subtitles=captions.srt\" clip_{i}_captioned.mp4\n\n"
            )
            f.write("-" * 60 + "\n\n")
    files["ffmpeg_commands"] = ffmpeg_path

    summary_path = os.path.join(output_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"SHORTS ANALYSIS: {analysis.video_title}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total Duration: {analysis.video_duration:.0f} seconds\n")
        f.write(f"Clips Found: {len(analysis.highlights)}\n\n")
        for i, clip in enumerate(analysis.highlights, 1):
            f.write(f"CLIP {i}\n")
            f.write(f"   Time: {clip.to_dict()['timestamp_display']}\n")
            f.write(f"   Duration: {clip.duration:.0f}s\n")
            f.write(f"   Score: {clip.score:.0f}/100\n")
            f.write(f"   Reason: {clip.reason}\n")
            f.write(f"   Hook: {clip.hook_quality}\n")
            f.write(f"   Title: {clip.suggested_title}\n\n")
            f.write("   Transcript:\n")
            transcript_excerpt = clip.transcript[:200]
            ellipsis = "..." if len(clip.transcript) > 200 else ""
            f.write(f"   {transcript_excerpt}{ellipsis}\n\n")
    files["summary"] = summary_path

    logger.info("shorts.clip.export.done", output_dir=output_dir)
    return files

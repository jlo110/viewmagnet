"""Dataclasses shared by the shorts pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class TranscriptUnavailable(Exception):
    """A usable transcript could not be obtained for a video.

    Raised when YouTube captions can't be fetched (disabled, none present, or
    the request was blocked) and the Whisper fallback didn't produce text.
    Carries a user-facing message so the API can return it verbatim.
    """


@dataclass
class Highlight:
    """A detected highlight/clip from the video."""

    start_time: float
    end_time: float
    duration: float

    score: float
    reason: str

    transcript: str

    hook_quality: str
    suggested_title: str

    crop_x: int
    crop_width: int
    crop_height: int

    tracking_result: Optional[object] = None
    use_smart_tracking: bool = False

    def to_dict(self) -> Dict:
        result = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "score": self.score,
            "reason": self.reason,
            "transcript": self.transcript,
            "hook_quality": self.hook_quality,
            "suggested_title": self.suggested_title,
            "crop": {
                "x": self.crop_x,
                "width": self.crop_width,
                "height": self.crop_height,
            },
            "ffmpeg_crop": (
                f"crop={self.crop_width}:{self.crop_height}:{self.crop_x}:0"
            ),
            "timestamp_display": (
                f"{self._format_time(self.start_time)} - "
                f"{self._format_time(self.end_time)}"
            ),
            "smart_tracking_enabled": self.use_smart_tracking,
        }

        if self.use_smart_tracking and self.tracking_result:
            result["ffmpeg_crop_dynamic"] = self.tracking_result.to_ffmpeg_filter(
                self.crop_width, self.crop_height
            )

        return result

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as ``MM:SS``."""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"


@dataclass
class ShortsAnalysis:
    """Result of analyzing a video for shorts."""

    video_title: str
    video_duration: float
    highlights: List[Highlight]
    transcript_full: str
    captions_srt: str
    clip_paths: List[str] = field(default_factory=list)
    vertical_clip_paths: List[str] = field(default_factory=list)

    def get_top_clips(self, n: int = 5) -> List[Highlight]:
        """Return the top ``n`` clips by score."""
        return sorted(self.highlights, key=lambda h: h.score, reverse=True)[:n]

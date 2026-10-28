"""
Pacing Analyzer - Visual pacing & dead-air detection

Based on Chris Girbu's framework: short-form videos must keep their pacing tight.
Dead air (silence > 800ms) and slow visual pacing (cuts < every 3-5 seconds) are
two of the biggest retention killers.

This module:
- Detects scene cuts using ffmpeg's scene-detection filter
- Detects dead-air (silence) using ffmpeg's silencedetect filter
- Computes a composite pacing grade (A-F) and concrete cut suggestions
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

import structlog

logger = structlog.get_logger()


# Pacing thresholds (tuned for short-form / vertical content)
TARGET_AVG_CUT_SECONDS = 4.0      # Ideal time between cuts
MAX_DEAD_AIR_SECONDS = 0.8        # Anything longer is "dead air"
SILENCE_THRESHOLD_DB = -30        # Below this = silence


@dataclass
class DeadAirSegment:
    """A silent segment that should likely be cut."""
    start_sec: float
    end_sec: float
    duration_sec: float


@dataclass
class CutSuggestion:
    """A suggested edit to improve pacing."""
    timestamp_sec: float
    issue: str           # "long_silence" | "no_visual_change" | "slow_pace"
    duration_sec: float  # Length of the problem segment
    recommendation: str


@dataclass
class PacingReport:
    """Complete pacing analysis."""
    total_duration_sec: float
    
    # Cuts (visual pacing)
    cut_count: int
    avg_cut_interval_sec: float
    longest_no_cut_sec: float
    
    # Dead air
    dead_air_segments: List[DeadAirSegment] = field(default_factory=list)
    total_dead_air_sec: float = 0.0
    dead_air_percent: float = 0.0
    
    # Scoring
    visual_pacing_score: float = 0.0   # 0-100
    dead_air_score: float = 0.0        # 0-100
    overall_score: float = 0.0         # 0-100
    grade: str = "F"                   # A | B | C | D | F
    
    # Actionable
    cut_suggestions: List[CutSuggestion] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "total_duration_sec": round(self.total_duration_sec, 2),
            "cut_count": self.cut_count,
            "avg_cut_interval_sec": round(self.avg_cut_interval_sec, 2),
            "longest_no_cut_sec": round(self.longest_no_cut_sec, 2),
            "dead_air_segments": [
                {
                    "start_sec": round(d.start_sec, 2),
                    "end_sec": round(d.end_sec, 2),
                    "duration_sec": round(d.duration_sec, 2),
                }
                for d in self.dead_air_segments
            ],
            "total_dead_air_sec": round(self.total_dead_air_sec, 2),
            "dead_air_percent": round(self.dead_air_percent, 1),
            "visual_pacing_score": round(self.visual_pacing_score, 1),
            "dead_air_score": round(self.dead_air_score, 1),
            "overall_score": round(self.overall_score, 1),
            "grade": self.grade,
            "cut_suggestions": [
                {
                    "timestamp_sec": round(c.timestamp_sec, 2),
                    "issue": c.issue,
                    "duration_sec": round(c.duration_sec, 2),
                    "recommendation": c.recommendation,
                }
                for c in self.cut_suggestions
            ],
            "issues": self.issues,
        }


def get_video_duration(video_path: str) -> Optional[float]:
    """Get video duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


def detect_scene_cuts(video_path: str, threshold: float = 0.3) -> List[float]:
    """
    Detect scene cut timestamps using ffmpeg's select=gt(scene,X) filter.
    
    Args:
        video_path: Path to video file
        threshold: Scene change sensitivity (0.0 = every frame, 1.0 = never)
    
    Returns: List of timestamps (seconds) where scene cuts occur.
    """
    try:
        cmd = [
            "ffmpeg", "-i", video_path,
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        # Parse "pts_time:X.XX" from showinfo output
        timestamps = []
        for match in re.finditer(r"pts_time:([\d.]+)", result.stderr):
            try:
                timestamps.append(float(match.group(1)))
            except ValueError:
                pass
        return sorted(set(timestamps))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Scene detection failed: {e}")
        return []


def detect_silence(
    video_path: str,
    threshold_db: float = SILENCE_THRESHOLD_DB,
    min_duration_sec: float = MAX_DEAD_AIR_SECONDS,
) -> List[DeadAirSegment]:
    """
    Detect silent segments using ffmpeg's silencedetect filter.
    """
    try:
        cmd = [
            "ffmpeg", "-i", video_path,
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration_sec}",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        segments = []
        # Parse pairs of "silence_start: X" and "silence_end: Y | silence_duration: Z"
        starts = re.findall(r"silence_start:\s*([\d.]+)", result.stderr)
        ends = re.findall(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)", result.stderr)
        
        for i, end_match in enumerate(ends):
            if i < len(starts):
                try:
                    start = float(starts[i])
                    end = float(end_match[0])
                    dur = float(end_match[1])
                    segments.append(DeadAirSegment(start_sec=start, end_sec=end, duration_sec=dur))
                except ValueError:
                    pass
        return segments
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Silence detection failed: {e}")
        return []


def grade_from_score(score: float) -> str:
    """Convert 0-100 score to letter grade."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


class PacingAnalyzer:
    """Analyzes video pacing and identifies cuts to make."""
    
    def analyze(self, video_path: str) -> PacingReport:
        """Run a full pacing analysis on a video file."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        duration = get_video_duration(video_path) or 0.0
        
        # Visual pacing
        cuts = detect_scene_cuts(video_path)
        cut_count = len(cuts)
        
        if cut_count > 0 and duration > 0:
            avg_cut_interval = duration / max(1, cut_count)
            
            # Longest stretch without a cut
            gaps = [cuts[0]] if cuts else []
            for i in range(1, len(cuts)):
                gaps.append(cuts[i] - cuts[i-1])
            if cuts:
                gaps.append(duration - cuts[-1])
            longest_no_cut = max(gaps) if gaps else duration
        else:
            avg_cut_interval = duration
            longest_no_cut = duration
        
        # Visual pacing score: target = 4s avg, penalize if >> than that
        if avg_cut_interval <= TARGET_AVG_CUT_SECONDS:
            visual_score = 100.0
        elif avg_cut_interval <= TARGET_AVG_CUT_SECONDS * 2:
            # 4-8 sec: linearly drop from 100 to 60
            visual_score = 100 - ((avg_cut_interval - TARGET_AVG_CUT_SECONDS) / TARGET_AVG_CUT_SECONDS) * 40
        elif avg_cut_interval <= TARGET_AVG_CUT_SECONDS * 4:
            # 8-16 sec: drop from 60 to 20
            visual_score = 60 - ((avg_cut_interval - TARGET_AVG_CUT_SECONDS * 2) / (TARGET_AVG_CUT_SECONDS * 2)) * 40
        else:
            visual_score = max(10.0, 20 - (avg_cut_interval - TARGET_AVG_CUT_SECONDS * 4))
        
        # Penalize if there's a single very long no-cut stretch
        if longest_no_cut > 10:
            visual_score *= 0.85
        if longest_no_cut > 20:
            visual_score *= 0.70
        
        visual_score = max(0.0, min(100.0, visual_score))
        
        # Dead air
        dead_air_segments = detect_silence(video_path)
        total_dead_air = sum(s.duration_sec for s in dead_air_segments)
        dead_air_percent = (total_dead_air / duration * 100) if duration > 0 else 0
        
        # Dead air score: ideally 0% dead air, every 5% costs 20 points
        if dead_air_percent <= 1:
            dead_air_score = 100.0
        elif dead_air_percent <= 5:
            dead_air_score = 100 - ((dead_air_percent - 1) / 4) * 20
        elif dead_air_percent <= 15:
            dead_air_score = 80 - ((dead_air_percent - 5) / 10) * 40
        else:
            dead_air_score = max(10.0, 40 - (dead_air_percent - 15))
        
        dead_air_score = max(0.0, min(100.0, dead_air_score))
        
        # Composite: visual=60%, dead_air=40%
        overall = visual_score * 0.6 + dead_air_score * 0.4
        grade = grade_from_score(overall)
        
        # Build cut suggestions
        suggestions: List[CutSuggestion] = []
        for seg in dead_air_segments:
            if seg.duration_sec > MAX_DEAD_AIR_SECONDS:
                suggestions.append(CutSuggestion(
                    timestamp_sec=seg.start_sec,
                    issue="long_silence",
                    duration_sec=seg.duration_sec,
                    recommendation=f"Cut {seg.duration_sec:.1f}s of silence at {format_timestamp(seg.start_sec)}",
                ))
        
        # Visual pacing suggestions: long no-cut spans
        if cuts and len(cuts) >= 2:
            for i in range(1, len(cuts)):
                gap = cuts[i] - cuts[i-1]
                if gap > 8:
                    suggestions.append(CutSuggestion(
                        timestamp_sec=cuts[i-1] + gap / 2,
                        issue="no_visual_change",
                        duration_sec=gap,
                        recommendation=f"Add a B-roll cut, zoom, or angle change around {format_timestamp(cuts[i-1] + gap/2)} (no visual change for {gap:.1f}s)",
                    ))
        
        # Sort suggestions by timestamp
        suggestions.sort(key=lambda s: s.timestamp_sec)
        
        # Build issues summary
        issues: List[str] = []
        if avg_cut_interval > TARGET_AVG_CUT_SECONDS * 2:
            issues.append(
                f"Average time between cuts is {avg_cut_interval:.1f}s - target is under {TARGET_AVG_CUT_SECONDS:.0f}s for short-form."
            )
        if dead_air_percent > 10:
            issues.append(
                f"{dead_air_percent:.1f}% of the video is dead air ({total_dead_air:.1f}s of silence)."
            )
        if longest_no_cut > 15:
            issues.append(
                f"Longest stretch with no cut is {longest_no_cut:.1f}s - viewers will tune out."
            )
        if not issues:
            issues.append("Pacing is solid - no major issues detected.")
        
        return PacingReport(
            total_duration_sec=duration,
            cut_count=cut_count,
            avg_cut_interval_sec=avg_cut_interval,
            longest_no_cut_sec=longest_no_cut,
            dead_air_segments=dead_air_segments,
            total_dead_air_sec=total_dead_air,
            dead_air_percent=dead_air_percent,
            visual_pacing_score=visual_score,
            dead_air_score=dead_air_score,
            overall_score=overall,
            grade=grade,
            cut_suggestions=suggestions[:20],  # Cap at top 20 suggestions
            issues=issues,
        )


def format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# Module-level helpers
_analyzer: Optional[PacingAnalyzer] = None

def get_pacing_analyzer() -> PacingAnalyzer:
    """Get the shared PacingAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = PacingAnalyzer()
    return _analyzer

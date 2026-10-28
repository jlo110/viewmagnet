"""
AI Video Effects Generator

Uses Claude (with Groq fallback) to analyze video + transcript and generate contextual FFmpeg filters
for dynamic zooms, contrast changes, color grading aligned with speech and emotion.
"""

import os
import re
import json
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger()


class EffectIntensity(Enum):
    """Intensity level for video effects."""
    SUBTLE = "subtle"
    MEDIUM = "medium"
    DRAMATIC = "dramatic"


@dataclass
class EffectSegment:
    """A single effect segment with timing and parameters."""
    start_sec: float
    end_sec: float
    zoom: float = 1.0
    zoom_center_x: float = 0.5
    zoom_center_y: float = 0.5
    brightness: float = 1.0
    contrast: float = 1.0
    saturate: float = 1.0
    description: str = ""


@dataclass
class EffectsConfig:
    """Complete effects configuration for a video."""
    segments: List[EffectSegment] = field(default_factory=list)
    filter_string: Optional[str] = None
    intensity: EffectIntensity = EffectIntensity.MEDIUM
    
    def to_dict(self) -> Dict:
        return {
            "segments": [
                {
                    "start_sec": s.start_sec,
                    "end_sec": s.end_sec,
                    "zoom": s.zoom,
                    "zoom_center_x": s.zoom_center_x,
                    "zoom_center_y": s.zoom_center_y,
                    "brightness": s.brightness,
                    "contrast": s.contrast,
                    "saturate": s.saturate,
                    "description": s.description,
                }
                for s in self.segments
            ],
            "filter_string": self.filter_string,
            "intensity": self.intensity.value,
        }


class VideoEffectsGenerator:
    """
    Generates contextual video effects using AI analysis.
    
    Uses Claude (with Groq fallback) to understand video content and create FFmpeg filters
    that enhance engagement through dynamic zooms and color adjustments.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the effects generator.
        
        Args:
            api_key: Optional API key (will use shared LLM client with fallback)
        """
        self.llm_client = get_llm_client()
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            logger.warning("No LLM API key configured (ANTHROPIC_API_KEY or GROQ_API_KEY)")
        # See HookLab.set_budget_context.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def analyze_and_generate_effects(
        self,
        transcript: str,
        duration: float,
        fps: int = 30,
        width: int = 1080,
        height: int = 1920,
        intensity: EffectIntensity = EffectIntensity.MEDIUM
    ) -> EffectsConfig:
        """
        Analyze transcript and generate effects configuration.
        
        Args:
            transcript: Video transcript text
            duration: Video duration in seconds
            fps: Video frame rate
            width: Video width
            height: Video height
            intensity: Effect intensity level
        
        Returns:
            EffectsConfig with segments and optional filter string
        """
        if not self.api_key:
            logger.warning("No API key, returning default effects")
            return self._get_default_effects(duration, intensity)
        
        try:
            # Intensity-specific parameters
            intensity_params = {
                EffectIntensity.SUBTLE: {
                    "max_zoom": 1.15,
                    "contrast_range": "0.95-1.1",
                    "description": "very subtle, barely noticeable"
                },
                EffectIntensity.MEDIUM: {
                    "max_zoom": 1.25,
                    "contrast_range": "0.9-1.2",
                    "description": "noticeable but professional"
                },
                EffectIntensity.DRAMATIC: {
                    "max_zoom": 1.4,
                    "contrast_range": "0.85-1.35",
                    "description": "bold and attention-grabbing"
                },
            }
            
            params = intensity_params[intensity]
            
            system_prompt = "You are an expert video editor specializing in creating dynamic video effects that enhance viewer engagement."
            
            user_prompt = f"""Analyze this transcript and create effect segments that enhance viewer engagement.

VIDEO INFO:
- Duration: {duration} seconds
- FPS: {fps}
- Resolution: {width}x{height}

TRANSCRIPT:
{transcript[:4000]}

INTENSITY: {intensity.value} ({params['description']})

Generate effect segments that:
1. Use slow zooms toward the speaker during key points
2. Increase contrast/saturation for dramatic moments
3. Keep transitions smooth - no jarring changes
4. Cover the ENTIRE video duration from 0 to {duration} seconds
5. Zoom range: 1.0 to {params['max_zoom']}
6. Contrast/saturation range: {params['contrast_range']}

Return JSON with this exact structure:
{{
    "segments": [
        {{
            "start_sec": 0,
            "end_sec": 5.0,
            "zoom": 1.0,
            "zoom_center_x": 0.5,
            "zoom_center_y": 0.4,
            "brightness": 1.0,
            "contrast": 1.0,
            "saturate": 1.0,
            "description": "Opening - neutral"
        }}
    ]
}}

Create 5-15 segments depending on content. Each segment should have a purpose based on what's being said."""

            # Use unified LLM client with fallback
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000,
                temperature=0.7,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
                feature="ai_video_effects.analyze",
            )

            if not response.success:
                logger.warning(f"LLM generation failed: {response.error}")
                return self._get_default_effects(duration, intensity)
            
            logger.info(f"Effects generated using {response.provider}/{response.model}")
            
            # Parse response
            text = response.text
            
            # Extract JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            text = text.strip()
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx + 1]
            
            data = json.loads(text)
            
            segments = []
            for seg_data in data.get("segments", []):
                segments.append(EffectSegment(
                    start_sec=float(seg_data.get("start_sec", 0)),
                    end_sec=float(seg_data.get("end_sec", duration)),
                    zoom=float(seg_data.get("zoom", 1.0)),
                    zoom_center_x=float(seg_data.get("zoom_center_x", 0.5)),
                    zoom_center_y=float(seg_data.get("zoom_center_y", 0.5)),
                    brightness=float(seg_data.get("brightness", 1.0)),
                    contrast=float(seg_data.get("contrast", 1.0)),
                    saturate=float(seg_data.get("saturate", 1.0)),
                    description=seg_data.get("description", ""),
                ))
            
            config = EffectsConfig(
                segments=segments,
                intensity=intensity
            )
            
            # Generate FFmpeg filter string
            config.filter_string = self._generate_ffmpeg_filter(
                segments, duration, fps, width, height
            )
            
            logger.info(f"Generated {len(segments)} effect segments")
            return config
            
        except Exception as e:
            logger.error(f"AI effects generation failed: {e}")
            return self._get_default_effects(duration, intensity)
    
    def _get_default_effects(
        self,
        duration: float,
        intensity: EffectIntensity
    ) -> EffectsConfig:
        """Generate default effects without AI."""
        # Simple default: slight zoom in over the video
        zoom_max = {
            EffectIntensity.SUBTLE: 1.05,
            EffectIntensity.MEDIUM: 1.1,
            EffectIntensity.DRAMATIC: 1.15,
        }[intensity]
        
        segments = [
            EffectSegment(
                start_sec=0,
                end_sec=duration,
                zoom=zoom_max,
                zoom_center_x=0.5,
                zoom_center_y=0.4,
                description="Gradual zoom in"
            )
        ]
        
        return EffectsConfig(
            segments=segments,
            intensity=intensity,
            filter_string=f"zoompan=z='1+{zoom_max-1}*(on/{duration*30})':x='iw/2-(iw/zoom/2)':y='ih*0.4-(ih/zoom*0.4)':d=1:s=1080x1920:fps=30"
        )
    
    def _generate_ffmpeg_filter(
        self,
        segments: List[EffectSegment],
        duration: float,
        fps: int,
        width: int,
        height: int
    ) -> str:
        """
        Generate FFmpeg filter string from effect segments.
        
        Uses timeline editing with enable expressions for segment-based effects.
        """
        if not segments:
            return ""
        
        filters = []
        
        # Build zoompan filter with segment-based zoom levels
        zoom_parts = []
        for seg in segments:
            frame_start = int(seg.start_sec * fps)
            frame_end = int(seg.end_sec * fps)
            zoom_parts.append(f"{seg.zoom}*between(on,{frame_start},{frame_end})")
        
        zoom_expr = "+".join(zoom_parts) if zoom_parts else "1"
        
        # Calculate center position (weighted average across segments)
        avg_cx = sum(s.zoom_center_x for s in segments) / len(segments)
        avg_cy = sum(s.zoom_center_y for s in segments) / len(segments)
        
        # Zoompan filter
        zoompan = (
            f"zoompan=z='{zoom_expr}':"
            f"x='iw*{avg_cx}-(iw/zoom*{avg_cx})':"
            f"y='ih*{avg_cy}-(ih/zoom*{avg_cy})':"
            f"d=1:s={width}x{height}:fps={fps}"
        )
        filters.append(zoompan)
        
        # Add contrast/saturation effects using eq filter with enable
        for i, seg in enumerate(segments):
            if seg.contrast != 1.0 or seg.brightness != 1.0:
                eq_filter = f"eq=contrast={seg.contrast}:brightness={seg.brightness - 1}:enable='between(t,{seg.start_sec},{seg.end_sec})'"
                filters.append(eq_filter)
            
            if seg.saturate != 1.0:
                hue_filter = f"hue=s={seg.saturate}:enable='between(t,{seg.start_sec},{seg.end_sec})'"
                filters.append(hue_filter)
        
        # Ensure pixel format is correct
        filters.append("setsar=1")
        
        return ",".join(filters)
    
    @staticmethod
    def sanitize_filter_string(filter_string: str) -> str:
        """
        Sanitize FFmpeg filter string by converting comparison operators
        to FFmpeg expression functions.
        """
        s = filter_string
        
        # Convert comparison operators to functions
        patterns = [
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*>=\s*(-?\d+(?:\.\d+)?)"), r"gte(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*<=\s*(-?\d+(?:\.\d+)?)"), r"lte(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*>\s*(-?\d+(?:\.\d+)?)"), r"gt(\1,\2)"),
            (re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*<\s*(-?\d+(?:\.\d+)?)"), r"lt(\1,\2)"),
        ]
        
        for pat, repl in patterns:
            s = pat.sub(repl, s)
        
        return s


def apply_effects_to_video(
    input_path: str,
    output_path: str,
    effects_config: EffectsConfig
) -> bool:
    """
    Apply effects configuration to a video using FFmpeg.
    
    Args:
        input_path: Path to input video
        output_path: Path to save output video
        effects_config: EffectsConfig with filter string
    
    Returns:
        True if successful
    """
    if not effects_config.filter_string:
        logger.warning("No filter string in effects config, copying original")
        subprocess.run(['ffmpeg', '-y', '-i', input_path, '-c', 'copy', output_path])
        return True
    
    filter_string = VideoEffectsGenerator.sanitize_filter_string(
        effects_config.filter_string
    )
    
    logger.info(f"Applying effects filter: {filter_string[:200]}...")
    
    cmd = [
        'ffmpeg', '-y',
        '-i', input_path,
        '-vf', filter_string,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
        '-c:a', 'copy',
        output_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Effects applied successfully: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr.decode() if e.stderr else 'Unknown error'}")
        raise


def get_video_info(video_path: str) -> Dict[str, Any]:
    """
    Get video information using ffprobe.
    
    Returns:
        Dict with width, height, duration, fps
    """
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,duration',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.check_output(cmd).decode()
        data = json.loads(result)
        
        stream = data.get('streams', [{}])[0]
        format_info = data.get('format', {})
        
        # Parse frame rate (may be like "30/1")
        fps_str = stream.get('r_frame_rate', '30/1')
        if '/' in fps_str:
            num, den = fps_str.split('/')
            fps = int(num) / int(den) if int(den) > 0 else 30
        else:
            fps = float(fps_str)
        
        return {
            'width': int(stream.get('width', 1080)),
            'height': int(stream.get('height', 1920)),
            'fps': int(fps),
            'duration': float(stream.get('duration') or format_info.get('duration', 60)),
        }
    except Exception as e:
        logger.error(f"Failed to get video info: {e}")
        return {
            'width': 1080,
            'height': 1920,
            'fps': 30,
            'duration': 60,
        }

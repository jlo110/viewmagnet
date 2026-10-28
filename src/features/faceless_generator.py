"""
Faceless Video Generator for ViewMagnet.

Generates complete faceless videos by combining:
- AI-generated voiceover (ElevenLabs)
- Stock footage B-roll (Pexels/Pixabay)
- Animated captions
- Background music (optional)

Pipeline:
1. Script → Sections with timestamps
2. Sections → AI voiceover audio files
3. Sections → B-roll clip suggestions
4. Script → Animated captions
5. Combine all with FFmpeg
"""
import os
import subprocess
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class ScriptSection:
    """A section of a video script."""
    name: str
    content: str
    duration_seconds: float = 0
    start_time: float = 0
    end_time: float = 0
    voiceover_path: Optional[str] = None
    broll_clips: List[str] = field(default_factory=list)


@dataclass
class FacelessVideoProject:
    """Represents a faceless video project."""
    project_id: str
    title: str
    script: str
    sections: List[ScriptSection]
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel
    caption_style: str = "capcut"
    output_format: str = "mp4"
    resolution: tuple = (1920, 1080)
    
    # Generated assets
    voiceover_files: List[str] = field(default_factory=list)
    broll_files: List[str] = field(default_factory=list)
    caption_file: Optional[str] = None
    
    # Output
    output_path: Optional[str] = None
    status: str = "created"
    created_at: datetime = field(default_factory=datetime.utcnow)


class ScriptParser:
    """Parses scripts into sections for video generation."""
    
    @staticmethod
    def estimate_duration(text: str, words_per_minute: int = 150) -> float:
        """
        Estimate speaking duration for text.
        
        Args:
            text: Text to estimate.
            words_per_minute: Speaking speed.
        
        Returns:
            Estimated duration in seconds.
        """
        word_count = len(text.split())
        return (word_count / words_per_minute) * 60
    
    @staticmethod
    def parse_script(script: str) -> List[ScriptSection]:
        """
        Parse a script into sections.
        
        Supports multiple formats:
        - Markdown headers (## Section Name)
        - [Section Name] markers
        - SECTION NAME: format
        
        Args:
            script: Full script text.
        
        Returns:
            List of ScriptSection objects with timing.
        """
        sections = []
        current_time = 0
        
        # Try to split by common section markers
        import re
        
        # Pattern for various section formats
        section_pattern = r'(?:^##\s*(.+?)$|^\[(.+?)\]$|^([A-Z][A-Z\s]+):)'
        
        parts = re.split(section_pattern, script, flags=re.MULTILINE)
        
        # Clean and process parts
        current_name = "Introduction"
        current_content = []
        
        for part in parts:
            if part is None:
                continue
            
            part = part.strip()
            if not part:
                continue
            
            # Check if this is a section header
            if re.match(r'^[A-Z][A-Z\s]*$', part) or len(part) < 50:
                # Save previous section if exists
                if current_content:
                    content = "\n".join(current_content).strip()
                    if content:
                        duration = ScriptParser.estimate_duration(content)
                        sections.append(ScriptSection(
                            name=current_name,
                            content=content,
                            duration_seconds=duration,
                            start_time=current_time,
                            end_time=current_time + duration,
                        ))
                        current_time += duration
                
                current_name = part.strip(":").strip("[]").strip("#").strip()
                current_content = []
            else:
                current_content.append(part)
        
        # Don't forget the last section
        if current_content:
            content = "\n".join(current_content).strip()
            if content:
                duration = ScriptParser.estimate_duration(content)
                sections.append(ScriptSection(
                    name=current_name,
                    content=content,
                    duration_seconds=duration,
                    start_time=current_time,
                    end_time=current_time + duration,
                ))
        
        # If no sections found, treat entire script as one section
        if not sections and script.strip():
            duration = ScriptParser.estimate_duration(script)
            sections.append(ScriptSection(
                name="Main Content",
                content=script.strip(),
                duration_seconds=duration,
                start_time=0,
                end_time=duration,
            ))
        
        return sections


class FacelessVideoGenerator:
    """
    Generates faceless videos from scripts.
    
    Orchestrates the full pipeline:
    1. Parse script into sections
    2. Generate voiceover for each section
    3. Find and download B-roll
    4. Generate animated captions
    5. Combine everything with FFmpeg
    """
    
    def __init__(self, output_dir: str = "output/faceless_videos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Lazy load dependencies
        self._voiceover_client = None
        self._broll_finder = None
        self._caption_generator = None
    
    @property
    def voiceover_client(self):
        if self._voiceover_client is None:
            from src.features.voiceover import ElevenLabsClient
            self._voiceover_client = ElevenLabsClient()
        return self._voiceover_client
    
    @property
    def broll_finder(self):
        if self._broll_finder is None:
            from src.features.broll_finder import BRollFinder
            self._broll_finder = BRollFinder()
        return self._broll_finder
    
    @property
    def caption_generator(self):
        if self._caption_generator is None:
            from src.features.animated_captions import CaptionGenerator
            self._caption_generator = CaptionGenerator()
        return self._caption_generator
    
    def create_project(
        self,
        title: str,
        script: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        caption_style: str = "capcut",
    ) -> FacelessVideoProject:
        """
        Create a new faceless video project.
        
        Args:
            title: Video title.
            script: Full script text.
            voice_id: ElevenLabs voice ID.
            caption_style: Caption animation style.
        
        Returns:
            FacelessVideoProject object.
        """
        import uuid
        
        project_id = str(uuid.uuid4())[:8]
        sections = ScriptParser.parse_script(script)
        
        return FacelessVideoProject(
            project_id=project_id,
            title=title,
            script=script,
            sections=sections,
            voice_id=voice_id,
            caption_style=caption_style,
        )
    
    def generate_voiceovers(
        self,
        project: FacelessVideoProject,
    ) -> List[str]:
        """
        Generate voiceover audio for all sections.
        
        Args:
            project: The video project.
        
        Returns:
            List of paths to generated audio files.
        """
        project_dir = self.output_dir / project.project_id / "voiceovers"
        project_dir.mkdir(parents=True, exist_ok=True)
        
        audio_files = []
        
        for i, section in enumerate(project.sections):
            try:
                result = self.voiceover_client.generate_voiceover(
                    text=section.content,
                    voice_id=project.voice_id,
                )
                
                filename = f"{i:02d}_{section.name.lower().replace(' ', '_')}.mp3"
                output_path = project_dir / filename
                
                with open(output_path, "wb") as f:
                    f.write(result.audio_data)
                
                section.voiceover_path = str(output_path)
                audio_files.append(str(output_path))
                
                logger.info(f"Generated voiceover for section: {section.name}")
            except Exception as e:
                logger.error(f"Failed to generate voiceover for {section.name}: {e}")
        
        project.voiceover_files = audio_files
        return audio_files
    
    def find_broll(
        self,
        project: FacelessVideoProject,
        clips_per_section: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Find B-roll clips for all sections.
        
        Args:
            project: The video project.
            clips_per_section: Number of clips per section.
        
        Returns:
            List of B-roll suggestions.
        """
        suggestions = self.broll_finder.find_broll_for_script(
            script_sections=[
                {"name": s.name, "content": s.content}
                for s in project.sections
            ],
            clips_per_section=clips_per_section,
        )
        
        # Update sections with B-roll clips
        for i, suggestion in enumerate(suggestions):
            if i < len(project.sections):
                project.sections[i].broll_clips = [
                    clip.download_url for clip in suggestion.clips
                ]
        
        return [
            {
                "section": s.section_name,
                "clips": [
                    {
                        "id": c.id,
                        "source": c.source,
                        "preview_url": c.preview_url,
                        "download_url": c.download_url,
                    }
                    for c in s.clips
                ]
            }
            for s in suggestions
        ]
    
    def download_broll(
        self,
        project: FacelessVideoProject,
        max_clips: int = 10,
    ) -> List[str]:
        """
        Download B-roll clips for the project.
        
        Args:
            project: The video project.
            max_clips: Maximum clips to download.
        
        Returns:
            List of paths to downloaded clips.
        """
        project_dir = self.output_dir / project.project_id / "broll"
        project_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded = []
        clip_count = 0
        
        for section in project.sections:
            for clip_url in section.broll_clips:
                if clip_count >= max_clips:
                    break
                
                try:
                    response = httpx.get(clip_url, timeout=60.0, follow_redirects=True)
                    response.raise_for_status()
                    
                    filename = f"broll_{clip_count:02d}.mp4"
                    output_path = project_dir / filename
                    
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    
                    downloaded.append(str(output_path))
                    clip_count += 1
                    
                    logger.info(f"Downloaded B-roll clip: {filename}")
                except Exception as e:
                    logger.error(f"Failed to download B-roll: {e}")
            
            if clip_count >= max_clips:
                break
        
        project.broll_files = downloaded
        return downloaded
    
    def generate_captions(
        self,
        project: FacelessVideoProject,
    ) -> str:
        """
        Generate animated captions for the project.
        
        Args:
            project: The video project.
        
        Returns:
            Path to the caption file (ASS format).
        """
        project_dir = self.output_dir / project.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Combine all section content
        full_transcript = "\n\n".join(s.content for s in project.sections)
        
        try:
            from src.features.animated_captions import generate_captions
            
            result = generate_captions(
                transcript=full_transcript,
                style=project.caption_style,
            )
            
            caption_path = project_dir / "captions.ass"
            with open(caption_path, "w") as f:
                f.write(result.ass_content)
            
            project.caption_file = str(caption_path)
            logger.info("Generated animated captions")
            
            return str(caption_path)
        except Exception as e:
            logger.error(f"Failed to generate captions: {e}")
            return ""
    
    def combine_video(
        self,
        project: FacelessVideoProject,
    ) -> str:
        """
        Combine all assets into final video using FFmpeg.
        
        Args:
            project: The video project with generated assets.
        
        Returns:
            Path to the final video.
        """
        project_dir = self.output_dir / project.project_id
        output_path = project_dir / f"{project.title.replace(' ', '_')}.mp4"
        
        # Check if we have the required assets
        if not project.voiceover_files:
            raise ValueError("No voiceover files generated")
        
        if not project.broll_files:
            logger.warning("No B-roll files, will use black background")
        
        try:
            # Concatenate voiceover files
            voiceover_concat = project_dir / "voiceover_full.mp3"
            self._concatenate_audio(project.voiceover_files, str(voiceover_concat))
            
            # Get total duration from voiceover
            duration = self._get_audio_duration(str(voiceover_concat))
            
            if project.broll_files:
                # Create video from B-roll clips
                video_concat = project_dir / "broll_concat.mp4"
                self._loop_videos_to_duration(
                    project.broll_files,
                    str(video_concat),
                    duration,
                    project.resolution,
                )
                
                # Combine video and audio
                self._combine_video_audio(
                    str(video_concat),
                    str(voiceover_concat),
                    str(output_path),
                    project.caption_file,
                )
            else:
                # Create video with black background
                self._create_video_from_audio(
                    str(voiceover_concat),
                    str(output_path),
                    project.resolution,
                    project.caption_file,
                )
            
            project.output_path = str(output_path)
            project.status = "completed"
            
            logger.info(f"Generated faceless video: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Failed to combine video: {e}")
            project.status = "failed"
            raise
    
    def _concatenate_audio(self, audio_files: List[str], output: str):
        """Concatenate audio files using FFmpeg."""
        list_file = Path(output).parent / "audio_list.txt"
        with open(list_file, "w") as f:
            for audio in audio_files:
                f.write(f"file '{audio}'\n")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", output
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using FFprobe."""
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    
    def _loop_videos_to_duration(
        self,
        video_files: List[str],
        output: str,
        duration: float,
        resolution: tuple,
    ):
        """Loop and concatenate videos to match target duration."""
        # Create a filter complex to loop videos
        inputs = []
        filter_parts = []
        
        for i, video in enumerate(video_files):
            inputs.extend(["-i", video])
            # Scale and set framerate
            filter_parts.append(
                f"[{i}:v]scale={resolution[0]}:{resolution[1]}:force_original_aspect_ratio=decrease,"
                f"pad={resolution[0]}:{resolution[1]}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
            )
        
        # Concatenate all scaled videos
        concat_inputs = "".join(f"[v{i}]" for i in range(len(video_files)))
        filter_parts.append(f"{concat_inputs}concat=n={len(video_files)}:v=1:a=0[vout]")
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast",
            output
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    
    def _combine_video_audio(
        self,
        video: str,
        audio: str,
        output: str,
        caption_file: Optional[str] = None,
    ):
        """Combine video and audio, optionally burning in captions."""
        if caption_file and os.path.exists(caption_file):
            cmd = [
                "ffmpeg", "-y",
                "-i", video,
                "-i", audio,
                "-vf", f"ass={caption_file}",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video,
                "-i", audio,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output
            ]
        subprocess.run(cmd, check=True, capture_output=True)
    
    def _create_video_from_audio(
        self,
        audio: str,
        output: str,
        resolution: tuple,
        caption_file: Optional[str] = None,
    ):
        """Create video from audio with solid background."""
        vf_filter = f"color=c=black:s={resolution[0]}x{resolution[1]}:d=1"
        
        if caption_file and os.path.exists(caption_file):
            vf_filter += f",ass={caption_file}"
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", vf_filter,
            "-i", audio,
            "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-pix_fmt", "yuv420p",
            output
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    
    def generate_full_video(
        self,
        title: str,
        script: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        caption_style: str = "capcut",
        include_broll: bool = True,
    ) -> FacelessVideoProject:
        """
        Generate a complete faceless video.
        
        This is the main entry point that orchestrates the full pipeline.
        
        Args:
            title: Video title.
            script: Full script text.
            voice_id: ElevenLabs voice ID.
            caption_style: Caption animation style.
            include_broll: Whether to include B-roll footage.
        
        Returns:
            FacelessVideoProject with all generated assets.
        """
        # Create project
        project = self.create_project(title, script, voice_id, caption_style)
        logger.info(f"Created faceless video project: {project.project_id}")
        
        # Generate voiceovers
        project.status = "generating_voiceover"
        self.generate_voiceovers(project)
        
        # Find and download B-roll
        if include_broll:
            project.status = "finding_broll"
            self.find_broll(project)
            self.download_broll(project)
        
        # Generate captions
        project.status = "generating_captions"
        self.generate_captions(project)
        
        # Combine into final video
        project.status = "combining"
        self.combine_video(project)
        
        return project


# Convenience function
def generate_faceless_video(
    title: str,
    script: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
    caption_style: str = "capcut",
    include_broll: bool = True,
) -> FacelessVideoProject:
    """
    Generate a complete faceless video from a script.
    
    Args:
        title: Video title.
        script: Full script text.
        voice_id: ElevenLabs voice ID.
        caption_style: Caption animation style.
        include_broll: Whether to include B-roll.
    
    Returns:
        FacelessVideoProject with generated video.
    """
    generator = FacelessVideoGenerator()
    return generator.generate_full_video(
        title=title,
        script=script,
        voice_id=voice_id,
        caption_style=caption_style,
        include_broll=include_broll,
    )

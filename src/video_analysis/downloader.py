"""Video downloader using yt-dlp - downloads first N seconds only."""

import os
import sys
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Get path to yt-dlp in the same venv as Python
YTDLP_PATH = os.path.join(os.path.dirname(sys.executable), "yt-dlp")

# Node.js runtime for yt-dlp (required for YouTube extraction since late 2024)
# Try common locations
NODE_PATHS = [
    "/opt/homebrew/opt/node@22/bin/node",
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/node",
]
NODE_PATH = next((p for p in NODE_PATHS if os.path.exists(p)), None)

# Base yt-dlp args that enable JS runtime
def get_ytdlp_base_args():
    """Get base args for yt-dlp including JS runtime, challenge solver, and cookies."""
    args = [YTDLP_PATH]
    if NODE_PATH:
        args.extend(["--js-runtimes", f"node:{NODE_PATH}"])
        args.extend(["--remote-components", "ejs:github"])  # Download challenge solver
    # Use browser cookies to avoid bot detection
    args.extend(["--cookies-from-browser", "chrome"])
    return args


@dataclass
class DownloadResult:
    """Result of a video download."""
    success: bool
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None


class VideoDownloader:
    """Downloads YouTube videos (first N seconds) for analysis."""
    
    def __init__(self, output_dir: Optional[str] = None, max_duration: int = 60):
        """
        Initialize downloader.
        
        Args:
            output_dir: Directory to save videos (temp dir if None)
            max_duration: Maximum seconds to download (default 60s for hook analysis)
        """
        self.output_dir = output_dir or tempfile.mkdtemp(prefix="ViewMagnet_")
        self.max_duration = max_duration
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
    
    def download(self, video_id: str, include_audio: bool = True) -> DownloadResult:
        """
        Download first N seconds of a YouTube video.
        
        Args:
            video_id: YouTube video ID
            include_audio: Whether to also extract audio separately
            
        Returns:
            DownloadResult with paths to downloaded files
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        video_path = os.path.join(self.output_dir, f"{video_id}.mp4")
        audio_path = os.path.join(self.output_dir, f"{video_id}.mp3") if include_audio else None
        
        try:
            # Download video with duration limit using yt-dlp + ffmpeg
            # First, get video info to check duration
            info_cmd = get_ytdlp_base_args() + [
                "--print", "duration",
                "--no-download",
                url
            ]
            
            result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                # Extract actual error message from yt-dlp output (combine stdout and stderr)
                error_msg = (result.stderr + "\n" + result.stdout).strip()
                # Look for the ERROR: line specifically
                for line in error_msg.split('\n'):
                    if 'ERROR:' in line or 'not available' in line.lower():
                        error_msg = line.strip()
                        break
                # Truncate long errors but keep the key part
                if len(error_msg) > 300:
                    error_msg = error_msg[:300] + "..."
                return DownloadResult(success=False, error=error_msg)
            
            try:
                total_duration = float(result.stdout.strip())
            except:
                total_duration = None
            
            # Download with postprocessor to cut to max_duration
            download_cmd = get_ytdlp_base_args() + [
                "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", video_path,
                "--no-playlist",
                "--postprocessor-args", f"ffmpeg:-t {self.max_duration}",
                url
            ]
            
            logger.info(f"Downloading first {self.max_duration}s of {video_id}...")
            result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=180)
            
            if result.returncode != 0:
                # Try simpler format
                download_cmd = get_ytdlp_base_args() + [
                    "-f", "best[height<=720]",
                    "-o", video_path,
                    "--no-playlist",
                    "--postprocessor-args", f"ffmpeg:-t {self.max_duration}",
                    url
                ]
                result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=180)
                
            if not os.path.exists(video_path):
                return DownloadResult(success=False, error=f"Download failed: {result.stderr}")
            
            # Extract audio if requested
            if include_audio and os.path.exists(video_path):
                audio_cmd = [
                    "ffmpeg",
                    "-i", video_path,
                    "-vn",  # No video
                    "-acodec", "libmp3lame",
                    "-q:a", "4",  # Good quality
                    "-y",  # Overwrite
                    audio_path
                ]
                subprocess.run(audio_cmd, capture_output=True, timeout=60)
            
            return DownloadResult(
                success=True,
                video_path=video_path,
                audio_path=audio_path if audio_path and os.path.exists(audio_path) else None,
                duration=min(self.max_duration, total_duration) if total_duration else self.max_duration
            )
            
        except subprocess.TimeoutExpired:
            return DownloadResult(success=False, error="Download timed out")
        except Exception as e:
            return DownloadResult(success=False, error=str(e))
    
    def cleanup(self, video_id: str):
        """Remove downloaded files for a video."""
        for ext in ['.mp4', '.mp3', '.webm', '.m4a']:
            path = os.path.join(self.output_dir, f"{video_id}{ext}")
            if os.path.exists(path):
                os.remove(path)
    
    def cleanup_all(self):
        """Remove all downloaded files."""
        import shutil
        if os.path.exists(self.output_dir) and self.output_dir.startswith(tempfile.gettempdir()):
            shutil.rmtree(self.output_dir)


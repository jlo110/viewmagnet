"""
Voice Dubbing / Translation Module

Uses ElevenLabs Dubbing API to translate video audio to 30+ languages
with AI voice cloning.
"""

import os
import time
from typing import Optional, Dict
from dataclasses import dataclass
from enum import Enum

import httpx
import structlog

logger = structlog.get_logger()

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# Supported target languages for dubbing
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "hi": "Hindi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
    "tr": "Turkish",
    "nl": "Dutch",
    "sv": "Swedish",
    "id": "Indonesian",
    "fil": "Filipino",
    "ms": "Malay",
    "vi": "Vietnamese",
    "th": "Thai",
    "uk": "Ukrainian",
    "el": "Greek",
    "cs": "Czech",
    "fi": "Finnish",
    "ro": "Romanian",
    "da": "Danish",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "ta": "Tamil",
}


class DubbingStatus(Enum):
    """Status of a dubbing job."""
    PENDING = "pending"
    DUBBING = "dubbing"
    DUBBED = "dubbed"
    FAILED = "failed"


@dataclass
class DubbingJob:
    """Represents a dubbing job."""
    dubbing_id: str
    status: DubbingStatus
    target_language: str
    source_language: Optional[str] = None
    expected_duration_sec: Optional[float] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "dubbing_id": self.dubbing_id,
            "status": self.status.value,
            "target_language": self.target_language,
            "source_language": self.source_language,
            "expected_duration_sec": self.expected_duration_sec,
            "error": self.error,
        }


class VoiceDubbingClient:
    """
    Client for ElevenLabs Dubbing API.
    
    Provides video translation to 30+ languages with AI voice cloning.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the dubbing client.
        
        Args:
            api_key: ElevenLabs API key (falls back to ELEVENLABS_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured for dubbing")
    
    def create_dubbing_project(
        self,
        video_path: str,
        target_language: str,
        source_language: Optional[str] = None,
    ) -> DubbingJob:
        """
        Create a new dubbing project with ElevenLabs.
        
        Args:
            video_path: Path to the video file
            target_language: Target language code (e.g., 'es', 'fr', 'de')
            source_language: Source language code (auto-detected if None)
        
        Returns:
            DubbingJob with dubbing_id and expected duration
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured")
        
        if target_language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {target_language}. Supported: {list(SUPPORTED_LANGUAGES.keys())}")
        
        url = f"{ELEVENLABS_API_BASE}/dubbing"
        
        headers = {
            "xi-api-key": self.api_key,
        }
        
        data = {
            "target_lang": target_language,
            "mode": "automatic",
            "num_speakers": "0",  # Auto-detect
            "watermark": "false",
        }
        
        if source_language:
            data["source_lang"] = source_language
        
        logger.info(f"Creating dubbing project for {target_language}...")
        
        with open(video_path, "rb") as video_file:
            files = {
                "file": (os.path.basename(video_path), video_file, "video/mp4")
            }
            
            with httpx.Client(timeout=300.0) as client:
                response = client.post(url, headers=headers, data=data, files=files)
        
        if response.status_code not in [200, 201]:
            error_msg = response.text
            try:
                error_data = response.json()
                error_msg = error_data.get("detail", {}).get("message", response.text)
            except Exception:
                pass
            raise Exception(f"ElevenLabs API error: {error_msg}")
        
        result = response.json()
        
        logger.info(f"Dubbing project created: {result.get('dubbing_id')}")
        
        return DubbingJob(
            dubbing_id=result["dubbing_id"],
            status=DubbingStatus.PENDING,
            target_language=target_language,
            source_language=source_language,
            expected_duration_sec=result.get("expected_duration_sec"),
        )
    
    def get_dubbing_status(self, dubbing_id: str) -> DubbingJob:
        """
        Check the status of a dubbing project.
        
        Args:
            dubbing_id: The dubbing project ID
        
        Returns:
            DubbingJob with current status
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured")
        
        url = f"{ELEVENLABS_API_BASE}/dubbing/{dubbing_id}"
        
        headers = {
            "xi-api-key": self.api_key,
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
        
        if response.status_code != 200:
            raise Exception(f"Failed to get dubbing status: {response.text}")
        
        data = response.json()
        status_str = data.get("status", "unknown")
        
        status_map = {
            "dubbing": DubbingStatus.DUBBING,
            "dubbed": DubbingStatus.DUBBED,
            "failed": DubbingStatus.FAILED,
        }
        status = status_map.get(status_str, DubbingStatus.PENDING)
        
        return DubbingJob(
            dubbing_id=dubbing_id,
            status=status,
            target_language=data.get("target_lang", ""),
            source_language=data.get("source_lang"),
            expected_duration_sec=data.get("expected_duration_sec"),
            error=data.get("error") if status == DubbingStatus.FAILED else None,
        )
    
    def download_dubbed_video(
        self,
        dubbing_id: str,
        target_language: str,
        output_path: str
    ) -> str:
        """
        Download the dubbed video file.
        
        Args:
            dubbing_id: The dubbing project ID
            target_language: Target language code
            output_path: Where to save the dubbed video
        
        Returns:
            Path to the downloaded file
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured")
        
        url = f"{ELEVENLABS_API_BASE}/dubbing/{dubbing_id}/audio/{target_language}"
        
        headers = {
            "xi-api-key": self.api_key,
        }
        
        logger.info("Downloading dubbed video...")
        
        with httpx.Client(timeout=120.0) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise Exception(f"Failed to download dubbed video: {response.text}")
                
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                
                with open(output_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
        
        logger.info(f"Dubbed video saved to: {output_path}")
        return output_path
    
    def translate_video(
        self,
        video_path: str,
        output_path: str,
        target_language: str,
        source_language: Optional[str] = None,
        max_wait_seconds: int = 600,
        poll_interval: int = 5,
    ) -> str:
        """
        Translate a video to a target language (blocking).
        
        This is a blocking call that waits for the dubbing to complete.
        
        Args:
            video_path: Path to input video
            output_path: Path to save translated video
            target_language: Target language code
            source_language: Source language code (auto-detected if None)
            max_wait_seconds: Maximum time to wait for dubbing (default 10 min)
            poll_interval: Seconds between status checks
        
        Returns:
            Path to the translated video
        """
        # Create dubbing project
        job = self.create_dubbing_project(
            video_path=video_path,
            target_language=target_language,
            source_language=source_language,
        )
        
        logger.info(f"Dubbing ID: {job.dubbing_id}, Expected duration: {job.expected_duration_sec}s")
        
        # Poll for completion
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_seconds:
                raise Exception(f"Dubbing timed out after {max_wait_seconds} seconds")
            
            job = self.get_dubbing_status(job.dubbing_id)
            
            logger.info(f"Dubbing status: {job.status.value} (elapsed: {int(elapsed)}s)")
            
            if job.status == DubbingStatus.DUBBED:
                return self.download_dubbed_video(
                    dubbing_id=job.dubbing_id,
                    target_language=target_language,
                    output_path=output_path,
                )
            
            elif job.status == DubbingStatus.FAILED:
                raise Exception(f"Dubbing failed: {job.error or 'Unknown error'}")
            
            time.sleep(poll_interval)


# In-memory job store for async API
_dubbing_jobs: Dict[str, DubbingJob] = {}


def get_supported_languages() -> Dict[str, str]:
    """Return dict of supported language codes and names."""
    return SUPPORTED_LANGUAGES.copy()


def start_dubbing_job(
    video_path: str,
    target_language: str,
    source_language: Optional[str] = None,
    api_key: Optional[str] = None,
) -> DubbingJob:
    """
    Start a dubbing job (non-blocking).
    
    Args:
        video_path: Path to input video
        target_language: Target language code
        source_language: Source language code (auto-detected if None)
        api_key: ElevenLabs API key
    
    Returns:
        DubbingJob with dubbing_id for status checking
    """
    client = VoiceDubbingClient(api_key)
    job = client.create_dubbing_project(
        video_path=video_path,
        target_language=target_language,
        source_language=source_language,
    )
    
    # Store in memory for status checking
    _dubbing_jobs[job.dubbing_id] = job
    
    return job


def check_dubbing_status(
    dubbing_id: str,
    api_key: Optional[str] = None,
) -> DubbingJob:
    """
    Check status of a dubbing job.
    
    Args:
        dubbing_id: The dubbing job ID
        api_key: ElevenLabs API key
    
    Returns:
        Updated DubbingJob
    """
    client = VoiceDubbingClient(api_key)
    job = client.get_dubbing_status(dubbing_id)
    
    # Update cache
    _dubbing_jobs[dubbing_id] = job
    
    return job


def download_dubbed_result(
    dubbing_id: str,
    output_path: str,
    api_key: Optional[str] = None,
) -> str:
    """
    Download completed dubbing result.
    
    Args:
        dubbing_id: The dubbing job ID
        output_path: Where to save the video
        api_key: ElevenLabs API key
    
    Returns:
        Path to downloaded video
    """
    job = _dubbing_jobs.get(dubbing_id)
    if not job:
        # Fetch from API
        client = VoiceDubbingClient(api_key)
        job = client.get_dubbing_status(dubbing_id)
    
    if job.status != DubbingStatus.DUBBED:
        raise ValueError(f"Job not complete. Status: {job.status.value}")
    
    client = VoiceDubbingClient(api_key)
    return client.download_dubbed_video(
        dubbing_id=dubbing_id,
        target_language=job.target_language,
        output_path=output_path,
    )

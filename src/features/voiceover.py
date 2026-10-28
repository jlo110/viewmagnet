"""
ElevenLabs Voiceover Integration for ViewMagnet.

Provides AI-powered text-to-speech functionality for video creation.
"""
import os
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class Voice:
    """Represents an ElevenLabs voice."""
    voice_id: str
    name: str
    category: str
    description: Optional[str] = None
    preview_url: Optional[str] = None
    labels: Optional[Dict[str, str]] = None


@dataclass
class VoiceoverResult:
    """Result of a voiceover generation."""
    audio_data: bytes
    voice_id: str
    text: str
    model_id: str
    duration_seconds: Optional[float] = None
    character_count: int = 0


class ElevenLabsClient:
    """Client for ElevenLabs API."""
    
    BASE_URL = "https://api.elevenlabs.io/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the ElevenLabs client.
        
        Args:
            api_key: ElevenLabs API key. Falls back to ELEVENLABS_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured")
        
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "xi-api-key": self.api_key or "",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
    
    def list_voices(self) -> List[Voice]:
        """
        Get all available voices.
        
        Returns:
            List of Voice objects.
        """
        if not self.api_key:
            return self._get_demo_voices()
        
        try:
            response = self.client.get("/voices")
            response.raise_for_status()
            data = response.json()
            
            voices = []
            for voice_data in data.get("voices", []):
                voices.append(Voice(
                    voice_id=voice_data["voice_id"],
                    name=voice_data["name"],
                    category=voice_data.get("category", "generated"),
                    description=voice_data.get("description"),
                    preview_url=voice_data.get("preview_url"),
                    labels=voice_data.get("labels"),
                ))
            
            return voices
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            return self._get_demo_voices()
    
    def _get_demo_voices(self) -> List[Voice]:
        """Get demo voices when API is not available."""
        return [
            Voice(
                voice_id="21m00Tcm4TlvDq8ikWAM",
                name="Rachel",
                category="premade",
                description="Calm female voice, great for narration",
            ),
            Voice(
                voice_id="AZnzlk1XvdvUeBnXmlld",
                name="Domi",
                category="premade",
                description="Strong female voice, good for tutorials",
            ),
            Voice(
                voice_id="EXAVITQu4vr4xnSDxMaL",
                name="Bella",
                category="premade",
                description="Soft female voice, ideal for meditation content",
            ),
            Voice(
                voice_id="ErXwobaYiN019PkySvjV",
                name="Antoni",
                category="premade",
                description="Natural male voice, great for storytelling",
            ),
            Voice(
                voice_id="MF3mGyEYCl7XYWbV9V6O",
                name="Elli",
                category="premade",
                description="Youthful female voice, good for explainer videos",
            ),
            Voice(
                voice_id="TxGEqnHWrfWFTfGW9XjX",
                name="Josh",
                category="premade",
                description="Deep male voice, professional tone",
            ),
            Voice(
                voice_id="VR6AewLTigWG4xSOukaG",
                name="Arnold",
                category="premade",
                description="Crisp male voice, authoritative",
            ),
            Voice(
                voice_id="pNInz6obpgDQGcFmaJgB",
                name="Adam",
                category="premade",
                description="Warm male voice, conversational style",
            ),
        ]
    
    def generate_voiceover(
        self,
        text: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel by default
        model_id: str = "eleven_monolingual_v1",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        use_speaker_boost: bool = True,
    ) -> VoiceoverResult:
        """
        Generate voiceover audio from text.
        
        Args:
            text: Text to convert to speech.
            voice_id: ID of the voice to use.
            model_id: Model to use for generation.
            stability: Voice stability (0-1).
            similarity_boost: How closely to match the original voice (0-1).
            style: Style exaggeration (0-1).
            use_speaker_boost: Enable speaker boost for clarity.
        
        Returns:
            VoiceoverResult with audio data.
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured. Set ELEVENLABS_API_KEY environment variable.")
        
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": use_speaker_boost,
            },
        }
        
        try:
            response = self.client.post(
                f"/text-to-speech/{voice_id}",
                json=payload,
                headers={"Accept": "audio/mpeg"},
            )
            response.raise_for_status()
            
            audio_data = response.content
            
            return VoiceoverResult(
                audio_data=audio_data,
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                character_count=len(text),
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs API error: {e.response.text}")
            raise ValueError(f"Failed to generate voiceover: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to generate voiceover: {e}")
            raise
    
    def generate_voiceover_stream(
        self,
        text: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        model_id: str = "eleven_monolingual_v1",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ):
        """
        Generate voiceover with streaming response.
        
        Yields audio chunks as they're generated.
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured")
        
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }
        
        with self.client.stream(
            "POST",
            f"/text-to-speech/{voice_id}/stream",
            json=payload,
            headers={"Accept": "audio/mpeg"},
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                yield chunk
    
    def save_voiceover(
        self,
        result: VoiceoverResult,
        output_path: str,
    ) -> str:
        """
        Save voiceover audio to file.
        
        Args:
            result: VoiceoverResult to save.
            output_path: Path to save the audio file.
        
        Returns:
            Path to the saved file.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output, "wb") as f:
            f.write(result.audio_data)
        
        logger.info(f"Saved voiceover to {output_path}")
        return str(output)
    
    def get_subscription_info(self) -> Dict[str, Any]:
        """Get current subscription information including remaining characters."""
        if not self.api_key:
            return {"error": "API key not configured"}
        
        try:
            response = self.client.get("/user/subscription")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get subscription info: {e}")
            return {"error": str(e)}
    
    def estimate_cost(self, text: str) -> Dict[str, Any]:
        """
        Estimate the cost of generating voiceover for given text.
        
        Args:
            text: Text to estimate cost for.
        
        Returns:
            Dict with character count and estimated cost.
        """
        char_count = len(text)
        
        # ElevenLabs pricing tiers (approximate)
        # Free: 10,000 chars/month
        # Starter: $5/month, 30,000 chars
        # Creator: $22/month, 100,000 chars
        # Pro: $99/month, 500,000 chars
        
        cost_per_char = 0.00018  # Approximate cost at Creator tier
        
        return {
            "character_count": char_count,
            "estimated_cost_usd": round(char_count * cost_per_char, 4),
            "estimated_duration_seconds": char_count / 15,  # ~15 chars/second average
        }


class VoiceoverService:
    """High-level service for voiceover generation."""
    
    def __init__(self):
        self.client = ElevenLabsClient()
    
    def get_recommended_voices(self, content_type: str = "general") -> List[Voice]:
        """
        Get recommended voices for a content type.
        
        Args:
            content_type: Type of content (tutorial, story, meditation, etc.)
        
        Returns:
            List of recommended voices.
        """
        all_voices = self.client.list_voices()
        
        # Filter by content type
        recommendations = {
            "tutorial": ["Josh", "Rachel", "Domi"],
            "story": ["Antoni", "Bella", "Adam"],
            "meditation": ["Bella", "Elli"],
            "professional": ["Josh", "Arnold", "Rachel"],
            "energetic": ["Domi", "Elli", "Antoni"],
            "general": ["Rachel", "Josh", "Adam"],
        }
        
        preferred_names = recommendations.get(content_type, recommendations["general"])
        
        # Sort voices by preference
        def sort_key(voice: Voice) -> int:
            try:
                return preferred_names.index(voice.name)
            except ValueError:
                return len(preferred_names)
        
        return sorted(all_voices, key=sort_key)
    
    def generate_script_voiceover(
        self,
        script_sections: List[Dict[str, str]],
        voice_id: str,
        output_dir: str = "output/voiceovers",
    ) -> List[str]:
        """
        Generate voiceovers for script sections.
        
        Args:
            script_sections: List of dicts with 'name' and 'content' keys.
            voice_id: Voice to use for all sections.
            output_dir: Directory to save audio files.
        
        Returns:
            List of paths to generated audio files.
        """
        output_paths = []
        
        for i, section in enumerate(script_sections):
            name = section.get("name", f"section_{i}")
            content = section.get("content", "")
            
            if not content.strip():
                continue
            
            try:
                result = self.client.generate_voiceover(
                    text=content,
                    voice_id=voice_id,
                )
                
                # Save to file
                filename = f"{i:02d}_{name.lower().replace(' ', '_')}.mp3"
                output_path = os.path.join(output_dir, filename)
                self.client.save_voiceover(result, output_path)
                output_paths.append(output_path)
                
                logger.info(f"Generated voiceover for section: {name}")
            except Exception as e:
                logger.error(f"Failed to generate voiceover for {name}: {e}")
        
        return output_paths
    
    def generate_full_script_voiceover(
        self,
        full_script: str,
        voice_id: str,
        output_path: str = "output/voiceovers/full_script.mp3",
    ) -> str:
        """
        Generate a single voiceover for a full script.
        
        Args:
            full_script: Complete script text.
            voice_id: Voice to use.
            output_path: Path to save the audio file.
        
        Returns:
            Path to the generated audio file.
        """
        result = self.client.generate_voiceover(
            text=full_script,
            voice_id=voice_id,
        )
        
        return self.client.save_voiceover(result, output_path)


# Convenience functions
def generate_voiceover(
    text: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
    output_path: Optional[str] = None,
) -> VoiceoverResult:
    """
    Generate voiceover from text.
    
    Args:
        text: Text to convert to speech.
        voice_id: ElevenLabs voice ID.
        output_path: Optional path to save the audio file.
    
    Returns:
        VoiceoverResult with audio data.
    """
    client = ElevenLabsClient()
    result = client.generate_voiceover(text, voice_id)
    
    if output_path:
        client.save_voiceover(result, output_path)
    
    return result


def list_voices() -> List[Voice]:
    """Get all available ElevenLabs voices."""
    client = ElevenLabsClient()
    return client.list_voices()

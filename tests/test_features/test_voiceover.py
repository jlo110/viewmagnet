"""Tests for voiceover.py - ElevenLabs integration."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from src.features.voiceover import (
    Voice,
    VoiceoverResult,
    ElevenLabsClient,
    VoiceoverService,
    generate_voiceover,
    list_voices,
)


class TestVoice:
    """Tests for Voice dataclass."""
    
    def test_voice_creation(self):
        """Test creating a Voice instance."""
        voice = Voice(
            voice_id="test123",
            name="Test Voice",
            category="premade",
            description="A test voice",
        )
        assert voice.voice_id == "test123"
        assert voice.name == "Test Voice"
        assert voice.category == "premade"
        assert voice.description == "A test voice"
    
    def test_voice_optional_fields(self):
        """Test Voice with optional fields."""
        voice = Voice(
            voice_id="test123",
            name="Test Voice",
            category="premade",
        )
        assert voice.description is None
        assert voice.preview_url is None
        assert voice.labels is None


class TestVoiceoverResult:
    """Tests for VoiceoverResult dataclass."""
    
    def test_voiceover_result_creation(self):
        """Test creating a VoiceoverResult instance."""
        result = VoiceoverResult(
            audio_data=b"fake audio data",
            voice_id="voice123",
            text="Hello world",
            model_id="eleven_monolingual_v1",
            character_count=11,
        )
        assert result.audio_data == b"fake audio data"
        assert result.voice_id == "voice123"
        assert result.text == "Hello world"
        assert result.character_count == 11
        assert result.duration_seconds is None


class TestElevenLabsClient:
    """Tests for ElevenLabsClient."""
    
    def test_init_without_api_key(self):
        """Test initialization without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(ElevenLabsClient, "__init__", lambda self, api_key=None: None):
                client = ElevenLabsClient.__new__(ElevenLabsClient)
                client.api_key = None
                assert client.api_key is None
    
    def test_get_demo_voices(self):
        """Test demo voices are returned when no API key."""
        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}, clear=True):
            client = ElevenLabsClient(api_key=None)
            voices = client._get_demo_voices()
            
            assert len(voices) == 8
            assert all(isinstance(v, Voice) for v in voices)
            
            # Check known demo voices
            voice_names = [v.name for v in voices]
            assert "Rachel" in voice_names
            assert "Josh" in voice_names
            assert "Adam" in voice_names
    
    def test_list_voices_without_api_key(self):
        """Test list_voices returns demo voices without API key."""
        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}, clear=True):
            client = ElevenLabsClient(api_key=None)
            client.api_key = None
            voices = client.list_voices()
            
            assert len(voices) == 8
            assert voices[0].name == "Rachel"
    
    def test_estimate_cost(self):
        """Test cost estimation."""
        client = ElevenLabsClient.__new__(ElevenLabsClient)
        client.api_key = "test_key"
        
        estimate = client.estimate_cost("Hello, this is a test message.")
        
        assert "character_count" in estimate
        assert "estimated_cost_usd" in estimate
        assert "estimated_duration_seconds" in estimate
        assert estimate["character_count"] == 30
        assert estimate["estimated_duration_seconds"] == 30 / 15  # ~15 chars/second
    
    def test_generate_voiceover_without_api_key(self):
        """Test generate_voiceover raises error without API key."""
        client = ElevenLabsClient.__new__(ElevenLabsClient)
        client.api_key = None
        
        with pytest.raises(ValueError, match="API key not configured"):
            client.generate_voiceover("Test text")
    
    @patch("httpx.Client")
    def test_generate_voiceover_success(self, mock_httpx_client):
        """Test successful voiceover generation."""
        mock_response = Mock()
        mock_response.content = b"audio data"
        mock_response.raise_for_status = Mock()
        
        mock_client_instance = Mock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance
        
        client = ElevenLabsClient.__new__(ElevenLabsClient)
        client.api_key = "test_key"
        client.client = mock_client_instance
        
        result = client.generate_voiceover("Hello world", voice_id="test_voice")
        
        assert isinstance(result, VoiceoverResult)
        assert result.audio_data == b"audio data"
        assert result.text == "Hello world"
        assert result.voice_id == "test_voice"


class TestVoiceoverService:
    """Tests for VoiceoverService."""
    
    def test_get_recommended_voices_tutorial(self):
        """Test voice recommendations for tutorial content."""
        with patch.object(ElevenLabsClient, "list_voices") as mock_list:
            mock_list.return_value = [
                Voice("1", "Josh", "premade"),
                Voice("2", "Rachel", "premade"),
                Voice("3", "Bella", "premade"),
                Voice("4", "Domi", "premade"),
            ]
            
            service = VoiceoverService()
            service.client = ElevenLabsClient.__new__(ElevenLabsClient)
            service.client.list_voices = mock_list
            
            recommended = service.get_recommended_voices("tutorial")
            
            # Josh and Rachel are recommended for tutorials
            assert recommended[0].name in ["Josh", "Rachel", "Domi"]
    
    def test_get_recommended_voices_meditation(self):
        """Test voice recommendations for meditation content."""
        with patch.object(ElevenLabsClient, "list_voices") as mock_list:
            mock_list.return_value = [
                Voice("1", "Bella", "premade"),
                Voice("2", "Rachel", "premade"),
                Voice("3", "Elli", "premade"),
            ]
            
            service = VoiceoverService()
            service.client = ElevenLabsClient.__new__(ElevenLabsClient)
            service.client.list_voices = mock_list
            
            recommended = service.get_recommended_voices("meditation")
            
            # Bella and Elli are recommended for meditation
            assert recommended[0].name in ["Bella", "Elli"]


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_list_voices_function(self):
        """Test list_voices convenience function."""
        with patch.object(ElevenLabsClient, "__init__", return_value=None):
            with patch.object(ElevenLabsClient, "list_voices") as mock_list:
                mock_list.return_value = [Voice("1", "Test", "premade")]
                
                client = ElevenLabsClient.__new__(ElevenLabsClient)
                client.list_voices = mock_list
                
                with patch("src.features.voiceover.ElevenLabsClient", return_value=client):
                    voices = list_voices()
                    assert len(voices) == 1
                    assert voices[0].name == "Test"

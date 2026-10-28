"""
Tests for Voice Dubbing module.
"""

import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os


from src.features.voice_dubbing import (
    DubbingStatus,
    DubbingJob,
    VoiceDubbingClient,
    SUPPORTED_LANGUAGES,
    get_supported_languages,
    start_dubbing_job,
    check_dubbing_status,
    download_dubbed_result,
)


class TestDubbingStatus:
    """Tests for DubbingStatus enum."""
    
    def test_status_values(self):
        assert DubbingStatus.PENDING.value == "pending"
        assert DubbingStatus.DUBBING.value == "dubbing"
        assert DubbingStatus.DUBBED.value == "dubbed"
        assert DubbingStatus.FAILED.value == "failed"


class TestDubbingJob:
    """Tests for DubbingJob dataclass."""
    
    def test_creation(self):
        job = DubbingJob(
            dubbing_id="test-123",
            status=DubbingStatus.PENDING,
            target_language="es"
        )
        
        assert job.dubbing_id == "test-123"
        assert job.status == DubbingStatus.PENDING
        assert job.target_language == "es"
        assert job.source_language is None
        assert job.error is None
    
    def test_to_dict(self):
        job = DubbingJob(
            dubbing_id="test-456",
            status=DubbingStatus.DUBBED,
            target_language="fr",
            source_language="en",
            expected_duration_sec=120.0
        )
        
        result = job.to_dict()
        
        assert result["dubbing_id"] == "test-456"
        assert result["status"] == "dubbed"
        assert result["target_language"] == "fr"
        assert result["source_language"] == "en"
        assert result["expected_duration_sec"] == 120.0


class TestSupportedLanguages:
    """Tests for supported languages."""
    
    def test_has_common_languages(self):
        assert "en" in SUPPORTED_LANGUAGES
        assert "es" in SUPPORTED_LANGUAGES
        assert "fr" in SUPPORTED_LANGUAGES
        assert "de" in SUPPORTED_LANGUAGES
        assert "ja" in SUPPORTED_LANGUAGES
        assert "ko" in SUPPORTED_LANGUAGES
        assert "zh" in SUPPORTED_LANGUAGES
    
    def test_language_names(self):
        assert SUPPORTED_LANGUAGES["en"] == "English"
        assert SUPPORTED_LANGUAGES["es"] == "Spanish"
        assert SUPPORTED_LANGUAGES["fr"] == "French"
    
    def test_get_supported_languages(self):
        langs = get_supported_languages()
        assert isinstance(langs, dict)
        assert len(langs) > 20
        assert langs == SUPPORTED_LANGUAGES


class TestVoiceDubbingClient:
    """Tests for VoiceDubbingClient class."""
    
    def test_init_without_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            client = VoiceDubbingClient()
            assert client.api_key is None
    
    def test_init_with_api_key(self):
        client = VoiceDubbingClient(api_key="test-key")
        assert client.api_key == "test-key"
    
    def test_init_from_env(self):
        with patch.dict('os.environ', {"ELEVENLABS_API_KEY": "env-key"}):
            client = VoiceDubbingClient()
            assert client.api_key == "env-key"
    
    def test_create_dubbing_raises_without_api_key(self):
        client = VoiceDubbingClient()
        client.api_key = None
        
        with pytest.raises(ValueError, match="API key not configured"):
            client.create_dubbing_project(
                video_path="/test.mp4",
                target_language="es"
            )
    
    def test_create_dubbing_raises_for_unsupported_language(self):
        client = VoiceDubbingClient(api_key="test-key")
        
        with pytest.raises(ValueError, match="Unsupported language"):
            client.create_dubbing_project(
                video_path="/test.mp4",
                target_language="xyz"
            )
    
    @patch('httpx.Client')
    def test_create_dubbing_success(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "dubbing_id": "dub-123",
            "expected_duration_sec": 120.0
        }
        
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        client = VoiceDubbingClient(api_key="test-key")
        
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"dummy video content")
            video_path = f.name
        
        try:
            job = client.create_dubbing_project(
                video_path=video_path,
                target_language="es"
            )
            
            assert job.dubbing_id == "dub-123"
            assert job.status == DubbingStatus.PENDING
            assert job.target_language == "es"
            assert job.expected_duration_sec == 120.0
        finally:
            os.unlink(video_path)
    
    @patch('httpx.Client')
    def test_get_dubbing_status_success(self, mock_client_class):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "dubbed",
            "target_lang": "es",
            "source_lang": "en"
        }
        
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        client = VoiceDubbingClient(api_key="test-key")
        job = client.get_dubbing_status("dub-123")
        
        assert job.dubbing_id == "dub-123"
        assert job.status == DubbingStatus.DUBBED
        assert job.target_language == "es"
        assert job.source_language == "en"


class TestStartDubbingJob:
    """Tests for start_dubbing_job convenience function."""
    
    @patch.object(VoiceDubbingClient, 'create_dubbing_project')
    def test_starts_job_and_stores_in_memory(self, mock_create):
        mock_job = DubbingJob(
            dubbing_id="func-123",
            status=DubbingStatus.PENDING,
            target_language="de"
        )
        mock_create.return_value = mock_job
        
        result = start_dubbing_job(
            video_path="/test.mp4",
            target_language="de",
            api_key="test-key"
        )
        
        assert result.dubbing_id == "func-123"
        assert result.target_language == "de"


class TestCheckDubbingStatus:
    """Tests for check_dubbing_status convenience function."""
    
    @patch.object(VoiceDubbingClient, 'get_dubbing_status')
    def test_checks_status(self, mock_get_status):
        mock_job = DubbingJob(
            dubbing_id="check-123",
            status=DubbingStatus.DUBBING,
            target_language="fr"
        )
        mock_get_status.return_value = mock_job
        
        result = check_dubbing_status("check-123", api_key="test-key")
        
        assert result.dubbing_id == "check-123"
        assert result.status == DubbingStatus.DUBBING


class TestDownloadDubbedResult:
    """Tests for download_dubbed_result convenience function."""
    
    def test_raises_if_job_not_complete(self):
        from src.features.voice_dubbing import _dubbing_jobs
        
        # Store incomplete job
        _dubbing_jobs["incomplete-123"] = DubbingJob(
            dubbing_id="incomplete-123",
            status=DubbingStatus.DUBBING,
            target_language="es"
        )
        
        with pytest.raises(ValueError, match="Job not complete"):
            download_dubbed_result(
                dubbing_id="incomplete-123",
                output_path="/output.mp4",
                api_key="test-key"
            )

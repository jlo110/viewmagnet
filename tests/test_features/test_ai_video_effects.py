"""
Tests for AI Video Effects Generator module.
"""

import pytest
import json
from unittest.mock import patch, MagicMock

from src.features.ai_video_effects import (
    EffectIntensity,
    EffectSegment,
    EffectsConfig,
    VideoEffectsGenerator,
    apply_effects_to_video,
    get_video_info,
)


class TestEffectIntensity:
    """Tests for EffectIntensity enum."""
    
    def test_intensity_values(self):
        assert EffectIntensity.SUBTLE.value == "subtle"
        assert EffectIntensity.MEDIUM.value == "medium"
        assert EffectIntensity.DRAMATIC.value == "dramatic"


class TestEffectSegment:
    """Tests for EffectSegment dataclass."""
    
    def test_default_values(self):
        segment = EffectSegment(start_sec=0, end_sec=10)
        assert segment.zoom == 1.0
        assert segment.zoom_center_x == 0.5
        assert segment.zoom_center_y == 0.5
        assert segment.brightness == 1.0
        assert segment.contrast == 1.0
        assert segment.saturate == 1.0
        assert segment.description == ""
    
    def test_custom_values(self):
        segment = EffectSegment(
            start_sec=5.0,
            end_sec=15.0,
            zoom=1.2,
            contrast=1.1,
            description="Key moment"
        )
        assert segment.start_sec == 5.0
        assert segment.end_sec == 15.0
        assert segment.zoom == 1.2
        assert segment.contrast == 1.1
        assert segment.description == "Key moment"


class TestEffectsConfig:
    """Tests for EffectsConfig dataclass."""
    
    def test_default_values(self):
        config = EffectsConfig()
        assert config.segments == []
        assert config.filter_string is None
        assert config.intensity == EffectIntensity.MEDIUM
    
    def test_to_dict(self):
        segment = EffectSegment(start_sec=0, end_sec=10, zoom=1.2)
        config = EffectsConfig(
            segments=[segment],
            filter_string="zoompan=...",
            intensity=EffectIntensity.DRAMATIC
        )
        
        result = config.to_dict()
        
        assert len(result["segments"]) == 1
        assert result["segments"][0]["zoom"] == 1.2
        assert result["filter_string"] == "zoompan=..."
        assert result["intensity"] == "dramatic"


class TestVideoEffectsGenerator:
    """Tests for VideoEffectsGenerator class."""
    
    def test_init_without_api_key(self):
        with patch.dict('os.environ', {}, clear=True):
            generator = VideoEffectsGenerator()
            assert generator.api_key is None
    
    def test_init_with_api_key(self):
        generator = VideoEffectsGenerator(api_key="test-key")
        assert generator.api_key == "test-key"
    
    def test_get_default_effects_subtle(self):
        generator = VideoEffectsGenerator()
        config = generator._get_default_effects(60.0, EffectIntensity.SUBTLE)
        
        assert len(config.segments) == 1
        assert config.segments[0].zoom == 1.05
        assert config.filter_string is not None
    
    def test_get_default_effects_dramatic(self):
        generator = VideoEffectsGenerator()
        config = generator._get_default_effects(60.0, EffectIntensity.DRAMATIC)
        
        assert config.segments[0].zoom == 1.15
    
    def test_generate_ffmpeg_filter_basic(self):
        generator = VideoEffectsGenerator()
        segments = [
            EffectSegment(start_sec=0, end_sec=5, zoom=1.1),
            EffectSegment(start_sec=5, end_sec=10, zoom=1.2),
        ]
        
        filter_string = generator._generate_ffmpeg_filter(
            segments=segments,
            duration=10.0,
            fps=30,
            width=1080,
            height=1920
        )
        
        assert "zoompan" in filter_string
        assert "1080x1920" in filter_string
    
    def test_generate_ffmpeg_filter_with_contrast(self):
        generator = VideoEffectsGenerator()
        segments = [
            EffectSegment(start_sec=0, end_sec=5, contrast=1.2),
        ]
        
        filter_string = generator._generate_ffmpeg_filter(
            segments=segments,
            duration=5.0,
            fps=30,
            width=1080,
            height=1920
        )
        
        assert "eq=contrast" in filter_string
    
    @patch('anthropic.Anthropic')
    def test_analyze_with_api(self, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "segments": [
                {
                    "start_sec": 0,
                    "end_sec": 10,
                    "zoom": 1.15,
                    "description": "Opening"
                }
            ]
        }))]
        
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client
        
        generator = VideoEffectsGenerator(api_key="test-key")
        config = generator.analyze_and_generate_effects(
            transcript="Test transcript for video",
            duration=30.0,
            intensity=EffectIntensity.MEDIUM
        )
        
        assert len(config.segments) > 0
        assert config.filter_string is not None
    
    def test_sanitize_filter_string(self):
        # Test comparison operator conversion
        filter_str = "enable='n>=30'"
        result = VideoEffectsGenerator.sanitize_filter_string(filter_str)
        assert "gte(n,30)" in result
        
        filter_str2 = "enable='t<5.0'"
        result2 = VideoEffectsGenerator.sanitize_filter_string(filter_str2)
        assert "lt(t,5.0)" in result2


class TestGetVideoInfo:
    """Tests for get_video_info function."""
    
    @patch('subprocess.check_output')
    def test_parses_ffprobe_output(self, mock_check_output):
        mock_check_output.return_value = json.dumps({
            "streams": [{
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "duration": "120.0"
            }],
            "format": {"duration": "120.0"}
        }).encode()
        
        info = get_video_info("/path/to/video.mp4")
        
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["fps"] == 30
        assert info["duration"] == 120.0
    
    @patch('subprocess.check_output')
    def test_handles_fractional_fps(self, mock_check_output):
        mock_check_output.return_value = json.dumps({
            "streams": [{
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30000/1001",
                "duration": "60.0"
            }],
            "format": {}
        }).encode()
        
        info = get_video_info("/path/to/video.mp4")
        
        # 30000/1001 ≈ 29.97
        assert info["fps"] in [29, 30]
    
    @patch('subprocess.check_output')
    def test_returns_defaults_on_error(self, mock_check_output):
        mock_check_output.side_effect = Exception("ffprobe error")
        
        info = get_video_info("/path/to/video.mp4")
        
        assert info["width"] == 1080
        assert info["height"] == 1920
        assert info["fps"] == 30
        assert info["duration"] == 60


class TestApplyEffectsToVideo:
    """Tests for apply_effects_to_video function."""
    
    @patch('subprocess.run')
    def test_copies_if_no_filter(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        
        config = EffectsConfig(filter_string=None)
        result = apply_effects_to_video(
            input_path="/input.mp4",
            output_path="/output.mp4",
            effects_config=config
        )
        
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "-c" in call_args
        assert "copy" in call_args
    
    @patch('subprocess.run')
    def test_applies_filter_string(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        
        config = EffectsConfig(filter_string="zoompan=z='1.1'")
        result = apply_effects_to_video(
            input_path="/input.mp4",
            output_path="/output.mp4",
            effects_config=config
        )
        
        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "-vf" in call_args

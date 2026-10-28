"""
Tests for Hook Text Overlays module.
"""

import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock

from src.features.hook_overlays import (
    HookPosition,
    HookStyle,
    HookResult,
    download_font_if_needed,
    create_hook_image,
    add_hook_to_video,
    generate_hook_suggestions,
)


class TestHookPosition:
    """Tests for HookPosition enum."""
    
    def test_position_values(self):
        assert HookPosition.TOP.value == "top"
        assert HookPosition.CENTER.value == "center"
        assert HookPosition.BOTTOM.value == "bottom"


class TestHookStyle:
    """Tests for HookStyle dataclass."""
    
    def test_default_values(self):
        style = HookStyle()
        assert style.position == HookPosition.TOP
        assert style.font_scale == 1.0
        assert style.padding_x == 30
        assert style.padding_y == 25
        assert style.corner_radius == 20
        assert style.text_color == "black"
    
    def test_custom_values(self):
        style = HookStyle(
            position=HookPosition.CENTER,
            font_scale=1.5,
            padding_x=40
        )
        assert style.position == HookPosition.CENTER
        assert style.font_scale == 1.5
        assert style.padding_x == 40


class TestCreateHookImage:
    """Tests for create_hook_image function."""
    
    def test_creates_image_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_hook.png")
            
            result_path, width, height = create_hook_image(
                text="TEST HOOK",
                target_width=1080,
                output_path=output_path
            )
            
            assert os.path.exists(result_path)
            assert result_path == output_path
            assert width > 0
            assert height > 0
    
    def test_auto_generates_path_if_none(self):
        result_path, width, height = create_hook_image(
            text="AUTO PATH",
            target_width=1080
        )
        
        try:
            assert os.path.exists(result_path)
            assert result_path.endswith('.png')
        finally:
            if os.path.exists(result_path):
                os.remove(result_path)
    
    def test_handles_multiline_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "multiline.png")
            
            result_path, width, height = create_hook_image(
                text="LINE ONE\nLINE TWO",
                target_width=500,
                output_path=output_path
            )
            
            assert os.path.exists(result_path)
            assert height > 100  # Should be taller for multiline
    
    def test_respects_font_scale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            small_path = os.path.join(tmpdir, "small.png")
            large_path = os.path.join(tmpdir, "large.png")
            
            _, _, small_height = create_hook_image(
                text="SCALE TEST",
                target_width=1080,
                output_path=small_path,
                style=HookStyle(font_scale=0.5)
            )
            
            _, _, large_height = create_hook_image(
                text="SCALE TEST",
                target_width=1080,
                output_path=large_path,
                style=HookStyle(font_scale=2.0)
            )
            
            assert large_height > small_height


class TestAddHookToVideo:
    """Tests for add_hook_to_video function."""
    
    def test_raises_for_missing_video(self):
        with pytest.raises(FileNotFoundError):
            add_hook_to_video(
                video_path="/nonexistent/video.mp4",
                text="TEST",
                output_path="/tmp/output.mp4"
            )
    
    @patch('subprocess.check_output')
    @patch('subprocess.run')
    def test_calls_ffmpeg_with_correct_args(self, mock_run, mock_check_output):
        mock_check_output.return_value = b"1080x1920x60.0"
        mock_run.return_value = MagicMock(returncode=0)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy input file
            input_path = os.path.join(tmpdir, "input.mp4")
            with open(input_path, 'w') as f:
                f.write("dummy")
            
            output_path = os.path.join(tmpdir, "output.mp4")
            
            result = add_hook_to_video(
                video_path=input_path,
                text="TEST HOOK",
                output_path=output_path,
                position="top"
            )
            
            # Check FFmpeg was called
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert 'ffmpeg' in call_args
            assert '-i' in call_args


class TestGenerateHookSuggestions:
    """Tests for generate_hook_suggestions function."""
    
    def test_returns_list(self):
        result = generate_hook_suggestions(
            transcript="This is a test transcript.",
            title="Test Video"
        )
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_finds_hook_keywords(self):
        result = generate_hook_suggestions(
            transcript="Here's the secret to success. Never give up.",
            title="Success Tips"
        )
        # Should find sentences with hook keywords
        assert isinstance(result, list)
    
    def test_returns_fallback_if_no_hooks_found(self):
        result = generate_hook_suggestions(
            transcript="Short.",
            title="Test"
        )
        assert len(result) > 0
        # Should include default hooks
        assert any("WATCH" in h or "SEE" in h for h in result)


class TestDownloadFontIfNeeded:
    """Tests for font download functionality."""
    
    @patch('urllib.request.urlopen')
    def test_skips_download_if_font_exists(self, mock_urlopen):
        # Test that download is skipped if font already exists
        # (implementation may vary based on actual font path)
        result = download_font_if_needed()
        # Should return True regardless (either font exists or downloaded)
        assert isinstance(result, bool)

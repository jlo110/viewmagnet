"""Tests for smart subject tracking module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from src.features.subject_tracker import (
    SubjectTracker,
    TrackingMode,
    TrackingResult,
    BoundingBox,
    FrameTracking,
)


class TestBoundingBox:
    """Tests for BoundingBox dataclass."""
    
    def test_center_x(self):
        """Test center_x calculation."""
        box = BoundingBox(x=100, y=50, width=200, height=300)
        assert box.center_x == 200  # 100 + 200/2
    
    def test_center_y(self):
        """Test center_y calculation."""
        box = BoundingBox(x=100, y=50, width=200, height=300)
        assert box.center_y == 200  # 50 + 300/2
    
    def test_area(self):
        """Test area calculation."""
        box = BoundingBox(x=100, y=50, width=200, height=300)
        assert box.area == 60000  # 200 * 300


class TestFrameTracking:
    """Tests for FrameTracking dataclass."""
    
    def test_frame_tracking_creation(self):
        """Test creating frame tracking."""
        tracking = FrameTracking(
            frame_number=10,
            timestamp=0.333,
            crop_x=656
        )
        assert tracking.frame_number == 10
        assert tracking.timestamp == 0.333
        assert tracking.crop_x == 656
        assert tracking.subjects == []
        assert tracking.primary_subject is None


class TestTrackingResult:
    """Tests for TrackingResult dataclass."""
    
    def test_get_crop_at_time_empty(self):
        """Test get_crop_at_time with no positions."""
        result = TrackingResult()
        # Should return center crop for 1080p
        crop_x = result.get_crop_at_time(1.0)
        expected = (1920 - int(1080 * 9 / 16)) // 2
        assert crop_x == expected
    
    def test_get_crop_at_time_with_positions(self):
        """Test get_crop_at_time with positions."""
        result = TrackingResult(
            smoothed_crop_positions=[500, 520, 540, 560, 580],
            fps=30.0
        )
        # At time 0, should be position 0
        assert result.get_crop_at_time(0) == 500
        # At time 0.1s (frame 3), should be position 3
        assert result.get_crop_at_time(0.1) == 560
    
    def test_to_ffmpeg_filter_static(self):
        """Test FFmpeg filter for static crop."""
        result = TrackingResult(
            smoothed_crop_positions=[600, 600, 600],
            frame_height=1080
        )
        filter_str = result.to_ffmpeg_filter()
        assert "crop=607:1080:600:0" in filter_str
    
    def test_export_keyframes(self):
        """Test exporting keyframes to JSON."""
        result = TrackingResult(
            smoothed_crop_positions=list(range(100)),
            fps=30.0,
            frame_width=1920,
            frame_height=1080
        )
        
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            result.export_keyframes(f.name)
            
            import json
            with open(f.name) as rf:
                data = json.load(rf)
            
            assert data["fps"] == 30.0
            assert data["total_frames"] == 100
            assert len(data["keyframes"]) > 0
            
            os.unlink(f.name)


class TestSubjectTracker:
    """Tests for SubjectTracker class."""
    
    @pytest.fixture
    def tracker(self):
        """Create a tracker instance."""
        return SubjectTracker(
            mode=TrackingMode.SPEAKER,
            smoothing_window=5,
            max_velocity=50.0,
            detection_interval=5
        )
    
    def test_initialization(self, tracker):
        """Test tracker initialization."""
        assert tracker.mode == TrackingMode.SPEAKER
        assert tracker.smoothing_window == 5
        assert tracker.max_velocity == 50.0
        assert tracker.detection_interval == 5
    
    def test_select_primary_subject_no_candidates(self, tracker):
        """Test selecting primary subject with no candidates."""
        result = tracker.select_primary_subject([], [], 1920, 1080)
        assert result is None
    
    def test_select_primary_subject_single_face(self, tracker):
        """Test selecting primary subject with one face."""
        faces = [BoundingBox(x=800, y=200, width=200, height=200, confidence=0.9)]
        result = tracker.select_primary_subject(faces, [], 1920, 1080)
        assert result == faces[0]
    
    def test_select_primary_subject_prefers_larger(self, tracker):
        """Test that larger subjects are preferred."""
        faces = [
            BoundingBox(x=800, y=200, width=100, height=100, confidence=0.9),
            BoundingBox(x=700, y=200, width=300, height=300, confidence=0.9),
        ]
        result = tracker.select_primary_subject(faces, [], 1920, 1080)
        assert result == faces[1]  # Larger face
    
    def test_select_primary_subject_prefers_centered(self, tracker):
        """Test that centered subjects are preferred when similar size."""
        faces = [
            BoundingBox(x=100, y=200, width=200, height=200, confidence=0.9),  # Left
            BoundingBox(x=860, y=200, width=200, height=200, confidence=0.9),  # Center
        ]
        result = tracker.select_primary_subject(faces, [], 1920, 1080)
        assert result == faces[1]  # Centered face
    
    def test_calculate_crop_position_no_subject(self, tracker):
        """Test crop position with no subject (defaults to center)."""
        crop_x = tracker.calculate_crop_position(
            subject=None,
            frame_width=1920,
            frame_height=1080,
            crop_width=607
        )
        expected = (1920 - 607) // 2
        assert crop_x == expected
    
    def test_calculate_crop_position_with_subject(self, tracker):
        """Test crop position centers on subject."""
        subject = BoundingBox(x=800, y=200, width=200, height=200)
        crop_x = tracker.calculate_crop_position(
            subject=subject,
            frame_width=1920,
            frame_height=1080,
            crop_width=607
        )
        # Should center the crop on the subject
        expected = subject.center_x - 607 // 2
        assert crop_x == expected
    
    def test_calculate_crop_position_velocity_limit(self, tracker):
        """Test that crop velocity is limited."""
        subject = BoundingBox(x=1500, y=200, width=200, height=200)
        crop_x = tracker.calculate_crop_position(
            subject=subject,
            frame_width=1920,
            frame_height=1080,
            crop_width=607,
            previous_crop_x=500  # Far from ideal position
        )
        # Should be limited by max_velocity
        assert abs(crop_x - 500) <= tracker.max_velocity
    
    def test_calculate_crop_position_clamped(self, tracker):
        """Test that crop position is clamped to valid range."""
        subject = BoundingBox(x=0, y=200, width=50, height=50)  # Far left
        crop_x = tracker.calculate_crop_position(
            subject=subject,
            frame_width=1920,
            frame_height=1080,
            crop_width=607
        )
        assert crop_x >= 0
        
        subject = BoundingBox(x=1870, y=200, width=50, height=50)  # Far right
        crop_x = tracker.calculate_crop_position(
            subject=subject,
            frame_width=1920,
            frame_height=1080,
            crop_width=607
        )
        assert crop_x <= 1920 - 607
    
    def test_smooth_crop_positions_single(self, tracker):
        """Test smoothing with single position."""
        positions = [600]
        smoothed = tracker.smooth_crop_positions(positions)
        assert smoothed == [600]
    
    def test_smooth_crop_positions_stable(self, tracker):
        """Test smoothing with stable positions."""
        positions = [600, 600, 600, 600, 600]
        smoothed = tracker.smooth_crop_positions(positions)
        # All should remain 600
        assert all(abs(p - 600) < 5 for p in smoothed)
    
    def test_smooth_crop_positions_gradual_change(self, tracker):
        """Test smoothing with gradually changing positions."""
        positions = [500, 520, 540, 560, 580]
        smoothed = tracker.smooth_crop_positions(positions)
        # Should smooth the progression
        assert len(smoothed) == 5
        # First and last should be close to originals
        assert abs(smoothed[0] - 500) < 30
        assert abs(smoothed[-1] - 580) < 30


class TestSubjectTrackerIntegration:
    """Integration tests for SubjectTracker with video processing."""
    
    @pytest.mark.skip(reason="Requires video file and ML models")
    def test_track_video_segment(self):
        """Test tracking a video segment."""
        tracker = SubjectTracker(mode=TrackingMode.SPEAKER)
        result = tracker.track_video_segment(
            video_path="test_video.mp4",
            start_time=0,
            end_time=10
        )
        assert isinstance(result, TrackingResult)
        assert len(result.smoothed_crop_positions) > 0
    
    @patch('cv2.VideoCapture')
    def test_track_video_segment_mocked(self, mock_cap):
        """Test tracking with mocked video capture."""
        # Setup mock
        mock_cap_instance = MagicMock()
        mock_cap.return_value = mock_cap_instance
        mock_cap_instance.isOpened.return_value = True
        mock_cap_instance.get.side_effect = lambda prop: {
            5: 30.0,   # FPS
            3: 1920,   # Width
            4: 1080,   # Height
            7: 150,    # Total frames
        }.get(prop, 0)
        
        # Return 5 frames then stop
        frames_returned = [0]
        def read_frame():
            if frames_returned[0] < 5:
                frames_returned[0] += 1
                return True, np.zeros((1080, 1920, 3), dtype=np.uint8)
            return False, None
        
        mock_cap_instance.read.side_effect = read_frame
        
        # Create tracker that skips actual detection
        tracker = SubjectTracker(
            mode=TrackingMode.CENTER,  # Center mode doesn't need detection
            detection_interval=1
        )
        
        result = tracker.track_video_segment(
            video_path="test_video.mp4",
            start_time=0,
            end_time=5/30
        )
        
        assert isinstance(result, TrackingResult)
        assert result.fps == 30.0
        assert result.frame_width == 1920
        assert result.frame_height == 1080


class TestTrackingModes:
    """Tests for different tracking modes."""
    
    def test_center_mode(self):
        """Test CENTER tracking mode."""
        tracker = SubjectTracker(mode=TrackingMode.CENTER)
        assert tracker.mode == TrackingMode.CENTER
    
    def test_face_mode(self):
        """Test FACE tracking mode."""
        tracker = SubjectTracker(mode=TrackingMode.FACE)
        assert tracker.mode == TrackingMode.FACE
    
    def test_person_mode(self):
        """Test PERSON tracking mode."""
        tracker = SubjectTracker(mode=TrackingMode.PERSON)
        assert tracker.mode == TrackingMode.PERSON
    
    def test_speaker_mode(self):
        """Test SPEAKER tracking mode."""
        tracker = SubjectTracker(mode=TrackingMode.SPEAKER)
        assert tracker.mode == TrackingMode.SPEAKER

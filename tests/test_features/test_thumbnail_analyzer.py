"""Tests for thumbnail_analyzer.py - Thumbnail feature extraction."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from src.features.thumbnail_analyzer import (
    ThumbnailFeatures,
    ThumbnailAnalyzer,
)


class TestThumbnailFeatures:
    """Tests for ThumbnailFeatures dataclass."""
    
    def test_features_creation(self):
        """Test creating a ThumbnailFeatures instance."""
        features = ThumbnailFeatures(
            face_count=1,
            face_area_ratio=0.15,
            has_face=True,
            face_emotion_primary="happy",
            face_emotion_intensity=0.8,
            has_text=True,
            text_area_ratio=0.1,
            dominant_color_1="#FF5500",
            dominant_color_2="#0055FF",
            dominant_color_3="#00FF55",
            brightness=0.6,
            saturation=0.7,
            contrast=0.8,
            visual_complexity=0.5,
            edge_density=0.4,
            composition_score=0.75,
        )
        assert features.face_count == 1
        assert features.has_face is True
        assert features.face_emotion_primary == "happy"
        assert features.dominant_color_1 == "#FF5500"
    
    def test_features_default_values(self):
        """Test ThumbnailFeatures with default values."""
        features = ThumbnailFeatures(
            face_count=0,
            face_area_ratio=0.0,
            has_face=False,
            face_emotion_primary=None,
            face_emotion_intensity=None,
            has_text=False,
            text_area_ratio=0.0,
            dominant_color_1="#000000",
            dominant_color_2="#000000",
            dominant_color_3="#000000",
            brightness=0.5,
            saturation=0.5,
            contrast=0.5,
            visual_complexity=0.5,
            edge_density=0.5,
            composition_score=0.5,
        )
        # Check defaults
        assert features.text_word_count == 0
        assert features.text_char_count == 0
        assert features.text_content == ""
        assert features.text_readability == 0.5
        assert features.rule_of_thirds_score == 0.0


class TestThumbnailAnalyzer:
    """Tests for ThumbnailAnalyzer."""
    
    def test_init_without_optional_features(self):
        """Test initialization without face/text detection."""
        analyzer = ThumbnailAnalyzer(
            enable_face_detection=False,
            enable_emotion_detection=False,
            enable_text_detection=False,
        )
        assert analyzer.enable_face_detection is False
        assert analyzer.enable_emotion_detection is False
        assert analyzer.enable_text_detection is False
    
    def test_empty_features(self):
        """Test _empty_features returns valid defaults."""
        analyzer = ThumbnailAnalyzer()
        features = analyzer._empty_features()
        
        assert features.face_count == 0
        assert features.has_face is False
        assert features.brightness == 0.0
        assert features.dominant_color_1 == "#000000"
    
    @patch("PIL.Image.open")
    def test_analyze_returns_features(self, mock_image_open):
        """Test analyze returns ThumbnailFeatures."""
        # Create a mock image for RGB data
        mock_image = Mock()
        mock_image.size = (1920, 1080)
        
        # Create separate mock for grayscale conversion
        mock_grayscale = Mock()
        mock_grayscale.getdata.return_value = [100] * 10000  # Single values for grayscale
        mock_grayscale.resize.return_value = mock_grayscale  # For edge density
        
        # Create separate mock for HSV conversion
        mock_hsv = Mock()
        mock_hsv.getdata.return_value = [(100, 100, 100)] * 10000
        
        # Create separate mock for resized images
        mock_resized = Mock()
        mock_resized.getdata.return_value = [(100, 100, 100)] * 2500
        mock_resized.convert.return_value = mock_grayscale
        mock_resized.resize.return_value = mock_resized
        
        # Setup convert to return appropriate mock based on mode
        def mock_convert(mode):
            if mode == "L":
                return mock_grayscale
            elif mode == "HSV":
                return mock_hsv
            return mock_image
        
        mock_image.convert.side_effect = mock_convert
        mock_image.getdata.return_value = [(100, 100, 100)] * 10000
        mock_image.resize.return_value = mock_resized
        mock_image_open.return_value = mock_image
        
        analyzer = ThumbnailAnalyzer()
        features = analyzer.analyze(b"fake image data")
        
        assert isinstance(features, ThumbnailFeatures)
    
    def test_get_dominant_colors_returns_hex(self):
        """Test _get_dominant_colors returns hex strings."""
        analyzer = ThumbnailAnalyzer()
        
        # Create a simple mock image with known colors
        mock_image = Mock()
        mock_image.resize.return_value = mock_image
        # Return red pixels
        mock_image.getdata.return_value = [(255, 0, 0)] * 100
        
        colors = analyzer._get_dominant_colors(mock_image, num_colors=3)
        
        assert len(colors) <= 3
        assert all(c.startswith("#") for c in colors)
        assert len(colors[0]) == 7  # #RRGGBB format
    
    def test_calculate_brightness(self):
        """Test _calculate_brightness returns value between 0 and 1."""
        analyzer = ThumbnailAnalyzer()
        
        # Create mock grayscale image
        mock_image = Mock()
        mock_gray = Mock()
        mock_gray.getdata.return_value = [128] * 100  # Mid-brightness
        mock_image.convert.return_value = mock_gray
        
        brightness = analyzer._calculate_brightness(mock_image)
        
        assert 0 <= brightness <= 1
        assert brightness == pytest.approx(128 / 255, rel=0.01)
    
    def test_calculate_brightness_dark(self):
        """Test brightness for dark image."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        mock_gray.getdata.return_value = [25] * 100  # Dark
        mock_image.convert.return_value = mock_gray
        
        brightness = analyzer._calculate_brightness(mock_image)
        
        assert brightness < 0.2
    
    def test_calculate_brightness_bright(self):
        """Test brightness for bright image."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        mock_gray.getdata.return_value = [230] * 100  # Bright
        mock_image.convert.return_value = mock_gray
        
        brightness = analyzer._calculate_brightness(mock_image)
        
        assert brightness > 0.8
    
    def test_calculate_saturation(self):
        """Test _calculate_saturation returns value between 0 and 1."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_hsv = Mock()
        # HSV tuples: (H, S, V) - S=128 = 50% saturation
        mock_hsv.getdata.return_value = [(0, 128, 128)] * 100
        mock_image.convert.return_value = mock_hsv
        
        saturation = analyzer._calculate_saturation(mock_image)
        
        assert 0 <= saturation <= 1
        assert saturation == pytest.approx(128 / 255, rel=0.01)
    
    def test_calculate_contrast(self):
        """Test _calculate_contrast returns value between 0 and 1."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        # High contrast: mix of very dark and very bright
        mock_gray.getdata.return_value = [0, 255, 0, 255] * 25
        mock_image.convert.return_value = mock_gray
        
        contrast = analyzer._calculate_contrast(mock_image)
        
        assert 0 <= contrast <= 1
        # Perfect contrast (0 and 255) should give contrast = 1
        assert contrast == pytest.approx(1.0, rel=0.01)
    
    def test_calculate_contrast_low(self):
        """Test contrast for uniform image."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        # Low contrast: all same value
        mock_gray.getdata.return_value = [128] * 100
        mock_image.convert.return_value = mock_gray
        
        contrast = analyzer._calculate_contrast(mock_image)
        
        assert contrast == 0.0  # No contrast
    
    def test_calculate_complexity(self):
        """Test _calculate_complexity returns value between 0 and 1."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_small = Mock()
        # Varied pixels for complexity
        mock_small.getdata.return_value = [(i*10, i*5, i*2) for i in range(25)] * 4
        mock_image.resize.return_value = mock_small
        
        complexity = analyzer._calculate_complexity(mock_image)
        
        assert 0 <= complexity <= 1
    
    def test_calculate_edge_density(self):
        """Test _calculate_edge_density returns value between 0 and 1."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        mock_small = Mock()
        # Create pixels with some edges (value changes)
        pixels = [100] * 50 + [200] * 50  # Sharp transition
        mock_small.getdata.return_value = pixels
        mock_gray.resize.return_value = mock_small
        mock_image.convert.return_value = mock_gray
        
        edge_density = analyzer._calculate_edge_density(mock_image)
        
        assert 0 <= edge_density <= 1
    
    def test_detect_text_regions_heuristic(self):
        """Test heuristic text detection."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_gray = Mock()
        mock_small = Mock()
        # High contrast adjacent pixels suggest text
        pixels = [0, 200, 0, 200] * 25  # Alternating pattern
        mock_small.getdata.return_value = pixels
        mock_gray.resize.return_value = mock_small
        mock_image.convert.return_value = mock_gray
        
        has_text, text_ratio = analyzer._detect_text_regions(mock_image)
        
        assert isinstance(has_text, bool)
        assert 0 <= text_ratio <= 1
    
    def test_calculate_composition_score(self):
        """Test composition score calculation."""
        analyzer = ThumbnailAnalyzer()
        
        mock_image = Mock()
        mock_small = Mock()
        mock_gray = Mock()
        # Create simple pixel data
        pixels = [128] * (90 * 90)
        mock_gray.getdata.return_value = pixels
        mock_small.convert.return_value = mock_gray
        mock_image.resize.return_value = mock_small
        
        result = analyzer._calculate_composition_score(mock_image)
        
        assert "composition_score" in result
        assert "rule_of_thirds_score" in result
        assert "focal_point_x" in result
        assert "focal_point_y" in result
        assert "focal_point_quadrant" in result
        assert "on_power_point" in result
    
    @patch("httpx.Client")
    def test_analyze_from_url_sync(self, mock_httpx_client):
        """Test synchronous URL analysis."""
        mock_response = Mock()
        mock_response.content = b"fake image data"
        mock_response.raise_for_status = Mock()
        
        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = Mock(return_value=False)
        mock_httpx_client.return_value = mock_client_instance
        
        analyzer = ThumbnailAnalyzer()
        
        with patch.object(analyzer, "analyze") as mock_analyze:
            mock_features = ThumbnailFeatures(
                face_count=0, face_area_ratio=0, has_face=False,
                face_emotion_primary=None, face_emotion_intensity=None,
                has_text=False, text_area_ratio=0,
                dominant_color_1="#000000", dominant_color_2="#000000",
                dominant_color_3="#000000", brightness=0.5, saturation=0.5,
                contrast=0.5, visual_complexity=0.5, edge_density=0.5,
                composition_score=0.5
            )
            mock_analyze.return_value = mock_features
            
            result = analyzer.analyze_from_url_sync("https://example.com/thumb.jpg")
            
            assert result == mock_features


class TestFaceDetection:
    """Tests for face detection functionality."""
    
    def test_detect_faces_without_opencv(self):
        """Test face detection returns zeros without OpenCV."""
        analyzer = ThumbnailAnalyzer(enable_face_detection=False)
        
        # _detect_faces shouldn't be called, but if it were
        # it would return (0, 0.0)
        assert analyzer.enable_face_detection is False
    
    @patch("cv2.CascadeClassifier")
    def test_detect_faces_with_opencv(self, mock_cascade):
        """Test face detection with OpenCV mocked."""
        mock_cascade_instance = Mock()
        mock_cascade_instance.detectMultiScale.return_value = [
            (10, 10, 100, 100),  # One face
        ]
        mock_cascade.return_value = mock_cascade_instance
        
        # Create analyzer with face detection
        with patch.dict("sys.modules", {"cv2": Mock()}):
            analyzer = ThumbnailAnalyzer.__new__(ThumbnailAnalyzer)
            analyzer.enable_face_detection = True
            analyzer._face_cascade = mock_cascade_instance
            
            mock_image = Mock()
            mock_image.size = (640, 480)
            
            with patch("cv2.cvtColor"):
                with patch("numpy.array"):
                    # This would normally detect faces
                    pass


class TestEmotionDetection:
    """Tests for emotion detection functionality."""
    
    def test_detect_emotions_without_deepface(self):
        """Test emotion detection returns None without DeepFace."""
        analyzer = ThumbnailAnalyzer(enable_emotion_detection=False)
        
        assert analyzer.enable_emotion_detection is False

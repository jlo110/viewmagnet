"""Thumbnail feature extraction."""
import io
from dataclasses import dataclass
from typing import Optional, Tuple, List
from collections import Counter

import httpx
from PIL import Image
import structlog

logger = structlog.get_logger()


@dataclass
class ThumbnailFeatures:
    """Extracted features from a video thumbnail."""
    # Face detection
    face_count: int
    face_area_ratio: float
    has_face: bool
    
    # Face emotions (optional, requires DeepFace)
    face_emotion_primary: Optional[str]  # happy, sad, angry, surprise, fear, disgust, neutral
    face_emotion_intensity: Optional[float]  # 0-1
    
    # Text detection (OCR)
    has_text: bool
    text_area_ratio: float
    
    # Color analysis
    dominant_color_1: str  # Hex
    dominant_color_2: str
    dominant_color_3: str
    brightness: float  # 0-1
    saturation: float  # 0-1
    contrast: float  # 0-1
    
    # Composition
    visual_complexity: float  # 0-1
    edge_density: float  # 0-1
    composition_score: float  # 0-1 (rule of thirds adherence)
    
    # Fields with defaults (must come last)
    text_word_count: int = 0
    text_char_count: int = 0
    text_content: str = ""  # The actual text detected
    text_readability: float = 0.5  # Estimated readability 0-1
    
    # Enhanced composition (rule of thirds)
    rule_of_thirds_score: float = 0.0  # 0-1, how well focal point aligns
    focal_point_x: float = 0.5  # 0-1, normalized x position of focal point
    focal_point_y: float = 0.5  # 0-1, normalized y position
    focal_point_quadrant: str = "center"  # top-left, top-right, bottom-left, bottom-right, center
    on_power_point: bool = False  # True if focal point is near a rule-of-thirds intersection


class ThumbnailAnalyzer:
    """
    Extracts features from video thumbnails.
    
    Uses PIL for basic image analysis.
    Face detection is optional and requires opencv-python.
    Face emotion detection requires deepface library.
    """
    
    def __init__(
        self, 
        enable_face_detection: bool = False, 
        enable_emotion_detection: bool = False,
        enable_text_detection: bool = False,
    ):
        """
        Initialize analyzer.
        
        Args:
            enable_face_detection: Whether to use OpenCV for face detection
            enable_emotion_detection: Whether to use DeepFace for emotion detection
            enable_text_detection: Whether to use EasyOCR for text detection
        """
        self.enable_face_detection = enable_face_detection
        self.enable_emotion_detection = enable_emotion_detection
        self.enable_text_detection = enable_text_detection
        self._face_cascade = None
        self._deepface_available = False
        self._ocr_reader = None
        
        if enable_face_detection:
            try:
                import cv2
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
            except ImportError:
                logger.warning("opencv_not_available", msg="Face detection disabled")
                self.enable_face_detection = False
        
        if enable_emotion_detection:
            try:
                from deepface import DeepFace  # noqa: F401  (availability probe)
                self._deepface_available = True
            except ImportError:
                logger.warning("deepface_not_available", msg="Emotion detection disabled")
                self.enable_emotion_detection = False
        
        if enable_text_detection:
            try:
                import easyocr
                self._ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            except ImportError:
                logger.warning("easyocr_not_available", msg="Text detection disabled")
                self.enable_text_detection = False
    
    async def analyze_from_url(self, url: str) -> Optional[ThumbnailFeatures]:
        """
        Download and analyze a thumbnail from URL.
        
        Args:
            url: Thumbnail URL
            
        Returns:
            ThumbnailFeatures or None if download fails
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
                
                image_data = response.content
                return self.analyze(image_data)
                
        except Exception as e:
            logger.error("thumbnail_download_error", url=url, error=str(e))
            return None
    
    def analyze_from_url_sync(self, url: str) -> Optional[ThumbnailFeatures]:
        """
        Download and analyze a thumbnail from URL (synchronous).
        
        Args:
            url: Thumbnail URL
            
        Returns:
            ThumbnailFeatures or None if download fails
        """
        try:
            with httpx.Client() as client:
                response = client.get(url, timeout=10.0)
                response.raise_for_status()
                
                image_data = response.content
                return self.analyze(image_data)
                
        except Exception as e:
            logger.debug("thumbnail_download_error", url=url[:50], error=str(e))
            return None
    
    def analyze(self, image_data: bytes) -> ThumbnailFeatures:
        """
        Analyze thumbnail image data.
        
        Args:
            image_data: Raw image bytes
            
        Returns:
            ThumbnailFeatures with extracted features
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            image = image.convert("RGB")
        except Exception as e:
            logger.error("image_parse_error", error=str(e))
            return self._empty_features()
        
        # Get basic dimensions
        width, height = image.size
        total_pixels = width * height
        
        # Color analysis
        colors = self._get_dominant_colors(image)
        brightness = self._calculate_brightness(image)
        saturation = self._calculate_saturation(image)
        contrast = self._calculate_contrast(image)
        
        # Complexity analysis
        complexity = self._calculate_complexity(image)
        edge_density = self._calculate_edge_density(image)
        
        # Composition analysis (rule of thirds)
        composition = self._calculate_composition_score(image)
        
        # Face detection (if enabled)
        face_count = 0
        face_area_ratio = 0.0
        face_emotion_primary = None
        face_emotion_intensity = None
        
        if self.enable_face_detection and self._face_cascade is not None:
            face_count, face_area_ratio = self._detect_faces(image)
        
        # Face emotion detection (if enabled and faces found)
        if self.enable_emotion_detection and self._deepface_available and face_count > 0:
            face_emotion_primary, face_emotion_intensity = self._detect_face_emotions(image)
        
        # Text detection
        text_word_count = 0
        text_char_count = 0
        text_content = ""
        text_readability = 0.5
        
        if self.enable_text_detection and self._ocr_reader is not None:
            has_text, text_area_ratio, text_word_count, text_char_count, text_content, text_readability = self._detect_text_ocr(image)
        else:
            # Fallback to heuristic detection
            has_text, text_area_ratio = self._detect_text_regions(image)
        
        return ThumbnailFeatures(
            face_count=face_count,
            face_area_ratio=face_area_ratio,
            has_face=face_count > 0,
            face_emotion_primary=face_emotion_primary,
            face_emotion_intensity=face_emotion_intensity,
            has_text=has_text,
            text_area_ratio=text_area_ratio,
            text_word_count=text_word_count,
            text_char_count=text_char_count,
            text_content=text_content,
            text_readability=text_readability,
            dominant_color_1=colors[0] if len(colors) > 0 else "#000000",
            dominant_color_2=colors[1] if len(colors) > 1 else "#000000",
            dominant_color_3=colors[2] if len(colors) > 2 else "#000000",
            brightness=brightness,
            saturation=saturation,
            contrast=contrast,
            visual_complexity=complexity,
            edge_density=edge_density,
            composition_score=composition["composition_score"],
            rule_of_thirds_score=composition["rule_of_thirds_score"],
            focal_point_x=composition["focal_point_x"],
            focal_point_y=composition["focal_point_y"],
            focal_point_quadrant=composition["focal_point_quadrant"],
            on_power_point=composition["on_power_point"],
        )
    
    def _empty_features(self) -> ThumbnailFeatures:
        """Return empty features for failed analysis."""
        return ThumbnailFeatures(
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
            brightness=0.0,
            saturation=0.0,
            contrast=0.0,
            visual_complexity=0.0,
            edge_density=0.0,
            composition_score=0.0,
        )
    
    def _get_dominant_colors(self, image: Image.Image, num_colors: int = 3) -> List[str]:
        """Extract dominant colors from image."""
        # Resize for faster processing
        small = image.resize((100, 100))
        
        # Get all pixels
        pixels = list(small.getdata())
        
        # Quantize to reduce color space
        quantized = []
        for r, g, b in pixels:
            # Round to nearest 32
            qr = (r // 32) * 32
            qg = (g // 32) * 32
            qb = (b // 32) * 32
            quantized.append((qr, qg, qb))
        
        # Count and get most common
        counter = Counter(quantized)
        most_common = counter.most_common(num_colors)
        
        # Convert to hex
        colors = []
        for (r, g, b), _ in most_common:
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            colors.append(hex_color)
        
        return colors
    
    def _calculate_brightness(self, image: Image.Image) -> float:
        """Calculate average brightness (0-1)."""
        grayscale = image.convert("L")
        pixels = list(grayscale.getdata())
        avg = sum(pixels) / len(pixels)
        return avg / 255.0
    
    def _calculate_saturation(self, image: Image.Image) -> float:
        """Calculate average saturation (0-1)."""
        hsv = image.convert("HSV")
        pixels = list(hsv.getdata())
        
        # S is second channel in HSV
        saturations = [p[1] for p in pixels]
        avg = sum(saturations) / len(saturations)
        return avg / 255.0
    
    def _calculate_contrast(self, image: Image.Image) -> float:
        """Calculate contrast level (0-1)."""
        grayscale = image.convert("L")
        pixels = list(grayscale.getdata())
        
        if not pixels:
            return 0.0
        
        min_val = min(pixels)
        max_val = max(pixels)
        
        # Michelson contrast
        if max_val + min_val == 0:
            return 0.0
        
        return (max_val - min_val) / (max_val + min_val)
    
    def _calculate_complexity(self, image: Image.Image) -> float:
        """
        Calculate visual complexity based on color variance.
        Higher complexity = more varied colors.
        """
        small = image.resize((50, 50))
        pixels = list(small.getdata())
        
        if len(pixels) < 2:
            return 0.0
        
        # Calculate variance of each channel
        r_vals = [p[0] for p in pixels]
        g_vals = [p[1] for p in pixels]
        b_vals = [p[2] for p in pixels]
        
        def variance(values):
            mean = sum(values) / len(values)
            return sum((x - mean) ** 2 for x in values) / len(values)
        
        avg_variance = (variance(r_vals) + variance(g_vals) + variance(b_vals)) / 3
        
        # Normalize (max variance is 127.5^2 = 16256.25)
        return min(1.0, avg_variance / 16256.25 * 4)  # Scale for reasonable range
    
    def _calculate_edge_density(self, image: Image.Image) -> float:
        """
        Calculate edge density using simple gradient.
        More edges = higher density.
        """
        grayscale = image.convert("L")
        small = grayscale.resize((100, 100))
        pixels = list(small.getdata())
        width = 100
        
        edge_count = 0
        total = 0
        
        for i, pixel in enumerate(pixels):
            # Check horizontal neighbor
            if (i + 1) % width != 0 and i + 1 < len(pixels):
                diff = abs(pixel - pixels[i + 1])
                if diff > 30:  # Threshold for edge
                    edge_count += 1
                total += 1
            
            # Check vertical neighbor
            if i + width < len(pixels):
                diff = abs(pixel - pixels[i + width])
                if diff > 30:
                    edge_count += 1
                total += 1
        
        if total == 0:
            return 0.0
        
        return edge_count / total
    
    def _detect_faces(self, image: Image.Image) -> Tuple[int, float]:
        """Detect faces using OpenCV."""
        try:
            import cv2
            import numpy as np
            
            # Convert PIL to OpenCV format
            img_array = np.array(image)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # Detect faces
            faces = self._face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            
            face_count = len(faces)
            
            # Calculate total face area ratio
            total_area = image.size[0] * image.size[1]
            face_area = sum(int(w) * int(h) for (x, y, w, h) in faces)
            face_ratio = float(face_area / total_area) if total_area > 0 else 0.0
            
            return int(face_count), float(face_ratio)
            
        except Exception as e:
            logger.debug("face_detection_error", error=str(e))
            return 0, 0.0
    
    def _detect_text_regions(self, image: Image.Image) -> Tuple[bool, float]:
        """
        Heuristic text detection based on high contrast regions.
        
        This is a simple approximation - real text detection would need OCR.
        """
        # Convert to grayscale
        gray = image.convert("L")
        small = gray.resize((100, 100))
        pixels = list(small.getdata())
        width = 100
        
        # Count high contrast adjacent pixels (potential text)
        text_pixels = 0
        
        for i, pixel in enumerate(pixels):
            if (i + 1) % width != 0 and i + 1 < len(pixels):
                diff = abs(pixel - pixels[i + 1])
                if diff > 100:  # High contrast threshold
                    text_pixels += 1
        
        text_ratio = text_pixels / len(pixels)
        
        # Consider text present if ratio is above threshold
        has_text = text_ratio > 0.05
        
        return has_text, text_ratio
    
    def _detect_text_ocr(self, image: Image.Image) -> Tuple[bool, float, int, int, str, float]:
        """
        Detect text in thumbnail using OCR.
        
        Returns:
            Tuple of (has_text, text_area_ratio, word_count, char_count, text_content, readability)
        """
        import numpy as np
        
        try:
            # Convert PIL to numpy array for easyocr
            img_array = np.array(image)
            
            # Run OCR
            results = self._ocr_reader.readtext(img_array)
            
            if not results:
                return False, 0.0, 0, 0, "", 0.5
            
            # Extract text and calculate metrics
            all_text = []
            total_text_area = 0
            img_area = image.width * image.height
            
            for (bbox, text, confidence) in results:
                if confidence > 0.3:  # Filter low confidence
                    all_text.append(text)
                    # Calculate bounding box area
                    x_coords = [p[0] for p in bbox]
                    y_coords = [p[1] for p in bbox]
                    box_width = max(x_coords) - min(x_coords)
                    box_height = max(y_coords) - min(y_coords)
                    total_text_area += box_width * box_height
            
            if not all_text:
                return False, 0.0, 0, 0, "", 0.5
            
            text_content = " ".join(all_text)
            word_count = len(text_content.split())
            char_count = len(text_content.replace(" ", ""))
            text_area_ratio = total_text_area / img_area if img_area > 0 else 0
            
            # Calculate readability score
            # Based on: text size (larger = more readable), contrast, word count
            # Higher ratio = larger text = more readable
            # Optimal word count for thumbnails: 2-5 words
            readability = min(1.0, text_area_ratio * 5)  # Scale up
            if word_count > 7:
                readability *= 0.7  # Penalty for too many words
            
            return True, text_area_ratio, word_count, char_count, text_content, readability
            
        except Exception as e:
            logger.debug("ocr_error", error=str(e))
            return False, 0.0, 0, 0, "", 0.5
    
    def _calculate_composition_score(self, image: Image.Image) -> dict:
        """
        Calculate composition score based on rule of thirds.
        
        Returns dict with:
        - composition_score: 0-1 overall score
        - rule_of_thirds_score: 0-1 adherence to rule of thirds
        - focal_point_x: 0-1 normalized x position
        - focal_point_y: 0-1 normalized y position
        - focal_point_quadrant: which quadrant focal point is in
        - on_power_point: True if focal point near thirds intersection
        """
        default = {
            "composition_score": 0.5,
            "rule_of_thirds_score": 0.0,
            "focal_point_x": 0.5,
            "focal_point_y": 0.5,
            "focal_point_quadrant": "center",
            "on_power_point": False,
        }
        
        try:
            # Resize for consistent analysis
            small = image.resize((90, 90))  # Divisible by 3
            gray = small.convert("L")
            pixels = list(gray.getdata())
            width, height = 90, 90
            
            # Calculate gradient magnitude as a proxy for visual interest
            interest_map = []
            for y in range(height):
                for x in range(width):
                    idx = y * width + x
                    gradient = 0
                    if x + 1 < width:
                        gradient += abs(pixels[idx] - pixels[idx + 1])
                    if y + 1 < height:
                        gradient += abs(pixels[idx] - pixels[idx + width])
                    interest_map.append(gradient)
            
            total_interest = sum(interest_map)
            if total_interest == 0:
                return default
            
            # Find focal point (point of highest interest)
            max_interest = 0
            focal_x, focal_y = width // 2, height // 2
            
            # Use 5x5 window to find focal point
            for cy in range(2, height - 2):
                for cx in range(2, width - 2):
                    window_interest = 0
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            window_interest += interest_map[(cy + dy) * width + (cx + dx)]
                    if window_interest > max_interest:
                        max_interest = window_interest
                        focal_x, focal_y = cx, cy
            
            # Normalize focal point to 0-1
            focal_x_norm = focal_x / width
            focal_y_norm = focal_y / height
            
            # Determine quadrant
            if focal_x_norm < 0.33:
                quadrant_x = "left"
            elif focal_x_norm > 0.66:
                quadrant_x = "right"
            else:
                quadrant_x = ""
            
            if focal_y_norm < 0.33:
                quadrant_y = "top"
            elif focal_y_norm > 0.66:
                quadrant_y = "bottom"
            else:
                quadrant_y = ""
            
            if quadrant_x and quadrant_y:
                quadrant = f"{quadrant_y}-{quadrant_x}"
            elif quadrant_x:
                quadrant = quadrant_x
            elif quadrant_y:
                quadrant = quadrant_y
            else:
                quadrant = "center"
            
            # Rule of thirds intersection points
            thirds_x = [width // 3, 2 * width // 3]
            thirds_y = [height // 3, 2 * height // 3]
            power_points = [(tx, ty) for tx in thirds_x for ty in thirds_y]
            
            # Check if focal point is near a power point
            on_power_point = False
            min_dist = float('inf')
            for px, py in power_points:
                dist = ((focal_x - px) ** 2 + (focal_y - py) ** 2) ** 0.5
                min_dist = min(min_dist, dist)
                if dist < 8:  # Within ~10% of image
                    on_power_point = True
                    break
            
            # Calculate rule of thirds score based on distance to nearest power point
            max_dist = ((width/2) ** 2 + (height/2) ** 2) ** 0.5
            rule_of_thirds_score = max(0, 1 - (min_dist / (max_dist / 2)))
            
            # Calculate overall composition score (interest near thirds)
            thirds_interest = 0
            for tx in thirds_x:
                for ty in thirds_y:
                    for dx in range(-2, 3):
                        for dy in range(-2, 3):
                            x, y = tx + dx, ty + dy
                            if 0 <= x < width and 0 <= y < height:
                                thirds_interest += interest_map[y * width + x]
            
            thirds_ratio = thirds_interest / total_interest
            composition_score = min(1.0, thirds_ratio * 3)
            
            return {
                "composition_score": composition_score,
                "rule_of_thirds_score": rule_of_thirds_score,
                "focal_point_x": focal_x_norm,
                "focal_point_y": focal_y_norm,
                "focal_point_quadrant": quadrant,
                "on_power_point": on_power_point,
            }
            
        except Exception as e:
            logger.debug("composition_score_error", error=str(e))
            return default
    
    def _detect_face_emotions(self, image: Image.Image) -> Tuple[Optional[str], Optional[float]]:
        """
        Detect emotions in faces using DeepFace.
        
        Returns the dominant emotion and its intensity.
        """
        try:
            from deepface import DeepFace
            import numpy as np
            
            # Convert PIL to numpy array
            img_array = np.array(image)
            
            # Analyze with DeepFace (enforce_detection=False to avoid errors)
            result = DeepFace.analyze(
                img_array,
                actions=['emotion'],
                enforce_detection=False,
                silent=True
            )
            
            # Handle both single and multiple face results
            if isinstance(result, list):
                if not result:
                    return None, None
                result = result[0]
            
            emotions = result.get('emotion', {})
            if not emotions:
                return None, None
            
            # Find dominant emotion
            dominant_emotion = max(emotions, key=emotions.get)
            intensity = float(emotions[dominant_emotion]) / 100.0  # Convert to 0-1, ensure native float
            
            return str(dominant_emotion), float(intensity)
            
        except Exception as e:
            logger.debug("emotion_detection_error", error=str(e))
            return None, None


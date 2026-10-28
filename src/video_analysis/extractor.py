"""Extract features from video content for ML model."""

import os
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List
import logging
import cv2
import librosa

logger = logging.getLogger(__name__)


@dataclass
class VideoContentFeatures:
    """Features extracted from video content."""
    
    # Hook quality (first 10 seconds)
    hook_face_appears_seconds: Optional[float] = None  # When does a face first appear
    hook_text_appears_seconds: Optional[float] = None  # When does text overlay appear
    hook_scene_changes_count: int = 0  # Number of cuts in first 10s
    hook_avg_motion: float = 0.0  # Average motion/action level
    
    # Visual pacing
    total_scene_changes: int = 0  # Total cuts in video
    avg_scene_duration: float = 0.0  # Average time between cuts
    scene_change_variance: float = 0.0  # Consistency of pacing
    
    # Scene variety analysis (NEW)
    scene_variety_score: float = 0.0  # 0-1, visual diversity across scenes
    unique_scene_types: int = 0  # Estimated distinct scene types
    scene_color_diversity: float = 0.0  # How much color varies between scenes
    scene_brightness_diversity: float = 0.0  # How much brightness varies
    has_b_roll: bool = False  # Likely has B-roll/cutaway footage
    
    # Visual quality
    avg_brightness: float = 0.5
    brightness_variance: float = 0.0  # Dynamic lighting changes
    avg_sharpness: float = 0.5
    color_variety: float = 0.0  # How many different colors used
    
    # Face presence throughout
    face_screen_time_ratio: float = 0.0  # % of time a face is visible
    face_size_consistency: float = 0.0  # How consistent is face framing
    
    # Audio features
    audio_energy_mean: float = 0.0
    audio_energy_variance: float = 0.0
    speech_ratio: float = 0.0  # % of audio that's speech vs music/silence
    audio_tempo: float = 0.0  # BPM if music present
    loudness_range: float = 0.0  # Dynamic range
    
    # Content pacing
    intro_duration_seconds: float = 0.0  # Estimated intro length
    has_music_intro: bool = False
    energy_ramp_up: float = 0.0  # Does energy increase over time
    
    # Energy arc analysis (NEW)
    energy_arc_shape: str = "flat"  # flat, rising, falling, peak_early, peak_late, valley
    energy_arc_segments: List[float] = field(default_factory=list)  # 10 normalized energy values
    energy_intro_level: float = 0.0  # Energy in first 10%
    energy_middle_level: float = 0.0  # Energy in middle
    energy_outro_level: float = 0.0  # Energy in last 10%
    energy_max_position: float = 0.0  # Where max energy occurs (0-1)
    
    # Transcript features (from Whisper)
    word_count: int = 0
    words_per_minute: float = 0.0
    question_count: int = 0  # How many questions asked
    call_to_action_count: int = 0  # "subscribe", "like", "comment"
    hook_words_in_first_10s: int = 0  # Engaging words early
    transcript_sentiment: float = 0.0  # Overall sentiment
    
    # Raw data for advanced analysis
    transcript: str = ""
    scene_timestamps: List[float] = field(default_factory=list)


class VideoFeatureExtractor:
    """Extract ML features from video content."""
    
    def __init__(self, use_whisper: bool = True, whisper_model: str = "base"):
        """
        Initialize extractor.
        
        Args:
            use_whisper: Whether to use Whisper for transcription
            whisper_model: Whisper model size (tiny, base, small, medium, large)
        """
        self.use_whisper = use_whisper
        self.whisper_model_name = whisper_model
        self._whisper_model = None
        
        # Load face detector
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
    
    @property
    def whisper_model(self):
        """Lazy load Whisper model - using CPU for stability (MPS causes NaN errors)."""
        if self._whisper_model is None and self.use_whisper:
            try:
                import whisper
                import torch
                
                # Force CPU - MPS causes NaN errors with Whisper on Apple Silicon
                # See: https://github.com/openai/whisper/issues/1399
                if torch.cuda.is_available():
                    device = "cuda"
                else:
                    device = "cpu"  # Skip MPS - causes NaN tensor errors
                
                logger.info(f"Loading Whisper model: {self.whisper_model_name} on {device}")
                self._whisper_model = whisper.load_model(self.whisper_model_name, device=device)
            except Exception as e:
                logger.error(f"Failed to load Whisper: {e}")
                self.use_whisper = False
        return self._whisper_model
    
    def extract(self, video_path: str, audio_path: Optional[str] = None) -> VideoContentFeatures:
        """
        Extract all features from a video.
        
        Args:
            video_path: Path to video file
            audio_path: Path to audio file (optional, extracted from video if not provided)
            
        Returns:
            VideoContentFeatures with all extracted features
        """
        features = VideoContentFeatures()
        
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return features
        
        # Extract visual features
        self._extract_visual_features(video_path, features)
        
        # Extract audio features
        if audio_path and os.path.exists(audio_path):
            self._extract_audio_features(audio_path, features)
        
        # Extract transcript features
        if self.use_whisper and audio_path and os.path.exists(audio_path):
            self._extract_transcript_features(audio_path, features)
        
        return features
    
    def _extract_visual_features(self, video_path: str, features: VideoContentFeatures):
        """Extract visual features from video frames."""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error("Failed to open video")
                return
            
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            # Sample frames (every 0.5 seconds)
            sample_interval = int(fps * 0.5)
            if sample_interval < 1:
                sample_interval = 1
            
            prev_frame = None
            scene_changes = []
            brightness_values = []
            sharpness_values = []
            face_frames = 0
            total_sampled = 0
            face_sizes = []
            motion_values = []
            
            frame_idx = 0
            first_face_time = None
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                current_time = frame_idx / fps
                
                if frame_idx % sample_interval == 0:
                    total_sampled += 1
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    
                    # Brightness
                    brightness = np.mean(gray) / 255.0
                    brightness_values.append(brightness)
                    
                    # Sharpness (Laplacian variance)
                    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var() / 1000
                    sharpness_values.append(min(sharpness, 1.0))
                    
                    # Face detection
                    faces = self.face_cascade.detectMultiScale(gray, 1.1, 4)
                    if len(faces) > 0:
                        face_frames += 1
                        if first_face_time is None:
                            first_face_time = current_time
                        # Track face size
                        for (x, y, w, h) in faces:
                            face_sizes.append(w * h / (frame.shape[0] * frame.shape[1]))
                    
                    # Scene change detection (frame difference)
                    if prev_frame is not None:
                        diff = cv2.absdiff(gray, prev_frame)
                        motion = np.mean(diff) / 255.0
                        motion_values.append(motion)
                        
                        # Scene change threshold
                        if motion > 0.15:
                            scene_changes.append(current_time)
                    
                    prev_frame = gray.copy()
                
                frame_idx += 1
            
            cap.release()
            
            # Calculate features
            if total_sampled > 0:
                features.face_screen_time_ratio = face_frames / total_sampled
                features.avg_brightness = np.mean(brightness_values)
                features.brightness_variance = np.var(brightness_values)
                features.avg_sharpness = np.mean(sharpness_values)
            
            if face_sizes:
                features.face_size_consistency = 1.0 - min(np.std(face_sizes) / (np.mean(face_sizes) + 0.01), 1.0)
            
            features.hook_face_appears_seconds = first_face_time
            features.total_scene_changes = len(scene_changes)
            features.scene_timestamps = scene_changes
            
            if scene_changes:
                # Scene changes in first 10 seconds
                features.hook_scene_changes_count = sum(1 for t in scene_changes if t <= 10)
                
                # Average scene duration
                if len(scene_changes) > 1:
                    durations = np.diff([0] + scene_changes + [duration])
                    features.avg_scene_duration = np.mean(durations)
                    features.scene_change_variance = np.var(durations)
            
            if motion_values:
                features.hook_avg_motion = np.mean(motion_values[:20]) if len(motion_values) >= 20 else np.mean(motion_values)
            
            # Scene variety analysis
            features.scene_brightness_diversity = np.std(brightness_values) if brightness_values else 0
            
            # Estimate scene variety from motion patterns
            if len(scene_changes) >= 2 and motion_values:
                # Divide video into segments at scene changes
                segment_brightnesses = []
                current_segment = []
                scene_idx = 0
                
                for i, brightness in enumerate(brightness_values):
                    current_segment.append(brightness)
                    # Check if we've passed a scene change
                    frame_time = i * 0.5  # Sampled every 0.5s
                    if scene_idx < len(scene_changes) and frame_time >= scene_changes[scene_idx]:
                        if current_segment:
                            segment_brightnesses.append(np.mean(current_segment))
                        current_segment = []
                        scene_idx += 1
                
                if current_segment:
                    segment_brightnesses.append(np.mean(current_segment))
                
                # Scene color diversity: variation between segments
                if len(segment_brightnesses) >= 3:
                    features.scene_color_diversity = np.std(segment_brightnesses)
                    
                    # Unique scene types: count distinct brightness levels
                    # Quantize brightness into 5 levels
                    quantized = [int(b * 5) for b in segment_brightnesses]
                    features.unique_scene_types = len(set(quantized))
                
                # Scene variety score: combines color diversity, scene count, and motion variance
                motion_variety = np.std(motion_values) if motion_values else 0
                features.scene_variety_score = min(1.0, (
                    features.scene_color_diversity * 2 +  # Weight color diversity
                    min(len(scene_changes) / 20, 1.0) * 0.3 +  # Scene change count
                    motion_variety * 2  # Motion variety
                ))
                
                # Detect B-roll: if there are scenes with very different characteristics
                # B-roll typically has different brightness/motion than talking head
                if features.unique_scene_types >= 3 and features.scene_color_diversity > 0.1:
                    features.has_b_roll = True
            
            logger.info(f"Visual features extracted: {total_sampled} frames sampled, "
                       f"{len(scene_changes)} scene changes, {features.face_screen_time_ratio:.1%} face time, "
                       f"variety={features.scene_variety_score:.2f}")
            
        except Exception as e:
            logger.error(f"Error extracting visual features: {e}")
    
    def _extract_audio_features(self, audio_path: str, features: VideoContentFeatures):
        """Extract audio features using librosa."""
        try:
            # Load audio
            y, sr = librosa.load(audio_path, sr=22050, duration=60)
            
            if len(y) == 0:
                return
            
            # Energy (RMS)
            rms = librosa.feature.rms(y=y)[0]
            features.audio_energy_mean = float(np.mean(rms))
            features.audio_energy_variance = float(np.var(rms))
            features.loudness_range = float(np.max(rms) - np.min(rms))
            
            # Check if energy increases over time
            if len(rms) > 10:
                first_half = np.mean(rms[:len(rms)//2])
                second_half = np.mean(rms[len(rms)//2:])
                features.energy_ramp_up = float(second_half - first_half)
            
            # Energy arc analysis - divide into 10 segments
            if len(rms) >= 10:
                segment_size = len(rms) // 10
                energy_segments = []
                for i in range(10):
                    start = i * segment_size
                    end = start + segment_size if i < 9 else len(rms)
                    segment_energy = float(np.mean(rms[start:end]))
                    energy_segments.append(segment_energy)
                
                # Normalize to 0-1
                max_energy = max(energy_segments) if max(energy_segments) > 0 else 1
                features.energy_arc_segments = [e / max_energy for e in energy_segments]
                
                # Calculate intro/middle/outro levels
                features.energy_intro_level = float(np.mean(features.energy_arc_segments[:2]))
                features.energy_middle_level = float(np.mean(features.energy_arc_segments[3:7]))
                features.energy_outro_level = float(np.mean(features.energy_arc_segments[-2:]))
                
                # Find max energy position
                max_idx = energy_segments.index(max(energy_segments))
                features.energy_max_position = max_idx / 10.0
                
                # Classify energy arc shape
                features.energy_arc_shape = self._classify_energy_arc(features.energy_arc_segments)
            
            # Tempo
            try:
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                features.audio_tempo = float(tempo) if not np.isnan(tempo) else 0.0
            except:
                features.audio_tempo = 0.0
            
            # Check for music in intro (first 10 seconds)
            intro_y = y[:sr*10] if len(y) > sr*10 else y
            intro_rms = librosa.feature.rms(y=intro_y)[0]
            # If intro has consistent energy, might be music
            features.has_music_intro = np.std(intro_rms) < 0.05 and np.mean(intro_rms) > 0.02
            
            # Estimate intro duration (when speech starts)
            # Simple heuristic: look for energy variance increase
            window_size = int(sr * 2)  # 2 second windows
            for i in range(0, min(len(y), sr * 15), window_size):
                window = y[i:i+window_size]
                if len(window) > 0:
                    var = np.var(window)
                    if var > 0.01:  # Speech detected
                        features.intro_duration_seconds = i / sr
                        break
            
            logger.info(f"Audio features extracted: energy={features.audio_energy_mean:.3f}, "
                       f"tempo={features.audio_tempo:.0f} BPM, arc={features.energy_arc_shape}")
            
        except Exception as e:
            logger.error(f"Error extracting audio features: {e}")
    
    def _classify_energy_arc(self, segments: List[float]) -> str:
        """
        Classify the energy arc shape from normalized segments.
        
        Returns one of: flat, rising, falling, peak_early, peak_late, valley, variable
        """
        if len(segments) < 5:
            return "flat"
        
        # Calculate trends
        first_third = np.mean(segments[:3])
        middle_third = np.mean(segments[3:7])
        last_third = np.mean(segments[7:])
        
        max_idx = segments.index(max(segments))
        min_idx = segments.index(min(segments))
        
        variance = np.var(segments)
        
        # Flat: low variance
        if variance < 0.02:
            return "flat"
        
        # Rising: steady increase
        if last_third > first_third * 1.3 and last_third > middle_third:
            return "rising"
        
        # Falling: steady decrease
        if first_third > last_third * 1.3 and first_third > middle_third:
            return "falling"
        
        # Peak early: max in first 30%
        if max_idx <= 2 and middle_third < first_third and last_third < first_third:
            return "peak_early"
        
        # Peak late: max in last 30%
        if max_idx >= 7 and middle_third < last_third and first_third < last_third:
            return "peak_late"
        
        # Valley: dip in middle
        if middle_third < first_third * 0.7 and middle_third < last_third * 0.7:
            return "valley"
        
        # Peak in middle
        if middle_third > first_third and middle_third > last_third:
            return "peak_middle"
        
        # High variance but no clear pattern
        return "variable"
    
    def _extract_transcript_features(self, audio_path: str, features: VideoContentFeatures):
        """Extract features from speech transcript using Whisper."""
        try:
            if self.whisper_model is None:
                return
            
            # Transcribe
            result = self.whisper_model.transcribe(audio_path, language="en")
            transcript = result.get("text", "")
            segments = result.get("segments", [])
            
            features.transcript = transcript
            
            # Word count
            words = transcript.split()
            features.word_count = len(words)
            
            # Words per minute
            duration = segments[-1]["end"] if segments else 60
            features.words_per_minute = (len(words) / duration) * 60 if duration > 0 else 0
            
            # Questions (engagement)
            features.question_count = transcript.count("?")
            
            # Call to action detection
            cta_phrases = ["subscribe", "like", "comment", "share", "click", "link", "check out", 
                          "let me know", "tell me", "below", "notification"]
            transcript_lower = transcript.lower()
            features.call_to_action_count = sum(1 for phrase in cta_phrases if phrase in transcript_lower)
            
            # Words in first 10 seconds
            first_10s_words = []
            for seg in segments:
                if seg["start"] < 10:
                    first_10s_words.extend(seg["text"].split())
                else:
                    break
            
            # Hook words detection
            hook_words = ["you", "secret", "revealed", "shocking", "amazing", "never", "best", 
                         "worst", "how", "why", "what", "discover", "learn", "mistake", "truth"]
            features.hook_words_in_first_10s = sum(1 for w in first_10s_words if w.lower() in hook_words)
            
            # Simple sentiment (positive vs negative words)
            positive_words = ["great", "amazing", "awesome", "love", "perfect", "best", "excellent", 
                            "wonderful", "fantastic", "good", "happy", "excited"]
            negative_words = ["bad", "worst", "terrible", "hate", "awful", "horrible", "wrong", 
                            "problem", "issue", "mistake", "fail", "never"]
            
            pos_count = sum(1 for w in words if w.lower() in positive_words)
            neg_count = sum(1 for w in words if w.lower() in negative_words)
            total_sentiment_words = pos_count + neg_count
            if total_sentiment_words > 0:
                features.transcript_sentiment = (pos_count - neg_count) / total_sentiment_words
            
            logger.info(f"Transcript features: {len(words)} words, {features.words_per_minute:.0f} WPM, "
                       f"{features.question_count} questions")
            
        except Exception as e:
            logger.error(f"Error extracting transcript: {e}")
    
    def get_feature_vector(self, features: VideoContentFeatures) -> List[float]:
        """Convert features to a vector for ML model."""
        return [
            # Hook features
            features.hook_face_appears_seconds or 999,  # 999 if no face
            features.hook_scene_changes_count,
            features.hook_avg_motion,
            features.hook_words_in_first_10s,
            
            # Pacing features
            features.total_scene_changes,
            features.avg_scene_duration,
            features.scene_change_variance,
            
            # Visual features
            features.avg_brightness,
            features.brightness_variance,
            features.avg_sharpness,
            features.face_screen_time_ratio,
            features.face_size_consistency,
            
            # Audio features
            features.audio_energy_mean,
            features.audio_energy_variance,
            features.audio_tempo / 200,  # Normalize
            features.loudness_range,
            features.energy_ramp_up,
            1 if features.has_music_intro else 0,
            features.intro_duration_seconds,
            
            # Transcript features
            features.word_count / 100,  # Normalize
            features.words_per_minute / 200,  # Normalize
            features.question_count,
            features.call_to_action_count,
            features.transcript_sentiment,
        ]
    
    @staticmethod
    def get_feature_names() -> List[str]:
        """Get names for each feature in the vector."""
        return [
            "hook_face_time", "hook_scene_cuts", "hook_motion", "hook_words",
            "total_cuts", "avg_scene_duration", "pacing_variance",
            "brightness", "brightness_var", "sharpness", "face_time", "face_consistency",
            "audio_energy", "audio_variance", "tempo", "loudness_range", "energy_ramp",
            "has_music_intro", "intro_duration",
            "word_count", "wpm", "questions", "cta_count", "sentiment"
        ]


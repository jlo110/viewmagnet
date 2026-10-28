"""
Loop Designer - Engineer the Perfect Loop

Based on Chris Girbu's framework: short-form videos that loop seamlessly back to
the hook get massive replay credit from the algorithm. A "perfect loop" combines:
- Text continuity: the ending sentence flows back into the opening
- Visual continuity: the last frame matches the first frame
- Audio continuity: no sudden silence/volume drop at the end
- No "stop signals": phrases like "thanks for watching" tell viewers to leave

This module analyzes existing videos for loop quality and generates better endings.
"""

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger()


# Phrases that explicitly tell viewers to stop watching (loop killers)
STOP_SIGNAL_PATTERNS = [
    r"\bthanks?\s+for\s+watching\b",
    r"\bsee\s+you\s+(in\s+)?(the\s+)?next\s+(one|video|time)\b",
    r"\bbye\b",
    r"\bgoodbye\b",
    r"\bpeace\s+out\b",
    r"\bthat'?s\s+(it|all)\s+for\s+(today|now|this\s+video)\b",
    r"\bcatch\s+you\s+later\b",
    r"\bsubscribe\s+(for\s+more|and\s+i'?ll\s+see\s+you)\b",
    r"\bend\s+of\s+(the\s+)?video\b",
    r"\boutro\b",
]


@dataclass
class LoopAnalysis:
    """Complete loop quality analysis."""
    overall_score: float                   # 0-100
    text_score: float                      # 0-100: end-text -> start-text similarity
    visual_score: float                    # 0-100: last-frame -> first-frame similarity
    audio_score: float                     # 0-100: audio continuity at boundary
    
    has_stop_signals: bool
    stop_signals_found: List[str] = field(default_factory=list)
    
    first_words: str = ""
    last_words: str = ""
    
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    # Diagnostic metadata
    text_method: str = "none"              # "embedding", "lexical", "none"
    visual_method: str = "none"            # "ssim", "histogram", "none"
    audio_method: str = "none"             # "rms", "none"
    
    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 1),
            "text_score": round(self.text_score, 1),
            "visual_score": round(self.visual_score, 1),
            "audio_score": round(self.audio_score, 1),
            "has_stop_signals": self.has_stop_signals,
            "stop_signals_found": self.stop_signals_found,
            "first_words": self.first_words,
            "last_words": self.last_words,
            "issues": self.issues,
            "recommendations": self.recommendations,
            "text_method": self.text_method,
            "visual_method": self.visual_method,
            "audio_method": self.audio_method,
        }


def detect_stop_signals(text: str) -> Tuple[bool, List[str]]:
    """Detect 'thanks for watching' style phrases that tell viewers to leave."""
    if not text:
        return False, []
    text_lower = text.lower()
    found: List[str] = []
    for pattern in STOP_SIGNAL_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            found.append(match.group(0))
    return len(found) > 0, found


def get_first_words(text: str, n: int = 12) -> str:
    """Extract the first N words of a transcript."""
    if not text:
        return ""
    words = text.strip().split()
    return " ".join(words[:n])


def get_last_words(text: str, n: int = 12) -> str:
    """Extract the last N words of a transcript."""
    if not text:
        return ""
    words = text.strip().split()
    return " ".join(words[-n:]) if len(words) >= n else " ".join(words)


def text_similarity_lexical(a: str, b: str) -> float:
    """
    Lightweight lexical similarity (0-100). Returns the Jaccard similarity of
    word sets, scaled. Used as a fallback when sentence-transformers isn't available.
    """
    if not a or not b:
        return 0.0
    a_set = set(re.findall(r"\b\w+\b", a.lower())) - {"the", "a", "an", "is", "are", "to", "of"}
    b_set = set(re.findall(r"\b\w+\b", b.lower())) - {"the", "a", "an", "is", "are", "to", "of"}
    if not a_set or not b_set:
        return 0.0
    intersection = len(a_set & b_set)
    union = len(a_set | b_set)
    return (intersection / union) * 100 if union > 0 else 0.0


def text_similarity_embedding(a: str, b: str) -> Optional[float]:
    """
    Semantic similarity (0-100) using sentence-transformers cosine sim.
    Returns None if the package isn't available.
    """
    try:
        from sentence_transformers import SentenceTransformer, util  # noqa: F401  (availability probe)
        model = _get_sentence_transformer()
        if model is None:
            return None
        embeddings = model.encode([a, b], convert_to_tensor=True)
        cos_sim = util.cos_sim(embeddings[0], embeddings[1]).item()
        # Map -1..1 to 0..100, clamping (negative = unrelated)
        return max(0.0, min(100.0, (cos_sim + 1.0) / 2.0 * 100))
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"Embedding similarity failed: {e}")
        return None


_st_model = None
def _get_sentence_transformer():
    """Lazy-load and cache sentence transformer."""
    global _st_model
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning(f"Failed to load sentence transformer: {e}")
            _st_model = None
    return _st_model


def extract_frame_at(video_path: str, timestamp: float, output_path: str) -> bool:
    """Extract a single frame at `timestamp` (seconds) using ffmpeg."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{timestamp:.2f}",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0 and os.path.exists(output_path)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_video_duration(video_path: str) -> Optional[float]:
    """Get video duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


def visual_similarity_ssim(first_frame: str, last_frame: str) -> Optional[float]:
    """
    Compute SSIM between two image files via ffmpeg. Returns 0-100.
    Returns None if not available.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", first_frame,
            "-i", last_frame,
            "-lavfi", "ssim=stats_file=-",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # Parse "All:0.987..." from stderr
        match = re.search(r"All:\s*([\d.]+)", result.stderr)
        if match:
            return float(match.group(1)) * 100
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def visual_similarity_histogram(first_frame: str, last_frame: str) -> Optional[float]:
    """
    Compute color histogram similarity between two frames using opencv.
    Returns 0-100 or None if cv2 unavailable.
    """
    try:
        import cv2
        img_a = cv2.imread(first_frame)
        img_b = cv2.imread(last_frame)
        if img_a is None or img_b is None:
            return None
        # Resize to same size for fair comparison
        img_b = cv2.resize(img_b, (img_a.shape[1], img_a.shape[0]))
        # Compute histograms in HSV space (more perceptually meaningful)
        hsv_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
        hsv_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
        hist_a = cv2.calcHist([hsv_a], [0, 1], None, [50, 60], [0, 180, 0, 256])
        hist_b = cv2.calcHist([hsv_b], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist_a, hist_a, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hist_b, hist_b, 0, 1, cv2.NORM_MINMAX)
        # Correlation method: -1..1, higher is better
        sim = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
        return max(0.0, min(100.0, (sim + 1.0) / 2.0 * 100))
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"Histogram similarity failed: {e}")
        return None


def audio_continuity_rms(video_path: str, duration: float) -> Tuple[Optional[float], str]:
    """
    Check audio continuity at the loop boundary. Returns (score 0-100, method).
    
    A "good" loop has audio levels at the end roughly matching the start (no
    sudden silence or volume drop). We extract short audio snippets from the
    start and end and compare RMS energy.
    """
    if duration is None or duration < 2:
        return None, "none"
    
    try:
        import librosa
        with tempfile.TemporaryDirectory() as tmpdir:
            start_audio = os.path.join(tmpdir, "start.wav")
            end_audio = os.path.join(tmpdir, "end.wav")
            
            # Extract first 2 seconds
            r1 = subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-ss", "0", "-t", "2",
                 "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", start_audio],
                capture_output=True, timeout=30,
            )
            # Extract last 2 seconds
            end_start = max(0, duration - 2)
            r2 = subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-ss", f"{end_start:.2f}", "-t", "2",
                 "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", end_audio],
                capture_output=True, timeout=30,
            )
            
            if r1.returncode != 0 or r2.returncode != 0:
                return None, "none"
            
            y1, _ = librosa.load(start_audio, sr=16000)
            y2, _ = librosa.load(end_audio, sr=16000)
            
            rms1 = float(librosa.feature.rms(y=y1).mean())
            rms2 = float(librosa.feature.rms(y=y2).mean())
            
            if rms1 < 1e-6 and rms2 < 1e-6:
                return 50.0, "rms"
            
            # Score: how close is the end RMS to the start RMS?
            # Penalize end-silence (rms2 << rms1) more heavily
            if rms2 < rms1 * 0.3:
                # End is much quieter than start - bad for looping
                return 30.0, "rms"
            ratio = min(rms1, rms2) / max(rms1, rms2)
            return ratio * 100, "rms"
    except ImportError:
        return None, "none"
    except Exception as e:
        logger.warning(f"Audio RMS analysis failed: {e}")
        return None, "none"


def audio_continuity_ffmpeg(video_path: str, duration: float) -> Tuple[Optional[float], str]:
    """
    Fallback audio analysis using ffmpeg's volumedetect filter.
    Compares mean volume at start vs end.
    """
    if duration is None or duration < 2:
        return None, "none"
    
    def mean_volume_db(start: float, length: float) -> Optional[float]:
        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
                "-af", "volumedetect", "-vn", "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", result.stderr)
            if match:
                return float(match.group(1))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
    
    start_db = mean_volume_db(0, 2)
    end_db = mean_volume_db(max(0, duration - 2), 2)
    
    if start_db is None or end_db is None:
        return None, "none"
    
    # Both very quiet => probably both silence, neutral score
    if start_db < -50 and end_db < -50:
        return 50.0, "ffmpeg"
    
    # End much quieter than start => bad for loop
    diff_db = start_db - end_db
    if diff_db > 10:
        return 30.0, "ffmpeg"
    
    # Closer the dB values, better the loop continuity
    score = 100 - min(70, abs(diff_db) * 5)
    return max(0.0, score), "ffmpeg"


class LoopDesigner:
    """
    Analyzes loop quality and generates better endings using LLM.
    """

    def __init__(self):
        self.llm_client = get_llm_client()
        # See HookLab.set_budget_context for the rationale.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def analyze_loop(
        self,
        transcript: Optional[str] = None,
        video_path: Optional[str] = None,
    ) -> LoopAnalysis:
        """
        Analyze a video's loop quality from text + (optionally) visual + audio.
        
        Args:
            transcript: Full transcript text. Required for text scoring.
            video_path: Local video file path. Required for visual + audio scoring.
        """
        analysis = LoopAnalysis(
            overall_score=0.0,
            text_score=0.0,
            visual_score=0.0,
            audio_score=0.0,
            has_stop_signals=False,
        )
        
        # ---- TEXT ANALYSIS ----
        if transcript and transcript.strip():
            first = get_first_words(transcript, 15)
            last = get_last_words(transcript, 15)
            analysis.first_words = first
            analysis.last_words = last
            
            # Stop signals
            has_stop, stops = detect_stop_signals(last)
            analysis.has_stop_signals = has_stop
            analysis.stop_signals_found = stops
            
            # Try semantic similarity first
            sem_score = text_similarity_embedding(first, last)
            if sem_score is not None:
                analysis.text_score = sem_score
                analysis.text_method = "embedding"
            else:
                analysis.text_score = text_similarity_lexical(first, last)
                analysis.text_method = "lexical"
            
            # Heavy penalty for stop signals
            if has_stop:
                analysis.text_score *= 0.4
                analysis.issues.append(
                    f"Stop signals detected: {', '.join(stops[:2])}. These tell viewers to leave."
                )
                analysis.recommendations.append(
                    "Remove 'thanks for watching' style phrases - they kill the loop."
                )
            
            if analysis.text_score < 30 and not has_stop:
                analysis.issues.append(
                    "Ending text doesn't connect back to the opening - viewers won't loop."
                )
                analysis.recommendations.append(
                    "End with a phrase that semantically connects to your opening words."
                )
        
        # ---- VISUAL ANALYSIS ----
        if video_path and os.path.exists(video_path):
            duration = get_video_duration(video_path)
            if duration and duration > 1:
                with tempfile.TemporaryDirectory() as tmpdir:
                    first_frame = os.path.join(tmpdir, "first.jpg")
                    last_frame = os.path.join(tmpdir, "last.jpg")
                    
                    extracted_first = extract_frame_at(video_path, 0.5, first_frame)
                    extracted_last = extract_frame_at(video_path, max(0.5, duration - 0.5), last_frame)
                    
                    if extracted_first and extracted_last:
                        # Try SSIM first, fallback to histogram
                        ssim = visual_similarity_ssim(first_frame, last_frame)
                        if ssim is not None:
                            analysis.visual_score = ssim
                            analysis.visual_method = "ssim"
                        else:
                            hist = visual_similarity_histogram(first_frame, last_frame)
                            if hist is not None:
                                analysis.visual_score = hist
                                analysis.visual_method = "histogram"
                
                if analysis.visual_score < 30 and analysis.visual_method != "none":
                    analysis.issues.append(
                        "Last frame looks completely different from the first - hard to loop visually."
                    )
                    analysis.recommendations.append(
                        "End on a shot composition similar to your opening (same person, framing, background)."
                    )
                
                # ---- AUDIO ANALYSIS ----
                audio_score, audio_method = audio_continuity_rms(video_path, duration)
                if audio_score is None:
                    audio_score, audio_method = audio_continuity_ffmpeg(video_path, duration)
                
                if audio_score is not None:
                    analysis.audio_score = audio_score
                    analysis.audio_method = audio_method
                    
                    if audio_score < 40:
                        analysis.issues.append(
                            "Audio drops off at the end - creates a noticeable break that prevents looping."
                        )
                        analysis.recommendations.append(
                            "Maintain audio energy through the last frame (don't fade out)."
                        )
        
        # ---- OVERALL SCORE ----
        # Weighted: text=50%, visual=30%, audio=20% (only count signals we have)
        weights = []
        scores = []
        if analysis.text_method != "none":
            weights.append(0.50)
            scores.append(analysis.text_score)
        if analysis.visual_method != "none":
            weights.append(0.30)
            scores.append(analysis.visual_score)
        if analysis.audio_method != "none":
            weights.append(0.20)
            scores.append(analysis.audio_score)
        
        if weights:
            total_weight = sum(weights)
            analysis.overall_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        
        # Always recommend the best fix
        if analysis.overall_score >= 75 and not analysis.recommendations:
            analysis.recommendations.append(
                "Strong loop! Test viewer retention to confirm replay rate is up."
            )
        elif not analysis.recommendations:
            analysis.recommendations.append(
                "Use the ending generator below to create a better loop-back ending."
            )
        
        return analysis
    
    def generate_loop_endings(
        self,
        opening: str,
        topic: str,
        count: int = 5,
        style: str = "natural",
    ) -> List[str]:
        """
        Generate N possible endings that loop back to the opening.
        
        Args:
            opening: First 1-2 sentences of the video
            topic: What the video is about (for context)
            count: How many ending options to generate
            style: "natural" | "callback" | "question" | "cliffhanger"
        """
        if not opening.strip():
            return []
        
        style_instructions = {
            "natural": "End naturally so the viewer doesn't realize the loop happened.",
            "callback": "Explicitly callback to a phrase or word from the opening.",
            "question": "End with a question whose answer is implied by the opening.",
            "cliffhanger": "End mid-thought so the viewer mentally completes it with the opening.",
        }
        instruction = style_instructions.get(style, style_instructions["natural"])
        
        system_prompt = (
            "You are a viral short-form content writer. You write video endings that "
            "seamlessly loop back to the opening, creating perfect replay loops that "
            "the algorithm rewards. Endings are 8-15 words, never include 'thanks for "
            "watching' or 'subscribe', and feel like a natural continuation that becomes "
            "a beginning."
        )
        
        user_prompt = f"""Write {count} ending sentences for a video about: {topic}

OPENING (the video starts with): "{opening}"

INSTRUCTION: {instruction}

Rules:
- 8-15 words each
- Must flow naturally back into the opening if the video replays
- NEVER include: "thanks for watching", "subscribe", "see you next time", "bye"
- No explicit "and that's why..." filler

Respond with ONLY a JSON array of {count} strings:
["ending 1", "ending 2", ...]"""
        
        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.85,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
                feature="loop_designer.generate_endings",
            )

            if not response.success:
                return self._fallback_endings(opening, topic, count)
            
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            # Find JSON array
            start = text.find('[')
            end = text.rfind(']') + 1
            if start >= 0 and end > start:
                endings = json.loads(text[start:end])
                if isinstance(endings, list):
                    return [str(e).strip() for e in endings[:count] if str(e).strip()]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse endings JSON: {e}")
        
        return self._fallback_endings(opening, topic, count)
    
    def _fallback_endings(self, opening: str, topic: str, count: int) -> List[str]:
        """Template-based fallback endings."""
        topic_clean = topic.strip().rstrip(".")
        first_few = " ".join(opening.split()[:6])
        templates = [
            f"...and that's exactly why {topic_clean} matters.",
            f"Which brings us right back to: {first_few}",
            f"And THAT is the part most people miss about {topic_clean}.",
            f"Now you can see why {topic_clean} works the way it does.",
            f"Which is the whole point of {topic_clean} in the first place.",
        ]
        return templates[:count]


# Module-level helpers
_designer: Optional[LoopDesigner] = None

def get_loop_designer() -> LoopDesigner:
    """Get the shared LoopDesigner instance."""
    global _designer
    if _designer is None:
        _designer = LoopDesigner()
    return _designer

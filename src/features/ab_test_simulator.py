"""
A/B Packaging Comparison (rubric-based)

Compares multiple titles or thumbnails against proven packaging principles and
ranks them. This is COACHING, not a CTR/performance prediction — packaging does
not reliably predict views (proven AUC 0.50; memory: content-classifier-title-
no-signal). The "winner" is the strongest BY THE RUBRIC, to help a creator pick;
the real test is the audience once the video is live.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum
import numpy as np
import re
import io
import base64
from PIL import Image
# Use httpx as a drop-in for requests (sync API is identical) -- unified
# HTTP layer; see CONTRIBUTING.md for the migration path to AsyncClient.
import httpx as requests

from src.features.smart_title_generator import SmartTitleGenerator


class TestType(Enum):
    TITLE = "title"
    THUMBNAIL = "thumbnail"
    COMBINED = "combined"


@dataclass
class Variation:
    """A single variation in an A/B test."""
    id: str
    content: str  # Title text or thumbnail URL/path
    score: float
    rank: int
    strengths: List[str]
    weaknesses: List[str]
    predicted_ctr_boost: float  # Relative to baseline


@dataclass
class ABTestResult:
    """Result of an A/B packaging comparison (rubric-based, NOT a CTR prediction)."""
    test_type: TestType
    category: str
    winner: Variation  # strongest BY THE RUBRIC — not a predicted-CTR winner
    variations: List[Variation]
    confidence: float  # rubric-score gap between top two (not statistical confidence)
    recommendation: str
    insights: List[str]
    disclaimer: str = (
        "This compares packaging against proven principles — it is NOT a CTR or "
        "performance prediction (packaging doesn't reliably predict views). Pick the "
        "one you'd click; the real test is the audience once it's live."
    )


class ABTestSimulator:
    """Simulates A/B tests for titles and thumbnails."""
    
    def __init__(self):
        self.title_generator = SmartTitleGenerator()
    
    def test_titles(
        self,
        titles: List[str],
        category: str = "general",
        channel_id: Optional[str] = None
    ) -> ABTestResult:
        """
        Test multiple title variations and predict winner.
        
        Args:
            titles: List of 2-5 title variations
            category: Video category
            channel_id: Optional channel ID for personalization
            
        Returns:
            ABTestResult with ranked variations
        """
        if len(titles) < 2:
            raise ValueError("Need at least 2 titles to compare")
        
        if len(titles) > 5:
            titles = titles[:5]  # Limit to 5
        
        variations = []
        
        for i, title in enumerate(titles):
            score = self._score_title(title, category)
            strengths = self._find_title_strengths(title)
            weaknesses = self._find_title_weaknesses(title)
            
            variations.append(Variation(
                id=f"title_{i+1}",
                content=title,
                score=score,
                rank=0,  # Will be set after sorting
                strengths=strengths,
                weaknesses=weaknesses,
                predicted_ctr_boost=0  # Will be calculated
            ))
        
        # Sort by score (highest first)
        variations.sort(key=lambda v: v.score, reverse=True)
        
        # Assign ranks and calculate CTR boost
        baseline_score = np.mean([v.score for v in variations])
        for i, v in enumerate(variations):
            v.rank = i + 1
            v.predicted_ctr_boost = ((v.score - baseline_score) / baseline_score) * 100 if baseline_score > 0 else 0
        
        winner = variations[0]
        
        # Calculate confidence (gap between winner and runner-up)
        if len(variations) > 1:
            gap = winner.score - variations[1].score
            confidence = min(95, 50 + gap * 2)  # 50-95% based on gap
        else:
            confidence = 50
        
        # Generate recommendation
        recommendation = self._generate_title_recommendation(winner, variations)
        
        # Generate insights
        insights = self._generate_title_insights(variations)
        
        return ABTestResult(
            test_type=TestType.TITLE,
            category=category,
            winner=winner,
            variations=variations,
            confidence=confidence,
            recommendation=recommendation,
            insights=insights
        )
    
    def test_thumbnails(
        self,
        thumbnails: List[str],  # URLs or base64 encoded images
        category: str = "general"
    ) -> ABTestResult:
        """
        Test multiple thumbnail variations and predict winner.
        
        Args:
            thumbnails: List of thumbnail URLs or base64 strings
            category: Video category
            
        Returns:
            ABTestResult with ranked variations
        """
        if len(thumbnails) < 2:
            raise ValueError("Need at least 2 thumbnails to compare")
        
        if len(thumbnails) > 5:
            thumbnails = thumbnails[:5]
        
        variations = []
        
        for i, thumb in enumerate(thumbnails):
            try:
                features = self._extract_thumbnail_features(thumb)
                score = self._score_thumbnail(features, category)
                strengths = self._find_thumbnail_strengths(features)
                weaknesses = self._find_thumbnail_weaknesses(features)
            except Exception as e:
                # If we can't analyze, give neutral score
                score = 50
                strengths = ["Could not fully analyze"]
                weaknesses = [str(e)]
                features = {}
            
            variations.append(Variation(
                id=f"thumb_{i+1}",
                content=thumb[:100] + "..." if len(thumb) > 100 else thumb,
                score=score,
                rank=0,
                strengths=strengths,
                weaknesses=weaknesses,
                predicted_ctr_boost=0
            ))
        
        # Sort by score
        variations.sort(key=lambda v: v.score, reverse=True)
        
        # Assign ranks and CTR boost
        baseline = np.mean([v.score for v in variations])
        for i, v in enumerate(variations):
            v.rank = i + 1
            v.predicted_ctr_boost = ((v.score - baseline) / baseline) * 100 if baseline > 0 else 0
        
        winner = variations[0]
        
        # Confidence
        if len(variations) > 1:
            gap = winner.score - variations[1].score
            confidence = min(95, 50 + gap * 2)
        else:
            confidence = 50
        
        recommendation = self._generate_thumbnail_recommendation(winner, variations)
        insights = self._generate_thumbnail_insights(variations)
        
        return ABTestResult(
            test_type=TestType.THUMBNAIL,
            category=category,
            winner=winner,
            variations=variations,
            confidence=confidence,
            recommendation=recommendation,
            insights=insights
        )
    
    def test_combined(
        self,
        combinations: List[Dict[str, str]],  # [{"title": "...", "thumbnail": "..."}]
        category: str = "general"
    ) -> ABTestResult:
        """
        Test complete title + thumbnail combinations.
        
        Args:
            combinations: List of {"title": str, "thumbnail": str} dicts
            category: Video category
            
        Returns:
            ABTestResult with ranked combinations
        """
        if len(combinations) < 2:
            raise ValueError("Need at least 2 combinations to compare")
        
        variations = []
        
        for i, combo in enumerate(combinations):
            title = combo.get("title", "")
            thumbnail = combo.get("thumbnail", "")
            
            # Score both components
            title_score = self._score_title(title, category)
            
            try:
                thumb_features = self._extract_thumbnail_features(thumbnail)
                thumb_score = self._score_thumbnail(thumb_features, category)
            except:
                thumb_score = 50
            
            # Combined score (60% title, 40% thumbnail - title usually matters more for CTR)
            combined_score = title_score * 0.6 + thumb_score * 0.4
            
            strengths = []
            weaknesses = []
            
            if title_score > 70:
                strengths.append(f"Strong title ({title_score:.0f})")
            elif title_score < 50:
                weaknesses.append(f"Weak title ({title_score:.0f})")
            
            if thumb_score > 70:
                strengths.append(f"Strong thumbnail ({thumb_score:.0f})")
            elif thumb_score < 50:
                weaknesses.append(f"Weak thumbnail ({thumb_score:.0f})")
            
            variations.append(Variation(
                id=f"combo_{i+1}",
                content=title,
                score=combined_score,
                rank=0,
                strengths=strengths or ["Balanced combination"],
                weaknesses=weaknesses or ["Room for improvement"],
                predicted_ctr_boost=0
            ))
        
        variations.sort(key=lambda v: v.score, reverse=True)
        
        baseline = np.mean([v.score for v in variations])
        for i, v in enumerate(variations):
            v.rank = i + 1
            v.predicted_ctr_boost = ((v.score - baseline) / baseline) * 100 if baseline > 0 else 0
        
        winner = variations[0]
        
        if len(variations) > 1:
            gap = winner.score - variations[1].score
            confidence = min(95, 50 + gap * 2)
        else:
            confidence = 50
        
        recommendation = f"Use combination #{winner.rank}: '{winner.content[:50]}...'"
        insights = [
            f"Winner scores {winner.score:.0f}/100",
            f"Gap to runner-up: {winner.score - variations[1].score:.1f} points" if len(variations) > 1 else ""
        ]
        
        return ABTestResult(
            test_type=TestType.COMBINED,
            category=category,
            winner=winner,
            variations=variations,
            confidence=confidence,
            recommendation=recommendation,
            insights=[i for i in insights if i]
        )
    
    def _score_title(self, title: str, category: str) -> float:
        """Score a title 0-100."""
        score = 50.0
        title_lower = title.lower()
        
        # Length (40-60 chars optimal)
        length = len(title)
        if 40 <= length <= 60:
            score += 10
        elif length < 25:
            score -= 10
        elif length > 75:
            score -= 5
        
        # Has number
        if re.search(r'\d', title):
            score += 8
        
        # Power words
        power_words = ["insane", "epic", "amazing", "incredible", "shocking", "secret", 
                       "ultimate", "complete", "best", "worst", "first", "finally"]
        if any(w in title_lower for w in power_words):
            score += 6
        
        # Weak words
        weak_words = ["very", "really", "just", "stuff", "things", "basically"]
        for word in weak_words:
            if word in title_lower:
                score -= 3
        
        # Question (curiosity)
        if '?' in title:
            score += 5
        
        # Exclamation (energy)
        if '!' in title:
            score += 3
        
        # Brackets (context)
        if '[' in title or '(' in title:
            score += 4
        
        # Category-specific boosts
        if category == "gaming":
            if any(w in title_lower for w in ["gameplay", "challenge", "vs", "pvp"]):
                score += 5
        elif category == "tech":
            if any(w in title_lower for w in ["review", "unboxing", "vs", "comparison"]):
                score += 5
        elif category == "education":
            if any(w in title_lower for w in ["how to", "tutorial", "guide", "learn"]):
                score += 5
        
        return min(100, max(0, score))
    
    def _find_title_strengths(self, title: str) -> List[str]:
        """Find strengths in a title."""
        strengths = []
        title_lower = title.lower()
        
        if re.search(r'\d', title):
            strengths.append("✅ Contains number (specificity)")
        if 40 <= len(title) <= 60:
            strengths.append("✅ Optimal length")
        if '?' in title:
            strengths.append("✅ Question creates curiosity")
        if any(w in title_lower for w in ["insane", "epic", "amazing", "incredible"]):
            strengths.append("✅ Emotional language")
        if '[' in title or '(' in title:
            strengths.append("✅ Context brackets")
        
        return strengths or ["Neutral - no standout elements"]
    
    def _find_title_weaknesses(self, title: str) -> List[str]:
        """Find weaknesses in a title."""
        weaknesses = []
        title_lower = title.lower()
        
        if len(title) > 70:
            weaknesses.append("⚠️ Too long - may truncate")
        elif len(title) < 30:
            weaknesses.append("⚠️ Too short - add context")
        if not re.search(r'\d', title):
            weaknesses.append("⚠️ No numbers")
        
        weak_words = ["very", "really", "just", "stuff"]
        found_weak = [w for w in weak_words if w in title_lower]
        if found_weak:
            weaknesses.append(f"⚠️ Weak words: {', '.join(found_weak)}")
        
        return weaknesses or ["Looking good!"]
    
    def _extract_thumbnail_features(self, thumbnail: str) -> Dict:
        """Extract features from a thumbnail."""
        features = {}
        
        try:
            # Handle URL
            if thumbnail.startswith("http"):
                response = requests.get(thumbnail, timeout=10)
                img = Image.open(io.BytesIO(response.content))
            # Handle base64
            elif thumbnail.startswith("data:image"):
                img_data = base64.b64decode(thumbnail.split(",")[1])
                img = Image.open(io.BytesIO(img_data))
            # Handle file path
            else:
                img = Image.open(thumbnail)
            
            # Convert to RGB if needed
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Basic features
            img_array = np.array(img)
            
            # Brightness
            features["brightness"] = np.mean(img_array)
            
            # Saturation (approximate via std of color channels)
            features["saturation"] = np.std(img_array)
            
            # Contrast (std of brightness)
            gray = np.mean(img_array, axis=2)
            features["contrast"] = np.std(gray)
            
            # Dominant color
            avg_color = np.mean(img_array, axis=(0, 1))
            if avg_color[0] > avg_color[1] and avg_color[0] > avg_color[2]:
                features["dominant_color"] = "red"
            elif avg_color[1] > avg_color[0] and avg_color[1] > avg_color[2]:
                features["dominant_color"] = "green"
            elif avg_color[2] > avg_color[0] and avg_color[2] > avg_color[1]:
                features["dominant_color"] = "blue"
            else:
                features["dominant_color"] = "neutral"
            
            # Edge density (complexity)
            try:
                from PIL import ImageFilter
                edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
                features["complexity"] = np.mean(np.array(edges))
            except:
                features["complexity"] = 50
            
            # Try face detection
            features["has_face"] = False
            try:
                from deepface import DeepFace
                faces = DeepFace.extract_faces(img_array, detector_backend="opencv", enforce_detection=False)
                features["has_face"] = len(faces) > 0
                features["face_count"] = len(faces)
            except:
                pass
            
            # Text detection would go here (EasyOCR)
            features["has_text"] = False
            
        except Exception as e:
            features["error"] = str(e)
        
        return features
    
    def _score_thumbnail(self, features: Dict, category: str) -> float:
        """Score a thumbnail based on features."""
        score = 50.0
        
        # Brightness (not too dark, not too bright)
        brightness = features.get("brightness", 128)
        if 80 < brightness < 200:
            score += 10
        elif brightness < 50 or brightness > 230:
            score -= 10
        
        # Saturation (higher is better for engagement)
        saturation = features.get("saturation", 50)
        if saturation > 60:
            score += 8
        elif saturation < 30:
            score -= 5
        
        # Contrast
        contrast = features.get("contrast", 50)
        if contrast > 50:
            score += 5
        
        # Face (usually helps)
        if features.get("has_face"):
            score += 10
        
        # Text (can help)
        if features.get("has_text"):
            score += 5
        
        # Category adjustments
        if category == "gaming":
            if features.get("saturation", 0) > 70:
                score += 5  # Gaming likes vibrant
        elif category == "tech":
            if features.get("brightness", 0) > 150:
                score += 3  # Clean, bright look
        
        return min(100, max(0, score))
    
    def _find_thumbnail_strengths(self, features: Dict) -> List[str]:
        """Find thumbnail strengths."""
        strengths = []
        
        if features.get("has_face"):
            strengths.append("✅ Face detected (builds connection)")
        if features.get("saturation", 0) > 60:
            strengths.append("✅ Vibrant colors (attention-grabbing)")
        if features.get("contrast", 0) > 50:
            strengths.append("✅ Good contrast (readable)")
        if 100 < features.get("brightness", 0) < 180:
            strengths.append("✅ Optimal brightness")
        
        return strengths or ["Neutral composition"]
    
    def _find_thumbnail_weaknesses(self, features: Dict) -> List[str]:
        """Find thumbnail weaknesses."""
        weaknesses = []
        
        if not features.get("has_face"):
            weaknesses.append("⚠️ No face (consider adding)")
        if features.get("brightness", 128) < 60:
            weaknesses.append("⚠️ Too dark")
        elif features.get("brightness", 128) > 220:
            weaknesses.append("⚠️ Too bright/washed out")
        if features.get("saturation", 50) < 35:
            weaknesses.append("⚠️ Low saturation (boost colors)")
        
        return weaknesses or ["Looking good!"]
    
    def _generate_title_recommendation(self, winner: Variation, all_vars: List[Variation]) -> str:
        """Generate recommendation text."""
        gap = winner.score - all_vars[-1].score if len(all_vars) > 1 else 0
        
        if gap > 20:
            return f"Clear winner: '{winner.content[:40]}...' with {gap:.0f} point advantage"
        elif gap > 10:
            return f"Recommended: '{winner.content[:40]}...' - moderate advantage"
        else:
            return f"Close call: '{winner.content[:40]}...' slightly edges out others"
    
    def _generate_thumbnail_recommendation(self, winner: Variation, all_vars: List[Variation]) -> str:
        """Generate thumbnail recommendation."""
        return f"Use thumbnail #{winner.rank} (score: {winner.score:.0f}/100)"
    
    def _generate_title_insights(self, variations: List[Variation]) -> List[str]:
        """Generate insights from title comparison."""
        insights = []
        
        scores = [v.score for v in variations]
        insights.append(f"Score range: {min(scores):.0f} - {max(scores):.0f}")
        
        # Find what the winner has that others don't
        winner = variations[0]
        for strength in winner.strengths:
            if "✅" in strength:
                insights.append(f"Winner advantage: {strength.replace('✅ ', '')}")
                break
        
        return insights
    
    def _generate_thumbnail_insights(self, variations: List[Variation]) -> List[str]:
        """Generate insights from thumbnail comparison."""
        insights = []
        
        scores = [v.score for v in variations]
        insights.append(f"Score range: {min(scores):.0f} - {max(scores):.0f}")
        
        return insights


def test_titles(titles: List[str], category: str = "general") -> ABTestResult:
    """Convenience function to test titles."""
    simulator = ABTestSimulator()
    return simulator.test_titles(titles, category)


def test_thumbnails(thumbnails: List[str], category: str = "general") -> ABTestResult:
    """Convenience function to test thumbnails."""
    simulator = ABTestSimulator()
    return simulator.test_thumbnails(thumbnails, category)





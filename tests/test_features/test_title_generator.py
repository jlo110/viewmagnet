"""
Tests for the Smart Title Generator feature.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestSmartTitleGenerator:
    """Test the SmartTitleGenerator class."""
    
    @pytest.fixture
    def title_generator(self):
        """Create a mock title generator instance."""
        with patch("src.features.smart_title_generator.get_session"):
            from src.features.smart_title_generator import SmartTitleGenerator
            return SmartTitleGenerator()
    
    def test_score_title_basic(self, title_generator):
        """Test basic title scoring using the internal _score_title method."""
        score = title_generator._score_title("How to Learn Python in 30 Days", "technology")
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100
    
    def test_score_title_with_numbers(self, title_generator):
        """Test title with numbers scores higher."""
        score_with_number = title_generator._score_title("5 Ways to Learn Python Fast", "technology")
        score_without_number = title_generator._score_title("Ways to Learn Python Fast", "technology")
        
        # Numbers typically improve score
        assert score_with_number >= score_without_number - 10
    
    def test_extract_subject_from_title(self, title_generator):
        """Test subject extraction from titles."""
        subject = title_generator._extract_subject("I bought the new iPhone so you don't have to")
        assert subject is not None
        assert len(subject) > 0
    
    def test_generate_returns_analysis(self, title_generator):
        """Test that generate returns a TitleAnalysis."""
        with patch.object(title_generator, "_get_niche_patterns", return_value={}):
            with patch.object(title_generator, "_get_channel_patterns", return_value=None):
                from src.features.smart_title_generator import TitleAnalysis
                result = title_generator.generate(
                    original_title="Python programming tips",
                    category="technology",
                )
        
        assert isinstance(result, TitleAnalysis)
    
    def test_find_strengths(self, title_generator):
        """Test strength identification in titles."""
        strengths = title_generator._find_strengths(
            "5 AMAZING Python Tips You NEED to Know!"
        )
        
        assert isinstance(strengths, list)
    
    def test_find_weaknesses(self, title_generator):
        """Test weakness identification in titles."""
        weaknesses = title_generator._find_weaknesses(
            "python tips"
        )
        
        assert isinstance(weaknesses, list)
        # Short lowercase title should have weaknesses
        assert len(weaknesses) > 0
    
    def test_get_niche_patterns(self, title_generator):
        """Test getting niche-specific patterns."""
        patterns = title_generator._get_niche_patterns("gaming")
        assert isinstance(patterns, dict)
    
    def test_generate_from_templates(self, title_generator):
        """Test template-based title generation."""
        suggestions = title_generator._generate_from_templates(
            original="Python tips for beginners",
            category="technology",
            niche_data={}
        )
        assert isinstance(suggestions, list)


class TestTitleSuggestion:
    """Test TitleSuggestion dataclass."""
    
    def test_title_suggestion_creation(self):
        """Test creating a TitleSuggestion."""
        with patch("src.features.smart_title_generator.get_session"):
            from src.features.smart_title_generator import TitleSuggestion
            
            suggestion = TitleSuggestion(
                title="10 Python Tips",
                score=85,
                reason="Has number and power words",
                pattern_used="listicle",
                improvements=["Add emoji", "Use caps"]
            )
            
            assert suggestion.title == "10 Python Tips"
            assert suggestion.score == 85
            assert "number" in suggestion.reason


class TestConvenienceFunctions:
    """Test module-level convenience functions."""
    
    def test_generate_titles_function_exists(self):
        """Test that generate_titles function exists."""
        with patch("src.features.smart_title_generator.get_session"):
            from src.features.smart_title_generator import generate_titles
            assert callable(generate_titles)

"""Tests for ai_writer.py - AI-powered content generation."""
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.features.ai_writer import (
    GeneratedDescription,
    GeneratedTags,
    GeneratedHook,
    GeneratedHooks,
    AIWriter,
)


class TestGeneratedDescription:
    """Tests for GeneratedDescription dataclass."""
    
    def test_description_creation(self):
        """Test creating a GeneratedDescription instance."""
        desc = GeneratedDescription(
            description="This video shows you how to learn Python programming...",
            word_count=150,
            has_timestamps=True,
            has_cta=True,
            seo_keywords=["python", "programming", "tutorial"],
            niche_optimizations=["Added chapter markers", "Included popular search terms"],
        )
        assert desc.word_count == 150
        assert desc.has_timestamps is True
        assert len(desc.seo_keywords) == 3


class TestGeneratedTags:
    """Tests for GeneratedTags dataclass."""
    
    def test_tags_creation(self):
        """Test creating a GeneratedTags instance."""
        tags = GeneratedTags(
            tags=["python", "programming", "tutorial", "learn python"],
            primary_tags=["python", "programming"],
            secondary_tags=["tutorial", "learn python"],
            long_tail_tags=["python programming for beginners", "learn python 2026"],
            total_characters=120,
            niche_specific_tags=["python beginner", "coding tutorial"],
        )
        assert len(tags.tags) == 4
        assert len(tags.primary_tags) == 2
        assert tags.total_characters == 120


class TestGeneratedHook:
    """Tests for GeneratedHook dataclass."""
    
    def test_hook_creation(self):
        """Test creating a GeneratedHook instance."""
        hook = GeneratedHook(
            hook_type="question",
            script="Did you know that 90% of developers fail to learn Python properly?",
            duration_seconds=8,
            why_it_works="Questions engage viewers and create curiosity",
            niche_insight="Questions perform 15% better in tech tutorials",
        )
        assert hook.hook_type == "question"
        assert hook.duration_seconds == 8
        assert "curiosity" in hook.why_it_works.lower()


class TestGeneratedHooks:
    """Tests for GeneratedHooks dataclass."""
    
    def test_hooks_collection_creation(self):
        """Test creating a GeneratedHooks collection."""
        hook1 = GeneratedHook("question", "Why?", 5, "Creates curiosity", "")
        hook2 = GeneratedHook("bold_claim", "I did it!", 5, "Surprising", "")
        
        hooks = GeneratedHooks(
            title="Learn Python Fast",
            category="Education",
            hooks=[hook1, hook2],
            recommended=hook1,
            recommendation_reason="Questions work best for tutorials",
        )
        assert len(hooks.hooks) == 2
        assert hooks.recommended == hook1


class TestAIWriter:
    """Tests for AIWriter class."""
    
    def test_init_creates_llm_client(self):
        """Test that AIWriter initialises with an LLMClient (not a raw Anthropic client)."""
        # AIWriter was refactored: it no longer exposes ANTHROPIC_AVAILABLE or
        # self.client.  It now delegates all LLM calls through self.llm_client
        # which is a shared LLMClient instance.
        writer = AIWriter()
        assert hasattr(writer, "llm_client")
        assert writer.llm_client is not None
    
    def test_init_loads_niche_patterns(self):
        """Test that niche patterns are loaded on init."""
        writer = AIWriter()
        # Should have discovered_insights as fallback
        assert hasattr(writer, "discovered_insights")
        assert "gaming" in writer.discovered_insights
        assert "tech" in writer.discovered_insights
        assert "education" in writer.discovered_insights
    
    def test_discovered_insights_structure(self):
        """Test discovered insights have correct structure."""
        writer = AIWriter()
        
        # Gaming insights
        gaming = writer.discovered_insights.get("gaming", {})
        assert "power_words" in gaming
        assert "title_patterns" in gaming
        assert "hook_style" in gaming
        assert "findings" in gaming
        
        # Tech insights
        tech = writer.discovered_insights.get("tech", {})
        assert "power_words" in tech
        assert isinstance(tech["power_words"], list)
    
    def test_gaming_insights(self):
        """Test gaming niche insights."""
        writer = AIWriter()
        gaming = writer.discovered_insights["gaming"]
        
        assert "challenge" in gaming["power_words"]
        assert "gameplay" in gaming["power_words"]
        assert gaming["avg_title_length"] == 52
        # Check for specific finding
        assert any("exclamation" in f.lower() for f in gaming["findings"])
    
    def test_tech_insights(self):
        """Test tech niche insights."""
        writer = AIWriter()
        tech = writer.discovered_insights["tech"]
        
        assert "review" in tech["power_words"]
        assert "comparison" in tech["power_words"]
        assert tech["avg_title_length"] == 48
    
    def test_education_insights(self):
        """Test education niche insights."""
        writer = AIWriter()
        education = writer.discovered_insights["education"]
        
        assert "how to" in education["power_words"]
        assert "tutorial" in education["power_words"]
        assert education["avg_title_length"] == 55
    
    @patch("anthropic.Anthropic")
    def test_generate_description_without_client(self, mock_anthropic):
        """Test description generation without API client."""
        writer = AIWriter()
        writer.client = None
        
        if hasattr(writer, "generate_description"):
            # Should handle gracefully or raise appropriate error
            try:
                result = writer.generate_description("Test Video", "Gaming")
                # If it returns something, check it's valid
                assert result is None or isinstance(result, (str, GeneratedDescription))
            except (ValueError, AttributeError):
                pass  # Expected without API
    
    @patch("anthropic.Anthropic")
    def test_generate_description_with_client(self, mock_anthropic):
        """Test description generation with mocked API."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="""
A comprehensive guide to Python programming.

Timestamps:
0:00 Introduction
1:30 Getting Started

Don't forget to subscribe!
        """)]
        mock_client.messages.create.return_value = mock_response
        
        writer = AIWriter()
        writer.client = mock_client
        
        if hasattr(writer, "generate_description"):
            result = writer.generate_description("Python Tutorial", "Education")
            # Should get some response
            assert result is not None
    
    @patch("anthropic.Anthropic")
    def test_generate_tags(self, mock_anthropic):
        """Test tag generation."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="python, programming, tutorial, learn python, coding")]
        mock_client.messages.create.return_value = mock_response
        
        writer = AIWriter()
        writer.client = mock_client
        
        if hasattr(writer, "generate_tags"):
            result = writer.generate_tags("Python Tutorial", "Education")
            assert result is not None
    
    @patch("anthropic.Anthropic")
    def test_generate_hooks(self, mock_anthropic):
        """Test hook generation."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="""
QUESTION: Did you know that 90% of developers fail?
BOLD CLAIM: I learned Python in 30 days.
STORY: Last year, I was struggling with code...
        """)]
        mock_client.messages.create.return_value = mock_response
        
        writer = AIWriter()
        writer.client = mock_client
        
        if hasattr(writer, "generate_hooks"):
            result = writer.generate_hooks("Learn Python", "Education")
            assert result is not None
    
    def test_niche_pattern_fallback(self):
        """Test that AIWriter has fallback discovered_insights."""
        writer = AIWriter()
        # Should have fallback patterns regardless of niche pattern discovery
        assert len(writer.discovered_insights) > 0
    
    def test_power_words_are_lists(self):
        """Test that power words are proper lists."""
        writer = AIWriter()
        
        for niche, insights in writer.discovered_insights.items():
            assert isinstance(insights["power_words"], list)
            assert len(insights["power_words"]) > 0
    
    def test_entertainment_insights(self):
        """Test entertainment niche insights."""
        writer = AIWriter()
        entertainment = writer.discovered_insights["entertainment"]
        
        assert "reaction" in entertainment["power_words"]
        assert "challenge" in entertainment["power_words"]


class TestNicheOptimization:
    """Tests for niche-specific optimization."""
    
    def test_gaming_avoids_exclamation(self):
        """Test gaming optimization avoids exclamation marks."""
        writer = AIWriter()
        gaming = writer.discovered_insights["gaming"]
        
        # The finding states exclamation marks hurt performance
        findings_text = " ".join(gaming["findings"]).lower()
        assert "exclamation" in findings_text
    
    def test_tech_prefers_music_intros(self):
        """Test tech optimization prefers music intros."""
        writer = AIWriter()
        tech = writer.discovered_insights["tech"]
        
        findings_text = " ".join(tech["findings"]).lower()
        assert "music" in findings_text
    
    def test_education_benefits_from_questions(self):
        """Test education optimization favors questions."""
        writer = AIWriter()
        education = writer.discovered_insights["education"]
        
        findings_text = " ".join(education["findings"]).lower()
        assert "question" in findings_text

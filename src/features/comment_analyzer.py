"""
Comment Sentiment Analysis for ViewMagnet.

Fetches YouTube comments and performs sentiment analysis to understand
audience feedback and engagement patterns.
"""
import os
import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter

import structlog

logger = structlog.get_logger()


@dataclass
class Comment:
    """Represents a YouTube comment."""
    comment_id: str
    video_id: str
    author_name: str
    author_channel_id: str
    text: str
    like_count: int
    reply_count: int
    published_at: datetime
    updated_at: datetime
    is_reply: bool = False
    parent_id: Optional[str] = None
    
    # Sentiment analysis results
    sentiment: Optional[str] = None  # positive, negative, neutral, mixed
    sentiment_score: Optional[float] = None  # -1 to 1
    topics: List[str] = field(default_factory=list)
    emotions: List[str] = field(default_factory=list)


@dataclass
class CommentAnalysis:
    """Analysis results for video comments."""
    video_id: str
    total_comments: int
    analyzed_comments: int
    
    # Sentiment distribution
    sentiment_distribution: Dict[str, int]  # positive, negative, neutral, mixed counts
    avg_sentiment_score: float
    
    # Top insights
    top_positive_comments: List[Comment]
    top_negative_comments: List[Comment]
    most_liked_comments: List[Comment]
    
    # Topics and themes
    common_topics: List[Tuple[str, int]]
    common_emotions: List[Tuple[str, int]]
    
    # Keywords
    positive_keywords: List[Tuple[str, int]]
    negative_keywords: List[Tuple[str, int]]
    
    # Engagement metrics
    avg_likes_per_comment: float
    comments_with_replies_pct: float


class SentimentAnalyzer:
    """
    Performs sentiment analysis on text.
    
    Uses a lexicon-based approach with enhancement for YouTube-specific
    language patterns.
    """
    
    # Positive word patterns
    POSITIVE_WORDS = {
        "great", "awesome", "amazing", "love", "excellent", "fantastic",
        "incredible", "wonderful", "perfect", "best", "helpful", "useful",
        "informative", "insightful", "brilliant", "genius", "thanks",
        "thank", "appreciate", "learned", "learning", "inspired", "inspiring",
        "beautiful", "fire", "goat", "legend", "masterpiece", "epic",
        "subscribed", "subscribing", "liked", "shared", "recommend",
        "underrated", "undervalued", "quality", "value", "free", "gold",
        "gem", "banger", "top-notch", "elite", "superb", "outstanding",
        "exceptional", "remarkable", "phenomenal", "extraordinary",
    }
    
    # Negative word patterns
    NEGATIVE_WORDS = {
        "bad", "terrible", "awful", "hate", "horrible", "worst", "boring",
        "useless", "waste", "misleading", "clickbait", "scam", "fake",
        "disappointing", "disappointed", "annoying", "irritating", "frustrated",
        "confusing", "confused", "wrong", "incorrect", "mistake", "error",
        "overrated", "overhyped", "trash", "garbage", "cringe", "mid",
        "unsubscribed", "dislike", "skip", "skipped", "stopped", "unwatchable",
        "repetitive", "filler", "padding", "wasted", "regret", "avoid",
    }
    
    # Intensifiers that amplify sentiment
    INTENSIFIERS = {
        "very", "really", "extremely", "absolutely", "totally", "completely",
        "super", "highly", "incredibly", "utterly", "quite", "truly",
        "definitely", "certainly", "seriously", "literally", "actually",
    }
    
    # Negators that flip sentiment
    NEGATORS = {
        "not", "no", "never", "neither", "nobody", "nothing", "nowhere",
        "hardly", "barely", "scarcely", "don't", "doesn't", "didn't",
        "won't", "wouldn't", "couldn't", "shouldn't", "isn't", "aren't",
        "wasn't", "weren't", "haven't", "hasn't", "hadn't",
    }
    
    # Emotion keywords
    EMOTION_KEYWORDS = {
        "happy": ["happy", "joy", "excited", "delighted", "pleased"],
        "sad": ["sad", "crying", "depressed", "heartbroken", "devastated"],
        "angry": ["angry", "furious", "mad", "outraged", "pissed"],
        "surprised": ["surprised", "shocked", "amazed", "stunned", "mindblown"],
        "fearful": ["scared", "afraid", "worried", "anxious", "nervous"],
        "disgusted": ["disgusted", "gross", "eww", "yuck", "nasty"],
        "amused": ["lol", "lmao", "haha", "funny", "hilarious", "laughing"],
        "inspired": ["inspired", "motivated", "pumped", "energized"],
        "grateful": ["grateful", "thankful", "blessed", "appreciate"],
        "curious": ["curious", "wondering", "interested", "intrigued"],
    }
    
    def analyze_sentiment(self, text: str) -> Tuple[str, float]:
        """
        Analyze sentiment of a text.
        
        Args:
            text: Text to analyze.
        
        Returns:
            Tuple of (sentiment label, score from -1 to 1).
        """
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)
        
        positive_count = 0
        negative_count = 0
        has_negation = False
        
        for i, word in enumerate(words):
            # Check for negation in the last few words
            if i > 0 and any(words[max(0, i-3):i].__contains__(neg) for neg in self.NEGATORS):
                has_negation = True
            else:
                has_negation = False
            
            if word in self.POSITIVE_WORDS:
                if has_negation:
                    negative_count += 1
                else:
                    positive_count += 1
            elif word in self.NEGATIVE_WORDS:
                if has_negation:
                    positive_count += 1
                else:
                    negative_count += 1
        
        # Check for intensifiers
        intensifier_count = sum(1 for w in words if w in self.INTENSIFIERS)
        
        # Calculate score
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            return "neutral", 0.0
        
        base_score = (positive_count - negative_count) / total_sentiment_words
        
        # Apply intensifier boost
        if intensifier_count > 0:
            base_score *= (1 + 0.1 * min(intensifier_count, 3))
        
        # Clamp score
        score = max(-1.0, min(1.0, base_score))
        
        # Determine label
        if score > 0.2:
            label = "positive"
        elif score < -0.2:
            label = "negative"
        elif positive_count > 0 and negative_count > 0:
            label = "mixed"
        else:
            label = "neutral"
        
        return label, round(score, 3)
    
    def extract_emotions(self, text: str) -> List[str]:
        """Extract emotions from text."""
        text_lower = text.lower()
        detected = []
        
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(emotion)
        
        return detected
    
    def extract_topics(self, text: str) -> List[str]:
        """Extract likely topics/themes from text."""
        # Simple keyword-based topic extraction
        topic_patterns = {
            "question": [r'\?', r'how do', r'what is', r'why', r'when', r'where', r'can you'],
            "request": [r'please', r'could you', r'make a video', r'tutorial on', r'more about'],
            "feedback": [r'suggestion', r'feedback', r'improve', r'better if'],
            "comparison": [r'vs', r'compared to', r'better than', r'worse than', r'similar'],
            "personal_story": [r'my experience', r'i tried', r'worked for me', r'i used'],
            "timestamp": [r'\d+:\d+', r'at \d+ minute'],
            "disagreement": [r'disagree', r'actually', r'wrong', r'incorrect', r'mistaken'],
            "agreement": [r'agree', r'exactly', r'this\s*[.!]', r'facts', r'true'],
        }
        
        text_lower = text.lower()
        topics = []
        
        for topic, patterns in topic_patterns.items():
            if any(re.search(p, text_lower) for p in patterns):
                topics.append(topic)
        
        return topics


class CommentFetcher:
    """
    Fetches comments from YouTube videos.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            logger.warning("YouTube API key not configured")
    
    def fetch_comments(
        self,
        video_id: str,
        max_results: int = 100,
        order: str = "relevance",  # relevance or time
    ) -> List[Comment]:
        """
        Fetch comments for a video.
        
        Args:
            video_id: YouTube video ID.
            max_results: Maximum number of top-level comments to fetch.
            order: Sort order (relevance or time).
        
        Returns:
            List of Comment objects.
        """
        if not self.api_key:
            logger.error("Cannot fetch comments without API key")
            return []
        
        try:
            from googleapiclient.discovery import build
            
            youtube = build("youtube", "v3", developerKey=self.api_key)
            
            comments = []
            page_token = None
            
            while len(comments) < max_results:
                request = youtube.commentThreads().list(
                    part="snippet,replies",
                    videoId=video_id,
                    maxResults=min(100, max_results - len(comments)),
                    order=order,
                    textFormat="plainText",
                    pageToken=page_token,
                )
                response = request.execute()
                
                for item in response.get("items", []):
                    snippet = item["snippet"]["topLevelComment"]["snippet"]
                    
                    comment = Comment(
                        comment_id=item["snippet"]["topLevelComment"]["id"],
                        video_id=video_id,
                        author_name=snippet["authorDisplayName"],
                        author_channel_id=snippet.get("authorChannelId", {}).get("value", ""),
                        text=snippet["textDisplay"],
                        like_count=snippet.get("likeCount", 0),
                        reply_count=item["snippet"].get("totalReplyCount", 0),
                        published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
                        updated_at=datetime.fromisoformat(snippet["updatedAt"].replace("Z", "+00:00")),
                        is_reply=False,
                    )
                    comments.append(comment)
                
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            
            return comments
            
        except Exception as e:
            logger.error(f"Failed to fetch comments: {e}")
            return []


class CommentAnalyzerService:
    """
    High-level service for analyzing video comments.
    """
    
    def __init__(self):
        self.fetcher = CommentFetcher()
        self.sentiment_analyzer = SentimentAnalyzer()
    
    def analyze_video_comments(
        self,
        video_id: str,
        max_comments: int = 100,
    ) -> CommentAnalysis:
        """
        Fetch and analyze comments for a video.
        
        Args:
            video_id: YouTube video ID.
            max_comments: Maximum comments to analyze.
        
        Returns:
            CommentAnalysis with sentiment and topic insights.
        """
        # Fetch comments
        comments = self.fetcher.fetch_comments(video_id, max_results=max_comments)
        
        if not comments:
            return CommentAnalysis(
                video_id=video_id,
                total_comments=0,
                analyzed_comments=0,
                sentiment_distribution={"positive": 0, "negative": 0, "neutral": 0, "mixed": 0},
                avg_sentiment_score=0,
                top_positive_comments=[],
                top_negative_comments=[],
                most_liked_comments=[],
                common_topics=[],
                common_emotions=[],
                positive_keywords=[],
                negative_keywords=[],
                avg_likes_per_comment=0,
                comments_with_replies_pct=0,
            )
        
        # Analyze each comment
        sentiment_counts = Counter()
        total_score = 0
        all_topics = Counter()
        all_emotions = Counter()
        positive_words_found = Counter()
        negative_words_found = Counter()
        
        for comment in comments:
            # Sentiment analysis
            sentiment, score = self.sentiment_analyzer.analyze_sentiment(comment.text)
            comment.sentiment = sentiment
            comment.sentiment_score = score
            
            sentiment_counts[sentiment] += 1
            total_score += score
            
            # Topic extraction
            topics = self.sentiment_analyzer.extract_topics(comment.text)
            comment.topics = topics
            all_topics.update(topics)
            
            # Emotion extraction
            emotions = self.sentiment_analyzer.extract_emotions(comment.text)
            comment.emotions = emotions
            all_emotions.update(emotions)
            
            # Track sentiment keywords
            words = set(re.findall(r'\b\w+\b', comment.text.lower()))
            positive_words_found.update(words & self.sentiment_analyzer.POSITIVE_WORDS)
            negative_words_found.update(words & self.sentiment_analyzer.NEGATIVE_WORDS)
        
        # Sort comments for insights
        positive_comments = sorted(
            [c for c in comments if c.sentiment == "positive"],
            key=lambda c: c.sentiment_score or 0,
            reverse=True
        )[:5]
        
        negative_comments = sorted(
            [c for c in comments if c.sentiment == "negative"],
            key=lambda c: c.sentiment_score or 0
        )[:5]
        
        most_liked = sorted(comments, key=lambda c: c.like_count, reverse=True)[:5]
        
        # Calculate engagement metrics
        total_likes = sum(c.like_count for c in comments)
        comments_with_replies = sum(1 for c in comments if c.reply_count > 0)
        
        return CommentAnalysis(
            video_id=video_id,
            total_comments=len(comments),
            analyzed_comments=len(comments),
            sentiment_distribution=dict(sentiment_counts),
            avg_sentiment_score=round(total_score / len(comments), 3) if comments else 0,
            top_positive_comments=positive_comments,
            top_negative_comments=negative_comments,
            most_liked_comments=most_liked,
            common_topics=all_topics.most_common(10),
            common_emotions=all_emotions.most_common(10),
            positive_keywords=positive_words_found.most_common(10),
            negative_keywords=negative_words_found.most_common(10),
            avg_likes_per_comment=round(total_likes / len(comments), 1) if comments else 0,
            comments_with_replies_pct=round(comments_with_replies / len(comments) * 100, 1) if comments else 0,
        )
    
    def get_sentiment_summary(self, analysis: CommentAnalysis) -> Dict[str, Any]:
        """Generate a summary of the sentiment analysis."""
        total = analysis.total_comments
        if total == 0:
            return {"summary": "No comments to analyze"}
        
        positive_pct = analysis.sentiment_distribution.get("positive", 0) / total * 100
        negative_pct = analysis.sentiment_distribution.get("negative", 0) / total * 100
        
        # Determine overall sentiment
        if positive_pct > 60:
            overall = "Very Positive"
        elif positive_pct > 40:
            overall = "Mostly Positive"
        elif negative_pct > 40:
            overall = "Concerning - High Negative Sentiment"
        elif positive_pct > negative_pct:
            overall = "Mixed - Slightly Positive"
        else:
            overall = "Mixed - Slightly Negative"
        
        return {
            "overall_sentiment": overall,
            "positive_percentage": round(positive_pct, 1),
            "negative_percentage": round(negative_pct, 1),
            "neutral_percentage": round(analysis.sentiment_distribution.get("neutral", 0) / total * 100, 1),
            "avg_score": analysis.avg_sentiment_score,
            "top_positive_keywords": [kw for kw, _ in analysis.positive_keywords[:5]],
            "top_negative_keywords": [kw for kw, _ in analysis.negative_keywords[:5]],
            "common_topics": [topic for topic, _ in analysis.common_topics[:5]],
            "common_emotions": [emotion for emotion, _ in analysis.common_emotions[:5]],
        }


# Convenience functions
def analyze_comments(video_id: str, max_comments: int = 100) -> CommentAnalysis:
    """
    Analyze comments for a video.
    
    Args:
        video_id: YouTube video ID.
        max_comments: Maximum comments to analyze.
    
    Returns:
        CommentAnalysis with insights.
    """
    service = CommentAnalyzerService()
    return service.analyze_video_comments(video_id, max_comments)


def get_sentiment_summary(video_id: str) -> Dict[str, Any]:
    """
    Get a quick sentiment summary for a video's comments.
    
    Args:
        video_id: YouTube video ID.
    
    Returns:
        Dict with sentiment summary.
    """
    service = CommentAnalyzerService()
    analysis = service.analyze_video_comments(video_id, max_comments=50)
    return service.get_sentiment_summary(analysis)

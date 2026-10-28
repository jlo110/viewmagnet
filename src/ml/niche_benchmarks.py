"""
Niche Benchmarks Calculator

Calculates category-specific benchmarks for personalized recommendations:
- Average metrics per category
- Top 10% performer metrics per category
- Gap analysis between user and benchmarks

Supports hierarchical fallback:
- Use micro-niche if 50+ channels
- Fall back to category otherwise
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional
from sqlalchemy import and_, func
from src.database.models import Video, VideoFeatures, Channel, Niche
from src.database.connection import get_session
import logging

logger = logging.getLogger(__name__)

# Minimum channels/videos for reliable benchmarks
MIN_CHANNELS_FOR_MICRONICHE = 50
MIN_VIDEOS_FOR_BENCHMARK = 100


@dataclass
class NicheBenchmark:
    """Benchmark metrics for a specific category or micro-niche."""
    name: str  # Category name or micro-niche name
    level: str  # 'category' or 'micro-niche'
    video_count: int
    channel_count: int = 0
    
    # Average metrics
    avg_face_rate: float = 0.0
    avg_text_rate: float = 0.0
    avg_brightness: float = 0.5
    avg_saturation: float = 0.5
    avg_title_length: float = 50.0
    avg_title_words: float = 8.0
    avg_has_number: float = 0.0
    avg_has_question: float = 0.0
    
    # Top 10% metrics (high performers)
    top10_face_rate: float = 0.0
    top10_text_rate: float = 0.0
    top10_brightness: float = 0.5
    top10_saturation: float = 0.5
    top10_title_length: float = 50.0
    top10_title_words: float = 8.0
    top10_has_number: float = 0.0
    top10_has_question: float = 0.0


@dataclass 
class BenchmarkResult:
    """Result of benchmark lookup with fallback info."""
    benchmark: NicheBenchmark
    used_fallback: bool = False
    fallback_reason: str = ""
    micro_niche_name: Optional[str] = None
    category_name: str = ""


class HierarchicalBenchmarkCalculator:
    """
    Calculates benchmarks with hierarchical fallback.
    
    Priority:
    1. Micro-niche (if 50+ channels)
    2. Category (fallback)
    """
    
    def __init__(self):
        self.category_benchmarks: Dict[str, NicheBenchmark] = {}
        self.microniche_benchmarks: Dict[int, NicheBenchmark] = {}  # niche_id -> benchmark
        self.microniche_channel_counts: Dict[int, int] = {}
        self._loaded = False
    
    def load_benchmarks(self):
        """Load all benchmarks from database."""
        if self._loaded:
            return
            
        logger.info("Loading hierarchical benchmarks...")
        
        with get_session() as session:
            # 1. Load category benchmarks
            self._load_category_benchmarks(session)
            
            # 2. Load micro-niche benchmarks (only for niches with 50+ channels)
            self._load_microniche_benchmarks(session)
        
        self._loaded = True
        logger.info(f"Loaded {len(self.category_benchmarks)} category benchmarks, "
                   f"{len(self.microniche_benchmarks)} micro-niche benchmarks")
    
    def _load_category_benchmarks(self, session):
        """Load benchmarks for all categories."""
        categories = session.query(
            Channel.primary_category
        ).filter(
            Channel.primary_category.isnot(None)
        ).group_by(
            Channel.primary_category
        ).having(
            func.count(Channel.channel_id) >= 10
        ).all()
        
        for (category,) in categories:
            benchmark = self._calculate_benchmark(
                session, 
                filter_column=Channel.primary_category,
                filter_value=category,
                name=category,
                level='category'
            )
            if benchmark:
                self.category_benchmarks[category] = benchmark
    
    def _load_microniche_benchmarks(self, session):
        """Load benchmarks for micro-niches with enough data."""
        # Get micro-niches with 50+ channels
        niche_counts = session.query(
            Niche.id,
            Niche.name,
            Niche.category,
            func.count(Channel.channel_id).label('channel_count')
        ).outerjoin(
            Channel, Niche.id == Channel.niche_id
        ).group_by(
            Niche.id, Niche.name, Niche.category
        ).having(
            func.count(Channel.channel_id) >= MIN_CHANNELS_FOR_MICRONICHE
        ).all()
        
        logger.info(f"Found {len(niche_counts)} micro-niches with {MIN_CHANNELS_FOR_MICRONICHE}+ channels")
        
        for niche_id, niche_name, category, channel_count in niche_counts:
            self.microniche_channel_counts[niche_id] = channel_count
            
            benchmark = self._calculate_benchmark(
                session,
                filter_column=Channel.niche_id,
                filter_value=niche_id,
                name=niche_name,
                level='micro-niche'
            )
            if benchmark:
                benchmark.channel_count = channel_count
                self.microniche_benchmarks[niche_id] = benchmark
    
    def _calculate_benchmark(self, session, filter_column, filter_value, 
                            name: str, level: str) -> Optional[NicheBenchmark]:
        """Calculate benchmarks for a specific filter."""
        
        results = session.query(
            Video.video_id,
            Video.view_count,
            Channel.avg_views_per_video,
            VideoFeatures.has_face,
            VideoFeatures.has_text,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).filter(and_(
            filter_column == filter_value,
            Video.view_count >= 100,
            Channel.avg_views_per_video > 0
        )).all()
        
        if len(results) < MIN_VIDEOS_FOR_BENCHMARK:
            return None
        
        # Calculate performance ratio for each video
        videos_with_perf = []
        for r in results:
            perf_ratio = r.view_count / r.avg_views_per_video if r.avg_views_per_video > 0 else 1
            videos_with_perf.append({
                'perf_ratio': perf_ratio,
                'has_face': 1 if r.has_face else 0,
                'has_text': 1 if r.has_text else 0,
                'brightness': r.brightness or 0.5,
                'saturation': r.saturation or 0.5,
                'title_length': r.title_char_length or 50,
                'title_words': r.title_word_count or 8,
                'has_number': 1 if r.title_has_number else 0,
                'has_question': 1 if r.title_has_question else 0,
            })
        
        # Sort by performance
        videos_with_perf.sort(key=lambda x: x['perf_ratio'], reverse=True)
        
        # Get top 10%
        top_10_pct_count = max(10, len(videos_with_perf) // 10)
        top_10_pct = videos_with_perf[:top_10_pct_count]
        
        def avg(data, key):
            vals = [d[key] for d in data if d[key] is not None]
            return np.mean(vals) if vals else 0
        
        return NicheBenchmark(
            name=name,
            level=level,
            video_count=len(results),
            avg_face_rate=avg(videos_with_perf, 'has_face'),
            avg_text_rate=avg(videos_with_perf, 'has_text'),
            avg_brightness=avg(videos_with_perf, 'brightness'),
            avg_saturation=avg(videos_with_perf, 'saturation'),
            avg_title_length=avg(videos_with_perf, 'title_length'),
            avg_title_words=avg(videos_with_perf, 'title_words'),
            avg_has_number=avg(videos_with_perf, 'has_number'),
            avg_has_question=avg(videos_with_perf, 'has_question'),
            top10_face_rate=avg(top_10_pct, 'has_face'),
            top10_text_rate=avg(top_10_pct, 'has_text'),
            top10_brightness=avg(top_10_pct, 'brightness'),
            top10_saturation=avg(top_10_pct, 'saturation'),
            top10_title_length=avg(top_10_pct, 'title_length'),
            top10_title_words=avg(top_10_pct, 'title_words'),
            top10_has_number=avg(top_10_pct, 'has_number'),
            top10_has_question=avg(top_10_pct, 'has_question'),
        )
    
    def get_benchmark(self, category: str, niche_id: Optional[int] = None) -> BenchmarkResult:
        """
        Get benchmark with hierarchical fallback.
        
        Args:
            category: Primary category (e.g., 'gaming')
            niche_id: Optional micro-niche ID
        
        Returns:
            BenchmarkResult with benchmark and fallback info
        """
        if not self._loaded:
            self.load_benchmarks()
        
        # Try micro-niche first
        if niche_id and niche_id in self.microniche_benchmarks:
            benchmark = self.microniche_benchmarks[niche_id]
            return BenchmarkResult(
                benchmark=benchmark,
                used_fallback=False,
                micro_niche_name=benchmark.name,
                category_name=category
            )
        
        # Check if niche exists but is too small
        if niche_id and niche_id not in self.microniche_benchmarks:
            channel_count = self.microniche_channel_counts.get(niche_id, 0)
            if channel_count > 0 and channel_count < MIN_CHANNELS_FOR_MICRONICHE:
                fallback_reason = f"Micro-niche has only {channel_count} channels (need {MIN_CHANNELS_FOR_MICRONICHE}+)"
            else:
                fallback_reason = "Micro-niche not found"
        else:
            fallback_reason = "No micro-niche specified"
        
        # Fall back to category
        if category in self.category_benchmarks:
            return BenchmarkResult(
                benchmark=self.category_benchmarks[category],
                used_fallback=True,
                fallback_reason=fallback_reason,
                category_name=category
            )
        
        # No benchmark available
        return BenchmarkResult(
            benchmark=NicheBenchmark(name="default", level="default", video_count=0),
            used_fallback=True,
            fallback_reason="No category benchmark available",
            category_name=category
        )
    
    def compare_to_benchmark(self, benchmark: NicheBenchmark, user_metrics: dict) -> Dict[str, dict]:
        """
        Compare user's video metrics to benchmark.
        
        Returns dict of comparisons with gaps.
        """
        if benchmark.video_count == 0:
            return {}
        
        comparisons = {}
        
        # Face comparison
        user_face = user_metrics.get('has_face', False)
        comparisons['face'] = {
            'user': 'Yes' if user_face else 'No',
            'category_avg': f"{benchmark.avg_face_rate*100:.0f}%",
            'top_10': f"{benchmark.top10_face_rate*100:.0f}%",
            'gap': 'below' if not user_face and benchmark.avg_face_rate > 0.5 else 'ok',
            'impact': f"+{(benchmark.top10_face_rate - benchmark.avg_face_rate)*100:.0f}% CTR" if benchmark.top10_face_rate > benchmark.avg_face_rate else None
        }
        
        # Text comparison
        user_text = user_metrics.get('has_text', False)
        comparisons['text'] = {
            'user': 'Yes' if user_text else 'No',
            'category_avg': f"{benchmark.avg_text_rate*100:.0f}%",
            'top_10': f"{benchmark.top10_text_rate*100:.0f}%",
            'gap': 'below' if not user_text and benchmark.top10_text_rate > 0.3 else 'ok',
            'impact': f"+{(benchmark.top10_text_rate - benchmark.avg_text_rate)*100:.0f}% CTR" if benchmark.top10_text_rate > benchmark.avg_text_rate else None
        }
        
        # Brightness comparison
        user_bright = user_metrics.get('brightness', 0.5)
        comparisons['brightness'] = {
            'user': f"{user_bright:.2f}",
            'category_avg': f"{benchmark.avg_brightness:.2f}",
            'top_10': f"{benchmark.top10_brightness:.2f}",
            'gap': 'below' if user_bright < benchmark.avg_brightness * 0.9 else 'ok',
            'improvement': f"+{(benchmark.top10_brightness - user_bright):.2f}" if user_bright < benchmark.top10_brightness else None
        }
        
        # Title length comparison
        user_title_len = user_metrics.get('title_length', 0)
        comparisons['title_length'] = {
            'user': f"{user_title_len} chars",
            'category_avg': f"{benchmark.avg_title_length:.0f} chars",
            'top_10': f"{benchmark.top10_title_length:.0f} chars",
            'gap': 'way_below' if user_title_len < benchmark.avg_title_length * 0.5 else ('below' if user_title_len < benchmark.avg_title_length * 0.8 else 'ok'),
            'chars_needed': int(benchmark.avg_title_length - user_title_len) if user_title_len < benchmark.avg_title_length else 0
        }
        
        # Number in title
        user_number = user_metrics.get('has_number', False)
        comparisons['has_number'] = {
            'user': 'Yes' if user_number else 'No',
            'category_avg': f"{benchmark.avg_has_number*100:.0f}%",
            'top_10': f"{benchmark.top10_has_number*100:.0f}%",
            'gap': 'below' if not user_number and benchmark.top10_has_number > 0.4 else 'ok',
        }
        
        # Question in title
        user_question = user_metrics.get('has_question', False)
        comparisons['has_question'] = {
            'user': 'Yes' if user_question else 'No',
            'category_avg': f"{benchmark.avg_has_question*100:.0f}%",
            'top_10': f"{benchmark.top10_has_question*100:.0f}%",
            'gap': 'below' if not user_question and benchmark.top10_has_question > 0.2 else 'ok',
        }
        
        return comparisons


# Backward compatibility - keep old class name working
class NicheBenchmarkCalculator(HierarchicalBenchmarkCalculator):
    """Backward compatible alias - returns NicheBenchmark directly."""
    pass


# Singleton instance
_benchmark_calculator = None

def get_benchmark_calculator() -> NicheBenchmarkCalculator:
    global _benchmark_calculator
    if _benchmark_calculator is None:
        _benchmark_calculator = NicheBenchmarkCalculator()
    return _benchmark_calculator


def get_hierarchical_calculator() -> HierarchicalBenchmarkCalculator:
    """Get the hierarchical calculator (same instance, full interface)."""
    return get_benchmark_calculator()

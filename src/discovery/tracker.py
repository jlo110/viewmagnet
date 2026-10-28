"""Distribution tracker for channel discovery."""
from dataclasses import dataclass
from typing import Dict, List, Tuple
import structlog

from src.config import CATEGORY_DISTRIBUTION, SIZE_DISTRIBUTION

logger = structlog.get_logger()


@dataclass
class CategoryProgress:
    """Progress for a single category."""
    category: str
    target: int
    current: int
    by_size: Dict[str, int]
    
    @property
    def remaining(self) -> int:
        return max(0, self.target - self.current)
    
    @property
    def progress_pct(self) -> float:
        if self.target == 0:
            return 100.0
        return min(100.0, (self.current / self.target) * 100)
    
    @property
    def is_complete(self) -> bool:
        return self.current >= self.target


class DistributionTracker:
    """
    Tracks channel collection progress against target distribution.
    
    Ensures we collect channels according to the target distribution:
    - Category distribution (gaming: 1200, commentary: 600, etc.)
    - Size distribution within each category (micro: 25%, small: 30%, etc.)
    """
    
    def __init__(self):
        """Initialize the tracker with target distributions."""
        # Category -> Size -> count
        self._collected: Dict[str, Dict[str, int]] = {}
        
        # Initialize structure
        for category in CATEGORY_DISTRIBUTION:
            self._collected[category] = {size: 0 for size in SIZE_DISTRIBUTION}
        
        self._total_collected = 0
    
    def get_size_tier(self, subscriber_count: int) -> str:
        """
        Determine size tier from subscriber count.
        
        Args:
            subscriber_count: Number of subscribers
            
        Returns:
            Size tier name (micro, small, medium, large, top)
        """
        for tier_name, tier_info in SIZE_DISTRIBUTION.items():
            min_subs, max_subs = tier_info["range"]
            if min_subs <= subscriber_count < max_subs:
                return tier_name
        
        # Default to the highest tier if above all ranges
        return "top"
    
    def record_channel(self, category: str, subscriber_count: int) -> bool:
        """
        Record a collected channel.
        
        Args:
            category: The channel's category
            subscriber_count: Number of subscribers
            
        Returns:
            True if the channel was needed (fills a gap), False if we already have enough
        """
        if category not in self._collected:
            logger.warning("unknown_category", category=category)
            category = "other"
        
        size_tier = self.get_size_tier(subscriber_count)
        
        # Check if we need more channels in this slot
        target_for_category = CATEGORY_DISTRIBUTION[category]
        target_for_size = int(target_for_category * SIZE_DISTRIBUTION[size_tier]["percentage"])
        current_for_size = self._collected[category][size_tier]
        
        if current_for_size >= target_for_size:
            logger.debug(
                "slot_full",
                category=category,
                size_tier=size_tier,
                current=current_for_size,
                target=target_for_size
            )
            return False
        
        # Record the channel
        self._collected[category][size_tier] += 1
        self._total_collected += 1
        
        return True
    
    def should_collect(self, category: str, subscriber_count: int) -> bool:
        """
        Check if we should collect a channel with given attributes.
        
        Args:
            category: The channel's category
            subscriber_count: Number of subscribers
            
        Returns:
            True if we need more channels in this slot
        """
        if category not in self._collected:
            category = "other"
        
        size_tier = self.get_size_tier(subscriber_count)
        
        target_for_category = CATEGORY_DISTRIBUTION[category]
        target_for_size = int(target_for_category * SIZE_DISTRIBUTION[size_tier]["percentage"])
        current_for_size = self._collected[category][size_tier]
        
        return current_for_size < target_for_size
    
    def get_category_progress(self, category: str) -> CategoryProgress:
        """Get detailed progress for a category."""
        target = CATEGORY_DISTRIBUTION.get(category, 0)
        by_size = self._collected.get(category, {})
        current = sum(by_size.values())
        
        return CategoryProgress(
            category=category,
            target=target,
            current=current,
            by_size=dict(by_size)
        )
    
    def get_gaps(self) -> List[Tuple[str, str, int]]:
        """
        Get list of category/size combinations that need more channels.
        
        Returns:
            List of (category, size_tier, needed_count) tuples, sorted by need
        """
        gaps = []
        
        for category, target_count in CATEGORY_DISTRIBUTION.items():
            for size_tier, size_info in SIZE_DISTRIBUTION.items():
                target = int(target_count * size_info["percentage"])
                current = self._collected[category][size_tier]
                needed = target - current
                
                if needed > 0:
                    gaps.append((category, size_tier, needed))
        
        # Sort by most needed first
        gaps.sort(key=lambda x: x[2], reverse=True)
        return gaps
    
    def get_priority_categories(self, top_n: int = 3) -> List[str]:
        """
        Get categories that need the most channels.
        
        Args:
            top_n: Number of categories to return
            
        Returns:
            List of category names, prioritized by need
        """
        category_needs = []
        
        for category in CATEGORY_DISTRIBUTION:
            progress = self.get_category_progress(category)
            category_needs.append((category, progress.remaining))
        
        category_needs.sort(key=lambda x: x[1], reverse=True)
        return [cat for cat, _ in category_needs[:top_n]]
    
    def get_summary(self) -> Dict:
        """Get a summary of collection progress."""
        total_target = sum(CATEGORY_DISTRIBUTION.values())
        
        categories = {}
        for category in CATEGORY_DISTRIBUTION:
            progress = self.get_category_progress(category)
            categories[category] = {
                "target": progress.target,
                "current": progress.current,
                "progress_pct": round(progress.progress_pct, 1),
                "by_size": progress.by_size,
            }
        
        return {
            "total_target": total_target,
            "total_collected": self._total_collected,
            "total_progress_pct": round((self._total_collected / total_target) * 100, 1),
            "categories": categories,
            "top_gaps": self.get_gaps()[:10],
        }
    
    def print_progress(self) -> None:
        """Print a formatted progress report."""
        summary = self.get_summary()
        
        print("\n" + "=" * 60)
        print(f"Channel Collection Progress: {summary['total_collected']}/{summary['total_target']} ({summary['total_progress_pct']}%)")
        print("=" * 60)
        
        for category, data in summary["categories"].items():
            bar_width = 30
            filled = int(bar_width * data["progress_pct"] / 100)
            bar = "█" * filled + "░" * (bar_width - filled)
            print(f"\n{category}:")
            print(f"  [{bar}] {data['current']}/{data['target']} ({data['progress_pct']}%)")
            
            size_parts = []
            for size, count in data["by_size"].items():
                target = int(data["target"] * SIZE_DISTRIBUTION[size]["percentage"])
                size_parts.append(f"{size}:{count}/{target}")
            print(f"  {' | '.join(size_parts)}")
        
        print("\n" + "-" * 60)
        print("Top gaps to fill:")
        for category, size, needed in summary["top_gaps"][:5]:
            print(f"  - {category}/{size}: need {needed} more")
        print("=" * 60 + "\n")
    
    def load_from_database(self, session) -> None:
        """
        Load current progress from database.
        
        Args:
            session: SQLAlchemy session
        """
        from sqlalchemy import func
        from src.database.models import Channel
        
        # Query channel counts by category and size tier
        results = session.query(
            Channel.primary_category,
            Channel.size_tier,
            func.count(Channel.id)
        ).filter(
            Channel.is_active == True
        ).group_by(
            Channel.primary_category,
            Channel.size_tier
        ).all()
        
        # Reset and load
        for category in CATEGORY_DISTRIBUTION:
            self._collected[category] = {size: 0 for size in SIZE_DISTRIBUTION}
        self._total_collected = 0
        
        for category, size_tier, count in results:
            if category in self._collected and size_tier in self._collected[category]:
                self._collected[category][size_tier] = count
                self._total_collected += count
        
        logger.info("loaded_progress_from_db", total=self._total_collected)


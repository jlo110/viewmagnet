#!/usr/bin/env python3
"""
Main script for running channel discovery.

This script orchestrates the Week 1-2 channel discovery process:
1. Initialize database
2. Discover channels across all categories
3. Fill gaps in distribution
4. Report progress

Run with: python run_discovery.py
"""
import sys
import logging
from datetime import datetime

import structlog
from rich.console import Console
from rich.panel import Panel

# Configure logging
logging.basicConfig(level=logging.INFO)
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

from src.config import get_settings, CATEGORY_DISTRIBUTION
from src.database.connection import get_session, init_db
from src.youtube.client import YouTubeClient
from src.discovery.tracker import DistributionTracker
from src.discovery.collector import ChannelCollector
from src.discovery.storage import ChannelStorage

console = Console()
logger = structlog.get_logger()


def run_discovery_session(
    max_searches_per_run: int = 50,
    prioritize_gaps: bool = True,
) -> dict:
    """
    Run a single discovery session.
    
    Args:
        max_searches_per_run: Maximum API searches to perform
        prioritize_gaps: Focus on filling distribution gaps
        
    Returns:
        Session statistics
    """
    logger.info("starting_discovery_session")
    
    # Initialize components
    client = YouTubeClient()
    tracker = DistributionTracker()
    collector = ChannelCollector(youtube_client=client, tracker=tracker)
    
    session_stats = {
        "started_at": datetime.utcnow().isoformat(),
        "channels_found": 0,
        "channels_added": 0,
        "errors": 0,
        "categories_processed": [],
    }
    
    with get_session() as session:
        storage = ChannelStorage(session, tracker)
        
        # Load existing state
        tracker.load_from_database(session)
        collector.load_seen_channels(session)
        
        initial_count = len(collector._seen_channel_ids)
        logger.info("loaded_existing_state", existing_channels=initial_count)
        
        # Show current progress
        tracker.print_progress()
        
        # Check quota
        quota = client.get_quota_status()
        available_searches = quota["total_remaining"] // 100  # search costs 100 units
        
        if available_searches < 5:
            logger.warning("insufficient_quota", available=available_searches)
            console.print("[red]Insufficient API quota for discovery. Try again tomorrow.[/red]")
            return session_stats
        
        searches_to_do = min(max_searches_per_run, available_searches)
        logger.info("quota_status", available_searches=available_searches, planned=searches_to_do)
        
        if prioritize_gaps:
            # Focus on filling gaps
            results = collector.fill_gaps(max_total=searches_to_do * 10)  # ~10 channels per search
        else:
            # Collect across all categories
            results = collector.collect_all_categories(
                channels_per_category=searches_to_do * 10 // len(CATEGORY_DISTRIBUTION)
            )
        
        # Process and save results
        for slot, result in results.items():
            session_stats["channels_found"] += result.channels_found
            session_stats["channels_added"] += result.channels_added
            session_stats["errors"] += result.errors
            session_stats["categories_processed"].append(slot)
        
        # Show updated progress
        tracker.print_progress()
        
        session_stats["ended_at"] = datetime.utcnow().isoformat()
        session_stats["final_quota"] = client.get_quota_status()["total_remaining"]
    
    return session_stats


def main():
    """Main entry point."""
    console.print(Panel.fit(
        "[bold blue]ViewMagnet Channel Discovery[/bold blue]\n"
        "Week 1-2: Building the Benchmark Database",
        border_style="blue"
    ))
    
    # Check settings
    settings = get_settings()
    
    if not settings.youtube_api_keys:
        console.print("\n[red]Error: No YouTube API keys configured![/red]")
        console.print("Create a .env file with your API keys:")
        console.print("  YOUTUBE_API_KEY_1=your_key_here")
        console.print("  YOUTUBE_API_KEY_2=your_key_here  (optional)")
        sys.exit(1)
    
    console.print(f"\n[dim]Configured API keys: {len(settings.youtube_api_keys)}[/dim]")
    
    # Initialize database
    console.print("\n[bold]Step 1:[/bold] Initializing database...")
    try:
        init_db()
        console.print("[green]✓ Database ready[/green]")
    except Exception as e:
        console.print(f"[red]Database error: {e}[/red]")
        console.print("Make sure PostgreSQL is running and DATABASE_URL is configured.")
        sys.exit(1)
    
    # Run discovery
    console.print("\n[bold]Step 2:[/bold] Running channel discovery...")
    
    try:
        stats = run_discovery_session(
            max_searches_per_run=50,
            prioritize_gaps=True
        )
        
        console.print("\n[bold]Session Summary:[/bold]")
        console.print(f"  • Channels found: {stats['channels_found']}")
        console.print(f"  • Channels added: {stats['channels_added']}")
        console.print(f"  • Errors: {stats['errors']}")
        console.print(f"  • Categories processed: {len(stats['categories_processed'])}")
        
        if stats.get("final_quota"):
            console.print(f"  • Remaining quota: {stats['final_quota']} units")
        
        console.print("\n[green]✓ Discovery session complete![/green]")
        console.print("\n[dim]Run again to continue collecting channels.[/dim]")
        console.print("[dim]Use 'python -m src.cli progress' to check status.[/dim]")
        
    except Exception as e:
        console.print(f"\n[red]Error during discovery: {e}[/red]")
        logger.exception("discovery_error")
        sys.exit(1)


if __name__ == "__main__":
    main()


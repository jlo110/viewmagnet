"""CLI for ViewMagnet channel discovery."""
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
import structlog

# Configure structured logging with rich output
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

from sqlalchemy import Integer, func

from src.config import CATEGORY_DISTRIBUTION, SIZE_DISTRIBUTION
from src.database.connection import get_session, init_db
from src.database.models import Channel
from src.youtube.client import YouTubeClient
from src.youtube.quota import QuotaManager
from src.discovery.tracker import DistributionTracker
from src.discovery.collector import ChannelCollector
from src.discovery.storage import ChannelStorage

app = typer.Typer(help="ViewMagnet Channel Discovery CLI")
console = Console()


@app.command()
def init():
    """Initialize the database tables."""
    console.print("[bold blue]Initializing database...[/bold blue]")
    init_db()
    console.print("[bold green]✓ Database initialized successfully![/bold green]")


@app.command()
def quota():
    """Check YouTube API quota status."""
    try:
        quota_mgr = QuotaManager()
        status = quota_mgr.get_status()
        
        table = Table(title="YouTube API Quota Status")
        table.add_column("Key", style="cyan")
        table.add_column("Used", justify="right")
        table.add_column("Remaining", justify="right")
        table.add_column("Status", style="bold")
        
        for key_info in status["keys"]:
            status_icon = "✓" if not key_info["exhausted"] else "✗"
            status_style = "green" if not key_info["exhausted"] else "red"
            table.add_row(
                f"Key {key_info['index'] + 1}",
                str(key_info["used"]),
                str(key_info["remaining"]),
                f"[{status_style}]{status_icon}[/{status_style}]"
            )
        
        console.print(table)
        console.print(f"\n[bold]Total remaining:[/bold] {status['total_remaining']} units")
        console.print(f"[bold]Estimated searches available:[/bold] {quota_mgr.estimate_available_searches()}")
        
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        console.print("Make sure you have configured your YouTube API keys in .env")


@app.command()
def progress():
    """Show channel collection progress."""
    tracker = DistributionTracker()
    
    with get_session() as session:
        tracker.load_from_database(session)
    
    summary = tracker.get_summary()
    
    # Overall progress
    console.print(f"\n[bold]Overall Progress:[/bold] {summary['total_collected']}/{summary['total_target']} ({summary['total_progress_pct']}%)")
    
    # Category table
    table = Table(title="Progress by Category")
    table.add_column("Category", style="cyan")
    table.add_column("Current", justify="right")
    table.add_column("Target", justify="right")
    table.add_column("Progress", justify="right")
    table.add_column("Bar")
    
    for category, data in summary["categories"].items():
        bar_width = 20
        filled = int(bar_width * data["progress_pct"] / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        table.add_row(
            category,
            str(data["current"]),
            str(data["target"]),
            f"{data['progress_pct']}%",
            bar
        )
    
    console.print(table)
    
    # Gaps
    if summary["top_gaps"]:
        console.print("\n[bold yellow]Top Gaps to Fill:[/bold yellow]")
        for category, size, needed in summary["top_gaps"][:5]:
            console.print(f"  • {category}/{size}: need {needed} more channels")


@app.command()
def discover(
    category: str = typer.Option(None, "--category", "-c", help="Specific category to collect"),
    max_channels: int = typer.Option(100, "--max", "-m", help="Maximum channels to collect"),
    fill_gaps: bool = typer.Option(False, "--fill-gaps", "-g", help="Focus on filling distribution gaps"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Don't save to database"),
):
    """Discover and collect YouTube channels."""
    console.print("[bold blue]Starting channel discovery...[/bold blue]\n")
    
    try:
        client = YouTubeClient()
        tracker = DistributionTracker()
        
        with get_session() as session:
            # Load existing progress
            tracker.load_from_database(session)
            
            storage = ChannelStorage(session, tracker)
            collector = ChannelCollector(youtube_client=client, tracker=tracker, storage=storage)
            collector.load_seen_channels(session)
            
            console.print(f"[dim]Loaded {len(collector._seen_channel_ids)} existing channels[/dim]\n")
            
            if fill_gaps:
                console.print("[bold]Mode:[/bold] Filling distribution gaps")
                results = collector.fill_gaps(max_total=max_channels)
            elif category:
                if category not in CATEGORY_DISTRIBUTION:
                    console.print(f"[red]Unknown category: {category}[/red]")
                    console.print(f"Valid categories: {', '.join(CATEGORY_DISTRIBUTION.keys())}")
                    raise typer.Exit(1)
                console.print(f"[bold]Mode:[/bold] Collecting for {category}")
                results = {category: collector.collect_by_search(category, max_channels)}
            else:
                console.print("[bold]Mode:[/bold] Collecting all categories")
                results = collector.collect_all_categories(channels_per_category=max_channels // len(CATEGORY_DISTRIBUTION))
            
            # Show results
            table = Table(title="Discovery Results")
            table.add_column("Category/Slot", style="cyan")
            table.add_column("Found", justify="right")
            table.add_column("Added", justify="right", style="green")
            table.add_column("Skipped", justify="right", style="yellow")
            table.add_column("Errors", justify="right", style="red")
            
            total_added = 0
            for slot, result in results.items():
                table.add_row(
                    slot,
                    str(result.channels_found),
                    str(result.channels_added),
                    str(result.channels_skipped),
                    str(result.errors)
                )
                total_added += result.channels_added
            
            console.print(table)
            
            if not dry_run:
                console.print(f"\n[bold green]✓ Added {total_added} channels to database[/bold green]")
            else:
                console.print(f"\n[bold yellow]Dry run - would have added {total_added} channels[/bold yellow]")
            
            # Show quota status
            quota_status = client.get_quota_status()
            console.print(f"\n[dim]Remaining quota: {quota_status['total_remaining']} units[/dim]")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def stats():
    """Show collection statistics."""
    with get_session() as session:
        storage = ChannelStorage(session)
        stats = storage.get_statistics()
        
        console.print(f"\n[bold]Total Channels:[/bold] {stats['total_channels']}")
        
        if stats["by_category"]:
            table = Table(title="Channels by Category")
            table.add_column("Category", style="cyan")
            table.add_column("Count", justify="right")
            
            for category, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
                table.add_row(category, str(count))
            
            console.print(table)
        
        if stats["by_size"]:
            table = Table(title="Channels by Size Tier")
            table.add_column("Size Tier", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Target %", justify="right")
            
            for tier, count in stats["by_size"].items():
                target_pct = SIZE_DISTRIBUTION.get(tier, {}).get("percentage", 0) * 100
                table.add_row(tier, str(count), f"{target_pct}%")
            
            console.print(table)


@app.command()
def targets():
    """Show target distribution."""
    table = Table(title="Target Distribution (5,000 channels)")
    table.add_column("Category", style="cyan")
    table.add_column("Target", justify="right")
    table.add_column("Micro\n10-50K", justify="right")
    table.add_column("Small\n50-200K", justify="right")
    table.add_column("Medium\n200K-1M", justify="right")
    table.add_column("Large\n1-5M", justify="right")
    table.add_column("Top\n5M+", justify="right")
    
    for category, target in CATEGORY_DISTRIBUTION.items():
        row = [category, str(target)]
        for tier, info in SIZE_DISTRIBUTION.items():
            tier_target = int(target * info["percentage"])
            row.append(str(tier_target))
        table.add_row(*row)
    
    # Totals
    total = sum(CATEGORY_DISTRIBUTION.values())
    totals = ["[bold]TOTAL[/bold]", f"[bold]{total}[/bold]"]
    for tier, info in SIZE_DISTRIBUTION.items():
        tier_total = int(total * info["percentage"])
        totals.append(f"[bold]{tier_total}[/bold]")
    table.add_row(*totals)
    
    console.print(table)


@app.command()
def test_api():
    """Test YouTube API connection."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Testing API connection...", total=None)
        
        try:
            client = YouTubeClient()
            
            # Try a simple search
            result = client.search_channels("test", max_results=1)
            
            if result.get("items"):
                progress.update(task, description="[green]✓ API connection successful!")
                channel = result["items"][0]["snippet"]
                console.print(f"\nSample result: {channel.get('title', 'Unknown')}")
            else:
                progress.update(task, description="[yellow]⚠ API connected but no results")
                
        except Exception as e:
            progress.update(task, description=f"[red]✗ API connection failed: {e}")
            raise typer.Exit(1)


@app.command()
def collect_videos(
    max_channels: int = typer.Option(None, "--max", "-m", help="Maximum channels to process"),
    category: str = typer.Option(None, "--category", "-c", help="Only process this category"),
):
    """Collect videos for channels (Week 2-3)."""
    from src.videos.collector import VideoCollector
    
    console.print("[bold blue]Starting video collection...[/bold blue]\n")
    
    try:
        client = YouTubeClient()
        
        with get_session() as session:
            collector = VideoCollector(session, youtube_client=client)
            
            # Show current stats
            stats = collector.get_collection_stats()
            console.print(f"[dim]Channels to process: {stats['pending_channels']}/{stats['total_channels']}[/dim]")
            console.print(f"[dim]Videos already collected: {stats['total_videos']}[/dim]\n")
            
            if stats['pending_channels'] == 0:
                console.print("[green]✓ All channels already processed![/green]")
                return
            
            # Collect videos
            results = collector.collect_all(
                max_channels=max_channels,
                category=category
            )
            
            # Summary
            total_added = sum(r.videos_added for r in results)
            total_errors = sum(r.errors for r in results)
            
            console.print(f"\n[bold green]✓ Processed {len(results)} channels[/bold green]")
            console.print(f"  Videos added: {total_added}")
            console.print(f"  Errors: {total_errors}")
            
            # Updated stats
            stats = collector.get_collection_stats()
            console.print(f"\n[bold]Total videos in database:[/bold] {stats['total_videos']}")
            console.print(f"[bold]Channels processed:[/bold] {stats['processed_channels']}/{stats['total_channels']} ({stats['progress_pct']}%)")
            
            # Quota status
            quota_status = client.get_quota_status()
            console.print(f"\n[dim]Remaining quota: {quota_status['total_remaining']} units[/dim]")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def video_stats():
    """Show video collection statistics."""
    from src.videos.collector import VideoCollector
    from src.database.models import Channel
    from sqlalchemy import func
    
    with get_session() as session:
        collector = VideoCollector(session)
        stats = collector.get_collection_stats()
        
        console.print("\n[bold]Video Collection Progress[/bold]")
        console.print(f"  Channels processed: {stats['processed_channels']}/{stats['total_channels']} ({stats['progress_pct']}%)")
        console.print(f"  Channels remaining: {stats['pending_channels']}")
        console.print(f"  Total videos collected: {stats['total_videos']}")
        
        if stats['processed_channels'] > 0:
            avg_videos = stats['total_videos'] / stats['processed_channels']
            console.print(f"  Average videos per channel: {avg_videos:.1f}")
        
        # Show by category
        results = session.query(
            Channel.primary_category,
            func.count(Channel.id).label('total'),
            func.sum(Channel.videos_collected.cast(Integer)).label('processed')
        ).group_by(Channel.primary_category).all()
        
        if results:
            table = Table(title="Progress by Category")
            table.add_column("Category", style="cyan")
            table.add_column("Processed", justify="right")
            table.add_column("Total", justify="right")
            table.add_column("Progress", justify="right")
            
            for cat, total, processed in results:
                processed = processed or 0
                pct = (processed / total * 100) if total else 0
                table.add_row(cat, str(processed), str(total), f"{pct:.0f}%")
            
            console.print(table)


@app.command()
def extract_features(
    max_videos: int = typer.Option(None, "--max", "-m", help="Maximum videos to process"),
    skip_thumbnails: bool = typer.Option(False, "--skip-thumbnails", "-s", help="Skip thumbnail download"),
    enable_faces: bool = typer.Option(False, "--faces", "-f", help="Enable face detection (requires opencv)"),
    enable_emotions: bool = typer.Option(False, "--emotions", "-e", help="Enable face emotion detection (requires deepface)"),
):
    """Extract features from videos (Week 3-4)."""
    from src.features.extractor import FeatureExtractor
    
    console.print("[bold blue]Starting feature extraction...[/bold blue]\n")
    
    try:
        with get_session() as session:
            extractor = FeatureExtractor(
                session,
                enable_face_detection=enable_faces,
                enable_emotion_detection=enable_emotions,
                enable_thumbnail_download=not skip_thumbnails,
            )
            
            # Show current stats
            stats = extractor.get_extraction_stats()
            console.print(f"[dim]Videos to process: {stats['pending_videos']}/{stats['total_videos']}[/dim]")
            console.print(f"[dim]Already extracted: {stats['extracted_videos']}[/dim]\n")
            
            if stats['pending_videos'] == 0:
                console.print("[green]✓ All videos already processed![/green]")
                return
            
            # Extract features
            results = extractor.extract_batch(
                max_videos=max_videos,
                skip_thumbnails=skip_thumbnails,
            )
            
            # Summary
            title_ok = sum(1 for r in results if r.title_extracted)
            thumb_ok = sum(1 for r in results if r.thumbnail_extracted)
            meta_ok = sum(1 for r in results if r.metadata_extracted)
            errors = sum(1 for r in results if r.error)
            
            console.print(f"\n[bold green]✓ Processed {len(results)} videos[/bold green]")
            console.print(f"  Title features: {title_ok}")
            console.print(f"  Thumbnail features: {thumb_ok}")
            console.print(f"  Metadata features: {meta_ok}")
            console.print(f"  Errors: {errors}")
            
            # Updated stats
            stats = extractor.get_extraction_stats()
            console.print(f"\n[bold]Progress:[/bold] {stats['extracted_videos']}/{stats['total_videos']} ({stats['progress_pct']}%)")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def feature_stats():
    """Show feature extraction statistics."""
    from src.features.extractor import FeatureExtractor
    from src.database.models import VideoFeatures
    from sqlalchemy import func
    
    with get_session() as session:
        extractor = FeatureExtractor(session)
        stats = extractor.get_extraction_stats()
        
        console.print("\n[bold]Feature Extraction Progress[/bold]")
        console.print(f"  Videos processed: {stats['extracted_videos']}/{stats['total_videos']} ({stats['progress_pct']}%)")
        console.print(f"  Videos remaining: {stats['pending_videos']}")
        console.print(f"  Title features: {stats['titles_processed']}")
        console.print(f"  Thumbnail features: {stats['thumbnails_processed']}")
        
        # Hook type distribution
        hook_counts = session.query(
            VideoFeatures.title_hook_type,
            func.count(VideoFeatures.id)
        ).filter(
            VideoFeatures.title_hook_type.isnot(None)
        ).group_by(VideoFeatures.title_hook_type).all()
        
        if hook_counts:
            console.print("\n[bold]Hook Type Distribution:[/bold]")
            table = Table()
            table.add_column("Hook Type", style="cyan")
            table.add_column("Count", justify="right")
            
            for hook_type, count in sorted(hook_counts, key=lambda x: x[1], reverse=True):
                table.add_row(hook_type, str(count))
            
            console.print(table)


# ===== PART 4: TEMPORAL TRACKING COMMANDS =====

@app.command()
def setup_tracking(
    target: int = typer.Option(10000, "--target", "-t", help="Target number of channels to track"),
    min_videos: int = typer.Option(2, "--min-videos", "-m", help="Minimum recent videos required"),
    all_channels: bool = typer.Option(False, "--all", "-a", help="Track ALL channels regardless of activity"),
):
    """Set up channel tracking for temporal data (Part 4)."""
    from src.tracking.channel_selector import ChannelSelector
    
    console.print("[bold blue]Setting up channel tracking...[/bold blue]\n")
    
    try:
        with get_session() as session:
            selector = ChannelSelector(session)
            
            # Show current stats
            stats = selector.get_tracking_stats()
            console.print(f"[dim]Currently tracking: {stats['active_tracked_channels']} channels[/dim]\n")
            
            if all_channels:
                # Track ALL channels in database
                console.print("[yellow]Adding ALL channels to tracking (ignoring activity filter)...[/yellow]")
                added = selector.track_all_channels()
            else:
                # Find and add active channels only
                added = selector.select_for_tracking(
                    target_count=target,
                    min_videos=min_videos,
                )
            
            # Updated stats
            stats = selector.get_tracking_stats()
            console.print(f"\n[bold green]✓ Added {added} channels to tracking[/bold green]")
            console.print(f"[bold]Total tracked:[/bold] {stats['active_tracked_channels']} channels")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def check_new_videos(
    max_channels: int = typer.Option(None, "--max", "-m", help="Maximum channels to check"),
):
    """Check tracked channels for new uploads."""
    from src.tracking.video_tracker import VideoTracker
    
    console.print("[bold blue]Checking for new videos...[/bold blue]\n")
    
    try:
        client = YouTubeClient()
        
        with get_session() as session:
            tracker = VideoTracker(session, youtube_client=client)
            
            result = tracker.check_for_new_videos(max_channels=max_channels)
            
            console.print("\n[bold green]✓ Check complete[/bold green]")
            console.print(f"  Channels checked: {result.channels_checked}")
            console.print(f"  New videos found: {result.new_videos_found}")
            console.print(f"  Errors: {result.errors}")
            
            # Quota status
            quota = client.get_quota_status()
            console.print(f"\n[dim]Remaining quota: {quota['total_remaining']} units[/dim]")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def collect_snapshots(
    max_videos: int = typer.Option(None, "--max", "-m", help="Maximum videos to process"),
):
    """Collect performance snapshots for tracked videos."""
    from src.tracking.video_tracker import VideoTracker
    
    console.print("[bold blue]Collecting video snapshots...[/bold blue]\n")
    
    try:
        client = YouTubeClient()
        
        with get_session() as session:
            tracker = VideoTracker(session, youtube_client=client)
            
            result = tracker.collect_snapshots(max_videos=max_videos)
            
            console.print("\n[bold green]✓ Collection complete[/bold green]")
            console.print(f"  Snapshots collected: {result.snapshots_collected}")
            console.print(f"  Errors: {result.errors}")
            
            # Show stats
            stats = tracker.get_tracking_stats()
            console.print("\n[bold]Tracking Progress:[/bold]")
            console.print(f"  Active videos: {stats['active_tracking']}")
            console.print(f"  Complete: {stats['complete']}")
            console.print(f"  Total snapshots: {stats['total_snapshots']}")
            
            # Quota status
            quota = client.get_quota_status()
            console.print(f"\n[dim]Remaining quota: {quota['total_remaining']} units[/dim]")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def tracking_stats():
    """Show temporal tracking statistics."""
    from src.tracking.channel_selector import ChannelSelector
    from src.tracking.video_tracker import VideoTracker
    
    with get_session() as session:
        channel_selector = ChannelSelector(session)
        video_tracker = VideoTracker(session)
        
        channel_stats = channel_selector.get_tracking_stats()
        video_stats = video_tracker.get_tracking_stats()
        
        console.print("\n[bold]Temporal Tracking Status (Part 4)[/bold]")
        console.print("\n[cyan]Tracked Channels:[/cyan]")
        console.print(f"  Total: {channel_stats['total_tracked_channels']}")
        console.print(f"  Active: {channel_stats['active_tracked_channels']}")
        
        console.print("\n[cyan]Tracked Videos:[/cyan]")
        console.print(f"  Total: {video_stats['total_tracked_videos']}")
        console.print(f"  Active tracking: {video_stats['active_tracking']}")
        console.print(f"  Complete (30d): {video_stats['complete']}")
        
        console.print("\n[cyan]Snapshots:[/cyan]")
        console.print(f"  Total: {video_stats['total_snapshots']}")
        
        if video_stats['by_checkpoint']:
            table = Table(title="Snapshots by Checkpoint")
            table.add_column("Checkpoint", style="cyan")
            table.add_column("Count", justify="right")
            
            for cp in ['1h', '6h', '24h', '3d', '7d', '14d', '30d']:
                count = video_stats['by_checkpoint'].get(cp, 0)
                table.add_row(cp, str(count))
            
            console.print(table)


# ============================================================================
# NICHE CLUSTERING COMMANDS (Week 4-5)
# ============================================================================

@app.command()
def cluster_niches():
    """Cluster channels into micro-niches (Week 4-5)."""
    from src.clustering.clusterer import NicheClusterer
    
    console.print("[bold blue]🔬 Clustering channels into micro-niches...[/bold blue]\n")
    
    try:
        with get_session() as session:
            # First, check if niches already exist
            from src.database.models import Niche
            existing = session.query(func.count(Niche.id)).scalar()
            if existing > 0:
                console.print(f"[yellow]⚠ Found {existing} existing niches. Clearing them first...[/yellow]")
                session.query(Niche).delete()
                session.query(Channel).update({Channel.niche_id: None})
                session.commit()
                console.print("[green]✓ Cleared existing niches[/green]\n")
            
            clusterer = NicheClusterer(session)
            
            # Get category count first
            categories = session.query(
                Channel.primary_category,
                func.count(Channel.id)
            ).filter(
                Channel.is_active == True
            ).group_by(
                Channel.primary_category
            ).all()
            
            valid_categories = [(c, n) for c, n in categories if c and n >= 5]
            total_channels = sum(n for _, n in valid_categories)
            
            console.print(f"[dim]Found {len(valid_categories)} categories with {total_channels} channels[/dim]\n")
            
            # Progress tracking with rich
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                
                current_task = progress.add_task("[cyan]Starting...", total=None)
                
                def update_progress(stage: str, current: int, total: int, message: str):
                    progress.update(current_task, description=f"[cyan]{message}")
                
                # Cluster all categories with progress
                all_niches = clusterer.cluster_all_categories(progress_callback=update_progress)
            
            total = sum(len(niches) for niches in all_niches.values())
            console.print(f"\n[bold green]✓ Created {total} micro-niches across {len(all_niches)} categories[/bold green]\n")
            
            # Show summary
            table = Table(title="Niches by Category")
            table.add_column("Category", style="cyan")
            table.add_column("Niches", justify="right")
            table.add_column("Channels", justify="right")
            table.add_column("Top Niche", style="dim")
            
            for category, niches in sorted(all_niches.items()):
                total_channels_in_cat = sum(n.channel_count for n in niches)
                top_niche = niches[0].name if niches else "-"
                # Remove category prefix from top niche name for display
                display_name = top_niche.replace(f"{category} - ", "")[:30]
                table.add_row(
                    category, 
                    str(len(niches)), 
                    str(total_channels_in_cat),
                    display_name
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def calculate_benchmarks():
    """Calculate performance benchmarks for each niche."""
    from src.clustering.benchmarks import NicheBenchmarks
    
    console.print("[bold blue]📊 Calculating niche benchmarks...[/bold blue]\n")
    
    try:
        with get_session() as session:
            calculator = NicheBenchmarks(session)
            
            benchmarks = calculator.calculate_all_benchmarks()
            
            console.print(f"\n[bold green]✓ Calculated benchmarks for {len(benchmarks)} niches[/bold green]\n")
            
            # Show top niches by engagement
            table = Table(title="Top Niches by Engagement")
            table.add_column("Niche", style="cyan")
            table.add_column("Channels", justify="right")
            table.add_column("Avg Views", justify="right")
            table.add_column("Engagement", justify="right")
            table.add_column("Face Rate", justify="right")
            
            sorted_benchmarks = sorted(
                benchmarks, 
                key=lambda b: b.avg_engagement_rate, 
                reverse=True
            )[:15]
            
            for b in sorted_benchmarks:
                table.add_row(
                    b.niche_name[:35],
                    str(b.channel_count),
                    f"{b.avg_views:,.0f}",
                    f"{b.avg_engagement_rate:.2%}",
                    f"{b.face_rate:.0%}",
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def niche_stats():
    """Show niche clustering statistics."""
    from src.database.models import Niche
    
    console.print("[bold blue]📊 Niche Statistics[/bold blue]\n")
    
    try:
        with get_session() as session:
            # Overall stats
            total_niches = session.query(func.count(Niche.id)).scalar()
            total_channels_assigned = session.query(func.count(Channel.id)).filter(
                Channel.niche_id.isnot(None)
            ).scalar()
            total_channels = session.query(func.count(Channel.id)).scalar()
            
            console.print(f"[cyan]Total niches:[/cyan] {total_niches}")
            console.print(f"[cyan]Channels assigned:[/cyan] {total_channels_assigned}/{total_channels}")
            
            if total_niches == 0:
                console.print("\n[yellow]No niches created yet. Run 'cluster-niches' first.[/yellow]")
                return
            
            # By category
            by_category = session.query(
                Niche.category,
                func.count(Niche.id),
                func.sum(Niche.channel_count)
            ).group_by(Niche.category).all()
            
            table = Table(title="Niches by Category")
            table.add_column("Category", style="cyan")
            table.add_column("Niches", justify="right")
            table.add_column("Channels", justify="right")
            
            for cat, niche_count, channel_count in sorted(by_category):
                table.add_row(cat, str(niche_count), str(channel_count or 0))
            
            console.print("\n")
            console.print(table)
            
            # Show largest niches
            largest = session.query(Niche).order_by(
                Niche.channel_count.desc()
            ).limit(10).all()
            
            table2 = Table(title="Largest Niches")
            table2.add_column("Niche", style="cyan")
            table2.add_column("Category", style="dim")
            table2.add_column("Channels", justify="right")
            table2.add_column("Avg Subs", justify="right")
            
            for n in largest:
                table2.add_row(
                    n.name[:40],
                    n.category,
                    str(n.channel_count),
                    f"{n.avg_subscribers:,.0f}" if n.avg_subscribers else "-"
                )
            
            console.print("\n")
            console.print(table2)
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


# ============================================================================
# ML MODEL COMMANDS
# ============================================================================

@app.command()
def train_thumbnail_model(
    min_views: int = typer.Option(100, "--min-views", help="Minimum views to include samples"),
    limit: int = typer.Option(None, "--limit", "-l", help="Limit training samples"),
):
    """Train the thumbnail performance predictor model."""
    from src.ml.thumbnail_predictor import ThumbnailPredictor
    
    console.print("[bold blue]🧠 Training Thumbnail Performance Predictor...[/bold blue]\n")
    
    try:
        predictor = ThumbnailPredictor()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Preparing data and training model...", total=None)
            
            result = predictor.train(min_views=min_views, limit=limit)
        
        console.print("\n[bold green]✓ Model trained successfully![/bold green]\n")
        
        # Show results
        console.print("[cyan]Training Results:[/cyan]")
        console.print(f"  Samples used: {result.samples_used:,}")
        console.print(f"  Validation RMSE: {result.val_rmse:.4f}")
        console.print(f"  Validation MAE: {result.val_mae:.4f}")
        console.print(f"  Validation R²: {result.val_r2:.4f}")
        
        # Feature importance
        console.print("\n[cyan]Top Feature Importance:[/cyan]")
        table = Table()
        table.add_column("Feature", style="cyan")
        table.add_column("Importance", justify="right")
        
        for i, (feature, importance) in enumerate(result.feature_importance.items()):
            if i >= 10:
                break
            table.add_row(feature, f"{importance:,.0f}")
        
        console.print(table)
        
        console.print("\n[dim]Model saved to models/thumbnail_predictor.pkl[/dim]")
        
    except ImportError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        console.print("[yellow]Install LightGBM: pip install lightgbm[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def score_thumbnail(
    image_path: str = typer.Argument(..., help="Path to thumbnail image"),
    niche: str = typer.Option(None, "--niche", "-n", help="Niche for context"),
    size_tier: str = typer.Option("small", "--size", "-s", help="Channel size tier"),
):
    """Score a thumbnail and get improvement suggestions."""
    from src.ml.thumbnail_predictor import ThumbnailPredictor
    from src.features.thumbnail_analyzer import ThumbnailAnalyzer
    from pathlib import Path
    
    console.print("[bold blue]📸 Analyzing Thumbnail...[/bold blue]\n")
    
    # Check file exists
    path = Path(image_path)
    if not path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {image_path}")
        raise typer.Exit(1)
    
    try:
        # Load predictor
        predictor = ThumbnailPredictor()
        if not predictor.is_trained():
            console.print("[bold red]Error:[/bold red] Model not trained. Run 'train-thumbnail-model' first.")
            raise typer.Exit(1)
        
        predictor.load()
        
        # Analyze thumbnail
        console.print("[dim]Extracting thumbnail features...[/dim]")
        analyzer = ThumbnailAnalyzer(enable_face_detection=True, enable_emotion_detection=True)
        
        # Read and analyze image
        
        with open(path, 'rb') as f:
            image_data = f.read()
        
        features = analyzer.analyze(image_data)
        
        if not features:
            console.print("[bold red]Error:[/bold red] Could not analyze thumbnail")
            raise typer.Exit(1)
        
        # Convert hex color to RGB
        def hex_to_rgb(hex_color):
            if not hex_color or len(hex_color) < 6:
                return (128, 128, 128)
            try:
                hex_color = hex_color.lstrip('#')
                return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
            except:
                return (128, 128, 128)
        
        r, g, b = hex_to_rgb(features.dominant_color_1)
        
        # Prepare features dict
        feature_dict = {
            'face_count': features.face_count,
            'has_face': features.has_face,
            'face_area_ratio': features.face_area_ratio or 0,
            'brightness': features.brightness or 0.5,
            'saturation': features.saturation or 0.5,
            'contrast': features.contrast or 0.5,
            'edge_density': features.edge_density or 0.5,
            'composition_score': features.composition_score or 0.5,
            'dominant_color_r': r,
            'dominant_color_g': g,
            'dominant_color_b': b,
            'face_emotion_primary': features.face_emotion_primary,
            'face_emotion_intensity': features.face_emotion_intensity or 0,
            'size_tier': size_tier,
            'niche_encoded': -1,  # Unknown niche
            'category_encoded': 0,
            'subscriber_count': 10000,  # Default
        }
        
        # Get prediction
        result = predictor.predict(feature_dict)
        
        # Display results
        console.print("\n")
        
        # Score with color coding
        if result.score >= 70:
            score_color = "green"
            score_emoji = "🔥"
        elif result.score >= 50:
            score_color = "yellow"
            score_emoji = "👍"
        else:
            score_color = "red"
            score_emoji = "⚠️"
        
        console.print(f"[bold {score_color}]{score_emoji} SCORE: {result.score:.0f}/100[/bold {score_color}]")
        console.print(f"[dim]Predicted performance: {result.performance_ratio:.2f}x channel average[/dim]")
        console.print(f"[dim]Better than {result.percentile}% of thumbnails[/dim]")
        
        # Feature analysis
        console.print("\n[cyan]📊 Feature Analysis:[/cyan]")
        table = Table(show_header=False)
        table.add_column("Feature", style="dim")
        table.add_column("Value")
        
        table.add_row("Faces detected", f"{features.face_count}" + (" ✓" if features.has_face else ""))
        table.add_row("Brightness", f"{(features.brightness or 0.5)*100:.0f}%")
        table.add_row("Saturation", f"{(features.saturation or 0.5)*100:.0f}%")
        table.add_row("Composition", f"{(features.composition_score or 0.5)*100:.0f}%")
        if features.face_emotion_primary:
            table.add_row("Emotion", f"{features.face_emotion_primary} ({(features.face_emotion_intensity or 0)*100:.0f}%)")
        
        console.print(table)
        
        # Suggestions
        if result.suggestions:
            console.print("\n[cyan]💡 Suggestions to Improve:[/cyan]")
            for suggestion in result.suggestions:
                console.print(f"  {suggestion}")
        
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def train_improved_model(
    min_views: int = typer.Option(100, "--min-views", help="Minimum views to include"),
    limit: int = typer.Option(None, "--limit", "-l", help="Limit training samples"),
):
    """Train the improved predictor with ALL features (guide spec)."""
    from src.ml.improved_predictor import ImprovedPredictor
    
    console.print("[bold blue]🧠 Training Improved Performance Predictor...[/bold blue]")
    console.print("[dim]Using: Thumbnail + Text(OCR) + Title + Niche-Relative + Context[/dim]")
    console.print("[dim]Features: 45 total (as specified in guide)[/dim]\n")
    
    try:
        predictor = ImprovedPredictor()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Training model...", total=None)
            result = predictor.train(min_views=min_views, limit=limit)
        
        console.print("\n[bold green]✓ Model trained![/bold green]\n")
        
        # Results
        console.print("[cyan]Training Results:[/cyan]")
        console.print(f"  Samples: {result.samples:,}")
        console.print(f"  Features: {result.features_used}")
        console.print(f"  Train R²: {result.train_r2:.4f}")
        console.print(f"  [bold]Validation R²: {result.val_r2:.4f}[/bold]")
        console.print(f"  Validation RMSE: {result.val_rmse:.4f}")
        
        # Comparison
        console.print("\n[cyan]R² Comparison:[/cyan]")
        console.print("  Thumbnail only:  ~0.14")
        console.print("  Combined model:  ~0.25")
        console.print(f"  [bold]Improved model: {result.val_r2:.2f}[/bold]")
        
        # Guide target
        console.print("\n[cyan]Guide Target: 60-68% accuracy[/cyan]")
        accuracy_pct = (1 - result.val_mae) * 100
        console.print(f"  Current accuracy: ~{accuracy_pct:.0f}%")
        
        # Feature importance
        console.print("\n[cyan]Top Feature Importance:[/cyan]")
        table = Table()
        table.add_column("Feature", style="cyan")
        table.add_column("Importance", justify="right")
        table.add_column("Type", style="dim")
        
        niche_features = ['niche_', 'similarity']
        thumb_features = ['face', 'has_text', 'text_', 'bright', 'satur', 'contrast', 'edge', 'composition', 'color']
        title_features = ['title_']
        
        for i, (feature, importance) in enumerate(result.feature_importance.items()):
            if i >= 15:
                break
            
            if any(f in feature.lower() for f in niche_features):
                ftype = "Niche-Rel"
            elif any(f in feature.lower() for f in thumb_features):
                ftype = "Thumbnail"
            elif any(f in feature.lower() for f in title_features):
                ftype = "Title"
            else:
                ftype = "Context"
            
            table.add_row(feature, f"{importance:,.0f}", ftype)
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def train_combined_model(
    min_views: int = typer.Option(100, "--min-views", help="Minimum views to include"),
    limit: int = typer.Option(None, "--limit", "-l", help="Limit training samples"),
):
    """Train the combined performance predictor (Title + Thumbnail + Context)."""
    from src.ml.combined_predictor import CombinedPredictor
    
    console.print("[bold blue]🧠 Training Combined Performance Predictor...[/bold blue]")
    console.print("[dim]Using: Thumbnail + Title + Niche + Channel Size + Timing[/dim]\n")
    
    try:
        predictor = CombinedPredictor()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Training model...", total=None)
            result = predictor.train(min_views=min_views, limit=limit)
        
        console.print("\n[bold green]✓ Model trained![/bold green]\n")
        
        # Results
        console.print("[cyan]Training Results:[/cyan]")
        console.print(f"  Samples: {result.samples:,}")
        console.print(f"  Features: {result.features_used}")
        console.print(f"  Train R²: {result.train_r2:.4f}")
        console.print(f"  [bold]Validation R²: {result.val_r2:.4f}[/bold]")
        console.print(f"  Validation RMSE: {result.val_rmse:.4f}")
        console.print(f"  Validation MAE: {result.val_mae:.4f}")
        
        # Comparison
        console.print("\n[cyan]R² Comparison:[/cyan]")
        console.print("  Thumbnail only:  ~0.14")
        console.print(f"  [bold]Combined model: {result.val_r2:.2f}[/bold]")
        improvement = (result.val_r2 - 0.14) / 0.14 * 100
        if improvement > 0:
            console.print(f"  [green]↑ {improvement:.0f}% improvement![/green]")
        
        # Feature importance
        console.print("\n[cyan]Top Feature Importance:[/cyan]")
        table = Table()
        table.add_column("Feature", style="cyan")
        table.add_column("Importance", justify="right")
        
        for i, (feature, importance) in enumerate(result.feature_importance.items()):
            if i >= 12:
                break
            table.add_row(feature, f"{importance:,.0f}")
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def optimize_title(
    title: str = typer.Argument(..., help="The video title to analyze"),
    suggest: bool = typer.Option(False, "--suggest", "-s", help="Generate alternative titles"),
):
    """Analyze a video title and get optimization suggestions."""
    from src.ml.title_optimizer import TitleOptimizer
    
    console.print("[bold blue]📝 Analyzing Title...[/bold blue]\n")
    
    try:
        with get_session() as session:
            optimizer = TitleOptimizer(session)
            analysis = optimizer.analyze_title(title)
        
        # Score display with color
        if analysis.score >= 70:
            score_color = "green"
            score_emoji = "🔥"
            verdict = "Great title!"
        elif analysis.score >= 50:
            score_color = "yellow" 
            score_emoji = "👍"
            verdict = "Good, but could improve"
        else:
            score_color = "red"
            score_emoji = "⚠️"
            verdict = "Needs work"
        
        console.print(f'[bold]Title:[/bold] "{title}"')
        console.print()
        console.print(f"[bold {score_color}]{score_emoji} SCORE: {analysis.score}/100 - {verdict}[/bold {score_color}]")
        console.print()
        
        # Metrics table
        table = Table(title="📊 Title Analysis", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        table.add_column("Status")
        
        # Length
        length_status = "✓" if 40 <= analysis.char_length <= 70 else "⚠️"
        table.add_row("Length", f"{analysis.char_length} chars", length_status)
        
        # Words
        words_status = "✓" if 5 <= analysis.word_count <= 12 else "⚠️"
        table.add_row("Words", str(analysis.word_count), words_status)
        
        # Number
        table.add_row("Has Number", "Yes ✓" if analysis.has_number else "No", 
                     "✓" if analysis.has_number else "💡")
        
        # Question
        table.add_row("Has Question", "Yes ✓" if analysis.has_question else "No", "")
        
        # Hook type
        hook_good = analysis.hook_type in ['how_to', 'listicle', 'question', 'challenge', 'tutorial']
        table.add_row("Hook Type", analysis.hook_type, "✓" if hook_good else "💡")
        
        # Power words
        pw_text = ", ".join(analysis.power_words) if analysis.power_words else "None"
        table.add_row("Power Words", pw_text, "✓" if analysis.power_words else "💡")
        
        # Caps
        caps_ok = analysis.caps_ratio < 0.3
        table.add_row("Caps Ratio", f"{analysis.caps_ratio*100:.0f}%", "✓" if caps_ok else "⚠️")
        
        console.print(table)
        
        # Issues
        if analysis.issues:
            console.print("\n[bold red]⚠️ Issues:[/bold red]")
            for issue in analysis.issues:
                console.print(f"  • {issue}")
        
        # Suggestions
        if analysis.suggestions:
            console.print("\n[bold cyan]💡 Suggestions:[/bold cyan]")
            for suggestion in analysis.suggestions:
                console.print(f"  {suggestion}")
        
        # Alternative suggestions
        if suggest:
            console.print("\n[bold green]✨ Alternative Title Ideas:[/bold green]")
            with get_session() as session:
                optimizer = TitleOptimizer(session)
                alternatives = optimizer.suggest_alternatives(title)
                for i, alt in enumerate(alternatives, 1):
                    console.print(f"  {i}. {alt}")
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def compare_titles(
    title1: str = typer.Argument(..., help="First title"),
    title2: str = typer.Argument(..., help="Second title"),
):
    """Compare two titles and show which is better optimized."""
    from src.ml.title_optimizer import TitleOptimizer
    
    console.print("[bold blue]📝 Comparing Titles...[/bold blue]\n")
    
    try:
        with get_session() as session:
            optimizer = TitleOptimizer(session)
            analysis1 = optimizer.analyze_title(title1)
            analysis2 = optimizer.analyze_title(title2)
        
        # Comparison table
        table = Table(title="Title Comparison")
        table.add_column("Metric", style="cyan")
        table.add_column("Title 1")
        table.add_column("Title 2")
        table.add_column("Winner")
        
        # Score
        winner = "1 ✓" if analysis1.score > analysis2.score else ("2 ✓" if analysis2.score > analysis1.score else "Tie")
        table.add_row("Score", f"{analysis1.score}/100", f"{analysis2.score}/100", winner)
        
        # Length
        len1_good = 40 <= analysis1.char_length <= 70
        len2_good = 40 <= analysis2.char_length <= 70
        winner = "1 ✓" if len1_good and not len2_good else ("2 ✓" if len2_good and not len1_good else "-")
        table.add_row("Length", f"{analysis1.char_length}", f"{analysis2.char_length}", winner)
        
        # Number
        winner = "1 ✓" if analysis1.has_number and not analysis2.has_number else ("2 ✓" if analysis2.has_number and not analysis1.has_number else "-")
        table.add_row("Has Number", "Yes" if analysis1.has_number else "No", "Yes" if analysis2.has_number else "No", winner)
        
        # Hook
        table.add_row("Hook Type", analysis1.hook_type, analysis2.hook_type, "-")
        
        # Power words
        pw1 = len(analysis1.power_words)
        pw2 = len(analysis2.power_words)
        winner = "1 ✓" if pw1 > pw2 else ("2 ✓" if pw2 > pw1 else "-")
        table.add_row("Power Words", str(pw1), str(pw2), winner)
        
        console.print(table)
        
        # Verdict
        console.print()
        if analysis1.score > analysis2.score + 10:
            console.print("[bold green]🏆 Title 1 is clearly better optimized[/bold green]")
        elif analysis2.score > analysis1.score + 10:
            console.print("[bold green]🏆 Title 2 is clearly better optimized[/bold green]")
        else:
            console.print("[bold yellow]🤝 Both titles are similarly optimized[/bold yellow]")
        
        # Show both titles
        console.print(f"\n[dim]Title 1: {title1}[/dim]")
        console.print(f"[dim]Title 2: {title2}[/dim]")
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def monitor_channel(
    channel_id: str = typer.Argument(..., help="YouTube channel ID (UC...)"),
):
    """Add a channel to velocity monitoring."""
    from src.tracking.velocity_monitor import VelocityMonitor
    
    console.print("[bold blue]📡 Adding channel to monitoring...[/bold blue]\n")
    
    try:
        with get_session() as session:
            monitor = VelocityMonitor(session)
            result = monitor.add_channel(channel_id)
        
        if result["status"] == "added":
            console.print("[bold green]✓ Channel added to monitoring![/bold green]")
            console.print(f"  Channel: {result.get('channel_name', 'Unknown')}")
            console.print(f"  Subscribers: {result.get('subscriber_count', 0):,}")
            console.print("\n[dim]New videos will be auto-tracked and velocity monitored.[/dim]")
        elif result["status"] == "already_tracked":
            console.print("[bold yellow]⚠️ Channel already being tracked[/bold yellow]")
            console.print(f"  Added at: {result.get('added_at')}")
        else:
            console.print(f"[bold red]Error:[/bold red] {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def velocity_status(
    channel_id: str = typer.Option(None, "--channel", "-c", help="Filter to specific channel"),
):
    """Show velocity monitoring status and predictions."""
    from src.tracking.velocity_monitor import VelocityMonitor
    
    console.print("[bold blue]📊 Velocity Monitoring Status[/bold blue]\n")
    
    try:
        with get_session() as session:
            monitor = VelocityMonitor(session)
            
            if channel_id:
                status = monitor.get_channel_status(channel_id)
                if not status:
                    console.print(f"[bold red]Channel not found: {channel_id}[/bold red]")
                    raise typer.Exit(1)
                
                # Channel info
                console.print(f"[bold]{status.channel_name}[/bold]")
                console.print(f"  Subscribers: {status.subscriber_count:,}")
                console.print(f"  Videos tracked: {status.videos_tracked}")
                console.print(f"  Active: {status.videos_active}, Complete: {status.videos_complete}")
                
                if status.avg_growth_24h_7d:
                    console.print(f"  Channel growth pattern (24h→7d): {status.avg_growth_24h_7d:.2f}x")
                if status.prediction_accuracy:
                    console.print(f"  Prediction accuracy: {status.prediction_accuracy:.1f}%")
                
                # Recent videos
                if status.recent_videos:
                    console.print("\n[bold]Recent Videos:[/bold]")
                    table = Table()
                    table.add_column("Title", max_width=40)
                    table.add_column("Age", justify="right")
                    table.add_column("Current", justify="right")
                    table.add_column("Pred 30d", justify="right")
                    table.add_column("Actual 30d", justify="right")
                    table.add_column("Accuracy", justify="right")
                    
                    for v in status.recent_videos[:10]:
                        age = f"{v.hours_since_publish / 24:.1f}d"
                        pred = f"{v.predicted_30d:,}" if v.predicted_30d else "-"
                        actual = f"{v.actual_30d:,}" if v.actual_30d else "-"
                        acc = f"{v.accuracy_30d:.0f}%" if v.accuracy_30d else "-"
                        table.add_row(
                            v.title[:40],
                            age,
                            f"{v.current_views:,}",
                            pred,
                            actual,
                            acc
                        )
                    console.print(table)
            else:
                # Overall report
                report = monitor.get_accuracy_report()
                
                if "total_complete_videos" in report:
                    console.print(f"Complete videos with 30d data: {report['total_complete_videos']}")
                    console.print()
                    
                    table = Table(title="Prediction Accuracy by Milestone")
                    table.add_column("Prediction", style="cyan")
                    table.add_column("Mean Accuracy", justify="right")
                    table.add_column("Median Accuracy", justify="right")
                    table.add_column("Samples", justify="right")
                    
                    for key in ["24h_to_3d", "24h_to_7d", "24h_to_14d", "24h_to_30d"]:
                        if f"{key}_accuracy" in report:
                            acc = report[f"{key}_accuracy"]
                            table.add_row(
                                key.replace("_", " → "),
                                f"{acc['mean']:.1f}%",
                                f"{acc['median']:.1f}%",
                                str(acc['samples'])
                            )
                    console.print(table)
                else:
                    console.print("[dim]No completed videos yet. Keep tracking![/dim]")
                
                # Show active predictions
                active = monitor.get_all_active_predictions()
                if active:
                    console.print(f"\n[bold]Active Videos Being Tracked: {len(active)}[/bold]")
                    table = Table()
                    table.add_column("Title", max_width=35)
                    table.add_column("Channel", max_width=20)
                    table.add_column("Age", justify="right")
                    table.add_column("Current", justify="right")
                    table.add_column("Pred 30d", justify="right")
                    
                    for v in active[:15]:
                        age = f"{v.hours_since_publish / 24:.1f}d"
                        pred = f"{v.predicted_30d:,}" if v.predicted_30d else "-"
                        table.add_row(
                            v.title[:35],
                            v.channel_id[:20],
                            age,
                            f"{v.current_views:,}",
                            pred
                        )
                    console.print(table)
                    
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def velocity_predict(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
):
    """Get velocity prediction for a specific video."""
    from src.tracking.velocity_monitor import VelocityMonitor
    
    console.print("[bold blue]🔮 Video Velocity Prediction[/bold blue]\n")
    
    try:
        with get_session() as session:
            monitor = VelocityMonitor(session)
            pred = monitor.get_video_prediction(video_id)
            
            if not pred:
                console.print(f"[bold red]Video not being tracked: {video_id}[/bold red]")
                console.print("[dim]Use 'monitor-channel' to add the channel first.[/dim]")
                raise typer.Exit(1)
            
            console.print(f"[bold]{pred.title}[/bold]")
            console.print(f"  Published: {pred.published_at}")
            console.print(f"  Age: {pred.hours_since_publish / 24:.1f} days ({pred.current_checkpoint})")
            console.print(f"  Current views: {pred.current_views:,}")
            
            if pred.channel_growth_pattern:
                console.print(f"  Channel growth pattern: {pred.channel_growth_pattern:.2f}x")
            
            console.print("\n[bold]Predictions vs Actual:[/bold]")
            table = Table()
            table.add_column("Milestone")
            table.add_column("Predicted", justify="right")
            table.add_column("Actual", justify="right")
            table.add_column("Accuracy", justify="right")
            
            for milestone, pred_val, actual_val, acc_val in [
                ("Day 3", pred.predicted_3d, pred.actual_3d, pred.accuracy_3d),
                ("Day 7", pred.predicted_7d, pred.actual_7d, pred.accuracy_7d),
                ("Day 14", pred.predicted_14d, pred.actual_14d, pred.accuracy_14d),
                ("Day 30", pred.predicted_30d, pred.actual_30d, pred.accuracy_30d),
            ]:
                p = f"{pred_val:,}" if pred_val else "-"
                a = f"{actual_val:,}" if actual_val else "pending"
                acc = f"{acc_val:.1f}%" if acc_val else "-"
                table.add_row(milestone, p, a, acc)
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()


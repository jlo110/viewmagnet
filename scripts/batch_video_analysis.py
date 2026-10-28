#!/usr/bin/env python3
"""
Batch video content analysis processor.
Downloads videos, extracts features, stores in R2, saves to database.
"""

import sys
import os
import time
import tempfile
import argparse
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import and_, func

from src.database.models import Video, VideoFeatures, Channel, VideoContentAnalysis
from src.database.connection import get_session, get_engine
from src.video_analysis.downloader import VideoDownloader
from src.video_analysis.extractor import VideoFeatureExtractor
from src.video_analysis.storage import R2Storage

console = Console()


def to_python_type(val):
    """Convert numpy types to native Python types for database storage."""
    if val is None:
        return None
    if isinstance(val, (np.integer, np.int64, np.int32)):
        return int(val)
    if isinstance(val, (np.floating, np.float64, np.float32)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    return val


def ensure_table_exists():
    """Create VideoContentAnalysis table if it doesn't exist."""
    from src.database.models import Base
    engine = get_engine()
    Base.metadata.create_all(engine, tables=[VideoContentAnalysis.__table__], checkfirst=True)
    console.print("[green]✓ Database table ready[/green]")


def get_videos_to_process(session, limit: int = 100, min_views: int = 1000, 
                          category: str = None, prioritize_high_performers: bool = True,
                          max_duration: int = 1800):
    """
    Get videos that haven't been analyzed yet.
    Prioritizes high-performing videos for better training data.
    Excludes very long videos (livestreams) that cause download timeouts.
    """
    # Get already processed video IDs (both successful and failed - don't retry)
    processed = session.query(VideoContentAnalysis.video_id).all()
    processed_ids = {p[0] for p in processed}
    
    # Build query for videos to process
    # Filter out long videos (>30min) which are usually livestreams and cause timeouts
    query = session.query(
        Video.video_id, Video.title, Video.view_count,
        Channel.channel_name, Channel.avg_views_per_video, Channel.primary_category
    ).join(Channel, Video.channel_id == Channel.channel_id
    ).filter(and_(
        Video.view_count >= min_views,
        Video.duration_seconds <= max_duration,  # Exclude livestreams (>30 min)
        Video.duration_seconds > 30,  # Exclude shorts (<30s)
        ~Video.video_id.in_(processed_ids) if processed_ids else True
    ))
    
    # Filter by category if specified
    if category:
        query = query.filter(Channel.primary_category == category)
    
    # Prioritize high performers (above channel average)
    if prioritize_high_performers:
        query = query.order_by(
            (Video.view_count / func.nullif(Channel.avg_views_per_video, 0)).desc()
        )
    else:
        query = query.order_by(Video.published_at.desc())
    
    return query.limit(limit).all()


def process_video(video_id: str, downloader: VideoDownloader, extractor: VideoFeatureExtractor,
                  r2: R2Storage, session, use_r2: bool = True) -> dict:
    """
    Process a single video: download, extract features, upload to R2, save to DB.
    """
    result = {
        'success': False,
        'video_id': video_id,
        'error': None,
        'r2_video_key': None,
        'r2_audio_key': None,
    }
    
    try:
        # Download video
        download_result = downloader.download(video_id, include_audio=True)
        
        if not download_result.success:
            result['error'] = f"Download failed: {download_result.error}"
            # Save failed attempt to DB so we don't retry
            try:
                failed_analysis = VideoContentAnalysis(
                    video_id=video_id,
                    extraction_success=False,
                    extraction_error=result['error'][:500] if result['error'] else "Download failed",
                    extracted_at=datetime.now(timezone.utc),
                )
                session.merge(failed_analysis)
                session.commit()
            except:
                session.rollback()
            return result
        
        # Extract features
        features = extractor.extract(download_result.video_path, download_result.audio_path)
        
        # Upload to R2 if enabled
        if use_r2 and download_result.video_path and os.path.exists(download_result.video_path):
            try:
                result['r2_video_key'] = r2.upload_video(video_id, download_result.video_path)
            except Exception as e:
                console.print(f"[yellow]R2 upload skipped: {e}[/yellow]")
        
        if use_r2 and download_result.audio_path and os.path.exists(download_result.audio_path):
            try:
                result['r2_audio_key'] = r2.upload_audio(video_id, download_result.audio_path)
            except Exception as e:
                pass  # Audio upload is optional
        
        # Save to database - convert all numpy types to native Python
        content_analysis = VideoContentAnalysis(
            video_id=video_id,
            r2_video_key=result['r2_video_key'],
            r2_audio_key=result['r2_audio_key'],
            
            # Hook features
            hook_face_appears_seconds=to_python_type(features.hook_face_appears_seconds),
            hook_scene_changes_count=to_python_type(features.hook_scene_changes_count),
            hook_avg_motion=to_python_type(features.hook_avg_motion),
            hook_words_count=to_python_type(features.hook_words_in_first_10s),
            
            # Visual pacing
            total_scene_changes=to_python_type(features.total_scene_changes),
            avg_scene_duration=to_python_type(features.avg_scene_duration),
            scene_change_variance=to_python_type(features.scene_change_variance),
            
            # Visual quality
            avg_brightness=to_python_type(features.avg_brightness),
            brightness_variance=to_python_type(features.brightness_variance),
            avg_sharpness=to_python_type(features.avg_sharpness),
            
            # Face presence
            face_screen_time_ratio=to_python_type(features.face_screen_time_ratio),
            face_size_consistency=to_python_type(features.face_size_consistency),
            
            # Audio features
            audio_energy_mean=to_python_type(features.audio_energy_mean),
            audio_energy_variance=to_python_type(features.audio_energy_variance),
            audio_tempo=to_python_type(features.audio_tempo),
            loudness_range=to_python_type(features.loudness_range),
            energy_ramp_up=to_python_type(features.energy_ramp_up),
            has_music_intro=to_python_type(features.has_music_intro),
            intro_duration_seconds=to_python_type(features.intro_duration_seconds),
            
            # Transcript features
            transcript_word_count=to_python_type(features.word_count),
            words_per_minute=to_python_type(features.words_per_minute),
            question_count=to_python_type(features.question_count),
            call_to_action_count=to_python_type(features.call_to_action_count),
            transcript_sentiment=to_python_type(features.transcript_sentiment),
            transcript=features.transcript[:10000] if features.transcript else None,
            
            # Processing metadata
            video_duration_analyzed=to_python_type(download_result.duration),
            extraction_success=True,
            extracted_at=datetime.now(timezone.utc),
        )
        
        session.merge(content_analysis)
        session.commit()
        
        result['success'] = True
        
    except Exception as e:
        result['error'] = str(e)
        
        # Save failed attempt to DB
        try:
            session.rollback()  # Clear any pending failed state
            failed_analysis = VideoContentAnalysis(
                video_id=video_id,
                extraction_success=False,
                extraction_error=str(e)[:500],
                extracted_at=datetime.now(timezone.utc),
            )
            session.merge(failed_analysis)
            session.commit()
        except:
            session.rollback()
    
    finally:
        # Cleanup local files
        downloader.cleanup(video_id)
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Batch video content analysis')
    parser.add_argument('--limit', type=int, default=50, help='Number of videos to process')
    parser.add_argument('--min-views', type=int, default=1000, help='Minimum view count')
    parser.add_argument('--category', type=str, help='Filter by category')
    parser.add_argument('--no-r2', action='store_true', help='Skip R2 upload')
    parser.add_argument('--no-whisper', action='store_true', help='Skip transcription')
    parser.add_argument('--whisper-model', type=str, default='base', 
                       choices=['tiny', 'base', 'small', 'medium'], help='Whisper model size')
    args = parser.parse_args()
    
    console.print(Panel.fit("🎬 BATCH VIDEO CONTENT ANALYSIS", style="bold magenta"))
    
    # Ensure database table exists
    ensure_table_exists()
    
    # Initialize components
    console.print("\n[yellow]Initializing components...[/yellow]")
    
    output_dir = tempfile.mkdtemp(prefix="ViewMagnet_batch_")
    downloader = VideoDownloader(output_dir=output_dir, max_duration=60)
    extractor = VideoFeatureExtractor(
        use_whisper=not args.no_whisper,
        whisper_model=args.whisper_model
    )
    
    use_r2 = not args.no_r2
    r2 = None
    if use_r2:
        try:
            r2 = R2Storage()
            # Test R2 connection
            r2.client  # This will raise if credentials are missing
            console.print("[green]✓ R2 storage connected[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ R2 not configured: {e}[/yellow]")
            console.print("[yellow]  Videos will be processed but not stored in R2[/yellow]")
            use_r2 = False
            r2 = R2Storage()  # Still create for interface compatibility
    
    console.print(f"[green]✓ Video downloader ready (60s clips)[/green]")
    console.print(f"[green]✓ Feature extractor ready (Whisper: {not args.no_whisper})[/green]")
    
    # Get videos to process
    console.print(f"\n[yellow]Finding videos to process...[/yellow]")
    
    with get_session() as session:
        videos = get_videos_to_process(
            session, 
            limit=args.limit,
            min_views=args.min_views,
            category=args.category,
            prioritize_high_performers=True
        )
        
        if not videos:
            console.print("[yellow]No videos found to process![/yellow]")
            return
        
        console.print(f"[green]✓ Found {len(videos)} videos to process[/green]")
        
        # Show sample
        table = Table(title="Sample Videos to Process", show_lines=True)
        table.add_column("Video ID", style="cyan")
        table.add_column("Title", max_width=40)
        table.add_column("Views", justify="right")
        table.add_column("Channel")
        
        for v in videos[:5]:
            table.add_row(v[0], v[1][:40] + "..." if len(v[1]) > 40 else v[1], 
                         f"{v[2]:,}", v[3][:20])
        
        console.print(table)
        
        # Convert to list while still in session
        videos_list = [(v[0], v[1], v[2], v[3], v[4], v[5]) for v in videos]
    
    # Process videos (outside the first session context)
    console.print(f"\n[bold]Starting batch processing...[/bold]")
    
    stats = {'success': 0, 'failed': 0, 'r2_uploaded': 0}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Processing videos...", total=len(videos_list))
        
        for video in videos_list:
            video_id, title, views, channel, avg_views, category = video
            
            progress.update(task, description=f"[cyan]Processing {video_id}...")
            
            # Use a new session for each video to avoid transaction issues
            with get_session() as session:
                result = process_video(
                    video_id=video_id,
                    downloader=downloader,
                    extractor=extractor,
                    r2=r2,
                    session=session,
                    use_r2=use_r2
                )
            
            if result['success']:
                stats['success'] += 1
                if result['r2_video_key']:
                    stats['r2_uploaded'] += 1
            else:
                stats['failed'] += 1
                if result['error']:
                    console.print(f"[red]  ✗ {video_id}: {result['error'][:50]}[/red]")
            
            progress.update(task, advance=1)
            
            # Small delay to be nice to YouTube
            time.sleep(1)
    
    # Final stats
    console.print("\n" + "=" * 60)
    console.print(Panel.fit("📊 BATCH PROCESSING COMPLETE", style="bold green"))
    
    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Videos processed", str(stats['success'] + stats['failed']))
    table.add_row("Successful", f"{stats['success']} ✅")
    table.add_row("Failed", f"{stats['failed']} ❌")
    if use_r2:
        table.add_row("Uploaded to R2", f"{stats['r2_uploaded']} ☁️")
    
    console.print(table)
    
    # Cleanup
    import shutil
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    console.print("\n[dim]Temporary files cleaned up[/dim]")


if __name__ == "__main__":
    main()


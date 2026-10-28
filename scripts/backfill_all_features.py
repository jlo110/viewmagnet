#!/usr/bin/env python
"""Backfill ALL new features: composition_score + face emotions."""
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import VideoFeatures, Video
from src.database.connection import get_session
from src.features.thumbnail_analyzer import ThumbnailAnalyzer
from sqlalchemy import and_, func
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.live import Live
from rich.table import Table
from rich.panel import Panel

console = Console()

def format_time(seconds):
    """Format seconds into human readable time."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m {seconds%60:.0f}s"
    else:
        return f"{seconds/3600:.0f}h {(seconds%3600)/60:.0f}m"

def main():
    console.print(Panel.fit("[bold cyan]🎬 Feature Backfill Script[/bold cyan]\n"
                           "Backfilling: composition_score + face emotions",
                           border_style="cyan"))
    
    # Initialize analyzer with face detection AND emotion detection
    console.print("\n[yellow]Initializing analyzers...[/yellow]")
    analyzer = ThumbnailAnalyzer(
        enable_face_detection=True,
        enable_emotion_detection=True
    )
    
    console.print(f"  Face detection: {'✅' if analyzer.enable_face_detection else '❌'}")
    console.print(f"  Emotion detection: {'✅' if analyzer.enable_emotion_detection else '❌'}")
    console.print()
    
    with get_session() as session:
        # Count records needing updates
        need_composition = session.query(func.count(VideoFeatures.id)).filter(
            and_(
                VideoFeatures.thumbnail_processed == True,
                VideoFeatures.composition_score.is_(None)
            )
        ).scalar()
        
        already_done = session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.composition_score.isnot(None)
        ).scalar()
        
        total_records = need_composition + already_done
        
        console.print(f"[bold]📊 Status:[/bold]")
        console.print(f"  Already processed: {already_done:,}")
        console.print(f"  Remaining: {need_composition:,}")
        console.print(f"  Total: {total_records:,}")
        console.print()
        
        if need_composition == 0:
            console.print("[green]✅ All records already processed![/green]")
            return
        
        batch_size = 200
        total_processed = 0
        emotions_found = 0
        faces_found = 0
        errors = 0
        start_time = time.time()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
            TextColumn("•"),
            TextColumn("[cyan]{task.completed:,}/{task.total:,}[/cyan]"),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
            refresh_per_second=2,
        ) as progress:
            
            task = progress.add_task("[green]Processing thumbnails...", total=need_composition)
            
            while True:
                records = session.query(VideoFeatures, Video.thumbnail_url).join(
                    Video, VideoFeatures.video_id == Video.video_id
                ).filter(
                    and_(
                        VideoFeatures.thumbnail_processed == True,
                        VideoFeatures.composition_score.is_(None)
                    )
                ).limit(batch_size).all()
                
                if not records:
                    break
                
                batch_emotions = 0
                batch_faces = 0
                batch_errors = 0
                
                for features, url in records:
                    if not url:
                        features.composition_score = 0.5
                        continue
                    try:
                        thumb_features = analyzer.analyze_from_url_sync(url)
                        if thumb_features:
                            # Convert numpy types to native Python types for PostgreSQL
                            features.composition_score = float(thumb_features.composition_score)
                            features.face_count = int(thumb_features.face_count)
                            features.face_area_ratio = float(thumb_features.face_area_ratio)
                            features.has_face = bool(thumb_features.has_face)
                            
                            if thumb_features.face_count > 0:
                                batch_faces += 1
                            
                            # Emotion features
                            if thumb_features.face_emotion_primary:
                                features.face_emotion_primary = str(thumb_features.face_emotion_primary)
                                features.face_emotion_intensity = float(thumb_features.face_emotion_intensity)
                                batch_emotions += 1
                        else:
                            features.composition_score = 0.5
                    except Exception as e:
                        features.composition_score = 0.5
                        batch_errors += 1
                
                session.commit()
                total_processed += len(records)
                emotions_found += batch_emotions
                faces_found += batch_faces
                errors += batch_errors
                
                # Update progress
                progress.update(task, advance=len(records))
                
                # Update description with stats
                elapsed = time.time() - start_time
                rate = total_processed / elapsed if elapsed > 0 else 0
                progress.update(
                    task, 
                    description=f"[green]Processing[/green] | {rate:.1f}/s | 👤 {faces_found:,} faces | 😀 {emotions_found:,} emotions"
                )
        
        # Final summary
        elapsed = time.time() - start_time
        console.print()
        console.print(Panel.fit(
            f"[bold green]✅ Backfill Complete![/bold green]\n\n"
            f"📊 [bold]Results:[/bold]\n"
            f"  • Processed: {total_processed:,} thumbnails\n"
            f"  • Faces found: {faces_found:,}\n"
            f"  • Emotions detected: {emotions_found:,}\n"
            f"  • Errors: {errors:,}\n"
            f"  • Time: {format_time(elapsed)}\n"
            f"  • Rate: {total_processed/elapsed:.1f} thumbnails/sec",
            border_style="green"
        ))

if __name__ == '__main__':
    main()


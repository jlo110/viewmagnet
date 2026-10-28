#!/usr/bin/env python3
"""
Resume backfill after internet outage.
- Resets failed downloads (composition=0.5) to null for retry
- Continues processing remaining records
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.panel import Panel
from sqlalchemy import and_, func
import numpy as np

from src.database.models import VideoFeatures, Video
from src.database.connection import get_session
from src.features.thumbnail_analyzer import ThumbnailAnalyzer

console = Console()

def main():
    console.print(Panel.fit(
        "[bold cyan]🔄 Resume Backfill Script[/]\n"
        "Retrying failed downloads + continuing remaining",
        border_style="cyan"
    ))
    
    with get_session() as session:
        # First, reset failed downloads (0.5) to null for retry
        failed_count = session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.composition_score == 0.5
        ).scalar()
        
        if failed_count > 0:
            console.print(f"\n[yellow]Resetting {failed_count:,} failed downloads for retry...[/]")
            session.query(VideoFeatures).filter(
                VideoFeatures.composition_score == 0.5
            ).update({
                VideoFeatures.composition_score: None,
                VideoFeatures.face_emotion_primary: None,
                VideoFeatures.face_emotion_intensity: None
            })
            session.commit()
            console.print(f"[green]✓ Reset complete[/]")
        
        # Count remaining
        remaining = session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.composition_score.is_(None)
        ).scalar()
        
        already_done = session.query(func.count(VideoFeatures.id)).filter(
            VideoFeatures.composition_score.isnot(None)
        ).scalar()
        
        console.print(f"\n[cyan]📊 Status:[/]")
        console.print(f"   Already processed: {already_done:,}")
        console.print(f"   Remaining: {remaining:,}")
    
    if remaining == 0:
        console.print("\n[green]✅ All records already processed![/]")
        return
    
    # Initialize analyzer
    console.print("\n[dim]Initializing analyzers...[/]")
    analyzer = ThumbnailAnalyzer(enable_face_detection=True, enable_emotion_detection=True)
    console.print(f"Face detection: [green]✅[/]")
    console.print(f"Emotion detection: [green]✅[/]")
    
    batch_size = 100
    total_processed = 0
    faces_found = 0
    emotions_found = 0
    failed_downloads = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        refresh_per_second=2
    ) as progress:
        task = progress.add_task("[cyan]Processing...", total=remaining)
        
        while True:
            with get_session() as session:
                records = session.query(VideoFeatures, Video.thumbnail_url).join(
                    Video, VideoFeatures.video_id == Video.video_id
                ).filter(
                    VideoFeatures.composition_score.is_(None)
                ).limit(batch_size).all()
                
                if not records:
                    break
                
                for features, url in records:
                    if not url:
                        features.composition_score = 0.0  # Mark as "no thumbnail"
                        continue
                    
                    try:
                        thumb_features = analyzer.analyze_from_url_sync(url)
                        
                        if thumb_features:
                            # Convert numpy types to Python native
                            features.composition_score = float(thumb_features.composition_score) if thumb_features.composition_score else 0.0
                            features.face_count = int(thumb_features.face_count) if thumb_features.face_count else 0
                            features.has_face = bool(thumb_features.has_face)
                            
                            if thumb_features.face_area_ratio is not None:
                                val = thumb_features.face_area_ratio
                                features.face_area_ratio = float(val.item()) if hasattr(val, 'item') else float(val)
                            
                            if thumb_features.has_face:
                                faces_found += 1
                                
                                if thumb_features.face_emotion_primary:
                                    features.face_emotion_primary = thumb_features.face_emotion_primary
                                    emotions_found += 1
                                    
                                    if thumb_features.face_emotion_intensity is not None:
                                        val = thumb_features.face_emotion_intensity
                                        features.face_emotion_intensity = float(val.item()) if hasattr(val, 'item') else float(val)
                        else:
                            features.composition_score = 0.0  # Failed to analyze
                            failed_downloads += 1
                            
                    except Exception as e:
                        features.composition_score = 0.0  # Mark as failed
                        failed_downloads += 1
                
                session.commit()
                total_processed += len(records)
                
                progress.update(
                    task,
                    advance=len(records),
                    description=f"[cyan]Processing | 👤 {faces_found:,} faces | 😀 {emotions_found:,} emotions | ❌ {failed_downloads:,} failed"
                )
    
    console.print(f"\n[green]✅ Backfill complete![/]")
    console.print(f"   Processed: {total_processed:,}")
    console.print(f"   Faces found: {faces_found:,}")
    console.print(f"   Emotions detected: {emotions_found:,}")
    console.print(f"   Failed downloads: {failed_downloads:,}")

if __name__ == "__main__":
    main()


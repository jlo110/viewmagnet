#!/usr/bin/env python3
"""
Recalculate composition features for all video thumbnails.

This script downloads thumbnails and calculates:
- rule_of_thirds_score
- focal_point_x, focal_point_y
- focal_point_quadrant
- on_power_point

Estimated time: 8-12 hours for 145K videos
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import signal
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image
import io
import structlog

from sqlalchemy import text
from src.database.connection import get_session, get_engine
from src.database.models import Video, VideoFeatures
from src.features.thumbnail_analyzer import ThumbnailAnalyzer

# Setup logging
log_file = Path(__file__).resolve().parents[1] / "logs" / "composition_recalc.log"
log_file.parent.mkdir(exist_ok=True)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ]
)
logger = structlog.get_logger()

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    logger.info("Shutdown requested, finishing current batch...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_videos_to_process(limit: int = None):
    """Get videos that need composition recalculation."""
    with get_session() as session:
        query = session.query(
            Video.video_id,
            Video.thumbnail_url
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(
            VideoFeatures.rule_of_thirds_score.is_(None),  # Not yet calculated
            Video.thumbnail_url.isnot(None)
        )
        
        if limit:
            query = query.limit(limit)
        
        results = query.all()
        return [(r[0], r[1]) for r in results]


def download_thumbnail(url: str, timeout: float = 10.0) -> Image.Image:
    """Download thumbnail image."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
    except Exception as e:
        raise Exception(f"Failed to download: {e}")


def calculate_composition(image: Image.Image) -> dict:
    """Calculate composition features from image."""
    analyzer = ThumbnailAnalyzer()
    return analyzer._calculate_composition_score(image)


def update_video_features(video_id: str, composition: dict):
    """Update video features with composition data."""
    with get_session() as session:
        session.execute(
            text("""
                UPDATE video_features SET
                    rule_of_thirds_score = :rot,
                    focal_point_x = :fpx,
                    focal_point_y = :fpy,
                    focal_point_quadrant = :quad,
                    on_power_point = :opp
                WHERE video_id = :vid
            """),
            {
                "rot": composition["rule_of_thirds_score"],
                "fpx": composition["focal_point_x"],
                "fpy": composition["focal_point_y"],
                "quad": composition["focal_point_quadrant"],
                "opp": composition["on_power_point"],
                "vid": video_id
            }
        )
        session.commit()


def main():
    global shutdown_requested
    
    logger.info("🚀 Starting composition feature recalculation")
    
    # Get count
    with get_session() as session:
        total = session.query(VideoFeatures).filter(
            VideoFeatures.rule_of_thirds_score.is_(None)
        ).count()
    
    logger.info(f"📊 Videos to process: {total:,}")
    
    if total == 0:
        logger.info("✅ All videos already processed!")
        return
    
    # Process in batches
    batch_size = 100
    processed = 0
    errors = 0
    start_time = time.time()
    
    while not shutdown_requested:
        # Get next batch
        videos = get_videos_to_process(limit=batch_size)
        
        if not videos:
            logger.info("✅ All videos processed!")
            break
        
        for video_id, thumbnail_url in videos:
            if shutdown_requested:
                break
            
            try:
                # Download thumbnail
                image = download_thumbnail(thumbnail_url)
                
                # Calculate composition
                composition = calculate_composition(image)
                
                # Update database
                update_video_features(video_id, composition)
                
                processed += 1
                
            except Exception as e:
                errors += 1
                # Set defaults for failed videos
                try:
                    update_video_features(video_id, {
                        "rule_of_thirds_score": 0.5,
                        "focal_point_x": 0.5,
                        "focal_point_y": 0.5,
                        "focal_point_quadrant": "center",
                        "on_power_point": False
                    })
                except:
                    pass
        
        # Progress update
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        
        logger.info(
            f"📈 Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | "
            f"Rate: {rate:.1f}/s | "
            f"ETA: {remaining/3600:.1f}h | "
            f"Errors: {errors}"
        )
        
        # Write progress to file
        with open(log_file, "a") as f:
            f.write(f"{datetime.now().isoformat()} | {processed}/{total} | {errors} errors\n")
    
    # Final summary
    elapsed = time.time() - start_time
    logger.info(f"""
    ✅ Recalculation complete!
    
    Processed: {processed:,} videos
    Errors: {errors:,}
    Time: {elapsed/3600:.2f} hours
    Rate: {processed/elapsed:.1f} videos/second
    """)


if __name__ == "__main__":
    main()





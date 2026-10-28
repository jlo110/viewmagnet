#!/usr/bin/env python
"""Backfill composition_score for all existing thumbnail features."""
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import VideoFeatures, Video
from src.database.connection import get_session
from src.features.thumbnail_analyzer import ThumbnailAnalyzer
from sqlalchemy import and_, func

def main():
    analyzer = ThumbnailAnalyzer()
    
    with get_session() as session:
        to_process = session.query(func.count(VideoFeatures.id)).filter(
            and_(
                VideoFeatures.thumbnail_processed == True,
                VideoFeatures.composition_score.is_(None)
            )
        ).scalar()
        
        print(f'Backfilling composition_score for {to_process} thumbnails...')
        print('This will take a while due to thumbnail downloads.')
        print(flush=True)
        
        batch_size = 500
        total_processed = 0
        start_time = time.time()
        
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
            
            for features, url in records:
                if not url:
                    features.composition_score = 0.5
                    continue
                try:
                    thumb_features = analyzer.analyze_from_url_sync(url)
                    if thumb_features:
                        features.composition_score = thumb_features.composition_score
                    else:
                        features.composition_score = 0.5
                except Exception:
                    features.composition_score = 0.5
            
            session.commit()
            total_processed += len(records)
            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            remaining = to_process - total_processed
            eta_mins = (remaining / rate / 60) if rate > 0 else 0
            
            print(f'  Processed {total_processed}/{to_process} ({total_processed/to_process*100:.1f}%) - {rate:.1f}/sec - ETA: {eta_mins:.0f}min', flush=True)
        
        print(f'\n✓ Composition score backfill complete! Processed {total_processed} records.')

if __name__ == '__main__':
    main()



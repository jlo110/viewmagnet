#!/usr/bin/env python3
"""
Calculate point-in-time channel trends for each video.

For each video, calculates what the channel's metrics looked like
at the time of upload (using only OLDER videos, no future data).

This avoids data leakage and creates legitimate pre-upload features:
- channel_momentum_at_upload
- channel_engagement_trend_at_upload  
- channel_hit_rate_at_upload
- channel_recent_avg_ratio_at_upload

Estimated time: 2-3 hours for 145K videos
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import signal
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np
from sqlalchemy import text
from src.database.connection import get_session, get_engine

# Setup logging
log_file = Path(__file__).resolve().parents[1] / "logs" / "trends_recalc.log"
log_file.parent.mkdir(exist_ok=True)

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    print("\n⏸️  Shutdown requested, finishing current batch...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def load_all_videos():
    """Load all videos with their view counts and dates."""
    print("📊 Loading all videos from database...")
    
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT 
                v.video_id,
                v.channel_id,
                v.view_count,
                v.like_count,
                v.comment_count,
                v.published_at,
                c.avg_views_per_video
            FROM videos v
            JOIN channels c ON v.channel_id = c.channel_id
            WHERE v.view_count > 0 
            AND v.published_at IS NOT NULL
            ORDER BY v.channel_id, v.published_at
        '''))
        
        videos = result.fetchall()
    
    print(f"   Loaded {len(videos):,} videos")
    return videos


def calculate_point_in_time_features(videos):
    """
    Calculate point-in-time features for each video.
    
    For each video, we only use videos from the SAME channel
    that were posted BEFORE this video.
    """
    print("🔄 Calculating point-in-time features...")
    
    # Group by channel
    channel_videos = defaultdict(list)
    for v in videos:
        channel_videos[v[1]].append({
            'video_id': v[0],
            'channel_id': v[1],
            'views': v[2],
            'likes': v[3] or 0,
            'comments': v[4] or 0,
            'published_at': v[5],
            'channel_avg': v[6] or 1,
        })
    
    print(f"   {len(channel_videos):,} channels")
    
    # Calculate features for each video
    results = []
    
    for channel_id, vids in channel_videos.items():
        # Sort by publish date (oldest first)
        sorted_vids = sorted(vids, key=lambda x: x['published_at'])
        
        for i, video in enumerate(sorted_vids):
            # Get all videos BEFORE this one
            older = sorted_vids[:i]
            
            if len(older) < 3:
                # Not enough history - use defaults
                results.append({
                    'video_id': video['video_id'],
                    'momentum': 0.0,
                    'engagement_trend': 0.0,
                    'hit_rate': 0.0,
                    'recent_avg_ratio': 1.0,
                })
                continue
            
            # Calculate metrics from older videos
            channel_avg = video['channel_avg']
            
            # Hit rate: % of older videos that beat channel average
            hit_rate = sum(1 for v in older if v['views'] > channel_avg) / len(older)
            
            # Recent avg ratio: last 5 videos avg / channel avg
            recent_5 = older[-5:] if len(older) >= 5 else older
            recent_avg = np.mean([v['views'] for v in recent_5])
            recent_avg_ratio = recent_avg / channel_avg if channel_avg > 0 else 1.0
            
            # Momentum: compare recent 5 to older 5
            if len(older) >= 10:
                recent_5_views = np.mean([v['views'] for v in older[-5:]])
                older_5_views = np.mean([v['views'] for v in older[-10:-5]])
                if older_5_views > 0:
                    momentum = (recent_5_views - older_5_views) / older_5_views
                else:
                    momentum = 0.0
            else:
                momentum = 0.0
            
            # Engagement trend: compare recent engagement to older
            def calc_engagement(v):
                if v['views'] > 0:
                    return (v['likes'] + v['comments']) / v['views']
                return 0
            
            if len(older) >= 10:
                recent_eng = np.mean([calc_engagement(v) for v in older[-5:]])
                older_eng = np.mean([calc_engagement(v) for v in older[-10:-5]])
                if older_eng > 0:
                    engagement_trend = (recent_eng - older_eng) / older_eng
                else:
                    engagement_trend = 0.0
            else:
                engagement_trend = 0.0
            
            # Clip to reasonable ranges
            momentum = np.clip(momentum, -2.0, 2.0)
            engagement_trend = np.clip(engagement_trend, -2.0, 2.0)
            recent_avg_ratio = np.clip(recent_avg_ratio, 0.0, 10.0)
            
            results.append({
                'video_id': video['video_id'],
                'momentum': float(momentum),
                'engagement_trend': float(engagement_trend),
                'hit_rate': float(hit_rate),
                'recent_avg_ratio': float(recent_avg_ratio),
            })
    
    print(f"   Calculated features for {len(results):,} videos")
    return results


def save_features(features, batch_size=1000):
    """Save features to database in batches."""
    global shutdown_requested
    
    print("💾 Saving features to database...")
    
    engine = get_engine()
    
    processed = 0
    start_time = time.time()
    
    for i in range(0, len(features), batch_size):
        if shutdown_requested:
            break
        
        batch = features[i:i + batch_size]
        
        with engine.connect() as conn:
            for f in batch:
                conn.execute(text('''
                    UPDATE video_features SET
                        channel_momentum_at_upload = :momentum,
                        channel_engagement_trend_at_upload = :engagement_trend,
                        channel_hit_rate_at_upload = :hit_rate,
                        channel_recent_avg_ratio_at_upload = :recent_avg_ratio
                    WHERE video_id = :video_id
                '''), {
                    'momentum': f['momentum'],
                    'engagement_trend': f['engagement_trend'],
                    'hit_rate': f['hit_rate'],
                    'recent_avg_ratio': f['recent_avg_ratio'],
                    'video_id': f['video_id'],
                })
            conn.commit()
        
        processed += len(batch)
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (len(features) - processed) / rate if rate > 0 else 0
        
        print(f"   📈 Progress: {processed:,}/{len(features):,} ({processed/len(features)*100:.1f}%) | "
              f"Rate: {rate:.0f}/s | ETA: {remaining/60:.1f} min")
        
        # Log to file
        with open(log_file, "a") as f:
            f.write(f"{datetime.now().isoformat()} | {processed}/{len(features)}\n")
    
    return processed


def main():
    print("=" * 60)
    print("🚀 POINT-IN-TIME CHANNEL TRENDS CALCULATION")
    print("=" * 60)
    print()
    
    start_time = time.time()
    
    # Load all videos
    videos = load_all_videos()
    
    # Calculate features
    features = calculate_point_in_time_features(videos)
    
    # Save to database
    saved = save_features(features)
    
    elapsed = time.time() - start_time
    
    print()
    print("=" * 60)
    print(f"✅ COMPLETE!")
    print(f"   Videos processed: {saved:,}")
    print(f"   Time: {elapsed/60:.1f} minutes")
    print("=" * 60)


if __name__ == "__main__":
    main()





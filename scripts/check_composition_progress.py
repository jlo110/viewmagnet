#!/usr/bin/env python3
"""
Check progress of composition feature recalculation.

Usage: python scripts/check_composition_progress.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from src.database.connection import get_engine
from sqlalchemy import text


def check_progress():
    engine = get_engine()
    
    with engine.connect() as conn:
        # Total count
        result = conn.execute(text('SELECT COUNT(*) FROM video_features'))
        total = result.scalar()
        
        # Completed count (has rule_of_thirds_score)
        result = conn.execute(text('SELECT COUNT(*) FROM video_features WHERE rule_of_thirds_score IS NOT NULL'))
        done = result.scalar()
        
        # Sample of recent values
        result = conn.execute(text('''
            SELECT rule_of_thirds_score, focal_point_quadrant, on_power_point 
            FROM video_features 
            WHERE rule_of_thirds_score IS NOT NULL 
            ORDER BY id DESC 
            LIMIT 5
        '''))
        samples = result.fetchall()
    
    # Calculate progress
    remaining = total - done
    pct = (done / total * 100) if total > 0 else 0
    
    # Estimate time remaining (assuming 4.5/sec average)
    rate = 4.5
    hours_remaining = remaining / rate / 3600 if remaining > 0 else 0
    
    # Display
    print("=" * 60)
    print("🖼️  COMPOSITION FEATURE RECALCULATION PROGRESS")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"📊 Total videos:     {total:>12,}")
    print(f"✅ Completed:        {done:>12,}  ({pct:.1f}%)")
    print(f"⏳ Remaining:        {remaining:>12,}")
    print()
    
    # Progress bar
    bar_width = 40
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(f"Progress: [{bar}] {pct:.1f}%")
    print()
    
    print(f"⏱️  Est. time remaining: {hours_remaining:.1f} hours")
    print()
    
    if samples:
        print("📝 Recent samples:")
        print("-" * 40)
        for s in samples:
            power = "✅" if s[2] else "❌"
            print(f"   RoT: {s[0]:.3f} | Quadrant: {s[1]:<12} | Power: {power}")
    
    print("=" * 60)
    
    # Check if process is running
    import subprocess
    result = subprocess.run(['pgrep', '-f', 'recalculate_composition'], capture_output=True, text=True)
    if result.stdout.strip():
        print("🟢 Process is RUNNING (PID: " + result.stdout.strip().split()[0] + ")")
    else:
        if remaining == 0:
            print("🎉 COMPLETE! All videos processed.")
        else:
            print("🔴 Process NOT RUNNING - may need to restart")
    print()


if __name__ == "__main__":
    check_progress()





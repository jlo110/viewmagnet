#!/usr/bin/env python3
"""Real-time progress tracker for video content analysis."""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from datetime import datetime, timedelta

from src.database.models import VideoContentAnalysis
from src.database.connection import get_session

console = Console()

def get_stats():
    """Get current processing stats."""
    with get_session() as session:
        total = session.query(VideoContentAnalysis).count()
        success = session.query(VideoContentAnalysis).filter_by(extraction_success=True).count()
        failed = session.query(VideoContentAnalysis).filter_by(extraction_success=False).count()
        
        # Get recent processing rate
        recent = session.query(VideoContentAnalysis).filter(
            VideoContentAnalysis.extraction_success == True
        ).order_by(VideoContentAnalysis.extracted_at.desc()).limit(10).all()
        
        rate = 0
        if len(recent) >= 2:
            time_diff = (recent[0].extracted_at - recent[-1].extracted_at).total_seconds()
            if time_diff > 0:
                rate = (len(recent) - 1) / (time_diff / 60)  # videos per minute
        
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'rate': rate
        }

def create_display(stats, target=5000, start_count=None):
    """Create the progress display."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="cyan")
    table.add_column("Value", style="green")
    
    progress = stats['success']
    pct = (progress / target) * 100 if target > 0 else 0
    
    table.add_row("✅ Processed", f"{stats['success']:,}")
    table.add_row("❌ Failed", f"{stats['failed']:,}")
    table.add_row("📊 Progress", f"{progress:,} / {target:,} ({pct:.1f}%)")
    table.add_row("⚡ Rate", f"{stats['rate']:.1f} videos/min")
    
    # Estimate time remaining
    if stats['rate'] > 0:
        remaining = target - progress
        minutes_left = remaining / stats['rate']
        eta = datetime.now() + timedelta(minutes=minutes_left)
        table.add_row("⏱️ ETA", f"~{minutes_left:.0f} min ({eta.strftime('%H:%M')})")
    else:
        table.add_row("⏱️ ETA", "Calculating...")
    
    # Progress bar
    bar_width = 40
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    
    return Panel(
        f"{table}\n\n[yellow]{bar}[/yellow] {pct:.1f}%",
        title="🎬 Video Content Analysis Progress",
        subtitle=f"Updated: {datetime.now().strftime('%H:%M:%S')}",
        border_style="blue"
    )

def main():
    target = 5000
    if len(sys.argv) > 1:
        target = int(sys.argv[1])
    
    console.print("[bold cyan]📊 Video Analysis Progress Tracker[/bold cyan]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    
    try:
        with Live(console=console, refresh_per_second=0.5) as live:
            while True:
                stats = get_stats()
                display = create_display(stats, target=target)
                live.update(display)
                
                # Check if complete
                if stats['success'] >= target:
                    console.print("\n[bold green]✅ Processing complete![/bold green]")
                    break
                
                time.sleep(5)  # Update every 5 seconds
                
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped tracking (batch continues in background)[/yellow]")

if __name__ == "__main__":
    main()


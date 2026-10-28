#!/usr/bin/env python3
"""Test video content analysis on sample videos."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from src.video_analysis.downloader import VideoDownloader
from src.video_analysis.extractor import VideoFeatureExtractor

console = Console()


def test_video_analysis(video_id: str, use_whisper: bool = True):
    """Test video analysis on a single video."""
    
    console.print(Panel.fit(f"🎬 Analyzing Video: {video_id}", style="bold cyan"))
    console.print(f"[dim]https://youtube.com/watch?v={video_id}[/dim]\n")
    
    # Initialize components
    downloader = VideoDownloader(max_duration=60)  # First 60 seconds
    extractor = VideoFeatureExtractor(use_whisper=use_whisper, whisper_model="base")
    
    try:
        # Download video
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Downloading video (first 60s)...", total=None)
            result = downloader.download(video_id, include_audio=True)
            progress.update(task, completed=True)
        
        if not result.success:
            console.print(f"[red]✗ Download failed: {result.error}[/red]")
            return None
        
        console.print(f"[green]✓ Downloaded: {result.video_path}[/green]")
        if result.audio_path:
            console.print(f"[green]✓ Audio extracted: {result.audio_path}[/green]")
        
        # Extract features
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Extracting video features...", total=None)
            features = extractor.extract(result.video_path, result.audio_path)
            progress.update(task, completed=True)
        
        # Display results
        console.print("\n")
        
        # Hook Features
        table = Table(title="🎣 Hook Features (First 10s)", show_header=True)
        table.add_column("Feature", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Analysis", style="yellow")
        
        face_time = features.hook_face_appears_seconds
        if face_time is not None and face_time < 3:
            face_analysis = "✅ Face appears quickly - good hook!"
        elif face_time is not None and face_time < 10:
            face_analysis = "🟡 Face appears, but could be faster"
        else:
            face_analysis = "🔴 No face in first 10s - consider adding"
        table.add_row("Face appears at", f"{face_time:.1f}s" if face_time else "Never", face_analysis)
        
        cuts = features.hook_scene_changes_count
        if cuts >= 3:
            cuts_analysis = "✅ Dynamic editing - keeps attention"
        elif cuts >= 1:
            cuts_analysis = "🟡 Some cuts - could be more dynamic"
        else:
            cuts_analysis = "🔴 No cuts - might lose viewers"
        table.add_row("Scene cuts (10s)", str(cuts), cuts_analysis)
        
        motion = features.hook_avg_motion
        if motion > 0.05:
            motion_analysis = "✅ High motion/action"
        elif motion > 0.02:
            motion_analysis = "🟡 Moderate motion"
        else:
            motion_analysis = "🔴 Low motion - could be boring"
        table.add_row("Motion level", f"{motion:.3f}", motion_analysis)
        
        console.print(table)
        
        # Visual Features
        table = Table(title="👁️ Visual Quality", show_header=True)
        table.add_column("Feature", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total scene cuts", str(features.total_scene_changes))
        table.add_row("Avg scene duration", f"{features.avg_scene_duration:.1f}s")
        table.add_row("Brightness", f"{features.avg_brightness:.2f}")
        table.add_row("Sharpness", f"{features.avg_sharpness:.2f}")
        table.add_row("Face screen time", f"{features.face_screen_time_ratio:.1%}")
        
        console.print(table)
        
        # Audio Features
        table = Table(title="🔊 Audio Analysis", show_header=True)
        table.add_column("Feature", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Energy level", f"{features.audio_energy_mean:.3f}")
        table.add_row("Energy variance", f"{features.audio_energy_variance:.4f}")
        table.add_row("Tempo (BPM)", f"{features.audio_tempo:.0f}")
        table.add_row("Has music intro", "Yes" if features.has_music_intro else "No")
        table.add_row("Intro duration", f"{features.intro_duration_seconds:.1f}s")
        table.add_row("Energy ramp-up", f"{features.energy_ramp_up:+.3f}")
        
        console.print(table)
        
        # Transcript Features
        if features.transcript:
            table = Table(title="💬 Speech Analysis", show_header=True)
            table.add_column("Feature", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Word count", str(features.word_count))
            table.add_row("Words per minute", f"{features.words_per_minute:.0f}")
            table.add_row("Questions asked", str(features.question_count))
            table.add_row("Call to actions", str(features.call_to_action_count))
            table.add_row("Hook words (10s)", str(features.hook_words_in_first_10s))
            table.add_row("Sentiment", f"{features.transcript_sentiment:+.2f}")
            
            console.print(table)
            
            console.print("\n[bold]📝 First 200 chars of transcript:[/bold]")
            console.print(f"[dim]{features.transcript[:200]}...[/dim]")
        
        # Feature vector for ML
        feature_vector = extractor.get_feature_vector(features)
        feature_names = extractor.get_feature_names()
        
        console.print("\n[bold]🧠 ML Feature Vector:[/bold]")
        for name, value in zip(feature_names, feature_vector):
            console.print(f"  {name}: {value:.3f}")
        
        return features
        
    finally:
        # Cleanup
        downloader.cleanup(video_id)
        console.print("\n[dim]Cleaned up temporary files[/dim]")


def main():
    console.print(Panel.fit("🎬 VIDEO CONTENT ANALYSIS TEST", style="bold magenta"))
    
    # Test videos - mix of different styles
    test_videos = [
        ("dQw4w9WgXcQ", "Rick Astley - Never Gonna Give You Up (music video)"),
        # Add more test videos here
    ]
    
    # Let user choose or use first one
    if len(sys.argv) > 1:
        video_id = sys.argv[1]
        console.print(f"[cyan]Testing custom video: {video_id}[/cyan]")
    else:
        video_id = test_videos[0][0]
        console.print(f"[cyan]Testing default video: {test_videos[0][1]}[/cyan]")
    
    # Ask about Whisper
    use_whisper = True
    console.print("\n[yellow]Note: Whisper transcription will be used for speech analysis.[/yellow]")
    console.print("[yellow]This may take 1-2 minutes for the first run (model download).[/yellow]\n")
    
    features = test_video_analysis(video_id, use_whisper=use_whisper)
    
    if features:
        console.print("\n[bold green]✅ Video analysis complete![/bold green]")
    else:
        console.print("\n[bold red]❌ Video analysis failed[/bold red]")


if __name__ == "__main__":
    main()


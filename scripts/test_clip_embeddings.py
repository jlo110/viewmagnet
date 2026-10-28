#!/usr/bin/env python3
"""Test CLIP embeddings impact on model accuracy with progress tracking."""

import clip
import torch
import numpy as np
import requests
from PIL import Image
from io import BytesIO
from sqlalchemy import and_, func
from sklearn.model_selection import train_test_split
import lightgbm as lgb
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.console import Console
from rich.panel import Panel
import json
import warnings
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session

warnings.filterwarnings('ignore')

console = Console()

def get_clip_embedding(model, preprocess, device, thumbnail_url):
    """Get CLIP embedding for a thumbnail URL."""
    try:
        response = requests.get(thumbnail_url, timeout=5)
        if response.status_code == 200:
            image = Image.open(BytesIO(response.content)).convert('RGB')
            image_input = preprocess(image).unsqueeze(0).to(device)
            with torch.no_grad():
                embedding = model.encode_image(image_input)
            return embedding.cpu().numpy().flatten()
    except Exception:
        pass
    return None


def main():
    console.print(Panel.fit("🎨 CLIP EMBEDDINGS TEST", style="bold magenta"))
    
    # Load CLIP
    console.print("\n[yellow]Loading CLIP model...[/yellow]")
    device = 'cpu'
    model, preprocess = clip.load('ViT-B/32', device=device)
    model.eval()
    console.print("[green]✓ CLIP model loaded[/green]")
    
    # Get videos
    console.print("\n[yellow]Fetching videos from database...[/yellow]")
    
    with get_session() as session:
        # First, get ALL videos to calculate proper hit rates
        all_videos = session.query(
            Video.channel_id, Video.view_count, Channel.avg_views_per_video
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).filter(Channel.avg_views_per_video > 0).all()
        
        # Calculate global hit rates per channel
        channel_perfs = {}
        for cid, views, avg in all_videos:
            if cid not in channel_perfs:
                channel_perfs[cid] = {'total': 0, 'hits': 0}
            channel_perfs[cid]['total'] += 1
            if views >= avg:
                channel_perfs[cid]['hits'] += 1
        hit_rates = {cid: p['hits']/max(p['total'],1) for cid, p in channel_perfs.items()}
        
        console.print(f"[cyan]Calculated hit rates for {len(hit_rates):,} channels[/cyan]")
        
        # Now get sample with thumbnails - random sample to get better class balance
        results = session.query(
            Video.video_id, Video.view_count, Video.channel_id, Video.thumbnail_url,
            Video.description, Video.tags, Video.title,
            Channel.avg_views_per_video, Channel.subscriber_count, Channel.size_tier,
            VideoFeatures.face_count, VideoFeatures.has_face, VideoFeatures.brightness,
            VideoFeatures.saturation, VideoFeatures.has_text, VideoFeatures.title_char_length,
            VideoFeatures.title_emotional_score,
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).filter(and_(
            Video.view_count >= 100, 
            VideoFeatures.thumbnail_processed == True,
            Channel.avg_views_per_video > 0, 
            Video.thumbnail_url.isnot(None)
        )).order_by(func.random()).limit(2000).all()
        
        console.print(f"[green]✓ Got {len(results):,} videos[/green]")
        
        size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
        
        # Process videos with progress bar
        X_base, X_clip, y = [], [], []
        processed = 0
        failed = 0
        target_count = 1200  # Process 1200 videos for testing
        
        console.print(f"\n[yellow]Extracting CLIP embeddings for {target_count} videos...[/yellow]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Processing thumbnails...", total=target_count)
            
            for r in results:
                if processed >= target_count:
                    break
                    
                video_id, views, channel_id, thumb_url, desc, tags_str, title, avg_views, \
                subs, size, face_count, has_face, bright, sat, has_text, title_len, emo_score = r
                
                if avg_views <= 0:
                    continue
                
                # Get CLIP embedding
                clip_emb = get_clip_embedding(model, preprocess, device, thumb_url)
                if clip_emb is None:
                    failed += 1
                    progress.update(task, advance=1, description=f"[cyan]Processing... ({failed} failed)")
                    continue
                
                try:
                    tags = json.loads(tags_str) if tags_str else []
                except:
                    tags = []
                
                ratio = views / avg_views
                label = 1 if ratio >= 1.0 else 0
                
                # Base features
                base_vec = [
                    face_count or 0, 1 if has_face else 0, bright or 0.5, sat or 0.5,
                    1 if has_text else 0, title_len or 50, emo_score or 0,
                    len(desc.split()) if desc else 0, len(tags),
                    np.log1p(subs or 10000), size_map.get(size, 2),
                    hit_rates.get(channel_id, 0.5), np.log1p(avg_views),
                ]
                
                X_base.append(base_vec)
                X_clip.append(np.concatenate([base_vec, clip_emb]))
                y.append(label)
                
                processed += 1
                progress.update(task, advance=1, description=f"[cyan]Processing... ({failed} failed)")
        
        console.print(f"\n[green]✓ Processed: {processed}, Failed: {failed}[/green]")
        
        X_base = np.array(X_base)
        X_clip = np.array(X_clip)
        y = np.array(y)
        
        # Balance classes
        pos_idx = np.where(y == 1)[0]
        neg_idx = np.where(y == 0)[0]
        np.random.seed(42)
        min_size = min(len(pos_idx), len(neg_idx))
        idx = np.concatenate([
            np.random.choice(pos_idx, min_size, replace=False),
            np.random.choice(neg_idx, min_size, replace=False)
        ])
        
        X_base_bal = X_base[idx]
        X_clip_bal = X_clip[idx]
        y_bal = y[idx]
        
        console.print(f"[cyan]Balanced dataset: {len(y_bal):,} samples[/cyan]")
        
        # Split
        X_base_train, X_base_test, X_clip_train, X_clip_test, y_train, y_test = train_test_split(
            X_base_bal, X_clip_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
        )
        
        console.print("\n[yellow]Training models...[/yellow]")
        
        params = {'objective': 'binary', 'metric': 'auc', 'num_leaves': 63,
                  'learning_rate': 0.05, 'verbose': -1, 'n_jobs': -1}
        
        # Base model
        train_base = lgb.Dataset(X_base_train, label=y_train)
        model_base = lgb.train(params, train_base, 200)
        probs_base = model_base.predict(X_base_test)
        acc_base = ((probs_base > 0.5) == y_test).mean()
        
        # CLIP model
        train_clip = lgb.Dataset(X_clip_train, label=y_train)
        model_clip = lgb.train(params, train_clip, 200)
        probs_clip = model_clip.predict(X_clip_test)
        acc_clip = ((probs_clip > 0.5) == y_test).mean()
        
        # Results
        console.print("\n" + "=" * 70)
        console.print(Panel.fit("📊 RESULTS: CLIP Embeddings (512-dim)", style="bold green"))
        console.print("=" * 70)
        
        console.print(f"\n  Base model (13 features):     [yellow]{acc_base*100:.2f}%[/yellow]")
        console.print(f"  + CLIP embeddings (525 feat): [green]{acc_clip*100:.2f}%[/green]")
        
        diff = (acc_clip - acc_base) * 100
        color = "green" if diff > 0 else "red"
        console.print(f"  Improvement:                  [{color}]{diff:+.2f}%[/{color}]")
        
        # Top features
        console.print("\n[cyan]📈 Top Feature Importances:[/cyan]")
        importance = model_clip.feature_importance()
        base_names = ['face_count', 'has_face', 'brightness', 'saturation', 'has_text',
                      'title_len', 'emo_score', 'desc_words', 'tag_count', 'log_subs',
                      'size_tier', 'hit_rate', 'log_avg_views']
        feature_names = base_names + [f'clip_{i}' for i in range(512)]
        
        top_features = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)[:15]
        max_imp = max(importance) if max(importance) > 0 else 1
        
        for feat, imp in top_features:
            bar_len = int(imp / max_imp * 20) if max_imp > 0 else 0
            bar = '█' * bar_len
            marker = ' 🆕' if feat.startswith('clip_') else ''
            console.print(f"    {feat:<15} {bar} {imp}{marker}")


if __name__ == "__main__":
    main()


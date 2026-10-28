#!/usr/bin/env python3
"""
CLIP embeddings - Process in ULTRA small batches to avoid crashes.
Saves progress every batch so we can resume if it crashes.
"""
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gc
import numpy as np
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image
import time

print("🖼️ CLIP - Ultra Batch Mode")
print("="*50)

cache_dir = Path("data/cache")
cache_dir.mkdir(exist_ok=True)
output_file = cache_dir / "clip_embeddings.npy"
progress_file = cache_dir / "clip_progress.npy"

if output_file.exists():
    emb = np.load(output_file)
    print(f"✅ Already complete: {emb.shape}")
    exit(0)

# Load URLs
print("📊 Loading thumbnail URLs...")
from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

with get_session() as session:
    results = session.query(Video.thumbnail_url
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0,
                Channel.subscriber_count > 1000).all()

urls = [r[0] for r in results]
total = len(urls)
print(f"   {total:,} thumbnails")

# Check for previous progress
start_idx = 0
existing_embeddings = []
if progress_file.exists():
    existing = np.load(progress_file)
    start_idx = len(existing)
    existing_embeddings = list(existing)
    print(f"   Resuming from {start_idx:,}")

if start_idx >= total:
    final = np.array(existing_embeddings)
    np.save(output_file, final)
    print(f"✅ Complete! Saved {final.shape}")
    exit(0)

# Load CLIP
print("📦 Loading CLIP (CPU)...")
import torch
torch.set_num_threads(1)
device = "cpu"

# Try loading CLIP
try:
    import clip
    model, preprocess = clip.load("ViT-B/32", device=device)
    print("   CLIP loaded")
except Exception as e:
    print(f"❌ CLIP failed: {e}")
    exit(1)

# Process ONE at a time
print(f"🔄 Processing from {start_idx} to {total}...")
batch_embeddings = existing_embeddings.copy()
failed = 0

for i in range(start_idx, total):
    url = urls[i]
    
    try:
        if url:
            response = requests.get(url, timeout=5)
            img = Image.open(BytesIO(response.content)).convert("RGB")
            img_tensor = preprocess(img).unsqueeze(0).to(device)
            
            with torch.no_grad():
                emb = model.encode_image(img_tensor).cpu().numpy().flatten()
            
            del img, img_tensor
        else:
            emb = np.zeros(512)
    except Exception as e:
        emb = np.zeros(512)
        failed += 1
    
    batch_embeddings.append(emb)
    
    # Save progress every 500
    if (i + 1) % 500 == 0:
        progress = np.array(batch_embeddings)
        np.save(progress_file, progress)
        pct = (i + 1) / total * 100
        print(f"   {i+1:,}/{total:,} ({pct:.1f}%) saved - {failed} failed")
        gc.collect()
    
    # Brief pause every 100 to avoid memory pressure
    if (i + 1) % 100 == 0:
        gc.collect()
        time.sleep(0.1)

# Final save
final = np.array(batch_embeddings)
np.save(output_file, final)
print(f"\n💾 Complete! Shape: {final.shape}")
print(f"   Failed: {failed}")

# Cleanup progress file
if progress_file.exists():
    progress_file.unlink()





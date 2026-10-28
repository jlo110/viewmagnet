#!/usr/bin/env python3
"""Generate CLIP embeddings for thumbnails - CPU only, minimal memory."""
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

print("🖼️ CLIP Thumbnail Embeddings Generator")
print("="*50)

cache_dir = Path("data/cache")
cache_dir.mkdir(exist_ok=True)
output_file = cache_dir / "clip_embeddings.npy"

if output_file.exists():
    print(f"✅ Already exists: {output_file}")
    emb = np.load(output_file)
    print(f"   Shape: {emb.shape}")
    exit(0)

# Load CLIP on CPU
print("📦 Loading CLIP model (CPU)...")
import torch
torch.set_num_threads(1)

import clip
device = "cpu"  # Force CPU to avoid MPS issues
model, preprocess = clip.load("ViT-B/32", device=device)
print(f"   CLIP loaded on {device}")

# Get thumbnail URLs
print("📊 Loading thumbnail URLs...")
from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

with get_session() as session:
    results = session.query(Video.thumbnail_url
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0,
                Channel.subscriber_count > 1000).all()

thumbnail_urls = [r[0] for r in results]
total = len(thumbnail_urls)
print(f"   {total:,} thumbnails")

# Process one at a time to minimize memory
print("🔄 Generating embeddings...")
all_embeddings = []
failed = 0

for i, url in enumerate(thumbnail_urls):
    try:
        if url:
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGB")
            img_tensor = preprocess(img).unsqueeze(0).to(device)
            
            with torch.no_grad():
                emb = model.encode_image(img_tensor).cpu().numpy().flatten()
        else:
            emb = np.zeros(512)
    except Exception as e:
        emb = np.zeros(512)
        failed += 1
    
    all_embeddings.append(emb)
    
    if (i + 1) % 1000 == 0 or i + 1 == total:
        pct = (i + 1) / total * 100
        print(f"   {i+1:,}/{total:,} ({pct:.1f}%) - {failed} failed")
        gc.collect()

embeddings = np.array(all_embeddings)
print(f"   Final shape: {embeddings.shape}")
print(f"   Total failed: {failed}")

# Save
np.save(output_file, embeddings)
print(f"💾 Saved to {output_file}")





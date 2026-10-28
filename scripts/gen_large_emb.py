#!/usr/bin/env python3
"""Generate large embeddings separately - minimal script."""
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gc
import numpy as np
from pathlib import Path

print("🧠 Large Embeddings Generator")
print("="*50)

cache_dir = Path("data/cache")
cache_dir.mkdir(exist_ok=True)
output_file = cache_dir / "large_embeddings.npy"

if output_file.exists():
    print(f"✅ Already exists: {output_file}")
    emb = np.load(output_file)
    print(f"   Shape: {emb.shape}")
    exit(0)

# Load titles
print("📊 Loading titles from database...")
from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

with get_session() as session:
    titles = [r[0] for r in session.query(Video.title
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0, 
                Channel.subscriber_count > 1000).all()]

total = len(titles)
print(f"   {total:,} titles")

# Load model
print("📦 Loading embedding model...")
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-mpnet-base-v2')

# Generate in very small batches
print("🔄 Generating embeddings...")
batch_size = 16
all_embeddings = []

for i in range(0, total, batch_size):
    batch = titles[i:i+batch_size]
    emb = model.encode(batch, show_progress_bar=False, convert_to_numpy=True)
    all_embeddings.append(emb)
    
    if (i + batch_size) % 2000 == 0 or i + batch_size >= total:
        pct = min(100, (i + batch_size) / total * 100)
        print(f"   {min(i+batch_size, total):,}/{total:,} ({pct:.1f}%)")
        gc.collect()

embeddings = np.vstack(all_embeddings)
print(f"   Final shape: {embeddings.shape}")

# Save
np.save(output_file, embeddings)
print(f"💾 Saved to {output_file}")





#!/usr/bin/env python3
"""
Experiment 7: CLIP Thumbnail Embeddings

CLIP understands what's IN the image semantically:
- "man excited holding iPhone" 
- "dramatic sunset landscape"
- "clickbait red arrow pointing"

This could add significant signal beyond basic features like brightness/faces.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import gc
import numpy as np
import pickle
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image

from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from xgboost import XGBClassifier

print("="*60)
print("🖼️ EXPERIMENT 7: CLIP Thumbnail Embeddings")
print("="*60)

cache_dir = Path("data/cache")
clip_cache = cache_dir / "clip_embeddings.npy"

# Load base data
print("\n📦 Loading base features...")
with open(cache_dir / "exp_features.pkl", 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']
title_emb = np.load(cache_dir / "exp_embeddings.npy")

print(f"   Base features: {X_base.shape}")
print(f"   Title embeddings: {title_emb.shape}")
print(f"   Samples: {len(y):,}")

# Check for cached CLIP embeddings
if clip_cache.exists():
    print("\n📦 Loading cached CLIP embeddings...")
    clip_emb = np.load(clip_cache)
    print(f"   Shape: {clip_emb.shape}")
else:
    print("\n🖼️ Generating CLIP embeddings for thumbnails...")
    
    # Load CLIP
    try:
        import torch
        import clip
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model, preprocess = clip.load("ViT-B/32", device=device)
        print(f"   CLIP loaded on {device}")
    except ImportError:
        print("❌ CLIP not installed. Install with: pip install git+https://github.com/openai/CLIP.git")
        exit(1)
    
    # Get thumbnail URLs from database
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
    print(f"   {total:,} thumbnails to process")
    
    # Process thumbnails in batches
    batch_size = 32
    all_embeddings = []
    failed = 0
    
    for i in range(0, total, batch_size):
        batch_urls = thumbnail_urls[i:i+batch_size]
        batch_images = []
        
        for url in batch_urls:
            try:
                if url:
                    response = requests.get(url, timeout=5)
                    img = Image.open(BytesIO(response.content)).convert("RGB")
                    img_tensor = preprocess(img).unsqueeze(0).to(device)
                    batch_images.append(img_tensor)
                else:
                    # Use zero embedding for missing thumbnails
                    batch_images.append(None)
            except:
                batch_images.append(None)
                failed += 1
        
        # Get embeddings for successful downloads
        batch_emb = []
        with torch.no_grad():
            for img_tensor in batch_images:
                if img_tensor is not None:
                    emb = model.encode_image(img_tensor).cpu().numpy().flatten()
                else:
                    emb = np.zeros(512)  # CLIP ViT-B/32 is 512 dims
                batch_emb.append(emb)
        
        all_embeddings.extend(batch_emb)
        
        if (i + batch_size) % 5000 == 0 or i + batch_size >= total:
            pct = min(100, (i + batch_size) / total * 100)
            print(f"   {min(i+batch_size, total):,}/{total:,} ({pct:.1f}%) - {failed} failed")
            gc.collect()
    
    clip_emb = np.array(all_embeddings)
    print(f"   Final shape: {clip_emb.shape}")
    print(f"   Failed downloads: {failed}")
    
    # Cache
    np.save(clip_cache, clip_emb)
    print(f"💾 Saved to {clip_cache}")

# Combine all features
print("\n🔗 Combining features...")
X_combined = np.hstack([X_base, title_emb, clip_emb])
print(f"   Total features: {X_combined.shape[1]}")
print(f"   (25 base + 384 title + 512 CLIP = 921)")

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X_combined, y, test_size=0.2, stratify=y, random_state=42
)

# Train XGBoost
print("\n🚀 Training XGBoost with CLIP embeddings...")
scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

model = XGBClassifier(
    n_estimators=300,
    max_depth=7,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos_weight,
    random_state=42,
    verbosity=0,
    use_label_encoder=False,
    eval_metric='logloss'
)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n{'='*60}")
print(f"✅ RESULTS: CLIP Thumbnail Embeddings")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")
print()

# Compare to baseline
baseline = 0.7458
improvement = (acc - baseline) * 100
if improvement > 0:
    print(f"   🎉 Improvement over XGBoost baseline: +{improvement:.2f}%")
else:
    print(f"   📊 Compared to XGBoost baseline: {improvement:.2f}%")

# Save result
results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp7 CLIP Thumbnails: {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Result saved to {results_file}")





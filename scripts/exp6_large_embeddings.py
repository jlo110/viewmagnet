#!/usr/bin/env python3
"""Experiment 6: Larger embeddings (768 dim) - memory optimized."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gc
import numpy as np
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

print("="*60)
print("📚 EXPERIMENT 6: Large Embeddings (768d mpnet)")
print("="*60)

cache_dir = Path("data/cache")
features_cache = cache_dir / "exp_features.pkl"
large_emb_cache = cache_dir / "large_embeddings.npy"

if not features_cache.exists():
    print("❌ Run exp1_baseline.py first!")
    exit(1)

print("📦 Loading base features...")
with open(features_cache, 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']

# Check for cached large embeddings
if large_emb_cache.exists():
    print("📦 Loading cached large embeddings...")
    embeddings = np.load(large_emb_cache)
else:
    print("🧠 Generating large embeddings (sequential, ~15 min)...")
    
    # Load titles from database
    from src.database.connection import get_session
    from src.database.models import Video, Channel, VideoFeatures
    
    with get_session() as session:
        titles = [r[0] for r in session.query(Video.title
            ).join(Channel, Video.channel_id == Channel.channel_id
            ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
            ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0, 
                    Channel.subscriber_count > 1000).all()]
    
    total = len(titles)
    print(f"   {total:,} titles to embed")
    
    # Load model with no multiprocessing
    import os
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    
    model = SentenceTransformer('all-mpnet-base-v2')
    
    # Process in chunks, save intermediate results
    chunk_size = 10000
    batch_size = 32  # Smaller batches
    temp_file = cache_dir / "large_emb_temp.npy"
    
    all_chunks = []
    
    for chunk_start in range(0, total, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total)
        chunk_titles = titles[chunk_start:chunk_end]
        
        chunk_embeddings = []
        for i in range(0, len(chunk_titles), batch_size):
            batch = chunk_titles[i:i+batch_size]
            # Sequential encoding, no parallelism
            emb = model.encode(batch, show_progress_bar=False, convert_to_numpy=True)
            chunk_embeddings.append(emb)
        
        chunk_arr = np.vstack(chunk_embeddings)
        all_chunks.append(chunk_arr)
        
        pct = chunk_end / total * 100
        print(f"   {chunk_end:,}/{total:,} ({pct:.1f}%)")
        
        # Save progress
        temp_embeddings = np.vstack(all_chunks)
        np.save(temp_file, temp_embeddings)
        
        gc.collect()
    
    embeddings = np.vstack(all_chunks)
    
    # Cache
    print("💾 Caching embeddings...")
    np.save(large_emb_cache, embeddings)
    
    del model, all_embeddings
    gc.collect()

print(f"   Embedding shape: {embeddings.shape}")

X = np.hstack([X_base, embeddings])
print(f"   Total features: {X.shape[1]}")

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

print("\n🚀 Training LightGBM with large embeddings...")
model = LGBMClassifier(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.1,
    class_weight='balanced',
    random_state=42,
    verbosity=-1
)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
acc = balanced_accuracy_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print(f"\n{'='*60}")
print(f"✅ RESULTS: Large Embeddings (768d)")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp6 Large Embeddings (768d): {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Result saved to {results_file}")


#!/usr/bin/env python3
"""
Experiment 8: Fine-Tuned Title Embeddings

Train sentence transformer specifically on viral vs non-viral titles.
This teaches the embeddings what makes a title successful.
"""
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pickle
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score, f1_score
from xgboost import XGBClassifier

print("="*60)
print("🎯 EXPERIMENT 8: Fine-Tuned Title Embeddings")
print("="*60)

cache_dir = Path("data/cache")
finetune_cache = cache_dir / "finetuned_embeddings.npy"

# Load base data
print("\n📦 Loading data...")
with open(cache_dir / "exp_features.pkl", 'rb') as f:
    cache = pickle.load(f)
X_base = cache['X_base']
y = cache['y']

# Load titles from database
from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

with get_session() as session:
    titles = [r[0] for r in session.query(Video.title
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(Video.view_count > 0, Channel.avg_views_per_video > 0,
                Channel.subscriber_count > 1000).all()]

print(f"   {len(titles):,} titles, {len(y):,} labels")

if finetune_cache.exists():
    print("\n📦 Loading cached fine-tuned embeddings...")
    finetuned_emb = np.load(finetune_cache)
else:
    print("\n🎯 Fine-tuning sentence transformer on viral/non-viral pairs...")
    
    from sentence_transformers import SentenceTransformer, InputExample, losses
    from torch.utils.data import DataLoader
    
    # Load base model
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Create training pairs: viral titles should be similar, non-viral different
    # Use contrastive learning approach
    train_examples = []
    
    # Get indices of viral (y=1) and non-viral (y=0)
    viral_idx = np.where(y == 1)[0]
    nonviral_idx = np.where(y == 0)[0]
    
    print(f"   Viral: {len(viral_idx):,}, Non-viral: {len(nonviral_idx):,}")
    
    # Create pairs (sample to avoid OOM)
    np.random.seed(42)
    n_pairs = min(20000, len(viral_idx))
    
    # Positive pairs: two viral titles (similar)
    for i in range(n_pairs):
        idx1 = np.random.choice(viral_idx)
        idx2 = np.random.choice(viral_idx)
        if idx1 != idx2:
            train_examples.append(InputExample(texts=[titles[idx1], titles[idx2]], label=0.8))
    
    # Negative pairs: viral + non-viral (different)
    for i in range(n_pairs):
        idx1 = np.random.choice(viral_idx)
        idx2 = np.random.choice(nonviral_idx)
        train_examples.append(InputExample(texts=[titles[idx1], titles[idx2]], label=0.2))
    
    print(f"   Created {len(train_examples):,} training pairs")
    
    # Train
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=32)
    train_loss = losses.CosineSimilarityLoss(model)
    
    print("   Training for 1 epoch...")
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=1,
        warmup_steps=100,
        show_progress_bar=True
    )
    
    # Generate embeddings with fine-tuned model
    print("\n🧠 Generating fine-tuned embeddings...")
    finetuned_emb = model.encode(titles, show_progress_bar=True, batch_size=256)
    
    # Cache
    np.save(finetune_cache, finetuned_emb)
    print(f"💾 Saved to {finetune_cache}")

print(f"   Embedding shape: {finetuned_emb.shape}")

# Combine features
X_combined = np.hstack([X_base, finetuned_emb])
print(f"   Total features: {X_combined.shape[1]}")

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X_combined, y, test_size=0.2, stratify=y, random_state=42
)

# Train
print("\n🚀 Training XGBoost with fine-tuned embeddings...")
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
print(f"✅ RESULTS: Fine-Tuned Embeddings")
print(f"{'='*60}")
print(f"   Balanced Accuracy: {acc*100:.2f}%")
print(f"   F1 Score: {f1:.3f}")

baseline = 0.7458
improvement = (acc - baseline) * 100
if improvement > 0:
    print(f"   🎉 Improvement: +{improvement:.2f}%")
else:
    print(f"   📊 vs baseline: {improvement:.2f}%")

# Save
results_file = cache_dir / "results.txt"
with open(results_file, 'a') as f:
    f.write(f"Exp8 Fine-Tuned Embeddings: {acc*100:.2f}% balanced acc, F1={f1:.3f}\n")
print(f"\n📝 Saved to {results_file}")





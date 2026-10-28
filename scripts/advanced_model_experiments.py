#!/usr/bin/env python3
"""
Advanced model experiments for ViewMagnet.

Tests:
1. CLIP thumbnail embeddings
2. Neural network for embeddings
3. Fine-tuned title embeddings (contrastive)
4. Multi-modal fusion
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pickle
import numpy as np
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

from sqlalchemy import func
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import balanced_accuracy_score, f1_score, make_scorer
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from lightgbm import LGBMClassifier
from sentence_transformers import SentenceTransformer

from src.database.connection import get_session
from src.database.models import Video, Channel, VideoFeatures

# Try to import CLIP
try:
    import torch
    from PIL import Image
    import clip
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False
    print("⚠️ CLIP not available. Install with: pip install git+https://github.com/openai/CLIP.git")


def load_data():
    """Load video data with features."""
    print("📊 Loading data from database...")
    
    with get_session() as session:
        query = session.query(
            Video.video_id,
            Video.title,
            Video.view_count,
            Video.channel_id,
            Video.published_at,
            Video.thumbnail_url,
            Channel.subscriber_count,
            Channel.avg_views_per_video,
            Channel.primary_category,
            VideoFeatures.title_char_length,
            VideoFeatures.title_word_count,
            VideoFeatures.title_has_number,
            VideoFeatures.title_has_question,
            VideoFeatures.title_has_exclamation,
            VideoFeatures.title_has_brackets,
            VideoFeatures.title_caps_ratio,
            VideoFeatures.title_emotional_score,
            VideoFeatures.title_sentiment,
            VideoFeatures.brightness,
            VideoFeatures.saturation,
            VideoFeatures.contrast,
            VideoFeatures.has_face,
            VideoFeatures.face_count,
            VideoFeatures.face_area_ratio,
            VideoFeatures.has_text,
            VideoFeatures.text_word_count,
            VideoFeatures.visual_complexity,
            VideoFeatures.edge_density,
            # Point-in-time features (no leakage)
            VideoFeatures.channel_momentum_at_upload,
            VideoFeatures.channel_engagement_trend_at_upload,
            VideoFeatures.channel_hit_rate_at_upload,
            VideoFeatures.channel_recent_avg_ratio_at_upload,
        ).join(
            Channel, Video.channel_id == Channel.channel_id
        ).join(
            VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).filter(
            Video.view_count > 0,
            Channel.avg_views_per_video > 0,
            Channel.subscriber_count > 1000,
        ).all()
        
        print(f"   Loaded {len(query):,} videos")
        
        columns = [
            'video_id', 'title', 'view_count', 'channel_id', 'published_at', 'thumbnail_url',
            'subscriber_count', 'avg_views_per_video', 'category',
            'title_len', 'title_words', 'has_number', 'has_question',
            'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
            'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
            'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
            'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio'
        ]
        
        df = pd.DataFrame(query, columns=columns)
        
    return df


def prepare_base_features(df):
    """Prepare base features and target (NO leaked channel features)."""
    print("📋 Preparing base features (NO leakage)...")
    
    # Performance ratio using channel average from database
    df['perf_ratio'] = df['view_count'] / df['avg_views_per_video'].clip(lower=1)
    
    # Target: Top 30% globally
    threshold = df['perf_ratio'].quantile(0.70)
    df['target'] = (df['perf_ratio'] >= threshold).astype(int)
    
    print(f"   Target distribution: {df['target'].mean()*100:.1f}% positive")
    
    # Channel size features
    df['log_subs'] = np.log1p(df['subscriber_count'])
    df['log_channel_avg'] = np.log1p(df['avg_views_per_video'])
    
    # Base feature columns (NO leaked hit_rate/avg_ratio/std_ratio)
    feature_cols = [
        'title_len', 'title_words', 'has_number', 'has_question',
        'has_exclamation', 'has_brackets', 'caps_ratio', 'emotional', 'sentiment',
        'brightness', 'saturation', 'contrast', 'has_face', 'face_count',
        'face_area_ratio', 'has_text', 'text_words', 'visual_complexity', 'edge_density',
        # Only point-in-time features (no leakage)
        'pit_momentum', 'pit_engagement_trend', 'pit_hit_rate', 'pit_recent_ratio',
        'log_subs', 'log_channel_avg',
    ]
    
    # Booleans to int
    for col in ['has_number', 'has_question', 'has_exclamation', 'has_brackets', 'has_face', 'has_text']:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
    
    # Fill NaN
    for col in feature_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    
    feature_cols = [c for c in feature_cols if c in df.columns]
    
    return df, feature_cols


def generate_title_embeddings(titles: list) -> np.ndarray:
    """Generate title embeddings."""
    print("🧠 Generating title embeddings...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    embeddings = []
    batch_size = 1000
    for i in range(0, len(titles), batch_size):
        batch = titles[i:i+batch_size]
        batch_emb = model.encode(batch, show_progress_bar=False)
        embeddings.append(batch_emb)
        if (i + batch_size) % 10000 == 0:
            print(f"   {min(i+batch_size, len(titles)):,}/{len(titles):,}")
    
    return np.vstack(embeddings)


def experiment_1_baseline_no_leakage(df, feature_cols):
    """Baseline with NO data leakage - honest evaluation."""
    print("\n" + "="*60)
    print("📊 EXPERIMENT 1: Baseline (No Leakage)")
    print("="*60)
    
    # Generate embeddings
    title_embeddings = generate_title_embeddings(df['title'].tolist())
    
    # Combine features
    X_base = df[feature_cols].values
    X = np.hstack([X_base, title_embeddings])
    y = df['target'].values
    
    print(f"   Features: {X.shape[1]} ({len(feature_cols)} base + {title_embeddings.shape[1]} title emb)")
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Train LightGBM
    model = LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        class_weight='balanced',
        random_state=42,
        verbosity=-1,
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = balanced_accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    print(f"\n   ✅ Balanced Accuracy: {acc*100:.2f}%")
    print(f"   ✅ F1 Score: {f1:.3f}")
    
    return acc, title_embeddings


def experiment_2_neural_network(df, feature_cols, title_embeddings):
    """Neural network - better at handling embeddings."""
    print("\n" + "="*60)
    print("🧠 EXPERIMENT 2: Neural Network")
    print("="*60)
    
    # Combine features
    X_base = df[feature_cols].values
    X = np.hstack([X_base, title_embeddings])
    y = df['target'].values
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Scale for neural network
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train MLP
    model = MLPClassifier(
        hidden_layer_sizes=(256, 128, 64),
        activation='relu',
        learning_rate_init=0.001,
        max_iter=300,
        early_stopping=True,
        random_state=42,
    )
    
    print("   Training neural network...")
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    acc = balanced_accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    print(f"\n   ✅ Balanced Accuracy: {acc*100:.2f}%")
    print(f"   ✅ F1 Score: {f1:.3f}")
    
    return acc


def experiment_3_larger_embeddings(df, feature_cols):
    """Test larger, more powerful embeddings - MEMORY OPTIMIZED."""
    print("\n" + "="*60)
    print("📚 EXPERIMENT 3: Larger Embeddings (all-mpnet-base-v2)")
    print("="*60)
    
    import gc
    from pathlib import Path
    
    cache_file = Path("data/cache/large_embeddings.npy")
    cache_file.parent.mkdir(exist_ok=True)
    
    # Check if we have cached embeddings
    if cache_file.exists():
        print("   Loading cached embeddings...")
        large_embeddings = np.load(cache_file)
        print(f"   Loaded {large_embeddings.shape[0]:,} embeddings ({large_embeddings.shape[1]} dims)")
    else:
        print("   Loading larger embedding model...")
        model_emb = SentenceTransformer('all-mpnet-base-v2')  # 768 dims
        
        print("   Generating embeddings (saving chunks to avoid OOM)...")
        titles = df['title'].tolist()
        total = len(titles)
        batch_size = 100  # Very small batches
        chunk_size = 10000  # Save every 10K
        
        all_embeddings = []
        chunk_embeddings = []
        
        for i in range(0, total, batch_size):
            batch = titles[i:i+batch_size]
            batch_emb = model_emb.encode(batch, show_progress_bar=False)
            chunk_embeddings.append(batch_emb)
            
            # Progress every 5000
            if (i + batch_size) % 5000 == 0:
                pct = (i + batch_size) / total * 100
                print(f"   {min(i+batch_size, total):,}/{total:,} ({pct:.1f}%)")
            
            # Save chunk to free memory
            if len(chunk_embeddings) * batch_size >= chunk_size:
                chunk_arr = np.vstack(chunk_embeddings)
                all_embeddings.append(chunk_arr)
                chunk_embeddings = []
                gc.collect()
        
        # Don't forget remaining
        if chunk_embeddings:
            all_embeddings.append(np.vstack(chunk_embeddings))
        
        large_embeddings = np.vstack(all_embeddings)
        
        # Cache for next time
        np.save(cache_file, large_embeddings)
        print(f"   Saved to cache: {cache_file}")
        
        # Free memory
        del model_emb, all_embeddings, chunk_embeddings
        gc.collect()
    
    print(f"   Embedding dimensions: {large_embeddings.shape[1]}")
    
    # Combine
    X_base = df[feature_cols].values
    X = np.hstack([X_base, large_embeddings])
    y = df['target'].values
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Train
    model = LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        class_weight='balanced',
        random_state=42,
        verbosity=-1,
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = balanced_accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    print(f"\n   ✅ Balanced Accuracy: {acc*100:.2f}%")
    print(f"   ✅ F1 Score: {f1:.3f}")
    
    return acc


def experiment_4_category_embeddings(df, feature_cols, title_embeddings):
    """Add category as embedding."""
    print("\n" + "="*60)
    print("🏷️ EXPERIMENT 4: Category Embeddings")
    print("="*60)
    
    # Generate category embeddings
    model_emb = SentenceTransformer('all-MiniLM-L6-v2')
    categories = df['category'].fillna('unknown').tolist()
    category_embeddings = model_emb.encode(categories, show_progress_bar=False)
    
    print(f"   Category embedding dims: {category_embeddings.shape[1]}")
    
    # Combine all
    X_base = df[feature_cols].values
    X = np.hstack([X_base, title_embeddings, category_embeddings])
    y = df['target'].values
    
    print(f"   Total features: {X.shape[1]}")
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Train
    model = LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        class_weight='balanced',
        random_state=42,
        verbosity=-1,
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = balanced_accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    print(f"\n   ✅ Balanced Accuracy: {acc*100:.2f}%")
    print(f"   ✅ F1 Score: {f1:.3f}")
    
    return acc


def experiment_5_deep_neural_network(df, feature_cols, title_embeddings):
    """Deeper neural network with dropout."""
    print("\n" + "="*60)
    print("🔮 EXPERIMENT 5: Deep Neural Network (PyTorch)")
    print("="*60)
    
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        print("   ⚠️ PyTorch not available, skipping...")
        return None
    
    print("   PyTorch available, training...")
    
    # Combine features
    X_base = df[feature_cols].values
    X = np.hstack([X_base, title_embeddings])
    y = df['target'].values
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    
    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Convert to tensors
    X_train_t = torch.FloatTensor(X_train_scaled)
    y_train_t = torch.LongTensor(y_train)
    X_test_t = torch.FloatTensor(X_test_scaled)
    y_test_t = torch.LongTensor(y_test)
    
    # Dataset
    train_dataset = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    
    # Model
    input_dim = X_train_scaled.shape[1]
    
    class DeepNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(input_dim, 512),
                nn.ReLU(),
                nn.BatchNorm1d(512),
                nn.Dropout(0.3),
                
                nn.Linear(512, 256),
                nn.ReLU(),
                nn.BatchNorm1d(256),
                nn.Dropout(0.3),
                
                nn.Linear(256, 128),
                nn.ReLU(),
                nn.BatchNorm1d(128),
                nn.Dropout(0.2),
                
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Dropout(0.2),
                
                nn.Linear(64, 2),
            )
        
        def forward(self, x):
            return self.net(x)
    
    model = DeepNet()
    
    # Class weights for imbalance
    pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    weights = torch.FloatTensor([1.0, pos_weight])
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    
    # Train
    print("   Training deep neural network...")
    model.train()
    for epoch in range(50):
        total_loss = 0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if (epoch + 1) % 10 == 0:
            print(f"   Epoch {epoch+1}/50, Loss: {total_loss/len(train_loader):.4f}")
    
    # Evaluate
    model.eval()
    with torch.no_grad():
        outputs = model(X_test_t)
        _, y_pred = torch.max(outputs, 1)
        y_pred = y_pred.numpy()
    
    acc = balanced_accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    
    print(f"\n   ✅ Balanced Accuracy: {acc*100:.2f}%")
    print(f"   ✅ F1 Score: {f1:.3f}")
    
    return acc


def main():
    print("="*70)
    print("🚀 ADVANCED MODEL EXPERIMENTS FOR ViewMagnet")
    print("="*70)
    print()
    
    # Load data
    df = load_data()
    df, feature_cols = prepare_base_features(df)
    
    results = {}
    
    # Experiment 1: Baseline (no leakage)
    acc1, title_embeddings = experiment_1_baseline_no_leakage(df, feature_cols)
    results['Baseline (No Leakage)'] = acc1
    
    # Experiment 2: Neural Network
    acc2 = experiment_2_neural_network(df, feature_cols, title_embeddings)
    results['Neural Network (MLP)'] = acc2
    
    # Experiment 3: Larger embeddings
    acc3 = experiment_3_larger_embeddings(df, feature_cols)
    results['Larger Embeddings (768d)'] = acc3
    
    # Experiment 4: Category embeddings
    acc4 = experiment_4_category_embeddings(df, feature_cols, title_embeddings)
    results['+ Category Embeddings'] = acc4
    
    # Experiment 5: Deep Neural Network
    acc5 = experiment_5_deep_neural_network(df, feature_cols, title_embeddings)
    if acc5:
        results['Deep Neural Network'] = acc5
    
    # Summary
    print("\n" + "="*70)
    print("📊 FINAL RESULTS SUMMARY")
    print("="*70)
    print()
    print("Model                          | Balanced Accuracy")
    print("-" * 55)
    
    for name, acc in sorted(results.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(acc * 30)
        print(f"{name:<30} | {acc*100:5.2f}% {bar}")
    
    print()
    best_name = max(results, key=results.get)
    best_acc = results[best_name]
    print(f"🏆 Best: {best_name} ({best_acc*100:.2f}%)")
    
    # Compare to claimed 74.5%
    print()
    print("📉 Note: Previous '74.5%' was inflated due to data leakage")
    print(f"   Honest baseline with same features: {acc1*100:.2f}%")
    

if __name__ == "__main__":
    main()


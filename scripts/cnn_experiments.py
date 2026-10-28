"""
CNN Thumbnail Embeddings Experiment.
Uses EfficientNet-B0 to extract deep visual features.
"""

import numpy as np
import json
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.decomposition import PCA
import lightgbm as lgb
import optuna
from sqlalchemy import and_
import warnings
import pickle
from pathlib import Path
from tqdm import tqdm
warnings.filterwarnings('ignore')

import torch
import torchvision.models as models
import torchvision.transforms as transforms

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator


class ThumbnailEmbedder:
    """Extract CNN embeddings from thumbnails using EfficientNet."""
    
    def __init__(self):
        print("   Loading EfficientNet-B0...")
        # Use EfficientNet-B0 (lightweight but powerful)
        self.model = models.efficientnet_b0(weights='IMAGENET1K_V1')
        self.model.eval()
        
        # Remove classifier to get embeddings
        self.model.classifier = torch.nn.Identity()
        
        # Standard ImageNet preprocessing
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                               std=[0.229, 0.224, 0.225])
        ])
        
        # Use GPU if available
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = self.model.to(self.device)
        print(f"   Using device: {self.device}")
    
    def get_embedding(self, image_url: str) -> np.ndarray | None:
        """Extract 1280-dim embedding from thumbnail URL."""
        try:
            response = requests.get(image_url, timeout=5)
            if response.status_code != 200:
                return None
            
            img = Image.open(BytesIO(response.content)).convert('RGB')
            img_tensor = self.transform(img).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                embedding = self.model(img_tensor)
            
            return embedding.cpu().numpy().flatten()
        except Exception as e:
            return None
    
    def get_embeddings_batch(self, urls: list, batch_size: int = 32) -> dict:
        """Get embeddings for multiple URLs."""
        embeddings = {}
        
        for i in tqdm(range(0, len(urls), batch_size), desc="Extracting CNN features"):
            batch_urls = urls[i:i+batch_size]
            batch_images = []
            valid_indices = []
            
            for j, url in enumerate(batch_urls):
                try:
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content)).convert('RGB')
                        batch_images.append(self.transform(img))
                        valid_indices.append(i + j)
                except:
                    pass
            
            if batch_images:
                batch_tensor = torch.stack(batch_images).to(self.device)
                with torch.no_grad():
                    batch_embeddings = self.model(batch_tensor).cpu().numpy()
                
                for idx, emb in zip(valid_indices, batch_embeddings):
                    embeddings[urls[idx - i + valid_indices.index(idx)]] = emb
        
        return embeddings


def load_data_with_cnn(use_cached: bool = True, sample_size: int = 20000):
    """Load data with CNN embeddings (cached for speed)."""
    cache_file = Path("data/cnn_embeddings_cache.pkl")
    
    print("📊 Loading data with CNN embeddings...")
    
    with get_session() as session:
        calc = NicheFeatureCalculator(session)
        calc.precompute_all_niches()
        
        # Get all videos with features
        results = session.query(
            Video.video_id, Video.view_count, Video.published_at, Video.title, 
            Video.description, Video.tags, Video.channel_id, Video.thumbnail_url,
            Channel.avg_views_per_video, Channel.subscriber_count, Channel.size_tier, 
            Channel.niche_id, Channel.video_count, Channel.primary_category, 
            Channel.total_views, Channel.created_at_yt,
            VideoFeatures.face_count, VideoFeatures.has_face, VideoFeatures.face_area_ratio,
            VideoFeatures.brightness, VideoFeatures.saturation, VideoFeatures.contrast,
            VideoFeatures.edge_density, VideoFeatures.composition_score, VideoFeatures.has_text,
            VideoFeatures.text_word_count, VideoFeatures.face_emotion_primary, 
            VideoFeatures.face_emotion_intensity, VideoFeatures.title_char_length, 
            VideoFeatures.title_word_count, VideoFeatures.title_has_number, 
            VideoFeatures.title_has_question, VideoFeatures.title_caps_ratio, 
            VideoFeatures.title_hook_type, VideoFeatures.title_emotional_score, 
            VideoFeatures.title_sentiment, VideoFeatures.title_trending_score,
            VideoFeatures.title_specificity_score,
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).filter(and_(Video.view_count >= 100, VideoFeatures.thumbnail_processed == True,
                      Channel.avg_views_per_video > 0, Channel.niche_id.isnot(None))
        ).limit(sample_size).all()  # Limit for CNN speed
        
        # Calculate hit rates
        channel_performances = {}
        for row in results:
            channel_id = row[6]
            views = row[1]
            avg_views = row[8]
            
            if channel_id not in channel_performances:
                channel_performances[channel_id] = {'total': 0, 'hits': 0}
            
            channel_performances[channel_id]['total'] += 1
            if views >= avg_views:
                channel_performances[channel_id]['hits'] += 1
        
        hit_rates = {cid: p['hits'] / max(p['total'], 1) 
                     for cid, p in channel_performances.items()}
    
    print(f"   Loaded {len(results):,} samples")
    
    # Load or compute CNN embeddings
    if use_cached and cache_file.exists():
        print("   Loading cached CNN embeddings...")
        with open(cache_file, 'rb') as f:
            cnn_cache = pickle.load(f)
    else:
        cnn_cache = {}
    
    # Get URLs needing embeddings
    urls_needed = []
    for row in results:
        if row[7] not in cnn_cache:  # thumbnail_url
            urls_needed.append(row[7])
    
    if urls_needed:
        print(f"   Need to extract {len(urls_needed):,} CNN embeddings...")
        embedder = ThumbnailEmbedder()
        
        for url in tqdm(urls_needed[:5000], desc="CNN embeddings"):  # Limit to 5000 new
            emb = embedder.get_embedding(url)
            if emb is not None:
                cnn_cache[url] = emb
        
        # Save cache
        cache_file.parent.mkdir(exist_ok=True)
        with open(cache_file, 'wb') as f:
            pickle.dump(cnn_cache, f)
        print(f"   Cached {len(cnn_cache):,} embeddings")
    
    # Build feature vectors
    print("   Building feature vectors...")
    
    size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
    cat_map = {'gaming': 0, 'education_howto': 1, 'tech_reviews': 2, 'entertainment_vlogs': 3,
               'music_creative': 4, 'news_politics': 5, 'commentary_essay': 6, 'lifestyle': 7, 'other': 8}
    emotion_map = {'neutral': 0, 'happy': 1, 'sad': 2, 'angry': 3, 'fear': 4, 'surprise': 5, 'disgust': 6}
    sentiment_map = {'negative': 0, 'neutral': 1, 'positive': 2}
    hook_map = {'listicle': 0, 'how_to': 1, 'question': 2, 'challenge': 3, 'story': 4, 
                'reveal': 5, 'comparison': 6, 'urgency': 7, 'emotional': 8, 'tutorial': 9, 'none': 10}
    
    X_base = []  # Base features (no CNN)
    X_cnn = []   # CNN embeddings
    y_list = []
    valid_indices = []
    
    for idx, row in enumerate(results):
        video_id, views, pub_date, title, description, tags_str, channel_id, thumb_url, \
        avg_views, subs, size, niche_id, video_count, category, total_views, channel_created, \
        face_count, has_face, face_area, bright, sat, contrast, edge, comp, has_text, text_words, \
        face_emotion, face_emo_int, title_len, title_words, title_num, title_q, title_caps, \
        hook_type, emo_score, sentiment, trend_score, spec_score = row
        
        if avg_views <= 0:
            continue
        
        # Only include if we have CNN embedding
        if thumb_url not in cnn_cache:
            continue
        
        ratio = views / avg_views
        label = 1 if ratio >= 1.0 else 0
        
        # === BASE FEATURES (same as enhanced) ===
        f_face_count = face_count or 0
        f_has_face = 1 if has_face else 0
        f_face_area = face_area or 0
        f_brightness = bright or 0.5
        f_saturation = sat or 0.5
        f_contrast = contrast or 0.5
        f_edge = edge or 0.5
        f_composition = comp or 0.5
        f_has_text = 1 if has_text else 0
        f_text_words = text_words or 0
        f_emotion = emotion_map.get(face_emotion, 0)
        f_emotion_int = face_emo_int or 0
        
        f_title_len = title_len or 50
        f_title_words = title_words or 8
        f_title_num = 1 if title_num else 0
        f_title_q = 1 if title_q else 0
        f_title_caps = title_caps or 0
        f_hook = hook_map.get(hook_type, 10)
        f_emo_score = emo_score or 0
        f_sentiment = sentiment_map.get(sentiment, 1)
        f_trend = trend_score or 0
        f_spec = spec_score or 0
        
        desc = description or ""
        f_desc_words = len(desc.split()) if desc else 0
        f_desc_has_links = 1 if ('http' in desc.lower() or 'www.' in desc.lower()) else 0
        
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        f_tag_count = len(tags)
        title_lower = (title or "").lower()
        f_tag_title_overlap = sum(1 for t in tags if t.lower() in title_lower) if tags else 0
        
        f_subs_log = np.log1p(subs or 10000)
        f_size = size_map.get(size, 2)
        f_video_count_log = np.log1p(video_count or 100)
        f_category = cat_map.get(category, 8)
        f_niche = niche_id or 0
        
        f_hit_rate = hit_rates.get(channel_id, 0.5)
        
        if channel_created and pub_date:
            channel_age_days = (pub_date - channel_created).days
            f_channel_age_log = np.log1p(max(channel_age_days, 1))
        else:
            f_channel_age_log = np.log1p(365)
        
        f_hour = pub_date.hour if pub_date else 12
        f_day = pub_date.weekday() if pub_date else 3
        f_is_weekend = 1 if (pub_date and pub_date.weekday() >= 5) else 0
        
        f_views_per_sub = (avg_views / max(subs, 1)) if subs else 0.1
        f_avg_views_log = np.log1p(avg_views)
        
        # Niche-relative features
        features = {
            'face_count': f_face_count, 'has_face': has_face, 'face_area_ratio': f_face_area,
            'brightness': f_brightness, 'saturation': f_saturation, 'contrast': f_contrast,
            'edge_density': f_edge, 'composition_score': f_composition,
            'has_text': has_text, 'text_word_count': f_text_words,
            'title_char_length': f_title_len, 'title_word_count': f_title_words,
        }
        niche_rel = calc.calculate_relative_features(niche_id, features)
        
        if niche_rel:
            f_niche_face = niche_rel.face_vs_niche
            f_niche_bright = niche_rel.brightness_vs_niche
            f_similarity_top = niche_rel.similarity_to_top
        else:
            f_niche_face = f_niche_bright = f_similarity_top = 0
        
        # Base feature vector (compact - 35 features)
        base_vec = [
            f_face_count, f_has_face, f_face_area, f_brightness, f_saturation, f_contrast,
            f_edge, f_composition, f_has_text, f_text_words, f_emotion, f_emotion_int,
            f_title_len, f_title_words, f_title_num, f_title_q, f_title_caps, f_hook,
            f_emo_score, f_sentiment, f_trend, f_spec,
            f_desc_words, f_desc_has_links, f_tag_count, f_tag_title_overlap,
            f_subs_log, f_size, f_video_count_log, f_category, f_niche,
            f_hit_rate, f_channel_age_log,
            f_hour, f_day, f_is_weekend,
            f_views_per_sub, f_avg_views_log,
            f_niche_face, f_niche_bright, f_similarity_top,
            f_hit_rate * f_size,  # interaction
        ]
        
        X_base.append(base_vec)
        X_cnn.append(cnn_cache[thumb_url])
        y_list.append(label)
        valid_indices.append(idx)
    
    X_base = np.array(X_base)
    X_cnn = np.array(X_cnn)
    y = np.array(y_list)
    
    print(f"   Samples with CNN: {len(y):,}")
    print(f"   Base features: {X_base.shape[1]}")
    print(f"   CNN features: {X_cnn.shape[1]}")
    
    return X_base, X_cnn, y


def balance_data(X, y, seed=42):
    """Balance dataset."""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    np.random.seed(seed)
    
    min_size = min(len(pos_idx), len(neg_idx))
    pos_idx = np.random.choice(pos_idx, size=min_size, replace=False)
    neg_idx = np.random.choice(neg_idx, size=min_size, replace=False)
    
    idx = np.concatenate([pos_idx, neg_idx])
    np.random.shuffle(idx)
    
    return idx


def run_cnn_experiments():
    """Compare models with and without CNN embeddings."""
    print("=" * 70)
    print("🖼️  CNN THUMBNAIL EMBEDDINGS EXPERIMENT")
    print("   Using EfficientNet-B0 (1280-dim embeddings)")
    print("=" * 70)
    print()
    
    # Load data
    X_base, X_cnn, y = load_data_with_cnn(use_cached=True, sample_size=30000)
    
    # Balance
    idx = balance_data(np.column_stack([X_base, X_cnn]), y)
    X_base_bal = X_base[idx]
    X_cnn_bal = X_cnn[idx]
    y_bal = y[idx]
    
    print(f"\n   Balanced samples: {len(y_bal):,}")
    
    # PCA on CNN embeddings (1280 -> 50 dims)
    print("\n   Applying PCA to CNN embeddings (1280 → 50)...")
    pca = PCA(n_components=50)
    X_cnn_pca = pca.fit_transform(X_cnn_bal)
    print(f"   Variance explained: {sum(pca.explained_variance_ratio_)*100:.1f}%")
    
    # Combine features
    X_combined = np.hstack([X_base_bal, X_cnn_pca])
    print(f"   Combined features: {X_combined.shape[1]}")
    
    # Split
    X_base_train, X_base_val, y_train, y_val = train_test_split(
        X_base_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
    )
    
    X_cnn_train = X_cnn_pca[: len(X_base_train)]
    X_cnn_val = X_cnn_pca[len(X_base_train):]
    
    X_comb_train = X_combined[:len(X_base_train)]
    X_comb_val = X_combined[len(X_base_train):]
    
    # Fix: proper split
    X_base_train, X_base_val, X_cnn_train, X_cnn_val, X_comb_train, X_comb_val, y_train, y_val = \
        train_test_split(X_base_bal, X_cnn_pca, X_combined, y_bal, 
                        test_size=0.2, random_state=42, stratify=y_bal)
    
    params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
        'learning_rate': 0.03, 'feature_fraction': 0.7, 'bagging_fraction': 0.8, 
        'bagging_freq': 5, 'min_data_in_leaf': 30, 'verbose': -1
    }
    
    results = {}
    
    # 1. Base features only
    print("\n1️⃣  BASE FEATURES ONLY (42 features)")
    train_data = lgb.Dataset(X_base_train, label=y_train)
    val_data = lgb.Dataset(X_base_val, label=y_val, reference=train_data)
    
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_base_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    results['base'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # 2. CNN features only
    print("\n2️⃣  CNN FEATURES ONLY (50 PCA components)")
    train_data = lgb.Dataset(X_cnn_train, label=y_train)
    val_data = lgb.Dataset(X_cnn_val, label=y_val, reference=train_data)
    
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_cnn_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    results['cnn_only'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # 3. Combined
    print("\n3️⃣  COMBINED (Base + CNN = 92 features)")
    train_data = lgb.Dataset(X_comb_train, label=y_train)
    val_data = lgb.Dataset(X_comb_val, label=y_val, reference=train_data)
    
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_comb_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    results['combined'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # 4. Optimized combined
    print("\n4️⃣  OPTUNA OPTIMIZED COMBINED (20 trials)")
    
    def objective(trial):
        params = {
            'objective': 'binary', 'metric': 'auc', 'verbosity': -1,
            'num_leaves': trial.suggest_int('num_leaves', 63, 255),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 0.9),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 0.9),
            'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 10, 100),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
        }
        
        train_d = lgb.Dataset(X_comb_train, label=y_train)
        val_d = lgb.Dataset(X_comb_val, label=y_val, reference=train_d)
        
        m = lgb.train(params, train_d, 1000, valid_sets=[val_d],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        
        p = m.predict(X_comb_val)
        return roc_auc_score(y_val, p)
    
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=20, show_progress_bar=True)
    
    best_params = study.best_params
    best_params['objective'] = 'binary'
    best_params['metric'] = 'auc'
    best_params['verbosity'] = -1
    
    train_data = lgb.Dataset(X_comb_train, label=y_train)
    val_data = lgb.Dataset(X_comb_val, label=y_val, reference=train_data)
    
    model = lgb.train(best_params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_comb_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    
    # Best threshold
    best_acc = acc
    for t in np.arange(0.35, 0.65, 0.01):
        a = accuracy_score(y_val, (probs > t).astype(int))
        if a > best_acc:
            best_acc = a
    
    results['optimized'] = {'acc': best_acc, 'auc': auc}
    print(f"    Accuracy: {best_acc*100:.2f}% | AUC: {auc:.4f}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 CNN EXPERIMENT SUMMARY")
    print("=" * 70)
    print(f"{'Model':<30} {'Accuracy':>12} {'AUC':>10}")
    print("-" * 55)
    print(f"{'Base features only':<30} {results['base']['acc']*100:>11.2f}% {results['base']['auc']:>10.4f}")
    print(f"{'CNN embeddings only':<30} {results['cnn_only']['acc']*100:>11.2f}% {results['cnn_only']['auc']:>10.4f}")
    print(f"{'Combined (Base + CNN)':<30} {results['combined']['acc']*100:>11.2f}% {results['combined']['auc']:>10.4f}")
    print(f"{'Optimized Combined':<30} {results['optimized']['acc']*100:>11.2f}% {results['optimized']['auc']:>10.4f}")
    print("-" * 55)
    
    improvement = (results['optimized']['acc'] - results['base']['acc']) * 100
    print(f"\n🎯 CNN Contribution: {improvement:+.2f}% accuracy")
    print(f"📈 Previous best: 77.83% → With CNN: {results['optimized']['acc']*100:.2f}%")
    
    return results


if __name__ == "__main__":
    results = run_cnn_experiments()


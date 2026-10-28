"""
Test CNN impact with available embeddings.
"""

import numpy as np
import json
import pickle
from pathlib import Path
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.decomposition import PCA
import lightgbm as lgb
from sqlalchemy import and_
import warnings
warnings.filterwarnings('ignore')

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator


def run_cnn_test():
    print("=" * 70)
    print("🧪 CNN IMPACT TEST")
    print("=" * 70)
    
    # Load CNN cache
    cache_file = Path("data/cnn_embeddings_cache.pkl")
    if not cache_file.exists():
        print("❌ No CNN cache found. Run cnn_batch_extractor.py first.")
        return
    
    with open(cache_file, 'rb') as f:
        cnn_cache = pickle.load(f)
    
    print(f"📂 Loaded {len(cnn_cache):,} CNN embeddings")
    
    # Load data
    print("\n📊 Loading data...")
    with get_session() as session:
        calc = NicheFeatureCalculator(session)
        calc.precompute_all_niches()
        
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
                      Channel.avg_views_per_video > 0, Channel.niche_id.isnot(None))).all()
        
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
    
    # Build features (only for videos with CNN)
    size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
    cat_map = {'gaming': 0, 'education_howto': 1, 'tech_reviews': 2, 'entertainment_vlogs': 3,
               'music_creative': 4, 'news_politics': 5, 'commentary_essay': 6, 'lifestyle': 7, 'other': 8}
    emotion_map = {'neutral': 0, 'happy': 1, 'sad': 2, 'angry': 3, 'fear': 4, 'surprise': 5, 'disgust': 6}
    sentiment_map = {'negative': 0, 'neutral': 1, 'positive': 2}
    hook_map = {'listicle': 0, 'how_to': 1, 'question': 2, 'challenge': 3, 'story': 4, 
                'reveal': 5, 'comparison': 6, 'urgency': 7, 'emotional': 8, 'tutorial': 9, 'none': 10}
    
    X_base = []
    X_cnn = []
    y_list = []
    
    for row in results:
        video_id, views, pub_date, title, description, tags_str, channel_id, thumb_url, \
        avg_views, subs, size, niche_id, video_count, category, total_views, channel_created, \
        face_count, has_face, face_area, bright, sat, contrast, edge, comp, has_text, text_words, \
        face_emotion, face_emo_int, title_len, title_words, title_num, title_q, title_caps, \
        hook_type, emo_score, sentiment, trend_score, spec_score = row
        
        if avg_views <= 0 or thumb_url not in cnn_cache:
            continue
        
        ratio = views / avg_views
        label = 1 if ratio >= 1.0 else 0
        
        # Base features
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
        
        desc = description or ""
        f_desc_words = len(desc.split()) if desc else 0
        
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        f_tag_count = len(tags)
        
        f_subs_log = np.log1p(subs or 10000)
        f_size = size_map.get(size, 2)
        f_video_count_log = np.log1p(video_count or 100)
        f_category = cat_map.get(category, 8)
        f_niche = niche_id or 0
        
        f_hit_rate = hit_rates.get(channel_id, 0.5)
        
        if channel_created and pub_date:
            f_channel_age_log = np.log1p(max((pub_date - channel_created).days, 1))
        else:
            f_channel_age_log = np.log1p(365)
        
        f_hour = pub_date.hour if pub_date else 12
        f_avg_views_log = np.log1p(avg_views)
        
        # Niche-relative
        features = {
            'face_count': f_face_count, 'has_face': has_face, 'face_area_ratio': f_face_area,
            'brightness': f_brightness, 'saturation': f_saturation, 'contrast': f_contrast,
            'edge_density': f_edge, 'composition_score': f_composition,
            'has_text': has_text, 'text_word_count': f_text_words,
            'title_char_length': f_title_len, 'title_word_count': f_title_words,
        }
        niche_rel = calc.calculate_relative_features(niche_id, features)
        
        f_niche_face = niche_rel.face_vs_niche if niche_rel else 0
        f_niche_bright = niche_rel.brightness_vs_niche if niche_rel else 0
        f_similarity_top = niche_rel.similarity_to_top if niche_rel else 0
        
        base_vec = [
            f_face_count, f_has_face, f_face_area, f_brightness, f_saturation, f_contrast,
            f_edge, f_composition, f_has_text, f_text_words, f_emotion, f_emotion_int,
            f_title_len, f_title_words, f_title_num, f_title_q, f_title_caps, f_hook,
            f_emo_score, f_sentiment, f_desc_words, f_tag_count,
            f_subs_log, f_size, f_video_count_log, f_category, f_niche,
            f_hit_rate, f_channel_age_log, f_hour, f_avg_views_log,
            f_niche_face, f_niche_bright, f_similarity_top,
            f_hit_rate * f_size,
        ]
        
        X_base.append(base_vec)
        X_cnn.append(cnn_cache[thumb_url])
        y_list.append(label)
    
    X_base = np.array(X_base)
    X_cnn = np.array(X_cnn)
    y = np.array(y_list)
    
    print(f"   Samples with CNN: {len(y):,}")
    print(f"   Base features: {X_base.shape[1]}")
    print(f"   CNN embedding dim: {X_cnn.shape[1]}")
    print(f"   Class balance: {sum(y)/len(y)*100:.1f}% positive")
    
    # Balance
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    np.random.seed(42)
    min_size = min(len(pos_idx), len(neg_idx))
    pos_idx = np.random.choice(pos_idx, size=min_size, replace=False)
    neg_idx = np.random.choice(neg_idx, size=min_size, replace=False)
    idx = np.concatenate([pos_idx, neg_idx])
    np.random.shuffle(idx)
    
    X_base_bal = X_base[idx]
    X_cnn_bal = X_cnn[idx]
    y_bal = y[idx]
    
    print(f"\n   Balanced: {len(y_bal):,} samples")
    
    # PCA on CNN
    print("\n   Applying PCA to CNN (576 → 30 dims)...")
    pca = PCA(n_components=30)
    X_cnn_pca = pca.fit_transform(X_cnn_bal)
    print(f"   Variance explained: {sum(pca.explained_variance_ratio_)*100:.1f}%")
    
    # Combine
    X_combined = np.hstack([X_base_bal, X_cnn_pca])
    
    # Split
    X_base_train, X_base_val, y_train, y_val = train_test_split(
        X_base_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
    )
    
    # Match CNN split
    train_idx = np.arange(len(y_train))
    val_idx = np.arange(len(y_train), len(y_bal))
    
    X_cnn_train, X_cnn_val = X_cnn_pca[:len(y_train)], X_cnn_pca[len(y_train):]
    X_comb_train, X_comb_val = X_combined[:len(y_train)], X_combined[len(y_train):]
    
    # Fix: proper split
    from sklearn.model_selection import train_test_split as tts
    X_base_train, X_base_val, X_cnn_train, X_cnn_val, X_comb_train, X_comb_val, y_train, y_val = \
        tts(X_base_bal, X_cnn_pca, X_combined, y_bal, test_size=0.2, random_state=42, stratify=y_bal)
    
    params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
        'learning_rate': 0.03, 'feature_fraction': 0.7, 'bagging_fraction': 0.8, 
        'bagging_freq': 5, 'min_data_in_leaf': 30, 'verbose': -1
    }
    
    print("\n" + "=" * 50)
    print("📊 RESULTS")
    print("=" * 50)
    
    # 1. Base features only
    print("\n1️⃣  BASE FEATURES ONLY (35 features)")
    train_data = lgb.Dataset(X_base_train, label=y_train)
    val_data = lgb.Dataset(X_base_val, label=y_val, reference=train_data)
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    probs = model.predict(X_base_val)
    base_acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    base_auc = roc_auc_score(y_val, probs)
    print(f"    Accuracy: {base_acc*100:.2f}% | AUC: {base_auc:.4f}")
    
    # 2. CNN only
    print("\n2️⃣  CNN FEATURES ONLY (30 PCA components)")
    train_data = lgb.Dataset(X_cnn_train, label=y_train)
    val_data = lgb.Dataset(X_cnn_val, label=y_val, reference=train_data)
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    probs = model.predict(X_cnn_val)
    cnn_acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    cnn_auc = roc_auc_score(y_val, probs)
    print(f"    Accuracy: {cnn_acc*100:.2f}% | AUC: {cnn_auc:.4f}")
    
    # 3. Combined
    print("\n3️⃣  COMBINED (Base + CNN = 65 features)")
    train_data = lgb.Dataset(X_comb_train, label=y_train)
    val_data = lgb.Dataset(X_comb_val, label=y_val, reference=train_data)
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    probs = model.predict(X_comb_val)
    comb_acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    comb_auc = roc_auc_score(y_val, probs)
    print(f"    Accuracy: {comb_acc*100:.2f}% | AUC: {comb_auc:.4f}")
    
    # Summary
    print("\n" + "=" * 50)
    print("📈 SUMMARY")
    print("=" * 50)
    print(f"   Base only:    {base_acc*100:.2f}% | AUC: {base_auc:.4f}")
    print(f"   CNN only:     {cnn_acc*100:.2f}% | AUC: {cnn_auc:.4f}")
    print(f"   Combined:     {comb_acc*100:.2f}% | AUC: {comb_auc:.4f}")
    print(f"\n   CNN impact: {(comb_acc - base_acc)*100:+.2f}%")
    
    return comb_acc, comb_auc


if __name__ == "__main__":
    run_cnn_test()


"""
Enhanced experiments with ALL available features.
Adds: description, tags, historical hit rate, channel age.
"""

import numpy as np
import json
from datetime import datetime
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import accuracy_score, roc_auc_score
import lightgbm as lgb
import optuna
from sqlalchemy import and_, func
import warnings
warnings.filterwarnings('ignore')

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator


def load_enhanced_data():
    """Load data with ALL available features including description, tags, hit rate."""
    print("📊 Loading enhanced data...")
    
    with get_session() as session:
        calc = NicheFeatureCalculator(session)
        calc.precompute_all_niches()
        
        # Get all videos with their features
        results = session.query(
            Video.video_id, Video.view_count, Video.published_at, Video.like_count, 
            Video.comment_count, Video.duration_seconds, Video.title, Video.description,
            Video.tags, Video.channel_id,
            Channel.avg_views_per_video, Channel.subscriber_count, Channel.size_tier, 
            Channel.niche_id, Channel.video_count, Channel.engagement_rate, 
            Channel.primary_category, Channel.total_views, Channel.created_at_yt,
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
        
        # Pre-calculate historical hit rates per channel
        print("   Calculating historical hit rates...")
        hit_rates = {}
        channel_video_counts = {}
        
        # Get all video performance per channel
        perf_query = session.query(
            Video.channel_id,
            func.count(Video.video_id).label('total_videos'),
            func.sum(
                func.cast(Video.view_count >= Channel.avg_views_per_video, Integer)
            ).label('hits')
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).filter(Video.view_count >= 100
        ).group_by(Video.channel_id).all()
        
        # Calculate hit rate using views from result set
        channel_performances = {}
        for row in results:
            channel_id = row[9]  # channel_id
            views = row[1]  # view_count
            avg_views = row[10]  # avg_views_per_video
            
            if channel_id not in channel_performances:
                channel_performances[channel_id] = {'total': 0, 'hits': 0}
            
            channel_performances[channel_id]['total'] += 1
            if views >= avg_views:
                channel_performances[channel_id]['hits'] += 1
        
        for channel_id, perf in channel_performances.items():
            hit_rates[channel_id] = perf['hits'] / max(perf['total'], 1)
            channel_video_counts[channel_id] = perf['total']
    
    print(f"   Raw samples: {len(results):,}")
    
    # Build features
    X_list = []
    y_list = []
    
    size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
    cat_map = {'gaming': 0, 'education_howto': 1, 'tech_reviews': 2, 'entertainment_vlogs': 3,
               'music_creative': 4, 'news_politics': 5, 'commentary_essay': 6, 'lifestyle': 7, 'other': 8}
    emotion_map = {'neutral': 0, 'happy': 1, 'sad': 2, 'angry': 3, 'fear': 4, 'surprise': 5, 'disgust': 6}
    sentiment_map = {'negative': 0, 'neutral': 1, 'positive': 2}
    hook_map = {'listicle': 0, 'how_to': 1, 'question': 2, 'challenge': 3, 'story': 4, 
                'reveal': 5, 'comparison': 6, 'urgency': 7, 'emotional': 8, 'tutorial': 9, 'none': 10}
    
    for row in results:
        video_id, views, pub_date, likes, comments, dur, title, description, tags_str, channel_id, \
        avg_views, subs, size, niche_id, video_count, eng_rate, category, total_views, channel_created, \
        face_count, has_face, face_area, bright, sat, contrast, edge, comp, has_text, text_words, \
        face_emotion, face_emo_int, title_len, title_words, title_num, title_q, title_caps, \
        hook_type, emo_score, sentiment, trend_score, spec_score = row
        
        if avg_views <= 0:
            continue
        
        ratio = views / avg_views
        label = 1 if ratio >= 1.0 else 0
        
        # === EXISTING THUMBNAIL FEATURES ===
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
        
        # === EXISTING TITLE FEATURES ===
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
        
        # === NEW: DESCRIPTION FEATURES ===
        desc = description or ""
        f_desc_len = len(desc)
        f_desc_words = len(desc.split()) if desc else 0
        f_desc_has_links = 1 if ('http' in desc.lower() or 'www.' in desc.lower()) else 0
        f_desc_has_hashtags = desc.count('#')
        f_desc_has_timestamps = 1 if any(c.isdigit() and ':' in desc for c in desc.split()) else 0
        
        # === NEW: TAG FEATURES ===
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        f_tag_count = len(tags)
        f_tag_total_chars = sum(len(t) for t in tags) if tags else 0
        
        # Tag-title overlap (how many tags appear in title)
        title_lower = (title or "").lower()
        f_tag_title_overlap = sum(1 for t in tags if t.lower() in title_lower) if tags else 0
        
        # === EXISTING CHANNEL CONTEXT ===
        f_subs_log = np.log1p(subs or 10000)
        f_size = size_map.get(size, 2)
        f_video_count_log = np.log1p(video_count or 100)
        f_eng_rate = eng_rate or 0.05
        f_category = cat_map.get(category, 8)
        f_niche = niche_id or 0
        
        # === NEW: CHANNEL HISTORICAL PERFORMANCE ===
        f_hit_rate = hit_rates.get(channel_id, 0.5)
        f_channel_videos_in_data = channel_video_counts.get(channel_id, 10)
        f_channel_experience = np.log1p(f_channel_videos_in_data)
        
        # === NEW: CHANNEL AGE ===
        if channel_created and pub_date:
            channel_age_days = (pub_date - channel_created).days
            f_channel_age_log = np.log1p(max(channel_age_days, 1))
        else:
            f_channel_age_log = np.log1p(365)  # default 1 year
        
        # === EXISTING TEMPORAL FEATURES ===
        f_hour = pub_date.hour if pub_date else 12
        f_day = pub_date.weekday() if pub_date else 3
        f_is_weekend = 1 if (pub_date and pub_date.weekday() >= 5) else 0
        f_is_prime_time = 1 if (pub_date and 17 <= pub_date.hour <= 21) else 0
        f_is_morning = 1 if (pub_date and 6 <= pub_date.hour <= 10) else 0
        f_is_night = 1 if (pub_date and pub_date.hour >= 22 or pub_date.hour <= 5) else 0
        
        # === EXISTING VIDEO METADATA ===
        f_duration_log = np.log1p(dur or 300)
        f_is_short = 1 if (dur and dur < 60) else 0
        f_is_long = 1 if (dur and dur > 1200) else 0
        f_is_medium = 1 if (dur and 300 <= dur <= 900) else 0
        
        # === EXISTING CHANNEL PERFORMANCE METRICS ===
        f_views_per_sub = (avg_views / max(subs, 1)) if subs else 0.1
        f_channel_total_log = np.log1p(total_views or 1000000)
        f_avg_views_log = np.log1p(avg_views)
        
        # === EXISTING NICHE-RELATIVE FEATURES ===
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
            f_niche_sat = niche_rel.saturation_vs_niche
            f_niche_contrast = niche_rel.contrast_vs_niche
            f_niche_edge = niche_rel.edge_vs_niche
            f_niche_comp = niche_rel.composition_vs_niche
            f_niche_title = niche_rel.title_length_vs_niche
            f_similarity_top = niche_rel.similarity_to_top
        else:
            f_niche_face = f_niche_bright = f_niche_sat = f_niche_contrast = 0
            f_niche_edge = f_niche_comp = f_niche_title = f_similarity_top = 0
        
        # === FEATURE INTERACTIONS ===
        f_face_bright = f_face_count * f_brightness
        f_face_text = f_has_face * f_has_text
        f_title_emo = f_title_len * f_emo_score
        f_subs_eng = f_subs_log * f_eng_rate
        f_bright_sat = f_brightness * f_saturation
        f_title_hook_emo = (1 if f_hook < 10 else 0) * f_emo_score
        f_hit_rate_size = f_hit_rate * f_size  # NEW: creator consistency × channel size
        f_desc_tags = f_desc_words * f_tag_count  # NEW: description richness
        
        # === DERIVED FEATURES ===
        f_title_density = f_title_words / max(f_title_len, 1)
        f_visual_score = (f_edge + f_contrast + f_saturation) / 3
        f_engage_potential = f_has_face + f_has_text + f_title_num + f_title_q
        f_metadata_richness = (f_desc_words > 50) + (f_tag_count > 5) + f_desc_has_links  # NEW
        
        # Build feature vector (now 72 features!)
        vec = [
            # Thumbnail (12)
            f_face_count, f_has_face, f_face_area, f_brightness, f_saturation, f_contrast,
            f_edge, f_composition, f_has_text, f_text_words, f_emotion, f_emotion_int,
            # Title (10)
            f_title_len, f_title_words, f_title_num, f_title_q, f_title_caps, f_hook,
            f_emo_score, f_sentiment, f_trend, f_spec,
            # NEW: Description (5)
            f_desc_len, f_desc_words, f_desc_has_links, f_desc_has_hashtags, f_desc_has_timestamps,
            # NEW: Tags (4)
            f_tag_count, f_tag_total_chars, f_tag_title_overlap, 
            min(f_tag_count, 10) / 10,  # normalized tag count
            # Channel context (8)
            f_subs_log, f_size, f_video_count_log, f_eng_rate, f_category, f_niche, 
            f_avg_views_log, f_channel_age_log,
            # NEW: Historical performance (3)
            f_hit_rate, f_channel_videos_in_data, f_channel_experience,
            # Temporal (6)
            f_hour, f_day, f_is_weekend, f_is_prime_time, f_is_morning, f_is_night,
            # Video metadata (4)
            f_duration_log, f_is_short, f_is_long, f_is_medium,
            # Channel performance (3)
            f_views_per_sub, f_channel_total_log, f_subs_log,
            # Niche-relative (8)
            f_niche_face, f_niche_bright, f_niche_sat, f_niche_contrast,
            f_niche_edge, f_niche_comp, f_niche_title, f_similarity_top,
            # Interactions (8)
            f_face_bright, f_face_text, f_title_emo, f_subs_eng, 
            f_bright_sat, f_title_hook_emo, f_hit_rate_size, f_desc_tags,
            # Derived (4)
            f_title_density, f_visual_score, f_engage_potential, f_metadata_richness,
        ]
        
        X_list.append(vec)
        y_list.append(label)
    
    X = np.array(X_list)
    y = np.array(y_list)
    
    print(f"   Processed samples: {len(y):,}")
    print(f"   Features: {X.shape[1]}")
    print(f"   Class balance: {sum(y)/len(y)*100:.1f}% positive")
    
    # Feature names for importance analysis
    feature_names = [
        # Thumbnail
        'face_count', 'has_face', 'face_area', 'brightness', 'saturation', 'contrast',
        'edge', 'composition', 'has_text', 'text_words', 'emotion', 'emotion_int',
        # Title
        'title_len', 'title_words', 'title_num', 'title_q', 'title_caps', 'hook',
        'emo_score', 'sentiment', 'trend', 'spec',
        # Description
        'desc_len', 'desc_words', 'desc_has_links', 'desc_hashtags', 'desc_timestamps',
        # Tags
        'tag_count', 'tag_chars', 'tag_title_overlap', 'tag_norm',
        # Channel
        'subs_log', 'size', 'video_count', 'eng_rate', 'category', 'niche',
        'avg_views_log', 'channel_age',
        # Historical
        'hit_rate', 'videos_in_data', 'channel_exp',
        # Temporal
        'hour', 'day', 'is_weekend', 'is_prime_time', 'is_morning', 'is_night',
        # Video
        'duration', 'is_short', 'is_long', 'is_medium',
        # Channel perf
        'views_per_sub', 'total_views', 'subs_log2',
        # Niche-relative
        'niche_face', 'niche_bright', 'niche_sat', 'niche_contrast',
        'niche_edge', 'niche_comp', 'niche_title', 'sim_top',
        # Interactions
        'face_x_bright', 'face_x_text', 'title_x_emo', 'subs_x_eng',
        'bright_x_sat', 'hook_x_emo', 'hit_x_size', 'desc_x_tags',
        # Derived
        'title_density', 'visual_score', 'engage_pot', 'metadata_rich',
    ]
    
    return X, y, feature_names


def balance_data(X, y, seed=42):
    """Balance dataset by undersampling."""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    np.random.seed(seed)
    
    min_size = min(len(pos_idx), len(neg_idx))
    pos_idx = np.random.choice(pos_idx, size=min_size, replace=False)
    neg_idx = np.random.choice(neg_idx, size=min_size, replace=False)
    
    idx = np.concatenate([pos_idx, neg_idx])
    np.random.shuffle(idx)
    
    return X[idx], y[idx]


def run_enhanced_experiments():
    """Run experiments with enhanced features."""
    print("=" * 70)
    print("🚀 ENHANCED FEATURE EXPERIMENTS")
    print("   Adding: Description, Tags, Hit Rate, Channel Age")
    print("=" * 70)
    print()
    
    # Load data
    X, y, feature_names = load_enhanced_data()
    X_bal, y_bal = balance_data(X, y)
    
    print(f"\n   Balanced samples: {len(y_bal):,}")
    print()
    
    # Split
    X_train, X_val, y_train, y_val = train_test_split(
        X_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
    )
    
    # 1. Baseline with enhanced features
    print("1️⃣  BASELINE (enhanced features)")
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
        'learning_rate': 0.03, 'feature_fraction': 0.7, 'bagging_fraction': 0.8, 
        'bagging_freq': 5, 'min_data_in_leaf': 30, 'verbose': -1
    }
    
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    
    # Best threshold
    best_thresh = 0.5
    best_acc = acc
    for t in np.arange(0.35, 0.65, 0.01):
        a = accuracy_score(y_val, (probs > t).astype(int))
        if a > best_acc:
            best_acc = a
            best_thresh = t
    
    print(f"    Accuracy: {acc*100:.2f}% | Best: {best_acc*100:.2f}% (t={best_thresh:.2f}) | AUC: {auc:.4f}")
    
    # 2. Feature importance
    print("\n2️⃣  TOP 20 FEATURE IMPORTANCE")
    importance = model.feature_importance(importance_type='gain')
    feat_imp = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)
    
    for i, (name, imp) in enumerate(feat_imp[:20]):
        bar = "█" * int(imp / max(importance) * 30)
        print(f"    {i+1:2d}. {name:<20} {bar} {imp:.1f}")
    
    # 3. Optuna optimization
    print("\n3️⃣  OPTUNA HYPERPARAMETER SEARCH (30 trials)")
    
    def objective(trial):
        params = {
            'objective': 'binary', 'metric': 'auc', 'verbosity': -1,
            'num_leaves': trial.suggest_int('num_leaves', 63, 255),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 0.9),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 0.9),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 10, 100),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
            'max_depth': trial.suggest_int('max_depth', 5, 20),
        }
        
        train_d = lgb.Dataset(X_train, label=y_train)
        val_d = lgb.Dataset(X_val, label=y_val, reference=train_d)
        
        m = lgb.train(params, train_d, 1000, valid_sets=[val_d],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        
        p = m.predict(X_val)
        return roc_auc_score(y_val, p)
    
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=30, show_progress_bar=True)
    
    # Train with best params
    best_params = study.best_params
    best_params['objective'] = 'binary'
    best_params['metric'] = 'auc'
    best_params['verbosity'] = -1
    
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    model = lgb.train(best_params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_val)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    
    # Best threshold
    best_acc_optuna = acc
    for t in np.arange(0.35, 0.65, 0.01):
        a = accuracy_score(y_val, (probs > t).astype(int))
        if a > best_acc_optuna:
            best_acc_optuna = a
    
    print(f"    Optuna Best: {best_acc_optuna*100:.2f}% | AUC: {auc:.4f}")
    
    # 4. Cross-validation
    print("\n4️⃣  5-FOLD CROSS-VALIDATION")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = []
    cv_aucs = []
    
    for train_idx, val_idx in cv.split(X_bal, y_bal):
        X_t, y_t = X_bal[train_idx], y_bal[train_idx]
        X_v, y_v = X_bal[val_idx], y_bal[val_idx]
        
        train_d = lgb.Dataset(X_t, label=y_t)
        val_d = lgb.Dataset(X_v, label=y_v, reference=train_d)
        
        m = lgb.train(best_params, train_d, 1000, valid_sets=[val_d],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        
        p = m.predict(X_v)
        cv_scores.append(accuracy_score(y_v, (p > 0.5).astype(int)))
        cv_aucs.append(roc_auc_score(y_v, p))
    
    print(f"    CV Accuracy: {np.mean(cv_scores)*100:.2f}% ± {np.std(cv_scores)*100:.2f}%")
    print(f"    CV AUC: {np.mean(cv_aucs):.4f} ± {np.std(cv_aucs):.4f}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 ENHANCED RESULTS SUMMARY")
    print("=" * 70)
    print(f"   Previous best (56 features):  73.19% accuracy, 0.8045 AUC")
    print(f"   NEW (72 features):            {best_acc_optuna*100:.2f}% accuracy, {auc:.4f} AUC")
    print(f"   Improvement: {(best_acc_optuna - 0.7319)*100:+.2f}%")
    print()
    
    # Show new feature contributions
    print("   NEW FEATURES CONTRIBUTION:")
    new_features = ['desc_len', 'desc_words', 'desc_has_links', 'desc_hashtags', 'desc_timestamps',
                    'tag_count', 'tag_chars', 'tag_title_overlap', 'tag_norm',
                    'hit_rate', 'videos_in_data', 'channel_exp', 'channel_age',
                    'hit_x_size', 'desc_x_tags', 'metadata_rich']
    
    for name, imp in feat_imp:
        if name in new_features:
            rank = [i for i, (n, _) in enumerate(feat_imp) if n == name][0] + 1
            print(f"   - {name}: rank #{rank} (importance: {imp:.1f})")
    
    return best_acc_optuna, auc


if __name__ == "__main__":
    from sqlalchemy import Integer
    acc, auc = run_enhanced_experiments()


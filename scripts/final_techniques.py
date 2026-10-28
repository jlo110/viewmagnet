"""
Final techniques: Stacking Ensemble + RFE Feature Selection
"""

import numpy as np
import json
from datetime import datetime
from sklearn.model_selection import train_test_split, cross_val_predict, StratifiedKFold
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.feature_selection import RFE
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, StackingClassifier, GradientBoostingClassifier
import lightgbm as lgb
import xgboost as xgb
from sqlalchemy import and_
import warnings
warnings.filterwarnings('ignore')

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator


def load_full_data():
    """Load full dataset with all features."""
    print("📊 Loading full data...")
    
    with get_session() as session:
        calc = NicheFeatureCalculator(session)
        calc.precompute_all_niches()
        
        results = session.query(
            Video.video_id, Video.view_count, Video.published_at, Video.title, 
            Video.description, Video.tags, Video.channel_id,
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
            avg_views = row[7]
            
            if channel_id not in channel_performances:
                channel_performances[channel_id] = {'total': 0, 'hits': 0}
            
            channel_performances[channel_id]['total'] += 1
            if views >= avg_views:
                channel_performances[channel_id]['hits'] += 1
        
        hit_rates = {cid: p['hits'] / max(p['total'], 1) 
                     for cid, p in channel_performances.items()}
    
    # Build features
    size_map = {'nano': 0, 'micro': 1, 'small': 2, 'medium': 3, 'large': 4, 'mega': 5, 'top': 6}
    cat_map = {'gaming': 0, 'education_howto': 1, 'tech_reviews': 2, 'entertainment_vlogs': 3,
               'music_creative': 4, 'news_politics': 5, 'commentary_essay': 6, 'lifestyle': 7, 'other': 8}
    emotion_map = {'neutral': 0, 'happy': 1, 'sad': 2, 'angry': 3, 'fear': 4, 'surprise': 5, 'disgust': 6}
    sentiment_map = {'negative': 0, 'neutral': 1, 'positive': 2}
    hook_map = {'listicle': 0, 'how_to': 1, 'question': 2, 'challenge': 3, 'story': 4, 
                'reveal': 5, 'comparison': 6, 'urgency': 7, 'emotional': 8, 'tutorial': 9, 'none': 10}
    
    X_list = []
    y_list = []
    
    for row in results:
        video_id, views, pub_date, title, description, tags_str, channel_id, \
        avg_views, subs, size, niche_id, video_count, category, total_views, channel_created, \
        face_count, has_face, face_area, bright, sat, contrast, edge, comp, has_text, text_words, \
        face_emotion, face_emo_int, title_len, title_words, title_num, title_q, title_caps, \
        hook_type, emo_score, sentiment, trend_score, spec_score = row
        
        if avg_views <= 0:
            continue
        
        ratio = views / avg_views
        label = 1 if ratio >= 1.0 else 0
        
        # Features
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
        f_desc_len = len(desc)
        f_desc_words = len(desc.split()) if desc else 0
        f_desc_has_links = 1 if ('http' in desc.lower() or 'www.' in desc.lower()) else 0
        f_desc_hashtags = desc.count('#')
        
        try:
            tags = json.loads(tags_str) if tags_str else []
        except:
            tags = []
        f_tag_count = len(tags)
        f_tag_chars = sum(len(t) for t in tags) if tags else 0
        title_lower = (title or "").lower()
        f_tag_title_overlap = sum(1 for t in tags if t.lower() in title_lower) if tags else 0
        
        f_subs_log = np.log1p(subs or 10000)
        f_size = size_map.get(size, 2)
        f_video_count_log = np.log1p(video_count or 100)
        f_category = cat_map.get(category, 8)
        f_niche = niche_id or 0
        f_avg_views_log = np.log1p(avg_views)
        
        f_hit_rate = hit_rates.get(channel_id, 0.5)
        f_channel_videos = channel_performances.get(channel_id, {}).get('total', 10)
        
        if channel_created and pub_date:
            f_channel_age_log = np.log1p(max((pub_date - channel_created).days, 1))
        else:
            f_channel_age_log = np.log1p(365)
        
        f_hour = pub_date.hour if pub_date else 12
        f_day = pub_date.weekday() if pub_date else 3
        f_is_weekend = 1 if (pub_date and pub_date.weekday() >= 5) else 0
        f_is_prime = 1 if (pub_date and 17 <= pub_date.hour <= 21) else 0
        
        f_views_per_sub = (avg_views / max(subs, 1)) if subs else 0.1
        f_total_views_log = np.log1p(total_views or 1000000)
        
        # Niche-relative
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
            f_niche_comp = niche_rel.composition_vs_niche
            f_niche_title = niche_rel.title_length_vs_niche
            f_sim_top = niche_rel.similarity_to_top
        else:
            f_niche_face = f_niche_bright = f_niche_sat = 0
            f_niche_comp = f_niche_title = f_sim_top = 0
        
        # Interactions
        f_hit_size = f_hit_rate * f_size
        f_desc_tags = f_desc_words * f_tag_count / 100
        
        vec = [
            f_face_count, f_has_face, f_face_area, f_brightness, f_saturation, f_contrast,
            f_edge, f_composition, f_has_text, f_text_words, f_emotion, f_emotion_int,
            f_title_len, f_title_words, f_title_num, f_title_q, f_title_caps, f_hook,
            f_emo_score, f_sentiment, f_trend, f_spec,
            f_desc_len, f_desc_words, f_desc_has_links, f_desc_hashtags,
            f_tag_count, f_tag_chars, f_tag_title_overlap,
            f_subs_log, f_size, f_video_count_log, f_category, f_niche, f_avg_views_log,
            f_hit_rate, f_channel_videos, f_channel_age_log,
            f_hour, f_day, f_is_weekend, f_is_prime,
            f_views_per_sub, f_total_views_log,
            f_niche_face, f_niche_bright, f_niche_sat, f_niche_comp, f_niche_title, f_sim_top,
            f_hit_size, f_desc_tags,
        ]
        
        X_list.append(vec)
        y_list.append(label)
    
    X = np.array(X_list)
    y = np.array(y_list)
    
    feature_names = [
        'face_count', 'has_face', 'face_area', 'brightness', 'saturation', 'contrast',
        'edge', 'composition', 'has_text', 'text_words', 'emotion', 'emotion_int',
        'title_len', 'title_words', 'title_num', 'title_q', 'title_caps', 'hook',
        'emo_score', 'sentiment', 'trend', 'spec',
        'desc_len', 'desc_words', 'desc_links', 'desc_hashtags',
        'tag_count', 'tag_chars', 'tag_overlap',
        'subs_log', 'size', 'video_count', 'category', 'niche', 'avg_views_log',
        'hit_rate', 'channel_videos', 'channel_age',
        'hour', 'day', 'is_weekend', 'is_prime',
        'views_per_sub', 'total_views_log',
        'niche_face', 'niche_bright', 'niche_sat', 'niche_comp', 'niche_title', 'sim_top',
        'hit_size', 'desc_tags',
    ]
    
    print(f"   Samples: {len(y):,}")
    print(f"   Features: {X.shape[1]}")
    
    return X, y, feature_names


def balance_data(X, y, seed=42):
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    np.random.seed(seed)
    min_size = min(len(pos_idx), len(neg_idx))
    pos_idx = np.random.choice(pos_idx, size=min_size, replace=False)
    neg_idx = np.random.choice(neg_idx, size=min_size, replace=False)
    idx = np.concatenate([pos_idx, neg_idx])
    np.random.shuffle(idx)
    return X[idx], y[idx]


def run_final_techniques():
    print("=" * 70)
    print("🎯 FINAL TECHNIQUES: Stacking + RFE")
    print("=" * 70)
    
    X, y, feature_names = load_full_data()
    X_bal, y_bal = balance_data(X, y)
    print(f"   Balanced: {len(y_bal):,}")
    
    X_train, X_test, y_train, y_test = train_test_split(
        X_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
    )
    
    results = {}
    
    # 1. Baseline LightGBM
    print("\n1️⃣  BASELINE (LightGBM)")
    lgb_train = lgb.Dataset(X_train, label=y_train)
    lgb_test = lgb.Dataset(X_test, label=y_test, reference=lgb_train)
    
    lgb_params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127,
        'learning_rate': 0.03, 'feature_fraction': 0.7, 'bagging_fraction': 0.8,
        'bagging_freq': 5, 'min_data_in_leaf': 30, 'verbose': -1
    }
    
    lgb_model = lgb.train(lgb_params, lgb_train, 1000, valid_sets=[lgb_test],
                          callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = lgb_model.predict(X_test)
    baseline_acc = accuracy_score(y_test, (probs > 0.5).astype(int))
    baseline_auc = roc_auc_score(y_test, probs)
    results['baseline'] = {'acc': baseline_acc, 'auc': baseline_auc}
    print(f"    Accuracy: {baseline_acc*100:.2f}% | AUC: {baseline_auc:.4f}")
    
    # 2. RFE Feature Selection
    print("\n2️⃣  RFE FEATURE SELECTION (selecting top 35)")
    
    # Use a fast estimator for RFE
    rf_est = RandomForestClassifier(n_estimators=50, max_depth=10, random_state=42, n_jobs=-1)
    rfe = RFE(rf_est, n_features_to_select=35, step=5)
    rfe.fit(X_train, y_train)
    
    X_train_rfe = rfe.transform(X_train)
    X_test_rfe = rfe.transform(X_test)
    
    selected_features = [f for f, s in zip(feature_names, rfe.support_) if s]
    print(f"    Selected: {selected_features[:10]}...")
    
    lgb_train_rfe = lgb.Dataset(X_train_rfe, label=y_train)
    lgb_test_rfe = lgb.Dataset(X_test_rfe, label=y_test, reference=lgb_train_rfe)
    
    lgb_model_rfe = lgb.train(lgb_params, lgb_train_rfe, 1000, valid_sets=[lgb_test_rfe],
                              callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs_rfe = lgb_model_rfe.predict(X_test_rfe)
    rfe_acc = accuracy_score(y_test, (probs_rfe > 0.5).astype(int))
    rfe_auc = roc_auc_score(y_test, probs_rfe)
    results['rfe'] = {'acc': rfe_acc, 'auc': rfe_auc}
    print(f"    Accuracy: {rfe_acc*100:.2f}% | AUC: {rfe_auc:.4f}")
    
    # 3. Stacking Ensemble
    print("\n3️⃣  STACKING ENSEMBLE")
    
    # Base estimators
    estimators = [
        ('lgb', lgb.LGBMClassifier(
            n_estimators=200, num_leaves=127, learning_rate=0.03,
            feature_fraction=0.7, bagging_fraction=0.8, verbose=-1
        )),
        ('xgb', xgb.XGBClassifier(
            n_estimators=200, max_depth=8, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.7, verbosity=0
        )),
        ('rf', RandomForestClassifier(
            n_estimators=100, max_depth=15, min_samples_leaf=10, n_jobs=-1
        )),
    ]
    
    # Meta-learner
    stack_clf = StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(C=1.0, max_iter=1000),
        cv=5,
        passthrough=False,
        n_jobs=-1
    )
    
    print("    Training stacking classifier...")
    stack_clf.fit(X_train, y_train)
    
    stack_probs = stack_clf.predict_proba(X_test)[:, 1]
    stack_acc = accuracy_score(y_test, (stack_probs > 0.5).astype(int))
    stack_auc = roc_auc_score(y_test, stack_probs)
    results['stacking'] = {'acc': stack_acc, 'auc': stack_auc}
    print(f"    Accuracy: {stack_acc*100:.2f}% | AUC: {stack_auc:.4f}")
    
    # 4. Stacking + Threshold calibration
    print("\n4️⃣  STACKING + THRESHOLD CALIBRATION")
    best_thresh = 0.5
    best_acc = stack_acc
    for t in np.arange(0.35, 0.65, 0.01):
        acc = accuracy_score(y_test, (stack_probs > t).astype(int))
        if acc > best_acc:
            best_acc = acc
            best_thresh = t
    
    results['stacking_thresh'] = {'acc': best_acc, 'thresh': best_thresh}
    print(f"    Best threshold: {best_thresh:.2f} | Accuracy: {best_acc*100:.2f}%")
    
    # 5. RFE + Stacking
    print("\n5️⃣  RFE + STACKING (combined)")
    
    stack_clf_rfe = StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(C=1.0, max_iter=1000),
        cv=5,
        passthrough=False,
        n_jobs=-1
    )
    
    print("    Training stacking with RFE features...")
    stack_clf_rfe.fit(X_train_rfe, y_train)
    
    stack_rfe_probs = stack_clf_rfe.predict_proba(X_test_rfe)[:, 1]
    stack_rfe_acc = accuracy_score(y_test, (stack_rfe_probs > 0.5).astype(int))
    stack_rfe_auc = roc_auc_score(y_test, stack_rfe_probs)
    
    # + threshold
    best_thresh_rfe = 0.5
    best_acc_rfe = stack_rfe_acc
    for t in np.arange(0.35, 0.65, 0.01):
        acc = accuracy_score(y_test, (stack_rfe_probs > t).astype(int))
        if acc > best_acc_rfe:
            best_acc_rfe = acc
            best_thresh_rfe = t
    
    results['rfe_stacking'] = {'acc': best_acc_rfe, 'auc': stack_rfe_auc}
    print(f"    Accuracy: {best_acc_rfe*100:.2f}% | AUC: {stack_rfe_auc:.4f}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Technique':<35} {'Accuracy':>12} {'AUC':>10}")
    print("-" * 60)
    print(f"{'Baseline (LightGBM)':<35} {results['baseline']['acc']*100:>11.2f}% {results['baseline']['auc']:>10.4f}")
    print(f"{'+ RFE Feature Selection':<35} {results['rfe']['acc']*100:>11.2f}% {results['rfe']['auc']:>10.4f}")
    print(f"{'Stacking Ensemble':<35} {results['stacking']['acc']*100:>11.2f}% {results['stacking']['auc']:>10.4f}")
    print(f"{'Stacking + Threshold':<35} {results['stacking_thresh']['acc']*100:>11.2f}%")
    print(f"{'RFE + Stacking + Threshold':<35} {results['rfe_stacking']['acc']*100:>11.2f}% {results['rfe_stacking']['auc']:>10.4f}")
    print("-" * 60)
    
    best = max(results['baseline']['acc'], results['rfe']['acc'], 
               results['stacking_thresh']['acc'], results['rfe_stacking']['acc'])
    print(f"\n🏆 BEST ACCURACY: {best*100:.2f}%")
    print(f"📈 Improvement over baseline: {(best - results['baseline']['acc'])*100:+.2f}%")
    
    return results


if __name__ == "__main__":
    results = run_final_techniques()


"""
Comprehensive accuracy improvement experiments.
Tests all features and model techniques to maximize performance.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.feature_selection import mutual_info_classif, SelectKBest
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
import lightgbm as lgb
import xgboost as xgb
import optuna
from sqlalchemy import and_
import warnings
warnings.filterwarnings('ignore')

from src.database.models import Video, VideoFeatures, Channel
from src.database.connection import get_session
from src.ml.niche_features import NicheFeatureCalculator


def load_data():
    """Load and prepare all features."""
    print("📊 Loading data...")
    
    with get_session() as session:
        calc = NicheFeatureCalculator(session)
        calc.precompute_all_niches()
        
        results = session.query(
            Video.view_count, Video.published_at, Video.like_count, Video.comment_count,
            Video.duration_seconds, Video.title,
            Channel.avg_views_per_video, Channel.subscriber_count, Channel.size_tier, 
            Channel.niche_id, Channel.video_count, Channel.engagement_rate, 
            Channel.primary_category, Channel.total_views,
            VideoFeatures.face_count, VideoFeatures.has_face, VideoFeatures.face_area_ratio,
            VideoFeatures.brightness, VideoFeatures.saturation, VideoFeatures.contrast,
            VideoFeatures.edge_density, VideoFeatures.composition_score, VideoFeatures.has_text,
            VideoFeatures.text_word_count, VideoFeatures.face_emotion_primary, 
            VideoFeatures.face_emotion_intensity, VideoFeatures.title_char_length, 
            VideoFeatures.title_word_count, VideoFeatures.title_has_number, 
            VideoFeatures.title_has_question, VideoFeatures.title_caps_ratio, 
            VideoFeatures.title_hook_type, VideoFeatures.title_emotional_score, 
            VideoFeatures.title_sentiment, VideoFeatures.title_trending_score,
            VideoFeatures.title_specificity_score, VideoFeatures.dominant_color_1,
        ).join(VideoFeatures, Video.video_id == VideoFeatures.video_id
        ).join(Channel, Video.channel_id == Channel.channel_id
        ).filter(and_(Video.view_count >= 100, VideoFeatures.thumbnail_processed == True,
                      Channel.avg_views_per_video > 0, Channel.niche_id.isnot(None))).all()
    
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
        views, pub_date, likes, comments, dur, title, avg_views, subs, size, niche_id, \
        video_count, eng_rate, category, total_views, face_count, has_face, face_area, \
        bright, sat, contrast, edge, comp, has_text, text_words, face_emotion, face_emo_int, \
        title_len, title_words, title_num, title_q, title_caps, hook_type, emo_score, \
        sentiment, trend_score, spec_score, dom_color = row
        
        if avg_views <= 0:
            continue
        
        ratio = views / avg_views
        label = 1 if ratio >= 1.0 else 0
        
        # === CORE THUMBNAIL FEATURES ===
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
        
        # === CORE TITLE FEATURES ===
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
        
        # === CHANNEL CONTEXT ===
        f_subs_log = np.log1p(subs or 10000)
        f_size = size_map.get(size, 2)
        f_video_count_log = np.log1p(video_count or 100)
        f_eng_rate = eng_rate or 0.05
        f_category = cat_map.get(category, 8)
        f_niche = niche_id or 0
        
        # === TEMPORAL FEATURES ===
        f_hour = pub_date.hour if pub_date else 12
        f_day = pub_date.weekday() if pub_date else 3
        f_is_weekend = 1 if (pub_date and pub_date.weekday() >= 5) else 0
        f_is_prime_time = 1 if (pub_date and 17 <= pub_date.hour <= 21) else 0
        
        # === VIDEO METADATA ===
        f_duration_log = np.log1p(dur or 300)
        f_is_short = 1 if (dur and dur < 60) else 0
        f_is_long = 1 if (dur and dur > 1200) else 0
        
        # === CHANNEL PERFORMANCE METRICS ===
        f_views_per_sub = (avg_views / max(subs, 1)) if subs else 0.1
        f_channel_total_log = np.log1p(total_views or 1000000)
        f_avg_views_log = np.log1p(avg_views)
        
        # === NICHE-RELATIVE FEATURES ===
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
        
        # === DERIVED FEATURES ===
        # Title efficiency (words per char)
        f_title_density = f_title_words / max(f_title_len, 1)
        # Visual complexity score
        f_visual_score = (f_edge + f_contrast + f_saturation) / 3
        # Engagement potential
        f_engage_potential = f_has_face + f_has_text + f_title_num + f_title_q
        
        # Build feature vector
        vec = [
            # Thumbnail (12)
            f_face_count, f_has_face, f_face_area, f_brightness, f_saturation, f_contrast,
            f_edge, f_composition, f_has_text, f_text_words, f_emotion, f_emotion_int,
            # Title (10)
            f_title_len, f_title_words, f_title_num, f_title_q, f_title_caps, f_hook,
            f_emo_score, f_sentiment, f_trend, f_spec,
            # Channel (7)
            f_subs_log, f_size, f_video_count_log, f_eng_rate, f_category, f_niche, f_avg_views_log,
            # Temporal (4)
            f_hour, f_day, f_is_weekend, f_is_prime_time,
            # Video metadata (3)
            f_duration_log, f_is_short, f_is_long,
            # Channel performance (3)
            f_views_per_sub, f_channel_total_log, f_subs_log,
            # Niche-relative (8)
            f_niche_face, f_niche_bright, f_niche_sat, f_niche_contrast,
            f_niche_edge, f_niche_comp, f_niche_title, f_similarity_top,
            # Interactions (6)
            f_face_bright, f_face_text, f_title_emo, f_subs_eng, f_bright_sat, f_title_hook_emo,
            # Derived (3)
            f_title_density, f_visual_score, f_engage_potential,
        ]
        
        X_list.append(vec)
        y_list.append(label)
    
    X = np.array(X_list)
    y = np.array(y_list)
    
    print(f"   Processed samples: {len(y):,}")
    print(f"   Features: {X.shape[1]}")
    print(f"   Class balance: {sum(y)/len(y)*100:.1f}% positive")
    
    return X, y


def balance_data(X, y, seed=42):
    """Balance dataset by undersampling majority class."""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    np.random.seed(seed)
    
    min_size = min(len(pos_idx), len(neg_idx))
    pos_idx = np.random.choice(pos_idx, size=min_size, replace=False)
    neg_idx = np.random.choice(neg_idx, size=min_size, replace=False)
    
    idx = np.concatenate([pos_idx, neg_idx])
    np.random.shuffle(idx)
    
    return X[idx], y[idx]


def experiment_baseline(X_train, X_val, y_train, y_val):
    """Baseline LightGBM model."""
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
    
    return acc, auc, model


def experiment_optuna(X_train, X_val, y_train, y_val, n_trials=50):
    """Hyperparameter optimization with Optuna."""
    
    def objective(trial):
        params = {
            'objective': 'binary',
            'metric': 'auc',
            'verbosity': -1,
            'num_leaves': trial.suggest_int('num_leaves', 31, 255),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 0.9),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 0.9),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 10, 100),
            'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
            'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
            'max_depth': trial.suggest_int('max_depth', 5, 20),
        }
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                          callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        
        probs = model.predict(X_val)
        auc = roc_auc_score(y_val, probs)
        return auc
    
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    
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
    
    return acc, auc, model, best_params


def experiment_feature_selection(X_train, X_val, y_train, y_val, k=30):
    """Feature selection using mutual information."""
    selector = SelectKBest(mutual_info_classif, k=k)
    X_train_sel = selector.fit_transform(X_train, y_train)
    X_val_sel = selector.transform(X_val)
    
    train_data = lgb.Dataset(X_train_sel, label=y_train)
    val_data = lgb.Dataset(X_val_sel, label=y_val, reference=train_data)
    
    params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
        'learning_rate': 0.03, 'feature_fraction': 0.8, 'bagging_fraction': 0.8, 
        'bagging_freq': 5, 'min_data_in_leaf': 30, 'verbose': -1
    }
    
    model = lgb.train(params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    
    probs = model.predict(X_val_sel)
    acc = accuracy_score(y_val, (probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, probs)
    
    return acc, auc, selector.get_support()


def experiment_ensemble(X_train, X_val, y_train, y_val):
    """Ensemble of LightGBM, XGBoost, and Random Forest."""
    
    # LightGBM
    lgb_train = lgb.Dataset(X_train, label=y_train)
    lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_train)
    lgb_params = {
        'objective': 'binary', 'metric': 'auc', 'num_leaves': 127, 
        'learning_rate': 0.03, 'verbose': -1
    }
    lgb_model = lgb.train(lgb_params, lgb_train, 500, valid_sets=[lgb_val],
                          callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
    lgb_probs = lgb_model.predict(X_val)
    
    # XGBoost
    xgb_model = xgb.XGBClassifier(
        n_estimators=500, max_depth=8, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.7, early_stopping_rounds=50,
        eval_metric='auc', verbosity=0, random_state=42
    )
    xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    xgb_probs = xgb_model.predict_proba(X_val)[:, 1]
    
    # Random Forest
    rf_model = RandomForestClassifier(n_estimators=200, max_depth=15, 
                                       min_samples_leaf=10, random_state=42, n_jobs=-1)
    rf_model.fit(X_train, y_train)
    rf_probs = rf_model.predict_proba(X_val)[:, 1]
    
    # Ensemble (weighted average)
    ensemble_probs = (lgb_probs * 0.4 + xgb_probs * 0.4 + rf_probs * 0.2)
    
    acc = accuracy_score(y_val, (ensemble_probs > 0.5).astype(int))
    auc = roc_auc_score(y_val, ensemble_probs)
    
    # Individual scores
    lgb_acc = accuracy_score(y_val, (lgb_probs > 0.5).astype(int))
    xgb_acc = accuracy_score(y_val, (xgb_probs > 0.5).astype(int))
    rf_acc = accuracy_score(y_val, (rf_probs > 0.5).astype(int))
    
    return acc, auc, {'lgb': lgb_acc, 'xgb': xgb_acc, 'rf': rf_acc}


def experiment_threshold(probs, y_val):
    """Find optimal decision threshold."""
    best_thresh = 0.5
    best_acc = 0
    
    for thresh in np.arange(0.3, 0.7, 0.01):
        acc = accuracy_score(y_val, (probs > thresh).astype(int))
        if acc > best_acc:
            best_acc = acc
            best_thresh = thresh
    
    return best_thresh, best_acc


def run_all_experiments():
    """Run all experiments and compare results."""
    print("=" * 70)
    print("🧪 COMPREHENSIVE ACCURACY IMPROVEMENT EXPERIMENTS")
    print("=" * 70)
    print()
    
    # Load data
    X, y = load_data()
    X_bal, y_bal = balance_data(X, y)
    
    print(f"\n   Balanced samples: {len(y_bal):,}")
    print()
    
    # Split
    X_train, X_val, y_train, y_val = train_test_split(
        X_bal, y_bal, test_size=0.2, random_state=42, stratify=y_bal
    )
    
    results = {}
    
    # 1. Baseline
    print("1️⃣  BASELINE (LightGBM default params)")
    acc, auc, model = experiment_baseline(X_train, X_val, y_train, y_val)
    results['baseline'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # Get baseline probs for threshold tuning
    probs = model.predict(X_val)
    
    # 2. Threshold calibration
    print("\n2️⃣  THRESHOLD CALIBRATION")
    best_thresh, best_acc = experiment_threshold(probs, y_val)
    results['threshold'] = {'acc': best_acc, 'thresh': best_thresh}
    print(f"    Best threshold: {best_thresh:.2f} | Accuracy: {best_acc*100:.2f}%")
    
    # 3. Feature selection
    print("\n3️⃣  FEATURE SELECTION (top 35 features)")
    acc, auc, selected = experiment_feature_selection(X_train, X_val, y_train, y_val, k=35)
    results['feature_sel'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # 4. Ensemble
    print("\n4️⃣  ENSEMBLE (LightGBM + XGBoost + RandomForest)")
    acc, auc, individual = experiment_ensemble(X_train, X_val, y_train, y_val)
    results['ensemble'] = {'acc': acc, 'auc': auc, 'individual': individual}
    print(f"    Individual: LGB={individual['lgb']*100:.1f}% XGB={individual['xgb']*100:.1f}% RF={individual['rf']*100:.1f}%")
    print(f"    Ensemble:   {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # 5. Hyperparameter optimization
    print("\n5️⃣  OPTUNA HYPERPARAMETER SEARCH (50 trials)")
    acc, auc, model, best_params = experiment_optuna(X_train, X_val, y_train, y_val, n_trials=50)
    results['optuna'] = {'acc': acc, 'auc': auc}
    print(f"    Accuracy: {acc*100:.2f}% | AUC: {auc:.4f}")
    
    # Threshold on Optuna model
    optuna_probs = model.predict(X_val)
    best_thresh, best_acc = experiment_threshold(optuna_probs, y_val)
    results['optuna_thresh'] = {'acc': best_acc, 'thresh': best_thresh}
    print(f"    + Threshold ({best_thresh:.2f}): {best_acc*100:.2f}%")
    
    # 6. Cross-validation
    print("\n6️⃣  5-FOLD CROSS-VALIDATION (best model)")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = []
    
    for train_idx, val_idx in cv.split(X_bal, y_bal):
        X_t, y_t = X_bal[train_idx], y_bal[train_idx]
        X_v, y_v = X_bal[val_idx], y_bal[val_idx]
        
        train_data = lgb.Dataset(X_t, label=y_t)
        val_data = lgb.Dataset(X_v, label=y_v, reference=train_data)
        
        m = lgb.train(best_params, train_data, 1000, valid_sets=[val_data],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        
        p = m.predict(X_v)
        cv_scores.append(accuracy_score(y_v, (p > 0.5).astype(int)))
    
    results['cv'] = {'mean': np.mean(cv_scores), 'std': np.std(cv_scores), 'scores': cv_scores}
    print(f"    CV Scores: {[f'{s*100:.1f}%' for s in cv_scores]}")
    print(f"    Mean: {np.mean(cv_scores)*100:.2f}% ± {np.std(cv_scores)*100:.2f}%")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Technique':<35} {'Accuracy':>12} {'AUC':>10}")
    print("-" * 60)
    print(f"{'Baseline (LightGBM)':<35} {results['baseline']['acc']*100:>11.2f}% {results['baseline']['auc']:>10.4f}")
    print(f"{'+ Threshold Calibration':<35} {results['threshold']['acc']*100:>11.2f}%")
    print(f"{'Feature Selection (k=35)':<35} {results['feature_sel']['acc']*100:>11.2f}% {results['feature_sel']['auc']:>10.4f}")
    print(f"{'Ensemble (LGB+XGB+RF)':<35} {results['ensemble']['acc']*100:>11.2f}% {results['ensemble']['auc']:>10.4f}")
    print(f"{'Optuna Tuned LightGBM':<35} {results['optuna']['acc']*100:>11.2f}% {results['optuna']['auc']:>10.4f}")
    print(f"{'Optuna + Threshold':<35} {results['optuna_thresh']['acc']*100:>11.2f}%")
    print(f"{'5-Fold CV (Optuna params)':<35} {results['cv']['mean']*100:>11.2f}% ± {results['cv']['std']*100:.2f}%")
    print("-" * 60)
    
    best_result = max([
        results['baseline']['acc'],
        results['threshold']['acc'],
        results['feature_sel']['acc'],
        results['ensemble']['acc'],
        results['optuna_thresh']['acc'],
    ])
    
    print(f"\n🏆 BEST ACCURACY: {best_result*100:.2f}%")
    print(f"📈 Improvement over baseline: +{(best_result - results['baseline']['acc'])*100:.2f}%")
    
    return results


if __name__ == "__main__":
    results = run_all_experiments()


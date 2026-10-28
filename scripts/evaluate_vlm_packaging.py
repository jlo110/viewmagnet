"""Does packaging *quality* (judged by a VLM) predict overperformance?

The crude image/title stats hit a ceiling at AUC 0.549. This asks the real
question: show a **vision-language model the actual thumbnail + title** and have
it rate the dimensions humans react to — curiosity gap, clarity, emotional pull,
click-compulsion, title↔thumbnail synergy, text readability — then test whether
THOSE ratings predict channel-relative overperformance (channel-grouped CV).

Provider: Synthetic vision (`syn:large:vision`) via the OpenAI-compatible
endpoint (key from SYNTHETIC_API_KEY env — never hard-coded). Thumbnails are sent
as base64 data URLs. VLM scores are cached by video_id so runs are incremental.

Usage:
    python -m scripts.evaluate_vlm_packaging --smoke           # score 3, print raw
    python -m scripts.evaluate_vlm_packaging --max-videos 1000 # score + evaluate
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
from pathlib import Path

import numpy as np

CACHE = Path("data/cache/vlm_packaging.pkl")
DIMENSIONS = [
    "curiosity_gap", "clarity", "emotional_pull",
    "click_compulsion", "title_thumbnail_synergy", "text_readability",
]
TOP_FRACTION = 0.30
VISION_MODEL = os.environ.get("SYNTHETIC_VISION_MODEL", "syn:large:vision")

PROMPT = (
    "You are a world-class YouTube packaging analyst. You are shown a video's "
    "THUMBNAIL (image) and its TITLE. Rate the PACKAGING (not the topic) on each "
    "dimension from 1 (poor) to 10 (excellent):\n"
    "- curiosity_gap: does it open a question you must click to resolve\n"
    "- clarity: instantly legible at small size, one clear focal idea\n"
    "- emotional_pull: facial expression / stakes / emotion that grabs\n"
    "- click_compulsion: raw urge to click\n"
    "- title_thumbnail_synergy: do title and image combine (not repeat) to tease\n"
    "- text_readability: overlay text punchy and readable (10 if no text needed)\n"
    'Return ONLY JSON: {"curiosity_gap":n,"clarity":n,"emotional_pull":n,'
    '"click_compulsion":n,"title_thumbnail_synergy":n,"text_readability":n}\n\n'
    "TITLE: {title}"
)


def _load_cache() -> dict:
    if CACHE.exists():
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    return {}


def _save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump(c, fh)


def _fetch_b64(url: str) -> str | None:
    import httpx

    try:
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
        return base64.b64encode(r.content).decode()
    except Exception:
        return None


def _score_one(client, title: str, thumb_url: str) -> dict | None:
    b64 = _fetch_b64(thumb_url)
    if not b64:
        return None
    try:
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            max_tokens=1500,   # reasoning vision models eat low budgets -> empty content
            temperature=0,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT.replace("{title}", title or "")},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]}],
        )
        text = resp.choices[0].message.content or ""
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1]
        data = json.loads(text.strip())
        return {d: float(data[d]) for d in DIMENSIONS if d in data} or None
    except Exception as e:
        print(f"    score failed: {str(e)[:80]}")
        return None


def _client():
    from openai import OpenAI

    from src.config import get_settings

    s = get_settings()
    if not s.synthetic_api_key:
        raise SystemExit("No SYNTHETIC_API_KEY configured.")
    return OpenAI(api_key=s.synthetic_api_key, base_url=s.synthetic_base_url)


def _sample(max_videos: int, per_channel: int, min_per_channel: int):
    from sqlalchemy import select

    from src.database.connection import get_session
    from src.database.models import BackfillVideo as BV
    from src.features.language import is_probably_english

    with get_session() as s:
        rows = s.execute(select(
            BV.video_id, BV.channel_id, BV.title, BV.outlier,
            BV.duration_seconds, BV.thumbnail_url, BV.default_audio_language,
        )).all()
    by_ch: dict = {}
    for vid, ch, title, outlier, dur, thumb, lang in rows:
        if outlier is None or (dur or 0) < 60 or not thumb:
            continue
        if not is_probably_english(title or "", lang):
            continue
        by_ch.setdefault(ch, []).append((vid, ch, title, outlier, thumb))
    out = []
    for ch, vids in by_ch.items():
        if len(vids) >= min_per_channel:
            out.extend(vids[:per_channel])
    return out[:max_videos]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="score 3 videos, print raw output")
    ap.add_argument("--max-videos", type=int, default=1200)
    ap.add_argument("--per-channel", type=int, default=8)
    ap.add_argument("--min-per-channel", type=int, default=8)
    args = ap.parse_args()

    sample = _sample(args.max_videos, args.per_channel, args.min_per_channel)
    print(f"Sample: {len(sample)} videos / {len({r[1] for r in sample})} channels")
    client = _client()
    cache = _load_cache()

    if args.smoke:
        for vid, ch, title, outlier, thumb in sample[:3]:
            print(f"\nTITLE: {title}\n  thumb: {thumb[:60]}")
            print(f"  scores: {_score_one(client, title, thumb)}")
        return

    todo = [r for r in sample if r[0] not in cache]
    print(f"  {len(cache)} cached, scoring {len(todo)} more via {VISION_MODEL}…")
    for i, (vid, ch, title, outlier, thumb) in enumerate(todo, 1):
        sc = _score_one(client, title, thumb)
        if sc:
            cache[vid] = sc
        if i % 50 == 0:
            _save_cache(cache)
            print(f"    …{i}/{len(todo)}")
    _save_cache(cache)

    # Build features from VLM scores + evaluate channel-grouped.
    import pandas as pd

    recs = [
        {**cache[vid], "outlier": outlier, "channel_id": ch}
        for vid, ch, title, outlier, thumb in sample if vid in cache
    ]
    df = pd.DataFrame(recs).dropna()
    if df.empty or df["channel_id"].nunique() < 20:
        print("Not enough scored videos for a grouped eval yet.")
        return
    cut = df["outlier"].quantile(1 - TOP_FRACTION)
    y = (df["outlier"] >= cut).astype(int).to_numpy()
    groups = df["channel_id"].to_numpy()
    X = df[[d for d in DIMENSIONS if d in df.columns]].astype(float).to_numpy()

    from sklearn.metrics import balanced_accuracy_score, roc_auc_score
    from sklearn.model_selection import GroupKFold
    from xgboost import XGBClassifier

    oof = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
        clf = XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
            scale_pos_weight=(y[tr] == 0).sum() / max(1, (y[tr] == 1).sum()),
        )
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    thr = np.quantile(oof, 1 - y.mean())
    auc = roc_auc_score(y, oof)
    bacc = balanced_accuracy_score(y, (oof >= thr).astype(int))

    print("\n── VLM packaging-quality → overperformance (channel-grouped CV) ──")
    print(f"  scored={len(df):,}  channels={df['channel_id'].nunique():,}  positives={y.mean():.0%}")
    print(f"  AUC {auc:.3f}   bal-acc {bacc:.3f}   (baseline 0.500, crude features 0.549)")
    # Which dimensions correlate with overperformance (descriptive)
    corrs = {d: float(np.corrcoef(df[d], df["outlier"])[0, 1]) for d in DIMENSIONS if d in df.columns}
    print("  dim→outlier corr: " + ", ".join(f"{d} {c:+.3f}" for d, c in sorted(corrs.items(), key=lambda x: -abs(x[1]))))


if __name__ == "__main__":
    main()

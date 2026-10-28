"""Candidate ranker (TODO #9 / plan 6.4 v1): pick the winning packaging.

Submit 2-4 title(+thumbnail) candidates for the same video; get them ranked
with explanations. Two scorers, composed:

1. **Reach predictor** — *will this packaging break out in absolute terms?*
   Prefers the FINE-TUNED CLIP head model (`reach_model.py`, val AUC 0.668),
   falls back to the legacy frozen-CLIP→XGBoost model (0.615) when torch is
   unavailable. Only candidates WITH a thumbnail get a reach score.
2. **Packaging rubric** (MrBeast principles, LLM): *why* each title works or
   doesn't — curiosity gap / extremity / clarity / specificity + the <50-char
   rule + rewrites. The explainable layer.

Ranking: mean-normalized blend when reach is available for all candidates,
else rubric score. Degrades gracefully: no reach artifact / no CLIP / no LLM
each remove a layer, never the endpoint.

CLIP + XGBoost co-load: fine on Linux (prod); on macOS they can segfault
together (OpenMP clash) — the known two-process caveat from Phase 6.1.
"""
from __future__ import annotations

import io
from typing import List, Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

REACH_ARTIFACT = "data/models/reach_predictor.pkl"
N_HAND = 25

_reach = None          # {"model", "feature_spec", "clip_model", ...} | False (absent)
_clip = None           # (model, processor) | False


def _load_reach():
    global _reach
    if _reach is None:
        try:
            import pickle
            from pathlib import Path

            p = Path(REACH_ARTIFACT)
            _reach = pickle.loads(p.read_bytes()) if p.exists() else False
            if _reach:
                logger.info("ranker.reach_loaded", cv_auc=_reach.get("cv_auc"))
        except Exception as e:
            logger.warning("ranker.reach_load_failed", error=str(e)[:120])
            _reach = False
    return _reach or None


def _load_clip(model_name: str):
    global _clip
    if _clip is None:
        try:
            import torch  # noqa: F401
            from transformers import CLIPModel, CLIPProcessor

            model = CLIPModel.from_pretrained(model_name)
            model.eval()
            _clip = (model, CLIPProcessor.from_pretrained(model_name))
            logger.info("ranker.clip_loaded", model=model_name)
        except Exception as e:
            logger.warning("ranker.clip_load_failed", error=str(e)[:120])
            _clip = False
    return _clip or None


def clip_features(image_bytes: bytes, title: str, clip_model_name: str) -> Optional[np.ndarray]:
    """[512 image | 512 text] embedding block for one candidate (or None).

    MUST mirror training exactly (`scripts/clip_thumbnail_experiment.py`):
    the joint forward pass's ``image_embeds``/``text_embeds`` — projected AND
    L2-normalized. ``get_image_features``/``get_text_features`` return
    UN-normalized projections → distribution shift the model never saw.
    """
    pair = _load_clip(clip_model_name)
    if pair is None:
        return None
    import torch
    from PIL import Image

    model, processor = pair
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    with torch.no_grad():
        inp = processor(
            text=[title[:200] or " "], images=img, return_tensors="pt",
            padding=True, truncation=True,
        )
        out = model(**inp)
        img_emb = out.image_embeds[0].numpy()
        txt_emb = out.text_embeds[0].numpy()
    return np.concatenate([img_emb, txt_emb]).astype(np.float32)


def _frozen_reach_score(image_bytes: bytes, title: str) -> Optional[float]:
    """Legacy frozen-CLIP→XGBoost reach score (grouped-CV AUC 0.615)."""
    art = _load_reach()
    if art is None:
        return None
    emb = clip_features(image_bytes, title, art.get("clip_model", "openai/clip-vit-base-patch32"))
    if emb is None:
        return None
    x = np.concatenate([np.zeros(N_HAND, dtype=np.float32), emb]).reshape(1, -1)
    try:
        return float(art["model"].predict_proba(x)[0, 1])
    except Exception as e:
        logger.warning("ranker.predict_failed", error=str(e)[:120])
        return None


def reach_score(image_bytes: bytes, title: str) -> Optional[float]:
    """Reach score for one (thumbnail, title) — prefers the FINE-TUNED CLIP
    model (val AUC 0.668), falls back to the frozen XGBoost model (0.615)."""
    from src.features import reach_model

    if reach_model.available():
        s = reach_model.reach_clip_score(image_bytes, title)
        if s is not None:
            return s
    return _frozen_reach_score(image_bytes, title)


def reach_model_label() -> str:
    """Which reach model is actually serving (for the response metadata)."""
    from src.features import reach_model

    if reach_model.available():
        return "finetuned_clip_head_auc_0.668"
    return "frozen_clip_xgboost_auc_0.615" if _load_reach() is not None else "none"


def rank_candidates(
    candidates: List[dict],
    idea: Optional[str] = None,
    user_id: Optional[int] = None,
    plan: str = "free",
) -> dict:
    """Rank 2-4 candidates: ``[{title, image_bytes|None}]`` → ranked report.

    Each candidate gets the packaging rubric; thumbnail-bearing ones also get
    a reach score. Final order: blended rank when every candidate has both
    signals, else rubric order (with reach shown where it exists).
    """
    from src.features.packaging_rubric import score_title

    results = []
    for i, c in enumerate(candidates):
        title = (c.get("title") or "").strip()
        entry: dict = {"index": i, "title": title}
        rubric = score_title(title, idea=idea, user_id=user_id, plan=plan)
        entry["packaging"] = {
            k: rubric.get(k)
            for k in ("overall_score", "under_50_chars", "biggest_weakness", "principles")
        }
        entry["rubric_score"] = rubric.get("overall_score")
        if c.get("image_bytes"):
            entry["reach_score"] = reach_score(c["image_bytes"], title)
            entry["has_thumbnail"] = True
        else:
            entry["reach_score"] = None
            entry["has_thumbnail"] = False
        results.append(entry)

    have_reach = [r for r in results if r["reach_score"] is not None]
    blend = len(have_reach) == len(results) and len(results) > 0
    for r in results:
        rub = (r["rubric_score"] or 0) / 100.0
        if blend:
            # Rubric-LED. The reach model is a weak, experimental prior (absolute
            # cross-channel AUC ~0.67, never re-validated with grouped CV / confound
            # checks), so it gets a small weight — not the headline.
            r["rank_score"] = round(0.7 * rub + 0.3 * r["reach_score"], 4)
        else:
            r["rank_score"] = round(rub, 4)
    results.sort(key=lambda r: r["rank_score"], reverse=True)
    for pos, r in enumerate(results, start=1):
        r["rank"] = pos

    winner = results[0] if results else None
    return {
        "ranking_basis": "rubric+reach_prior" if blend else "rubric_only",
        "reach_model": reach_model_label() if blend else None,
        "winner_index": winner["index"] if winner else None,
        "disclaimer": (
            "This ranks your packaging against proven principles (coaching) — it is "
            "NOT a performance prediction. The reach prior is experimental and modest. "
            "Pick the one you'd click; the audience decides once it's live."
        ),
        "candidates": results,
    }

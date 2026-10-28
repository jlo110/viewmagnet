"""Fine-tuned reach model inference (end-to-end CLIP) — TODO #5 productionized.

`scripts/finetune_reach_clip.py` fine-tuned CLIP image+text + a fusion head on
the breakout label and beat the frozen-CLIP→XGBoost baseline: grouped/val AUC
**0.667 vs 0.615**. This serves that artifact (`data/models/reach_clip.pt`):
preprocess (thumbnail, title) exactly as training, forward through the same
`ReachCLIP` module, sigmoid the logit → P(breakout-reach).

Pure torch (no XGBoost) — so unlike the frozen path it doesn't co-load the two
OpenMP runtimes that deadlock on macOS; prod (Linux, CPU) runs it fine. Lazy,
singleton load; absent artifact → ``None`` so callers fall back gracefully.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Head-only artifact (val AUC 0.668): the fine-tune froze the CLIP backbone, so
# we ship only the 4 head tensors (~1MB) and load stock CLIP from HF — vs the
# 578MB full-state checkpoint. (A full-fine-tune artifact would set
# head_only=False with a complete state_dict; the loader handles both.)
REACH_CLIP_ARTIFACT = "data/models/reach_head.pt"
_TITLE_MAX = 200
_TOKEN_MAX = 32  # must match training (padding="max_length", max_length=32)

_model = None  # (module, processor) | False (absent/failed)


def _build_module(backbone: str):
    """Reconstruct the ReachCLIP architecture from the trainer (must match)."""
    import torch.nn as nn
    from transformers import CLIPModel

    class ReachCLIP(nn.Module):
        def __init__(self):
            super().__init__()
            self.clip = CLIPModel.from_pretrained(backbone)
            dim = self.clip.config.projection_dim
            self.head = nn.Sequential(
                nn.Linear(dim * 2, 256), nn.ReLU(), nn.Dropout(0.3), nn.Linear(256, 1)
            )

        def forward(self, pixel_values, input_ids, attention_mask):
            import torch

            out = self.clip(
                pixel_values=pixel_values, input_ids=input_ids, attention_mask=attention_mask
            )
            fused = torch.cat([out.image_embeds, out.text_embeds], dim=-1)
            return self.head(fused).squeeze(-1)

    return ReachCLIP()


def _load():
    global _model
    if _model is None:
        p = Path(REACH_CLIP_ARTIFACT)
        if not p.exists():
            logger.info("reach_clip.absent", path=str(p))
            _model = False
            return None
        try:
            import torch
            from transformers import CLIPProcessor

            ckpt = torch.load(p, map_location="cpu", weights_only=False)
            backbone = ckpt.get("backbone", "openai/clip-vit-base-patch32")
            module = _build_module(backbone)
            if ckpt.get("head_only"):
                # stock CLIP (already loaded in _build_module) + the saved head
                module.head.load_state_dict(ckpt["head_state"])
            else:
                module.load_state_dict(ckpt["state_dict"])
            module.eval()
            _model = (module, CLIPProcessor.from_pretrained(backbone))
            logger.info("reach_clip.loaded", val_auc=ckpt.get("val_auc"),
                        head_only=bool(ckpt.get("head_only")))
        except Exception as e:
            logger.warning("reach_clip.load_failed", error=str(e)[:160])
            _model = False
    return _model or None


def available() -> bool:
    return _load() is not None


def reach_clip_score(image_bytes: bytes, title: str) -> Optional[float]:
    """P(breakout-reach) for one (thumbnail, title) from the fine-tuned model."""
    pair = _load()
    if pair is None:
        return None
    import torch
    from PIL import Image

    module, processor = pair
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    enc = processor(
        text=[(title or " ")[:_TITLE_MAX]], images=[img], return_tensors="pt",
        padding="max_length", truncation=True, max_length=_TOKEN_MAX,
    )
    with torch.no_grad():
        logit = module(enc["pixel_values"], enc["input_ids"], enc["attention_mask"])
        return float(torch.sigmoid(logit)[0])

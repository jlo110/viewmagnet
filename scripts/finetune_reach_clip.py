"""End-to-end CLIP fine-tune for the REACH (breakout) predictor — GPU / Colab.

Frozen CLIP gave grouped-CV AUC ~0.61 for "will this thumbnail+title break out
beyond the channel's audience?" Fine-tuning the CLIP backbone on the breakout
label should beat that. This trains image+text CLIP end-to-end with a small
fusion head, channel-grouped train/val split, early-stopping on val AUC.

================ COLAB QUICKSTART ================
1. Runtime -> Change runtime type -> GPU (T4 is fine).
2. Upload `reach_dataset.csv` (from scripts/build_reach_dataset.py).
3. Run:
       !pip -q install "transformers>=4.40" torch torchvision scikit-learn pillow requests
       !python finetune_reach_clip.py --data reach_dataset.csv --epochs 6 --out reach_clip.pt
   (or paste this file into a cell and call main())
Thumbnails are downloaded on the fly from i.ytimg.com (cached under ./thumbs).
=================================================

Local Mac note: works on CPU/MPS too but slowly; this is built for CUDA.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

THUMBS = Path("thumbs")
BACKBONE = "openai/clip-vit-base-patch32"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def _download(vid: str) -> bool:
    import requests

    p = THUMBS / f"{vid}.jpg"
    if p.exists() and p.stat().st_size > 0:
        return True
    # hqdefault (480x360) ALWAYS exists and is plenty for CLIP (resizes to 224).
    # Fetching it directly avoids the maxresdefault 404→retry that made the 40k
    # pre-download stall on Kaggle.
    try:
        r = requests.get(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", timeout=8)
        if r.status_code == 200 and len(r.content) > 1000:
            p.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


def _read_csv(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        r["breakout"] = int(r["breakout"])
    return rows


def _make_dataset(rows, processor):
    import torch
    from PIL import Image
    from torch.utils.data import Dataset

    class ReachDS(Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, i):
            r = self.rows[i]
            try:
                img = Image.open(THUMBS / f"{r['video_id']}.jpg").convert("RGB")
            except Exception:
                img = Image.new("RGB", (224, 224))
            enc = processor(text=[(r["title"] or " ")[:200]], images=[img],
                            return_tensors="pt", padding="max_length",
                            truncation=True, max_length=32)
            return (
                enc["pixel_values"][0],
                enc["input_ids"][0],
                enc["attention_mask"][0],
                torch.tensor(float(r["breakout"])),
            )

    return ReachDS(rows)


# --------------------------------------------------------------------------- #
# Model: CLIP backbone + fusion head
# --------------------------------------------------------------------------- #
def _build_model(unfreeze_last: int, backbone: str):
    import torch
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
            # Freeze everything, then unfreeze the head + last N transformer layers
            for p in self.clip.parameters():
                p.requires_grad = False
            if unfreeze_last > 0:
                for enc in (self.clip.vision_model.encoder.layers,
                            self.clip.text_model.encoder.layers):
                    for layer in enc[-unfreeze_last:]:
                        for p in layer.parameters():
                            p.requires_grad = True
                for proj in (self.clip.visual_projection, self.clip.text_projection):
                    for p in proj.parameters():
                        p.requires_grad = True

        def forward(self, pixel_values, input_ids, attention_mask):
            out = self.clip(pixel_values=pixel_values, input_ids=input_ids,
                            attention_mask=attention_mask)
            fused = torch.cat([out.image_embeds, out.text_embeds], dim=-1)
            return self.head(fused).squeeze(-1)

    return ReachCLIP()


# --------------------------------------------------------------------------- #
# Train
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, help="reach_dataset.csv")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--unfreeze-last", type=int, default=3, help="0 = head only (linear probe)")
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--out", default="reach_clip.pt")
    # OPT-IN accuracy lever #3: bigger backbone. Default unchanged (ViT-B/32).
    # A/B "openai/clip-vit-large-patch14" on Colab; KEEP ONLY IF val AUC beats
    # the frozen 0.615 baseline (bigger can overfit on small data).
    ap.add_argument("--backbone", default=BACKBONE,
                    help="any CLIP checkpoint, e.g. openai/clip-vit-large-patch14")
    ap.add_argument("--limit", type=int, default=0,
                    help="subsample to N rows (0 = all). Use a smaller N for a fast first run.")
    args = ap.parse_args()

    import torch
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupShuffleSplit
    from torch.utils.data import DataLoader
    from transformers import CLIPProcessor

    THUMBS.mkdir(exist_ok=True)
    rows = _read_csv(args.data)
    if args.limit and args.limit < len(rows):
        import random
        random.Random(42).shuffle(rows)
        rows = rows[:args.limit]
    print(f"{len(rows):,} rows, breakout={np.mean([r['breakout'] for r in rows]):.0%}")

    # Channel-grouped split (no channel in both train and val).
    groups = np.array([r["channel_id"] for r in rows])
    tr_idx, va_idx = next(GroupShuffleSplit(1, test_size=args.val_frac, random_state=42)
                          .split(rows, groups=groups))
    tr_rows = [rows[i] for i in tr_idx]
    va_rows = [rows[i] for i in va_idx]
    print(f"train {len(tr_rows):,} / val {len(va_rows):,} "
          f"({len(set(groups[tr_idx]))}/{len(set(groups[va_idx]))} channels)")

    print(f"pre-downloading {len(rows):,} thumbnails...", flush=True)
    vids = [r["video_id"] for r in rows]
    ok = 0
    with ThreadPoolExecutor(max_workers=48) as ex:
        for i, got in enumerate(ex.map(_download, vids), 1):
            ok += bool(got)
            if i % 500 == 0:
                print(f"  downloaded {i:,}/{len(vids):,} ({ok:,} ok)", flush=True)
    print(f"thumbnails ready: {ok:,}/{len(vids):,}", flush=True)

    device = ("cuda" if torch.cuda.is_available()
              else "mps" if torch.backends.mps.is_available() else "cpu")
    print("device:", device)
    processor = CLIPProcessor.from_pretrained(args.backbone)
    model = _build_model(args.unfreeze_last, args.backbone).to(device)

    tr_dl = DataLoader(_make_dataset(tr_rows, processor), batch_size=args.batch,
                       shuffle=True, num_workers=2, pin_memory=(device == "cuda"))
    va_dl = DataLoader(_make_dataset(va_rows, processor), batch_size=args.batch,
                       num_workers=2)

    # Discriminative LRs: tiny for the backbone, larger for the fresh head.
    head_p = list(model.head.parameters())
    back_p = [p for n, p in model.named_parameters() if p.requires_grad and not n.startswith("head.")]
    opt = torch.optim.AdamW([{"params": back_p, "lr": args.lr},
                             {"params": head_p, "lr": args.head_lr}])
    pos_w = torch.tensor((1 - np.mean([r["breakout"] for r in tr_rows]))
                         / max(np.mean([r["breakout"] for r in tr_rows]), 1e-6))
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_w.to(device))

    best_auc = 0.0
    for epoch in range(args.epochs):
        model.train()
        for px, ids, am, y in tr_dl:
            px, ids, am, y = px.to(device), ids.to(device), am.to(device), y.to(device)
            opt.zero_grad()
            loss = loss_fn(model(px, ids, am), y)
            loss.backward()
            opt.step()
        # validate
        model.eval()
        ys, ps = [], []
        with torch.no_grad():
            for px, ids, am, y in va_dl:
                logit = model(px.to(device), ids.to(device), am.to(device))
                ps.extend(torch.sigmoid(logit).cpu().numpy().tolist())
                ys.extend(y.numpy().tolist())
        auc = roc_auc_score(ys, ps)
        print(f"epoch {epoch+1}/{args.epochs}  val AUC = {auc:.3f}"
              + ("  *" if auc > best_auc else ""))
        if auc > best_auc:
            best_auc = auc
            torch.save({"state_dict": model.state_dict(), "backbone": args.backbone,
                        "val_auc": auc, "unfreeze_last": args.unfreeze_last}, args.out)

    print(f"best val AUC = {best_auc:.3f}  (frozen-CLIP baseline was ~0.61)")
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

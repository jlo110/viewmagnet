"""Go/no-go for multimodal: does a PROPER frozen CLIP beat the 0.690 baseline?

Phase 6.1 showed the *cached* embeddings (generic ImageNet CNN + generic
MiniLM) add no signal. Before investing in end-to-end fine-tuning, this tests
the cheaper question: does a real vision-language backbone (CLIP), run frozen on
the actual thumbnails + titles, carry any "overperform" signal the hand-crafted
features lack?

  - If base + CLIP(image/text) clearly beats base-alone (0.690 grouped) -> a
    thumbnail/text signal exists; end-to-end fine-tuning is worth the GPU.
  - If it's flat/negative -> the thumbnail just doesn't encode this label;
    fine-tuning won't rescue it.

IMPORTANT — runs in TWO separate processes (torch and xgboost each bundle their
own OpenMP runtime; loading both in one process segfaults on macOS):
    --phase extract : download thumbnails + CLIP embed (torch only) -> .npz
    --phase eval    : channel-grouped CV on the saved features (xgboost only)

Usage:
    python -m scripts.clip_thumbnail_experiment --phase extract --sample 5000
    python -m scripts.clip_thumbnail_experiment --phase eval --folds 3
"""
from __future__ import annotations

import argparse
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

CACHE = Path("data/cache")
THUMB_DIR = Path("data/thumbnails")
FEATS = THUMB_DIR / "clip_feats.npz"
CLIP_MODEL = "openai/clip-vit-base-patch32"
SERVED_GROUPED_BASE = 0.690  # lean 25-feat grouped-CV balanced-acc (the bar)


def _thumb_path(vid: str) -> Path:
    return THUMB_DIR / f"{vid}.jpg"


def _download_one(vid: str) -> bool:
    import requests

    p = _thumb_path(vid)
    if p.exists() and p.stat().st_size > 0:
        return True
    for q in ("maxresdefault", "hqdefault"):
        try:
            r = requests.get(f"https://i.ytimg.com/vi/{vid}/{q}.jpg", timeout=10)
            if r.status_code == 200 and len(r.content) > 1000:
                p.write_bytes(r.content)
                return True
        except Exception:
            continue
    return False


def phase_extract(sample: int, batch: int, device: str) -> int:
    """torch-only: download thumbnails, CLIP-embed, save features to FEATS."""
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    d = pickle.load(open(CACHE / "exp_features.pkl", "rb"))
    X_base = np.asarray(d["X_base"], dtype=np.float32)
    y_all = np.asarray(d["y"]).astype(int)
    video_ids = [l.strip() for l in open(CACHE / "video_ids.txt") if l.strip()]
    titles = [l.rstrip("\n") for l in open(CACHE / "titles.txt")]
    cmap = json.load(open(CACHE / "video_channels.json"))

    rng = np.random.default_rng(42)
    cand = [i for i in range(len(video_ids)) if video_ids[i] in cmap]
    rng.shuffle(cand)
    cand = cand[:sample]
    print(f"candidates with channel label: {len(cand):,}")

    sample_vids = [video_ids[i] for i in cand]
    print("downloading thumbnails...")
    with ThreadPoolExecutor(max_workers=16) as ex:
        ok = list(ex.map(_download_one, sample_vids))
    kept = [cand[i] for i in range(len(cand)) if ok[i]]
    print(f"downloaded {sum(ok):,}/{len(cand):,} thumbnails")

    torch.set_num_threads(max(1, torch.get_num_threads() or 4))
    print(f"loading {CLIP_MODEL} on {device} ...")
    model = CLIPModel.from_pretrained(CLIP_MODEL).to(device).eval()
    proc = CLIPProcessor.from_pretrained(CLIP_MODEL)

    img_emb, txt_emb, rows = [], [], []
    with torch.no_grad():
        for s in range(0, len(kept), batch):
            imgs, txts, keep = [], [], []
            for i in kept[s:s + batch]:
                try:
                    imgs.append(Image.open(_thumb_path(video_ids[i])).convert("RGB"))
                except Exception:
                    continue
                txts.append((titles[i] if i < len(titles) else "")[:200] or " ")
                keep.append(i)
            if not imgs:
                continue
            inp = proc(text=txts, images=imgs, return_tensors="pt",
                       padding=True, truncation=True).to(device)
            out = model(**inp)
            img_emb.append(out.image_embeds.detach().cpu().numpy())
            txt_emb.append(out.text_embeds.detach().cpu().numpy())
            rows.extend(keep)
            print(f"  embedded {len(rows):,}/{len(kept):,}", end="\r")
    print()
    if len(rows) < 100:
        print("too few embedded thumbnails.")
        return 1

    rows = np.array(rows)
    np.savez_compressed(
        FEATS,
        img_emb=np.vstack(img_emb).astype(np.float32),
        txt_emb=np.vstack(txt_emb).astype(np.float32),
        Xb=X_base[rows],
        y=y_all[rows],
        groups=np.array([cmap[video_ids[i]] for i in rows]),
        vids=np.array([video_ids[i] for i in rows]),  # for absolute-target labels
    )
    print(f"saved {FEATS} ({len(rows):,} videos)")
    return 0


def phase_eval(folds: int) -> int:
    """xgboost-only: channel-grouped CV on the saved CLIP features."""
    from scripts.train_multimodal_predictor import _cv_score

    if not FEATS.exists():
        print(f"{FEATS} not found — run --phase extract first.")
        return 1
    z = np.load(FEATS, allow_pickle=True)
    Xb, y, groups = z["Xb"], z["y"], z["groups"]
    img_emb, txt_emb = z["img_emb"], z["txt_emb"]
    print(f"evaluating on {len(y):,} videos / {len(set(groups.tolist())):,} channels")

    variants = {
        "base        ": Xb,
        "base+clipImg": np.hstack([Xb, img_emb]),
        "base+clipTxt": np.hstack([Xb, txt_emb]),
        "base+clipAll": np.hstack([Xb, img_emb, txt_emb]),
    }
    print(f"\n{'variant':<13}{'feats':>7}  {'balanced_acc':>15}{'AUC':>14}")
    base_here = None
    best = ("", -1.0)
    for name, X in variants.items():
        s = _cv_score(np.ascontiguousarray(X.astype(np.float32)), y, groups, folds)
        ba, auc = s["balanced_acc"], s["auc"]
        print(f"{name:<13}{X.shape[1]:>7}  {ba[0]:>10.3f}±{ba[1]:.3f}{auc[0]:>9.3f}±{auc[1]:.3f}")
        if name.strip() == "base":
            base_here = ba[0]
        if ba[0] > best[1]:
            best = (name.strip(), ba[0])

    print("-" * 56)
    print(f"baseline (25 hand-crafted, grouped, full data): {SERVED_GROUPED_BASE:.3f}")
    print(f"best={best[0]} {best[1]:.3f}  vs base-on-this-sample {base_here:.3f}  "
          f"-> CLIP delta {best[1]-base_here:+.3f}")
    print("GO for fine-tuning if CLIP delta is clearly positive; otherwise the "
          "thumbnail/title carry no extra signal for this label.")
    return 0


def _fetch_views_and_subs(vids):
    """Return (view_count[], subs_per_video[]) for vids via the YouTube API.
    Missing videos get -1 view_count (dropped by caller)."""
    from src.youtube.client import YouTubeClient

    client = YouTubeClient()
    views = {}
    chans = {}
    for i in range(0, len(vids), 50):
        try:
            for info in client.get_video_details(list(vids[i:i + 50])):
                views[info.video_id] = info.view_count
                chans[info.video_id] = getattr(info, "channel_id", None)
        except Exception as e:
            print(f"  video batch {i} failed: {str(e)[:60]}")
    uniq_ch = {c for c in chans.values() if c}
    subs = {}
    uch = list(uniq_ch)
    for i in range(0, len(uch), 50):
        try:
            for ci in client.get_channel_details(uch[i:i + 50]):
                subs[ci.channel_id] = getattr(ci, "subscriber_count", 0) or 0
        except Exception as e:
            print(f"  channel batch {i} failed: {str(e)[:60]}")
    vc = np.array([views.get(v, -1) for v in vids], dtype=float)
    sv = np.array([max(subs.get(chans.get(v), 0), 1) for v in vids], dtype=float)
    return vc, sv


def phase_eval_abs(folds: int) -> int:
    """xgboost-only: re-test base vs CLIP against an ABSOLUTE target
    (views-per-subscriber top quartile) instead of channel-relative overperform."""
    from scripts.train_multimodal_predictor import _cv_score

    if not FEATS.exists():
        print(f"{FEATS} not found — run --phase extract first.")
        return 1
    z = np.load(FEATS, allow_pickle=True)
    Xb, groups, vids = z["Xb"], z["groups"], z["vids"]
    img_emb, txt_emb = z["img_emb"], z["txt_emb"]

    print(f"fetching views + subs for {len(vids):,} videos...")
    vc, sv = _fetch_views_and_subs(vids)
    keep = vc >= 0
    print(f"resolved {keep.sum():,}/{len(vids):,} videos")
    vps = np.log1p(vc[keep] / sv[keep])               # log views-per-subscriber
    thr = np.quantile(vps, 0.75)
    y = (vps >= thr).astype(int)                       # top-quartile reach
    Xb, img_emb, txt_emb, groups = Xb[keep], img_emb[keep], txt_emb[keep], groups[keep]
    print(f"ABSOLUTE target = top-quartile views-per-sub ({y.mean():.0%} positive), "
          f"{len(set(groups.tolist())):,} channels")

    variants = {
        "base        ": Xb,
        "base+clipImg": np.hstack([Xb, img_emb]),
        "base+clipTxt": np.hstack([Xb, txt_emb]),
        "base+clipAll": np.hstack([Xb, img_emb, txt_emb]),
    }
    print(f"\n{'variant':<13}{'feats':>7}  {'balanced_acc':>15}{'AUC':>14}")
    base_here, best = None, ("", -1.0)
    for name, X in variants.items():
        s = _cv_score(np.ascontiguousarray(X.astype(np.float32)), y, groups, folds)
        ba, auc = s["balanced_acc"], s["auc"]
        print(f"{name:<13}{X.shape[1]:>7}  {ba[0]:>10.3f}±{ba[1]:.3f}{auc[0]:>9.3f}±{auc[1]:.3f}")
        if name.strip() == "base":
            base_here = (ba[0], auc[0])
        if auc[0] > best[1]:
            best = (name.strip(), auc[0])
    print("-" * 56)
    print(f"best-by-AUC={best[0]} AUC {best[1]:.3f}  vs base AUC {base_here[1]:.3f}  "
          f"-> CLIP AUC delta {best[1]-base_here[1]:+.3f}")
    print("If the CLIP AUC delta is clearly bigger here than on the overperform "
          "target (+0.012), thumbnails DO carry signal — just for absolute reach.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", required=True, choices=["extract", "eval", "eval-abs"])
    ap.add_argument("--sample", type=int, default=5000)
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    args = ap.parse_args()
    if args.phase == "extract":
        return phase_extract(args.sample, args.batch, args.device)
    if args.phase == "eval-abs":
        return phase_eval_abs(args.folds)
    return phase_eval(args.folds)


if __name__ == "__main__":
    raise SystemExit(main())

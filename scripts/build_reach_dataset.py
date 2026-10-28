"""Build a scaled REACH dataset for the thumbnail/title breakout model.

Reach = did a video break out beyond its channel's own audience. We measure it
as **views-per-subscriber**, and (key accuracy fix) **age-normalize** it: a
video published yesterday and one published 5 months ago can't be compared on
raw views, so we rank reach *within age buckets*. Output is a CSV the GPU
fine-tune trainer (`finetune_reach_clip.py`) consumes.

For each video it fetches (YouTube API): current view_count, published_at, and
the channel's subscriber_count. Resumable + cached, so re-running continues.

Output columns:
  video_id, channel_id, title, views, subs, age_days, views_per_sub,
  reach_score (age-bucket percentile of log views_per_sub, 0..1),
  breakout (1 if reach_score >= --quantile)

Usage:
  python -m scripts.build_reach_dataset --limit 40000          # 40k videos
  python -m scripts.build_reach_dataset                        # all ~140k
Quota: ~1 unit / 50 videos + ~1 / 50 channels. Shares keys with the live
scheduler, so it self-throttles and is resumable if quota runs out.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

CACHE = Path("data/cache")
RAW = Path("data/reach/raw.json")          # {video_id: {views, subs, age_days, title, channel}}
OUT = Path("data/reach/reach_dataset.csv")


def _load_inputs(limit):
    video_ids = [l.strip() for l in open(CACHE / "video_ids.txt") if l.strip()]
    titles = [l.rstrip("\n") for l in open(CACHE / "titles.txt")]
    cmap = json.load(open(CACHE / "video_channels.json"))
    title_by = {video_ids[i]: (titles[i] if i < len(titles) else "") for i in range(len(video_ids))}
    vids = [v for v in video_ids if v in cmap]
    if limit:
        vids = vids[:limit]
    return vids, cmap, title_by


def _fetch(vids, cmap):
    """Resumable fetch of view/sub/age into RAW. Returns the raw dict."""
    from src.youtube.client import YouTubeClient

    RAW.parent.mkdir(parents=True, exist_ok=True)
    raw = json.load(open(RAW)) if RAW.exists() else {}
    todo = [v for v in vids if v not in raw]
    print(f"to fetch: {len(todo):,} of {len(vids):,} (resuming from {len(raw):,})")

    client = YouTubeClient()
    now = datetime.now(timezone.utc)
    subs_cache: dict[str, int] = {}
    flush = 0
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        try:
            infos = client.get_video_details(batch)
        except Exception as e:
            print(f"  video batch {i} failed: {str(e)[:50]}")
            continue
        # subscriber counts for any new channels in this batch
        need_ch = {cmap[inf.video_id] for inf in infos if cmap.get(inf.video_id) not in subs_cache}
        need_ch = [c for c in need_ch if c]
        for j in range(0, len(need_ch), 50):
            try:
                for ci in client.get_channel_details(need_ch[j:j + 50]):
                    subs_cache[ci.channel_id] = getattr(ci, "subscriber_count", 0) or 0
            except Exception as e:
                print(f"  channel batch failed: {str(e)[:50]}")
        for inf in infos:
            ch = cmap.get(inf.video_id)
            pub = getattr(inf, "published_at", None)
            if pub is not None and pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age = max((now - pub).days, 1) if pub else None
            raw[inf.video_id] = {
                "views": int(inf.view_count or 0),
                "subs": int(subs_cache.get(ch, 0)),
                "age_days": age,
                "channel": ch,
            }
            flush += 1
        if flush >= 2000:
            json.dump(raw, open(RAW, "w"))
            flush = 0
            print(f"  ... {len(raw):,} fetched")
        if client.get_quota_status()["total_remaining"] < 100:
            print("low quota — stopping (resumable).")
            break
    json.dump(raw, open(RAW, "w"))
    return raw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=40000)
    ap.add_argument("--quantile", type=float, default=0.75)
    ap.add_argument("--age-buckets", type=int, default=8)
    args = ap.parse_args()

    vids, cmap, title_by = _load_inputs(args.limit)
    raw = _fetch(vids, cmap)

    # Assemble rows with a clean reach metric.
    rows = []
    for v, d in raw.items():
        if d["views"] is None or d["subs"] in (None, 0) or not d["age_days"]:
            continue
        vps = d["views"] / max(d["subs"], 1)
        rows.append({
            "video_id": v, "channel_id": d["channel"],
            "title": (title_by.get(v, "") or "").replace("\n", " "),
            "views": d["views"], "subs": d["subs"], "age_days": d["age_days"],
            "views_per_sub": vps, "log_vps": float(np.log1p(vps)),
        })
    if not rows:
        print("no usable rows yet — re-run to fetch more.")
        return 0

    # Age-normalized reach: percentile of log_vps WITHIN age buckets, so old and
    # new videos are judged fairly. This is the label the model actually learns.
    ages = np.array([r["age_days"] for r in rows], dtype=float)
    edges = np.quantile(ages, np.linspace(0, 1, args.age_buckets + 1))
    bucket = np.clip(np.digitize(ages, edges[1:-1]), 0, args.age_buckets - 1)
    logvps = np.array([r["log_vps"] for r in rows])
    reach = np.zeros(len(rows))
    for b in range(args.age_buckets):
        m = bucket == b
        if m.sum() > 1:
            order = logvps[m].argsort().argsort()
            reach[m] = order / max(m.sum() - 1, 1)
    thr = args.quantile
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "channel_id", "title", "views", "subs",
                    "age_days", "views_per_sub", "reach_score", "breakout"])
        for r, rs in zip(rows, reach):
            w.writerow([r["video_id"], r["channel_id"], r["title"], r["views"],
                        r["subs"], r["age_days"], f"{r['views_per_sub']:.4f}",
                        f"{rs:.4f}", int(rs >= thr)])
    print(f"wrote {len(rows):,} rows -> {OUT}  "
          f"({np.mean(reach >= thr):.0%} breakout, {len(set(r['channel_id'] for r in rows)):,} channels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Resolve a video_id -> channel_id map for the 144k cache via the YouTube API.

Needed for **channel-grouped** evaluation of the content model (the surviving
cache has video_ids but no channel labels). Saves an incremental, resumable
JSON map at data/cache/video_channels.json.

Cost: 1 quota unit per 50 video ids (~2,900 units for the full 144k file).
Deleted videos simply don't resolve (skipped). Resumable: re-running picks up
where it left off.

Usage:
    python -m scripts.resolve_video_channels                 # full file
    python -m scripts.resolve_video_channels --limit 50000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

VIDEO_IDS = Path("data/cache/video_ids.txt")
OUT = Path("data/cache/video_channels.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--flush-every", type=int, default=2000, help="save progress every N resolved")
    args = ap.parse_args()

    from src.youtube.client import YouTubeClient

    vids = [l.strip() for l in open(VIDEO_IDS) if l.strip()]
    if args.limit:
        vids = vids[: args.limit]

    mapping: dict[str, str] = {}
    if OUT.exists():
        mapping = json.load(open(OUT))
        print(f"resuming: {len(mapping):,} already resolved")

    todo = [v for v in vids if v not in mapping]
    print(f"to resolve: {len(todo):,} of {len(vids):,}")

    client = YouTubeClient()
    since_flush = 0
    for i in range(0, len(todo), 50):
        batch = todo[i : i + 50]
        try:
            for info in client.get_video_details(batch):
                cid = getattr(info, "channel_id", None)
                if cid:
                    mapping[info.video_id] = cid
                    since_flush += 1
        except Exception as e:
            logger.warning("resolve.batch_failed", start=i, error=str(e))

        if since_flush >= args.flush_every:
            json.dump(mapping, open(OUT, "w"))
            since_flush = 0
            print(f"  ... {len(mapping):,} resolved")

        if client.get_quota_status()["total_remaining"] < 50:
            print("low quota — stopping (resumable).")
            break

    json.dump(mapping, open(OUT, "w"))
    uniq = len(set(mapping.values()))
    print(f"done: {len(mapping):,} videos -> {uniq:,} unique channels. saved {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

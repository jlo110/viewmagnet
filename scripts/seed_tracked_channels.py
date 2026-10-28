"""Enroll channels into velocity tracking (``tracked_channels``).

The velocity time-series is rebuilt by watching channels for new uploads and
sampling each new video at 1h/6h/24h/3d/7d/14d/30d. That only happens for
channels in ``tracked_channels`` — which is near-empty after the data loss.
This script enrolls channels so the scheduler's discovery/collection jobs have
something to watch.

Sources (combine as needed):
  --from-channels-table   enroll every channel already in the `channels` table
  --ids UCxxx,UCyyy        enroll explicit channel IDs (comma-separated)
  --file path              enroll channel IDs from a file (one per line)
  --from-video-ids file    resolve channel IDs from a file of VIDEO ids via the
                           YouTube API (e.g. data/cache/video_ids.txt) and
                           enroll the unique channels — rebuilds a tracking set
                           aligned with the original 144k training distribution.

Usage:
    python -m scripts.seed_tracked_channels --from-channels-table
    python -m scripts.seed_tracked_channels --ids UC_x2y... --ids UC_ab...
    python -m scripts.seed_tracked_channels --from-video-ids data/cache/video_ids.txt --limit 5000

Idempotent: channels already tracked are skipped. Quota note: --from-video-ids
costs 1 unit per 50 video ids resolved.
"""
from __future__ import annotations

import argparse

import structlog

logger = structlog.get_logger(__name__)


def _existing_tracked(session) -> set[str]:
    from src.database.models import TrackedChannel
    return {c.channel_id for c in session.query(TrackedChannel.channel_id).all()}


def _enroll(session, channel_ids: set[str], recent_video_count: int = 1) -> int:
    from src.database.models import TrackedChannel

    already = _existing_tracked(session)
    added = 0
    for cid in channel_ids:
        if not cid or not cid.startswith("UC") or cid in already:
            continue
        session.add(TrackedChannel(
            channel_id=cid,
            recent_video_count=recent_video_count,
            is_active=True,
            source="seed",
        ))
        already.add(cid)
        added += 1
    session.commit()
    return added


def _channels_from_table(session) -> set[str]:
    from src.database.models import Channel
    return {c.channel_id for c in session.query(Channel.channel_id).all()}


def _channels_from_video_ids(path: str, limit: int | None) -> set[str]:
    """Resolve unique channel IDs for a file of video IDs via the YouTube API."""
    from src.youtube.client import YouTubeClient

    with open(path) as fh:
        vids = [ln.strip() for ln in fh if ln.strip()]
    if limit:
        vids = vids[:limit]

    client = YouTubeClient()
    channels: set[str] = set()
    for i in range(0, len(vids), 50):
        batch = vids[i:i + 50]
        try:
            for info in client.get_video_details(batch):
                cid = getattr(info, "channel_id", None)
                if cid:
                    channels.add(cid)
        except Exception as e:
            logger.warning("seed.resolve_failed", batch_start=i, error=str(e))
        if client.get_quota_status()["total_remaining"] < 50:
            logger.warning("seed.low_quota_stop", resolved=len(channels))
            break
    return channels


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-channels-table", action="store_true")
    p.add_argument("--ids", action="append", default=[], help="comma-separated channel IDs")
    p.add_argument("--file", help="file of channel IDs, one per line")
    p.add_argument("--from-video-ids", help="file of VIDEO ids to resolve to channels")
    p.add_argument("--limit", type=int, default=None, help="cap video ids resolved")
    args = p.parse_args()

    from src.database.connection import get_session

    targets: set[str] = set()
    for chunk in args.ids:
        targets.update(x.strip() for x in chunk.split(","))
    if args.file:
        with open(args.file) as fh:
            targets.update(ln.strip() for ln in fh if ln.strip())

    with get_session() as session:
        if args.from_channels_table:
            targets.update(_channels_from_table(session))
        if args.from_video_ids:
            targets.update(_channels_from_video_ids(args.from_video_ids, args.limit))

        targets = {t for t in targets if t and t.startswith("UC")}
        if not targets:
            print("No channel IDs to enroll. Pass --from-channels-table / --ids / --file / --from-video-ids.")
            return 1

        added = _enroll(session, targets)
        total = len(_existing_tracked(session))

    print(f"Enrolled {added} new channel(s). Now tracking {total} total.")
    print("The scheduler's velocity jobs will start watching them on the next tick.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

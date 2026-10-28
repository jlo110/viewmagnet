"""Expand the tracked set with currently-popular creators (plan 8.11).

Manual CLI wrapper around ``src.tracking.channel_expansion`` (which the weekly
scheduler job also uses). Sweeps ``videos.list chart=mostPopular`` per
(region × category) — 1 quota unit/call, niche-stratified — and enrolls
channels not already tracked. English-speaking regions by default (plan 8.12);
override with ``--regions`` for an international expansion.

Usage:
    python -m scripts.expand_tracked_channels                 # English sweep
    python -m scripts.expand_tracked_channels --limit 1000    # cap new enrollments
    python -m scripts.expand_tracked_channels --regions US,GB --categories 20,24
    python -m scripts.expand_tracked_channels --dry-run
"""
from __future__ import annotations

import argparse

from src.tracking.channel_expansion import (
    DEFAULT_CATEGORIES,
    DEFAULT_REGIONS,
    expand_tracked_set,
    fetch_popular_channels,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regions", default=",".join(DEFAULT_REGIONS))
    ap.add_argument("--categories", default=None,
                    help="comma-separated category ids (default: broad set)")
    ap.add_argument("--limit", type=int, default=None, help="cap NEW enrollments")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from src.database.connection import get_session
    from src.database.models import TrackedChannel
    from src.youtube.client import YouTubeClient

    regions = [r.strip().upper() for r in args.regions.split(",") if r.strip()]
    categories = (
        [c.strip() or None for c in args.categories.split(",")]
        if args.categories else DEFAULT_CATEGORIES
    )
    client = YouTubeClient()

    if args.dry_run:
        found = fetch_popular_channels(client, regions, categories)
        with get_session() as session:
            already = {r[0] for r in session.query(TrackedChannel.channel_id).all()}
        new = len([ch for ch in found if ch not in already])
        print(f"Sweep found {len(found)} channels; {new} new (rest already tracked).")
        return 0

    with get_session() as session:
        result = expand_tracked_set(session, client, regions, categories, limit=args.limit)
    print(f"Enrolled {result['enrolled']} new channel(s). Now tracking "
          f"{result['total_active']} total (swept {result['swept']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

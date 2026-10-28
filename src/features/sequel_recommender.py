"""Durability-driven "what to do about your own breakout" recommendation (3.1).

When the validated detector flags a breakout on the *user's own* channel, the
durability grade (sustain vs flash) tells them what to DO about it — make a
sequel while it has attention, or capture the spike before it cools. This is
descriptive coaching grounded in the measured durability label, NOT a
performance prediction (we never claim a sequel will also break out).
"""
from __future__ import annotations

from typing import Optional


def sequel_recommendation(durability_label: Optional[str]) -> dict:
    """{action, why, urgency} keyed off the durability label.

    Pure — unit-testable. Labels come from ``durability_grader.grade``:
    likely_to_sustain | could_flash | uncertain | too_early."""
    if durability_label == "likely_to_sustain":
        return {
            "action": "Make a sequel — and pour fuel on this one now",
            "why": "Our durability read says this is sticking, not a one-day spike. "
                   "While it still has attention: ship a part 2 / same-format follow-up, "
                   "pin a comment pointing to it, and link it from your next upload.",
            "urgency": "high",
        }
    if durability_label == "could_flash":
        return {
            "action": "Capture the spike before it cools",
            "why": "Big jump, but the durability read says it's more likely a flash than a "
                   "lasting hit. Convert the burst now — pin a CTA, end-screen to your best "
                   "evergreen, post to community — rather than banking on a sequel.",
            "urgency": "high",
        }
    if durability_label == "too_early":
        return {
            "action": "Wait for the 24h read before deciding",
            "why": "It's breaking out, but too young to grade durability. Check back around "
                   "the 24h mark — if it's sustaining, that's your sequel signal.",
            "urgency": "low",
        }
    # uncertain / missing
    return {
        "action": "Watch it — durability is unclear",
        "why": "Breaking out, but the sustain-vs-flash read isn't confident yet. Keep an eye "
               "on it; don't commit to a sequel until the trajectory firms up.",
        "urgency": "medium",
    }

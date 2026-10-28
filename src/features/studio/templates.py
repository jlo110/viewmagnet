"""Studio templates (Week 5).

A *template* is a partial ``EditSpec`` snapshot that pre-configures the
"opinionated" parts of a short — captions style, transitions, auto-zoom
behavior, camera defaults — without touching the *content* fields the user
brought to the editor (the source clip, transcript, B-roll picks).

Apply flow:
1. UI calls ``POST /studio/sessions/{key}/apply-template`` with a name.
2. Backend looks the preset up in :data:`TEMPLATE_PRESETS`.
3. Preset is **deep-merged over the user's current spec** — preset wins.
4. The user can keep tweaking; the preset is a new baseline, not a lock.

We intentionally keep this as plain dicts (not Pydantic models) so the
merge logic doesn't have to deal with default-factories or model identity.
``EditSpec`` validates the merged result before persistence.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from src.features.studio.spec import EditSpec

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------
#
# Each preset overrides a subset of:
#   captions:   { style, position, color_highlight, uppercase, font_size, ... }
#   transitions:{ enabled, type, duration_ms, sfx_enabled }
#   auto_zoom:  { enabled, max_scale }
#   camera:     { ease_pan, bbox_overlay_enabled, n_subjects_requested }
#   brand_kit:  { font_family }
#
# NEVER touch ``clip`` (source video / transcript) or ``broll.clips`` —
# the user's content is sacred.

TEMPLATE_PRESETS: Dict[str, Dict[str, Any]] = {
    "podcast": {
        "captions": {
            "style": "mrbeast",
            "position": "bottom",
            "color_highlight": "#FFD400",
            "uppercase": True,
            "font_size": 88,
            "highlight_mode": "word",
        },
        "transitions": {
            "enabled": True,
            "type": "fade",
            "duration_ms": 250,
            "sfx_enabled": True,
        },
        "auto_zoom": {"enabled": True, "max_scale": 1.20},
        "camera": {"ease_pan": True, "bbox_overlay_enabled": False},
        "template": "podcast",
    },
    "tutorial": {
        "captions": {
            "style": "minimal",
            "position": "bottom",
            "color_primary": "#FFFFFF",
            "color_highlight": "#7DD3FC",
            "uppercase": False,
            "font_size": 64,
            "highlight_mode": "group",
        },
        "transitions": {
            "enabled": True,
            "type": "swipe",
            "duration_ms": 300,
            "sfx_enabled": False,
        },
        "auto_zoom": {"enabled": False, "max_scale": 1.10},
        "camera": {"ease_pan": False, "bbox_overlay_enabled": False},
        "template": "tutorial",
    },
    "reaction": {
        "captions": {
            "style": "hormozi",
            "position": "top",
            "color_highlight": "#FF4D8D",
            "uppercase": True,
            "font_size": 96,
            "highlight_mode": "word",
        },
        "transitions": {
            "enabled": True,
            "type": "whoosh",
            "duration_ms": 200,
            "sfx_enabled": True,
        },
        "auto_zoom": {"enabled": True, "max_scale": 1.40},
        "camera": {"ease_pan": True, "bbox_overlay_enabled": True},
        "template": "reaction",
    },
    "storytime": {
        "captions": {
            "style": "karaoke",
            "position": "middle",
            "color_highlight": "#FBBF24",
            "uppercase": False,
            "font_size": 72,
            "highlight_mode": "group",
        },
        "transitions": {
            "enabled": True,
            "type": "fade",
            "duration_ms": 500,
            "sfx_enabled": True,
        },
        "auto_zoom": {"enabled": True, "max_scale": 1.15},
        "camera": {"ease_pan": True, "bbox_overlay_enabled": False},
        "template": "storytime",
    },
    "talking-head": {
        "captions": {
            "style": "capcut",
            "position": "bottom",
            "color_highlight": "#A78BFA",
            "uppercase": False,
            "font_size": 72,
            "highlight_mode": "word",
        },
        "transitions": {
            "enabled": True,
            "type": "fade",
            "duration_ms": 200,
            "sfx_enabled": False,
        },
        "auto_zoom": {"enabled": True, "max_scale": 1.25},
        "camera": {
            "ease_pan": True,
            "bbox_overlay_enabled": False,
            "n_subjects_requested": 1,
        },
        "template": "talking-head",
    },
}

TEMPLATE_NAMES: List[str] = list(TEMPLATE_PRESETS.keys())


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``overrides`` INTO ``base``, recursing into dict values.

    Lists are replaced atomically (preset wins). Used to fold a preset
    on top of the user's current spec without clobbering unrelated fields.
    """
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def apply_template(spec: EditSpec, name: str) -> EditSpec:
    """Return a new :class:`EditSpec` with the named preset merged over ``spec``.

    Raises :class:`KeyError` if the template name isn't registered.
    """
    if name not in TEMPLATE_PRESETS:
        raise KeyError(f"unknown template '{name}'; known: {TEMPLATE_NAMES}")
    base = spec.model_dump(mode="json")
    merged = _deep_merge(base, TEMPLATE_PRESETS[name])
    return EditSpec.model_validate(merged)


def describe_templates() -> List[Dict[str, Any]]:
    """Lightweight catalog the frontend can render without re-importing
    every preset's structure."""
    descriptions = {
        "podcast": "Bold yellow captions, smooth pans, gentle punch-in on punchlines.",
        "tutorial": "Clean teal highlights, decisive swipes between cuts, no zoom drift.",
        "reaction": "Top-mounted pink captions, fast whoosh cuts, aggressive zoom on punchlines.",
        "storytime": "Narrative karaoke captions, long fades, soft punch-ins.",
        "talking-head": "Single-subject focus, violet captions, subtle zoom on emphasis.",
    }
    return [
        {
            "name": name,
            "description": descriptions.get(name, name),
            "caption_style": TEMPLATE_PRESETS[name]["captions"]["style"],
            "transition_type": TEMPLATE_PRESETS[name]["transitions"]["type"],
            "auto_zoom_enabled": TEMPLATE_PRESETS[name]["auto_zoom"]["enabled"],
        }
        for name in TEMPLATE_NAMES
    ]

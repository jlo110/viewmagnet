"""Centralized asset (font, image) path resolution.

Replaces hardcoded font paths in ``thumbnail_generator`` and ``hook_overlays``.
Override paths via env vars ``BOLD_FONT_PATH`` / ``REGULAR_FONT_PATH``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FONTS_DIR = _PROJECT_ROOT / "fonts"

_BOLD_CANDIDATES = [
    str(_FONTS_DIR / "Inter-Bold.ttf"),
    str(_FONTS_DIR / "Roboto-Bold.ttf"),
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

_REGULAR_CANDIDATES = [
    str(_FONTS_DIR / "Inter-Regular.ttf"),
    str(_FONTS_DIR / "Roboto-Regular.ttf"),
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _first_existing(env_var: str, candidates: list[str]) -> Optional[str]:
    override = os.environ.get(env_var)
    if override and os.path.exists(override):
        return override
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def get_bold_font_path() -> Optional[str]:
    """Return the first available bold font, or ``None`` if none found."""
    path = _first_existing("BOLD_FONT_PATH", _BOLD_CANDIDATES)
    if path is None:
        logger.warning("assets.no_bold_font_found", message="Falling back to PIL default font")
    return path


def get_regular_font_path() -> Optional[str]:
    """Return the first available regular font, or ``None`` if none found."""
    path = _first_existing("REGULAR_FONT_PATH", _REGULAR_CANDIDATES)
    if path is None:
        logger.warning("assets.no_regular_font_found", message="Falling back to PIL default font")
    return path


# Constants for backwards-compatible imports.
BOLD_FONT_PATH = get_bold_font_path()
REGULAR_FONT_PATH = get_regular_font_path()

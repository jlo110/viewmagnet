"""Backward-compatible re-exports for the legacy ``shorts_creator`` module.

The original ~2.5k LOC monolith has been split into
:mod:`src.features.shorts` (``fetch``, ``transcribe``, ``score``, ``clip``).
Importers keep using ``from src.features.shorts_creator import ShortsCreator``
during the transition; new code should import from :mod:`src.features.shorts`
directly.
"""
from __future__ import annotations

from src.features.shorts import Highlight, ShortsAnalysis, ShortsCreator, find_shorts

__all__ = ["Highlight", "ShortsAnalysis", "ShortsCreator", "find_shorts"]

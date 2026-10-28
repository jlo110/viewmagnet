"""AI Shorts Creator package.

Splits the previous ``src/features/shorts_creator.py`` monolith into:

* :mod:`src.features.shorts.models` - ``Highlight`` and ``ShortsAnalysis``
* :mod:`src.features.shorts.fetch` - YouTube ID parsing, comment fetching,
  viral pattern dictionary and transcript parsing helpers
* :mod:`src.features.shorts.transcribe` - Whisper-based transcription
  providers (Groq, OpenAI, local model)
* :mod:`src.features.shorts.score` - regex / LLM / audio scoring, quality
  checks, boundary refinement, ranking and diversification
* :mod:`src.features.shorts.clip` - SRT generation, vertical-crop ffmpeg
  extraction and editor-friendly export bundles

The :class:`ShortsCreator` orchestrator and the
:func:`find_shorts` convenience wrapper compose the modules above and
preserve the public API of the legacy module so importers keep working.
"""
from __future__ import annotations

from src.features.shorts.creator import ShortsCreator, find_shorts
from src.features.shorts.models import Highlight, ShortsAnalysis

__all__ = ["Highlight", "ShortsAnalysis", "ShortsCreator", "find_shorts"]

"""Lightweight language gating (no deps) for the English-targeted product.

The tracked-set expansion swept mostPopular charts across many regions, which
flooded the collection with non-English channels (Armenian/Tamil/Hindi/Japanese/
Arabic news, etc.). The product targets English creators, so the user-facing
radar (and ideally the tracked set) should be English-focused.

Two signals, no model dependency:
1. ``default_audio_language`` — YouTube's own metadata (captured in 8.5). Most
   reliable when present; catches Latin-script non-English (es/pt/fr/de) too.
2. **Script ratio** — fraction of letters that are NOT Latin. Catches the
   dominant, most-jarring cases (non-Latin scripts) when audio-language is null.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

NON_LATIN_THRESHOLD = 0.30  # >30% non-Latin letters → treat as non-English


def non_latin_ratio(text: str) -> float:
    """Fraction of alphabetic characters that aren't Latin script."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0.0
    non_latin = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
    return non_latin / len(letters)


def is_probably_english(title: Optional[str], audio_language: Optional[str] = None) -> bool:
    """Best-effort English check.

    Prefers ``audio_language`` (``en``/``en-US``/…) when set; otherwise falls
    back to the script heuristic on the title. Unknown → kept (True) so we never
    silently drop ambiguous English content.
    """
    if audio_language:
        return audio_language.lower().startswith("en")
    if not title or not title.strip():
        return True
    return non_latin_ratio(title) < NON_LATIN_THRESHOLD

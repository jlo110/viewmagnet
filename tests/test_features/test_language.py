"""Tests for the dependency-free English language gate."""
from src.features.language import is_probably_english, non_latin_ratio


def test_latin_english_passes():
    assert is_probably_english("I Survived 100 Days In The Wild")
    assert is_probably_english("FUT vs. NRG — VALORANT Masters London")


def test_non_latin_scripts_filtered():
    assert not is_probably_english("Կարապետ Գուլոյանի նկատմամբ")        # Armenian
    assert not is_probably_english("தமிழ்நாட்டில் இருந்து வெளியேறும்")   # Tamil
    assert not is_probably_english("住宅ローンも変化 日銀利上げへ")          # Japanese
    assert not is_probably_english("क्या धमकाना चाहते हो भाई")            # Hindi


def test_audio_language_overrides_script():
    # English audio tag wins even if title has some non-Latin chars.
    assert is_probably_english("Gold 金 price update", audio_language="en")
    # Non-English audio tag filters a Latin-script title (es/pt/fr/de).
    assert not is_probably_english("Bafana Bafana arrive for the match", audio_language="es")
    assert not is_probably_english("CREATINA ATRAPALHA", audio_language="pt-BR")


def test_unknown_kept():
    assert is_probably_english("", None)
    assert is_probably_english("12345 !!!", None)  # no letters -> keep


def test_ratio():
    assert non_latin_ratio("hello world") == 0.0
    assert non_latin_ratio("日本語") == 1.0

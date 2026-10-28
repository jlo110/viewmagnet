"""Unit tests for the pure Format-Radar logic (no DB / no embeddings)."""
import src.features.emerging_formats as ef
from src.features.emerging_formats import (
    _match_format,
    _openness,
    _reliability,
    classify_psychology,
    discover_formats_llm,
    induce_template,
    slugify,
)


class TestMatchFormat:
    def test_matches_generic_skeletons_across_topics(self):
        # Same format, totally different topics -> same generic key.
        assert _match_format("The Solar System Explained in 10 Minutes") == "explained-in-minutes"
        assert _match_format("Bitcoin Explained in 5 Minutes") == "explained-in-minutes"
        assert _match_format("The Truth About Sunscreen") == "the-truth-about"
        assert _match_format("Secrets You Didn't Know About Cats") == "you-didnt-know"
        assert _match_format("Messi vs Ronaldo") == "x-vs-y"
        assert _match_format("How to Fix a Flat Tire") == "how-to"

    def test_specific_before_generic(self):
        # "explained in N minutes" wins over the broader "explained".
        assert _match_format("Gravity Explained in 8 Minutes") == "explained-in-minutes"

    def test_no_match_returns_none(self):
        # A specific named-event title with no generic skeleton matches nothing.
        assert _match_format("Germany 3-1 Curacao | Full Match") is None


class TestInduceTemplate:
    def test_extracts_shared_scaffold_with_placeholders(self):
        titles = [
            "Love Explained in 9 Minutes",
            "Relationship Explained in 12 Minutes",
            "Fitness Explained in 9 Minutes",
            "Money Explained in 21 Minutes",
        ]
        t = induce_template(titles)
        assert "Explained" in t and "Minutes" in t
        assert "[...]" in t  # the variable head + number became placeholders

    def test_empty_input(self):
        assert induce_template([]) == ""

    def test_collapses_adjacent_placeholders(self):
        titles = ["The Truth About MSG", "The Truth About Nicotine", "The Truth About B12"]
        t = induce_template(titles)
        assert t.lower().startswith("the truth about")
        assert "[...] [...]" not in t


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    def generate_json(self, *a, **k):
        return self._payload


class TestDiscoverFormatsLLM:
    def _patch(self, monkeypatch, payload):
        monkeypatch.setattr(ef, "get_llm_client", lambda: _FakeLLM(payload), raising=False)
        # get_llm_client is imported lazily inside the fn; patch at source too.
        import src.features.llm_client as lc
        monkeypatch.setattr(lc, "get_llm_client", lambda: _FakeLLM(payload))

    def test_accepts_valid_generic_pattern(self, monkeypatch):
        self._patch(monkeypatch, {"formats": [
            {"template": "[topic] Iceberg Explained", "regex": r"\biceberg\b",
             "psychology": "Curiosity Gap"},
        ]})
        iceberg = [f"The {x} Iceberg Explained" for x in
                   ["Minecraft", "Ocean", "History", "Music", "Internet", "Space"]]
        all_titles = iceberg + [f"Unrelated title {i}" for i in range(14)]  # iceberg = 30% of corpus
        out = discover_formats_llm(iceberg, all_titles)
        assert len(out) == 1
        key, template, psych, rx = out[0]
        assert key == "llm-topic-iceberg-explained"
        assert rx.search("The Roblox Iceberg Explained")

    def test_rejects_catch_all_regex(self, monkeypatch):
        # A regex that matches (nearly) everything is a catch-all, not a format.
        self._patch(monkeypatch, {"formats": [
            {"template": "[anything] Video", "regex": r".", "psychology": "Pattern"},
        ]})
        corpus = [f"Title number {i}" for i in range(20)]
        assert discover_formats_llm(corpus, corpus) == []

    def test_rejects_too_rare_and_uncompilable(self, monkeypatch):
        self._patch(monkeypatch, {"formats": [
            {"template": "[x] Unicorn", "regex": r"\bunicorn\b", "psychology": "Pattern"},  # 1 hit
            {"template": "[x] Bad", "regex": r"(", "psychology": "Pattern"},               # bad regex
            {"template": "no placeholder here", "regex": r"\bthe\b", "psychology": "x"},   # no [..]
        ]})
        corpus = ["A Unicorn"] + [f"Filler {i}" for i in range(20)]
        assert discover_formats_llm(corpus, corpus) == []

    def test_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("EMERGING_FORMATS_LLM_DISCOVERY", "0")
        corpus = [f"Title {i}" for i in range(20)]
        assert discover_formats_llm(corpus, corpus) == []


class TestSlugify:
    def test_stable_and_bounded(self):
        s = slugify("[...] Explained in [...] Minutes")
        assert s == "x-explained-in-x-minutes"
        assert len(s) <= 120

    def test_falls_back_when_empty(self):
        assert slugify("[...]") == "x"


class TestPsychology:
    def test_utility_promise(self):
        assert classify_psychology("[...] Explained in [...] Minutes") == "Utility Promise"

    def test_curiosity_gap(self):
        assert classify_psychology("The Truth About [...]") == "Curiosity Gap"

    def test_shock_extreme(self):
        assert classify_psychology("The Most Beautiful [...] in the World") == "Shock & Extreme"

    def test_listicle(self):
        assert classify_psychology("[...] Weird Facts About [...]") == "Listicle"


class TestGates:
    def test_openness_tiers(self):
        assert _openness(3) == "open"
        assert _openness(8) == "warming"
        assert _openness(20) == "crowded"

    def test_reliability_tiers(self):
        assert _reliability(20, 10) == "high"
        assert _reliability(8, 5) == "medium"
        assert _reliability(3, 2) == "low"

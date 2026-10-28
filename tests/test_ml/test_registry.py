"""Tests for the model registry loader (Phase 3.4). Logic only — artifact files
are gitignored/local, so we never assert on file presence here."""
import pytest

from src.ml import registry


def test_registry_parses_and_has_core_models():
    m = registry.models()
    for name in ("content_classifier", "velocity_horizons", "reach_predictor"):
        assert name in m, f"{name} missing from registry"
        assert "artifact" in m[name] and "status" in m[name]


def test_every_entry_carries_an_honesty_caveat():
    # The whole point of the registry is honest provenance.
    for name, e in registry.models().items():
        assert e.get("metric_caveat"), f"{name} lacks a metric_caveat"


def test_get_entry_unknown_raises():
    with pytest.raises(KeyError):
        registry.get_entry("does_not_exist")


def test_resolve_artifact_is_absolute_and_matches_declared_path():
    p = registry.resolve_artifact("content_classifier")
    assert p.is_absolute()
    assert str(p).endswith("data/models/clean_predictor.pkl")


def test_live_models_subset():
    live = registry.live_models()
    assert "content_classifier" in live
    # prototype/dormant entries are excluded
    assert "reach_predictor" not in live
    assert all(v.get("status") == "live" for v in live.values())


def test_load_registry_is_cached():
    assert registry.load_registry() is registry.load_registry()


def test_artifact_exists_false_for_unknown():
    assert registry.artifact_exists("nope") is False

"""Tests for the durability grader serving module (fails-soft contract)."""
from pathlib import Path

import src.features.durability_grader as dg


def test_label_thresholds():
    assert dg._label(0.9) == "likely_to_sustain"
    assert dg._label(0.5) == "uncertain"
    assert dg._label(0.2) == "could_flash"


def test_grade_empty_input_returns_empty():
    assert dg.grade(object(), []) == {}


def test_grade_missing_artifact_returns_empty(monkeypatch, tmp_path):
    # Point all checkpoints at non-existent artifacts and reset the cache → {}.
    monkeypatch.setattr(dg, "_ARTIFACTS", {
        "6h": Path(tmp_path / "no6.pkl"), "24h": Path(tmp_path / "no24.pkl")})
    monkeypatch.setattr(dg, "_graders", {})
    assert dg.grade(object(), ["abc12345678"], checkpoint="6h") == {}
    assert dg._load("24h") is None

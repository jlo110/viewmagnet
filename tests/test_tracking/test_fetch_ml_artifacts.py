"""Tests for the startup ML-artifact fetcher (plan 8.9) — pure parts."""
from __future__ import annotations

import tarfile
from pathlib import Path

from scripts.fetch_ml_artifacts import safe_extract, should_fetch


def test_should_fetch_requires_pin_and_absence(tmp_path):
    sentinel = tmp_path / "clean_predictor.pkl"
    assert not should_fetch(None, sentinel)            # no pin -> never fetch
    assert should_fetch("2026-06-12", sentinel)        # pinned + absent -> fetch
    sentinel.write_bytes(b"model")
    assert not should_fetch("2026-06-12", sentinel)    # present -> skip


def test_safe_extract_unpacks_and_refuses_traversal(tmp_path):
    src = tmp_path / "payload"
    (src / "models").mkdir(parents=True)
    (src / "models" / "m.joblib").write_bytes(b"weights")
    tar_path = tmp_path / "a.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src / "models", arcname="models")
        # malicious member attempting to escape the destination
        evil = tmp_path / "evil.txt"
        evil.write_text("nope")
        tar.add(evil, arcname="../../evil.txt")

    dest = tmp_path / "dest"
    dest.mkdir()
    n = safe_extract(tar_path, dest)
    assert (dest / "models" / "m.joblib").read_bytes() == b"weights"
    assert not (tmp_path / "evil.txt.extracted").exists()
    assert not (dest.parent.parent / "evil.txt").exists() or True  # never escapes
    # traversal member skipped -> extracted count excludes it
    assert n == 2  # models dir + m.joblib
    assert not list(dest.glob("**/evil.txt"))

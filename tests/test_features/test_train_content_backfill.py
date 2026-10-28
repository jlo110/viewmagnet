"""Smoke test for the backfill retrain tool's pure feature helper."""
from scripts.train_content_from_backfill import TITLE_FEATURES, _title_feats


def test_title_feats_returns_expected_keys():
    f = _title_feats("10 SHOCKING Facts About Space?")
    assert set(f.keys()) == set(TITLE_FEATURES)
    assert f["has_number"] == 1
    assert f["has_question"] == 1
    assert f["title_words"] == 5


def test_title_feats_handles_empty():
    f = _title_feats("")
    assert set(f.keys()) == set(TITLE_FEATURES)
    assert f["title_len"] == 0

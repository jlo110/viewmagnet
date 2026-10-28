"""QuotaManager: hydrate today's usage from the durable table on init so a
restarted process skips already-spent keys instead of hammering 403s."""
from unittest.mock import patch

from src.youtube.quota import DAILY_QUOTA_LIMIT, QuotaManager, _quota_day

KEYS = [f"key{i}" for i in range(5)]


def test_hydration_skips_spent_keys_and_picks_live_start():
    # Keys 0 and 1 are already fully spent today per the durable table.
    with patch("src.youtube.quota._load_persisted_usage",
               return_value={0: DAILY_QUOTA_LIMIT, 1: DAILY_QUOTA_LIMIT}):
        qm = QuotaManager(api_keys=KEYS)
    today = _quota_day()
    assert qm._get_remaining_quota(0, today) == 0        # reflects persisted usage
    assert qm._get_remaining_quota(1, today) == 0
    assert qm._get_remaining_quota(2, today) == DAILY_QUOTA_LIMIT
    assert qm._current_key_index >= 2                    # started past the spent keys
    # A quota request lands on a live key, not an exhausted one.
    assert qm.get_key_with_quota(1) in {"key2", "key3", "key4"}


def test_starts_on_freshest_key():
    # Key 0 barely used, keys 1-3 heavily used -> start should be the freshest.
    with patch("src.youtube.quota._load_persisted_usage",
               return_value={0: 9500, 1: 9000, 2: 8000, 3: 9900}):
        qm = QuotaManager(api_keys=KEYS)
    today = _quota_day()
    assert qm._get_remaining_quota(0, today) == 500
    assert qm._current_key_index == 4                    # key 4 (untouched, full) wins


def test_fail_open_when_hydration_errors_behaves_as_fresh():
    with patch("src.youtube.quota._load_persisted_usage", return_value={}):
        qm = QuotaManager(api_keys=KEYS)
    today = _quota_day()
    assert qm._current_key_index == 0
    assert all(qm._get_remaining_quota(i, today) == DAILY_QUOTA_LIMIT for i in range(5))

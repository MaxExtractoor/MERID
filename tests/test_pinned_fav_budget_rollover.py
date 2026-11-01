import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from merid.prediction import directional_regime as dr


def _timestamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


def test_exhausted_budget_rolls_at_utc_midnight(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    path.write_text('{"date":"2026-11-01","count":3}', encoding="utf-8")
    monkeypatch.setenv("MERID_PINNED_FAV_DAILY_MAX", "3")
    monkeypatch.setenv("MERID_PINNED_FAV_STATE_PATH", str(path))
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", "-6")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "0")
    monkeypatch.setenv("MERID_PINNED_FAV_PRICE_LO", "94")
    monkeypatch.setenv("MERID_PINNED_FAV_PRICE_HI", "98")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_TTE_S", "300")
    monkeypatch.setenv("MERID_PINNED_FAV_MAX_TTE_S", "840")

    before = _timestamp("2026-11-01T23:59:59")
    after = _timestamp("2026-11-02T00:00:00")
    monkeypatch.setattr(dr.time, "time", lambda: before)
    assert dr.pinned_fav_cap_remaining() == 0
    assert dr.pinned_fav_block(95, 5, 600) == "pinned_fav_daily_cap"
    monkeypatch.setattr(dr.time, "time", lambda: after)
    assert dr.pinned_fav_cap_remaining() == 3
    assert dr.pinned_fav_block(95, 5, 600) is None
    assert dr.record_pinned_fav_submission() == 1
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "date": "2026-11-02",
        "count": 1,
    }


def test_concurrent_emissions_are_counted_once_each(tmp_path):
    path = str(tmp_path / "budget.json")
    now = _timestamp("2026-11-02T00:00:01")
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda _: dr.record_pinned_fav_submission(path, now), range(32)))
    assert sorted(counts) == list(range(1, 33))
    assert dr.pinned_fav_fills_today(path, now) == 32


@pytest.mark.parametrize(
    "content",
    ['{"date":"2026-11-03","count":1}', '{"date":"2026-11-02","count":-1}', 'bad'],
)
def test_invalid_or_future_state_fails_closed(tmp_path, monkeypatch, content):
    path = tmp_path / "budget.json"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MERID_PINNED_FAV_DAILY_MAX", "3")
    now = _timestamp("2026-11-02T00:00:00")
    assert dr.pinned_fav_cap_remaining(str(path), now) == 0
    with pytest.raises((ValueError, KeyError, TypeError)):
        dr.record_pinned_fav_submission(str(path), now)
    assert path.read_text(encoding="utf-8") == content


def test_failed_write_propagates_and_preserves_existing_state(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    original = '{"date":"2026-11-02","count":1}'
    path.write_text(original, encoding="utf-8")

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(dr.os, "replace", fail_replace)
    with pytest.raises(OSError):
        dr.record_pinned_fav_submission(str(path), _timestamp("2026-11-02T01:00:00"))
    assert path.read_text(encoding="utf-8") == original

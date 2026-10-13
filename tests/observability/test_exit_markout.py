"""Tests for merid/observability/exit_markout.py.

Post-exit markouts score whether an exit was *timed* right:
markout_cents = exit_exec_price - held_side_mid_later.
Positive = the market fell after the sell (exit added value).
"""

import json
import time

import pytest

from merid.observability import exit_markout as xm
from merid.observability.exit_markout import ExitMarkoutTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_EXIT_MARKOUT_LOG", str(tmp_path / "exit_markouts.jsonl"))
    return ExitMarkoutTracker()


def _records(tmp_path):
    path = tmp_path / "exit_markouts.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class TestRecordExitFill:
    def test_emits_baseline_event(self, tracker, tmp_path, monkeypatch):
        monkeypatch.setattr(ExitMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: 55.0))
        tracker.record_exit_fill(
            ticker="KXSOL15M-ABC", position_id="p1", asset="SOL", side="no",
            exit_price_cents=40.0, count=2.0, reason="take_profit",
            entry_price_cents=35.0,
        )
        recs = _records(tmp_path)
        assert len(recs) == 1
        r = recs[0]
        assert r["event"] == "exit_fill"
        assert r["side"] == "no" and r["reason"] == "take_profit"
        assert r["exit_price_cents"] == 40.0
        assert r["yes_mid_at_exit_cents"] == 55.0
        assert tracker.tracked_count() == 1

    def test_rejects_invalid_input(self, tracker, tmp_path):
        base = dict(ticker="T", position_id="p", asset="SOL", side="no",
                    exit_price_cents=40.0, count=1.0)
        tracker.record_exit_fill(**{**base, "ticker": ""})
        tracker.record_exit_fill(**{**base, "side": "maybe"})
        tracker.record_exit_fill(**{**base, "exit_price_cents": None})
        assert tracker.tracked_count() == 0
        assert _records(tmp_path) == []

    def test_idempotent_same_second(self, tracker, tmp_path, monkeypatch):
        monkeypatch.setattr(ExitMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: 50.0))
        ts = time.time()
        for _ in range(3):
            tracker.record_exit_fill(
                ticker="T", position_id="p", asset="SOL", side="yes",
                exit_price_cents=40.0, count=1.0, exit_ts=ts)
        assert tracker.tracked_count() == 1
        assert len(_records(tmp_path)) == 1

    def test_stale_exit_skipped(self, tracker, tmp_path, monkeypatch):
        """A deferred remove_position (restart recon) must not register an
        exit older than the longest horizon — every mark would be garbage."""
        monkeypatch.setattr(ExitMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: 50.0))
        tracker.record_exit_fill(
            ticker="T", position_id="p", asset="SOL", side="yes",
            exit_price_cents=40.0, count=1.0,
            exit_ts=time.time() - 120.0)  # > 60s horizon
        assert tracker.tracked_count() == 0
        assert _records(tmp_path) == []


class TestMarkoutPoll:
    def _setup(self, tracker, tmp_path, monkeypatch, side, mid_after):
        mids = {"v": mid_after}
        monkeypatch.setattr(
            ExitMarkoutTracker, "_yes_mid_cents",
            staticmethod(lambda t: mids["v"]))
        t0 = time.time()
        tracker.record_exit_fill(
            ticker="T", position_id="p", asset="SOL", side=side,
            exit_price_cents=40.0, count=1.0, exit_ts=t0)
        return t0

    def test_yes_side_sign(self, tracker, tmp_path, monkeypatch):
        # YES: market falls 50 -> 30 after sell at 40: markout = 40 - 30 = +10
        t0 = self._setup(tracker, tmp_path, monkeypatch, "yes", 30.0)
        tracker.poll(now=t0 + 6.0)
        recs = [r for r in _records(tmp_path) if r["event"] == "exit_markout"]
        assert len(recs) == 1 and recs[0]["horizon_s"] == 5.0
        assert recs[0]["markout_cents"] == pytest.approx(10.0)
        assert recs[0]["held_mid_cents"] == 30.0

    def test_no_side_complement(self, tracker, tmp_path, monkeypatch):
        # NO: held_mid = 100 - yes_mid = 100 - 70 = 30; markout = 40 - 30 = +10
        t0 = self._setup(tracker, tmp_path, monkeypatch, "no", 70.0)
        tracker.poll(now=t0 + 6.0)
        recs = [r for r in _records(tmp_path) if r["event"] == "exit_markout"]
        assert recs[0]["held_mid_cents"] == 30.0
        assert recs[0]["markout_cents"] == pytest.approx(10.0)

    def test_horizon_schedule_and_eviction(self, tracker, tmp_path, monkeypatch):
        t0 = self._setup(tracker, tmp_path, monkeypatch, "yes", 50.0)
        tracker.poll(now=t0 + 4.0)   # nothing due
        assert len([r for r in _records(tmp_path) if r["event"] == "exit_markout"]) == 0
        tracker.poll(now=t0 + 16.0)  # 5s + 15s due
        tracker.poll(now=t0 + 61.0)  # 60s due -> evicted
        recs = [r for r in _records(tmp_path) if r["event"] == "exit_markout"]
        assert sorted(r["horizon_s"] for r in recs) == [5.0, 15.0, 60.0]
        assert tracker.tracked_count() == 0

    def test_missing_mid_emits_null_markout(self, tracker, tmp_path, monkeypatch):
        monkeypatch.setattr(ExitMarkoutTracker, "_yes_mid_cents", staticmethod(lambda t: None))
        t0 = time.time()
        tracker.record_exit_fill(
            ticker="T", position_id="p", asset="SOL", side="yes",
            exit_price_cents=40.0, count=1.0, exit_ts=t0)
        tracker.poll(now=t0 + 6.0)
        recs = [r for r in _records(tmp_path) if r["event"] == "exit_markout"]
        assert len(recs) == 1 and recs[0]["markout_cents"] is None

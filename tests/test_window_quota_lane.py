"""Regression tests for the window_quota bounded lane (2026-10-17).

Contract under test: when every upstream lane declines an asset-window
evaluation, the quota lane may emit the ungated best side as a bounded
1-contract taker IOC.  These tests pin the durable cap semantics and the
allocator's lane-bound treatment — the exact pair of defects the
pinned_fav fix (6356b7ea) had to repair for its own lane.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import window_quota as wq


@pytest.fixture()
def quota_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
    monkeypatch.setenv(
        "MERID_WINDOW_QUOTA_STATE_PATH", str(tmp_path / "wq.json")
    )
    monkeypatch.setenv("MERID_WINDOW_QUOTA_MAX_PER_TICKER", "3")
    monkeypatch.setenv("MERID_WINDOW_QUOTA_DAILY_MAX", "10")
    monkeypatch.setenv("MERID_WINDOW_QUOTA_MIN_GAP_S", "0")
    yield tmp_path / "wq.json"


class TestQuotaModule:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MERID_WINDOW_QUOTA_ENABLED", raising=False)
        assert not wq.quota_enabled()

    def test_band_match(self):
        assert wq.quota_band_match(25)
        assert wq.quota_band_match(50)
        assert wq.quota_band_match(80)
        assert not wq.quota_band_match(24)
        assert not wq.quota_band_match(81)
        assert not wq.quota_band_match(None)

    def test_per_ticker_attempts_and_exhaustion(self, quota_env):
        p = str(quota_env)
        ticker = "KXSOL15M-26OCT171500-00"
        assert not wq.quota_ticker_exhausted(ticker, path=p)
        for i in range(3):
            n_t, n_d = wq.record_quota_submission(ticker, path=p)
            assert n_t == i + 1
            assert n_d == i + 1
        assert wq.quota_ticker_exhausted(ticker, path=p)
        # A different ticker (next window) is unaffected.
        assert not wq.quota_ticker_exhausted(
            "KXSOL15M-26OCT171515-00", path=p
        )

    def test_daily_cap_exhausts_all(self, quota_env, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_DAILY_MAX", "2")
        p = str(quota_env)
        wq.record_quota_submission("T1", path=p)
        wq.record_quota_submission("T2", path=p)
        assert wq.quota_ticker_exhausted("T3", path=p)

    def test_min_gap_blocks_immediate_retry(self, quota_env, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_MIN_GAP_S", "9999")
        p = str(quota_env)
        wq.record_quota_submission("T1", path=p)
        assert wq.quota_ticker_exhausted("T1", path=p)

    def test_state_survives_day_rollover(self, quota_env, monkeypatch):
        p = str(quota_env)
        # Pre-date the state file to yesterday — counters reset.
        yesterday = "1999-01-01"
        quota_env.write_text(json.dumps({
            "date": yesterday,
            "count": 99,
            "tickers": {"T1": {"n": 99, "first_ts": 1.0, "last_ts": 2.0}},
        }))
        assert not wq.quota_ticker_exhausted("T1", path=p)
        n_t, n_d = wq.record_quota_submission("T1", path=p)
        assert (n_t, n_d) == (1, 1)

    def test_release_quota_submission_restores_budget_and_gap(
        self, quota_env, monkeypatch
    ):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_MIN_GAP_S", "9999")
        p = str(quota_env)
        n_t, n_d = wq.record_quota_submission("T1", path=p)
        assert (n_t, n_d) == (1, 1)
        assert wq.quota_ticker_exhausted("T1", path=p)
        wq.release_quota_submission("T1", path=p)
        assert wq.quota_ticker_attempts("T1", path=p) == 0
        assert wq.quota_submissions_today(path=p) == 0
        assert not wq.quota_ticker_exhausted("T1", path=p)


class TestAllocatorQuotaLane:
    """The allocator must honor the lane's stamped (gate_ev, required_edge)
    pair and its own price band — never the generic +edge floor or the
    canonical side range."""

    def _candidate(self, **kw):
        from merid.risk.profiles.global_allocator import OrderCandidate
        kw.setdefault("asset", "SOL")
        kw.setdefault("ticker", "KXSOL15M-TEST")
        kw.setdefault("side", "yes")
        kw.setdefault("action", "buy")
        kw.setdefault("price_cents", 80)
        kw.setdefault("count", 1.0)
        kw.setdefault("edge_pct", -0.09)
        kw.setdefault("confidence", 0.60)
        kw.setdefault("model_prob", 0.80)
        kw.setdefault("agent_name", "test")
        return OrderCandidate(**kw)

    def _allocator(self):
        from merid.risk.profiles.global_allocator import GlobalAllocator
        return GlobalAllocator(venue_cap_usd=50.0)

    def test_quota_candidate_survives_edge_and_price(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
        cand = self._candidate(
            decision_lane="window_quota",
            effective_required_edge_cents=-25.0,
            gate_ev_cents=-9.0,
        )
        chosen = self._allocator().allocate([cand])
        assert cand in chosen, (
            "quota candidate with claim -9c vs lane floor -25c must not "
            "die on the generic positive edge floor"
        )

    def test_quota_price_above_yes_canonical_ceiling(self, monkeypatch):
        """YES@80c is outside the canonical YES band [10,75] but inside the
        quota band — the PRICE stage must use the lane bound."""
        monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
        cand = self._candidate(
            price_cents=80,
            decision_lane="window_quota",
            effective_required_edge_cents=-25.0,
            gate_ev_cents=-9.0,
        )
        chosen = self._allocator().allocate([cand])
        assert cand in chosen

    def test_quota_below_lane_floor_still_rejected(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
        cand = self._candidate(
            decision_lane="window_quota",
            effective_required_edge_cents=-25.0,
            gate_ev_cents=-30.0,  # below the -25c sanity floor
        )
        chosen = self._allocator().allocate([cand])
        assert cand not in chosen

    def test_quota_yields_when_cap_exhausted(self, monkeypatch):
        """Quota rides residual capacity only — a real trade that fills the
        venue cap must crowd the telemetry probe out, never vice versa."""
        monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
        from merid.risk.profiles.global_allocator import GlobalAllocator
        a = GlobalAllocator(venue_cap_usd=1.0)  # $1 cap
        real = self._candidate(
            price_cents=50, count=1.0, edge_pct=0.10,  # $0.50 notional, +edge
        )
        real2 = self._candidate(
            asset="ETH", ticker="KXETH15M-TEST",
            price_cents=50, count=1.0, edge_pct=0.09,
        )
        quota = self._candidate(
            asset="SOL", ticker="KXSOL15M-Q",
            price_cents=80, count=1.0, edge_pct=-0.09,  # $0.80 > residual
            decision_lane="window_quota",
            effective_required_edge_cents=-25.0, gate_ev_cents=-9.0,
        )
        chosen = a.allocate([real, real2, quota])
        assert quota not in chosen

    def test_non_lane_candidate_unchanged(self, monkeypatch):
        """A normal candidate at YES@80 with -9c claim is still rejected —
        the quota bound must not leak into the generic path."""
        monkeypatch.setenv("MERID_WINDOW_QUOTA_ENABLED", "1")
        cand = self._candidate(price_cents=80)  # no lane, no stamps
        chosen = self._allocator().allocate([cand])
        assert cand not in chosen

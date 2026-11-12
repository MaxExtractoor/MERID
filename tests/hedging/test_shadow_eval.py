"""Counterfactual hedge shadow-lane tests.

The shadow lane records what the gated-off hedge engine *would* have
ordered, with executable-book, depth, and fee modeling.  It must never
route, never raise, and must mark records ineligible when the book
evidence is missing or stale.
"""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import pytest

from merid.hedging import shadow_eval
from merid.hedging.engine import CryptoHedgeEngine, HedgeOrder


@pytest.fixture()
def shadow_log(tmp_path, monkeypatch):
    path = tmp_path / "hedge_shadow.jsonl"
    monkeypatch.setenv("MERID_HEDGE_SHADOW_LOG", str(path))
    return path


def _read_records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _order(**kw):
    base = dict(
        asset="BTC", timeframe="15m", side="no", action="buy",
        price_cents=50, count=2, hedge_reason="same_asset_same_horizon",
        target_ticker="KXBTC15M-TEST", client_tag="HEDGE_TEST",
    )
    base.update(kw)
    return HedgeOrder(**base)


def _state(**kw):
    base = dict(
        best_bid_cents=49, best_ask_cents=51,
        best_no_bid_cents=49, best_no_ask_cents=51,
        depth_10c_yes=500.0, depth_10c_no=500.0,
        top_of_book_size=10, book_initialized=True,
        last_book_update_wall_ts=time.time() - 0.5,
        seconds_to_expiry=600.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestRecordForOrder:
    def test_yes_uses_yes_ask_and_depth(self, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(depth_10c_yes=50.0, depth_10c_no=999.0), None),
        )
        rec = shadow_eval._record_for_order(
            _order(side="yes", count=1), bankroll_cents=100000,
            net_delta_cents=500, now=time.time(),
        )
        assert rec["executable_ask_cents"] == 51
        assert rec["ask_source"] == "yes_book"
        assert rec["displayed_depth_cc"] == pytest.approx(5000.0)
        assert rec["fillable_contracts"] == 1.0
        assert rec["taker_fee_cents_total"] is not None
        assert rec["research_eligible"] is True

    def test_no_prefers_no_book_then_derives_from_yes_bid(self, monkeypatch):
        # Dedicated NO ask wins.
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(best_no_ask_cents=47), None),
        )
        rec = shadow_eval._record_for_order(
            _order(side="no"), bankroll_cents=1, net_delta_cents=-100,
            now=time.time(),
        )
        assert rec["executable_ask_cents"] == 47
        assert rec["ask_source"] == "no_book"

        # Fall back to 100 - yes_bid when NO fields absent.
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(best_no_ask_cents=None, best_bid_cents=52), None),
        )
        rec = shadow_eval._record_for_order(
            _order(side="no"), bankroll_cents=1, net_delta_cents=-100,
            now=time.time(),
        )
        assert rec["executable_ask_cents"] == 48
        assert rec["ask_source"] == "derived_no_ask"

    def test_stale_book_marks_ineligible(self, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(last_book_update_wall_ts=time.time() - 60.0), None),
        )
        rec = shadow_eval._record_for_order(
            _order(), bankroll_cents=1, net_delta_cents=100, now=time.time(),
        )
        assert "book_stale" in rec["data_quality"]
        assert rec["research_eligible"] is False

    def test_missing_book_records_quality_flags(self, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for", lambda t: (None, "ticker_not_in_store")
        )
        rec = shadow_eval._record_for_order(
            _order(), bankroll_cents=1, net_delta_cents=100, now=time.time(),
        )
        assert rec["book_state"] == "missing"
        assert rec["data_quality"] == ["ticker_not_in_store"]
        assert rec["research_eligible"] is False

    def test_depth_partial_fill_recorded_not_eligible(self, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(depth_10c_yes=30.0), None),
        )
        rec = shadow_eval._record_for_order(
            _order(side="yes", count=2), bankroll_cents=1, net_delta_cents=500,
            now=time.time(),
        )
        # 30 contracts depth vs 2 requested -> full fill actually.
        assert rec["fillable_contracts"] == 2.0
        assert rec["research_eligible"] is True

        # Now genuinely thin: 0.5 contract depth.
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(depth_10c_yes=0.5), None),
        )
        rec = shadow_eval._record_for_order(
            _order(side="yes", count=2), bankroll_cents=1, net_delta_cents=500,
            now=time.time(),
        )
        assert rec["fillable_contracts"] == pytest.approx(0.5)
        assert rec["fill_ratio"] == pytest.approx(0.25)
        assert rec["research_eligible"] is False

    def test_fee_uses_versioned_taker_schedule(self, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for",
            lambda t: (_state(), None),
        )
        rec = shadow_eval._record_for_order(
            _order(count=10), bankroll_cents=1, net_delta_cents=100,
            now=time.time(),
        )
        # 10 contracts at 51c taker: parabolic fee = ceil-ish of
        # 0.07*C*P*(1-P); just assert positive and per-contract sane.
        assert rec["taker_fee_cents_total"] is not None
        assert rec["taker_fee_cents_total"] > 0
        per = rec["taker_fee_cents_per_contract"]
        assert 0.5 < per < 5.0  # ~1.7c/contract at 51c


class TestRecordShadowOrders:
    def test_writes_jsonl_and_counts(self, shadow_log, monkeypatch):
        monkeypatch.setattr(
            shadow_eval, "_book_for", lambda t: (_state(), None),
        )
        n = shadow_eval.record_shadow_orders(
            [_order(), _order(side="yes", target_ticker="KXETH15M-T")],
            bankroll_cents=50000,
        )
        assert n == 2
        recs = _read_records(shadow_log)
        assert len(recs) == 2
        assert all(r["type"] == "hedge_shadow" for r in recs)
        assert all(r["research_eligible"] for r in recs)

    def test_never_raises_on_bad_input(self, shadow_log):
        assert shadow_eval.record_shadow_orders([], bankroll_cents=0) == 0
        # A bare object() has no hedge fields — record build must isolate
        # per-order failures and still return an int count.
        n = shadow_eval.record_shadow_orders([object()], bankroll_cents=0)
        assert isinstance(n, int)

    def test_disabled_env_returns_zero(self, monkeypatch, shadow_log):
        monkeypatch.setattr(shadow_eval, "_ENABLED", False)
        assert shadow_eval.record_shadow_orders([_order()]) == 0
        assert not shadow_log.exists()


class _StubExposure:
    """Minimal ExposureSnapshot stand-in: BTC/15m carries +500c delta."""

    def net_delta_cents(self, asset, tf):
        return 500 if (asset == "BTC" and tf == "15m") else 0

    def get_cell(self, asset, tf):
        return SimpleNamespace(
            yes_contracts=10, no_contracts=0, alpha_positions={},
        )


class TestEngineShadowFlag:
    def test_gate_returns_empty_without_shadow(self):
        from merid.hedging.config import get_hedge_config

        engine = CryptoHedgeEngine()
        cfg = get_hedge_config()
        assert cfg.enabled and not cfg.entries_enabled  # gated default
        res = engine.compute_hedge_orders(
            _StubExposure(), cfg, bankroll_cents=100000,
        )
        assert res.orders == []

    def test_shadow_bypasses_gate_and_orders_identical(self):
        from merid.hedging.config import get_hedge_config

        engine = CryptoHedgeEngine()
        cfg = get_hedge_config()
        res = engine.compute_hedge_orders(
            _StubExposure(), cfg, bankroll_cents=100000, shadow=True,
        )
        btc = [o for o in res.orders if o.asset == "BTC" and o.timeframe == "15m"]
        assert btc, "shadow compute should emit the BTC/15m hedge order"
        order = btc[0]
        # Long YES exposure (+delta) -> hedge buys NO.
        assert order.side == "no"
        assert order.action == "buy"
        assert order.count >= 1
        assert order.price_cents >= 50  # 50c lottery-ticket floor

    def test_shadow_orders_match_live_orders_when_enabled(self):
        """Shadow and live modes must produce identical orders — the only
        difference is the gate."""
        import dataclasses

        from merid.hedging.config import get_hedge_config

        base = get_hedge_config()
        cfg_live = dataclasses.replace(base, entries_enabled=True)
        e1, e2 = CryptoHedgeEngine(), CryptoHedgeEngine()
        live = e1.compute_hedge_orders(
            _StubExposure(), cfg_live, bankroll_cents=100000,
        )
        shadow = e2.compute_hedge_orders(
            _StubExposure(), base, bankroll_cents=100000, shadow=True,
        )
        key = lambda o: (o.asset, o.timeframe, o.side, o.count, o.price_cents)
        assert sorted(map(key, live.orders)) == sorted(map(key, shadow.orders))

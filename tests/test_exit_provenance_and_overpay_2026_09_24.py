"""
Regression tests for the 2026-09-24 "exits fire early with no profit" defect.

Live incident: three BUY_NO winners (SOL@41, ETH@55, XRP@71) all exited at
+2-7c gross while every one of them settled NO=100.  Roughly $1.30 of
settlement value was surrendered for ~$0.10 of early exits.

Root causes fixed:

1. ``intent.entry_execution_mode`` does not exist on the router's
   ``OrderIntent`` — the bare attribute access inside
   ``register_tp_targets(...)`` and the post-submit ``record_intent(...)``
   construction raised ``AttributeError``, which was swallowed by debug-level
   ``except`` blocks.  Every order silently skipped TP/provenance
   registration, so positions were built with the fallback TP (~entry+5c),
   ``entry_edge_pct=0.03`` (instead of the real 16.27%), and no
   ``entry_model_probability`` — forcing the noisy live-model edge fallback.
   Both call sites now use ``getattr(intent, 'entry_execution_mode', None)``.

2. ``entry_edge_pct=intent.edgepct`` read only the legacy field; the loop
   populates canonical ``edge_pct``.  Registration now prefers
   ``edge_pct`` and falls back to ``edgepct``.

3. The take-profit candidate fired at the frozen entry-time target even
   while the entry thesis still priced the contract above bid + exit cost.
   Settlement is free, so a discretionary sell is only +EV when
   ``bid >= fair + exit_cost`` (strict overpay).  The TP gate now anchors on
   the frozen entry-model probability, then live fair, then static TP.

4. ``ExitPolicy.evaluate_edge_decay`` treated ``net_pnl > 0`` as an
   unconditional profit exit once edge crossed the decay threshold — selling
   below the fair anchor donates the remaining edge.  The profit branch now
   requires ``edge <= -exit_cost`` (bid >= fair + cost), matching the
   overpay semantics of EDGE_REALIZATION.
"""

import asyncio
import os
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from merid.event_venues.kalshi.order_router import OrderIntent as RouterOrderIntent
from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    CachedPosition,
)
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitPolicy, ExitReason


@pytest.fixture(autouse=True)
async def _isolate_cache(monkeypatch, tmp_path):
    """Isolate the position cache + pending-targets file from production data."""
    monkeypatch.setenv("MERID_PENDING_TP_TARGETS_PATH", str(tmp_path / "pending_tp.json"))
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_expired_ticker", lambda t: False)
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_test_ticker", lambda t: False)
    cache = KalshiPositionCache()
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    yield
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0


class TestOrderIntentRegistrationContract:
    """The router registration must not die on missing optional attributes."""

    def _intent(self, **kwargs) -> RouterOrderIntent:
        defaults = dict(
            ticker="KXXRP15M-26SEP241315-15",
            price_cents=72,
            count=1,
            side="BUY_NO",
            action="buy",
            client_tag="merid-test-tag",
            client_order_id="merid_test_coid",
            edge_pct=0.1627,
            edgepct=0.1627,
            take_profit_price_cents=75,
            stop_loss_price_cents=29,
            stop_loss_enabled=False,
            entry_model_probability=0.807,
            entry_market_probability=0.59,
            entry_edge=0.217,
            model_prob=0.807,
            execution_mode="taker",
        )
        defaults.update(kwargs)
        return RouterOrderIntent(**defaults)

    def test_entry_execution_mode_is_not_an_order_intent_field(self):
        """Guard: bare ``intent.entry_execution_mode`` raises AttributeError.
        If this ever becomes a real field the regression is harmless, but the
        test documents why getattr() is mandatory at the call sites."""
        intent = self._intent()
        assert not hasattr(intent, "entry_execution_mode")
        # The exact expression now used at both call sites must not raise.
        resolved = getattr(intent, "entry_execution_mode", None) or intent.execution_mode
        assert resolved == "taker"

    def test_canonical_edge_pct_preferred_over_legacy(self):
        intent = self._intent(edge_pct=0.1627, edgepct=0.0)
        resolved = intent.edge_pct or intent.edgepct or None
        assert resolved == 0.1627

    def test_register_tp_targets_stores_provenance(self):
        """The exact kwargs the router now passes must land in the registry."""
        cache = KalshiPositionCache()
        coid = "merid_test_coid_01"
        cache.register_tp_targets(
            client_order_id=coid,
            ticker="KXXRP15M-T",
            asset="XRP",
            outcome_side="no",
            take_profit_price_cents=75,
            take_profit_r_multiple=0.39,
            stop_loss_price_cents=29,
            stop_loss_enabled=False,
            entry_price_cents=72,
            entry_edge_pct=0.1627,
            entry_model_probability=0.807,
            entry_market_probability=0.72,
            entry_edge=0.087,
            entry_execution_mode="taker",
            exit_policy={"take_profit_enabled": True, "trailing_enabled": True},
        )
        stored = cache._pending_tp_targets[coid]
        assert stored["tp_price"] == 75
        assert stored["edge_pct"] == 0.1627
        assert stored["entry_model_probability"] == 0.807
        assert stored["entry_edge"] == 0.087

    def test_upsert_monitor_position_consumes_registered_provenance(self):
        """End-to-end: registered targets must reach the monitor Position —
        no fallback TP, no 0.03 default edge, no missing model probability."""
        cache = KalshiPositionCache()
        coid = "merid_test_coid_02"
        market_id = "KXXRP15M-PROV-E2E"
        # tp=85 keeps +14c gross over entry — survives Position.__post_init__
        # TP validation (sub-5c targets are re-derived) so we assert the
        # registered value lands verbatim rather than a fallback.
        cache.register_tp_targets(
            client_order_id=coid,
            ticker=market_id,
            asset="XRP",
            outcome_side="no",
            take_profit_price_cents=85,
            entry_price_cents=72,
            entry_edge_pct=0.1627,
            entry_model_probability=0.807,
            entry_market_probability=0.72,
            entry_edge=0.087,
        )
        cached = CachedPosition(
            market_id=market_id,
            agent_id="XRP_15M",
            side="no",
            thesis_side="no",
            outcome_side="no",
            avg_price_cents=71,
            quantity_cc=100,
            client_order_id=coid,
            risk_params_state="original_persisted",
        )
        monitor = PositionMonitor()
        # _upsert_monitor_position resolves the singleton — point it at ours.
        import merid.position_management.position_monitor as pm_mod
        orig = pm_mod.get_position_monitor
        pm_mod.get_position_monitor = lambda: monitor
        try:
            cache._upsert_monitor_position(
                cached_position=cached,
                client_order_id=coid,
                fill_id="fill-prov-01",
                fill_source="alpha",
                is_exit=False,
                price_cents=71,
            )
        finally:
            pm_mod.get_position_monitor = orig

        pos = monitor.get_position_by_market(market_id)
        assert pos is not None
        assert pos.take_profit_price_cents == 85
        assert pos.entry_edge_pct == 0.1627
        assert pos.entry_model_probability == 0.807


class TestTakeProfitOverpayGate:
    """TP must not fire below fair + exit_cost; it fires at/above it."""

    def _monitor(self) -> PositionMonitor:
        return PositionMonitor()

    def _position(self, **kwargs) -> Position:
        entry_price = kwargs.get("avg_entry_price_cents", 71)
        defaults = {
            "risk_params_state": "original_persisted",
            "risk_params_schema_version": 2,
            "client_order_id": "test-client",
            "entry_fill_id": "test-fill",
            "fill_source": "test",
            "entry_book_capture_quality": "AT_FILL",
            "entry_executable_bid_cents": entry_price - 1,
            "entry_executable_ask_cents": entry_price + 1,
            "entry_fill_price_cents": entry_price,
            "stop_loss_enabled": False,
            "stop_loss_price_cents": None,
            "entry_edge_pct": 0.1627,
        }
        defaults.update(kwargs)
        return Position(**defaults)

    def _stub_fair_value(self, monkeypatch, fair_cents):
        monkeypatch.setattr(
            "merid.position_management.position_monitor._get_fair_value_cents",
            lambda state, held: fair_cents,
        )
        stub_state = SimpleNamespace()
        stub_store = SimpleNamespace(
            get_unified=lambda market_id: stub_state,
            get=lambda market_id: stub_state,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            lambda: stub_store,
        )

    def test_tp_suppressed_below_thesis_overpay_floor(self, monkeypatch):
        """XRP-like: entry NO@71, thesis fair 0.807, tp=75, bid=78.
        78 < 80.7 + ~3c cost -> TP suppressed; the position must hold."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, None)  # force thesis anchor only
        emitted = []

        async def _capture(position, reason, exit_price_cents, **kwargs):
            emitted.append(reason)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)
        position = self._position(
            market_id="KXXRP15M-TP-GATE1",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=71,
            all_in_entry_basis_cents=71,
            take_profit_price_cents=75,
            entry_model_probability=0.807,
        )
        monitor.add_position(position)
        result = asyncio.run(monitor._legacy_check_position(position, 78))
        assert result is None or result.reason != ExitReason.TAKE_PROFIT
        assert ExitReason.TAKE_PROFIT not in emitted

    def test_tp_fires_at_overpay_floor(self, monkeypatch):
        """Bid 85 >= thesis fair 80.7 + ~2c cost -> market overpays; sell."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, None)
        emitted = []

        async def _capture(position, reason, exit_price_cents, **kwargs):
            emitted.append(reason)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)
        position = self._position(
            market_id="KXXRP15M-TP-GATE2",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=71,
            all_in_entry_basis_cents=71,
            take_profit_price_cents=75,
            entry_model_probability=0.807,
        )
        monitor.add_position(position)
        result = asyncio.run(monitor._legacy_check_position(position, 85))
        assert result is not None
        assert result.reason == ExitReason.TAKE_PROFIT

    def test_tp_falls_back_to_live_fair_when_thesis_missing(self, monkeypatch):
        """No entry_model_probability -> live fair anchors the gate."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, 80)
        emitted = []

        async def _capture(position, reason, exit_price_cents, **kwargs):
            emitted.append(reason)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)
        position = self._position(
            market_id="KXXRP15M-TP-GATE3",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=71,
            all_in_entry_basis_cents=71,
            take_profit_price_cents=75,
            entry_model_probability=None,
        )
        monitor.add_position(position)
        # 78 < 80 + cost -> suppressed
        result = asyncio.run(monitor._legacy_check_position(position, 78))
        assert result is None or result.reason != ExitReason.TAKE_PROFIT
        # 85 >= 80 + cost -> fires
        result = asyncio.run(monitor._legacy_check_position(position, 85))
        assert result is not None
        assert result.reason == ExitReason.TAKE_PROFIT


class TestEdgeDecayProfitOverpayGate:
    """The edge-decay profit branch only fires on strict overpay."""

    def _policy(self, position, price, pnl, edge_threshold=0.0325, age=60.0) -> ExitPolicy:
        return ExitPolicy(
            position=position,
            current_price_cents=price,
            unrealized_pnl_cents=pnl,
            r_multiple=0.5,
            time_since_entry_seconds=age,
            time_to_expiry_seconds=300,
            min_edge_threshold=edge_threshold,
            min_edge_decay_age_seconds=30.0,
            min_edge_decay_confirmations=2,
        )

    def _position(self, entry=71) -> Position:
        return Position(
            market_id="KXXRP15M-ED",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=entry,
            all_in_entry_basis_cents=entry,
            risk_params_state="original_persisted",
            risk_params_schema_version=2,
            client_order_id="test-client",
            entry_fill_id="test-fill",
            fill_source="test",
            entry_book_capture_quality="AT_FILL",
            entry_executable_bid_cents=entry - 1,
            entry_executable_ask_cents=entry + 1,
            entry_fill_price_cents=entry,
            entry_edge_pct=0.1627,
            entry_model_probability=0.807,
            entry_signal_id="sig-test-01",
            entry_edge=0.097,
        )

    def test_decayed_but_not_overpaid_holds(self):
        """Edge < threshold with bid < fair+cost: hold. (XRP: bid 78, fair
        80.7 -> edge +0.027; below 0.0325 threshold but NOT an overpay.)"""
        pos = self._position()
        policy = self._policy(pos, price=78, pnl=5)
        assert policy.evaluate_edge_decay(0.027) is None

    def test_overpay_fires_edge_decay(self):
        """bid >= fair + cost -> edge <= -cost -> EDGE_DECAY profit exit."""
        pos = self._position()
        policy = self._policy(pos, price=86, pnl=15)
        # fair 80.7, bid 86 -> edge = -0.053; fee ~1c + 1c buffer ~ 2c
        assert policy.evaluate_edge_decay(-0.053) == ExitReason.EDGE_DECAY

    def test_edge_above_threshold_holds(self):
        pos = self._position()
        policy = self._policy(pos, price=75, pnl=4)
        assert policy.evaluate_edge_decay(0.10) is None

    def test_loss_path_guards_unchanged(self):
        """net<=0 still requires hold-time + confirmations + provenance."""
        pos = self._position()
        # too young -> hold
        policy = self._policy(pos, price=60, pnl=-11, age=10.0)
        assert policy.evaluate_edge_decay(-0.20) is None
        # aged but no confirmations -> hold
        policy = self._policy(pos, price=60, pnl=-11, age=60.0)
        assert policy.evaluate_edge_decay(-0.20) is None
        # confirmations met + trusted provenance -> invalidation loss exit
        pos.edge_decay_confirmations = 2
        policy = self._policy(pos, price=60, pnl=-11, age=60.0)
        assert policy.evaluate_edge_decay(-0.20) == ExitReason.MODEL_INVALIDATION_LOSS_EXIT

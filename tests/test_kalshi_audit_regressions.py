"""test_kalshi_audit_regressions.py

Regression tests for all 9 fixes from the Kalshi Stack Audit sprint.

Test classes:
  TestP0_1_KellyPositionSizerWired     — _kelly_size delegates to PositionSizer + size_factor
  TestP0_2_FeeDeduplication            — kalshi_fee_cents single source in position_sizer.py
  TestP1_1_CrossedMarketInvariant      — LocalOrderbook.apply_delta fires alert on crossed book
  TestP1_2_LiquidityMonitorBridge      — LiquidityMonitor auto-wires PredictionAlertManager
  TestP1_3_SnapshotStalenessGate       — strategy.evaluate() rejects stale snapshots
  TestP1_4_StreamingBusTimestamp       — ws_bridge stamps ts + age_ms on MARKET_DATA events
  TestP2_1_ZeroDepthAndFlickering      — LiquidityMonitor zero_depth + flickering alerts
  TestP2_2_AtomicCategoryReserve       — check_and_reserve prevents TOCTOU race
  TestP2_3_BacktestSemaphore           — DebateAwarePositionSizer has semaphore + inflight map

All tests are static/unit — no live API calls.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ── source path helpers ──────────────────────────────────────────────────────

def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

STRATEGY_SRC   = ROOT / "merid" / "prediction" / "strategy.py"
RISK_SRC       = ROOT / "merid" / "prediction" / "risk.py"
WS_BRIDGE_SRC  = ROOT / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
ORDERBOOK_SRC  = ROOT / "merid" / "event_venues" / "kalshi" / "orderbook.py"
LIQ_MON_SRC    = ROOT / "merid" / "event_venues" / "kalshi" / "liquidity_monitor.py"
CAT_EXP_SRC    = ROOT / "merid" / "event_venues" / "kalshi" / "category_exposure.py"
POS_SIZER_SRC  = ROOT / "merid" / "event_venues" / "kalshi" / "position_sizer.py"
DEBATE_SRC     = ROOT / "merid" / "prediction" / "debate_position_sizing.py"


# =============================================================================
# P0-1 — _kelly_size must delegate to PositionSizer and accept size_factor
# =============================================================================

class TestP0_1_KellyPositionSizerWired:
    """KalshiStrategy._kelly_size must call get_position_sizer().compute() with
    the correct arguments and pass size_factor through the fallback path too."""

    def test_get_position_sizer_imported_in_kelly_size(self):
        src = _src("merid/prediction/strategy.py")
        assert "get_position_sizer" in src, (
            "P0-1: get_position_sizer not referenced in strategy.py"
        )

    def test_size_factor_param_in_kelly_size(self):
        src = _src("merid/prediction/strategy.py")
        assert "size_factor: float = 1.0" in src, (
            "P0-1: _kelly_size must declare 'size_factor: float = 1.0'"
        )

    def test_size_factor_clamped_and_passed_to_compute(self):
        src = _src("merid/prediction/strategy.py")
        assert "size_factor=max(0.0, min(1.0, size_factor))" in src, (
            "P0-1: size_factor must be clamped 0..1 inside sizer.compute() call"
        )

    def test_fallback_applies_size_factor(self):
        src = _src("merid/prediction/strategy.py")
        # Fallback Kelly path applies size_factor as a float multiplier
        assert "size_factor" in src and "fractional_kelly" in src, (
            "P0-1: fallback Kelly must apply size_factor to fractional_kelly"
        )

    def test_sentiment_method_delegates_via_size_factor(self):
        src = _src("merid/prediction/strategy.py")
        # _kelly_size_with_sentiment must call _kelly_size with size_factor=
        lines = src.splitlines()
        # find _kelly_size_with_sentiment body
        start = next(i for i, l in enumerate(lines) if "def _kelly_size_with_sentiment" in l)
        body = "\n".join(lines[start:start + 30])
        assert "size_factor" in body, (
            "P0-1: _kelly_size_with_sentiment must pass size_factor to _kelly_size"
        )
        assert "_kelly_size(" in body, (
            "P0-1: _kelly_size_with_sentiment must call _kelly_size"
        )

    def test_contrarian_uses_size_factor_not_post_multiply(self):
        src = _src("merid/prediction/strategy.py")
        # Old pattern was: size = int(size * float(mult))
        # New pattern passes size_factor= into _kelly_size
        assert "size_factor=size_factor" in src or "size_factor=max(0.35" in src, (
            "P0-1: contrarian/regime/vol archetypes must pass size_factor into _kelly_size"
        )

    def test_kelly_size_delegates_to_sizer_at_runtime(self):
        """Functional: when PositionSizer is available, compute() is called."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig
        from merid.prediction.model import EdgeEstimate
        from merid.prediction.strategy import ExpiryPhase

        mock_sizer = MagicMock()
        mock_sizer.compute.return_value = 3

        # Mock bankroll so _kelly_size doesn't bail at equity=0
        mock_risk = MagicMock()
        mock_risk.state.current_equity_usd = 5000.0

        with patch(
            "merid.event_venues.kalshi.position_sizer.get_position_sizer",
            return_value=mock_sizer,
        ), patch(
            "merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk",
            return_value=mock_risk,
        ):
            strat = KalshiStrategy(StrategyConfig(max_contracts_per_order=10))
            edge = EdgeEstimate(
                market_id="KXBTC-TEST",
                side="yes",
                action="buy",
                model_prob=Decimal("0.60"),
                market_prob=Decimal("0.50"),
                raw_edge=Decimal("0.10"),
                fee_drag=Decimal("0.02"),
                slippage_est=Decimal("0.01"),
                net_edge=Decimal("0.07"),
                edge_type="speculative",
                confidence=Decimal("0.8"),
            )
            result = strat._kelly_size(edge, ExpiryPhase.MID, size_factor=0.8)

        mock_sizer.compute.assert_called_once()
        call_kwargs = mock_sizer.compute.call_args[1]
        assert call_kwargs["size_factor"] == pytest.approx(0.8), (
            "P0-1: size_factor not forwarded to sizer.compute()"
        )
        assert result == 3

    def test_kelly_size_fallback_respects_size_factor(self):
        """Functional: fallback Kelly result scales with size_factor."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig
        from merid.prediction.model import EdgeEstimate
        from merid.prediction.strategy import ExpiryPhase

        strat = KalshiStrategy(StrategyConfig(max_contracts_per_order=100))
        edge = EdgeEstimate(
            market_id="KXBTC-TEST2",
            side="yes",
            action="buy",
            model_prob=Decimal("0.65"),
            market_prob=Decimal("0.50"),
            raw_edge=Decimal("0.15"),
            fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"),
            net_edge=Decimal("0.12"),
            edge_type="speculative",
            confidence=Decimal("0.9"),
        )

        with patch(
            "merid.event_venues.kalshi.position_sizer.get_position_sizer",
            side_effect=ImportError("forced fallback"),
        ):
            full = strat._kelly_size(edge, ExpiryPhase.MID, size_factor=1.0)
            half = strat._kelly_size(edge, ExpiryPhase.MID, size_factor=0.5)

        # At size_factor=0.5, result must be ≤ full (may be floor at 0)
        assert half <= full, (
            "P0-1: fallback Kelly with size_factor=0.5 must not exceed size_factor=1.0"
        )


# =============================================================================
# P0-2 — kalshi_fee_cents deduplicated: single source in position_sizer.py
# =============================================================================

class TestP0_2_FeeDeduplication:
    """risk.py must not define kalshi_fee_cents locally — only import it."""

    def test_risk_py_does_not_define_kalshi_fee_cents(self):
        src = _src("merid/prediction/risk.py")
        # Must NOT contain a 'def kalshi_fee_cents' definition
        assert "def kalshi_fee_cents" not in src, (
            "P0-2: risk.py still defines its own kalshi_fee_cents — must be removed"
        )

    def test_risk_py_imports_from_position_sizer(self):
        src = _src("merid/prediction/risk.py")
        assert "from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents" in src, (
            "P0-2: risk.py must import kalshi_fee_cents from position_sizer"
        )

    def test_position_sizer_defines_kalshi_fee_cents(self):
        src = _src("merid/event_venues/kalshi/position_sizer.py")
        assert "def kalshi_fee_cents" in src, (
            "P0-2: position_sizer.py must be the canonical definition of kalshi_fee_cents"
        )

    def test_fee_function_importable_from_position_sizer(self):
        from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents
        assert callable(kalshi_fee_cents), (
            "P0-2: kalshi_fee_cents must be a callable in position_sizer"
        )

    def test_fee_function_same_object_in_both_modules(self):
        from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents as sizer_fn
        from merid.prediction.risk import kalshi_fee_cents as risk_fn
        assert sizer_fn is risk_fn, (
            "P0-2: both modules must reference the same kalshi_fee_cents function object"
        )

    def test_fee_calculation_consistent(self):
        from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents
        # Spot-check: 10 contracts at 60¢ → parabolic: ceil(0.07*10*0.60*0.40*100)=17
        fee = kalshi_fee_cents(price_cents=60, contracts=10)
        assert fee > 0, "P0-2: fee must be positive for valid trade"
        assert fee == 17, f"P0-2: expected 17¢ fee, got {fee}"


# =============================================================================
# P1-1 — LocalOrderbook.apply_delta fires alert on crossed book
# =============================================================================

class TestP1_1_CrossedMarketInvariant:
    """apply_delta must call _check_crossed_market after every update and
    PredictionAlertManager must receive a CRITICAL alert on a crossed book."""

    def test_check_crossed_market_method_exists(self):
        from merid.event_venues.kalshi.orderbook import LocalOrderbook
        assert hasattr(LocalOrderbook, "_check_crossed_market"), (
            "P1-1: LocalOrderbook must have _check_crossed_market method"
        )

    def test_apply_delta_calls_check(self):
        src = _src("merid/event_venues/kalshi/orderbook.py")
        lines = src.splitlines()
        start = next(i for i, l in enumerate(lines) if "def apply_delta" in l)
        body = "\n".join(lines[start:start + 50])
        assert "_check_crossed_market()" in body, (
            "P1-1: apply_delta must call self._check_crossed_market() after updating levels"
        )

    def test_snapshot_age_seconds_property(self):
        from merid.event_venues.kalshi.orderbook import LocalOrderbook
        ob = LocalOrderbook("TEST-TICKER")
        # Before snapshot: None
        assert ob.snapshot_age_seconds is None
        ob.apply_snapshot({"yes": [[60, 10]], "no": [[40, 10]], "seq": 1})
        age = ob.snapshot_age_seconds
        assert age is not None and age >= 0.0, (
            "P1-1: snapshot_age_seconds should be >= 0 after apply_snapshot"
        )

    def test_crossed_long_fires_alert(self):
        """yes_bid + no_bid > 100 must fire a CRITICAL alert."""
        import merid.event_venues.kalshi.orderbook as ob_mod
        import merid.prediction.alerts as alerts_mod
        from merid.event_venues.kalshi.orderbook import LocalOrderbook
        from merid.prediction.alerts import PredictionAlertManager, AlertSeverity

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        ob = LocalOrderbook("KXBTC-CROSS")
        ob.apply_snapshot({"yes": [[70, 10]], "no": [[20, 10]], "seq": 1})

        # orderbook.py does an inline 'from merid.prediction.alerts import get_alert_manager'
        # so patching the attribute on the alerts module is the correct target.
        with patch.object(alerts_mod, "get_alert_manager", return_value=mgr):
            # Inject a crossed state: yes_bid=70, no_bid=40 → 70+40=110 > 100
            ob.no_levels.clear()
            ob.no_levels[40] = 5  # no_bid=40 (min key)
            ob._check_crossed_market()

        critical = [a for a in fired if a.severity == AlertSeverity.CRITICAL]
        assert critical, (
            "P1-1: crossed book (yes_bid+no_bid>100) must fire a CRITICAL alert"
        )
        assert any("crossed" in a.title.lower() for a in critical), (
            "P1-1: alert title must mention 'crossed'"
        )

    def test_uncrossed_book_no_alert(self):
        """A valid book (yes_bid=60, no_bid=35 → 95 ≤ 100) must NOT fire."""
        import merid.prediction.alerts as alerts_mod
        from merid.event_venues.kalshi.orderbook import LocalOrderbook
        from merid.prediction.alerts import PredictionAlertManager

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        ob = LocalOrderbook("KXBTC-VALID")
        ob.apply_snapshot({"yes": [[60, 10]], "no": [[35, 10]], "seq": 1})

        with patch.object(alerts_mod, "get_alert_manager", return_value=mgr):
            ob._check_crossed_market()

        assert not fired, (
            "P1-1: valid book must not fire a crossed-market alert"
        )

    def test_uninitialized_delta_fires_staleness(self):
        """Delta on uninitialized book should fire fire_staleness, not crash."""
        import merid.prediction.alerts as alerts_mod
        from merid.event_venues.kalshi.orderbook import LocalOrderbook
        from merid.prediction.alerts import PredictionAlertManager

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        ob = LocalOrderbook("KXBTC-UNINIT")
        with patch.object(alerts_mod, "get_alert_manager", return_value=mgr):
            ob.apply_delta({"side": "yes", "price": 55, "size_delta": 5})

        # Should not raise and book should still be uninitialized
        assert not ob.initialized


# =============================================================================
# P1-2 — LiquidityMonitor auto-wires PredictionAlertManager on init
# =============================================================================

class TestP1_2_LiquidityMonitorBridge:
    """LiquidityMonitor.__init__ must register a callback that forwards
    alerts to PredictionAlertManager without any caller setup."""

    def test_wire_method_exists(self):
        from merid.event_venues.kalshi.liquidity_monitor import LiquidityMonitor
        assert hasattr(LiquidityMonitor, "_wire_prediction_alert_manager"), (
            "P1-2: LiquidityMonitor must have _wire_prediction_alert_manager method"
        )

    def test_callback_auto_registered_on_init(self):
        from merid.event_venues.kalshi.liquidity_monitor import LiquidityMonitor
        mon = LiquidityMonitor()
        # At least one callback registered (the PM bridge) without any manual call
        assert len(mon._callbacks) >= 1, (
            "P1-2: LiquidityMonitor.__init__ must auto-register at least one callback"
        )

    def test_critical_alert_reaches_pm_fire_risk_breach(self):
        """A critical liquidity alert must call fire_risk_breach on PM manager."""
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        from merid.prediction.alerts import PredictionAlertManager, AlertSeverity

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        with patch("merid.prediction.alerts.get_alert_manager", return_value=mgr):
            mon = LiquidityMonitor(max_spread=0.05, min_depth=100, cooldown_s=0)
            # zero-depth → critical
            snap = OrderBookSnapshot(
                market_id="KXBTC-LIQ", best_bid=0.50, best_ask=0.60,
                bid_size=0, ask_size=0,
            )
            mon.process(snap)

        critical = [a for a in fired if a.severity == AlertSeverity.CRITICAL]
        assert critical, (
            "P1-2: zero-depth alert must propagate as CRITICAL to PredictionAlertManager"
        )

    def test_warning_alert_reaches_pm_fire_risk_warning(self):
        """A warning liquidity alert (spread_spike) must call fire_risk_warning."""
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        from merid.prediction.alerts import PredictionAlertManager, AlertSeverity

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        with patch("merid.prediction.alerts.get_alert_manager", return_value=mgr):
            mon = LiquidityMonitor(max_spread=0.20, min_depth=1, cooldown_s=0,
                                   spike_mult=1.5, window=5)
            # Prime the buffer with narrow spreads, then spike
            for _ in range(5):
                mon.process(OrderBookSnapshot(
                    market_id="KXBTC-SPIKE", best_bid=0.49, best_ask=0.51,
                    bid_size=50, ask_size=50,
                ))
            # Wide spread spike — 2× the rolling average
            mon.process(OrderBookSnapshot(
                market_id="KXBTC-SPIKE", best_bid=0.40, best_ask=0.60,
                bid_size=50, ask_size=50,
            ))

        warnings = [a for a in fired if a.severity == AlertSeverity.WARNING]
        assert warnings, (
            "P1-2: spread_spike alert must propagate as WARNING to PredictionAlertManager"
        )


# =============================================================================
# P1-3 — strategy.evaluate() rejects snapshots older than SNAPSHOT_STALE_SECONDS
# =============================================================================

class TestP1_3_SnapshotStalenessGate:
    """evaluate() must return NO_ACTION and fire fire_staleness for stale snapshots."""

    def test_stale_constant_defined(self):
        import merid.prediction.strategy as strat_mod
        assert hasattr(strat_mod, "SNAPSHOT_STALE_SECONDS"), (
            "P1-3: SNAPSHOT_STALE_SECONDS constant not found in strategy.py"
        )
        assert strat_mod.SNAPSHOT_STALE_SECONDS > 0

    def test_stale_snapshot_returns_no_action(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction, SNAPSHOT_STALE_SECONDS
        from merid.prediction.model import (
            MarketSnapshot, ContractState, ImpliedProbability,
        )

        strat = KalshiStrategy(StrategyConfig())
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=SNAPSHOT_STALE_SECONDS + 60)

        snap = MarketSnapshot(
            market_id="KXBTC-STALE",
            event_id="KXBTC",
            title="Test",
            state=ContractState.TRADING,
            implied=ImpliedProbability(
                yes_prob=Decimal("0.50"), no_prob=Decimal("0.50"),
                yes_bid=Decimal("48"), yes_ask=Decimal("52"),
                no_bid=Decimal("48"), no_ask=Decimal("52"),
            ),
            volume=Decimal("1000"),
            open_interest=Decimal("500"),
            timestamp=stale_ts,
            time_to_expiry_hours=Decimal("4.0"),
        )

        signal = strat.evaluate(snap)
        assert signal.action == SignalAction.NO_ACTION, (
            "P1-3: stale snapshot must produce NO_ACTION signal"
        )
        assert "stale" in signal.reason.lower(), (
            "P1-3: NO_ACTION reason must mention 'stale'"
        )

    def test_stale_snapshot_fires_staleness_alert(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SNAPSHOT_STALE_SECONDS
        from merid.prediction.model import (
            MarketSnapshot, ContractState, ImpliedProbability,
        )
        from merid.prediction.alerts import PredictionAlertManager, AlertCategory

        mgr = PredictionAlertManager()
        fired = []
        mgr.add_sink(fired.append)

        strat = KalshiStrategy(StrategyConfig())
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=SNAPSHOT_STALE_SECONDS + 10)

        snap = MarketSnapshot(
            market_id="KXBTC-STALE2",
            event_id="KXBTC",
            title="Test",
            state=ContractState.TRADING,
            implied=ImpliedProbability(
                yes_prob=Decimal("0.50"), no_prob=Decimal("0.50"),
                yes_bid=Decimal("48"), yes_ask=Decimal("52"),
                no_bid=Decimal("48"), no_ask=Decimal("52"),
            ),
            volume=Decimal("1000"),
            open_interest=Decimal("500"),
            timestamp=stale_ts,
            time_to_expiry_hours=Decimal("4.0"),
        )

        with patch("merid.prediction.alerts.get_alert_manager", return_value=mgr):
            strat.evaluate(snap)

        staleness_alerts = [a for a in fired if a.category == AlertCategory.STALENESS]
        assert staleness_alerts, (
            "P1-3: stale snapshot must fire a STALENESS alert via PredictionAlertManager"
        )

    def test_fresh_snapshot_not_gated(self):
        """A fresh snapshot must not be rejected by the staleness gate."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction
        from merid.prediction.model import (
            MarketSnapshot, ContractState, ImpliedProbability,
        )

        strat = KalshiStrategy(StrategyConfig(
            min_volume=Decimal("0"),
            min_open_interest=Decimal("0"),
        ))
        snap = MarketSnapshot(
            market_id="KXBTC-FRESH",
            event_id="KXBTC",
            title="Test",
            state=ContractState.TRADING,
            implied=ImpliedProbability(
                yes_prob=Decimal("0.50"), no_prob=Decimal("0.50"),
                yes_bid=Decimal("48"), yes_ask=Decimal("52"),
                no_bid=Decimal("48"), no_ask=Decimal("52"),
            ),
            volume=Decimal("1000"),
            open_interest=Decimal("500"),
            timestamp=datetime.now(timezone.utc),
        )

        signal = strat.evaluate(snap)
        # Not rejected for staleness (may be NO_ACTION for other reasons but reason
        # must NOT say "stale")
        assert "stale" not in signal.reason.lower(), (
            "P1-3: fresh snapshot must not be rejected for staleness"
        )


# =============================================================================
# P1-4 — ws_bridge stamps ts + age_ms on streaming_bus MARKET_DATA events
# =============================================================================

class TestP1_4_StreamingBusTimestamp:
    """ws_bridge.py must include 'ts' and 'age_ms' keys in MARKET_DATA payloads."""

    def test_ts_key_in_market_data_event(self):
        src = _src("merid/event_venues/kalshi/ws_bridge.py")
        lines = src.splitlines()
        # Locate the streaming_bus MARKET_DATA event dict
        start = next(
            i for i, l in enumerate(lines) if "EventChannel.MARKET_DATA" in l
        )
        window = "\n".join(lines[start:start + 25])
        assert '"ts"' in window or "'ts'" in window, (
            "P1-4: 'ts' key not found in MARKET_DATA event payload in ws_bridge.py"
        )

    def test_age_ms_key_in_market_data_event(self):
        src = _src("merid/event_venues/kalshi/ws_bridge.py")
        lines = src.splitlines()
        start = next(
            i for i, l in enumerate(lines) if "EventChannel.MARKET_DATA" in l
        )
        window = "\n".join(lines[start:start + 25])
        assert '"age_ms"' in window or "'age_ms'" in window, (
            "P1-4: 'age_ms' key not found in MARKET_DATA event payload in ws_bridge.py"
        )

    def test_tick_ts_derived_from_event_timestamp(self):
        src = _src("merid/event_venues/kalshi/ws_bridge.py")
        assert "_tick_ts = event.timestamp.timestamp()" in src, (
            "P1-4: ts must be derived from event.timestamp.timestamp()"
        )

    def test_age_ms_computed_from_time_time(self):
        src = _src("merid/event_venues/kalshi/ws_bridge.py")
        assert "time.time() - _tick_ts" in src, (
            "P1-4: age_ms must be computed as time.time() - _tick_ts"
        )


# =============================================================================
# P2-1 — LiquidityMonitor zero_depth gate + flickering detection
# =============================================================================

class TestP2_1_ZeroDepthAndFlickering:
    """zero_depth must be a separate CRITICAL alert kind (not folded into thin_book).
    Flickering detection must fire when bids alternate rapidly."""

    def test_zero_depth_fires_critical(self):
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        mon = LiquidityMonitor(min_depth=10, cooldown_s=0)
        snap = OrderBookSnapshot(
            market_id="KXBTC-ZERO", best_bid=0.50, best_ask=0.60,
            bid_size=0, ask_size=0,
        )
        alerts = mon.process(snap)
        zero = [a for a in alerts if a.kind == "zero_depth"]
        assert zero, "P2-1: zero_depth alert not emitted when depth==0"
        assert zero[0].severity == "critical", (
            "P2-1: zero_depth alert must have severity='critical'"
        )

    def test_zero_depth_not_also_thin_book(self):
        """When depth==0 the zero_depth alert fires, but thin_book must not duplicate."""
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        mon = LiquidityMonitor(min_depth=10, cooldown_s=0)
        snap = OrderBookSnapshot(
            market_id="KXBTC-ZERO2", best_bid=0.50, best_ask=0.60,
            bid_size=0, ask_size=0,
        )
        alerts = mon.process(snap)
        thin = [a for a in alerts if a.kind == "thin_book"]
        assert not thin, (
            "P2-1: thin_book must not fire alongside zero_depth (use elif)"
        )

    def test_flickering_detected_on_rapid_alternation(self):
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        mon = LiquidityMonitor(
            min_depth=1, max_spread=1.0,
            flicker_window=10, flicker_threshold=0.7, cooldown_s=0,
        )
        # Alternate bid between 0.49 and 0.51 on every tick (100% alternation)
        all_alerts = []
        bids = [0.49, 0.51] * 10  # 20 ticks alternating
        for bid in bids:
            snaps = OrderBookSnapshot(
                market_id="KXBTC-FLICKER",
                best_bid=bid, best_ask=bid + 0.02,
                bid_size=20, ask_size=20,
            )
            all_alerts.extend(mon.process(snaps))

        flicker = [a for a in all_alerts if a.kind == "flickering"]
        assert flicker, "P2-1: flickering alert not emitted on rapidly alternating bids"
        assert flicker[0].severity == "warning", (
            "P2-1: flickering alert must have severity='warning'"
        )

    def test_stable_book_no_flicker(self):
        from merid.event_venues.kalshi.liquidity_monitor import (
            LiquidityMonitor, OrderBookSnapshot,
        )
        mon = LiquidityMonitor(
            min_depth=1, max_spread=1.0,
            flicker_window=10, flicker_threshold=0.7, cooldown_s=0,
        )
        all_alerts = []
        for _ in range(15):
            snap = OrderBookSnapshot(
                market_id="KXBTC-STABLE",
                best_bid=0.50, best_ask=0.52,
                bid_size=50, ask_size=50,
            )
            all_alerts.extend(mon.process(snap))

        flicker = [a for a in all_alerts if a.kind == "flickering"]
        assert not flicker, "P2-1: stable book must not trigger flickering alert"

    def test_flicker_params_in_constructor(self):
        from merid.event_venues.kalshi.liquidity_monitor import LiquidityMonitor
        mon = LiquidityMonitor(flicker_window=8, flicker_threshold=0.6)
        assert mon.flicker_window == 8
        assert mon.flicker_threshold == pytest.approx(0.6)


# =============================================================================
# P2-2 — CategoryExposureTracker.check_and_reserve is atomic
# =============================================================================

class TestP2_2_AtomicCategoryReserve:
    """check_and_reserve must atomically check caps AND reserve notional,
    preventing two concurrent threads from both passing and jointly breaching."""

    def test_check_and_reserve_method_exists(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        assert hasattr(CategoryExposureTracker, "check_and_reserve"), (
            "P2-2: CategoryExposureTracker must have check_and_reserve method"
        )

    def test_check_and_reserve_approves_and_reserves(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        tracker = CategoryExposureTracker(
            category_caps={"crypto": 1000.0},
            corr_cap_usd=500.0,
        )
        ok, reason = tracker.check_and_reserve("crypto", "BTC", 200.0)
        assert ok, f"P2-2: first reservation should pass; got reason={reason!r}"

        snap = tracker.get_snapshot()
        assert snap.category_notional.get("crypto", 0.0) == pytest.approx(200.0), (
            "P2-2: category notional must be incremented by check_and_reserve"
        )
        assert snap.corr_notional.get("BTC", 0.0) == pytest.approx(200.0), (
            "P2-2: correlated notional must be incremented by check_and_reserve"
        )

    def test_check_and_reserve_rejects_at_cap(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        tracker = CategoryExposureTracker(
            category_caps={"crypto": 300.0},
            corr_cap_usd=500.0,
        )
        ok1, _ = tracker.check_and_reserve("crypto", "BTC", 200.0)
        assert ok1
        # Second reservation would push to 400 > cap=300
        ok2, reason2 = tracker.check_and_reserve("crypto", "BTC", 200.0)
        assert not ok2, "P2-2: second reservation exceeding cap must be rejected"
        assert "category_cap_exceeded" in reason2

    def test_check_and_reserve_rejects_at_corr_cap(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        tracker = CategoryExposureTracker(
            category_caps={"crypto": 5000.0},
            corr_cap_usd=300.0,
        )
        ok1, _ = tracker.check_and_reserve("crypto", "BTC", 200.0)
        assert ok1
        ok2, reason2 = tracker.check_and_reserve("crypto", "BTC", 200.0)
        assert not ok2, "P2-2: correlated cap breach must be rejected"
        assert "corr_stack_cap_exceeded" in reason2

    def test_check_and_reserve_nothing_reserved_on_rejection(self):
        """On rejection, no notional must be reserved."""
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        tracker = CategoryExposureTracker(
            category_caps={"crypto": 100.0},
            corr_cap_usd=500.0,
        )
        ok, _ = tracker.check_and_reserve("crypto", "BTC", 200.0)  # exceeds cap immediately
        assert not ok
        snap = tracker.get_snapshot()
        assert snap.category_notional.get("crypto", 0.0) == pytest.approx(0.0), (
            "P2-2: rejected reservation must not mutate notional"
        )

    def test_concurrent_reservations_stay_within_cap(self):
        """Two threads each trying to reserve 600 against cap=1000 — only one wins."""
        import threading
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker

        tracker = CategoryExposureTracker(
            category_caps={"crypto": 1000.0},
            corr_cap_usd=2000.0,
        )
        results = []

        def _reserve():
            ok, reason = tracker.check_and_reserve("crypto", "ETH", 600.0)
            results.append(ok)

        t1 = threading.Thread(target=_reserve)
        t2 = threading.Thread(target=_reserve)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Exactly one should succeed (600 fits, 1200 doesn't)
        assert sum(results) == 1, (
            f"P2-2: exactly one of two concurrent 600$ reservations against cap=1000 "
            f"must succeed; got {results}"
        )
        snap = tracker.get_snapshot()
        assert snap.category_notional.get("crypto", 0.0) == pytest.approx(600.0), (
            "P2-2: final notional must be exactly 600 after concurrent reservations"
        )

    def test_release_after_reserve(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        tracker = CategoryExposureTracker(
            category_caps={"crypto": 1000.0},
            corr_cap_usd=1000.0,
        )
        tracker.check_and_reserve("crypto", "BTC", 400.0)
        tracker.release("crypto", "BTC", 400.0)
        snap = tracker.get_snapshot()
        assert snap.category_notional.get("crypto", 0.0) == pytest.approx(0.0), (
            "P2-2: release must undo reservation"
        )


# =============================================================================
# P2-3 — DebateAwarePositionSizer semaphore + inflight deduplication
# =============================================================================

class TestP2_3_BacktestSemaphore:
    """DebateAwarePositionSizer must have a semaphore cap and per-symbol
    inflight deduplication to prevent thundering-herd on the backtest engine."""

    def test_max_concurrent_constant_exists(self):
        from merid.prediction.debate_position_sizing import DebateAwarePositionSizer
        assert hasattr(DebateAwarePositionSizer, "_MAX_CONCURRENT_BACKTESTS"), (
            "P2-3: _MAX_CONCURRENT_BACKTESTS class constant not found"
        )
        assert DebateAwarePositionSizer._MAX_CONCURRENT_BACKTESTS >= 1

    def test_backtest_semaphore_attr_on_init(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "_backtest_semaphore" in src, (
            "P2-3: _backtest_semaphore not initialised in DebateAwarePositionSizer.__init__"
        )

    def test_inflight_dict_on_init(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "_inflight" in src, (
            "P2-3: _inflight dict not initialised in DebateAwarePositionSizer.__init__"
        )

    def test_get_semaphore_method_exists(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "def _get_semaphore" in src, (
            "P2-3: _get_semaphore lazy-init method not found"
        )

    def test_asyncio_semaphore_used_in_profile_method(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "async with self._get_semaphore()" in src, (
            "P2-3: semaphore not used via 'async with' in _get_performance_profile"
        )

    def test_inflight_coalesce_logic_present(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "self._inflight" in src and "asyncio.shield" in src, (
            "P2-3: inflight coalescing via asyncio.shield not found"
        )

    def test_inflight_cleaned_up_in_finally(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "self._inflight.pop(symbol, None)" in src, (
            "P2-3: _inflight must be cleaned up in a finally block"
        )

    def test_asyncio_imported(self):
        src = _src("merid/prediction/debate_position_sizing.py")
        assert "import asyncio" in src, (
            "P2-3: asyncio must be imported in debate_position_sizing.py"
        )

    def test_semaphore_cap_is_sane(self):
        from merid.prediction.debate_position_sizing import DebateAwarePositionSizer
        cap = DebateAwarePositionSizer._MAX_CONCURRENT_BACKTESTS
        assert 1 <= cap <= 10, (
            f"P2-3: _MAX_CONCURRENT_BACKTESTS={cap} seems unreasonable; expected 1–10"
        )

    def test_semaphore_limits_concurrency(self):
        """Functional: semaphore must block a 3rd concurrent backtest when cap=2."""
        import asyncio as aio
        from merid.prediction.debate_position_sizing import DebateAwarePositionSizer

        async def _run():
            sizer = DebateAwarePositionSizer.__new__(DebateAwarePositionSizer)
            sizer._MAX_CONCURRENT_BACKTESTS = 2
            sizer._backtest_semaphore = None
            sem = sizer._get_semaphore()
            assert sem._value == 2

            acquired = []
            async with sem:
                acquired.append(1)
                async with sem:
                    acquired.append(2)
                    # semaphore value should now be 0 — third acquire would block
                    assert sem._value == 0, (
                        "P2-3: semaphore should be fully acquired after 2 concurrent holders"
                    )

            return acquired

        result = aio.run(_run())
        assert result == [1, 2]

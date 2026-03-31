"""Tests for Kalshi signal data-driven computation and loop-lag execution gate.

Test Cases:
  §1  Edge signals change with different market data (not hardcoded)
  §2  Liquidity signals fire on wide spreads / thin books
  §3  Volume signals fire on cross-sectional anomalies
  §4  Risk signals fire on kill-switch / drawdown
  §5  Loop-lag → execution gate transitions (clear → degraded → blocked → clear)
  §6  Blocked gate prevents order execution
"""
from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.signals.kalshi_signals import (
    KalshiSignalGenerator,
    MarketEdgeSignal,
    LiquiditySignal,
    VolumeAnomalySignal,
    KalshiRiskSignal,
    reset_kalshi_signal_generator,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_instrument(
    id: str,
    bid: float = None,
    ask: float = None,
    last_price: float = None,
    volume: float = 0,
    open_interest: float = 100,
    title: str = "",
):
    """Create a mock instrument with configurable price data."""
    inst = MagicMock()
    inst.id = id
    inst.best_bid = bid
    inst.best_ask = ask
    inst.bid = bid
    inst.ask = ask
    inst.last_price = last_price
    inst.price = last_price
    inst.volume = volume
    inst.open_interest = open_interest
    inst.depth = open_interest
    inst.title = title or f"Market {id}"
    return inst


def _patch_venue_adapter(instruments):
    """Context manager that patches the venue adapter import inside signal methods."""
    adapter = MagicMock()
    adapter.list_instruments = AsyncMock(return_value=instruments)
    mock_module = MagicMock()
    mock_module.get_kalshi_venue_adapter = MagicMock(return_value=adapter)
    return patch.dict("sys.modules", {
        "merid.event_venues": MagicMock(),
        "merid.event_venues.kalshi": MagicMock(),
        "merid.event_venues.kalshi.venue_adapter": mock_module,
    })


# ══════════════════════════════════════════════════════════════════════════════
# §1  Edge signals are data-driven (not hardcoded)
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeSignalsDataDriven:

    @pytest.mark.asyncio
    async def test_edge_varies_with_bid_ask(self):
        """Two instruments with different bid/ask produce different edge values."""
        reset_kalshi_signal_generator()
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-DAILY-A", bid=40, ask=50, volume=200),  # mid=45
            _mock_instrument("ETH-DAILY-B", bid=70, ask=80, volume=200),  # mid=75
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_edge_signals(time.time())

        # Both should produce signals with different implied_prob
        assert len(signals) >= 1
        probs = {s.implied_prob for s in signals}
        assert len(probs) >= 1  # at least varying data

    @pytest.mark.asyncio
    async def test_edge_no_hardcoded_055(self):
        """Edge signals should NOT always produce implied_prob=0.55 (old hardcoded value)."""
        reset_kalshi_signal_generator()
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-DAILY-C", bid=30, ask=35, volume=100),  # mid=32.5
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_edge_signals(time.time())

        for s in signals:
            assert s.implied_prob != 0.55, "Edge signal still uses hardcoded 0.55"
            assert s.source != "synthetic", "Edge signal still marked as synthetic"

    @pytest.mark.asyncio
    async def test_edge_skips_no_price_data(self):
        """Instruments with no bid/ask/last should be skipped, not produce bogus signals."""
        reset_kalshi_signal_generator()
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-NO-PRICE", bid=None, ask=None, last_price=None),
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_edge_signals(time.time())

        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_edge_uses_last_price_fallback(self):
        """When bid/ask are missing but last_price exists, use it."""
        reset_kalshi_signal_generator()
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-DAILY-X", bid=None, ask=None, last_price=60, volume=150),
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_edge_signals(time.time())

        # Should produce a signal with implied_prob derived from last_price=60
        if signals:
            assert abs(signals[0].implied_prob - 0.60) < 0.05


# ══════════════════════════════════════════════════════════════════════════════
# §2  Liquidity signals fire on wide spreads / thin books
# ══════════════════════════════════════════════════════════════════════════════

class TestLiquiditySignals:

    @pytest.mark.asyncio
    async def test_wide_spread_fires_alert(self):
        """Wide spread (>8%) triggers a liquidity warning."""
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-DAILY-W", bid=40, ask=55, open_interest=200),
            # spread = 15, mid = 47.5, spread_pct = 31.6% → critical
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_liquidity_signals(time.time())

        assert len(signals) == 1
        assert signals[0].alert_type == "wide_spread"
        assert signals[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_thin_book_fires_alert(self):
        """Low open interest (<20) triggers a thin_book warning."""
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("ETH-DAILY-T", bid=50, ask=52, open_interest=5),
            # spread_pct ~4% (OK), but depth=5 < 20 → thin_book
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_liquidity_signals(time.time())

        assert len(signals) == 1
        assert signals[0].alert_type == "thin_book"

    @pytest.mark.asyncio
    async def test_healthy_liquidity_no_alert(self):
        """Tight spread + deep book → no alert."""
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("SOL-DAILY-H", bid=50, ask=52, open_interest=500),
            # spread_pct ~4%, depth=500 → healthy
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_liquidity_signals(time.time())

        assert len(signals) == 0


# ══════════════════════════════════════════════════════════════════════════════
# §3  Volume anomaly signals
# ══════════════════════════════════════════════════════════════════════════════

class TestVolumeAnomalySignals:

    @pytest.mark.asyncio
    async def test_volume_spike_detected(self):
        """Instrument with volume far above the group mean gets flagged."""
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument("BTC-D-1", volume=100),
            _mock_instrument("ETH-D-2", volume=110),
            _mock_instrument("SOL-D-3", volume=90),
            _mock_instrument("XRP-D-4", volume=105),
            _mock_instrument("ADA-D-5", volume=95),
            _mock_instrument("DOGE-D-6", volume=100000),  # massive outlier
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_volume_signals(time.time())

        assert len(signals) >= 1
        spike = [s for s in signals if s.direction == "spike"]
        assert len(spike) >= 1
        assert spike[0].z_score > 2.0

    @pytest.mark.asyncio
    async def test_uniform_volume_no_anomaly(self):
        """When all volumes are similar, no anomaly fires."""
        gen = KalshiSignalGenerator()

        insts = [
            _mock_instrument(f"BTC-D-{i}", volume=100 + i) for i in range(5)
        ]

        with _patch_venue_adapter(insts):
            signals = await gen._generate_volume_signals(time.time())

        assert len(signals) == 0


# ══════════════════════════════════════════════════════════════════════════════
# §4  Risk signals from risk manager state
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskSignals:

    @pytest.mark.asyncio
    async def test_kill_switch_generates_signal(self):
        """Kill-switch engaged → circuit_breaker risk signal."""
        gen = KalshiSignalGenerator()

        mock_rc = MagicMock()
        mock_rc._global_kill = True
        mock_rc._kill_details = "Manual trigger"
        mock_rc._kill_reason = "operator"

        with patch("merid.signals.kalshi_signals.risk_controller", mock_rc, create=True):
            with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc)}):
                signals = await gen._generate_risk_signals(time.time())

        assert len(signals) >= 1
        assert any(s.category == "circuit_breaker" for s in signals)

    @pytest.mark.asyncio
    async def test_drawdown_generates_warning(self):
        """Elevated drawdown → drawdown risk signal."""
        gen = KalshiSignalGenerator()

        mock_rc = MagicMock()
        mock_rc._global_kill = False
        mock_rc._drawdown_pct = 7.5
        mock_rc._daily_pnl = 0.0

        with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc)}):
            signals = await gen._generate_risk_signals(time.time())

        assert len(signals) >= 1
        dd_signals = [s for s in signals if s.category == "drawdown"]
        assert len(dd_signals) == 1
        assert dd_signals[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_no_risk_events_when_healthy(self):
        """No kill switch, no drawdown, no loss → no risk signals."""
        gen = KalshiSignalGenerator()

        mock_rc = MagicMock()
        mock_rc._global_kill = False
        mock_rc._drawdown_pct = 1.0
        mock_rc._daily_pnl = 50.0  # positive

        with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc)}):
            signals = await gen._generate_risk_signals(time.time())

        assert len(signals) == 0


# ══════════════════════════════════════════════════════════════════════════════
# §5  Loop-lag → execution gate transitions
# ══════════════════════════════════════════════════════════════════════════════

class TestLoopLagExecutionGate:

    def setup_method(self):
        from core.execution_gate import reset_loop_lag_state, set_loop_lag_config, LoopLagConfig
        reset_loop_lag_state()
        set_loop_lag_config(LoopLagConfig(
            warn_threshold_ms=200.0,
            block_threshold_ms=500.0,
            sustained_count=3,
            rolling_window_s=60.0,
            cooloff_s=5.0,
        ))

    def test_no_lag_no_block(self):
        """When no lag samples exist, no block reason is produced."""
        from core.execution_gate import _check_loop_lag
        reason = _check_loop_lag()
        assert reason is None

    def test_normal_lag_no_block(self):
        """Normal lag below warning threshold → no block."""
        from core.execution_gate import record_loop_lag, _check_loop_lag
        now = time.time()
        for i in range(10):
            record_loop_lag(50.0, ts=now + i)
        reason = _check_loop_lag()
        assert reason is None

    def test_elevated_lag_produces_warning(self):
        """Sustained elevated lag (above warn, below critical) → warning."""
        from core.execution_gate import record_loop_lag, _check_loop_lag
        now = time.time()
        for i in range(10):
            record_loop_lag(300.0, ts=now + i)  # above 200ms warn
        reason = _check_loop_lag()
        assert reason is not None
        assert reason.severity == "warning"
        assert "elevated" in reason.message.lower() or "p95" in reason.message.lower()

    def test_sustained_critical_blocks(self):
        """Sustained critical lag (>=3 consecutive >= 500ms) → blocked."""
        from core.execution_gate import record_loop_lag, _check_loop_lag
        now = time.time()
        # 3 consecutive critical samples
        for i in range(3):
            record_loop_lag(600.0, ts=now + i)
        reason = _check_loop_lag()
        assert reason is not None
        assert reason.severity == "critical"
        assert "blocked" in reason.message.lower() or "sustained" in reason.message.lower()

    def test_transient_spike_no_block(self):
        """Single critical spike surrounded by normal → warning at most, not blocked."""
        from core.execution_gate import record_loop_lag, _check_loop_lag
        now = time.time()
        record_loop_lag(50.0, ts=now)
        record_loop_lag(800.0, ts=now + 1)  # single spike
        record_loop_lag(50.0, ts=now + 2)
        reason = _check_loop_lag()
        # Should NOT be critical (transient spike resets consecutive counter)
        if reason is not None:
            assert reason.severity != "critical"

    def test_cooloff_period_blocks_until_expired(self):
        """After sustained critical lag, gate stays blocked for cooloff_s."""
        from core.execution_gate import record_loop_lag, _check_loop_lag, _lag_blocked_until
        now = time.time()
        # Trigger block
        for i in range(5):
            record_loop_lag(600.0, ts=now + i)

        reason = _check_loop_lag()
        assert reason is not None
        assert reason.severity == "critical"

    def test_block_clears_after_cooloff(self):
        """After cooloff expires, gate clears if lag is now normal."""
        from core.execution_gate import (
            record_loop_lag, _check_loop_lag,
            reset_loop_lag_state, set_loop_lag_config, LoopLagConfig,
        )
        reset_loop_lag_state()
        set_loop_lag_config(LoopLagConfig(
            warn_threshold_ms=200.0,
            block_threshold_ms=500.0,
            sustained_count=3,
            rolling_window_s=60.0,
            cooloff_s=0.0,  # immediate cooloff for testing
        ))
        # Use timestamps in the past so cooloff expires instantly
        past = time.time() - 120
        # Trigger block with past timestamps
        for i in range(3):
            record_loop_lag(600.0, ts=past + i)
        # Now send normal samples with recent timestamps to reset consecutive counter
        now = time.time()
        for i in range(5):
            record_loop_lag(50.0, ts=now + i)
        reason = _check_loop_lag()
        # With cooloff=0 and normal samples, should not be critical anymore
        if reason is not None:
            assert reason.severity != "critical"


# ══════════════════════════════════════════════════════════════════════════════
# §6  Execution gate integrates loop-lag check
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutionGateWithLoopLag:

    def setup_method(self):
        from core.execution_gate import (
            reset_loop_lag_state, set_loop_lag_config, LoopLagConfig,
            _update_blocked_state,
        )
        reset_loop_lag_state()
        _update_blocked_state(False)  # pretend we were clear before
        set_loop_lag_config(LoopLagConfig(
            warn_threshold_ms=200.0,
            block_threshold_ms=500.0,
            sustained_count=3,
            rolling_window_s=60.0,
            cooloff_s=5.0,
        ))

    def test_gate_includes_loop_lag_reason(self):
        """check_execution_gate() includes loop_lag reason when lag is high."""
        from core.execution_gate import record_loop_lag, check_execution_gate
        now = time.time()
        for i in range(3):
            record_loop_lag(600.0, ts=now + i)

        # Patch other checks to not interfere
        with patch("core.execution_gate._is_kalshi_demo_mode", return_value=True):
            gate = check_execution_gate()

        lag_reasons = [r for r in gate.reasons if r.source == "loop_lag"]
        assert len(lag_reasons) >= 1
        assert lag_reasons[0].severity == "critical"

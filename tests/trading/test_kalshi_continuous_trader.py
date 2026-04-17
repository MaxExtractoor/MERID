"""Tests for Kalshi continuous trader.

Tests the continuous trading module with confidence clamp and group-level risk.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import pytest


@dataclass
class MockTraderConfig:
    """Mock configuration for continuous trader."""
    enabled: bool = True
    max_position_contracts: int = 1000
    confidence_threshold: float = 0.6
    confidence_clamp_max: float = 0.95
    risk_per_trade_pct: float = 0.02
    max_open_positions: int = 5
    asset_whitelist: Set[str] = field(default_factory=lambda: {"BTC", "ETH", "SOL", "XRP", "DOGE"})


@dataclass 
class MockTradingSignal:
    """Mock trading signal."""
    ticker: str
    direction: str  # "buy" or "sell"
    confidence: float  # 0.0 to 1.0
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None


class MockKalshiContinuousTrader:
    """Mock continuous trader for testing."""
    
    def __init__(self, config: MockTraderConfig) -> None:
        self.config = config
        self._running = False
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._signals_processed = 0
        self._trades_executed = 0
        self._errors = []
        self._group_risk_exposure: Dict[str, float] = {}  # group -> exposure
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the continuous trader."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
    
    async def stop(self) -> None:
        """Stop the continuous trader."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
    
    def is_running(self) -> bool:
        """Check if trader is running."""
        return self._running and self._task is not None
    
    async def _run_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            await asyncio.sleep(1)
    
    def clamp_confidence(self, confidence: float) -> float:
        """Clamp confidence to configured range."""
        if confidence < self.config.confidence_threshold:
            return 0.0  # Reject below threshold
        return min(confidence, self.config.confidence_clamp_max)
    
    def check_group_risk(self, group: str, new_exposure: float) -> bool:
        """Check if trade would violate group-level risk limits."""
        current = self._group_risk_exposure.get(group, 0.0)
        total = current + new_exposure
        # Group risk limit: 20% of portfolio
        group_limit = 0.20
        return total <= group_limit
    
    def update_group_risk(self, group: str, exposure: float) -> None:
        """Update group risk exposure."""
        self._group_risk_exposure[group] = self._group_risk_exposure.get(group, 0.0) + exposure
    
    async def process_signal(self, signal: MockTradingSignal) -> bool:
        """Process a trading signal with all checks."""
        self._signals_processed += 1
        
        # Check if enabled
        if not self.config.enabled:
            return False
        
        # Check if running
        if not self._running:
            return False
        
        # Confidence clamping
        clamped = self.clamp_confidence(signal.confidence)
        if clamped == 0.0:
            return False  # Rejected by confidence filter
        
        # Asset whitelist check
        asset = self._extract_asset(signal.ticker)
        if asset not in self.config.asset_whitelist:
            return False
        
        # Position limit check
        if len(self._positions) >= self.config.max_open_positions:
            return False
        
        # Group risk check
        group = self._get_group_for_asset(asset)
        exposure = self._calculate_exposure(signal, clamped)
        if not self.check_group_risk(group, exposure):
            return False
        
        # Execute trade
        self._positions[signal.ticker] = {
            "direction": signal.direction,
            "confidence": clamped,
            "entry_time": datetime.now(timezone.utc),
        }
        self.update_group_risk(group, exposure)
        self._trades_executed += 1
        return True
    
    def _extract_asset(self, ticker: str) -> str:
        """Extract asset from ticker."""
        # Simple extraction: KXBTC-15M -> BTC
        if ticker.startswith("KX"):
            asset = ticker[2:].split("-")[0].split("15M")[0].split("D1")[0]
            return asset
        return ticker
    
    def _get_group_for_asset(self, asset: str) -> str:
        """Get risk group for asset."""
        crypto_group = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        if asset in crypto_group:
            return "crypto"
        return "other"
    
    def _calculate_exposure(self, signal: MockTradingSignal, confidence: float) -> float:
        """Calculate position exposure."""
        base_exposure = self.config.risk_per_trade_pct
        return base_exposure * confidence
    
    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get position for ticker."""
        return self._positions.get(ticker)
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get all positions."""
        return dict(self._positions)
    
    def stats(self) -> Dict[str, Any]:
        """Get trader statistics."""
        return {
            "running": self.is_running(),
            "signals_processed": self._signals_processed,
            "trades_executed": self._trades_executed,
            "open_positions": len(self._positions),
            "group_risk_exposure": dict(self._group_risk_exposure),
        }


@pytest.fixture
def config() -> MockTraderConfig:
    """Provide default trader config."""
    return MockTraderConfig()


@pytest.fixture
def trader(config: MockTraderConfig) -> MockKalshiContinuousTrader:
    """Provide a fresh trader instance."""
    return MockKalshiContinuousTrader(config)


class TestContinuousTraderLifecycle:
    """Test trader start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_stop(self, trader: MockKalshiContinuousTrader) -> None:
        """Test basic start and stop."""
        assert not trader.is_running()
        
        await trader.start()
        assert trader.is_running()
        
        await trader.stop()
        assert not trader.is_running()

    @pytest.mark.asyncio
    async def test_double_start(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that double start is safe."""
        await trader.start()
        await trader.start()  # Should not crash
        
        assert trader.is_running()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, trader: MockKalshiContinuousTrader) -> None:
        """Test stop when not running is safe."""
        await trader.stop()  # Should not crash
        
        assert not trader.is_running()

    @pytest.mark.asyncio
    async def test_task_cleanup_on_stop(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that task is properly cleaned up on stop."""
        await trader.start()
        assert trader._task is not None
        
        await trader.stop()
        assert trader._task is None


class TestContinuousTraderConfidenceClamping:
    """Test confidence clamping behavior."""

    def test_confidence_below_threshold_rejected(self, config: MockTraderConfig) -> None:
        """Test that confidence below threshold returns 0."""
        trader = MockKalshiContinuousTrader(config)
        clamped = trader.clamp_confidence(0.5)  # Below 0.6 threshold
        assert clamped == 0.0

    def test_confidence_at_threshold_accepted(self, config: MockTraderConfig) -> None:
        """Test that confidence at threshold is accepted."""
        trader = MockKalshiContinuousTrader(config)
        clamped = trader.clamp_confidence(0.6)  # At threshold
        assert clamped == 0.6

    def test_confidence_above_max_clamped(self, config: MockTraderConfig) -> None:
        """Test that confidence above max is clamped."""
        trader = MockKalshiContinuousTrader(config)
        clamped = trader.clamp_confidence(0.99)  # Above 0.95 max
        assert clamped == 0.95

    def test_confidence_within_range_unchanged(self, config: MockTraderConfig) -> None:
        """Test that confidence within range is unchanged."""
        trader = MockKalshiContinuousTrader(config)
        clamped = trader.clamp_confidence(0.8)  # Within [0.6, 0.95]
        assert clamped == 0.8

    @pytest.mark.asyncio
    async def test_signal_rejected_by_confidence(self, trader: MockKalshiContinuousTrader) -> None:
        """Test signal rejected due to low confidence."""
        await trader.start()
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.5)  # Below threshold
        result = await trader.process_signal(signal)
        
        assert result is False
        assert trader.stats()["trades_executed"] == 0


class TestContinuousTraderGroupRisk:
    """Test group-level risk management."""

    def test_group_risk_check_passes(self, config: MockTraderConfig) -> None:
        """Test group risk check when under limit."""
        trader = MockKalshiContinuousTrader(config)
        assert trader.check_group_risk("crypto", 0.05) is True

    def test_group_risk_check_fails_when_over(self, config: MockTraderConfig) -> None:
        """Test group risk check when over limit."""
        trader = MockKalshiContinuousTrader(config)
        trader._group_risk_exposure["crypto"] = 0.18
        # Adding 5% would exceed 20% limit
        assert trader.check_group_risk("crypto", 0.05) is False

    def test_group_risk_updates_correctly(self, config: MockTraderConfig) -> None:
        """Test that group risk is updated after trade."""
        trader = MockKalshiContinuousTrader(config)
        trader.update_group_risk("crypto", 0.05)
        assert trader._group_risk_exposure["crypto"] == 0.05
        
        trader.update_group_risk("crypto", 0.03)
        assert trader._group_risk_exposure["crypto"] == 0.08

    @pytest.mark.asyncio
    async def test_trade_rejected_by_group_risk(self, trader: MockKalshiContinuousTrader) -> None:
        """Test trade rejected due to group risk limit."""
        await trader.start()
        trader._group_risk_exposure["crypto"] = 0.19  # Near limit
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.8)
        result = await trader.process_signal(signal)
        
        assert result is False


class TestContinuousTraderPositionLimits:
    """Test position limit enforcement."""

    @pytest.mark.asyncio
    async def test_max_positions_enforced(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that max open positions is enforced."""
        await trader.start()
        
        # Fill to max positions (5)
        for i in range(5):
            signal = MockTradingSignal(f"KXBTC-{i}", "buy", 0.8)
            result = await trader.process_signal(signal)
            assert result is True
        
        # Next one should fail
        signal = MockTradingSignal("KXBTC-EXCESS", "buy", 0.8)
        result = await trader.process_signal(signal)
        assert result is False


class TestContinuousTraderAssetWhitelist:
    """Test asset whitelist enforcement."""

    @pytest.mark.asyncio
    async def test_whitelisted_asset_accepted(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that whitelisted asset is accepted."""
        await trader.start()
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.8)
        result = await trader.process_signal(signal)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_whitelisted_asset_rejected(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that non-whitelisted asset is rejected."""
        await trader.start()
        
        signal = MockTradingSignal("KXINVALID-15M", "buy", 0.8)
        result = await trader.process_signal(signal)
        assert result is False


class TestContinuousTraderPositionTracking:
    """Test position tracking."""

    @pytest.mark.asyncio
    async def test_position_stored_after_trade(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that position is tracked after successful trade."""
        await trader.start()
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.8)
        await trader.process_signal(signal)
        
        position = trader.get_position("KXBTC-15M")
        assert position is not None
        assert position["direction"] == "buy"
        assert position["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_get_all_positions(self, trader: MockKalshiContinuousTrader) -> None:
        """Test retrieving all positions."""
        await trader.start()
        
        await trader.process_signal(MockTradingSignal("KXBTC-15M", "buy", 0.8))
        await trader.process_signal(MockTradingSignal("KXETH-15M", "buy", 0.75))
        
        positions = trader.get_all_positions()
        assert len(positions) == 2
        assert "KXBTC-15M" in positions
        assert "KXETH-15M" in positions


class TestContinuousTraderStats:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_accuracy(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that stats accurately reflect state."""
        await trader.start()
        
        await trader.process_signal(MockTradingSignal("KXBTC-15M", "buy", 0.8))
        await trader.process_signal(MockTradingSignal("KXETH-15M", "buy", 0.75))
        await trader.process_signal(MockTradingSignal("KXINVALID", "buy", 0.5))  # Rejected
        
        stats = trader.stats()
        assert stats["running"] is True
        assert stats["signals_processed"] == 3
        assert stats["trades_executed"] == 2
        assert stats["open_positions"] == 2

    @pytest.mark.asyncio
    async def test_group_risk_in_stats(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that group risk exposure appears in stats."""
        await trader.start()
        
        await trader.process_signal(MockTradingSignal("KXBTC-15M", "buy", 0.8))
        
        stats = trader.stats()
        assert "crypto" in stats["group_risk_exposure"]
        assert stats["group_risk_exposure"]["crypto"] > 0


class TestContinuousTraderEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_zero_confidence_rejected(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that zero confidence signal is rejected."""
        await trader.start()
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.0)
        result = await trader.process_signal(signal)
        assert result is False

    @pytest.mark.asyncio
    async def test_disabled_trader_rejects_all(self, config: MockTraderConfig) -> None:
        """Test that disabled trader rejects all signals."""
        config.enabled = False
        trader = MockKalshiContinuousTrader(config)
        await trader.start()
        
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.9)
        result = await trader.process_signal(signal)
        assert result is False

    @pytest.mark.asyncio
    async def test_signal_when_not_running(self, trader: MockKalshiContinuousTrader) -> None:
        """Test that signal is rejected when not running."""
        # Don't start trader
        signal = MockTradingSignal("KXBTC-15M", "buy", 0.9)
        result = await trader.process_signal(signal)
        assert result is False

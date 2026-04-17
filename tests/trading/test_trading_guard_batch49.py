"""Additional tests for trading_guard uncovered lines - Batch 49."""
import pytest
from unittest.mock import MagicMock, patch

from trading.guards.trading_guard import (
    TradingGuard, TradingGuardConfig, GuardDecisionStatus,
    CircuitBreakerState, SolanaAntiRugGuard, SolanaAntiRugConfig,
    TokenRisk
)
from trading.config.runtime_config import VenueMode


class MockTradeRequest:
    """Mock trade request for testing."""
    def __init__(self, venue="coinbase", symbol="BTC-USD", quantity=1.0, price=45000.0,
                 notional_usd=None, live=False, metadata=None):
        self.venue = venue
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.notional_usd = notional_usd
        self.live = live
        self.metadata = metadata or {}


class TestTradingGuardUncovered:
    """Tests for previously uncovered lines in TradingGuard."""

    def test_half_open_success_exceeds_max(self):
        """Test half-open success count exceeds max to close circuit (lines 184-186, 195-198)."""
        guard = TradingGuard()
        guard.config.circuit_breaker_half_open_max = 2
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard._half_open_successes = 1
        guard._error_timestamps = [1.0, 2.0, 3.0]
        
        # Second success should trigger close
        guard.record_success()
        
        assert guard._circuit_state == CircuitBreakerState.CLOSED
        assert len(guard._error_timestamps) == 0
        assert guard._half_open_successes == 0

    def test_venue_live_paper_request(self):
        """Test venue LIVE mode with paper request (lines 285-286)."""
        cfg = TradingGuardConfig(allow_live_trades=True)
        guard = TradingGuard(config=cfg)
        
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False, "allow_live_trades": True}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime
        
        # Request with live=False when venue is LIVE
        request = MockTradeRequest(live=False, notional_usd=1000)
        decision = guard.evaluate(request, vpn_connected=True)
        
        assert decision.status == GuardDecisionStatus.ALLOW
        assert decision.metadata.get("override_live") is True

    def test_venue_notional_limit_exceeded(self):
        """Test venue-specific notional limit (lines 300-301)."""
        cfg = TradingGuardConfig(allow_live_trades=True, max_notional_usd=50000)
        guard = TradingGuard(config=cfg)
        
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False, "allow_live_trades": True}
        # Venue has lower limit than global
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=5000)
        guard.runtime_config = mock_runtime
        
        request = MockTradeRequest(live=True, notional_usd=10000)
        decision = guard.evaluate(request, vpn_connected=True)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "venue limit" in decision.reason.lower()


class TestSolanaAntiRugConfigUncovered:
    """Tests for previously uncovered lines in SolanaAntiRugConfig."""

    def test_get_float_invalid_value(self):
        """Test _get_float with invalid value (lines 336-337)."""
        with patch.dict('os.environ', {"MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD": "invalid"}, clear=True):
            cfg = SolanaAntiRugConfig.from_env()
            # Should use default when value is invalid
            assert cfg.min_liquidity_usd == 100_000.0

    def test_get_enum_invalid_value(self):
        """Test _get_enum with invalid value (lines 344-345)."""
        with patch.dict('os.environ', {"MERID_SOLANA_SNIPER_MAX_RISK": "invalid_risk"}, clear=True):
            cfg = SolanaAntiRugConfig.from_env()
            # Should use default when value is invalid
            assert cfg.max_token_risk == TokenRisk.MEDIUM


class TestSolanaAntiRugGuardUncovered:
    """Tests for previously uncovered lines in SolanaAntiRugGuard."""

    def test_token_risk_enum_conversion_exception(self):
        """Test token risk enum conversion with exception (lines 390-391)."""
        guard = SolanaAntiRugGuard()
        
        # Use an object that will cause exception when converted to enum
        class BadRisk:
            def __str__(self):
                return "not_a_risk"
        
        context = {
            "liquidity_usd": 200_000,
            "token_risk": BadRisk(),  # Will cause exception in conversion
            "liquidity_locked": True
        }
        decision = guard.evaluate(context)
        
        # Should default to HIGH risk and block
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_token_risk_exceeds_max(self):
        """Test token risk exceeds max threshold (line 398)."""
        cfg = SolanaAntiRugConfig(max_token_risk=TokenRisk.LOW)
        guard = SolanaAntiRugGuard(config=cfg)
        
        # MEDIUM is higher than LOW max
        context = {
            "liquidity_usd": 200_000,
            "token_risk": TokenRisk.MEDIUM,
            "liquidity_locked": True
        }
        decision = guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "exceeds max" in decision.reason.lower()

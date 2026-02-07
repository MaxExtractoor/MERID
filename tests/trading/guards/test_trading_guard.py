"""Comprehensive tests for trading/guards/trading_guard.py.

Covers:
- GuardDecisionStatus, CircuitBreakerState enums
- GuardDecision dataclass
- TradingGuardConfig (construction, from_env, defaults)
- TradingGuard circuit breaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- TradingGuard.evaluate() all decision paths
- SolanaAntiRugConfig and SolanaAntiRugGuard
- Helper functions (_safe_global_mode, _estimate_notional)
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from trading.guards.trading_guard import (
    GuardDecision,
    GuardDecisionStatus,
    CircuitBreakerState,
    TradingGuardConfig,
    TradingGuard,
    SolanaAntiRugConfig,
    SolanaAntiRugGuard,
    TokenRisk,
    _safe_global_mode,
    get_trading_guard,
    get_solana_anti_rug_guard,
)
from trading.config.runtime_config import (
    GlobalTradingMode,
    VenueMode,
    TradingRuntimeConfig,
    TradingRuntimeState,
    VenueConfig,
)
from trading.adapters.base import TradeRequest, TradeSide, OrderType


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons before each test."""
    import trading.guards.trading_guard as tg
    tg._trading_guard = None
    tg._solana_guard = None
    yield


@pytest.fixture
def mock_env_clean():
    """Clean environment for env-based tests."""
    with patch.dict(os.environ, {}, clear=True):
        yield


class TestEnumsAndDataclasses:
    """Test basic enums and dataclasses."""

    def test_guard_decision_status_values(self):
        """Test GuardDecisionStatus enum values."""
        assert GuardDecisionStatus.ALLOW.value == "allow"
        assert GuardDecisionStatus.SIMULATE.value == "simulate"
        assert GuardDecisionStatus.REQUIRE_CONFIRMATION.value == "require_confirmation"
        assert GuardDecisionStatus.BLOCK.value == "block"

    def test_circuit_breaker_state_values(self):
        """Test CircuitBreakerState enum values."""
        assert CircuitBreakerState.CLOSED.value == "closed"
        assert CircuitBreakerState.OPEN.value == "open"
        assert CircuitBreakerState.HALF_OPEN.value == "half_open"

    def test_guard_decision_creation(self):
        """Test GuardDecision dataclass."""
        decision = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="Test reason",
            metadata={"key": "value"}
        )
        assert decision.status == GuardDecisionStatus.ALLOW
        assert decision.reason == "Test reason"
        assert decision.metadata == {"key": "value"}

    def test_guard_decision_defaults(self):
        """Test GuardDecision default metadata."""
        decision = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Blocked"
        )
        assert decision.metadata == {}

    def test_token_risk_values(self):
        """Test TokenRisk enum values."""
        assert TokenRisk.SAFE.value == "safe"
        assert TokenRisk.LOW.value == "low"
        assert TokenRisk.MEDIUM.value == "medium"
        assert TokenRisk.HIGH.value == "high"
        assert TokenRisk.EXTREME.value == "extreme"
        assert TokenRisk.HONEYPOT.value == "honeypot"
        assert TokenRisk.RUGPULL.value == "rugpull"


class TestSafeGlobalMode:
    """Test _safe_global_mode helper."""

    def test_safe_global_mode_with_enum(self):
        """Test passing GlobalTradingMode enum."""
        result = _safe_global_mode(GlobalTradingMode.SIM)
        assert result == GlobalTradingMode.SIM

    def test_safe_global_mode_with_valid_string(self):
        """Test passing valid string value."""
        result = _safe_global_mode("live")
        assert result == GlobalTradingMode.LIVE

    def test_safe_global_mode_with_invalid_string(self):
        """Test passing invalid string defaults to SIM."""
        result = _safe_global_mode("invalid")
        assert result == GlobalTradingMode.SIM

    def test_safe_global_mode_with_none(self):
        """Test passing None defaults to SIM."""
        result = _safe_global_mode(None)
        assert result == GlobalTradingMode.SIM


class TestTradingGuardConfig:
    """Test TradingGuardConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TradingGuardConfig()
        assert config.enable_trading_suite is True
        assert config.allow_live_trades is False
        assert config.vpn_only is True
        assert config.max_notional_usd == 25_000.0
        assert config.max_memecoin_notional_usd == 2_500.0
        assert config.max_daily_loss_usd == 25_000.0
        assert config.max_per_symbol_exposure_usd == 10_000.0
        assert config.max_open_orders == 100
        assert config.allowed_venues is None
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_window_seconds == 60.0
        assert config.circuit_breaker_cooldown_seconds == 300.0
        assert config.circuit_breaker_half_open_max == 3

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TradingGuardConfig(
            enable_trading_suite=False,
            allow_live_trades=True,
            max_notional_usd=50_000.0,
            allowed_venues=frozenset({"alpaca", "coinbase"})
        )
        assert config.enable_trading_suite is False
        assert config.allow_live_trades is True
        assert config.max_notional_usd == 50_000.0
        assert config.allowed_venues == frozenset({"alpaca", "coinbase"})

    @patch.dict(os.environ, {
        "MERID_ENABLE_TRADING_SUITE": "false",
        "MERID_ALLOW_LIVE_TRADES": "true",
        "MERID_TRADING_VPN_ONLY": "false",
        "MERID_MAX_NOTIONAL_PER_TRADE_USD": "50000",
        "MERID_MAX_MEMECOIN_NOTIONAL_USD": "5000",
        "MERID_TRADING_ALLOWED_VENUES": "alpaca, coinbase, kalshi",
    })
    def test_from_env(self):
        """Test loading configuration from environment."""
        config = TradingGuardConfig.from_env()
        assert config.enable_trading_suite is False
        assert config.allow_live_trades is True
        assert config.vpn_only is False
        assert config.max_notional_usd == 50_000.0
        assert config.max_memecoin_notional_usd == 5_000.0
        assert config.allowed_venues == frozenset({"alpaca", "coinbase", "kalshi"})

    @patch.dict(os.environ, {
        "MERID_ENABLE_TRADING_SUITE": "1",
        "MERID_ALLOW_LIVE_TRADES": "yes",
        "MERID_TRADING_VPN_ONLY": "on",
    })
    def test_from_env_boolean_variations(self):
        """Test various boolean string representations."""
        config = TradingGuardConfig.from_env()
        assert config.enable_trading_suite is True
        assert config.allow_live_trades is True
        assert config.vpn_only is True

    @patch.dict(os.environ, {
        "MERID_MAX_NOTIONAL_PER_TRADE_USD": "invalid",
    })
    def test_from_env_invalid_float_defaults(self):
        """Test invalid float values default properly."""
        config = TradingGuardConfig.from_env()
        assert config.max_notional_usd == 25_000.0  # Default


class TestTradingGuardCircuitBreaker:
    """Test TradingGuard circuit breaker functionality."""

    def test_initial_state(self):
        """Test initial circuit breaker state."""
        guard = TradingGuard()
        assert guard.circuit_state == CircuitBreakerState.CLOSED
        assert guard._error_timestamps == []
        assert guard._circuit_opened_at is None
        assert guard._half_open_successes == 0

    def test_record_error_increments_count(self):
        """Test recording errors."""
        guard = TradingGuard()
        now = time.time()
        guard.record_error(now)
        assert len(guard._error_timestamps) == 1

    def test_circuit_opens_after_threshold(self):
        """Test circuit opens after error threshold."""
        guard = TradingGuard()
        guard.config.circuit_breaker_threshold = 3
        now = time.time()
        
        # Record errors up to threshold
        guard.record_error(now)
        guard.record_error(now)
        assert guard.circuit_state == CircuitBreakerState.CLOSED
        
        guard.record_error(now)
        assert guard.circuit_state == CircuitBreakerState.OPEN
        assert guard._circuit_opened_at == now

    def test_cleanup_old_errors(self):
        """Test old errors are cleaned up."""
        guard = TradingGuard()
        now = time.time()
        
        # Add old and new errors
        guard._error_timestamps = [now - 120, now - 90, now - 30]  # 60s window
        guard._cleanup_old_errors(now)
        
        assert len(guard._error_timestamps) == 1  # Only recent error remains

    def test_half_open_after_cooldown(self):
        """Test transition to half-open after cooldown."""
        guard = TradingGuard()
        guard._circuit_state = CircuitBreakerState.OPEN
        guard._circuit_opened_at = time.time() - 400  # 400s ago (> 300s cooldown)
        
        decision = guard._check_circuit_for_request(time.time())
        
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN
        assert decision is None  # Allow request in half-open

    def test_blocked_when_circuit_open(self):
        """Test requests blocked when circuit is open."""
        guard = TradingGuard()
        guard._circuit_state = CircuitBreakerState.OPEN
        guard._circuit_opened_at = time.time()  # Just opened
        
        decision = guard._check_circuit_for_request(time.time())
        
        assert decision is not None
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "circuit breaker open" in decision.reason.lower()

    def test_record_success_in_half_open(self):
        """Test recording success in half-open state."""
        guard = TradingGuard()
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard.config.circuit_breaker_half_open_max = 3
        
        guard.record_success()
        guard.record_success()
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN
        assert guard._half_open_successes == 2
        
        guard.record_success()
        assert guard.circuit_state == CircuitBreakerState.CLOSED
        assert guard._half_open_successes == 0
        assert guard._error_timestamps == []

    def test_error_in_half_open_returns_to_open(self):
        """Test error in half-open returns to open state."""
        guard = TradingGuard()
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard._half_open_successes = 2
        now = time.time()
        
        guard.record_error(now)
        
        assert guard.circuit_state == CircuitBreakerState.OPEN
        assert guard._half_open_successes == 0


class TestTradingGuardEvaluate:
    """Test TradingGuard.evaluate() method with various scenarios."""

    @pytest.fixture
    def base_request(self):
        """Create base trade request."""
        return TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=False,
        )

    @pytest.fixture
    def runtime_config_sim(self):
        """Create runtime config in SIM mode."""
        config = TradingRuntimeConfig()
        # Create a proper mock that returns the expected values
        config._state = TradingRuntimeState(
            mode=GlobalTradingMode.SIM,
            spectator_mode=True,
            allow_live_trades=False,
            venues={}
        )
        return config

    def test_trading_suite_disabled(self, base_request):
        """Test blocked when trading suite disabled."""
        config = TradingGuardConfig(enable_trading_suite=False)
        guard = TradingGuard(config=config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "disabled" in decision.reason.lower()

    def test_vpn_required_but_not_connected(self, base_request):
        """Test confirmation required when VPN not connected."""
        config = TradingGuardConfig(vpn_only=True)
        guard = TradingGuard(config=config)
        
        decision = guard.evaluate(base_request, vpn_connected=False)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "vpn" in decision.reason.lower()

    def test_venue_not_whitelisted(self, base_request):
        """Test blocked when venue not in allowed list."""
        config = TradingGuardConfig(allowed_venues=frozenset({"coinbase"}))
        guard = TradingGuard(config=config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "not whitelisted" in decision.reason.lower()

    def test_venue_disabled(self, base_request, runtime_config_sim):
        """Test blocked when venue is disabled."""
        config = TradingGuardConfig()
        guard = TradingGuard(config=config, runtime_config=runtime_config_sim)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "disabled" in decision.reason.lower()

    def test_sim_mode_returns_simulate(self, base_request):
        """Test SIMULATE decision in SIM mode."""
        config = TradingGuardConfig()
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.SIM
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.SIMULATE
        assert "sim" in decision.reason.lower()

    def test_spectator_mode_returns_simulate(self, base_request):
        """Test SIMULATE decision in spectator mode."""
        config = TradingGuardConfig()
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = True
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.SIMULATE
        assert "spectator" in decision.reason.lower()

    def test_offline_mode_returns_simulate(self, base_request):
        """Test SIMULATE decision in OFFLINE mode."""
        config = TradingGuardConfig()
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.OFFLINE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.SIMULATE

    def test_venue_paper_mode(self, base_request):
        """Test ALLOW decision in venue PAPER mode."""
        config = TradingGuardConfig()
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "paper", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        decision = guard.evaluate(base_request)
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_venue_live_mode_confirmation_required(self, base_request):
        """Test REQUIRE_CONFIRMATION for live trades when not allowed."""
        config = TradingGuardConfig(allow_live_trades=False)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = False
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        live_request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=True,
        )
        
        decision = guard.evaluate(live_request)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "live" in decision.reason.lower()

    def test_daily_loss_limit_exceeded(self, base_request):
        """Test blocked when daily loss limit exceeded."""
        config = TradingGuardConfig(max_daily_loss_usd=10_000.0)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        aggregator = MagicMock()
        aggregator.daily_pnl = -15_000.0  # Exceeds 10k limit
        
        decision = guard.evaluate(base_request, portfolio_aggregator=aggregator)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "daily loss" in decision.reason.lower()

    def test_symbol_exposure_limit(self, base_request):
        """Test blocked when symbol exposure limit exceeded."""
        config = TradingGuardConfig(max_per_symbol_exposure_usd=10_000.0)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        aggregator = MagicMock()
        aggregator.daily_pnl = 0
        aggregator.get_symbol_exposure.return_value = 8_000.0
        aggregator.open_orders_count = 0
        
        decision = guard.evaluate(base_request, portfolio_aggregator=aggregator)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "exposure" in decision.reason.lower()

    def test_max_open_orders_limit(self, base_request):
        """Test blocked when max open orders reached."""
        config = TradingGuardConfig(max_open_orders=5)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        aggregator = MagicMock()
        aggregator.daily_pnl = 0
        aggregator.get_symbol_exposure.return_value = 0
        aggregator.open_orders_count = 5  # At limit
        
        decision = guard.evaluate(base_request, portfolio_aggregator=aggregator)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "max open orders" in decision.reason.lower()

    def test_notional_exceeds_global_limit(self, base_request):
        """Test blocked when notional exceeds global limit."""
        config = TradingGuardConfig(max_notional_usd=1_000.0, allow_live_trades=True)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        # When venue is LIVE and request.live=False, it returns ALLOW before notional check
        # Need to use live=True to reach notional limits
        live_request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=True,
        )
        decision = guard.evaluate(live_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "notional" in decision.reason.lower()

    def test_memecoin_notional_limit(self, base_request):
        """Test blocked when memecoin notional exceeds limit."""
        config = TradingGuardConfig(max_memecoin_notional_usd=1_000.0, allow_live_trades=True)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        memecoin_request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=True,  # Must be live to reach notional check
            metadata={"category": "memecoin"},
        )
        
        decision = guard.evaluate(memecoin_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "memecoin" in decision.reason.lower()

    def test_venue_notional_limit(self, base_request):
        """Test blocked when notional exceeds venue limit."""
        config = TradingGuardConfig(max_notional_usd=50_000.0, allow_live_trades=True)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True, "max_notional_usd": 1_000.0})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        # When venue is LIVE and request.live=False, it returns ALLOW before venue notional check
        # Need to use live=True to reach the limit check
        live_request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=True,
        )
        decision = guard.evaluate(live_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "venue limit" in decision.reason.lower()

    def test_successful_allow(self, base_request):
        """Test successful ALLOW decision."""
        config = TradingGuardConfig(allow_live_trades=True)
        runtime_config = TradingRuntimeConfig()
        runtime_config._state.mode = GlobalTradingMode.LIVE
        runtime_config._state.spectator_mode = False
        runtime_config._state.allow_live_trades = True
        runtime_config.upsert_venue("alpaca", {"mode": "live", "enabled": True})
        guard = TradingGuard(config=config, runtime_config=runtime_config)
        
        live_request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
            live=True,
        )
        
        decision = guard.evaluate(live_request)
        
        assert decision.status == GuardDecisionStatus.ALLOW
        assert "approved" in decision.reason.lower()


class TestEstimateNotional:
    """Test _estimate_notional method."""

    def test_notional_provided_directly(self):
        """Test when notional_usd is provided."""
        guard = TradingGuard()
        request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            notional_usd=5000.0,
        )
        
        result = guard._estimate_notional(request)
        
        assert result == 5000.0

    def test_calculate_from_price_and_quantity(self):
        """Test calculation from price and quantity."""
        guard = TradingGuard()
        request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=2.0,
            price=2500.0,
        )
        
        result = guard._estimate_notional(request)
        
        assert result == 5000.0

    def test_reference_price_from_metadata(self):
        """Test using reference_price from metadata."""
        guard = TradingGuard()
        request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
            metadata={"reference_price": 3000.0}
        )
        
        result = guard._estimate_notional(request)
        
        assert result == 3000.0

    def test_returns_none_when_insufficient_data(self):
        """Test returns None when can't calculate."""
        guard = TradingGuard()
        request = TradeRequest(
            venue="alpaca",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        
        result = guard._estimate_notional(request)
        
        assert result is None


class TestSolanaAntiRugConfig:
    """Test SolanaAntiRugConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SolanaAntiRugConfig()
        assert config.min_liquidity_usd == 100_000.0
        assert config.max_token_risk == TokenRisk.MEDIUM
        assert config.require_liquidity_lock is True
        assert config.block_honeypots is True
        assert config.max_bundle_score == 0.7

    @patch.dict(os.environ, {
        "MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD": "200000",
        "MERID_SOLANA_SNIPER_MAX_RISK": "high",
        "MERID_SOLANA_REQUIRE_LOCK": "false",
        "MERID_SOLANA_BLOCK_HONEYPOTS": "0",
        "MERID_SOLANA_MAX_BUNDLE_SCORE": "0.5",
    })
    def test_from_env(self):
        """Test loading configuration from environment."""
        config = SolanaAntiRugConfig.from_env()
        assert config.min_liquidity_usd == 200_000.0
        assert config.max_token_risk == TokenRisk.HIGH
        assert config.require_liquidity_lock is False
        assert config.block_honeypots is False
        assert config.max_bundle_score == 0.5


class TestSolanaAntiRugGuard:
    """Test SolanaAntiRugGuard evaluate method."""

    @pytest.fixture
    def base_token_context(self):
        """Create base token context."""
        return {
            "token_symbol": "TEST",
            "token_address": "0x123",
            "liquidity_usd": 200_000.0,
            "token_risk": TokenRisk.LOW,
            "liquidity_locked": True,
            "honeypot": False,
            "bundle_score": 0.3,
        }

    def test_passes_all_checks(self, base_token_context):
        """Test token passes all safety checks."""
        guard = SolanaAntiRugGuard()
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_blocks_low_liquidity(self, base_token_context):
        """Test blocks token with low liquidity."""
        guard = SolanaAntiRugGuard()
        base_token_context["liquidity_usd"] = 50_000.0  # Below 100k threshold
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "liquidity" in decision.reason.lower()

    def test_requires_confirmation_missing_risk(self, base_token_context):
        """Test requires confirmation when risk analysis missing."""
        guard = SolanaAntiRugGuard()
        del base_token_context["token_risk"]
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "risk" in decision.reason.lower()

    def test_blocks_high_risk_token(self, base_token_context):
        """Test blocks high risk token."""
        guard = SolanaAntiRugGuard()
        base_token_context["token_risk"] = TokenRisk.HIGH
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "risk" in decision.reason.lower()

    def test_blocks_honeypot(self, base_token_context):
        """Test blocks honeypot token."""
        guard = SolanaAntiRugGuard()
        base_token_context["honeypot"] = True
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "honeypot" in decision.reason.lower()

    def test_requires_confirmation_unlocked_liquidity(self, base_token_context):
        """Test requires confirmation when liquidity not locked."""
        guard = SolanaAntiRugGuard()
        base_token_context["liquidity_locked"] = False
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "liquidity" in decision.reason.lower()

    def test_requires_confirmation_high_bundle_score(self, base_token_context):
        """Test requires confirmation with high bundle score."""
        guard = SolanaAntiRugGuard()
        base_token_context["bundle_score"] = 0.8  # Above 0.7 threshold
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "bundle" in decision.reason.lower()

    def test_risk_as_string(self, base_token_context):
        """Test token risk provided as string."""
        guard = SolanaAntiRugGuard()
        base_token_context["token_risk"] = "safe"
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_invalid_risk_defaults_to_high(self, base_token_context):
        """Test invalid risk value defaults to HIGH."""
        guard = SolanaAntiRugGuard()
        base_token_context["token_risk"] = "invalid_risk"
        
        decision = guard.evaluate(base_token_context)
        
        assert decision.status == GuardDecisionStatus.BLOCK


class TestSingletonFunctions:
    """Test singleton getter functions."""

    def test_get_trading_guard_singleton(self):
        """Test get_trading_guard returns singleton."""
        guard1 = get_trading_guard()
        guard2 = get_trading_guard()
        
        assert guard1 is guard2

    def test_get_solana_anti_rug_guard_singleton(self):
        """Test get_solana_anti_rug_guard returns singleton."""
        guard1 = get_solana_anti_rug_guard()
        guard2 = get_solana_anti_rug_guard()
        
        assert guard1 is guard2

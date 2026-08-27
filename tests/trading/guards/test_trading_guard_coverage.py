"""Comprehensive tests for trading/guards/trading_guard.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch
import time

from trading.guards.trading_guard import (
    GuardDecisionStatus, CircuitBreakerState, GuardDecision,
    TradingGuardConfig, TradingGuard, SolanaAntiRugConfig,
    SolanaAntiRugGuard, get_trading_guard, get_solana_anti_rug_guard,
    init_trading_guard_from_env, _safe_global_mode
)
from trading.adapters.base import TradeRequest, TradeSide
from trading.config.runtime_config import GlobalTradingMode, VenueMode


# =============================================================================
# Enum Tests
# =============================================================================

class TestGuardDecisionStatus:
    """Test GuardDecisionStatus enum."""

    def test_allow(self):
        assert GuardDecisionStatus.ALLOW.value == "allow"

    def test_simulate(self):
        assert GuardDecisionStatus.SIMULATE.value == "simulate"

    def test_require_confirmation(self):
        assert GuardDecisionStatus.REQUIRE_CONFIRMATION.value == "require_confirmation"

    def test_block(self):
        assert GuardDecisionStatus.BLOCK.value == "block"


class TestCircuitBreakerState:
    """Test CircuitBreakerState enum."""

    def test_closed(self):
        assert CircuitBreakerState.CLOSED.value == "closed"

    def test_open(self):
        assert CircuitBreakerState.OPEN.value == "open"

    def test_half_open(self):
        assert CircuitBreakerState.HALF_OPEN.value == "half_open"


# =============================================================================
# GuardDecision Dataclass Tests
# =============================================================================

class TestGuardDecision:
    """Test GuardDecision dataclass."""

    def test_creation(self):
        decision = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="Trade approved"
        )
        assert decision.status == GuardDecisionStatus.ALLOW
        assert decision.reason == "Trade approved"

    def test_with_metadata(self):
        decision = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Limit exceeded",
            metadata={"limit": 25000}
        )
        assert decision.metadata["limit"] == 25000


# =============================================================================
# SafeGlobalMode Function Tests
# =============================================================================

class TestSafeGlobalMode:
    """Test _safe_global_mode function."""

    def test_with_enum(self):
        result = _safe_global_mode(GlobalTradingMode.LIVE)
        assert result == GlobalTradingMode.LIVE

    def test_with_valid_string(self):
        result = _safe_global_mode("mock")
        assert result == GlobalTradingMode.MOCK

    def test_with_invalid_string(self):
        result = _safe_global_mode("invalid")
        assert result == GlobalTradingMode.MOCK

    def test_with_none(self):
        result = _safe_global_mode(None)
        assert result == GlobalTradingMode.MOCK


# =============================================================================
# TradingGuardConfig Tests
# =============================================================================

class TestTradingGuardConfig:
    """Test TradingGuardConfig dataclass."""

    def test_defaults(self):
        config = TradingGuardConfig()
        assert config.enable_trading_suite is True
        assert config.allow_live_trades is False
        assert config.max_notional_usd == 25_000.0

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_TRADING_SUITE", "true")
        monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "false")
        monkeypatch.setenv("MERID_MAX_NOTIONAL_PER_TRADE_USD", "50000")
        
        config = TradingGuardConfig.from_env()
        
        assert config.enable_trading_suite is True
        assert config.max_notional_usd == 50000.0

    def test_from_env_with_venues(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_ALLOWED_VENUES", "alpaca,coinbase")
        
        config = TradingGuardConfig.from_env()
        
        assert "alpaca" in config.allowed_venues
        assert "coinbase" in config.allowed_venues


# =============================================================================
# TradingGuard Tests
# =============================================================================

@pytest.fixture
def mock_runtime_config():
    """Create mock runtime config."""
    config = MagicMock()
    config.snapshot.return_value = {
        "mode": GlobalTradingMode.LIVE,
        "spectator_mode": False,
        "allow_live_trades": True
    }
    venue_cfg = MagicMock()
    venue_cfg.enabled = True
    venue_cfg.mode = VenueMode.LIVE
    venue_cfg.max_notional_usd = None
    config.get_venue.return_value = venue_cfg
    return config


@pytest.fixture
def guard(mock_runtime_config):
    """Create TradingGuard with mocks."""
    config = TradingGuardConfig(
        enable_trading_suite=True,
        allow_live_trades=True,
        vpn_only=False
    )
    return TradingGuard(config=config, runtime_config=mock_runtime_config)


@pytest.fixture
def trade_request():
    """Create sample trade request."""
    return TradeRequest(
        venue="alpaca",
        symbol="AAPL",
        side=TradeSide.BUY,
        quantity=10.0,
        price=150.0,
        live=True
    )


class TestTradingGuardInit:
    """Test TradingGuard initialization."""

    def test_defaults(self):
        with patch("trading.guards.trading_guard.get_runtime_config"):
            guard = TradingGuard()
        assert guard.circuit_state == CircuitBreakerState.CLOSED


class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    def test_initial_state(self, guard):
        assert guard.circuit_state == CircuitBreakerState.CLOSED

    def test_record_error_trips_breaker(self, guard):
        guard.config.circuit_breaker_threshold = 3
        
        for _ in range(5):
            guard.record_error()
        
        assert guard.circuit_state == CircuitBreakerState.OPEN

    def test_record_success_in_half_open(self, guard):
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard.config.circuit_breaker_half_open_max = 2
        
        guard.record_success()
        guard.record_success()
        
        assert guard.circuit_state == CircuitBreakerState.CLOSED


class TestEvaluate:
    """Test evaluate method."""

    def test_allow_trade(self, guard, trade_request):
        decision = guard.evaluate(trade_request)
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_block_disabled_suite(self, guard, trade_request):
        guard.config.enable_trading_suite = False
        
        decision = guard.evaluate(trade_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_require_confirmation_vpn(self, guard, trade_request):
        guard.config.vpn_only = True
        
        decision = guard.evaluate(trade_request, vpn_connected=False)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION

    def test_block_venue_not_whitelisted(self, guard, trade_request):
        guard.config.allowed_venues = frozenset(["coinbase"])
        
        decision = guard.evaluate(trade_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_block_venue_disabled(self, guard, trade_request, mock_runtime_config):
        venue_cfg = MagicMock()
        venue_cfg.enabled = False
        mock_runtime_config.get_venue.return_value = venue_cfg
        
        decision = guard.evaluate(trade_request)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_simulate_spectator_mode(self, guard, trade_request, mock_runtime_config):
        mock_runtime_config.snapshot.return_value = {
            "mode": GlobalTradingMode.LIVE,
            "spectator_mode": True,
            "allow_live_trades": True
        }
        
        decision = guard.evaluate(trade_request)
        
        assert decision.status == GuardDecisionStatus.SIMULATE

    def test_block_notional_exceeds_limit(self, guard):
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            live=True,
            notional_usd=50000.0
        )
        guard.config.max_notional_usd = 25000.0
        
        decision = guard.evaluate(request)
        
        assert decision.status == GuardDecisionStatus.BLOCK


# =============================================================================
# SolanaAntiRugConfig Tests
# =============================================================================

class TestSolanaAntiRugConfig:
    """Test SolanaAntiRugConfig dataclass."""

    def test_defaults(self):
        config = SolanaAntiRugConfig()
        assert config.min_liquidity_usd == 100_000.0
        assert config.block_honeypots is True

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD", "50000")
        
        config = SolanaAntiRugConfig.from_env()
        
        assert config.min_liquidity_usd == 50000.0


# =============================================================================
# SolanaAntiRugGuard Tests
# =============================================================================

@pytest.fixture
def solana_guard():
    """Create SolanaAntiRugGuard."""
    config = SolanaAntiRugConfig(
        min_liquidity_usd=50000.0,
        require_liquidity_lock=True,
        block_honeypots=True
    )
    return SolanaAntiRugGuard(config=config)


class TestSolanaAntiRugGuard:
    """Test SolanaAntiRugGuard."""

    def test_allow_safe_token(self, solana_guard):
        context = {
            "token_symbol": "SAFE",
            "liquidity_usd": 100000.0,
            "token_risk": "safe",
            "liquidity_locked": True,
            "honeypot": False
        }
        
        decision = solana_guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_block_low_liquidity(self, solana_guard):
        context = {
            "token_symbol": "LOW",
            "liquidity_usd": 10000.0
        }
        
        decision = solana_guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_block_honeypot(self, solana_guard):
        context = {
            "token_symbol": "SCAM",
            "liquidity_usd": 100000.0,
            "token_risk": "safe",
            "liquidity_locked": True,
            "honeypot": True
        }
        
        decision = solana_guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_require_confirmation_no_lock(self, solana_guard):
        context = {
            "token_symbol": "NOLOCK",
            "liquidity_usd": 100000.0,
            "token_risk": "safe",
            "liquidity_locked": False,
            "honeypot": False
        }
        
        decision = solana_guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION


# =============================================================================
# Singleton Tests
# =============================================================================

class TestSingletons:
    """Test singleton factory functions."""

    def test_get_trading_guard(self):
        import trading.guards.trading_guard as module
        module._trading_guard = None

        with patch("trading.guards.trading_guard.get_runtime_config"):
            init_trading_guard_from_env()
            guard = get_trading_guard()

        assert isinstance(guard, TradingGuard)

    def test_get_solana_anti_rug_guard(self):
        import trading.guards.trading_guard as module
        module._solana_guard = None
        
        guard = get_solana_anti_rug_guard()
        
        assert isinstance(guard, SolanaAntiRugGuard)


# =============================================================================
# Additional Coverage Tests - Circuit Breaker
# =============================================================================

class TestCircuitBreakerFull:
    """Additional circuit breaker tests for full coverage."""

    @pytest.fixture
    def guard_with_mock(self):
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {
            "mode": GlobalTradingMode.PAPER,
            "spectator_mode": False,
            "allow_live_trades": True
        }
        mock_venue = MagicMock()
        mock_venue.enabled = True
        mock_venue.mode = VenueMode.PAPER
        mock_venue.max_notional_usd = None
        mock_runtime.get_venue.return_value = mock_venue
        
        config = TradingGuardConfig(
            enable_trading_suite=True,
            vpn_only=False,
            circuit_breaker_threshold=3,
            circuit_breaker_window_seconds=60.0,
            circuit_breaker_cooldown_seconds=10.0,
            circuit_breaker_half_open_max=2
        )
        return TradingGuard(config=config, runtime_config=mock_runtime)

    def test_circuit_breaker_trips_after_threshold(self, guard_with_mock):
        now = time.time()
        for i in range(3):
            guard_with_mock.record_error(now + i)
        
        assert guard_with_mock.circuit_state == CircuitBreakerState.OPEN

    def test_circuit_breaker_cooldown_to_half_open(self, guard_with_mock):
        now = time.time()
        for i in range(3):
            guard_with_mock.record_error(now)
        
        assert guard_with_mock.circuit_state == CircuitBreakerState.OPEN
        
        guard_with_mock._circuit_opened_at = now - 15  # 15 seconds ago
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            live=False
        )
        
        decision = guard_with_mock.evaluate(request)
        
        assert guard_with_mock.circuit_state == CircuitBreakerState.HALF_OPEN

    def test_half_open_closes_after_successes(self, guard_with_mock):
        guard_with_mock._circuit_state = CircuitBreakerState.HALF_OPEN
        guard_with_mock._half_open_successes = 0
        
        guard_with_mock.record_success()
        guard_with_mock.record_success()
        
        assert guard_with_mock.circuit_state == CircuitBreakerState.CLOSED

    def test_half_open_reopens_on_error(self, guard_with_mock):
        now = time.time()
        guard_with_mock._circuit_state = CircuitBreakerState.HALF_OPEN
        guard_with_mock._half_open_successes = 1
        
        guard_with_mock.record_error(now)
        
        assert guard_with_mock.circuit_state == CircuitBreakerState.OPEN


# =============================================================================
# Additional Coverage Tests - Evaluate Paths
# =============================================================================

class TestEvaluateAllPaths:
    """Test all evaluate paths for coverage."""

    @pytest.fixture
    def configured_guard(self):
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {
            "mode": GlobalTradingMode.PAPER,
            "spectator_mode": False,
            "allow_live_trades": True
        }
        mock_venue = MagicMock()
        mock_venue.enabled = True
        mock_venue.mode = VenueMode.PAPER
        mock_venue.max_notional_usd = None
        mock_runtime.get_venue.return_value = mock_venue
        
        config = TradingGuardConfig(
            enable_trading_suite=True,
            vpn_only=False,
            max_notional_usd=25000,
            max_memecoin_notional_usd=2500,
            max_daily_loss_usd=25000,
            max_per_symbol_exposure_usd=10000,
            max_open_orders=100
        )
        return TradingGuard(config=config, runtime_config=mock_runtime)

    def test_daily_loss_limit_exceeded(self, configured_guard):
        mock_portfolio = MagicMock()
        mock_portfolio.daily_pnl = -30000  # Exceeds limit
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            live=False
        )
        
        decision = configured_guard.evaluate(request, portfolio_aggregator=mock_portfolio)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Daily loss" in decision.reason

    def test_symbol_exposure_limit_exceeded(self, configured_guard):
        mock_portfolio = MagicMock()
        mock_portfolio.daily_pnl = 0
        mock_portfolio.get_symbol_exposure.return_value = 9000
        mock_portfolio.open_orders_count = 5
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100.0,
            price=150.0,  # 15000 notional
            live=False,
            notional_usd=15000.0
        )
        
        decision = configured_guard.evaluate(request, portfolio_aggregator=mock_portfolio)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "symbol exposure" in decision.reason

    def test_max_open_orders_exceeded(self, configured_guard):
        mock_portfolio = MagicMock()
        mock_portfolio.daily_pnl = 0
        mock_portfolio.get_symbol_exposure.return_value = 0
        mock_portfolio.open_orders_count = 100
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            live=False
        )
        
        decision = configured_guard.evaluate(request, portfolio_aggregator=mock_portfolio)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "open orders" in decision.reason

    def test_venue_live_mode_request_paper(self, configured_guard):
        configured_guard.runtime_config.get_venue.return_value.mode = VenueMode.LIVE
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            live=False  # Request paper
        )
        
        decision = configured_guard.evaluate(request)
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_venue_notional_limit_exceeded(self, configured_guard):
        configured_guard.runtime_config.get_venue.return_value.max_notional_usd = 1000
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100.0,
            price=150.0,
            live=False,
            notional_usd=15000.0
        )
        
        decision = configured_guard.evaluate(request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "venue limit" in decision.reason

    def test_memecoin_limit_exceeded(self, configured_guard):
        request = TradeRequest(
            venue="alpaca",
            symbol="MEME",
            side=TradeSide.BUY,
            quantity=100.0,
            price=50.0,
            live=False,
            notional_usd=5000.0,
            metadata={"category": "memecoin"}
        )
        
        decision = configured_guard.evaluate(request)
        
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Memecoin" in decision.reason


# =============================================================================
# Additional Coverage Tests - SolanaAntiRugGuard
# =============================================================================

class TestSolanaGuardFullCoverage:
    """Additional SolanaAntiRugGuard tests."""

    def test_missing_token_risk(self):
        guard = SolanaAntiRugGuard(SolanaAntiRugConfig(min_liquidity_usd=1000))
        context = {
            "liquidity_usd": 5000,
            "token_risk": None
        }
        
        decision = guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION

    def test_invalid_token_risk_string(self):
        guard = SolanaAntiRugGuard(SolanaAntiRugConfig(min_liquidity_usd=1000))
        context = {
            "liquidity_usd": 5000,
            "token_risk": "invalid_risk_level",
            "liquidity_locked": True,
            "honeypot": False
        }
        
        decision = guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_high_risk_blocked(self):
        from trading.guards.trading_guard import TokenRisk
        guard = SolanaAntiRugGuard(SolanaAntiRugConfig(
            min_liquidity_usd=1000,
            max_token_risk=TokenRisk.MEDIUM
        ))
        context = {
            "liquidity_usd": 5000,
            "token_risk": "high",
            "liquidity_locked": True,
            "honeypot": False
        }
        
        decision = guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_bundle_score_threshold(self):
        guard = SolanaAntiRugGuard(SolanaAntiRugConfig(
            min_liquidity_usd=1000,
            max_bundle_score=0.5,
            require_liquidity_lock=False
        ))
        context = {
            "liquidity_usd": 5000,
            "token_risk": "safe",
            "liquidity_locked": True,
            "honeypot": False,
            "bundle_score": 0.8
        }
        
        decision = guard.evaluate(context)
        
        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION


# =============================================================================
# Additional Coverage Tests - Config from_env
# =============================================================================

class TestConfigFromEnv:
    """Test config from_env methods."""

    def test_trading_guard_config_from_env_venues(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_ALLOWED_VENUES", "alpaca,coinbase")
        
        config = TradingGuardConfig.from_env()
        
        assert "alpaca" in config.allowed_venues
        assert "coinbase" in config.allowed_venues

    def test_solana_config_from_env_full(self, monkeypatch):
        monkeypatch.setenv("MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD", "75000")
        monkeypatch.setenv("MERID_SOLANA_SNIPER_MAX_RISK", "low")
        monkeypatch.setenv("MERID_SOLANA_REQUIRE_LOCK", "false")
        monkeypatch.setenv("MERID_SOLANA_BLOCK_HONEYPOTS", "false")
        monkeypatch.setenv("MERID_SOLANA_MAX_BUNDLE_SCORE", "0.5")
        
        config = SolanaAntiRugConfig.from_env()
        
        assert config.min_liquidity_usd == 75000.0
        assert config.require_liquidity_lock is False
        assert config.block_honeypots is False
        assert config.max_bundle_score == 0.5

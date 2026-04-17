"""Tests for TradingGuard and SolanaAntiRugGuard - Coverage Improvement."""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from trading.guards.trading_guard import (
    TradingGuard, TradingGuardConfig, GuardDecision, GuardDecisionStatus,
    CircuitBreakerState, SolanaAntiRugGuard, SolanaAntiRugConfig,
    _safe_global_mode, get_trading_guard, get_solana_anti_rug_guard,
    TokenRisk
)
from trading.config.runtime_config import GlobalTradingMode, VenueMode


@dataclass
class MockTradeRequest:
    """Mock trade request for testing."""
    venue: str = "coinbase"
    symbol: str = "BTC-USD"
    quantity: float = 1.0
    price: float = 45000.0
    notional_usd: float = None
    live: bool = False
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MockPortfolioAggregator:
    """Mock portfolio aggregator for testing."""
    def __init__(self, daily_pnl=0, symbol_exposure=0, open_orders=0):
        self.daily_pnl = daily_pnl
        self._symbol_exposure = symbol_exposure
        self.open_orders_count = open_orders

    def get_symbol_exposure(self, symbol):
        return self._symbol_exposure


class TestSafeGlobalMode:
    """Tests for _safe_global_mode function."""

    def test_with_enum_value(self):
        """Test passing GlobalTradingMode enum."""
        result = _safe_global_mode(GlobalTradingMode.LIVE)
        assert result == GlobalTradingMode.LIVE

    def test_with_valid_string(self):
        """Test passing valid string."""
        result = _safe_global_mode("live")
        assert result == GlobalTradingMode.LIVE

    def test_with_invalid_string(self):
        """Test passing invalid string returns MOCK."""
        result = _safe_global_mode("invalid")
        assert result == GlobalTradingMode.MOCK

    def test_with_none(self):
        """Test passing None returns MOCK."""
        result = _safe_global_mode(None)
        assert result == GlobalTradingMode.MOCK


class TestTradingGuardConfig:
    """Tests for TradingGuardConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        cfg = TradingGuardConfig()
        assert cfg.enable_trading_suite is True
        assert cfg.allow_live_trades is False
        assert cfg.vpn_only is True
        assert cfg.max_notional_usd == 25000.0
        assert cfg.max_daily_loss_usd == 25000.0
        assert cfg.circuit_breaker_threshold == 5

    def test_from_env_defaults(self):
        """Test loading from environment with defaults."""
        with patch.dict('os.environ', {}, clear=True):
            cfg = TradingGuardConfig.from_env()
            assert cfg.enable_trading_suite is True
            assert cfg.allow_live_trades is False

    def test_from_env_custom_values(self):
        """Test loading from environment with custom values."""
        env = {
            "MERID_ENABLE_TRADING_SUITE": "false",
            "MERID_ALLOW_LIVE_TRADES": "true",
            "MERID_MAX_NOTIONAL_PER_TRADE_USD": "50000",
        }
        with patch.dict('os.environ', env, clear=True):
            cfg = TradingGuardConfig.from_env()
            assert cfg.enable_trading_suite is False
            assert cfg.allow_live_trades is True
            assert cfg.max_notional_usd == 50000.0


class TestTradingGuardInitialization:
    """Tests for TradingGuard initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        guard = TradingGuard()
        assert guard.config is not None
        assert guard.circuit_state == CircuitBreakerState.CLOSED
        assert guard._error_timestamps == []

    def test_custom_config(self):
        """Test with custom config."""
        cfg = TradingGuardConfig(max_notional_usd=10000)
        guard = TradingGuard(config=cfg)
        assert guard.config.max_notional_usd == 10000


class TestTradingGuardCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_initial_state(self):
        """Test initial circuit state."""
        guard = TradingGuard()
        assert guard.circuit_state == CircuitBreakerState.CLOSED

    def test_record_error(self):
        """Test recording errors."""
        guard = TradingGuard()
        guard.record_error(timestamp=1000.0)
        assert len(guard._error_timestamps) == 1

    def test_circuit_opens_on_threshold(self):
        """Test circuit opens when error threshold reached."""
        guard = TradingGuard()
        guard.config.circuit_breaker_threshold = 3

        # Record 3 errors
        for i in range(3):
            guard.record_error(timestamp=1000.0 + i)

        assert guard.circuit_state == CircuitBreakerState.OPEN
        assert guard._circuit_opened_at is not None

    def test_circuit_cooldown_to_half_open(self):
        """Test circuit transitions to half-open after cooldown."""
        guard = TradingGuard()
        guard.config.circuit_breaker_threshold = 1
        guard.config.circuit_breaker_cooldown_seconds = 60.0

        # Open the circuit
        guard.record_error(timestamp=1000.0)
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Check after cooldown
        now = 1061.0  # 61 seconds later
        decision = guard._check_circuit_for_request(now)
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN
        assert decision is None  # Allow request in half-open

    def test_half_open_to_closed_on_success(self):
        """Test circuit closes after enough successes in half-open."""
        guard = TradingGuard()
        guard.config.circuit_breaker_half_open_max = 3

        # Force half-open state
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard._half_open_successes = 0

        # Record 3 successes
        for _ in range(3):
            guard.record_success()

        assert guard.circuit_state == CircuitBreakerState.CLOSED

    def test_half_open_back_to_open_on_error(self):
        """Test circuit returns to open on error in half-open."""
        guard = TradingGuard()
        guard._circuit_state = CircuitBreakerState.HALF_OPEN
        guard._half_open_successes = 1

        guard.record_error(timestamp=1000.0)

        assert guard.circuit_state == CircuitBreakerState.OPEN
        assert guard._half_open_successes == 0

    def test_cleanup_old_errors(self):
        """Test old errors are cleaned up."""
        guard = TradingGuard()
        guard.config.circuit_breaker_window_seconds = 60.0

        # Add old and new errors (at or past cutoff)
        guard._error_timestamps = [900.0, 950.0, 1000.0]  # 100s, 50s, 0s old
        guard._cleanup_old_errors(now=1000.0)

        # Should keep only errors within 60s window
        assert len(guard._error_timestamps) <= 2  # 950 and 1000


class TestTradingGuardEvaluate:
    """Tests for TradingGuard.evaluate method."""

    def test_trading_suite_disabled(self):
        """Test blocked when trading suite disabled."""
        cfg = TradingGuardConfig(enable_trading_suite=False)
        guard = TradingGuard(config=cfg)

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "disabled" in decision.reason.lower()

    def test_vpn_required_not_connected(self):
        """Test confirmation required when VPN not connected."""
        cfg = TradingGuardConfig(vpn_only=True)
        guard = TradingGuard(config=cfg)

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=False)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "VPN" in decision.reason

    def test_venue_not_whitelisted(self):
        """Test blocked when venue not in whitelist."""
        cfg = TradingGuardConfig(allowed_venues=frozenset({"coinbase"}))
        guard = TradingGuard(config=cfg)

        request = MockTradeRequest(venue="unauthorized")
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "not whitelisted" in decision.reason

    def test_venue_disabled(self):
        """Test blocked when venue disabled in runtime config."""
        guard = TradingGuard()

        # Mock runtime config to return disabled venue
        mock_runtime = MagicMock()
        mock_runtime.get_venue.return_value = None
        guard.runtime_config = mock_runtime

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK

    def test_daily_loss_limit_exceeded(self):
        """Test blocked when daily loss exceeded."""
        cfg = TradingGuardConfig(max_daily_loss_usd=10000)
        guard = TradingGuard(config=cfg)

        # Mock runtime config to enable venue
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        portfolio = MockPortfolioAggregator(daily_pnl=-15000)
        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "loss limit" in decision.reason.lower()

    def test_symbol_exposure_limit(self):
        """Test blocked when symbol exposure would exceed limit."""
        cfg = TradingGuardConfig(max_per_symbol_exposure_usd=10000)
        guard = TradingGuard(config=cfg)

        # Mock runtime config to enable venue
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        portfolio = MockPortfolioAggregator(symbol_exposure=8000)
        request = MockTradeRequest(notional_usd=5000)
        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "exposure limit" in decision.reason.lower()

    def test_max_open_orders_limit(self):
        """Test blocked when max open orders reached."""
        cfg = TradingGuardConfig(max_open_orders=5, max_per_symbol_exposure_usd=100000)
        guard = TradingGuard(config=cfg)

        # Mock runtime config to enable venue
        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False, "allow_live_trades": True}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        portfolio = MockPortfolioAggregator(open_orders=5)
        request = MockTradeRequest(notional_usd=1000)
        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "max open orders" in decision.reason.lower()

    def test_global_offline_mode(self):
        """Test simulate mode when global mode is OFFLINE."""
        guard = TradingGuard()

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "offline"}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.SIMULATE

    def test_spectator_mode(self):
        """Test simulate mode when spectator mode enabled."""
        guard = TradingGuard()

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": True}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.SIMULATE

    def test_venue_sim_mode(self):
        """Test simulate mode when venue in SIM mode."""
        guard = TradingGuard()

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.SIM)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest()
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.SIMULATE

    def test_venue_paper_mode(self):
        """Test allow in paper mode."""
        guard = TradingGuard()

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.PAPER)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest(live=True)
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.ALLOW

    def test_live_trades_disabled(self):
        """Test confirmation required when live trades disabled."""
        cfg = TradingGuardConfig(allow_live_trades=False)
        guard = TradingGuard(config=cfg)

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {
            "mode": "live",
            "spectator_mode": False,
            "allow_live_trades": False
        }
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest(live=True)
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION

    def test_notional_exceeds_global_limit(self):
        """Test blocked when notional exceeds global limit."""
        cfg = TradingGuardConfig(max_notional_usd=10000, allow_live_trades=True)
        guard = TradingGuard(config=cfg)

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False, "allow_live_trades": True}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest(notional_usd=15000, live=True)
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK

    def test_memecoin_limit(self):
        """Test blocked when memecoin notional exceeds limit."""
        cfg = TradingGuardConfig(max_memecoin_notional_usd=1000, allow_live_trades=True)
        guard = TradingGuard(config=cfg)

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {"mode": "live", "spectator_mode": False, "allow_live_trades": True}
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest(notional_usd=2000, metadata={"category": "memecoin"}, live=True)
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK

    def test_approved(self):
        """Test approval under normal conditions."""
        cfg = TradingGuardConfig(allow_live_trades=True, max_notional_usd=50000)
        guard = TradingGuard(config=cfg)

        mock_runtime = MagicMock()
        mock_runtime.snapshot.return_value = {
            "mode": "live",
            "spectator_mode": False,
            "allow_live_trades": True
        }
        mock_runtime.get_venue.return_value = MagicMock(enabled=True, mode=VenueMode.LIVE, max_notional_usd=None)
        guard.runtime_config = mock_runtime

        request = MockTradeRequest(live=True, notional_usd=10000)
        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestTradingGuardEstimateNotional:
    """Tests for _estimate_notional method."""

    def test_from_notional_usd(self):
        """Test using notional_usd field directly."""
        guard = TradingGuard()
        request = MockTradeRequest(notional_usd=5000)
        result = guard._estimate_notional(request)
        assert result == 5000

    def test_from_price_and_quantity(self):
        """Test calculating from price and quantity."""
        guard = TradingGuard()
        request = MockTradeRequest(price=100, quantity=10)
        result = guard._estimate_notional(request)
        assert result == 1000

    def test_from_metadata_reference_price(self):
        """Test using reference_price from metadata."""
        guard = TradingGuard()
        # Override default price so reference_price is used
        request = MockTradeRequest(price=None, quantity=5, metadata={"reference_price": 200})
        result = guard._estimate_notional(request)
        assert result == 1000

    def test_no_price_available(self):
        """Test returns None when no price available."""
        guard = TradingGuard()
        request = MockTradeRequest(price=None, quantity=10)
        result = guard._estimate_notional(request)
        assert result is None


class TestSolanaAntiRugConfig:
    """Tests for SolanaAntiRugConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        cfg = SolanaAntiRugConfig()
        assert cfg.min_liquidity_usd == 100_000.0
        assert cfg.max_token_risk == TokenRisk.MEDIUM
        assert cfg.require_liquidity_lock is True
        assert cfg.block_honeypots is True

    def test_from_env_defaults(self):
        """Test loading from environment with defaults."""
        with patch.dict('os.environ', {}, clear=True):
            cfg = SolanaAntiRugConfig.from_env()
            assert cfg.min_liquidity_usd == 100_000.0

    def test_from_env_custom_values(self):
        """Test loading custom environment values."""
        env = {
            "MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD": "50000",
            "MERID_SOLANA_SNIPER_MAX_RISK": "high",
            "MERID_SOLANA_REQUIRE_LOCK": "false",
        }
        with patch.dict('os.environ', env, clear=True):
            cfg = SolanaAntiRugConfig.from_env()
            assert cfg.min_liquidity_usd == 50000.0
            assert cfg.max_token_risk == TokenRisk.HIGH
            assert cfg.require_liquidity_lock is False


class TestSolanaAntiRugGuard:
    """Tests for SolanaAntiRugGuard."""

    def test_low_liquidity_blocked(self):
        """Test blocked when liquidity below threshold."""
        cfg = SolanaAntiRugConfig(min_liquidity_usd=100_000)
        guard = SolanaAntiRugGuard(config=cfg)

        context = {"liquidity_usd": 50_000}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Liquidity below" in decision.reason

    def test_missing_token_risk(self):
        """Test requires approval when token risk missing."""
        guard = SolanaAntiRugGuard()

        context = {"liquidity_usd": 200_000, "token_risk": None}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION

    def test_high_risk_blocked(self):
        """Test blocked when token risk too high."""
        cfg = SolanaAntiRugConfig(max_token_risk=TokenRisk.MEDIUM)
        guard = SolanaAntiRugGuard(config=cfg)

        context = {"liquidity_usd": 200_000, "token_risk": TokenRisk.HIGH}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.BLOCK

    def test_extreme_risk_blocked(self):
        """Test blocked for extreme risk."""
        guard = SolanaAntiRugGuard()

        context = {"liquidity_usd": 200_000, "token_risk": TokenRisk.EXTREME}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.BLOCK

    def test_honeypot_blocked(self):
        """Test blocked when honeypot detected."""
        guard = SolanaAntiRugGuard()

        context = {"liquidity_usd": 200_000, "token_risk": TokenRisk.LOW, "honeypot": True}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Honeypot" in decision.reason

    def test_liquidity_not_locked(self):
        """Test requires approval when liquidity not locked."""
        cfg = SolanaAntiRugConfig(require_liquidity_lock=True)
        guard = SolanaAntiRugGuard(config=cfg)

        context = {"liquidity_usd": 200_000, "token_risk": TokenRisk.LOW, "liquidity_locked": False}
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION

    def test_bundle_score_too_high(self):
        """Test requires approval when bundle score too high."""
        cfg = SolanaAntiRugConfig(max_bundle_score=0.5)
        guard = SolanaAntiRugGuard(config=cfg)

        context = {
            "liquidity_usd": 200_000,
            "token_risk": TokenRisk.LOW,
            "liquidity_locked": True,
            "bundle_score": 0.8
        }
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "bundle" in decision.reason.lower()

    def test_approved(self):
        """Test approval when all checks pass."""
        guard = SolanaAntiRugGuard()

        context = {
            "liquidity_usd": 200_000,
            "token_risk": TokenRisk.LOW,
            "liquidity_locked": True,
            "bundle_score": 0.3
        }
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.ALLOW

    def test_token_risk_as_string(self):
        """Test handling token risk as string."""
        guard = SolanaAntiRugGuard()

        context = {
            "liquidity_usd": 200_000,
            "token_risk": "low",
            "liquidity_locked": True
        }
        decision = guard.evaluate(context)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestGetters:
    """Tests for singleton getter functions."""

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

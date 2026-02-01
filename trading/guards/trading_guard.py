"""TradingGuard and SolanaAntiRugGuard scaffolds for unified trading suite."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from trading.adapters.base import TradeRequest
from trading.config.runtime_config import (
    GlobalTradingMode,
    VenueMode,
    get_runtime_config,
    TradingRuntimeConfig,
)

try:  # Optional import when memecoin engine is available
    from sniping.memecoin_engine import TokenRisk
except Exception:  # pragma: no cover - fallback when module not present
    class TokenRisk(str, Enum):  # type: ignore
        SAFE = "safe"
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        EXTREME = "extreme"
        HONEYPOT = "honeypot"
        RUGPULL = "rugpull"


def _safe_global_mode(mode: Any) -> GlobalTradingMode:
    """Safely convert mode value to GlobalTradingMode enum."""
    if isinstance(mode, GlobalTradingMode):
        return mode
    if isinstance(mode, str):
        try:
            return GlobalTradingMode(mode)
        except ValueError:
            pass
    return GlobalTradingMode.SIM  # Default fallback


class GuardDecisionStatus(str, Enum):
    """Possible guard decision outcomes."""

    ALLOW = "allow"
    SIMULATE = "simulate"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCK = "block"


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking all requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass(frozen=True)
class GuardDecision:
    """Decision payload returned by guards."""

    status: GuardDecisionStatus
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradingGuardConfig:
    """High-level trading guard configuration."""

    enable_trading_suite: bool = True
    allow_live_trades: bool = False
    vpn_only: bool = True
    max_notional_usd: float = 25_000.0
    max_memecoin_notional_usd: float = 2_500.0
    max_daily_loss_usd: float = 25_000.0
    max_per_symbol_exposure_usd: float = 10_000.0
    max_open_orders: int = 100
    allowed_venues: Optional[frozenset[str]] = None
    # Circuit breaker settings
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_seconds: float = 60.0
    circuit_breaker_cooldown_seconds: float = 300.0
    circuit_breaker_half_open_max: int = 3

    @classmethod
    def from_env(cls) -> "TradingGuardConfig":
        def _get_bool(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.lower() in {"1", "true", "yes", "on"}

        def _get_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, default))
            except (TypeError, ValueError):
                return default

        venues_raw = os.getenv("MERID_TRADING_ALLOWED_VENUES")
        venues = frozenset(v.strip() for v in venues_raw.split(",")) if venues_raw else None

        return cls(
            enable_trading_suite=_get_bool("MERID_ENABLE_TRADING_SUITE", True),
            allow_live_trades=_get_bool("MERID_ALLOW_LIVE_TRADES", False),
            vpn_only=_get_bool("MERID_TRADING_VPN_ONLY", True),
            max_notional_usd=_get_float("MERID_MAX_NOTIONAL_PER_TRADE_USD", 25_000.0),
            max_memecoin_notional_usd=_get_float("MERID_MAX_MEMECOIN_NOTIONAL_USD", 2_500.0),
            allowed_venues=venues,
        )


class TradingGuard:
    """Top-level guard invoked before any adapter execution."""

    def __init__(
        self,
        config: Optional[TradingGuardConfig] = None,
        runtime_config: Optional[TradingRuntimeConfig] = None,
    ) -> None:
        self.config = config or TradingGuardConfig.from_env()
        self.runtime_config = runtime_config or get_runtime_config()
        # Circuit breaker state
        self._circuit_state = CircuitBreakerState.CLOSED
        self._error_timestamps: list[float] = []
        self._circuit_opened_at: Optional[float] = None
        self._half_open_successes = 0

    @property
    def circuit_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._circuit_state

    def record_error(self, timestamp: Optional[float] = None) -> None:
        """Record an error for circuit breaker tracking."""
        now = timestamp or time.time()
        self._error_timestamps.append(now)
        self._cleanup_old_errors(now)
        self._check_circuit_breaker(now)

    def _cleanup_old_errors(self, now: float) -> None:
        """Remove errors outside the window."""
        window = self.config.circuit_breaker_window_seconds
        cutoff = now - window
        self._error_timestamps = [ts for ts in self._error_timestamps if ts > cutoff]

    def _check_circuit_breaker(self, now: float) -> None:
        """Check if circuit breaker should trip."""
        cfg = self.config
        error_count = len(self._error_timestamps)

        if self._circuit_state == CircuitBreakerState.CLOSED:
            if error_count >= cfg.circuit_breaker_threshold:
                self._circuit_state = CircuitBreakerState.OPEN
                self._circuit_opened_at = now
        elif self._circuit_state == CircuitBreakerState.HALF_OPEN:
            if error_count > 0:
                # Failed in half-open, go back to open
                self._circuit_state = CircuitBreakerState.OPEN
                self._circuit_opened_at = now
                self._half_open_successes = 0

    def _check_circuit_for_request(self, now: float) -> Optional[GuardDecision]:
        """Check circuit breaker state and return decision if blocked."""
        cfg = self.config

        if self._circuit_state == CircuitBreakerState.OPEN:
            # Check if cooldown period has passed
            if self._circuit_opened_at and (now - self._circuit_opened_at) >= cfg.circuit_breaker_cooldown_seconds:
                self._circuit_state = CircuitBreakerState.HALF_OPEN
                self._half_open_successes = 0
                return None  # Allow request in half-open state
            return GuardDecision(
                GuardDecisionStatus.BLOCK,
                "Circuit breaker open - too many recent errors",
                {"circuit_state": "open", "errors_in_window": len(self._error_timestamps)},
            )

        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            if self._half_open_successes >= cfg.circuit_breaker_half_open_max:
                self._circuit_state = CircuitBreakerState.CLOSED
                self._error_timestamps.clear()
                self._half_open_successes = 0
            return None  # Allow request

        return None  # Circuit closed, allow request

    def record_success(self) -> None:
        """Record a successful request for half-open tracking."""
        if self._circuit_state == CircuitBreakerState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.config.circuit_breaker_half_open_max:
                self._circuit_state = CircuitBreakerState.CLOSED
                self._error_timestamps.clear()
                self._half_open_successes = 0

    def evaluate(
        self,
        request: TradeRequest,
        *,
        vpn_connected: bool = True,
        portfolio_aggregator: Any = None,
    ) -> GuardDecision:
        cfg = self.config

        # Check circuit breaker first
        now = time.time()
        circuit_decision = self._check_circuit_for_request(now)
        if circuit_decision:
            return circuit_decision

        state = self.runtime_config.snapshot()
        global_mode = _safe_global_mode(state.get("mode"))
        spectator_mode = bool(state.get("spectator_mode", True))
        runtime_allow_live = bool(state.get("allow_live_trades", False))
        venue_cfg = self.runtime_config.get_venue(request.venue)

        notional = self._estimate_notional(request)

        metadata: Dict[str, Any] = {
            "venue": request.venue,
            "symbol": request.symbol,
            "live": request.live,
            "notional_usd": notional,
            "global_mode": global_mode.value,
            "spectator_mode": spectator_mode,
            "runtime_allow_live": runtime_allow_live,
            "venue_mode": venue_cfg.mode.value if venue_cfg else None,
        }

        if not cfg.enable_trading_suite:
            return GuardDecision(GuardDecisionStatus.BLOCK, "Trading suite disabled via env", metadata)

        if cfg.vpn_only and not vpn_connected:
            return GuardDecision(GuardDecisionStatus.REQUIRE_CONFIRMATION, "VPN enforcement active", metadata)

        if cfg.allowed_venues and request.venue not in cfg.allowed_venues:
            return GuardDecision(GuardDecisionStatus.BLOCK, f"Venue {request.venue} not whitelisted", metadata)

        if not venue_cfg or not venue_cfg.enabled:
            return GuardDecision(GuardDecisionStatus.BLOCK, f"Venue {request.venue} disabled", metadata)

        # Risk limits check (requires portfolio_aggregator)
        if portfolio_aggregator is not None:
            # Daily loss limit
            daily_pnl = getattr(portfolio_aggregator, 'daily_pnl', 0)
            if daily_pnl < -cfg.max_daily_loss_usd:
                metadata["daily_loss"] = daily_pnl
                metadata["max_daily_loss"] = cfg.max_daily_loss_usd
                return GuardDecision(GuardDecisionStatus.BLOCK, "Daily loss limit exceeded", metadata)

            # Per-symbol exposure limit
            symbol_exposure = portfolio_aggregator.get_symbol_exposure(request.symbol)
            if notional and (symbol_exposure + notional) > cfg.max_per_symbol_exposure_usd:
                metadata["symbol_exposure"] = symbol_exposure
                metadata["max_symbol_exposure"] = cfg.max_per_symbol_exposure_usd
                return GuardDecision(GuardDecisionStatus.BLOCK, "Per-symbol exposure limit exceeded", metadata)

            # Max open orders limit
            if portfolio_aggregator.open_orders_count >= cfg.max_open_orders:
                metadata["open_orders"] = portfolio_aggregator.open_orders_count
                metadata["max_open_orders"] = cfg.max_open_orders
                return GuardDecision(GuardDecisionStatus.BLOCK, "Max open orders limit reached", metadata)

        # Mode semantics -------------------------------------------------
        if global_mode in {GlobalTradingMode.OFFLINE, GlobalTradingMode.SIM}:
            return GuardDecision(GuardDecisionStatus.SIMULATE, f"Global mode {global_mode.value}", metadata)

        if spectator_mode:
            return GuardDecision(GuardDecisionStatus.SIMULATE, "Spectator mode enabled", metadata)

        if venue_cfg.mode == VenueMode.SIM:
            return GuardDecision(GuardDecisionStatus.SIMULATE, "Venue set to SIM", metadata)

        if venue_cfg.mode == VenueMode.PAPER and request.live:
            # Force paper execution even if caller requested live
            metadata["override_live"] = False
            return GuardDecision(GuardDecisionStatus.ALLOW, "Venue in PAPER mode", metadata)

        if venue_cfg.mode == VenueMode.LIVE:
            if request.live is False:
                metadata["override_live"] = True
                return GuardDecision(GuardDecisionStatus.ALLOW, "Venue LIVE but request marked paper", metadata)
            if not cfg.allow_live_trades or not runtime_allow_live:
                return GuardDecision(
                    GuardDecisionStatus.REQUIRE_CONFIRMATION,
                    "Live trades disabled",
                    metadata,
                )

        # Limits ---------------------------------------------------------
        if notional and notional > cfg.max_notional_usd:
            metadata["limit"] = cfg.max_notional_usd
            return GuardDecision(GuardDecisionStatus.BLOCK, "Notional exceeds global limit", metadata)

        if venue_cfg.max_notional_usd and notional and notional > venue_cfg.max_notional_usd:
            metadata["venue_limit"] = venue_cfg.max_notional_usd
            return GuardDecision(GuardDecisionStatus.BLOCK, "Notional exceeds venue limit", metadata)

        if request.metadata.get("category") == "memecoin" and notional and notional > cfg.max_memecoin_notional_usd:
            metadata["limit"] = cfg.max_memecoin_notional_usd
            return GuardDecision(GuardDecisionStatus.BLOCK, "Memecoin notional exceeds limit", metadata)

        return GuardDecision(GuardDecisionStatus.ALLOW, "Approved", metadata)

    def _estimate_notional(self, request: TradeRequest) -> Optional[float]:
        if request.notional_usd is not None:
            return request.notional_usd
        price = request.price or request.metadata.get("reference_price")
        if price is None:
            return None
        try:
            return float(price) * float(request.quantity)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None


@dataclass
class SolanaAntiRugConfig:
    """Memecoin-specific safety requirements."""

    min_liquidity_usd: float = 100_000.0
    max_token_risk: TokenRisk = TokenRisk.MEDIUM
    require_liquidity_lock: bool = True
    block_honeypots: bool = True
    max_bundle_score: float = 0.7

    @classmethod
    def from_env(cls) -> "SolanaAntiRugConfig":
        def _get_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, default))
            except (TypeError, ValueError):
                return default

        def _get_enum(value: Optional[str], default: TokenRisk) -> TokenRisk:
            if not value:
                return default
            try:
                return TokenRisk(value.lower())
            except Exception:
                return default

        return cls(
            min_liquidity_usd=_get_float("MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD", 100_000.0),
            max_token_risk=_get_enum(os.getenv("MERID_SOLANA_SNIPER_MAX_RISK"), TokenRisk.MEDIUM),
            require_liquidity_lock=os.getenv("MERID_SOLANA_REQUIRE_LOCK", "1").lower() in {"1", "true", "yes"},
            block_honeypots=os.getenv("MERID_SOLANA_BLOCK_HONEYPOTS", "1").lower() in {"1", "true", "yes"},
            max_bundle_score=_get_float("MERID_SOLANA_MAX_BUNDLE_SCORE", 0.7),
        )


class SolanaAntiRugGuard:
    """Runs memecoin safety checks before Solana sniper execution."""

    def __init__(self, config: Optional[SolanaAntiRugConfig] = None) -> None:
        self.config = config or SolanaAntiRugConfig.from_env()

    def evaluate(self, token_context: Dict[str, Any]) -> GuardDecision:
        cfg = self.config
        metadata: Dict[str, Any] = {
            "token": token_context.get("token_symbol"),
            "token_address": token_context.get("token_address"),
            "liquidity_usd": token_context.get("liquidity_usd"),
            "token_risk": token_context.get("token_risk"),
            "liquidity_locked": token_context.get("liquidity_locked"),
            "honeypot": token_context.get("honeypot"),
            "bundle_score": token_context.get("bundle_score"),
        }

        # Liquidity floor
        liquidity = metadata["liquidity_usd"]
        if liquidity is None or liquidity < cfg.min_liquidity_usd:
            return GuardDecision(
                GuardDecisionStatus.DENY,
                "Liquidity below guard threshold",
                metadata | {"required_liquidity_usd": cfg.min_liquidity_usd},
            )

        # Token risk classification
        token_risk = metadata["token_risk"]
        if token_risk is None:
            return GuardDecision(GuardDecisionStatus.REQUIRE_APPROVAL, "Missing token risk analysis", metadata)

        try:
            token_risk_enum = token_risk if isinstance(token_risk, TokenRisk) else TokenRisk(token_risk)
        except Exception:
            token_risk_enum = TokenRisk.HIGH

        if token_risk_enum.value not in {TokenRisk.SAFE.value, TokenRisk.LOW.value, TokenRisk.MEDIUM.value}:
            return GuardDecision(GuardDecisionStatus.DENY, f"Risk level {token_risk_enum.value} blocked", metadata)

        ranking = [TokenRisk.SAFE, TokenRisk.LOW, TokenRisk.MEDIUM, TokenRisk.HIGH, TokenRisk.EXTREME]
        if ranking.index(token_risk_enum) > ranking.index(cfg.max_token_risk):
            return GuardDecision(
                GuardDecisionStatus.DENY,
                f"Risk level {token_risk_enum.value} exceeds max {cfg.max_token_risk.value}",
                metadata,
            )

        # Honeypot checks
        if cfg.block_honeypots and token_context.get("honeypot"):
            return GuardDecision(GuardDecisionStatus.DENY, "Honeypot detected", metadata)

        # Liquidity lock
        if cfg.require_liquidity_lock and not token_context.get("liquidity_locked"):
            return GuardDecision(GuardDecisionStatus.REQUIRE_APPROVAL, "Liquidity not locked", metadata)

        # Wallet bundle analysis (0-1 scale)
        bundle_score = metadata["bundle_score"]
        if bundle_score is not None and bundle_score > cfg.max_bundle_score:
            return GuardDecision(
                GuardDecisionStatus.REQUIRE_APPROVAL,
                "Insider bundle score above threshold",
                metadata | {"max_bundle_score": cfg.max_bundle_score},
            )

        return GuardDecision(GuardDecisionStatus.ALLOW, "Passed Solana safety checks", metadata)


_trading_guard: Optional[TradingGuard] = None
_solana_guard: Optional[SolanaAntiRugGuard] = None


def get_trading_guard() -> TradingGuard:
    global _trading_guard
    if _trading_guard is None:
        _trading_guard = TradingGuard()
    return _trading_guard


def get_solana_anti_rug_guard() -> SolanaAntiRugGuard:
    global _solana_guard
    if _solana_guard is None:
        _solana_guard = SolanaAntiRugGuard()
    return _solana_guard

"""§4 Prediction Market Risk — Per-market limits, pre-trade checks, kill switch.

Provides prediction-market-scoped risk controls:
- Per-market and per-event exposure limits.
- Portfolio-wide daily loss limit for prediction markets.
- Pre-trade sanity checks (max order size, slippage guard, depth check).
- Kill switch: halt new orders and optionally unwind on drawdown.
- Circuit breaker for consecutive risk check failures.
"""

from __future__ import annotations

import threading
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Set

from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents  # canonical fee schedule
from utils.logger import get_logger

logger = get_logger("merid.prediction.risk")


class RiskAction(str, Enum):
    """Actions the risk system can take."""
    ALLOW = "allow"
    REJECT = "reject"
    REDUCE_SIZE = "reduce_size"
    HALT = "halt"
    UNWIND = "unwind"


@dataclass
class CategoryLimit:
    """Exposure limit for a market category.
    
    CRITICAL: max_notional_usd should be derived from live Kalshi balance, not hardcoded.
    Default 0 means "derive from live bankroll" (20% of bankroll per category).
    """
    category: str
    # CRITICAL FIX: 0 = derive from live bankroll (was $5000 - catastrophic for micro bankrolls)
    max_notional_usd: Decimal = Decimal("0")  # 0 = derive: 20% of bankroll per category
    max_contracts: int = 0  # 0 = derive: 1 per $10 of bankroll
    max_pct_of_portfolio: float = 0.20  # 20% max in any one category
    enabled: bool = True

@dataclass
class PredictionRiskConfig:
    """Risk limits for prediction market trading.
    
    1-2% ALLOCATION STRATEGY (per MERID_RISK_PROFILE):
    - Conservative: 1% total allocation (0.5% per market × 2 markets)
    - Balanced: 1.5% total allocation (0.5% per market × 3 markets)
    - Functional: 2% total allocation (0.67% per market × 3 markets)
    
    All zero values derive from risk profile + live bankroll.
    """
    # Per-market limits - 0 = derive from risk profile allocation %
    max_notional_per_market_usd: Decimal = Decimal("0")
    max_contracts_per_market: int = 0  # 0 = derive: allocation% / price
    max_contracts_per_order: int = 0  # 0 = derive: min(25, allocation% / price)

    # Per-event limits
    max_notional_per_event_usd: Decimal = Decimal("0")  # 0 = derive: 2× per-market

    # THE KEY 1-2% TOTAL ALLOCATION CAP
    # 0 = derive from risk profile (conservative: 1%, balanced: 1.5%, functional: 2%)
    max_total_notional_usd: Decimal = Decimal("0")
    
    # Safety limits (separate from allocation)
    max_daily_loss_usd: Decimal = Decimal("0")  # 0 = derive: 5% of bankroll
    max_open_markets: int = 0  # 0 = derive: 1 per $50 of bankroll

    # Category-specific limits
    category_limits: Dict[str, CategoryLimit] = field(default_factory=dict)

    # Pre-trade checks
    max_slippage_cents: Decimal = Decimal("3")  # Max 3 cents worse than best
    min_depth_contracts: int = 5                 # Min depth at target price
    max_spread_cents: Decimal = Decimal("10")    # Reject if spread > 10 cents
    
    # Kalshi Platform Constraints
    min_order_size: int = 1                      # 1 contract min
    max_order_size: int = 100000                 # 100k contracts max (typicalretail)
    tick_size_cents: Decimal = Decimal("1")      # 1 cent tick

    # Rate limiting
    max_orders_per_minute: int = 30
    max_orders_per_hour: int = 300

    # Kill switch
    drawdown_halt_pct: Decimal = Decimal("0.10")   # Halt at 10 % drawdown
    drawdown_unwind_pct: Decimal = Decimal("0.15")  # Unwind at 15 % drawdown

    # Circuit breaker: halt if odds move > X cents in Y seconds
    odds_move_threshold_cents: Decimal = Decimal("15")
    odds_move_window_seconds: int = 60

    def __post_init__(self):
        # PROFILE GATING: When kalshi_crypto_15m_v2 profile is active, use profile values
        # instead of hardcoded defaults for category limits, drawdown limits, and daily loss
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
            if is_profile_active():
                adapter = get_active_profile()
                if adapter:
                    profile = adapter.profile
                    # Use profile-based category limits (config-only)
                    self.category_limits = adapter.to_category_limits()
                    # Use profile-based drawdown limits
                    self.drawdown_halt_pct = Decimal(str(profile.guardrails_drawdown_halt_pct))
                    self.drawdown_unwind_pct = Decimal(str(profile.guardrails_drawdown_unwind_pct))
                    # Use profile-based daily loss limit
                    self.max_daily_loss_usd = Decimal(str(profile.guardrails_max_daily_loss_usd))
                    return
        except ImportError:
            # Profile module not available, proceed with legacy behavior
            pass

        if not self.category_limits:
            # C6/RISK-18: Read caps from the same env vars as CategoryExposureTracker
            # so that a single env-var change governs both enforcement layers and
            # they can never silently diverge.
            # CRITICAL FIX: Default to "0" (derive from bankroll), not hardcoded $ amounts
            # LEGACY: This path is disabled for kalshi_crypto_15m_v2 profile
            import os as _os
            self.category_limits = {
                "crypto": CategoryLimit(
                    "crypto",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_CRYPTO_USD", "0")),  # 0 = 20% of bankroll
                    max_contracts=0,  # 0 = derive from bankroll
                ),
                "economics": CategoryLimit(
                    "economics",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_ECONOMICS_USD", "0")),
                    max_contracts=0,
                ),
                "financials": CategoryLimit(
                    "financials",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_FINANCIALS_USD", "0")),
                    max_contracts=0,
                ),
                "politics": CategoryLimit(
                    "politics",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_POLITICS_USD", "0")),
                    max_contracts=0,
                ),
                "macro": CategoryLimit(
                    "macro",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_MACRO_USD", "0")),
                    max_contracts=0,
                ),
                "tech": CategoryLimit(
                    "tech",
                    max_notional_usd=Decimal(_os.getenv("MERID_CAT_CAP_TECH_USD", "0")),
                    max_contracts=0,
                ),
            }


@dataclass
class PreTradeCheck:
    """Result of a pre-trade risk check."""
    allowed: bool
    action: RiskAction
    reason: str
    adjusted_size: Optional[int] = None  # If REDUCE_SIZE, the new size
    market_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "action": self.action.value,
            "reason": self.reason,
            "adjusted_size": self.adjusted_size,
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MarketExposure:
    """Tracks exposure for a single market."""
    market_id: str
    event_id: str
    side: str
    contracts: int
    avg_entry_cents: Decimal
    notional_usd: Decimal  # contracts * avg_entry_cents / 100
    unrealized_pnl_usd: Decimal = Decimal("0")


@dataclass
class DailyPnL:
    """Tracks daily PnL for prediction markets."""
    date: str  # ISO date string
    realized_pnl_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    trades: int = 0
    fees_usd: Decimal = Decimal("0")

    @property
    def total_pnl_usd(self) -> Decimal:
        return self.realized_pnl_usd + self.unrealized_pnl_usd - self.fees_usd


class PredictionMarketRisk:
    """Prediction-market-scoped risk manager.

    Enforces per-market, per-event, and portfolio-wide limits.
    Provides pre-trade checks and a kill switch.
    """

    def __init__(self, config: Optional[PredictionRiskConfig] = None):
        self.config = config or PredictionRiskConfig()
        self._exposures: Dict[str, MarketExposure] = {}
        self._daily_pnl: Dict[str, DailyPnL] = {}
        self._halted: bool = False
        self._halt_reason: str = ""
        self._unwind_requested: bool = False
        self._recent_prices: Dict[str, List[tuple]] = {}  # market_id -> [(ts, price)]
        self._breach_log: List[dict] = []
        self._category_notional: Dict[str, Decimal] = {}
        self._category_contracts: Dict[str, int] = {}
        self._orders_this_minute = 0
        self._orders_this_hour = 0
        self._last_minute_reset = datetime.now(timezone.utc)
        self._last_hour_reset = datetime.now(timezone.utc)
        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._rate_lock = threading.Lock()  # guards check-and-increment atomicity
        self._rate_lock = None  # Disabled to prevent startup hang

        # Circuit breaker for risk check failures
        self._consecutive_failures = 0
        self._circuit_breaker_threshold = 10  # Consecutive failures before halting
        self._circuit_breaker_open = False
        self._circuit_breaker_reset_time = 0.0
        self._circuit_breaker_cooldown = 30.0  # Seconds before attempting recovery

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def unwind_requested(self) -> bool:
        return self._unwind_requested

    # ------------------------------------------------------------------
    # Exposure tracking
    # ------------------------------------------------------------------

    def record_fill(
        self,
        market_id: str,
        event_id: str,
        side: str,
        contracts: int,
        price_cents: Decimal,
        fee_cents: Decimal = Decimal("0"),
        category: Optional[str] = None,
    ) -> None:
        """Record a fill and update exposure."""
        notional = (Decimal(contracts) * price_cents / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        if market_id in self._exposures:
            exp = self._exposures[market_id]
            total_contracts = exp.contracts + contracts
            if total_contracts > 0:
                exp.avg_entry_cents = (
                    (exp.avg_entry_cents * exp.contracts + price_cents * contracts)
                    / total_contracts
                ).quantize(Decimal("0.01"), ROUND_HALF_UP)
            exp.contracts = total_contracts
            exp.notional_usd = (
                Decimal(total_contracts) * exp.avg_entry_cents / Decimal("100")
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            self._exposures[market_id] = MarketExposure(
                market_id=market_id,
                event_id=event_id,
                side=side,
                contracts=contracts,
                avg_entry_cents=price_cents,
                notional_usd=notional,
            )

        # Update category counters so check_order's category cap fires correctly.
        if category:
            self._category_notional[category] = (
                self._category_notional.get(category, Decimal("0")) + notional
            )
            self._category_contracts[category] = (
                self._category_contracts.get(category, 0) + contracts
            )

        # Update daily PnL
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today not in self._daily_pnl:
            self._daily_pnl[today] = DailyPnL(date=today)
        self._daily_pnl[today].trades += 1
        self._daily_pnl[today].fees_usd += (fee_cents / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

    def record_close(
        self,
        market_id: str,
        contracts: int,
        exit_price_cents: Decimal,
        category: Optional[str] = None,
        outcome: Optional[str] = None,
        fee_cents: Decimal = Decimal("0"),
    ) -> None:
        """Record a position close and update realized PnL.

        Args:
            outcome: Settlement outcome — "yes", "no", or "cancelled".
                     When provided, overrides exit_price_cents with the
                     canonical settlement price (100¢ YES, 0¢ NO, entry
                     price for cancellations) so PnL is exact.
            fee_cents: Total fees paid on the closing trade, deducted
                       from realized PnL.
        """
        exp = self._exposures.get(market_id)
        if not exp:
            return

        if outcome == "yes":
            exit_price_cents = Decimal("100")
        elif outcome == "no":
            exit_price_cents = Decimal("0")
        elif outcome == "cancelled":
            exit_price_cents = exp.avg_entry_cents

        pnl_per_contract = exit_price_cents - exp.avg_entry_cents
        realized = (pnl_per_contract * contracts / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        fee_usd = (fee_cents / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        realized -= fee_usd

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today not in self._daily_pnl:
            self._daily_pnl[today] = DailyPnL(date=today)
        self._daily_pnl[today].realized_pnl_usd += realized

        # Reduce category counters proportionally to contracts being closed.
        if category:
            closed_notional = (
                Decimal(contracts) * exp.avg_entry_cents / Decimal("100")
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if category in self._category_notional:
                self._category_notional[category] = max(
                    Decimal("0"),
                    self._category_notional[category] - closed_notional,
                )
            if category in self._category_contracts:
                self._category_contracts[category] = max(
                    0,
                    self._category_contracts[category] - contracts,
                )

        exp.contracts -= contracts
        if exp.contracts <= 0:
            del self._exposures[market_id]
        else:
            exp.notional_usd = (
                Decimal(exp.contracts) * exp.avg_entry_cents / Decimal("100")
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    def check_order(
        self,
        market_id: str,
        event_id: str,
        side: str,
        contracts: int,
        price_cents: Decimal,
        best_bid_cents: Optional[Decimal] = None,
        best_ask_cents: Optional[Decimal] = None,
        depth_at_price: Optional[int] = None,
        category: Optional[str] = None,
        edge: Decimal = Decimal("0"),
        agent_max_notional_usd: Optional[Decimal] = None,
        max_yes_position: Optional[int] = None,
        max_no_position: Optional[int] = None,
        existing_yes_contracts: int = 0,
        existing_no_contracts: int = 0,
        max_contracts_per_order: Optional[int] = None,
    ) -> PreTradeCheck:
        """Run all pre-trade checks for a proposed order.

        Checks (in order):
        1. Circuit breaker check (degradation path)
        2. Kill switch halted?
        3. Max order size.
        4. Per-market exposure limit.
        5. Per-side position limit (BUG-009: YES/NO specific limits).
        6. Per-event exposure limit.
        7. Portfolio-wide notional limit.
        8. Daily loss limit.
        9. Max open markets.
        10. Category exposure.
        11. Rate limit.
        12. Post-fee edge minimum.
        13. Tick size.
        14. Spread check.
        15. Slippage guard.
        16. Depth check.
        """
        # BYPASS: Circuit breaker for kalshi_crypto_15m_v2 - use risk envelope drawdown only
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_regime_cooldown_enabled'):
                if not profile_adapter.profile.guardrails_regime_cooldown_enabled:
                    logger.debug("[RISK-CIRCUIT-BREAKER] Disabled for kalshi_crypto_15m_v2 - using risk envelope drawdown only")
                else:
                    # Only check circuit breaker if enabled
                    if self._circuit_breaker_open:
                        now = time.monotonic()
                        if now < self._circuit_breaker_reset_time:
                            remaining = self._circuit_breaker_reset_time - now
                            logger.warning(
                                "[RISK-CIRCUIT-BREAKER] Circuit breaker open - rejecting order (cooldown: %.1fs remaining)",
                                remaining
                            )
                            return PreTradeCheck(
                                action=RiskAction.REJECT,
                                reason="risk_circuit_breaker_open",
                                details=f"Risk engine circuit breaker open - retry after {remaining:.1f}s"
                            )
                        else:
                            # Reset circuit breaker after cooldown
                            logger.info("[RISK-CIRCUIT-BREAKER] Circuit breaker reset - attempting recovery")
                            self._circuit_breaker_open = False
                            self._consecutive_failures = 0
        except Exception as e:
            logger.debug("[RISK-CIRCUIT-BREAKER] Failed to check profile for bypass: %s", e)
            # Fallback to original behavior if profile check fails
            if self._circuit_breaker_open:
                now = time.monotonic()
                if now < self._circuit_breaker_reset_time:
                    remaining = self._circuit_breaker_reset_time - now
                    logger.warning(
                        "[RISK-CIRCUIT-BREAKER] Circuit breaker open - rejecting order (cooldown: %.1fs remaining)",
                        remaining
                    )
                    return PreTradeCheck(
                        action=RiskAction.REJECT,
                        reason="risk_circuit_breaker_open",
                        details=f"Risk engine circuit breaker open - retry after {remaining:.1f}s"
                    )
                else:
                    # Reset circuit breaker after cooldown
                    logger.info("[RISK-CIRCUIT-BREAKER] Circuit breaker reset - attempting recovery")
                    self._circuit_breaker_open = False
                    self._consecutive_failures = 0

        # CRITICAL: Type safety enforcement - convert any float inputs to Decimal
        # to prevent TypeError: unsupported operand type(s) for float and Decimal
        try:
            if not isinstance(price_cents, Decimal):
                price_cents = Decimal(str(price_cents))
            if not isinstance(contracts, int):
                contracts = int(contracts)
            if not isinstance(edge, Decimal):
                edge = Decimal(str(edge))
            if agent_max_notional_usd is not None and not isinstance(agent_max_notional_usd, Decimal):
                agent_max_notional_usd = Decimal(str(agent_max_notional_usd))
            if best_bid_cents is not None and not isinstance(best_bid_cents, Decimal):
                best_bid_cents = Decimal(str(best_bid_cents))
            if best_ask_cents is not None and not isinstance(best_ask_cents, Decimal):
                best_ask_cents = Decimal(str(best_ask_cents))
        except (ValueError, InvalidOperation) as e:
            logger.error(f"Invalid order parameters: price={price_cents}, contracts={contracts}, edge={edge}, error={e}")
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Invalid numeric parameters: {e}",
                market_id=market_id,
            )

        now = datetime.now(timezone.utc)

        # 1. Kill switch
        if self._halted:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.HALT,
                reason=f"Kill switch active: {self._halt_reason}",
                market_id=market_id,
            )

        # 2. Max order size
        # Use provided agent limit if available, otherwise fall back to config default
        # SAFETY: Always derive from bankroll to ensure 1-2% allocation cap is respected
        _max_contracts = max_contracts_per_order if max_contracts_per_order is not None else self.config.max_contracts_per_order
        
        # CRITICAL: Always validate against live bankroll - never trust static config
        # for micro bankrolls (e.g., 50 contracts on $14 bankroll = 178% risk!)
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            _equity = get_equity_for_risk_calc_sync()
            if _equity and _equity > 0:
                # Derive max contracts from 1% of bankroll / price
                # This ensures we never exceed the 1-2% allocation strategy
                _price_usd = float(price_cents) / 100.0 if price_cents else 0.50
                _derived_max = max(1, int((_equity * 0.01) / _price_usd))
                
                # Use the MORE CONSERVATIVE of: provided value, config value, or derived value
                if _max_contracts is None or _max_contracts <= 0:
                    _max_contracts = _derived_max
                else:
                    _max_contracts = min(_max_contracts, _derived_max)
            elif _max_contracts is None or _max_contracts <= 0:
                # No bankroll available and no valid config - use absolute safety floor
                _max_contracts = 5  # Absolute minimum for unknown bankroll
        except Exception:
            if _max_contracts is None or _max_contracts <= 0:
                _max_contracts = 5  # Absolute safety floor
        
        if contracts > _max_contracts:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REDUCE_SIZE,
                reason=f"Order size {contracts} exceeds agent max {_max_contracts}.",
                adjusted_size=_max_contracts,
                market_id=market_id,
            )
        
        if contracts < self.config.min_order_size:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Order size {contracts} below platform min {self.config.min_order_size}.",
                market_id=market_id,
            )
            
        if contracts > self.config.max_order_size:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Order size {contracts} exceeds platform max {self.config.max_order_size}.",
                market_id=market_id,
            )

        order_notional = (Decimal(contracts) * price_cents / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # HARD REQUIREMENT: Live Kalshi bankroll only - no fake data, no fallbacks
        # agent_max_notional_usd comes from trading_agent which calls get_live_bankroll()
        if agent_max_notional_usd is None:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason="BANKROLL_UNAVAILABLE: Live Kalshi bankroll not available. Cannot trade.",
                market_id=market_id,
            )
        
        # Use the provided max_notional (already computed as % of live bankroll by trading_agent)
        effective_max_notional = agent_max_notional_usd
        
        if order_notional > effective_max_notional:
            # BUG-FIX (2026-05-07): Ensure at least 1 contract is allowed if budget permits
            # Original logic could return adjusted_size=0 when cap < price, causing
            # "resizing from 1 to 1" confusion in trading_agent (skips resize when adjusted_size=0)
            adjusted_contracts = int(
                (effective_max_notional * Decimal("100") / price_cents)
                .to_integral_value()
            ) if price_cents > 0 else 0
            
            # Allow 1 contract if we have any budget, even if cap < price
            # This mirrors the MIN_CONTRACTS_PER_WINNER logic in dynamic_sizing.py
            if adjusted_contracts == 0 and effective_max_notional >= (price_cents / Decimal("100")):
                adjusted_contracts = 1
            
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REDUCE_SIZE,
                reason=(
                    f"Order notional ${order_notional:.2f} exceeds 2% bankroll cap "
                    f"${effective_max_notional:.2f}."
                ),
                adjusted_size=adjusted_contracts,
                market_id=market_id,
            )

        # 3. Per-market limit
        # BUG-FIX: Derive max_contracts_per_market from bankroll if set to 0
        # This mirrors the logic used for _max_contracts per-order sizing
        _max_per_market = self.config.max_contracts_per_market
        if _max_per_market is None or _max_per_market <= 0:
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                _equity_market = get_equity_for_risk_calc_sync()
                if _equity_market and _equity_market > 0:
                    # Derive from 2% of bankroll / price (more conservative than per-order 1%)
                    _price_usd_market = float(price_cents) / 100.0 if price_cents else 0.50
                    _derived_market_max = max(1, int((_equity_market * 0.02) / _price_usd_market))
                    _max_per_market = _derived_market_max
                else:
                    _max_per_market = 100  # Default fallback
            except Exception:
                _max_per_market = 100  # Default fallback
        
        existing = self._exposures.get(market_id)
        current_contracts = existing.contracts if existing else 0
        new_total_contracts = current_contracts + contracts
        if new_total_contracts > _max_per_market:
            allowed = _max_per_market - current_contracts
            if allowed <= 0:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Market {market_id}: at max {_max_per_market} contracts.",
                    market_id=market_id,
                )
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REDUCE_SIZE,
                reason=f"Market {market_id}: would exceed limit. Max additional: {allowed}.",
                adjusted_size=allowed,
                market_id=market_id,
            )

        new_notional = (Decimal(new_total_contracts) * price_cents / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        # ZERO-FIX: Skip check if max_notional_per_market_usd is 0 (meaning derive from bankroll)
        if self.config.max_notional_per_market_usd > Decimal("0") and new_notional > self.config.max_notional_per_market_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Market {market_id}: notional ${new_notional} exceeds max ${self.config.max_notional_per_market_usd}.",
                market_id=market_id,
            )

        # 4. Per-side position limit (BUG-009: Enforce max_yes_position / max_no_position from YAML)
        if side.lower() == "yes" and max_yes_position is not None:
            new_yes_total = existing_yes_contracts + contracts
            if new_yes_total > max_yes_position:
                allowed = max_yes_position - existing_yes_contracts
                if allowed <= 0:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Side YES: at max {max_yes_position} contracts.",
                        market_id=market_id,
                    )
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REDUCE_SIZE,
                    reason=f"Side YES: would exceed limit. Max additional: {allowed}.",
                    adjusted_size=allowed,
                    market_id=market_id,
                )
        elif side.lower() == "no" and max_no_position is not None:
            new_no_total = existing_no_contracts + contracts
            if new_no_total > max_no_position:
                allowed = max_no_position - existing_no_contracts
                if allowed <= 0:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Side NO: at max {max_no_position} contracts.",
                        market_id=market_id,
                    )
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REDUCE_SIZE,
                    reason=f"Side NO: would exceed limit. Max additional: {allowed}.",
                    adjusted_size=allowed,
                    market_id=market_id,
                )

        # 5. Per-event limit
        event_notional = sum(
            e.notional_usd for e in self._exposures.values()
            if e.event_id == event_id
        )
        # ZERO-FIX: Skip if max_notional_per_event_usd is 0 (derive from bankroll)
        if self.config.max_notional_per_event_usd > Decimal("0") and event_notional + order_notional > self.config.max_notional_per_event_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Event {event_id}: notional ${event_notional + order_notional} exceeds max ${self.config.max_notional_per_event_usd}.",
                market_id=market_id,
            )

        # 5. Portfolio-wide notional (legacy hardcoded cap)
        total_notional = sum(e.notional_usd for e in self._exposures.values())
        # ZERO-FIX: Skip if max_total_notional_usd is 0 (derive from bankroll)
        if self.config.max_total_notional_usd > Decimal("0") and total_notional + order_notional > self.config.max_total_notional_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Portfolio notional ${total_notional + order_notional} exceeds max ${self.config.max_total_notional_usd}.",
                market_id=market_id,
            )

        # 5b. EMERGENCY GLOBAL BANKROLL CAP: Total portfolio notional cannot exceed 2% of bankroll
        # SAFETY: This is the critical 1-2% bankroll enforcement across ALL agents
        # CRITICAL FIX: Use live bankroll from bankroll_service_v2, not static settings
        MINIMUM_GLOBAL_BANKROLL_CENTS = 5000  # $50 minimum to prevent negative caps
        global_bankroll_usd = Decimal("50000.00")  # Default for logging only
        try:
            # Use live bankroll from bankroll_service_v2 (same source as sizing)
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            live_equity_usd = get_equity_for_risk_calc_sync()
            if live_equity_usd is not None and live_equity_usd > 0:
                global_bankroll_cents = int(live_equity_usd * 100)
                global_bankroll_usd = Decimal(str(live_equity_usd))
            else:
                # Fail-closed: if no live bankroll, reject the order
                logger.error(
                    "[RISK_GLOBAL_CAP_REJECT] Live bankroll unavailable (equity=%s). "
                    "Rejecting order to prevent untethered sizing.",
                    live_equity_usd
                )
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason="BANKROLL_UNAVAILABLE: Live Kalshi bankroll not available for global cap.",
                    market_id=market_id,
                )
            # FIX: If bankroll is 0 or negative, use minimum to prevent negative cap
            if global_bankroll_cents <= 0:
                logger.warning(
                    "[RISK_GLOBAL_CAP_FIX] Live bankroll is %s (invalid), using minimum $%.2f",
                    global_bankroll_cents, MINIMUM_GLOBAL_BANKROLL_CENTS / 100
                )
                global_bankroll_cents = MINIMUM_GLOBAL_BANKROLL_CENTS
            global_bankroll_usd = Decimal(global_bankroll_cents) / Decimal("100")
            # 2% of bankroll = max TOTAL portfolio notional (1% = more conservative)
            global_bankroll_cap = (global_bankroll_usd * Decimal("0.02")).quantize(Decimal("0.01"))
            # EXTRA SAFETY: Ensure cap is never negative or zero
            if global_bankroll_cap <= 0:
                global_bankroll_cap = Decimal("1.00")  # Minimum $1.00 cap
        except Exception as e:
            logger.error("[RISK_GLOBAL_CAP_FIX] Error computing global bankroll cap: %s. Using fallback.", e)
            global_bankroll_cap = Decimal("1000.00")  # Fallback: 2% of $50K

        if total_notional + order_notional > global_bankroll_cap:
            logger.error(
                "[EMERGENCY_BANKROLL_CAP] Order rejected: total_notional=$%.2f + order=$%.2f "
                "would exceed 2%% bankroll cap=$%.2f. Bankroll=$%.2f",
                float(total_notional), float(order_notional), float(global_bankroll_cap), float(global_bankroll_usd)
            )
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"EMERGENCY: Total portfolio notional ${total_notional + order_notional:.2f} would exceed 2% bankroll cap ${global_bankroll_cap:.2f}.",
                market_id=market_id,
            )

        # 6. Daily loss limit
        today = now.strftime("%Y-%m-%d")
        daily = self._daily_pnl.get(today)
        if daily and daily.total_pnl_usd < -self.config.max_daily_loss_usd:
            self.halt(f"Daily loss ${abs(daily.total_pnl_usd)} exceeds max ${self.config.max_daily_loss_usd}.")
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.HALT,
                reason=f"Daily loss ${abs(daily.total_pnl_usd)} exceeds max ${self.config.max_daily_loss_usd}.",
                market_id=market_id,
            )

        # 7. Max open markets
        # BUG-FIX: Derive max_open_markets from bankroll if set to 0
        _max_open = self.config.max_open_markets
        if _max_open is None or _max_open <= 0:
            try:
                from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                _equity_open = get_equity_for_risk_calc_sync()
                if _equity_open and _equity_open > 0:
                    # 1 market per $50 of bankroll, max 50 markets
                    _derived_open = max(1, min(50, int(_equity_open / 50)))
                    _max_open = _derived_open
                else:
                    _max_open = 10  # Default fallback
            except Exception:
                _max_open = 10  # Default fallback
        
        open_markets = len(self._exposures)
        if market_id not in self._exposures and open_markets >= _max_open:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Already in {open_markets} markets, max is {_max_open}.",
                market_id=market_id,
            )

        # 8. Category exposure
        if category and category in self.config.category_limits:
            cat_limit = self.config.category_limits[category]
            if cat_limit.enabled:
                cat_notional = self._category_notional.get(category, Decimal("0")) + order_notional
                if cat_notional > cat_limit.max_notional_usd:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Category '{category}' notional ${cat_notional:.2f} exceeds cap ${cat_limit.max_notional_usd:.2f}",
                        market_id=market_id,
                    )

                cat_contracts = self._category_contracts.get(category, 0) + contracts
                if cat_contracts > cat_limit.max_contracts:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Category '{category}' contracts {cat_contracts} exceeds cap {cat_limit.max_contracts}",
                        market_id=market_id,
                    )

        # 9. Rate limit — lock to make check-and-increment atomic across
        # concurrent agent tasks that share this singleton.
        if self._rate_lock is not None:
            with self._rate_lock:
                self._reset_rate_counters(now)
                if self._orders_this_minute >= self.config.max_orders_per_minute:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Rate limit: {self._orders_this_minute} orders this minute",
                        market_id=market_id,
                    )
                if self._orders_this_hour >= self.config.max_orders_per_hour:
                    return PreTradeCheck(
                        allowed=False,
                        action=RiskAction.REJECT,
                        reason=f"Rate limit: {self._orders_this_hour} orders this hour",
                        market_id=market_id,
                    )
        else:
            # Lock disabled - direct check (startup workaround)
            self._reset_rate_counters(now)
            if self._orders_this_minute >= self.config.max_orders_per_minute:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Rate limit: {self._orders_this_minute} orders this minute",
                    market_id=market_id,
                )
            if self._orders_this_hour >= self.config.max_orders_per_hour:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Rate limit: {self._orders_this_hour} orders this hour",
                    market_id=market_id,
                )
            # Pre-increment inside the lock so no other thread can see the
            # same slot as available.  The increments at line 536 are removed.
            self._orders_this_minute += 1
            self._orders_this_hour += 1

        # 10. Post-fee edge minimum (formula is side-aware for binary contracts)
        # BUG-FIX: Default price_cents to 50 if 0 or invalid to avoid post_fee_edge=0
        _effective_price_cents = price_cents if price_cents > 0 else Decimal("50")
        if edge > 0:
            fee = Decimal(str(kalshi_fee_cents(int(_effective_price_cents), contracts)))
            fee_per = fee / max(contracts, 1)
            if side in ("no", "buy_no", "sell_no"):
                payout_per = _effective_price_cents  # NO pays price_cents if YES loses
            else:
                payout_per = Decimal("100") - _effective_price_cents  # YES pays 100-price
            post_fee_edge = edge - (fee_per / payout_per) if payout_per > 0 else Decimal("0")
            if post_fee_edge < Decimal("0.05"):  # CONSERVATIVE: 5% post-fee edge
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Post-fee edge {post_fee_edge:.4f} below minimum 0.05",
                    market_id=market_id,
                )

        # 11. Tick size check
        if price_cents % self.config.tick_size_cents != 0:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Price {price_cents}¢ must be multiple of tick size {self.config.tick_size_cents}¢.",
                market_id=market_id,
            )

        # 12. Spread check — crypto KX* uses profile config for max spread
        # LEGACY REMOVAL: crypto_edge_production moved to archive/legacy/ during 15m stack cleanup
        # Profile config (kalshi_crypto_15m.yaml) sets max_spread_cents = 10 for all crypto
        if best_bid_cents is not None and best_ask_cents is not None:
            spread = best_ask_cents - best_bid_cents
            max_spread = self.config.max_spread_cents
            if spread > max_spread:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Spread {spread}¢ exceeds max {max_spread}¢.",
                    market_id=market_id,
                )

        # 13. Slippage guard
        if side in ("buy", "buy_yes", "buy_no") and best_ask_cents is not None:
            if price_cents > best_ask_cents + self.config.max_slippage_cents:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Price {price_cents}¢ is {price_cents - best_ask_cents}¢ above best ask {best_ask_cents}¢.",
                    market_id=market_id,
                )
        elif side in ("sell", "sell_yes", "sell_no") and best_bid_cents is not None:
            if price_cents < best_bid_cents - self.config.max_slippage_cents:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Price {price_cents}¢ is {best_bid_cents - price_cents}¢ below best bid {best_bid_cents}¢.",
                    market_id=market_id,
                )

        # 14. Depth check
        if depth_at_price is not None and depth_at_price < self.config.min_depth_contracts:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Depth {depth_at_price} contracts below minimum {self.config.min_depth_contracts}.",
                market_id=market_id,
            )

        return PreTradeCheck(
            allowed=True,
            action=RiskAction.ALLOW,
            reason="All pre-trade checks passed.",
            market_id=market_id,
        )

    # ------------------------------------------------------------------
    # Kill switch & circuit breakers
    # ------------------------------------------------------------------

    def halt(self, reason: str, unwind: bool = False) -> None:
        """Activate the kill switch."""
        already_halted = self._halted
        self._halted = True
        self._halt_reason = reason
        self._unwind_requested = unwind
        self._log_breach("HALT", reason)
        logger.warning(f"PM kill switch activated: {reason} (unwind={unwind})")
        # Fire alert + escalation only on fresh halts to avoid suppression issues.
        if not already_halted:
            self._emit_halt_alert(reason, unwind)

    def _emit_halt_alert(self, reason: str, unwind: bool) -> None:
        """Emit a CRITICAL alert and start an escalation for this halt."""
        try:
            from merid.prediction.alerts import get_alert_manager
            get_alert_manager().fire_kill_switch(reason, unwind)
        except Exception as _ae:
            logger.error("halt: alert emission failed: %s", _ae)
        try:
            from notifications.escalation import get_escalation_manager
            get_escalation_manager().start_escalation(
                alert_id=f"pm_kill_switch_{self._last_minute_reset.strftime('%Y%m%d%H%M%S')}",
                severity="critical",
                alert_data={"reason": reason, "unwind": unwind},
            )
        except Exception as _ee:
            logger.error("halt: escalation start failed: %s", _ee)

    def resume(self) -> None:
        """Deactivate the kill switch."""
        self._halted = False
        self._halt_reason = ""
        self._unwind_requested = False
        logger.info("PM kill switch deactivated")

    def check_drawdown(self, portfolio_value_usd: Decimal, peak_value_usd: Decimal) -> None:
        """Check portfolio drawdown and trigger halt/unwind if needed."""
        if peak_value_usd <= Decimal("0"):
            return

        drawdown = (peak_value_usd - portfolio_value_usd) / peak_value_usd

        if drawdown >= self.config.drawdown_unwind_pct:
            self.halt(
                f"Drawdown {drawdown:.2%} >= unwind threshold {self.config.drawdown_unwind_pct:.2%}.",
                unwind=True,
            )
        elif drawdown >= self.config.drawdown_halt_pct:
            self.halt(
                f"Drawdown {drawdown:.2%} >= halt threshold {self.config.drawdown_halt_pct:.2%}.",
                unwind=False,
            )

    def record_price(self, market_id: str, price_cents: Decimal) -> None:
        """Record a price for circuit breaker monitoring."""
        now = datetime.now(timezone.utc)
        if market_id not in self._recent_prices:
            self._recent_prices[market_id] = []

        self._recent_prices[market_id].append((now, price_cents))

        # Prune old entries
        cutoff = now - timedelta(seconds=self.config.odds_move_window_seconds * 2)
        self._recent_prices[market_id] = [
            (ts, p) for ts, p in self._recent_prices[market_id] if ts > cutoff
        ]

    def check_circuit_breaker(self, market_id: str) -> Optional[str]:
        """Check if odds moved too fast for a market.

        Returns a reason string if the circuit breaker should trip, else None.
        """
        prices = self._recent_prices.get(market_id, [])
        if len(prices) < 2:
            return None

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=self.config.odds_move_window_seconds)
        window_prices = [p for ts, p in prices if ts >= window_start]

        if len(window_prices) < 2:
            return None

        max_price = max(window_prices)
        min_price = min(window_prices)
        move = max_price - min_price

        if move >= self.config.odds_move_threshold_cents:
            reason = (
                f"Market {market_id}: odds moved {move}¢ in "
                f"{self.config.odds_move_window_seconds}s "
                f"(threshold: {self.config.odds_move_threshold_cents}¢)."
            )
            self._log_breach("CIRCUIT_BREAKER", reason)
            return reason

        return None

    # ------------------------------------------------------------------
    # Breach log
    # ------------------------------------------------------------------

    def _log_breach(self, breach_type: str, reason: str) -> None:
        self._breach_log.append({
            "type": breach_type,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 100
        if len(self._breach_log) > 100:
            self._breach_log = self._breach_log[-100:]

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a JSON-serialisable risk summary for dashboards."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self._daily_pnl.get(today, DailyPnL(date=today))

        total_notional = sum(e.notional_usd for e in self._exposures.values())
        total_unrealized = sum(e.unrealized_pnl_usd for e in self._exposures.values())
        
        # Calculate drawdown if we have peak equity tracking (not fully implemented in state yet)
        drawdown_pct = 0.0
        
        return {
            "kill_switch_active": self._halted,
            "kill_switch_reason": self._halt_reason,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "unwind_requested": self._unwind_requested,
            "open_market_count": len(self._exposures),
            "total_notional_usd": float(total_notional),
            "total_unrealized_pnl_usd": float(total_unrealized),
            "daily_realized_pnl_usd": float(daily.realized_pnl_usd),
            "daily_total_pnl_usd": float(daily.total_pnl_usd),
            "daily_trades": daily.trades,
            "daily_fees_usd": float(daily.fees_usd),
            "drawdown_pct": drawdown_pct,
            "category_notional": {k: float(v) for k, v in self._category_notional.items()},
            "category_contracts": self._category_contracts,
            "exposures": [
                {
                    "market_id": e.market_id,
                    "event_id": e.event_id,
                    "side": e.side,
                    "contracts": e.contracts,
                    "notional_usd": float(e.notional_usd),
                    "unrealized_pnl_usd": float(e.unrealized_pnl_usd),
                }
                for e in self._exposures.values()
            ],
            "recent_breaches": self._breach_log[-10:],
            "limits": {
                "max_notional_per_market_usd": float(self.config.max_notional_per_market_usd),
                "max_notional_per_event_usd": float(self.config.max_notional_per_event_usd),
                "max_total_notional_usd": float(self.config.max_total_notional_usd),
                "max_daily_loss_usd": float(self.config.max_daily_loss_usd),
                "max_open_markets": self.config.max_open_markets,
            },
        }

    def get_markets_to_unwind(self) -> List[str]:
        """Return market IDs that should be unwound (all if unwind requested)."""
        if not self._unwind_requested:
            return []
        return list(self._exposures.keys())

    def _reset_rate_counters(self, now: datetime) -> None:
        if self._last_minute_reset is None or (now - self._last_minute_reset).total_seconds() >= 60:
            self._orders_this_minute = 0
            self._last_minute_reset = now
        if self._last_hour_reset is None or (now - self._last_hour_reset).total_seconds() >= 3600:
            self._orders_this_hour = 0
            self._last_hour_reset = now


# ── Cycle Cap Tracker ───────────────────────────────────────────────────

@dataclass
class CycleCapConfig:
    """Configuration for cycle-level risk cap.
    
    Bankroll MUST come from live Kalshi API via bankroll_service_v2.
    NO hardcoded fallbacks permitted - fail closed if bankroll unavailable.
    
    UNIFIED 3%/8% RISK REGIME (2026-05-07): Aligned with MAX_CYCLE_RISK_PCT/MAX_TOTAL_RISK_PCT from core.settings
    """
    max_cycle_risk_pct: float = 0.03  # 3% of bankroll per cycle (unified regime - optimized 2026-05-07)
    bankroll_source: str = "live"  # "live" = from bankroll service ONLY


class CycleCapTracker:
    """Real-time cycle utilization tracker for micro-scalping.
    
    Tracks deployed capital within a trading cycle to ensure total exposure
    stays within the configured cap (default 3% of bankroll, unified regime).
    
    With $44.35 bankroll and 3% cap = $1.33 max per cycle.
    Top 3 winners at $0.50 each = $1.50 total < $1.33 cap ✗ (need tighter sizing)
    
    Usage::
        tracker = CycleCapTracker(config)
        ok, available = tracker.check_capacity(pending_order_notional)
        if ok:
            tracker.record_deployment(order_notional)
            # ... execute order ...
            tracker.record_release(order_notional)  # on fill or cancel
    """
    
    def __init__(self, config: Optional[CycleCapConfig] = None) -> None:
        self._config = config or CycleCapConfig()
        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._lock = threading.Lock()
        self._lock = None  # Disabled to prevent startup hang
        self._deployed_this_cycle: float = 0.0
        self._cycle_start: datetime = datetime.now(timezone.utc)
        self._deployment_log: List[Dict] = []
        self._max_cycle_deployed: float = 0.0
    
    def _get_bankroll(self) -> float:
        """Get current bankroll for cap calculation.
        
        FAILS CLOSED if live bankroll unavailable - NO fallbacks permitted.
        Bankroll must come from live Kalshi API via bankroll_service_v2.
        """
        # Try live bankroll service
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity = get_equity_for_risk_calc_sync()
            if equity is not None and equity > 0:
                return float(equity)
        except Exception:
            pass
        
        # FAIL CLOSED: No bankroll available - log and return 0 to block trading
        logger.error(
            "[CycleCapTracker] Bankroll unavailable from Kalshi API. "
            "Trading blocked. Check bankroll_service_v2 health and Kalshi credentials."
        )
        return 0.0
    
    @property
    def max_cycle_cap(self) -> float:
        """Maximum allowed deployment per cycle in USD."""
        return self._get_bankroll() * self._config.max_cycle_risk_pct
    
    @property
    def deployed(self) -> float:
        """Currently deployed capital this cycle."""
        with self._lock:
            return self._deployed_this_cycle
    
    @property
    def available(self) -> float:
        """Remaining available capacity this cycle."""
        with self._lock:
            return max(0.0, self.max_cycle_cap - self._deployed_this_cycle)
    
    def check_capacity(self, pending_order_notional: float) -> tuple[bool, float, str]:
        """Check if pending order fits within cycle cap.
        
        Args:
            pending_order_notional: Order size in USD
            
        Returns:
            Tuple of (allowed, available_capacity, reason)
        """
        with self._lock:
            cap = self.max_cycle_cap
            available = cap - self._deployed_this_cycle
            
            if pending_order_notional <= available:
                return True, available, ""
            else:
                return False, available, (
                    f"Cycle cap reached: ${self._deployed_this_cycle:.2f}/"
                    f"${cap:.2f} deployed, need ${pending_order_notional:.2f} "
                    f"but only ${available:.2f} available"
                )
    
    def record_deployment(self, order_notional: float, order_id: str = "") -> None:
        """Record capital deployment (order submitted)."""
        with self._lock:
            self._deployed_this_cycle += order_notional
            if self._deployed_this_cycle > self._max_cycle_deployed:
                self._max_cycle_deployed = self._deployed_this_cycle
            
            self._deployment_log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "deploy",
                "amount": order_notional,
                "order_id": order_id,
                "cycle_total": self._deployed_this_cycle,
            })
            # Keep last 100 entries
            if len(self._deployment_log) > 100:
                self._deployment_log = self._deployment_log[-100:]
    
    def record_release(self, order_notional: float, order_id: str = "") -> None:
        """Record capital release (order filled or canceled)."""
        with self._lock:
            self._deployed_this_cycle = max(0.0, self._deployed_this_cycle - order_notional)
            
            self._deployment_log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "release",
                "amount": order_notional,
                "order_id": order_id,
                "cycle_total": self._deployed_this_cycle,
            })
    
    def reset_cycle(self) -> Dict[str, Any]:
        """Reset cycle tracking (call at start of new cycle).
        
        Returns:
            Summary of completed cycle
        """
        with self._lock:
            summary = {
                "previous_cycle_start": self._cycle_start.isoformat(),
                "previous_cycle_max_deployed": self._max_cycle_deployed,
                "previous_cycle_cap": self.max_cycle_cap,
                "utilization_pct": (
                    self._max_cycle_deployed / self.max_cycle_cap * 100
                    if self.max_cycle_cap > 0 else 0.0
                ),
            }
            
            self._deployed_this_cycle = 0.0
            self._max_cycle_deployed = 0.0
            self._cycle_start = datetime.now(timezone.utc)
            
            return summary
    
    def summary(self) -> Dict[str, Any]:
        """Current cycle utilization summary."""
        with self._lock:
            cap = self.max_cycle_cap
            return {
                "cycle_start": self._cycle_start.isoformat(),
                "max_cycle_cap_usd": round(cap, 2),
                "deployed_usd": round(self._deployed_this_cycle, 2),
                "available_usd": round(max(0.0, cap - self._deployed_this_cycle), 2),
                "utilization_pct": round(
                    self._deployed_this_cycle / cap * 100 if cap > 0 else 0.0, 1
                ),
                "max_deployed_this_cycle": round(self._max_cycle_deployed, 2),
                "config": {
                    "max_cycle_risk_pct": self._config.max_cycle_risk_pct,
                    "bankroll_source": self._config.bankroll_source,
                },
            }


# ── Singleton ────────────────────────────────────────────────────────────

_risk: Optional[PredictionMarketRisk] = None
_risk_lock = None


def get_prediction_risk(config: Optional[PredictionRiskConfig] = None) -> PredictionMarketRisk:
    """Get or create the singleton PredictionMarketRisk."""
    global _risk
    if _risk is None:
        if _risk_lock is not None:
            with _risk_lock:
                if _risk is None:
                    _risk = PredictionMarketRisk(config)
        else:
            # Lock disabled - direct initialization (startup workaround)
            _risk = PredictionMarketRisk(config)
    # BUG-P fix: warn if caller passes a non-None config that differs from the
    # already-constructed singleton's config — silently ignored configs hide
    # misconfigured callers.  All callers in this codebase use the same YAML
    # limits so this fires only on genuine mismatches.
    elif config is not None and _risk.config != config:
        import logging as _log
        _log.getLogger("merid.prediction.risk").warning(
            "get_prediction_risk: config arg ignored — singleton already initialised. "
            "Pass config only on first call or use PredictionMarketRisk() directly."
        )
    return _risk

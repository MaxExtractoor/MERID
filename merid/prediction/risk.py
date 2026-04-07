"""§4 Prediction Market Risk — Per-market limits, pre-trade checks, kill switch.

Provides prediction-market-scoped risk controls:
- Per-market and per-event exposure limits.
- Portfolio-wide daily loss limit for prediction markets.
- Pre-trade sanity checks (max order size, slippage guard, depth check).
- Kill switch: halt new orders and optionally unwind on drawdown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Set

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
    """Exposure limit for a market category."""
    category: str
    max_notional_usd: Decimal = Decimal("5000.0")
    max_contracts: int = 500
    max_pct_of_portfolio: float = 0.20  # 20% max in any one category
    enabled: bool = True

@dataclass
class PredictionRiskConfig:
    """Risk limits for prediction market trading."""
    # Per-market limits
    max_notional_per_market_usd: Decimal = Decimal("500")
    max_contracts_per_market: int = 200
    max_contracts_per_order: int = 50

    # Per-event limits (an event can have multiple markets)
    max_notional_per_event_usd: Decimal = Decimal("1000")

    # Portfolio-wide limits
    max_total_notional_usd: Decimal = Decimal("5000")
    max_daily_loss_usd: Decimal = Decimal("250")
    max_open_markets: int = 20

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
        if not self.category_limits:
            self.category_limits = {
                "crypto": CategoryLimit("crypto", max_notional_usd=Decimal("5000"), max_contracts=500),
                "economics": CategoryLimit("economics", max_notional_usd=Decimal("3000"), max_contracts=300),
                "financials": CategoryLimit("financials", max_notional_usd=Decimal("3000"), max_contracts=300),
                "politics": CategoryLimit("politics", max_notional_usd=Decimal("2000"), max_contracts=200),
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
        return self.realized_pnl_usd + self.unrealized_pnl_usd


# ── Fee schedule ─────────────────────────────────────────────────────────

def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi fee in cents for a trade.

    Tiered:
      1-99 contracts:   7% of payout, min 2¢ per contract
      100-999:          5% of payout, min 2¢
      1000+:            3% of payout, min 2¢
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    payout_per = 100 - price_cents  # cents won per contract if correct

    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03

    fee_per = max(2, math.ceil(payout_per * rate))
    return fee_per * contracts

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
    ) -> None:
        """Record a position close and update realized PnL."""
        exp = self._exposures.get(market_id)
        if not exp:
            return

        pnl_per_contract = exit_price_cents - exp.avg_entry_cents
        realized = (pnl_per_contract * contracts / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today not in self._daily_pnl:
            self._daily_pnl[today] = DailyPnL(date=today)
        self._daily_pnl[today].realized_pnl_usd += realized

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
    ) -> PreTradeCheck:
        """Run all pre-trade checks for a proposed order.

        Checks (in order):
        1. Kill switch halted?
        2. Max order size.
        3. Per-market exposure limit.
        4. Per-event exposure limit.
        5. Portfolio-wide notional limit.
        6. Daily loss limit.
        7. Max open markets.
        8. Category exposure.
        9. Rate limit.
        10. Post-fee edge minimum.
        11. Tick size.
        12. Spread check.
        13. Slippage guard.
        14. Depth check.
        """
        now = datetime.now(timezone.utc)

        # 1. Kill switch
        if self._halted:
            result = PreTradeCheck(
                allowed=False,
                action=RiskAction.HALT,
                reason=f"Kill switch active: {self._halt_reason}",
                market_id=market_id,
            )
            logger.info(
                "[RISK-VETO] halt | market=%s reason=%s",
                market_id, self._halt_reason
            )
            return result

        # 2. Max order size
        if contracts > self.config.max_contracts_per_order:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REDUCE_SIZE,
                reason=f"Order size {contracts} exceeds agent max {self.config.max_contracts_per_order}.",
                adjusted_size=self.config.max_contracts_per_order,
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

        # Tick size check
        if price_cents % self.config.tick_size_cents != 0:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Price {price_cents}¢ must be multiple of tick size {self.config.tick_size_cents}¢.",
                market_id=market_id,
            )

        order_notional = (Decimal(contracts) * price_cents / Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # 3. Per-market limit
        existing = self._exposures.get(market_id)
        current_contracts = existing.contracts if existing else 0
        new_total_contracts = current_contracts + contracts
        if new_total_contracts > self.config.max_contracts_per_market:
            allowed = self.config.max_contracts_per_market - current_contracts
            if allowed <= 0:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Market {market_id}: at max {self.config.max_contracts_per_market} contracts.",
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
        if new_notional > self.config.max_notional_per_market_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Market {market_id}: notional ${new_notional} exceeds max ${self.config.max_notional_per_market_usd}.",
                market_id=market_id,
            )

        # 4. Per-event limit
        event_notional = sum(
            e.notional_usd for e in self._exposures.values()
            if e.event_id == event_id
        )
        if event_notional + order_notional > self.config.max_notional_per_event_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Event {event_id}: notional ${event_notional + order_notional} exceeds max ${self.config.max_notional_per_event_usd}.",
                market_id=market_id,
            )

        # 5. Portfolio-wide notional
        total_notional = sum(e.notional_usd for e in self._exposures.values())
        if total_notional + order_notional > self.config.max_total_notional_usd:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Portfolio notional ${total_notional + order_notional} exceeds max ${self.config.max_total_notional_usd}.",
                market_id=market_id,
            )

        # 6. Daily loss limit
        today = now.strftime("%Y-%m-%d")
        daily = self._daily_pnl.get(today)
        if daily and daily.total_pnl_usd < -self.config.max_daily_loss_usd:
            self.halt(f"Daily loss ${abs(daily.total_pnl_usd)} exceeds max ${self.config.max_daily_loss_usd}.")
            result = PreTradeCheck(
                allowed=False,
                action=RiskAction.HALT,
                reason=f"Daily loss ${abs(daily.total_pnl_usd)} exceeds max ${self.config.max_daily_loss_usd}.",
                market_id=market_id,
            )
            logger.info(
                "[RISK-VETO] daily_loss | market=%s loss=$%.2f max=$%.2f",
                market_id, abs(daily.total_pnl_usd), self.config.max_daily_loss_usd
            )
            return result

        # 7. Max open markets
        open_markets = len(self._exposures)
        if market_id not in self._exposures and open_markets >= self.config.max_open_markets:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Already in {open_markets} markets, max is {self.config.max_open_markets}.",
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

        # 9. Rate limit
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

        # 10. Post-fee edge minimum
        if edge > 0:
            fee = Decimal(str(kalshi_fee_cents(int(price_cents), contracts)))
            fee_per = fee / max(contracts, 1)
            payout_per = Decimal("100") - price_cents
            post_fee_edge = edge - (fee_per / payout_per) if payout_per > 0 else Decimal("0")
            if post_fee_edge < Decimal("0.01"):
                result = PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Post-fee edge {post_fee_edge:.4f} below minimum 0.01",
                    market_id=market_id,
                )
                logger.info(
                    "[RISK-VETO] edge_too_low | market=%s post_fee_edge=%.4f min=0.01",
                    market_id, post_fee_edge
                )
                return result

        # 11. Tick size check
        if price_cents % self.config.tick_size_cents != 0:
            return PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=f"Price {price_cents}¢ must be multiple of tick size {self.config.tick_size_cents}¢.",
                market_id=market_id,
            )

        # 12. Spread check
        if best_bid_cents is not None and best_ask_cents is not None:
            spread = best_ask_cents - best_bid_cents
            if spread > self.config.max_spread_cents:
                return PreTradeCheck(
                    allowed=False,
                    action=RiskAction.REJECT,
                    reason=f"Spread {spread}¢ exceeds max {self.config.max_spread_cents}¢.",
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
        self._halted = True
        self._halt_reason = reason
        self._unwind_requested = unwind
        self._log_breach("HALT", reason)
        logger.warning(f"PM kill switch activated: {reason} (unwind={unwind})")

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


# ── Singleton ────────────────────────────────────────────────────────────

_risk: Optional[PredictionMarketRisk] = None


def get_prediction_risk(config: Optional[PredictionRiskConfig] = None) -> PredictionMarketRisk:
    """Get or create the singleton PredictionMarketRisk."""
    global _risk
    if _risk is None:
        _risk = PredictionMarketRisk(config)
    return _risk

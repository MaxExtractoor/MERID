"""Yes/No Parity Checker for Kalshi 15-minute markets.

This module implements diagnostic checks to ensure Yes/No intent, prices, and orders
are internally consistent and symmetric per Kalshi's market framing.

Kalshi's matching model makes buying Yes equivalent to selling No at the complementary price,
and buying No equivalent to selling Yes at the complementary price. This checker verifies
that the bot's execution layer preserves the intended exposure all the way through to the
final order side.

Reference: https://help.kalshi.com/en/articles/13823806-buying-yes-vs-selling-no
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json


class ExposureIntent(str, Enum):
    """High-level exposure intent."""
    BULLISH_EVENT = "bullish_event_happens"   # want YES exposure
    BEARISH_EVENT = "bearish_event_happens"   # want NO exposure
    NEUTRAL = "neutral"


class IntendedAction(str, Enum):
    """Intended action enum matching SignalAction."""
    BUY_YES = "buy_yes"
    SELL_YES = "sell_yes"
    BUY_NO = "buy_no"
    SELL_NO = "sell_no"
    NONE = "none"


@dataclass
class MarketSnapshot:
    """Market context snapshot from Kalshi orderbook."""
    market_id: str
    asset: str
    expiry_ts: int
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]


@dataclass
class BotView:
    """Bot's internal view of the market."""
    model_prob_yes: float
    model_prob_no: float
    edge_yes: float
    edge_no: float
    chosen_side: Optional[str]  # "yes" or "no" or None
    exposure_intent: ExposureIntent


@dataclass
class ExecutionDecision:
    """Execution decision before order submission."""
    intended_action: IntendedAction
    api_side: Optional[str]      # "yes"/"no"/None
    api_yes_price: Optional[float]
    api_no_price: Optional[float]


@dataclass
class ParityCheckResult:
    """Result of parity check."""
    ok: bool
    reasons: list
    context: Dict[str, Any]


class YesNoParityChecker:
    """Diagnostic checker for Yes/No parity invariants.
    
    Verifies that the bot's Yes/No intent, prices, and orders are internally
    consistent and symmetric per Kalshi's market framing.
    
    Core invariants:
    1. Probability parity: prob_no ≈ 1 - prob_yes
    2. Edge parity: chosen side should have higher edge
    3. Exposure vs action parity: bullish intent should map to YES exposure
    4. API side/price mapping parity: intended action matches API call
    5. Symmetric evaluation: both Yes and No edges computed
    """
    
    def __init__(
        self,
        prob_eps: float = 1e-3,
        edge_eps: float = 1e-3,
        price_eps: float = 1e-2,
    ):
        """Initialize parity checker with tolerance thresholds.
        
        Args:
            prob_eps: Tolerance for probability parity check
            edge_eps: Tolerance for edge parity check
            price_eps: Tolerance for price parity check
        """
        self.prob_eps = prob_eps
        self.edge_eps = edge_eps
        self.price_eps = price_eps
    
    def check(
        self,
        m: MarketSnapshot,
        v: BotView,
        d: ExecutionDecision,
    ) -> ParityCheckResult:
        """Run all parity checks on a single market.
        
        Args:
            m: Market snapshot from Kalshi orderbook
            v: Bot's internal view of the market
            d: Execution decision before order submission
            
        Returns:
            ParityCheckResult with ok flag, reasons for failure, and context
        """
        reasons = []
        
        # 1) Probability parity
        implied_no = 1.0 - v.model_prob_yes
        if abs(v.model_prob_no - implied_no) > self.prob_eps:
            reasons.append(
                f"PROB_MISMATCH: prob_no={v.model_prob_no:.4f} != 1-prob_yes={implied_no:.4f}"
            )
        
        # 2) Edge winner parity
        if v.edge_yes is not None and v.edge_no is not None:
            if v.chosen_side == "yes" and v.edge_no > v.edge_yes + self.edge_eps:
                reasons.append(
                    f"WINNER_MISMATCH: chose YES but edge_no={v.edge_no:.4f} > edge_yes={v.edge_yes:.4f}"
                )
            if v.chosen_side == "no" and v.edge_yes > v.edge_no + self.edge_eps:
                reasons.append(
                    f"WINNER_MISMATCH: chose NO but edge_yes={v.edge_yes:.4f} > edge_no={v.edge_no:.4f}"
                )
        
        # 3) Exposure vs action parity
        # Per Kalshi semantics:
        # - Bullish (event happens): BUY_YES or SELL_NO are both valid
        # - Bearish (event does not happen): BUY_NO or SELL_YES are both valid
        # We flag only the truly conflicting actions
        if v.exposure_intent == ExposureIntent.BULLISH_EVENT:
            if d.intended_action in {IntendedAction.SELL_YES, IntendedAction.BUY_NO}:
                reasons.append(
                    f"INTENT_ACTION_CONFLICT: bullish intent but action={d.intended_action} (should be BUY_YES or SELL_NO)"
                )
        if v.exposure_intent == ExposureIntent.BEARISH_EVENT:
            if d.intended_action in {IntendedAction.BUY_YES, IntendedAction.SELL_NO}:
                reasons.append(
                    f"INTENT_ACTION_CONFLICT: bearish intent but action={d.intended_action} (should be BUY_NO or SELL_YES)"
                )
        
        # 4) API side/price mapping parity
        if d.intended_action == IntendedAction.BUY_YES:
            if d.api_side != "yes" or d.api_yes_price is None:
                reasons.append(
                    "API_MISMATCH: BUY_YES but api_side!=yes or yes_price missing"
                )
        if d.intended_action == IntendedAction.BUY_NO:
            if d.api_side != "no" or d.api_no_price is None:
                reasons.append(
                    "API_MISMATCH: BUY_NO but api_side!=no or no_price missing"
                )
        if d.intended_action == IntendedAction.SELL_YES:
            if d.api_side != "yes" or d.api_yes_price is None:
                reasons.append(
                    "API_MISMATCH: SELL_YES but api_side!=yes or yes_price missing"
                )
        if d.intended_action == IntendedAction.SELL_NO:
            if d.api_side != "no" or d.api_no_price is None:
                reasons.append(
                    "API_MISMATCH: SELL_NO but api_side!=no or no_price missing"
                )
        
        # 5) Symmetric evaluation
        if v.edge_yes is None or v.edge_no is None:
            reasons.append(
                "MISSING_SIDE: one of edges is None (non-symmetric evaluation)"
            )
        
        return ParityCheckResult(
            ok=(len(reasons) == 0),
            reasons=reasons,
            context={
                "market_id": m.market_id,
                "asset": m.asset,
                "expiry_ts": m.expiry_ts,
                "yes_bid": m.yes_bid,
                "yes_ask": m.yes_ask,
                "no_bid": m.no_bid,
                "no_ask": m.no_ask,
                "model_prob_yes": v.model_prob_yes,
                "model_prob_no": v.model_prob_no,
                "edge_yes": v.edge_yes,
                "edge_no": v.edge_no,
                "chosen_side": v.chosen_side,
                "exposure_intent": v.exposure_intent.value,
                "intended_action": d.intended_action.value,
                "api_side": d.api_side,
                "api_yes_price": d.api_yes_price,
                "api_no_price": d.api_no_price,
            },
        )
    
    def log_failure(
        self,
        result: ParityCheckResult,
        cycle_id: str,
        logger,
    ) -> None:
        """Log parity check failure as structured JSON event.
        
        Args:
            result: ParityCheckResult from check()
            cycle_id: 15-minute cycle identifier
            logger: Logger instance
        """
        if result.ok:
            return
        
        log_record = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "cycle_id": cycle_id,
            "market_id": result.context.get("market_id"),
            "asset": result.context.get("asset"),
            "check": "YES_NO_PARITY",
            "ok": False,
            "reasons": result.reasons,
            "context": result.context,
        }
        
        logger.error(
            "[YES_NO_PARITY_FAILURE] %s",
            json.dumps(log_record, indent=2),
        )


class ParityMetrics:
    """Per-cycle parity metrics aggregator."""
    
    def __init__(self):
        self.reset()
    
    def reset(self) -> None:
        """Reset metrics for new cycle."""
        self.total_markets_evaluated = 0
        self.total_markets_traded = 0
        self.parity_checks_failed = 0
        self.failures_by_reason: Dict[str, int] = {
            "PROB_MISMATCH": 0,
            "WINNER_MISMATCH": 0,
            "INTENT_ACTION_CONFLICT": 0,
            "API_MISMATCH": 0,
            "MISSING_SIDE": 0,
        }
        self.yes_won_but_no_traded = 0
        self.no_won_but_yes_traded = 0
    
    def record_evaluated(self) -> None:
        """Record a market was evaluated."""
        self.total_markets_evaluated += 1
    
    def record_traded(self) -> None:
        """Record a market was traded."""
        self.total_markets_traded += 1
    
    def record_failure(self, result: ParityCheckResult) -> None:
        """Record a parity check failure."""
        self.parity_checks_failed += 1
        
        for reason in result.reasons:
            for failure_type in self.failures_by_reason:
                if failure_type in reason:
                    self.failures_by_reason[failure_type] += 1
                    break
    
    def record_side_mismatch(self, chosen_side: str, traded_side: str) -> None:
        """Record a side mismatch (edge winner vs traded side)."""
        if chosen_side == "yes" and traded_side == "no":
            self.yes_won_but_no_traded += 1
        elif chosen_side == "no" and traded_side == "yes":
            self.no_won_but_yes_traded += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        return {
            "total_markets_evaluated": self.total_markets_evaluated,
            "total_markets_traded": self.total_markets_traded,
            "parity_checks_failed": self.parity_checks_failed,
            "failures_by_reason": self.failures_by_reason,
            "yes_won_but_no_traded": self.yes_won_but_no_traded,
            "no_won_but_yes_traded": self.no_won_but_yes_traded,
        }
    
    def is_healthy(self) -> bool:
        """Check if cycle is healthy (no parity failures)."""
        return self.parity_checks_failed == 0


# Singleton instance for global access
_parity_checker: Optional[YesNoParityChecker] = None
_parity_metrics: Optional[ParityMetrics] = None


def get_parity_checker() -> YesNoParityChecker:
    """Get singleton parity checker instance."""
    global _parity_checker
    if _parity_checker is None:
        _parity_checker = YesNoParityChecker()
    return _parity_checker


def get_parity_metrics() -> ParityMetrics:
    """Get singleton parity metrics instance."""
    global _parity_metrics
    if _parity_metrics is None:
        _parity_metrics = ParityMetrics()
    return _parity_metrics


def reset_parity_metrics() -> None:
    """Reset parity metrics for new cycle."""
    global _parity_metrics
    if _parity_metrics is not None:
        _parity_metrics.reset()

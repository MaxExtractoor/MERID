"""Yes/No Parity Checker for Kalshi 15-minute markets.

This module implements diagnostic checks to ensure Yes/No intent, prices, and orders
are internally consistent and symmetric per Kalshi's market framing.

Kalshi's matching model makes buying Yes equivalent to selling No at the complementary price,
and buying No equivalent to selling Yes at the complementary price. This checker verifies
that the bot's execution layer preserves the intended exposure all the way through to the
final order side.

Reference: https://help.kalshi.com/en/articles/13823806-buying-yes-vs-selling-no
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json
import os
import time


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


# ── Directional Anomaly Circuit Breaker (2026-08-19) ─────────────────────────
# Temporary safety guard that blocks signals when YES/NO selection cannot be
# explained by the raw model probabilities and market prices.  Disabled by
# setting MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED=1.

MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED = (
    os.getenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0") == "1"
)
MERID_DIRECTIONAL_TRACE_ENABLED = (
    os.getenv("MERID_DIRECTIONAL_TRACE_ENABLED", "1") == "1"
)
DIRECTIONAL_ANOMALY_WINDOW_SIZE = int(
    os.getenv("MERID_DIRECTIONAL_ANOMALY_WINDOW_SIZE", "30")
)
DIRECTIONAL_ANOMALY_SIDE_RATIO = float(
    os.getenv("MERID_DIRECTIONAL_ANOMALY_SIDE_RATIO", "0.8")
)
DIRECTIONAL_ANOMALY_PRICE_EPS = float(
    os.getenv("MERID_DIRECTIONAL_ANOMALY_PRICE_EPS", "0.05")
)


def emit_directional_trace(logger, payload: Dict[str, Any]) -> None:
    """Emit a one-line structured directional-trace JSON event."""
    if not MERID_DIRECTIONAL_TRACE_ENABLED:
        return
    try:
        logger.info("[DIRECTIONAL-TRACE] %s", json.dumps(payload, default=str))
    except Exception:
        pass


class DirectionalAnomalyCircuitBreaker:
    """Rolling-window guard against structural YES/NO selection bias.

    Blocks when:
    1. The model probabilities for YES/NO do not sum to ~1 (parity failure).
    2. The selected side is not the side with the highest net edge.
    3. A side is selected > ``side_ratio`` of the time while the average
       executable price of those selections is not in the configured entry
       zone (i.e. the raw signal distribution cannot explain the frequency).
    """

    def __init__(
        self,
        window_size: int = DIRECTIONAL_ANOMALY_WINDOW_SIZE,
        side_ratio: float = DIRECTIONAL_ANOMALY_SIDE_RATIO,
        price_eps: float = DIRECTIONAL_ANOMALY_PRICE_EPS,
    ) -> None:
        self._window_size = window_size
        self._side_ratio = side_ratio
        self._price_eps = price_eps
        self._windows: Dict[str, deque] = {}

    def record_and_check(
        self,
        asset: str,
        ticker: str,
        buy_threshold: float,
        sell_threshold: float,
        yes_model_prob: float,
        no_model_prob: float,
        yes_edge: float,
        no_edge: float,
        selected_side: Optional[str],
        selected_action: str,
        market_price: float,
    ) -> tuple[bool, str]:
        """Return (allowed, reason).  ``reason`` is empty when allowed."""
        # Re-read the env var on every call so tests and ops can toggle it live.
        if os.getenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0") == "1":
            return True, ""

        # 1. Probability parity (complement symmetry)
        prob_sum = yes_model_prob + no_model_prob
        if abs(prob_sum - 1.0) > 1e-6:
            return False, (
                f"prob_parity_violation: prob_sum={prob_sum:.6f} "
                f"yes_model_prob={yes_model_prob:.6f} no_model_prob={no_model_prob:.6f}"
            )

        # 2. Edge-winner parity (only when a side is selected)
        if selected_side in ("yes", "no"):
            if selected_side == "yes" and no_edge > yes_edge + 1e-9:
                return False, (
                    f"edge_winner_mismatch: selected=yes but no_edge={no_edge:.6f} > "
                    f"yes_edge={yes_edge:.6f}"
                )
            if selected_side == "no" and yes_edge > no_edge + 1e-9:
                return False, (
                    f"edge_winner_mismatch: selected=no but yes_edge={yes_edge:.6f} > "
                    f"no_edge={no_edge:.6f}"
                )

        # 3. Rolling-window frequency / price fairness
        window = self._windows.setdefault(asset, deque(maxlen=self._window_size))
        if selected_side in ("yes", "no"):
            # Record the executable YES price associated with the selection.
            # For a YES trade we record the YES market price; for a NO trade we
            # record the complementary YES price (1 - NO market price).
            if selected_side == "yes":
                yes_price = float(market_price)
            else:
                # For a NO trade the analogous "expensive YES / cheap NO" signal is
                # the YES market price.  Cheap NO means YES is high, so we record the
                # YES price and block NO trades whose average YES price is too low.
                yes_price = float(market_price)
            window.append({
                "time": time.time(),
                "side": selected_side,
                "yes_price": yes_price,
            })

        if len(window) >= 5:
            total = len(window)
            yes_count = sum(1 for r in window if r["side"] == "yes")
            no_count = total - yes_count
            yes_ratio = yes_count / total
            no_ratio = no_count / total

            if yes_ratio >= self._side_ratio and yes_count > 0:
                avg_yes_price = (
                    sum(r["yes_price"] for r in window if r["side"] == "yes")
                    / yes_count
                )
                if avg_yes_price > buy_threshold + self._price_eps:
                    return False, (
                        f"yes_frequency_anomaly: yes_ratio={yes_ratio:.2f} "
                        f"avg_yes_price={avg_yes_price:.4f} "
                        f"buy_threshold={buy_threshold:.4f}"
                    )

            if no_ratio >= self._side_ratio and no_count > 0:
                # NO trades should only fire when YES is expensive (>= sell_threshold).
                avg_yes_price_for_no = (
                    sum(r["yes_price"] for r in window if r["side"] == "no")
                    / no_count
                )
                if avg_yes_price_for_no < sell_threshold - self._price_eps:
                    return False, (
                        f"no_frequency_anomaly: no_ratio={no_ratio:.2f} "
                        f"avg_yes_price_for_no={avg_yes_price_for_no:.4f} "
                        f"sell_threshold={sell_threshold:.4f}"
                    )

        return True, ""

    def reset(self) -> None:
        """Clear all rolling windows."""
        self._windows.clear()


_directional_anomaly_breaker: Optional[DirectionalAnomalyCircuitBreaker] = None


def get_directional_anomaly_breaker() -> DirectionalAnomalyCircuitBreaker:
    """Get singleton directional anomaly circuit breaker instance."""
    global _directional_anomaly_breaker
    if _directional_anomaly_breaker is None:
        _directional_anomaly_breaker = DirectionalAnomalyCircuitBreaker()
    return _directional_anomaly_breaker


def reset_directional_anomaly_breaker() -> None:
    """Reset the singleton directional anomaly circuit breaker."""
    global _directional_anomaly_breaker
    _directional_anomaly_breaker = None

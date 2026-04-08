"""No-trade decision reason tracking for observability.

Provides a single authoritative taxonomy of reasons why a signal
did not result in an order, enabling dashboard-level visibility into
what gates are blocking trades.
"""

from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("merid.prediction.no_trade_reasons")


class NoTradeReason(str, Enum):
    """Authoritative reasons why a trade was not executed."""

    # Edge/threshold gates
    EDGE_BELOW_THRESHOLD = "edge_below_threshold"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    SHADOW_THRESHOLD_ONLY = "shadow_threshold_only"  # Would trade if shadow floor used

    # Consensus gates
    CONSENSUS_FORMING = "consensus_forming"
    CONSENSUS_CONFLICTED = "consensus_conflicted"
    CONSENSUS_MISMATCH = "consensus_mismatch"

    # Risk/limits gates
    RISK_LIMIT = "risk_limit"
    ORDER_LIMIT_REACHED = "order_limit_reached"
    DEGRADED_MODE_PAUSED = "degraded_mode_paused"

    # Market gates
    MARKET_NOT_TRADEABLE = "market_not_tradeable"
    ENTRY_WINDOW_CLOSED = "entry_window_closed"
    LIQUIDITY_INSUFFICIENT = "liquidity_insufficient"

    # Venue/mode gates
    VENUE_CLOSED = "venue_closed"
    PAPER_ONLY = "paper_only"

    # Strategy gates
    NO_ACTIONABLE_EDGE = "no_actionable_edge"
    KELLY_SIZE_ZERO = "kelly_size_zero"

    # Infrastructure gates
    INFRA_BACKOFF = "infra_backoff"
    DATA_STALE = "data_stale"
    SPOT_PRICE_UNAVAILABLE = "spot_price_unavailable"


class NoTradeDecisionTracker:
    """Tracks and logs no-trade decisions for observability."""

    def __init__(self):
        self._decision_counts: Dict[str, int] = {}
        for reason in NoTradeReason:
            self._decision_counts[reason.value] = 0

    def record(
        self,
        agent_name: str,
        market_id: str,
        asset: str,
        timeframe: str,
        reason: NoTradeReason,
        net_edge: Optional[float] = None,
        threshold: Optional[float] = None,
        consensus_status: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a no-trade decision with full context.

        Args:
            agent_name: Name of the trading agent
            market_id: Market/ticker that was evaluated
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, etc.)
            reason: NoTradeReason enum value
            net_edge: Net edge if available
            threshold: Threshold that blocked if applicable
            consensus_status: Consensus status if relevant
            additional_context: Any extra metadata
        """
        self._decision_counts[reason.value] += 1

        # Log the decision
        logger.info(
            "[NO-TRADE] agent=%s market=%s asset=%s tf=%s reason=%s "
            "net_edge=%s threshold=%s consensus=%s context=%s",
            agent_name,
            market_id,
            asset,
            timeframe,
            reason.value,
            f"{net_edge:.4f}" if net_edge is not None else "N/A",
            f"{threshold:.4f}" if threshold is not None else "N/A",
            consensus_status or "N/A",
            additional_context or {},
        )

    def get_counts(self) -> Dict[str, int]:
        """Get current counts of all no-trade reasons."""
        return dict(self._decision_counts)

    def reset_counts(self) -> None:
        """Reset all counters (for new reporting period)."""
        for reason in NoTradeReason:
            self._decision_counts[reason.value] = 0

    def get_top_reasons(self, limit: int = 5) -> list[tuple[str, int]]:
        """Get top N reasons by frequency.

        Args:
            limit: Number of top reasons to return

        Returns:
            List of (reason, count) tuples sorted by count descending
        """
        sorted_reasons = sorted(
            self._decision_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_reasons[:limit]


# Singleton instance
_tracker: Optional[NoTradeDecisionTracker] = None


def get_no_trade_tracker() -> NoTradeDecisionTracker:
    """Get or create the singleton NoTradeDecisionTracker."""
    global _tracker
    if _tracker is None:
        _tracker = NoTradeDecisionTracker()
    return _tracker


def reset_no_trade_tracker() -> None:
    """Reset singleton (for testing)."""
    global _tracker
    _tracker = None

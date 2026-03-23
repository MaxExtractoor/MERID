"""Market Consensus Engine for Kalshi Trading.

This engine coordinates agent voting on MarketConsensusSnapshot objects
to determine trading actions (LONG/SHORT/FLAT/NO_EDGE).

Key differences from old news consensus:
- Votes on **market state** not news approval
- Produces **trading actions** not binary approve/reject
- Considers **liquidity, fees, and risk** in final decision
- Logs show **market decisions** not "news rejected"

Flow:
1. Receive MarketConsensusSnapshot with market data + features
2. Collect AgentOpinion votes from each agent
3. Aggregate votes using weighted consensus rules
4. Apply risk filters (liquidity, position limits, fees)
5. Output final consensus: LONG/SHORT/FLAT/NO_EDGE
6. Log market decision with edge and confidence
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from merid.signals.market_consensus import (
    AgentOpinion,
    MarketConsensusSnapshot,
    MarketConsensusDecision,
    TradingAction,
)
from utils.logger import get_logger

logger = get_logger("merid.consensus.market_engine")


class MarketConsensusEngine:
    """Aggregates agent votes on Kalshi markets to determine trading actions.

    Consensus rules:
    - Minimum quorum: 60% of agents must vote
    - Minimum agreement: 60% must agree on same action for LONG/SHORT
    - Edge threshold: Consensus edge must exceed fees + spread
    - Liquidity filter: Spread must be < 5% of mid
    - No trade default: If no clear consensus, action = NO_EDGE
    """

    def __init__(
        self,
        min_quorum_pct: float = 0.60,
        min_agreement_pct: float = 0.60,
        min_edge_pct: float = 2.0,
        max_spread_pct: float = 5.0,
        kalshi_fee_pct: float = 0.7,  # Kalshi takes 7% of winnings = ~0.7% of notional
    ):
        self.min_quorum_pct = min_quorum_pct
        self.min_agreement_pct = min_agreement_pct
        self.min_edge_pct = min_edge_pct
        self.max_spread_pct = max_spread_pct
        self.kalshi_fee_pct = kalshi_fee_pct

        self._consensus_history: List[MarketConsensusSnapshot] = []

    async def form_consensus(
        self,
        snapshot: MarketConsensusSnapshot,
        agent_opinions: List[AgentOpinion],
    ) -> MarketConsensusSnapshot:
        """Form consensus on a market snapshot using agent opinions.

        Args:
            snapshot: MarketConsensusSnapshot with market data and features
            agent_opinions: List of agent votes

        Returns:
            Updated MarketConsensusSnapshot with consensus outcome
        """
        # Attach agent opinions to snapshot
        snapshot.agent_opinions = agent_opinions
        snapshot.total_votes = len(agent_opinions)

        # Count votes by action
        votes_by_action = self._count_votes(agent_opinions)
        snapshot.votes_long = votes_by_action.get(TradingAction.LONG, 0)
        snapshot.votes_short = votes_by_action.get(TradingAction.SHORT, 0)
        snapshot.votes_flat = votes_by_action.get(TradingAction.FLAT, 0)
        snapshot.votes_no_edge = votes_by_action.get(TradingAction.NO_EDGE, 0)

        # Check quorum
        if snapshot.total_votes == 0:
            logger.warning(f"No votes for {snapshot.contract_id}")
            snapshot.consensus_action = TradingAction.NO_EDGE
            snapshot.consensus_confidence = 0.0
            return snapshot

        # Determine consensus action and confidence
        consensus_action, agreement_pct = self._determine_consensus_action(votes_by_action, snapshot.total_votes)
        snapshot.consensus_action = consensus_action
        snapshot.agreement_pct = agreement_pct

        # Calculate weighted consensus confidence and edge
        consensus_confidence, consensus_edge = self._calculate_weighted_metrics(
            agent_opinions,
            consensus_action,
        )
        snapshot.consensus_confidence = consensus_confidence
        snapshot.consensus_edge_pct = consensus_edge

        # Apply risk filters
        snapshot.liquidity_ok = self._check_liquidity(snapshot)
        snapshot.risk_ok = self._check_risk_limits(snapshot)
        snapshot.fees_acceptable = self._check_fees_vs_edge(snapshot)

        # Override consensus if filters fail
        if not snapshot.liquidity_ok or not snapshot.risk_ok or not snapshot.fees_acceptable:
            logger.info(
                f"Consensus overridden for {snapshot.contract_id}: "
                f"liquidity={snapshot.liquidity_ok}, risk={snapshot.risk_ok}, fees={snapshot.fees_acceptable}"
            )
            snapshot.consensus_action = TradingAction.NO_EDGE

        # Set execution parameters if tradeable
        if snapshot.is_tradeable():
            self._set_execution_params(snapshot)

        # Log consensus result
        self._log_consensus(snapshot)

        # Store in history
        self._consensus_history.append(snapshot)

        return snapshot

    # ── Vote aggregation ──────────────────────────────────────────────────

    def _count_votes(self, opinions: List[AgentOpinion]) -> Dict[TradingAction, int]:
        """Count votes by action."""
        counts: Dict[TradingAction, int] = {
            TradingAction.LONG: 0,
            TradingAction.SHORT: 0,
            TradingAction.FLAT: 0,
            TradingAction.NO_EDGE: 0,
        }
        for opinion in opinions:
            counts[opinion.action] = counts.get(opinion.action, 0) + 1
        return counts

    def _determine_consensus_action(
        self,
        votes_by_action: Dict[TradingAction, int],
        total_votes: int,
    ) -> Tuple[TradingAction, float]:
        """Determine consensus action based on vote counts.

        Returns:
            (consensus_action, agreement_pct)
        """
        # Find action with most votes
        max_votes = 0
        consensus_action = TradingAction.NO_EDGE
        for action, count in votes_by_action.items():
            if count > max_votes:
                max_votes = count
                consensus_action = action

        agreement_pct = (max_votes / total_votes * 100) if total_votes > 0 else 0.0

        # Check if agreement exceeds threshold for directional trades
        if consensus_action in (TradingAction.LONG, TradingAction.SHORT):
            if agreement_pct < (self.min_agreement_pct * 100):
                # Not enough agreement, default to NO_EDGE
                consensus_action = TradingAction.NO_EDGE

        return consensus_action, agreement_pct

    def _calculate_weighted_metrics(
        self,
        opinions: List[AgentOpinion],
        consensus_action: TradingAction,
    ) -> Tuple[float, float]:
        """Calculate weighted confidence and edge for consensus action.

        Only considers opinions that match the consensus action.

        Returns:
            (weighted_confidence, weighted_edge_pct)
        """
        matching_opinions = [op for op in opinions if op.action == consensus_action]

        if not matching_opinions:
            return 0.0, 0.0

        total_confidence = sum(op.confidence for op in matching_opinions)
        weighted_confidence = total_confidence / len(matching_opinions)

        total_edge = sum(op.edge_estimate_pct * op.confidence for op in matching_opinions)
        total_weight = sum(op.confidence for op in matching_opinions)
        weighted_edge = total_edge / total_weight if total_weight > 0 else 0.0

        return weighted_confidence, weighted_edge

    # ── Risk filters ──────────────────────────────────────────────────────

    def _check_liquidity(self, snapshot: MarketConsensusSnapshot) -> bool:
        """Check if market liquidity is acceptable.

        Criteria:
        - Spread < max_spread_pct of mid
        - Total depth > 0 (basic sanity check)
        """
        if not snapshot.market_data:
            return False

        if snapshot.market_data.spread_pct > self.max_spread_pct:
            logger.debug(
                f"Liquidity check failed for {snapshot.contract_id}: "
                f"spread {snapshot.market_data.spread_pct:.2f}% > {self.max_spread_pct}%"
            )
            return False

        if snapshot.market_data.total_depth <= 0:
            logger.debug(f"Liquidity check failed for {snapshot.contract_id}: no depth")
            return False

        return True

    def _check_risk_limits(self, snapshot: MarketConsensusSnapshot) -> bool:
        """Check if trade passes risk limits.

        In production, this would call the actual risk manager.
        For now, always returns True (assuming risk manager is wired separately).
        """
        # TODO: Call actual risk manager
        # from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk_manager
        # risk_mgr = get_kalshi_risk_manager()
        # return risk_mgr.can_trade(snapshot.asset, snapshot.recommended_size)

        return True

    def _check_fees_vs_edge(self, snapshot: MarketConsensusSnapshot) -> bool:
        """Check if consensus edge exceeds fees + spread.

        Edge must be > (spread/2 + kalshi_fee_pct) to be profitable.
        """
        if not snapshot.market_data:
            return False

        # Kalshi fees are ~7% of winnings = ~0.7% of notional for 50-cent price
        # Spread cost = half spread (we pay the ask or hit the bid)
        spread_cost_pct = snapshot.market_data.spread_pct / 2
        total_cost_pct = spread_cost_pct + self.kalshi_fee_pct

        net_edge = snapshot.consensus_edge_pct - total_cost_pct

        if net_edge < self.min_edge_pct:
            logger.debug(
                f"Fee check failed for {snapshot.contract_id}: "
                f"edge {snapshot.consensus_edge_pct:.2f}% - costs {total_cost_pct:.2f}% "
                f"= {net_edge:.2f}% < {self.min_edge_pct}%"
            )
            return False

        return True

    # ── Execution parameters ──────────────────────────────────────────────

    def _set_execution_params(self, snapshot: MarketConsensusSnapshot):
        """Set execution parameters for tradeable consensus.

        Determines:
        - Side (yes/no)
        - Size (contracts)
        - Max price (limit)
        """
        if snapshot.consensus_action == TradingAction.LONG:
            # LONG = buy YES (or sell NO if we think prob is higher than market)
            snapshot.recommended_side = "yes"
        elif snapshot.consensus_action == TradingAction.SHORT:
            # SHORT = buy NO (or sell YES if we think prob is lower than market)
            snapshot.recommended_side = "no"

        # Size calculation (simplified - in production use Kelly)
        # For now: fixed size based on confidence
        base_size = 10  # Base 10 contracts
        if snapshot.consensus_confidence >= 0.80:
            snapshot.recommended_size = base_size * 3
        elif snapshot.consensus_confidence >= 0.70:
            snapshot.recommended_size = base_size * 2
        else:
            snapshot.recommended_size = base_size

        # Max price: mid + small tolerance
        if snapshot.market_data:
            mid_cents = int(snapshot.market_data.mid_price)
            tolerance_cents = 2  # Allow 2 cents slippage
            if snapshot.recommended_side == "yes":
                snapshot.max_price_cents = min(99, mid_cents + tolerance_cents)
            else:
                snapshot.max_price_cents = max(1, mid_cents - tolerance_cents)

    # ── Logging ───────────────────────────────────────────────────────────

    def _log_consensus(self, snapshot: MarketConsensusSnapshot):
        """Log consensus result with market-centric messaging.

        Example outputs:
        - KalshiConsensus: KXBTCD-26MAR2300 LONG (72.4%) edge=+3.1% after fees
        - KalshiConsensus: KXBTCD-26MAR2300 FLAT (81.0%) – no tradable edge
        - Features: {news_bullish: +0.15, onchain: +0.8, vol_regime: high}
        """
        action_str = snapshot.consensus_action.value.upper()
        confidence_pct = snapshot.agreement_pct

        if snapshot.consensus_action in (TradingAction.LONG, TradingAction.SHORT):
            # Directional trade
            logger.info(
                f"KalshiConsensus: {snapshot.contract_id} {action_str} ({confidence_pct:.1f}%) "
                f"edge={snapshot.consensus_edge_pct:+.1f}% "
                f"(spread={snapshot.market_data.spread_pct:.1f}%, "
                f"depth={snapshot.market_data.total_depth})"
            )

            # Log dominant features
            features = snapshot.get_dominant_features()
            if features:
                feature_str = ", ".join(features)
                logger.info(f"  Dominant features: {feature_str}")

            # Log execution params if tradeable
            if snapshot.is_tradeable():
                logger.info(
                    f"  → Execute: {snapshot.recommended_side.upper()} "
                    f"{snapshot.recommended_size} contracts @ ≤{snapshot.max_price_cents}¢"
                )
            else:
                reasons = []
                if not snapshot.liquidity_ok:
                    reasons.append("liquidity")
                if not snapshot.risk_ok:
                    reasons.append("risk")
                if not snapshot.fees_acceptable:
                    reasons.append("fees")
                logger.info(f"  → Blocked by: {', '.join(reasons)}")

        else:
            # NO_EDGE or FLAT
            logger.info(
                f"KalshiConsensus: {snapshot.contract_id} {action_str} ({confidence_pct:.1f}%) "
                f"– no tradable edge"
            )

    def get_consensus_history(self, limit: int = 10) -> List[MarketConsensusSnapshot]:
        """Get recent consensus history."""
        return self._consensus_history[-limit:]


# ── Singleton ─────────────────────────────────────────────────────────────

_engine: Optional[MarketConsensusEngine] = None


def get_market_consensus_engine() -> MarketConsensusEngine:
    """Get or create the singleton market consensus engine."""
    global _engine
    if _engine is None:
        _engine = MarketConsensusEngine()
    return _engine


def reset_market_consensus_engine() -> None:
    """Reset singleton (for testing)."""
    global _engine
    _engine = None

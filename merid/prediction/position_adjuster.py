"""Stateful position adjustment engine for Kalshi traders.

Tracks open positions per market and decides whether to buy more, reduce,
or close based on updated edge/Kelly signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from merid.prediction.agent_grid_config import AgentRiskLimits
from merid.prediction.model import EdgeEstimate, MarketSnapshot
from merid.prediction.strategy import ExpiryPhase, KalshiStrategy, SignalAction, StrategySignal
from utils.logger import get_logger


logger = get_logger("merid.prediction.position_adjuster")


@dataclass
class PositionView:
    """Internal view of an open position."""

    market_id: str
    side: str
    contracts: int
    avg_entry_cents: Decimal
    last_edge: Decimal = Decimal("0")
    last_model_prob: Decimal = Decimal("0.5")
    last_market_prob: Decimal = Decimal("0.5")
    last_target: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def signed_contracts(self) -> int:
        return self.contracts if self.side == "yes" else -self.contracts


class PositionAdjustmentEngine:
    """Decide per-cycle position adjustments (buy more vs sell/reduce)."""

    def __init__(
        self,
        strategy: KalshiStrategy,
        risk_limits: AgentRiskLimits,
        *,
        edge_epsilon: Decimal = Decimal("0.002"),
        min_increment: int = 1,
    ) -> None:
        self._strategy = strategy
        self._risk_limits = risk_limits
        self._edge_epsilon = edge_epsilon
        self._min_increment = max(1, min_increment)
        self._positions: Dict[str, PositionView] = {}

    # ------------------------------------------------------------------
    # Position state
    # ------------------------------------------------------------------

    @property
    def positions(self) -> Dict[str, PositionView]:
        return self._positions

    def apply_fill(
        self,
        market_id: str,
        side: str,
        action: str,
        contracts: int,
        price_cents: int,
        *,
        edge: Optional[EdgeEstimate] = None,
    ) -> None:
        """Update internal state with a filled order."""
        if contracts <= 0:
            return

        existing = self._positions.get(market_id)
        side = side.lower()
        action = action.lower()

        if existing and existing.side != side:
            # Opposite-side trade: reset state to new side
            existing = None

        if existing is None:
            if action == "sell":
                # Selling without a recorded position → nothing to track
                return
            self._positions[market_id] = PositionView(
                market_id=market_id,
                side=side,
                contracts=contracts,
                avg_entry_cents=Decimal(str(price_cents)),
                last_edge=edge.net_edge if edge else Decimal("0"),
                last_model_prob=edge.model_prob if edge else Decimal("0.5"),
                last_market_prob=edge.market_prob if edge else Decimal("0.5"),
                last_target=contracts,
            )
            return

        if action == "buy":
            total_contracts = existing.contracts + contracts
            existing.avg_entry_cents = (
                (existing.avg_entry_cents * existing.contracts + Decimal(str(price_cents)) * contracts)
                / total_contracts
            )
            existing.contracts = total_contracts
        elif action == "sell":
            existing.contracts = max(0, existing.contracts - contracts)

        if existing.contracts == 0:
            self._positions.pop(market_id, None)
        else:
            existing.updated_at = datetime.now(timezone.utc)
            if edge:
                existing.last_edge = edge.net_edge
                existing.last_model_prob = edge.model_prob
                existing.last_market_prob = edge.market_prob

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, snapshot: MarketSnapshot) -> Optional[StrategySignal]:
        """Return an adjustment signal for the given snapshot if needed."""
        pos = self._positions.get(snapshot.market_id)
        if not pos or pos.contracts <= 0:
            return None

        edge = self._find_edge(snapshot, pos.side)
        if edge is None:
            return None

        phase = self._strategy._expiry_phase(snapshot.time_to_expiry_hours)
        target_abs = self._target_size(edge, phase, snapshot, pos.side)
        target_signed = target_abs if pos.side == "yes" else -target_abs
        current_signed = pos.signed_contracts
        kelly_fraction = self._kelly_fraction(edge)

        action_signal: Optional[StrategySignal] = None

        # Decision 1: exit/reduce if edge deteriorated or flipped
        if edge.net_edge <= 0 or edge.net_edge < pos.last_edge - self._edge_epsilon or kelly_fraction <= Decimal("0"):
            if current_signed != 0:
                qty = abs(current_signed)
                action = SignalAction.SELL_YES if pos.side == "yes" else SignalAction.SELL_NO
                action_signal = StrategySignal(
                    market_id=snapshot.market_id,
                    action=action,
                    side=pos.side,
                    contracts=qty,
                    limit_price_cents=self._exit_price(snapshot, pos.side),
                    edge=edge,
                    phase=phase,
                    reason="edge_shrunk_close",
                )
        else:
            delta = target_signed - current_signed
            if target_abs > pos.contracts + self._min_increment and edge.net_edge > pos.last_edge + self._edge_epsilon:
                qty = abs(delta)
                action = SignalAction.BUY_YES if pos.side == "yes" else SignalAction.BUY_NO
                action_signal = StrategySignal(
                    market_id=snapshot.market_id,
                    action=action,
                    side=pos.side,
                    contracts=qty,
                    limit_price_cents=self._entry_price(snapshot, pos.side),
                    edge=edge,
                    phase=phase,
                    reason="edge_improved_buy_more",
                )
            elif abs(delta) >= self._min_increment and abs(target_signed) < abs(current_signed):
                qty = abs(current_signed - target_signed)
                action = SignalAction.SELL_YES if pos.side == "yes" else SignalAction.SELL_NO
                action_signal = StrategySignal(
                    market_id=snapshot.market_id,
                    action=action,
                    side=pos.side,
                    contracts=qty,
                    limit_price_cents=self._exit_price(snapshot, pos.side),
                    edge=edge,
                    phase=phase,
                    reason="edge_downsize",
                )

        # Update tracking regardless so next eval has fresh context
        pos.last_edge = edge.net_edge
        pos.last_model_prob = edge.model_prob
        pos.last_market_prob = edge.market_prob
        pos.last_target = target_abs
        pos.updated_at = datetime.now(timezone.utc)

        if action_signal:
            logger.info(
                "position_decision ticker=%s side=%s p_prev=%.4f p_now=%.4f edge_prev=%.4f edge_now=%.4f N_current=%s N_target=%s reason=%s",
                snapshot.market_id,
                pos.side,
                float(pos.last_model_prob),
                float(edge.model_prob),
                float(pos.last_edge),
                float(edge.net_edge),
                current_signed,
                target_signed,
                action_signal.reason,
            )
        return action_signal

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_edge(snapshot: MarketSnapshot, side: str) -> Optional[EdgeEstimate]:
        for edge in snapshot.edges:
            if edge.side == side and edge.action == "buy":
                return edge
        return None

    def _target_size(self, edge: EdgeEstimate, phase: ExpiryPhase, snapshot: MarketSnapshot, side: str) -> int:
        """Target total position size based on Kelly with risk caps."""
        size = self._strategy._kelly_size_with_sentiment(edge, phase, snapshot)
        cap_side = self._risk_limits.max_yes_position if side == "yes" else self._risk_limits.max_no_position
        size = min(size, cap_side, self._strategy.config.max_contracts_per_market)
        return max(0, size)

    @staticmethod
    def _kelly_fraction(edge: EdgeEstimate) -> Decimal:
        try:
            p = edge.model_prob
            q = Decimal("1") - p
            market_prob = edge.market_prob
            if market_prob <= Decimal("0") or market_prob >= Decimal("1"):
                return Decimal("0")
            b = (Decimal("1") / market_prob) - Decimal("1")
            if b <= Decimal("0"):
                return Decimal("0")
            kelly = (p * b - q) / b
            return kelly
        except (InvalidOperation, AttributeError):
            return Decimal("0")

    @staticmethod
    def _entry_price(snapshot: MarketSnapshot, side: str) -> Optional[int]:
        if side == "yes" and snapshot.implied.yes_ask is not None:
            return int(snapshot.implied.yes_ask)
        if side == "no" and snapshot.implied.no_ask is not None:
            return int(snapshot.implied.no_ask)
        return None

    @staticmethod
    def _exit_price(snapshot: MarketSnapshot, side: str) -> Optional[int]:
        if side == "yes" and snapshot.implied.yes_bid is not None:
            return int(snapshot.implied.yes_bid)
        if side == "no" and snapshot.implied.no_bid is not None:
            return int(snapshot.implied.no_bid)
        return None

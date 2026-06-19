"""Agent Performance Tracker - Real-time calibration and win rate tracking.

Tracks each Kalshi agent's performance metrics:
- Win rate (filled orders that closed profitable)
- Average edge realized vs predicted
- Confidence calibration (predicted vs actual outcomes)
- P&L attribution per agent
- Signal quality score

Usage::

    tracker = get_agent_performance_tracker()
    tracker.record_fill(agent_id, market_id, side, price, contracts)
    tracker.record_close(agent_id, market_id, profit_usd)
    metrics = tracker.get_agent_metrics(agent_id)
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.agent_performance_tracker")


@dataclass
class TradeRecord:
    """Record of a single trade (fill + eventual close)."""
    agent_id: str
    market_id: str
    side: str  # "yes" or "no"
    entry_price_cents: int
    contracts: int
    entry_ts: float
    predicted_edge: float
    confidence: float
    exit_price_cents: Optional[int] = None
    exit_ts: Optional[float] = None
    profit_usd: Optional[Decimal] = None
    realized_edge: Optional[float] = None
    outcome: Optional[str] = None  # "win", "loss", "scratch"


@dataclass
class AgentMetrics:
    """Performance metrics for a single agent."""
    agent_id: str
    total_fills: int = 0
    total_closes: int = 0
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    total_pnl_usd: Decimal = Decimal("0")
    avg_predicted_edge: float = 0.0
    avg_realized_edge: float = 0.0
    avg_confidence: float = 0.0
    calibration_error: float = 0.0  # Mean absolute error
    sharpe_ratio: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def win_rate(self) -> float:
        """Win rate as fraction (0.0 to 1.0)."""
        if self.total_closes == 0:
            return 0.0
        return self.wins / self.total_closes

    @property
    def avg_profit_per_trade(self) -> Decimal:
        """Average P&L per closed trade."""
        if self.total_closes == 0:
            return Decimal("0")
        return self.total_pnl_usd / self.total_closes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_fills": self.total_fills,
            "total_closes": self.total_closes,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 3),
            "total_pnl_usd": str(self.total_pnl_usd),
            "avg_profit_per_trade": str(self.avg_profit_per_trade),
            "avg_predicted_edge": round(self.avg_predicted_edge, 4),
            "avg_realized_edge": round(self.avg_realized_edge, 4),
            "edge_accuracy": round(self.avg_realized_edge - self.avg_predicted_edge, 4),
            "avg_confidence": round(self.avg_confidence, 3),
            "calibration_error": round(self.calibration_error, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "last_updated": self.last_updated.isoformat(),
        }


class AgentPerformanceTracker:
    """Tracks real-time performance metrics for all Kalshi trading agents.
    
    Maintains:
    - Open trade records (fills awaiting close)
    - Closed trade records (completed trades with P&L)
    - Aggregated metrics per agent
    - System-wide performance stats
    """

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history

        # Trade records
        self._open_trades: Dict[str, TradeRecord] = {}  # market_id -> record
        self._closed_trades: List[TradeRecord] = []

        # Metrics cache
        self._agent_metrics: Dict[str, AgentMetrics] = defaultdict(lambda: AgentMetrics(agent_id=""))
        self._last_recalc = 0.0
        self._recalc_interval = 30.0  # Recalculate every 30 seconds

        # Thread-safety lock
        self._lock = asyncio.Lock()

    # ── Recording ──────────────────────────────────────────────────

    async def record_fill(
        self,
        agent_id: str,
        market_id: str,
        side: str,
        price_cents: int,
        contracts: int,
        predicted_edge: float = 0.0,
        confidence: float = 0.5,
    ) -> None:
        """Record an order fill (trade entry).

        Args:
            agent_id: Agent that placed the order
            market_id: Kalshi market ticker
            side: "yes" or "no"
            price_cents: Fill price in cents
            contracts: Number of contracts filled
            predicted_edge: Agent's predicted edge (0.0 to 1.0)
            confidence: Agent's confidence in signal (0.0 to 1.0)
        """
        async with self._lock:
            record = TradeRecord(
                agent_id=agent_id,
                market_id=market_id,
                side=side,
                entry_price_cents=price_cents,
                contracts=contracts,
                entry_ts=time.time(),
                predicted_edge=predicted_edge,
                confidence=confidence,
            )

            # Key by market_id (assumes one position per market at a time)
            self._open_trades[market_id] = record

            # Update metrics
            metrics = self._agent_metrics[agent_id]
            if not metrics.agent_id:
                metrics.agent_id = agent_id
            metrics.total_fills += 1

            logger.debug(f"Recorded fill: {agent_id} {market_id} {side} {contracts}@{price_cents}¢")

    async def record_close(
        self,
        agent_id: str,
        market_id: str,
        exit_price_cents: int,
        profit_usd: Decimal,
    ) -> None:
        """Record a position close (trade exit).

        Args:
            agent_id: Agent that owned the position
            market_id: Kalshi market ticker
            exit_price_cents: Exit price in cents
            profit_usd: Realized P&L in USD
        """
        async with self._lock:
            # Find open trade
            if market_id not in self._open_trades:
                logger.warning(f"No open trade found for {market_id} close (agent={agent_id}, profit=${profit_usd})")
                # Create an orphan record with minimal information
                orphan_record = TradeRecord(
                    agent_id=agent_id,
                    market_id=market_id,
                    side="unknown",
                    entry_price_cents=0,
                    contracts=0,
                    entry_ts=time.time(),
                    predicted_edge=0.0,
                    confidence=0.5,
                    exit_price_cents=exit_price_cents,
                    exit_ts=time.time(),
                    profit_usd=profit_usd,
                    realized_edge=0.0,
                    outcome="orphan",
                )
                self._closed_trades.append(orphan_record)
                if len(self._closed_trades) > self._max_history:
                    self._closed_trades = self._closed_trades[-self._max_history:]
                return

            record = self._open_trades.pop(market_id)

            # Complete the record
            record.exit_price_cents = exit_price_cents
            record.exit_ts = time.time()
            record.profit_usd = profit_usd

            # Calculate realized edge
            entry = record.entry_price_cents / 100.0
            exit = exit_price_cents / 100.0
            record.realized_edge = abs(exit - entry)

            # Classify outcome
            if profit_usd > Decimal("1"):
                record.outcome = "win"
            elif profit_usd < Decimal("-1"):
                record.outcome = "loss"
            else:
                record.outcome = "scratch"

            # Store
            self._closed_trades.append(record)
            if len(self._closed_trades) > self._max_history:
                self._closed_trades = self._closed_trades[-self._max_history:]

            # Update metrics
            metrics = self._agent_metrics[agent_id]
            metrics.total_closes += 1
            metrics.total_pnl_usd += profit_usd

            if record.outcome == "win":
                metrics.wins += 1
            elif record.outcome == "loss":
                metrics.losses += 1
            else:
                metrics.scratches += 1

            metrics.last_updated = datetime.now(timezone.utc)

            logger.info(
                f"Recorded close: {agent_id} {market_id} "
                f"{record.outcome} P&L=${profit_usd:.2f}"
            )

        # Feed outcome back into ReflectionSystem for learning (outside lock to avoid deadlock)
        try:
            from agents.reflection.integration import get_reflection_system
            from agents.reflection.core import DecisionOutcome
            reflection_sys = get_reflection_system()
            # Find the most recent pending reflection for this agent+market
            agent_reflections = reflection_sys.core.get_agent_reflections(
                agent_id, limit=50
            )
            # Match by market_id in energy_id (format: "TICKER:timestamp")
            for ref in agent_reflections:
                from agents.reflection.core import DecisionOutcome as DO
                if ref.outcome == DO.PENDING and market_id in ref.energy_id:
                    # price_change proxy: positive for win, negative for loss
                    price_change = float(profit_usd) / max(record.contracts * record.entry_price_cents / 100.0, 0.01)
                    reflection_sys.validate_market_outcome(
                        reflection_id=ref.reflection_id,
                        actual_price_change=price_change,
                    )
                    break
        except Exception as exc:
            logger.debug(f"ReflectionSystem outcome feedback error (ignored): {exc}")

        # Trigger recalculation if needed (outside lock)
        if time.time() - self._last_recalc > self._recalc_interval:
            await self._recalculate_metrics()

    async def record_outcome(
        self,
        market_id: str,
        settled_yes: bool,
        settlement_price_cents: int = 100,
    ) -> None:
        """Record a Kalshi market settlement outcome.

        Called when a market resolves (YES=100c or NO=0c).  Finds the open
        trade for this market, computes realised P&L from the settlement price,
        closes the record, and triggers a promotion-engine eligibility check.

        Args:
            market_id: Kalshi ticker that settled.
            settled_yes: True if the YES contract paid out (resolved YES).
            settlement_price_cents: Settlement price in cents (100=YES, 0=NO).
        """
        async with self._lock:
            if market_id not in self._open_trades:
                logger.debug("record_outcome: no open trade for %s — skipping", market_id)
                return

            record = self._open_trades[market_id]
            agent_id = record.agent_id

            # Compute realised P&L in cents then convert to USD
            # YES holder: pnl = (settlement - entry) * contracts
            # NO  holder: pnl = ((100 - settlement) - (100 - entry)) * contracts
            #                  = (entry - settlement) * contracts
            if record.side == "yes":
                pnl_cents = (settlement_price_cents - record.entry_price_cents) * record.contracts
            else:
                pnl_cents = (record.entry_price_cents - settlement_price_cents) * record.contracts

            profit_usd = Decimal(str(round(pnl_cents / 100.0, 4)))

            logger.info(
                "record_outcome: %s settled_yes=%s pnl=$%.2f agent=%s",
                market_id, settled_yes, float(profit_usd), agent_id,
            )

        # Delegate to record_close which handles metrics + reflection feedback (outside lock to avoid deadlock)
        await self.record_close(
            agent_id=agent_id,
            market_id=market_id,
            exit_price_cents=settlement_price_cents,
            profit_usd=profit_usd,
        )

        # Trigger promotion-engine eligibility check
        try:
            from merid.promotion_report import run_promotion_check
            run_promotion_check(agent_id)
        except Exception as exc:
            logger.debug("promotion check skipped for %s: %s", agent_id, exc)

    # ── Metrics Retrieval ──────────────────────────────────────────

    async def get_agent_metrics(self, agent_id: str) -> AgentMetrics:
        """Get performance metrics for a specific agent."""
        async with self._lock:
            return self._agent_metrics.get(agent_id, AgentMetrics(agent_id=agent_id))

    async def get_all_metrics(self) -> Dict[str, AgentMetrics]:
        """Get metrics for all agents."""
        async with self._lock:
            return dict(self._agent_metrics)

    async def get_system_summary(self) -> Dict[str, Any]:
        """Get system-wide performance summary."""
        async with self._lock:
            all_metrics = list(self._agent_metrics.values())

            if not all_metrics:
                return {
                    "total_agents": 0,
                    "total_fills": 0,
                    "total_closes": 0,
                    "system_win_rate": 0.0,
                    "system_pnl_usd": "0",
                }

            total_closes = sum(m.total_closes for m in all_metrics)
            total_wins = sum(m.wins for m in all_metrics)
            total_pnl = sum(m.total_pnl_usd for m in all_metrics)

            return {
                "total_agents": len(all_metrics),
                "total_fills": sum(m.total_fills for m in all_metrics),
                "total_closes": total_closes,
                "system_win_rate": round(total_wins / total_closes, 3) if total_closes > 0 else 0.0,
                "system_pnl_usd": str(total_pnl),
                "avg_sharpe": round(
                    sum(m.sharpe_ratio for m in all_metrics) / len(all_metrics), 2
                ) if all_metrics else 0.0,
                "open_trades": len(self._open_trades),
                "closed_trades": len(self._closed_trades),
            }

    async def get_top_agents(self, metric: str = "win_rate", limit: int = 10) -> List[Dict[str, Any]]:
        """Get top performing agents by specified metric.

        Args:
            metric: Sort by "win_rate", "total_pnl_usd", "sharpe_ratio"
            limit: Number of agents to return
        """
        async with self._lock:
            agents = list(self._agent_metrics.values())

            # Filter agents with at least 10 closed trades
            agents = [a for a in agents if a.total_closes >= 10]

            # Sort
            if metric == "win_rate":
                agents.sort(key=lambda a: a.win_rate, reverse=True)
            elif metric == "total_pnl_usd":
                agents.sort(key=lambda a: a.total_pnl_usd, reverse=True)
            elif metric == "sharpe_ratio":
                agents.sort(key=lambda a: a.sharpe_ratio, reverse=True)

            return [a.to_dict() for a in agents[:limit]]

    # ── Calculation ────────────────────────────────────────────────

    async def _recalculate_metrics(self) -> None:
        """Recalculate aggregated metrics from trade history."""
        async with self._lock:
            self._last_recalc = time.time()

            # Group trades by agent
            trades_by_agent: Dict[str, List[TradeRecord]] = defaultdict(list)
            for trade in self._closed_trades:
                trades_by_agent[trade.agent_id].append(trade)

            # Calculate per-agent metrics
            for agent_id, trades in trades_by_agent.items():
                if not trades:
                    continue

                metrics = self._agent_metrics[agent_id]

                # Average edges
                metrics.avg_predicted_edge = sum(t.predicted_edge for t in trades) / len(trades)
                metrics.avg_realized_edge = sum(
                    t.realized_edge for t in trades if t.realized_edge is not None
                ) / len(trades)

                # Average confidence
                metrics.avg_confidence = sum(t.confidence for t in trades) / len(trades)

                # Calibration error (predicted edge vs realized)
                errors = [
                    abs(t.predicted_edge - (t.realized_edge or 0))
                    for t in trades if t.realized_edge is not None
                ]
                metrics.calibration_error = sum(errors) / len(errors) if errors else 0.0

                # Sharpe ratio (simplified)
                if len(trades) > 1:
                    pnls = [float(t.profit_usd or 0) for t in trades]
                    avg_pnl = sum(pnls) / len(pnls)
                    variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
                    std_dev = variance ** 0.5
                    metrics.sharpe_ratio = avg_pnl / std_dev if std_dev > 0 else 0.0

            logger.debug(f"Recalculated metrics for {len(trades_by_agent)} agents")

    async def compute_brier_score(self, agent_id: Optional[str] = None) -> Optional[float]:
        """Compute Brier score for an agent (or all agents if agent_id is None).

        Brier score = mean((confidence - outcome_binary)^2)
        where outcome_binary = 1 for win, 0 for loss/scratch.
        Lower is better; 0.25 is the no-skill baseline.

        Args:
            agent_id: Agent to compute for, or None for system-wide.

        Returns:
            Brier score float, or None if no closed trades with confidence data.
        """
        async with self._lock:
            trades = [
                t for t in self._closed_trades
                if t.outcome is not None and t.confidence is not None
                and (agent_id is None or t.agent_id == agent_id)
            ]
            if not trades:
                return None
            total = sum(
                (t.confidence - (1.0 if t.outcome == "win" else 0.0)) ** 2
                for t in trades
            )
            return round(total / len(trades), 4)

    # ── Export ─────────────────────────────────────────────────────

    async def get_closed_trade_count(self) -> int:
        """Return the number of closed trades in history."""
        async with self._lock:
            return len(self._closed_trades)

    async def export_trades_csv(self, filepath: str) -> None:
        """Export closed trades to CSV for analysis."""
        import csv

        async with self._lock:
            trades_snapshot = list(self._closed_trades)

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "agent_id", "market_id", "side", "entry_price", "exit_price",
                "contracts", "profit_usd", "predicted_edge", "realized_edge",
                "confidence", "outcome", "entry_ts", "exit_ts", "hold_duration_s"
            ])

            for trade in trades_snapshot:
                duration = (trade.exit_ts or 0) - trade.entry_ts
                writer.writerow([
                    trade.agent_id,
                    trade.market_id,
                    trade.side,
                    trade.entry_price_cents,
                    trade.exit_price_cents or 0,
                    trade.contracts,
                    str(trade.profit_usd or 0),
                    trade.predicted_edge,
                    trade.realized_edge or 0,
                    trade.confidence,
                    trade.outcome or "open",
                    trade.entry_ts,
                    trade.exit_ts or 0,
                    duration,
                ])

        logger.info(f"Exported {len(trades_snapshot)} trades to {filepath}")


# ── Singleton ──────────────────────────────────────────────────────

_tracker: Optional[AgentPerformanceTracker] = None


def get_agent_performance_tracker() -> AgentPerformanceTracker:
    """Return the module-level AgentPerformanceTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = AgentPerformanceTracker()
    return _tracker

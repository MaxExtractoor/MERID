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

import threading
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
    velocity: Optional[float] = None  # Spot velocity at signal time (used for side accuracy analysis)
    p_selected: Optional[float] = None  # model probability of the selected/held side (0-1)
    exit_price_cents: Optional[int] = None
    exit_ts: Optional[float] = None
    profit_usd: Optional[Decimal] = None
    realized_edge: Optional[float] = None
    outcome: Optional[str] = None  # "win", "loss", "scratch"


@dataclass
class AgentPerformanceMetrics:
    """Performance metrics for a single agent (renamed from AgentMetrics to avoid conflict with risk.agent_metrics)."""
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
        self._open_trades: Dict[str, TradeRecord] = {}  # "{agent_id}:{market_id}" -> record
        self._closed_trades: List[TradeRecord] = []
        
        # Metrics cache
        self._agent_metrics: Dict[str, AgentPerformanceMetrics] = defaultdict(lambda: AgentPerformanceMetrics(agent_id=""))
        self._last_recalc = 0.0
        self._recalc_interval = 30.0  # Recalculate every 30 seconds
        
        # Thread-safety lock for concurrent fill recording (BUG-UPSTREAM-2 fix)
        self._fill_lock = threading.RLock()

    # ── Recording ──────────────────────────────────────────────────

    def record_fill(
        self,
        agent_id: str,
        market_id: str,
        side: str,
        price_cents: int,
        contracts: int,
        predicted_edge: float = 0.0,
        confidence: float = 0.5,
        velocity: Optional[float] = None,
        p_selected: Optional[float] = None,
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
            velocity: Spot velocity at signal time (used for side accuracy analysis)
            p_selected: Model probability of the selected/held side (0.0 to 1.0)
        """
        # P0 FIX: Thread-safe fill recording with RLock (BUG-UPSTREAM-2)
        with self._fill_lock:
            record = TradeRecord(
                agent_id=agent_id,
                market_id=market_id,
                side=side,
                entry_price_cents=price_cents,
                contracts=contracts,
                entry_ts=time.time(),
                predicted_edge=predicted_edge,
                confidence=confidence,
                velocity=velocity,
                p_selected=p_selected,
            )
            
            # BUG-W fix: composite key prevents multi-agent same-market collision
            self._open_trades[f"{agent_id}:{market_id}"] = record
            
            # Update metrics
            metrics = self._agent_metrics[agent_id]
            if not metrics.agent_id:
                metrics.agent_id = agent_id
            metrics.total_fills += 1
        
        logger.debug(f"Recorded fill: {agent_id} {market_id} {side} {contracts}@{price_cents}¢")

    def record_close(
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
        # BUG-D1 fix: hold _fill_lock for the full read-modify-write on _open_trades
        with self._fill_lock:
            _trade_key = f"{agent_id}:{market_id}"
            if _trade_key in self._open_trades:
                record = self._open_trades.pop(_trade_key)
            else:
                # Fallback: try legacy key format (market_id only) for backward compatibility
                if market_id in self._open_trades:
                    record = self._open_trades.pop(market_id)
                    logger.debug(f"Fallback close for legacy key {market_id}")
                else:
                    logger.warning(f"No open trade found for {_trade_key} close")
                    return

            # Complete the record
            record.exit_price_cents = exit_price_cents
            record.exit_ts = time.time()
            record.profit_usd = profit_usd

            # Calculate realized edge (signed, not abs — BUG-W2 fix)
            # For YES: profit when exit > entry. For NO: profit when exit < entry.
            entry = record.entry_price_cents / 100.0
            exit_p = exit_price_cents / 100.0
            raw_edge = exit_p - entry
            if record.side == "no":
                raw_edge = -raw_edge  # NO profits when price falls
            record.realized_edge = raw_edge

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

        # Feed outcome back into ReflectionSystem for learning
        try:
            # Skip reflection for kalshi_crypto_15m_v2 profile
            import os
            profile = os.environ.get("MERID_PROFILE", "")
            if profile == "kalshi_crypto_15m_v2":
                return  # Skip reflection for 15m profile
                
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
                    price_change = float(profit_usd) / max(float(record.contracts) * record.entry_price_cents / 100.0, 0.01)
                    reflection_sys.validate_market_outcome(
                        reflection_id=ref.reflection_id,
                        actual_price_change=price_change,
                    )
                    break
        except Exception as exc:
            logger.debug(f"ReflectionSystem outcome feedback error (ignored): {exc}")

        # Trigger recalculation if needed
        if time.time() - self._last_recalc > self._recalc_interval:
            self._recalculate_metrics()

    def record_outcome(
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
        # BUG-D1b fix: take a locked snapshot of all records for this market before
        # computing P&L.  record_close() acquires _fill_lock internally; we must NOT
        # hold it here to avoid re-entrant locking (RLock allows it, but the intent
        # is cleaner: snapshot under lock, compute + delegate outside lock).
        with self._fill_lock:
            _outcome_keys = [k for k in self._open_trades if k.endswith(f":{market_id}")]
            _outcome_records = [
                (self._open_trades[k].agent_id,
                 self._open_trades[k].side,
                 self._open_trades[k].entry_price_cents,
                 self._open_trades[k].contracts)
                for k in _outcome_keys
            ]

        if not _outcome_records:
            logger.debug("record_outcome: no open trade for %s — skipping", market_id)
            return

        # Settle each agent's position for this market
        for agent_id, side, entry_price_cents, contracts in _outcome_records:
            # Compute realised P&L in cents then convert to USD
            # YES holder: pnl = (settlement - entry) * contracts
            # NO  holder: pnl = (entry - settlement) * contracts
            if side == "yes":
                pnl_cents = (settlement_price_cents - entry_price_cents) * contracts
            else:
                pnl_cents = (entry_price_cents - settlement_price_cents) * contracts

            profit_usd = Decimal(str(round(float(pnl_cents) / 100.0, 4)))

            logger.info(
                "record_outcome: %s settled_yes=%s pnl=$%.2f agent=%s",
                market_id, settled_yes, float(profit_usd), agent_id,
            )

            # Delegate to record_close which handles metrics + reflection feedback
            self.record_close(
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

    def get_agent_metrics(self, agent_id: str) -> AgentPerformanceMetrics:
        """Get performance metrics for a specific agent."""
        return self._agent_metrics.get(agent_id, AgentPerformanceMetrics(agent_id=agent_id))

    def get_all_metrics(self) -> Dict[str, AgentPerformanceMetrics]:
        """Get metrics for all agents."""
        return dict(self._agent_metrics)

    def get_system_summary(self) -> Dict[str, Any]:
        """Get system-wide performance summary."""
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

    def get_asset_performance(self, asset: str, min_trades: int = 20) -> Dict[str, Any]:
        """Get recent performance metrics for a specific asset (BTC, ETH, SOL, XRP, DOGE).
        
        Aggregates performance across all agents trading this asset.
        
        Args:
            asset: Asset code (e.g., "BTC", "ETH")
            min_trades: Minimum number of trades required for meaningful stats
            
        Returns:
            Dict with win_rate, total_trades, total_pnl_usd, avg_edge, and sufficient_data flag
        """
        # Filter closed trades by asset (extract from market_id)
        asset_trades = []
        for trade in self._closed_trades:
            # Extract asset from market_id (e.g., KXBTC15M-... -> BTC)
            if f"KX{asset}" in trade.market_id.upper():
                asset_trades.append(trade)
        
        # Take the most recent min_trades if available
        recent_trades = asset_trades[-min_trades:] if len(asset_trades) >= min_trades else asset_trades
        
        if not recent_trades:
            return {
                "asset": asset,
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl_usd": Decimal("0"),
                "avg_predicted_edge": 0.0,
                "avg_realized_edge": 0.0,
                "sufficient_data": False,
            }
        
        # Calculate metrics
        wins = sum(1 for t in recent_trades if t.outcome == "win")
        total_pnl = sum(t.profit_usd or Decimal("0") for t in recent_trades)
        avg_pred_edge = sum(t.predicted_edge for t in recent_trades) / len(recent_trades)
        avg_real_edge = sum(t.realized_edge or 0.0 for t in recent_trades) / len(recent_trades)
        
        return {
            "asset": asset,
            "total_trades": len(recent_trades),
            "win_rate": wins / len(recent_trades) if recent_trades else 0.0,
            "total_pnl_usd": total_pnl,
            "avg_predicted_edge": avg_pred_edge,
            "avg_realized_edge": avg_real_edge,
            "sufficient_data": len(recent_trades) >= min_trades,
        }

    def get_top_agents(self, metric: str = "win_rate", limit: int = 10) -> List[Dict[str, Any]]:
        """Get top performing agents by specified metric.
        
        Args:
            metric: Sort by "win_rate", "total_pnl_usd", "sharpe_ratio"
            limit: Number of agents to return
        """
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

    def _recalculate_metrics(self) -> None:
        """Recalculate aggregated metrics from trade history."""
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
            realized = [t.realized_edge for t in trades if t.realized_edge is not None]
            metrics.avg_realized_edge = sum(realized) / len(realized) if realized else 0.0
            
            # Average confidence
            metrics.avg_confidence = sum(t.confidence for t in trades) / len(trades)
            
            # Calibration error (predicted edge vs realized)
            errors = [
                abs(t.predicted_edge - (t.realized_edge or 0))
                for t in trades if t.realized_edge is not None
            ]
            metrics.calibration_error = sum(errors) / len(errors) if errors else 0.0
            
            # Sharpe ratio (simplified — sample std dev)
            if len(trades) > 1:
                pnls = [float(t.profit_usd or 0) for t in trades]
                avg_pnl = sum(pnls) / len(pnls)
                variance = sum((p - avg_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
                std_dev = variance ** 0.5
                metrics.sharpe_ratio = avg_pnl / std_dev if std_dev > 0 else 0.0
        
        logger.debug(f"Recalculated metrics for {len(trades_by_agent)} agents")

    def get_probability_bucket_report(
        self,
        bucket_width: float = 0.05,
        min_trades: int = 1,
    ) -> Dict[str, Any]:
        """Return realized win rate by model-probability bucket.

        Trades are bucketed by ``p_selected`` (the model probability of the
        side that was held).  For each bucket we report count, win rate, total
        PnL, and average predicted/realized edge so we can empirically verify
        calibration of the newly-admitted cheap-side EV trades.

        Args:
            bucket_width: Width of each probability bucket (default 0.05 = 5%).
            min_trades: Minimum number of trades required to report a bucket.

        Returns:
            Dict with bucket list and summary counts.
        """
        from collections import defaultdict

        buckets: Dict[int, List[TradeRecord]] = defaultdict(list)
        for trade in self._closed_trades:
            if trade.p_selected is None:
                continue
            bucket_idx = int(trade.p_selected / bucket_width)
            buckets[bucket_idx].append(trade)

        report = []
        for idx, trades in sorted(buckets.items()):
            if len(trades) < min_trades:
                continue
            wins = sum(1 for t in trades if t.outcome == "win")
            losses = sum(1 for t in trades if t.outcome == "loss")
            total = wins + losses
            win_rate = wins / total if total > 0 else 0.0
            total_pnl = sum(t.profit_usd or Decimal("0") for t in trades)
            avg_pred_edge = sum(t.predicted_edge for t in trades) / len(trades)
            realized_edges = [t.realized_edge for t in trades if t.realized_edge is not None]
            avg_real_edge = sum(realized_edges) / len(realized_edges) if realized_edges else 0.0
            lo = idx * bucket_width
            hi = lo + bucket_width
            report.append({
                "bucket": f"{lo:.2f}-{hi:.2f}",
                "count": len(trades),
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 4),
                "total_pnl_usd": str(total_pnl),
                "avg_predicted_edge": round(avg_pred_edge, 4),
                "avg_realized_edge": round(avg_real_edge, 4),
            })

        return {
            "bucket_width": bucket_width,
            "total_trades_with_p_selected": sum(len(v) for v in buckets.values()),
            "buckets": report,
        }

    def compute_brier_score(self, agent_id: Optional[str] = None) -> Optional[float]:
        """Compute Brier score for an agent (or all agents if agent_id is None).

        Brier score = mean((confidence - outcome_binary)^2)
        where outcome_binary = 1 for win, 0 for loss/scratch.
        Lower is better; 0.25 is the no-skill baseline.

        Args:
            agent_id: Agent to compute for, or None for system-wide.

        Returns:
            Brier score float, or None if no closed trades with confidence data.
        """
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

    def get_closed_trade_count(self) -> int:
        """Return the number of closed trades in history."""
        return len(self._closed_trades)

    def export_trades_csv(self, filepath: str) -> None:
        """Export closed trades to CSV for analysis."""
        import csv
        
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "agent_id", "market_id", "side", "entry_price", "exit_price",
                "contracts", "profit_usd", "predicted_edge", "realized_edge",
                "confidence", "outcome", "entry_ts", "exit_ts", "hold_duration_s"
            ])
            
            for trade in self._closed_trades:
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
        
        logger.info(f"Exported {len(self._closed_trades)} trades to {filepath}")


# ── Scalping Metrics ───────────────────────────────────────────────

@dataclass
class ScalpingMetrics:
    """Micro-scalping performance requirements and validation.
    
    For $44.35 micro bankrolls with rapid capital turnover:
    - 70% minimum win rate for profitability (after transaction costs)
    - $0.02 minimum profit per trade to justify Kalshi fees
    - Tracks last N trades for rolling window analysis
    """
    
    MIN_WIN_RATE: float = 0.70  # 70% minimum for scalping viability
    MIN_PROFIT_PER_TRADE_USD: Decimal = Decimal("0.02")  # $0.02 after fees
    WINDOW_SIZE: int = 30  # Last 30 trades for rolling metrics
    
    def validate_strategy_health(
        self,
        last_trades: List[TradeRecord],
    ) -> tuple[bool, str, Dict[str, Any]]:
        """Check if scalping strategy remains profitable.
        
        Args:
            last_trades: List of closed trades (last N)
            
        Returns:
            Tuple of (healthy, reason, metrics_dict)
        """
        if not last_trades:
            return False, "No trades to evaluate", {"trade_count": 0}
        
        # Win rate calculation
        closed = [t for t in last_trades if t.outcome is not None]
        if not closed:
            return False, "No closed trades", {"trade_count": 0}
        
        wins = sum(1 for t in closed if t.outcome == "win")
        win_rate = wins / len(closed)
        
        # Average profit on winning trades
        win_trades = [t for t in closed if t.outcome == "win" and t.profit_usd is not None]
        avg_profit = (
            sum(t.profit_usd for t in win_trades) / len(win_trades)
            if win_trades else Decimal("0")
        )
        
        # Average loss on losing trades
        loss_trades = [t for t in closed if t.outcome == "loss" and t.profit_usd is not None]
        avg_loss = (
            sum(t.profit_usd for t in loss_trades) / len(loss_trades)
            if loss_trades else Decimal("0")
        )
        
        metrics = {
            "trade_count": len(closed),
            "win_rate": round(win_rate, 3),
            "min_win_rate": self.MIN_WIN_RATE,
            "avg_profit_per_win": str(avg_profit.quantize(Decimal("0.01"))),
            "avg_loss_per_loss": str(avg_loss.quantize(Decimal("0.01"))),
            "min_profit_threshold": str(self.MIN_PROFIT_PER_TRADE_USD),
            "wins": wins,
            "losses": len(closed) - wins,
        }
        
        # Validation
        if win_rate < self.MIN_WIN_RATE:
            return False, (
                f"Win rate {win_rate:.1%} below {self.MIN_WIN_RATE:.0%} threshold "
                f"({wins}/{len(closed)} trades)"
            ), metrics
        
        if avg_profit < self.MIN_PROFIT_PER_TRADE_USD:
            return False, (
                f"Avg profit ${avg_profit:.2f} below min ${self.MIN_PROFIT_PER_TRADE_USD} "
                f"— transaction costs may be eroding profitability"
            ), metrics
        
        return True, "Strategy healthy", metrics
    
    def get_rolling_metrics(self, trades: List[TradeRecord]) -> Dict[str, Any]:
        """Get rolling window metrics for scalping performance."""
        recent = trades[-self.WINDOW_SIZE:] if len(trades) > self.WINDOW_SIZE else trades
        healthy, reason, metrics = self.validate_strategy_health(recent)
        
        return {
            "window_size": len(recent),
            "window_max": self.WINDOW_SIZE,
            "healthy": healthy,
            "status": reason,
            **metrics,
        }


# ── Singleton ──────────────────────────────────────────────────────

_tracker: Optional[AgentPerformanceTracker] = None
_tracker_lock = None


def get_agent_performance_tracker() -> AgentPerformanceTracker:
    """Return the module-level AgentPerformanceTracker singleton."""
    global _tracker
    if _tracker is None:
        if _tracker_lock is not None:
            with _tracker_lock:
                if _tracker is None:
                    _tracker = AgentPerformanceTracker()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _tracker = AgentPerformanceTracker()
    return _tracker

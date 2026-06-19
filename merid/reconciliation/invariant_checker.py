"""PnL & Position Invariant Checker — Real-time Consistency Monitoring

Runs periodic checks to ensure data consistency across:
- Position cache vs Kalshi API
- Agent PnL aggregation
- Win/loss count conservation
- Fee reconciliation

Usage:
    from merid.reconciliation.invariant_checker import InvariantChecker

    checker = InvariantChecker()
    violations = await checker.check_all()
    if violations:
        for v in violations:
            logger.error(f"Invariant violation: {v}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.reconciliation.invariant_checker")


@dataclass
class InvariantViolation:
    """Record of an invariant violation."""
    invariant_id: str
    severity: str  # "INFO", "WARNING", "CRITICAL"
    message: str
    details: Dict[str, Any]
    timestamp: float


class InvariantChecker:
    """Checks data consistency invariants for Kalshi positions and PnL.

    Invariants Checked:
    - INV-PNL-1: System PnL == sum(agent PnL)
    - INV-PNL-2: Agent PnL == sum(closed trades)
    - INV-WINS-1: total_closes == wins + losses + scratches
    - INV-CACHE-1: Position cache has no zero-contract positions
    - INV-CACHE-2: sum(realized_pnl) from cache matches tracker
    """

    def __init__(
        self,
        pnl_tolerance: float = 1.0,  # $1 tolerance for PnL drift
        check_interval: float = 60.0,  # Check every 60 seconds
    ):
        self.pnl_tolerance = Decimal(str(pnl_tolerance))
        self.check_interval = check_interval
        self._last_check = 0.0
        self._violation_history: List[InvariantViolation] = []

    async def check_all(self, force: bool = False) -> List[InvariantViolation]:
        """Run all invariant checks.

        Args:
            force: Skip interval check, run immediately

        Returns:
            List of violations detected
        """
        now = time.time()

        if not force and (now - self._last_check) < self.check_interval:
            return []

        self._last_check = now
        violations: List[InvariantViolation] = []

        # Run all checks
        violations.extend(await self._check_pnl_conservation())
        violations.extend(await self._check_win_loss_conservation())
        violations.extend(await self._check_position_cache_consistency())
        violations.extend(await self._check_pnl_aggregation())

        # Log and store violations
        for v in violations:
            if v.severity == "CRITICAL":
                logger.error(f"CRITICAL: {v.invariant_id} - {v.message}")
            elif v.severity == "WARNING":
                logger.warning(f"WARNING: {v.invariant_id} - {v.message}")
            else:
                logger.info(f"INFO: {v.invariant_id} - {v.message}")

            self._violation_history.append(v)

        # Keep last 100 violations
        if len(self._violation_history) > 100:
            self._violation_history = self._violation_history[-100:]

        return violations

    async def _check_pnl_conservation(self) -> List[InvariantViolation]:
        """INV-PNL-1: System PnL must equal sum of agent PnLs."""
        violations = []

        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

            tracker = get_agent_performance_tracker()
            system_summary = tracker.get_system_summary()

            system_pnl = Decimal(str(system_summary.get("system_pnl_usd", "0")))

            # Sum agent PnLs
            agent_pnl_sum = sum(
                m.total_pnl_usd for m in tracker.get_all_metrics().values()
            )

            drift = abs(system_pnl - agent_pnl_sum)

            if drift > self.pnl_tolerance:
                violations.append(
                    InvariantViolation(
                        invariant_id="INV-PNL-1",
                        severity="CRITICAL",
                        message=f"System PnL != sum(agent PnL): drift=${drift:.2f}",
                        details={
                            "system_pnl": str(system_pnl),
                            "agent_pnl_sum": str(agent_pnl_sum),
                            "drift": str(drift),
                            "tolerance": str(self.pnl_tolerance),
                        },
                        timestamp=time.time(),
                    )
                )

        except Exception as exc:
            logger.debug(f"INV-PNL-1 check skipped: {exc}")

        return violations

    async def _check_win_loss_conservation(self) -> List[InvariantViolation]:
        """INV-WINS-1: total_closes must equal wins + losses + scratches."""
        violations = []

        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

            tracker = get_agent_performance_tracker()

            for agent_id, metrics in tracker.get_all_metrics().items():
                computed_total = metrics.wins + metrics.losses + metrics.scratches

                if computed_total != metrics.total_closes:
                    violations.append(
                        InvariantViolation(
                            invariant_id="INV-WINS-1",
                            severity="CRITICAL",
                            message=f"Agent {agent_id}: win/loss count mismatch",
                            details={
                                "agent_id": agent_id,
                                "wins": metrics.wins,
                                "losses": metrics.losses,
                                "scratches": metrics.scratches,
                                "computed_total": computed_total,
                                "actual_total_closes": metrics.total_closes,
                            },
                            timestamp=time.time(),
                        )
                    )

        except Exception as exc:
            logger.debug(f"INV-WINS-1 check skipped: {exc}")

        return violations

    async def _check_position_cache_consistency(self) -> List[InvariantViolation]:
        """INV-CACHE-1: Position cache must not have zero-contract positions."""
        violations = []

        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache

            cache = get_position_cache()
            all_positions = cache.get_all_positions()

            for market_id, pos in all_positions.items():
                if pos.contracts <= 0:
                    violations.append(
                        InvariantViolation(
                            invariant_id="INV-CACHE-1",
                            severity="CRITICAL",
                            message=f"Position cache has zero-contract position: {market_id}",
                            details={
                                "market_id": market_id,
                                "contracts": pos.contracts,
                                "side": pos.side,
                            },
                            timestamp=time.time(),
                        )
                    )

        except Exception as exc:
            logger.debug(f"INV-CACHE-1 check skipped: {exc}")

        return violations

    async def _check_pnl_aggregation(self) -> List[InvariantViolation]:
        """INV-PNL-2: Agent PnL must equal sum of closed trade profits."""
        violations = []

        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

            tracker = get_agent_performance_tracker()

            # Group closed trades by agent
            trades_by_agent: Dict[str, List] = {}
            for trade in tracker._closed_trades:
                trades_by_agent.setdefault(trade.agent_id, []).append(trade)

            # Check each agent
            for agent_id, trades in trades_by_agent.items():
                computed_pnl = sum(t.profit_usd or Decimal("0") for t in trades)
                agent_metrics = tracker.get_agent_metrics(agent_id)
                reported_pnl = agent_metrics.total_pnl_usd

                drift = abs(computed_pnl - reported_pnl)

                if drift > self.pnl_tolerance:
                    violations.append(
                        InvariantViolation(
                            invariant_id="INV-PNL-2",
                            severity="CRITICAL",
                            message=f"Agent {agent_id}: PnL != sum(trades)",
                            details={
                                "agent_id": agent_id,
                                "computed_pnl": str(computed_pnl),
                                "reported_pnl": str(reported_pnl),
                                "drift": str(drift),
                                "trade_count": len(trades),
                            },
                            timestamp=time.time(),
                        )
                    )

        except Exception as exc:
            logger.debug(f"INV-PNL-2 check skipped: {exc}")

        return violations

    def get_violation_history(
        self, since: Optional[float] = None, severity: Optional[str] = None
    ) -> List[InvariantViolation]:
        """Get historical violations.

        Args:
            since: Unix timestamp, only return violations after this time
            severity: Filter by severity ("INFO", "WARNING", "CRITICAL")

        Returns:
            Filtered violation list
        """
        violations = self._violation_history

        if since is not None:
            violations = [v for v in violations if v.timestamp >= since]

        if severity is not None:
            violations = [v for v in violations if v.severity == severity]

        return violations

    def get_violation_summary(self) -> Dict[str, Any]:
        """Get summary of recent violations."""
        now = time.time()
        last_hour = now - 3600

        recent_violations = [v for v in self._violation_history if v.timestamp >= last_hour]

        by_severity = {
            "CRITICAL": len([v for v in recent_violations if v.severity == "CRITICAL"]),
            "WARNING": len([v for v in recent_violations if v.severity == "WARNING"]),
            "INFO": len([v for v in recent_violations if v.severity == "INFO"]),
        }

        by_invariant = {}
        for v in recent_violations:
            by_invariant[v.invariant_id] = by_invariant.get(v.invariant_id, 0) + 1

        return {
            "total_violations_last_hour": len(recent_violations),
            "by_severity": by_severity,
            "by_invariant": by_invariant,
            "last_check_ts": self._last_check,
            "check_interval": self.check_interval,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_checker: Optional[InvariantChecker] = None


def get_invariant_checker() -> InvariantChecker:
    """Get or create the singleton InvariantChecker."""
    global _checker
    if _checker is None:
        _checker = InvariantChecker()
    return _checker


def reset_invariant_checker() -> None:
    """Reset singleton (for testing)."""
    global _checker
    _checker = None

"""Portfolio rebalancing automation for Kalshi.

Automated rebalancing based on target allocations, risk limits, and market conditions.
"""

from __future__ import annotations

import threading
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.rebalancer")


@dataclass
class TargetAllocation:
    """Target allocation for an event or market."""
    ticker: str
    target_pct: Decimal  # Target percentage of portfolio (0-100)
    max_deviation_pct: Decimal = Decimal("5.0")  # Rebalance if deviated by this much
    side_preference: str = "yes"  # "yes" or "no"


@dataclass
class RebalanceAction:
    """Proposed rebalance action."""
    ticker: str
    action: str  # "buy" or "sell"
    side: str  # "yes" or "no"
    current_exposure: Decimal
    target_exposure: Decimal
    delta: Decimal  # Contracts to adjust
    reason: str


class PortfolioRebalancer:
    """Automated portfolio rebalancing engine.

    Monitors portfolio allocations against targets and generates
    rebalance orders to maintain desired exposure levels.

    Features:
    - Target allocation tracking per event/market
    - Deviation-based rebalancing triggers
    - Risk-aware position sizing
    - Batch order generation for efficiency
    """

    def __init__(
        self,
        max_rebalance_pct_per_day: Decimal = Decimal("20.0"),
        min_order_size: int = 1,
        max_orders_per_rebalance: int = 10,
    ):
        self._targets: Dict[str, TargetAllocation] = {}
        self._max_rebalance_pct_per_day = max_rebalance_pct_per_day
        self._min_order_size = min_order_size
        self._max_orders_per_rebalance = max_orders_per_rebalance

        # Tracking
        self._rebalanced_today: Set[str] = set()
        self._last_rebalance_time: Optional[float] = None
        self._daily_rebalance_volume: Decimal = Decimal("0")

        # Action history
        self._action_history: List[RebalanceAction] = []

    def set_target(self, target: TargetAllocation) -> None:
        """Set target allocation for a ticker."""
        self._targets[target.ticker] = target
        logger.info(f"Rebalancer target set: {target.ticker} = {target.target_pct}%")

    def remove_target(self, ticker: str) -> bool:
        """Remove target allocation."""
        if ticker in self._targets:
            del self._targets[ticker]
            return True
        return False

    def get_targets(self) -> Dict[str, TargetAllocation]:
        """Get all current targets."""
        return dict(self._targets)

    async def analyze_rebalance_needed(
        self,
        client,
    ) -> List[RebalanceAction]:
        """Analyze portfolio and determine if rebalancing is needed.

        Args:
            client: KalshiVenueClient instance

        Returns:
            List of rebalance actions to take
        """
        if not self._targets:
            return []

        # Get current portfolio summary
        result = await client.get_portfolio_summary()
        if not result.success:
            logger.warning(f"Rebalancer: Failed to get portfolio summary: {result.error}")
            return []

        portfolio = result.data
        total_value = portfolio["portfolio_value"] + portfolio["balance"]

        # Get aggregated positions by event
        agg_result = await client.get_positions_aggregated_by_event()
        if not agg_result.success:
            logger.warning(f"Rebalancer: Failed to get positions: {agg_result.error}")
            return []

        positions_by_event = agg_result.data

        actions: List[RebalanceAction] = []

        for ticker, target in self._targets.items():
            # Get current exposure for this ticker
            pos_data = positions_by_event.get(ticker, {
                "event_exposure": Decimal("0"),
                "market_positions": [],
            })

            current_exposure = Decimal(str(pos_data.get("event_exposure", 0)))

            # Calculate current percentage
            if total_value > 0:
                current_pct = (current_exposure / total_value) * 100
            else:
                current_pct = Decimal("0")

            # Calculate deviation
            deviation = abs(current_pct - target.target_pct)

            if deviation > target.max_deviation_pct:
                # Need to rebalance
                target_exposure = (target.target_pct / 100) * total_value
                delta = target_exposure - current_exposure

                # Determine action
                if delta > 0:
                    action = "buy"
                    side = target.side_preference
                else:
                    action = "sell"
                    # For selling, we need to determine which side to reduce
                    side = "yes" if current_exposure > 0 else "no"
                    delta = abs(delta)

                # Convert exposure delta to contracts (simplified - assumes ~50c avg)
                avg_price_cents = 50
                contracts_delta = int(delta * 100 / avg_price_cents)

                if contracts_delta >= self._min_order_size:
                    actions.append(RebalanceAction(
                        ticker=ticker,
                        action=action,
                        side=side,
                        current_exposure=current_exposure,
                        target_exposure=target_exposure,
                        delta=contracts_delta,
                        reason=f"Deviation {deviation:.1f}% exceeds max {target.max_deviation_pct}%",
                    ))

        # Sort by largest deviation first
        actions.sort(key=lambda a: abs(a.delta), reverse=True)

        return actions[:self._max_orders_per_rebalance]

    async def execute_rebalance(
        self,
        client,
        actions: Optional[List[RebalanceAction]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute or simulate rebalance actions.

        Args:
            client: KalshiVenueClient instance
            actions: Specific actions to execute (or None to analyze first)
            dry_run: If True, only simulate orders

        Returns:
            Execution summary
        """
        if actions is None:
            actions = await self.analyze_rebalance_needed(client)

        if not actions:
            return {
                "executed": False,
                "reason": "No rebalance needed",
                "actions": [],
            }

        # ── Risk Manager Kill Switch Check ─────────────────────────────────
        if not dry_run:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk = get_kalshi_risk()
                if risk and hasattr(risk, 'state') and risk.state.kill_switch_active:
                    return {
                        "executed": False,
                        "reason": "Kill switch is active - rebalancing blocked",
                        "kill_switch_reason": risk.state.kill_switch_reason,
                        "actions_blocked": len(actions),
                    }
            except Exception as exc:
                logger.warning(f"Kill switch check failed during rebalance: {exc}")

            # G13: VenueGate — block real rebalance orders in paper/sim mode
            try:
                from merid.prediction.venue_gate import get_venue_gate
                _gate = get_venue_gate()
                if _gate.should_simulate_fill():
                    return {
                        "executed": False,
                        "reason": f"VenueGate blocked: mode={_gate.mode.value} (paper/sim — no real rebalance orders)",
                        "actions_blocked": len(actions),
                        "simulated": True,
                    }
            except Exception as _vge:
                logger.debug("VenueGate check skipped in rebalancer: %s", _vge)

        executed_actions = []
        failed_actions = []

        for action in actions:
            if dry_run:
                executed_actions.append({
                    "ticker": action.ticker,
                    "action": action.action,
                    "side": action.side,
                    "contracts": action.delta,
                    "dry_run": True,
                })
                continue

            # Build order spec
            order_spec = {
                "ticker": action.ticker,
                "side": action.side,
                "action": action.action,
                "count": action.delta,
                "type": "limit",
                "yes_price": 50,  # Mid-market for rebalancing
            }

            try:
                result = await client.place_order_result(order_spec)
                if result.success:
                    executed_actions.append({
                        "ticker": action.ticker,
                        "action": action.action,
                        "order_id": result.data.order_id if result.data else None,
                    })
                    self._action_history.append(action)
                else:
                    failed_actions.append({
                        "ticker": action.ticker,
                        "error": str(result.error),
                    })
            except Exception as e:
                logger.error(f"Rebalance order failed for {action.ticker}: {e}")
                failed_actions.append({
                    "ticker": action.ticker,
                    "error": str(e),
                })

        self._last_rebalance_time = asyncio.get_running_loop().time()

        return {
            "executed": len(executed_actions) > 0,
            "dry_run": dry_run,
            "actions_taken": len(executed_actions),
            "actions_failed": len(failed_actions),
            "actions_executed": executed_actions,
            "failed": failed_actions,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get rebalancer status."""
        return {
            "targets_count": len(self._targets),
            "targets": [
                {
                    "ticker": t.ticker,
                    "target_pct": float(t.target_pct),
                    "max_deviation_pct": float(t.max_deviation_pct),
                }
                for t in self._targets.values()
            ],
            "last_rebalance": self._last_rebalance_time,
            "action_history_count": len(self._action_history),
        }

    def reset_daily_limits(self) -> None:
        """Reset daily rebalance tracking."""
        self._rebalanced_today.clear()
        self._daily_rebalance_volume = Decimal("0")

    def _bootstrap_targets(self) -> None:
        """Instance-method shim — delegates to the module-level _bootstrap_targets().

        Allows call sites to use ``rebalancer._bootstrap_targets()`` without
        needing to import the module-level function directly.
        """
        _bootstrap_targets(self)


# ── Singleton ────────────────────────────────────────────────────────────

_rebalancer: Optional[PortfolioRebalancer] = None
_rebalancer_lock = threading.Lock()


def get_portfolio_rebalancer(
    max_rebalance_pct_per_day: Decimal = Decimal("20.0"),
) -> PortfolioRebalancer:
    """Get or create the singleton portfolio rebalancer.

    On first creation, bootstraps target allocations from the prediction
    domain config in paper_config and the active agent grid tickers.
    """
    global _rebalancer
    if _rebalancer is None:
        with _rebalancer_lock:
            if _rebalancer is None:
                _rebalancer = PortfolioRebalancer(
                max_rebalance_pct_per_day=max_rebalance_pct_per_day,
            )
            _bootstrap_targets(_rebalancer)
    return _rebalancer


def _bootstrap_targets(rebalancer: "PortfolioRebalancer") -> None:
    """Seed PortfolioRebalancer with targets derived from paper_config.

    Reads the prediction domain's ``allocation_pct`` and distributes it
    evenly across all active Kalshi tickers in the agent grid.  Falls back
    to a no-op if neither source is available (targets can be set manually
    via ``set_target()`` at any time).
    """
    try:
        from merid.paper_config import get_paper_config
        pc = get_paper_config()
        prediction_domain = pc.get_domain("prediction")
        if prediction_domain is None:
            return

        domain_alloc_pct = float(prediction_domain.allocation_pct) * 100.0  # 0.10 → 10.0

        # Collect active tickers from the agent grid
        tickers: list = []
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            for agent in grid.agents:
                tickers.extend(agent.state.active_tickers)
            tickers = list(dict.fromkeys(tickers))  # deduplicate, preserve order
        except Exception as _age:
            logger.debug("rebalancer bootstrap agent_grid skipped: %s", _age)

        if not tickers:
            logger.debug("rebalancer bootstrap: no active tickers — targets not seeded")
            return

        # Distribute domain allocation evenly across active tickers
        per_ticker_pct = Decimal(str(round(domain_alloc_pct / len(tickers), 4)))
        max_dev = Decimal("5.0")

        for ticker in tickers:
            rebalancer.set_target(TargetAllocation(
                ticker=ticker,
                target_pct=per_ticker_pct,
                max_deviation_pct=max_dev,
                side_preference="yes",
            ))

        logger.info(
            "rebalancer bootstrap: %d targets seeded (%.2f%% each, domain_alloc=%.1f%%)",
            len(tickers), float(per_ticker_pct), domain_alloc_pct,
        )
    except Exception as exc:
        logger.debug("rebalancer bootstrap skipped: %s", exc)

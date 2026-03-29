"""Portfolio Risk Agent — Cross-asset exposure caps, net position limits, margin tracking.

Runs as a background task alongside the trading agents.  Periodically:
1. Fetches all Kalshi positions via kalshi_get_positions tool
2. Aggregates notional per asset, total notional, daily P&L
3. Enforces portfolio-level limits from PortfolioRiskConfig
4. Can pause individual trading agents if limits are breached

Reuses:
- PredictionMarketRisk for kill-switch / drawdown logic
- PredictionAlertManager for breach notifications
- kalshi_get_positions / kalshi_get_balance tools
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from merid.prediction.agent_grid_config import PortfolioRiskConfig
from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.prediction.trading_agent import KalshiTradingAgent

logger = get_logger("merid.prediction.portfolio_risk_agent")

ACTIVE_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state across all Kalshi agents."""
    timestamp: datetime
    total_notional_usd: Decimal = Decimal("0")
    notional_per_asset: Dict[str, Decimal] = field(default_factory=dict)
    open_market_count: int = 0
    daily_pnl_usd: Decimal = Decimal("0")
    available_balance_usd: Decimal = Decimal("0")
    locked_balance_usd: Decimal = Decimal("0")
    margin_utilization_pct: Decimal = Decimal("0")
    breaches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_notional_usd": str(self.total_notional_usd),
            "notional_per_asset": {k: str(v) for k, v in self.notional_per_asset.items()},
            "open_market_count": self.open_market_count,
            "daily_pnl_usd": str(self.daily_pnl_usd),
            "available_balance_usd": str(self.available_balance_usd),
            "locked_balance_usd": str(self.locked_balance_usd),
            "margin_utilization_pct": str(self.margin_utilization_pct),
            "breaches": self.breaches,
        }


class PortfolioRiskAgent:
    """Cross-asset portfolio risk monitor for the Kalshi agent grid.

    Usage::

        agent = PortfolioRiskAgent(config, trading_agents)
        await agent.start()
        ...
        await agent.stop()
    """

    def __init__(
        self,
        config: PortfolioRiskConfig,
        trading_agents: Optional[List["KalshiTradingAgent"]] = None,
    ):
        self._config = config
        self._agents = trading_agents or []
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._running = False

        # State
        self._latest_snapshot: Optional[PortfolioSnapshot] = None
        self._snapshots: List[PortfolioSnapshot] = []
        self._max_snapshots = 200
        self._kill_switch_active = False
        self._paused_agents: List[str] = []
        self._risk_alert_cooldown_seconds = int(os.getenv("MERID_RISK_ALERT_COOLDOWN_SECONDS", "180"))
        self._min_alert_exposure_usd = Decimal(os.getenv("MERID_RISK_MIN_ALERT_EXPOSURE_USD", "1"))
        self._last_alert_ts_by_key: Dict[str, float] = {}

    def set_agents(self, agents: List["KalshiTradingAgent"]) -> None:
        """Update the list of trading agents to monitor."""
        self._agents = agents

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the portfolio risk monitoring loop."""
        if self._running:
            return
        self._shutdown.clear()
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(), name="kalshi-portfolio-risk"
        )
        logger.info(
            f"Portfolio risk agent started: "
            f"max_notional=${self._config.max_total_notional_usd}, "
            f"max_daily_loss=${self._config.max_daily_loss_usd}, "
            f"check_interval={self._config.rebalance_check_interval_seconds}s"
        )

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._shutdown.set()
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Portfolio risk agent stopped")

    # ── Main loop ──────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        interval = self._config.rebalance_check_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._check_portfolio()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Portfolio risk check error: {exc}")

            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def _check_portfolio(self) -> None:
        """Run a single portfolio risk check."""
        now = datetime.now(timezone.utc)
        snapshot = PortfolioSnapshot(timestamp=now)

        # 1. Fetch positions
        try:
            from merid.prediction.kalshi_tools import _kalshi_get_positions, _kalshi_get_balance

            pos_result = await _kalshi_get_positions()
            bal_result = await _kalshi_get_balance()

            if pos_result.success:
                positions = pos_result.payload.get("positions", [])
                snapshot.open_market_count = len(positions)
                for asset in ACTIVE_CRYPTO_ASSETS:
                    snapshot.notional_per_asset.setdefault(asset, Decimal("0"))

                # Aggregate notional per asset
                for pos in positions:
                    ticker = pos.get("ticker", "")
                    size = Decimal(pos.get("size", "0"))
                    avg_price = Decimal(pos.get("avg_entry_price", "0"))
                    notional = abs(size) * avg_price

                    # Infer asset from ticker
                    asset = self._infer_asset(ticker)
                    snapshot.notional_per_asset[asset] = (
                        snapshot.notional_per_asset.get(asset, Decimal("0")) + notional
                    )
                    snapshot.total_notional_usd += notional

                    # Accumulate daily P&L
                    pnl = Decimal(pos.get("unrealized_pnl", "0"))
                    snapshot.daily_pnl_usd += pnl

            if bal_result.success:
                snapshot.available_balance_usd = Decimal(
                    bal_result.payload.get("available_usd", "0")
                )
                snapshot.locked_balance_usd = Decimal(
                    bal_result.payload.get("locked_usd", "0")
                )
                total_bal = snapshot.available_balance_usd + snapshot.locked_balance_usd
                if total_bal > 0:
                    snapshot.margin_utilization_pct = (
                        snapshot.locked_balance_usd / total_bal * 100
                    )

        except Exception as exc:
            logger.warning(f"Failed to fetch portfolio data: {exc}")
            return

        # 2. Check limits
        breaches = self._check_limits(snapshot)
        snapshot.breaches = breaches

        # 3. Store snapshot
        self._latest_snapshot = snapshot
        self._snapshots.append(snapshot)
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        # 3b. Feed live state into KalshiRiskManager so sizing-metrics / risk
        #     endpoints reflect real positions, not paper defaults.
        self._sync_to_risk_manager(snapshot)

        # 3c. Update PositionSizer realized vol from rolling PnL series.
        self._sync_to_position_sizer()

        # 3d. Sprint H: Publish RiskView message to streaming bus
        await self._publish_risk_view(snapshot, breaches)

        # 4. Enforce breaches
        if breaches:
            logger.warning(f"Portfolio risk breaches: {breaches}")
            self._emit_exposure_risk_alerts(snapshot, breaches)
            await self._enforce_breaches(breaches)

        # 5. Auto-rollback check for live agents
        self._check_agent_auto_rollback(snapshot)

    def _check_limits(self, snapshot: PortfolioSnapshot) -> List[str]:
        """Check portfolio against configured limits. Returns list of breach descriptions."""
        breaches: List[str] = []

        # Total notional
        if snapshot.total_notional_usd > self._config.max_total_notional_usd:
            breaches.append(
                f"Total notional ${snapshot.total_notional_usd} > "
                f"limit ${self._config.max_total_notional_usd}"
            )

        # Per-asset notional (with correlation-adjusted caps)
        for asset, notional in snapshot.notional_per_asset.items():
            if notional > self._config.max_notional_per_asset_usd:
                breaches.append(
                    f"{asset} notional ${notional} > "
                    f"limit ${self._config.max_notional_per_asset_usd}"
                )

        # Sprint D: Correlation-adjusted combined exposure check
        try:
            from merid.risk.correlation import get_correlation_tracker, ASSET_CLUSTERS
            corr_tracker = get_correlation_tracker()
            for cluster_name, members in ASSET_CLUSTERS.items():
                cluster_notional = sum(
                    snapshot.notional_per_asset.get(m.upper(), Decimal("0"))
                    for m in members
                )
                if cluster_notional <= 0:
                    continue
                # Get worst-case reduction factor for this cluster
                worst_factor = Decimal("1.0")
                for i, a in enumerate(members):
                    for b in members[i + 1:]:
                        f = corr_tracker.exposure_reduction_factor(a, b)
                        worst_factor = min(worst_factor, Decimal(str(f)))
                combined_cap = self._config.max_notional_per_asset_usd * Decimal(str(len(members))) * worst_factor
                if cluster_notional > combined_cap:
                    breaches.append(
                        f"Correlated cluster {cluster_name} notional ${cluster_notional} > "
                        f"correlation-adjusted cap ${combined_cap:.0f} (factor={worst_factor:.2f})"
                    )
        except Exception as exc:
            logger.debug(f"Correlation check skipped: {exc}")

        # Open markets
        if snapshot.open_market_count > self._config.max_open_markets:
            breaches.append(
                f"Open markets {snapshot.open_market_count} > "
                f"limit {self._config.max_open_markets}"
            )

        # Daily loss
        if snapshot.daily_pnl_usd < -self._config.max_daily_loss_usd:
            breaches.append(
                f"Daily loss ${abs(snapshot.daily_pnl_usd)} > "
                f"limit ${self._config.max_daily_loss_usd}"
            )

        # Margin utilization
        if snapshot.margin_utilization_pct > self._config.max_margin_utilization_pct:
            breaches.append(
                f"Margin utilization {snapshot.margin_utilization_pct}% > "
                f"limit {self._config.max_margin_utilization_pct}%"
            )

        return breaches

    def _emit_exposure_risk_alerts(self, snapshot: PortfolioSnapshot, breaches: List[str]) -> None:
        """Emit deduplicated risk-limit alerts from *real* exposure only."""
        if snapshot.open_market_count <= 0:
            return
        if snapshot.total_notional_usd < self._min_alert_exposure_usd:
            return
        now = time.monotonic()
        cap = self._config.max_notional_per_asset_usd
        for asset in ACTIVE_CRYPTO_ASSETS:
            exposure = snapshot.notional_per_asset.get(asset, Decimal("0"))
            if exposure <= cap:
                continue
            if exposure < self._min_alert_exposure_usd:
                continue
            key = f"risk_limit:{asset}:portfolio"
            last = self._last_alert_ts_by_key.get(key)
            if last is not None and (now - last) < self._risk_alert_cooldown_seconds:
                continue
            self._last_alert_ts_by_key[key] = now
            message = (
                f"{asset} portfolio capped: exposure=${float(exposure):.2f} / cap=${float(cap):.2f}; "
                f"positions_count={snapshot.open_market_count}; timeframe=portfolio."
            )
            data = {
                "asset": asset,
                "timeframe": "portfolio",
                "exposure_usd": float(exposure),
                "cap_usd": float(cap),
                "positions_count": snapshot.open_market_count,
            }
            try:
                mgr = getattr(self, "_alert_manager", None)
                if mgr is None:
                    from merid.prediction.alerts import get_alert_manager
                    mgr = get_alert_manager()
                mgr.fire_risk_breach(
                    market_id=f"{asset}:portfolio",
                    message=message,
                    data=data,
                )
            except Exception as exc:
                logger.debug("risk alert emit failed (%s): %s", asset, exc)

    async def _enforce_breaches(self, breaches: List[str]) -> None:
        """Pause agents when critical breaches detected."""
        if not breaches:
            return
        
        # Critical breaches that warrant immediate pause
        critical_keywords = ["Daily loss", "Total notional", "Margin utilization"]
        has_critical = any(any(kw in b for kw in critical_keywords) for b in breaches)
        
        if has_critical and not self._kill_switch_active:
            logger.error(f"CRITICAL PORTFOLIO BREACH - Pausing all agents: {breaches}")
            self._kill_switch_active = True

            # Pause all trading agents
            for agent in self._agents:
                if agent.state.enabled:
                    agent.pause()
                    if agent.config.name not in self._paused_agents:
                        self._paused_agents.append(agent.config.name)
                    logger.warning(f"Paused agent {agent.config.name} due to portfolio breach")

            # Fire alert via PredictionAlertManager
            try:
                from merid.prediction.alerts import get_alert_manager
                mgr = get_alert_manager()
                reason = "; ".join(breaches)
                mgr.fire_kill_switch(reason, unwind=False)
            except Exception as exc:
                logger.debug(f"Alert manager error (ignored): {exc}")

            # Telegram alert for critical portfolio breach
            try:
                import asyncio as _aio
                from merid.alerts.webhook_client import tg_send
                _aio.get_running_loop().create_task(tg_send(
                    f"\u26a0\ufe0f [PortfolioRiskAgent] Critical breach — all agents paused\n"
                    f"{chr(10).join(breaches)}"
                ))
            except RuntimeError:
                pass  # No running loop — Telegram skipped
            except Exception as _tg_exc:
                logger.debug("[portfolio_risk] Telegram failed: %s", _tg_exc)
            return

        # For per-asset or per-category breach — pause only relevant agents
        for breach in breaches:
            for agent in self._agents:
                # Check if agent trades the breached asset
                asset_match = any(asset.upper() in breach.upper() for asset in agent.config.assets)
                # Check if agent trades the breached category
                category_match = agent.config.category.upper() in breach.upper()

                if (asset_match or category_match) and agent.state.enabled:
                    agent.pause()
                    if agent.config.name not in self._paused_agents:
                        self._paused_agents.append(agent.config.name)
                    logger.warning(f"Paused {agent.config.name} due to breach: {breach}")

    async def _publish_risk_view(self, snapshot: PortfolioSnapshot, breaches: List[str]) -> None:
        """Sprint H: Publish a RiskView message to the streaming bus."""
        try:
            from merid.swarm.messages import RiskView, publish_risk_view
            risk_level = "low"
            if breaches:
                risk_level = "critical" if any("Daily loss" in b or "Total notional" in b for b in breaches) else "high"
            elif snapshot.margin_utilization_pct > 70:
                risk_level = "medium"

            rv = RiskView(
                risk_agent_id="portfolio_risk_agent",
                market_id="",  # Portfolio-level
                asset="ALL",
                risk_level=risk_level,
                max_size_contracts=0,
                kelly_fraction=0.0,
                edge_threshold_met=False,
                correlation_factor=1.0,
                exposure_pct=float(snapshot.margin_utilization_pct),
                flags=breaches,
            )
            await publish_risk_view(rv)
        except Exception as exc:
            logger.debug(f"RiskView publish failed: {exc}")

    def _check_agent_auto_rollback(self, snapshot: PortfolioSnapshot) -> None:
        """Check each live agent for auto-rollback conditions using DeploymentController."""
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            ctrl = get_deployment_controller()
        except Exception as _dce:
            logger.debug("_check_agent_auto_rollback: deployment controller unavailable: %s", _dce)
            return

        for agent in self._agents:
            if not agent.state.enabled:
                continue
            try:
                state_dict = agent.state.to_dict()
                pf = float(state_dict.get("profit_factor", 0.0))
                dd_pct = float(state_dict.get("max_drawdown_pct", 0.0))
                consec_losses = int(state_dict.get("consecutive_losses", 0))
                reason = ctrl.check_auto_rollback(
                    agent.config.name,
                    profit_factor=pf,
                    drawdown_pct=dd_pct,
                    consecutive_losses=consec_losses,
                )
                if reason:
                    logger.warning(
                        f"[portfolio-risk] Auto-rollback triggered for {agent.config.name}: {reason}"
                    )
            except Exception as exc:
                logger.debug(f"Auto-rollback check failed for {agent.config.name}: {exc}")

    def _sync_to_risk_manager(self, snapshot: PortfolioSnapshot) -> None:
        """Push live portfolio snapshot into KalshiRiskManager state."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk = get_kalshi_risk()
            state = risk.state
            # Overwrite with live values from Kalshi API
            state.total_notional_usd = float(snapshot.total_notional_usd)
            state.daily_pnl_usd = float(snapshot.daily_pnl_usd)
            # Equity = available + locked balance
            live_equity = float(snapshot.available_balance_usd + snapshot.locked_balance_usd)
            if live_equity > 0:
                state.current_equity_usd = live_equity
                if live_equity > state.peak_equity_usd:
                    state.peak_equity_usd = live_equity
            # Sync category notional from per-asset breakdown
            for asset, notional in snapshot.notional_per_asset.items():
                state.category_notional[asset.lower()] = float(notional)
            # Record equity snapshot for pnl-history endpoint
            if live_equity > 0:
                risk.record_equity_snapshot(live_equity)
            # Propagate kill switch if portfolio agent triggered it
            if self._kill_switch_active and not state.kill_switch_active:
                risk._activate_kill_switch("Portfolio risk agent: limit breach")
        except Exception as exc:
            logger.debug(f"_sync_to_risk_manager error (ignored): {exc}")

    def _sync_to_position_sizer(self) -> None:
        """Compute realized vol from rolling PnL series and push into PositionSizer."""
        if len(self._snapshots) < 5:
            return
        try:
            from merid.event_venues.kalshi.position_sizer import get_position_sizer
            sizer = get_position_sizer()
            # Compute rolling std-dev of daily_pnl as realized vol proxy
            pnls = [float(s.daily_pnl_usd) for s in self._snapshots[-50:]]
            if len(pnls) < 2:
                return
            mean = sum(pnls) / len(pnls)
            variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
            realized_vol = variance ** 0.5
            # Normalize: express as fraction of average equity
            avg_equity = sum(
                float(s.available_balance_usd + s.locked_balance_usd)
                for s in self._snapshots[-50:]
            ) / len(self._snapshots[-50:])
            if avg_equity > 0:
                realized_vol_frac = realized_vol / avg_equity
            else:
                realized_vol_frac = 0.02  # fallback
            sizer.update_vol_state(
                realized_vol=max(0.001, realized_vol_frac),
                kelly_util_pct=float(
                    self._latest_snapshot.margin_utilization_pct
                    if self._latest_snapshot else 0
                ),
            )
        except Exception as exc:
            logger.debug(f"_sync_to_position_sizer error (ignored): {exc}")

    def _infer_asset(self, ticker: str) -> str:
        """Infer asset from Kalshi ticker string using market catalog if possible."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            m = catalog.get_market(ticker)
            if m and m.asset:
                return m.asset
        except Exception as _ace:
            logger.debug("catalog asset lookup skipped for %s: %s", ticker, _ace)

        # Fallback to local inference
        ticker_upper = ticker.upper()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE", "PEPE", "WIF"]:
            if asset in ticker_upper:
                return asset
        return "OTHER"

    # ── Public API ─────────────────────────────────────────────────────

    def reset_kill_switch(self) -> None:
        """Reset kill switch and resume all paused agents."""
        self._kill_switch_active = False
        for agent in self._agents:
            if agent.config.name in self._paused_agents:
                agent.resume()
        self._paused_agents.clear()
        logger.info("Kill switch reset — all agents resumed")

    @property
    def latest_snapshot(self) -> Optional[PortfolioSnapshot]:
        return self._latest_snapshot

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable summary."""
        return {
            "running": self._running,
            "kill_switch_active": self._kill_switch_active,
            "paused_agents": self._paused_agents,
            "latest_snapshot": self._latest_snapshot.to_dict() if self._latest_snapshot else None,
            "config": {
                "max_total_notional_usd": str(self._config.max_total_notional_usd),
                "max_notional_per_asset_usd": str(self._config.max_notional_per_asset_usd),
                "max_open_markets": self._config.max_open_markets,
                "max_daily_loss_usd": str(self._config.max_daily_loss_usd),
                "max_margin_utilization_pct": str(self._config.max_margin_utilization_pct),
                "check_interval_s": self._config.rebalance_check_interval_seconds,
            },
            "snapshot_count": len(self._snapshots),
        }

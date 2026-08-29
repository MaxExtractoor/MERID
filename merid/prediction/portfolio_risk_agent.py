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

Risk limits now use core.settings (MAX_TOTAL_RISK_PCT, MAX_CYCLE_RISK_PCT, DAILY_LOSS_CAP_PCT)
instead of deprecated KALSHI_PORTFOLIO_MAX_* fields.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.settings import MAX_TOTAL_RISK_PCT, DAILY_LOSS_CAP_PCT, MAX_CYCLE_RISK_PCT
from merid.prediction.agent_grid_config import PortfolioRiskConfig
from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.prediction.trading_agent import KalshiTradingAgent

logger = get_logger("merid.prediction.portfolio_risk_agent")


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state across all Kalshi agents.
    
    DESIGN: Daily loss percentage is computed against starting_bankroll_usd (stable baseline)
    not current bankroll, to prevent pathological values like -119.61%.
    """
    timestamp: datetime
    total_notional_usd: Decimal = Decimal("0")
    notional_per_asset: Dict[str, Decimal] = field(default_factory=dict)
    open_market_count: int = 0
    daily_pnl_usd: Decimal = Decimal("0")
    starting_bankroll_usd: Decimal = Decimal("0")  # Bankroll at start of day (stable baseline)
    total_unrealized_pnl_usd: Decimal = Decimal("0")
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
            "total_unrealized_pnl_usd": str(self.total_unrealized_pnl_usd),
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
        self._start_stop_lock = asyncio.Lock()  # RACE-FIX: Protect start/stop from concurrent calls
        # Set after the first successful _check_portfolio() completes.
        # AgentGrid.start() waits on this before activating trading agents.
        self._ready_event = asyncio.Event()

        # State
        self._latest_snapshot: Optional[PortfolioSnapshot] = None
        self._snapshots: List[PortfolioSnapshot] = []
        self._max_snapshots = 200
        self._kill_switch_active = False
        self._paused_agents: List[str] = []
        self._startup_blocked_reason: Optional[str] = None  # Set if startup failed due to policy violation
        self._integrity_check_interval: float = 30.0  # Seconds between integrity checks
        self._last_integrity_check: Optional[datetime] = None
        self._integrity_issues: List[str] = []
        self._seen_uninferable_tickers: set = set()  # Rate-limit warnings per ticker
        self._starting_bankroll_usd: Decimal = Decimal("0")  # Stable baseline for daily loss %
        self._last_daily_reset_date: Optional[datetime] = None  # Track day rollover

    def set_agents(self, agents: List["KalshiTradingAgent"]) -> None:
        """Update the list of trading agents to monitor."""
        self._agents = agents

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the portfolio risk monitoring loop.
        
        LIVE MODE SAFETY: In live trading mode (KALSHI_ENV=live), this method
        enforces that risk limits match the bankroll-derived policy exactly.
        Any mismatch is treated as a hard error that prevents live trading.
        Use MERID_RISK_LIMIT_OVERRIDE=1 with explicit operator acknowledgment
        to bypass (logged as audit event).
        """
        async with self._start_stop_lock:
            if self._running:
                return
            self._shutdown.clear()
            self._ready_event.clear()
            self._running = True  # Set BEFORE creating task to prevent double-start
            self._task = asyncio.create_task(
                self._run_loop(), name="kalshi-portfolio-risk"
            )
        
        # Import settings for bankroll context in logs
        from merid.settings import settings
        import os
        
        # LIVE MODE: Validate Redis availability
        is_live_mode = os.environ.get("KALSHI_ENV", "").lower() == "live"
        redis_enabled = os.environ.get("MERID_REDIS_ENABLED", "1").strip() != "0"
        
        if is_live_mode and redis_enabled:
            try:
                from merid.infra.redis_resilient import get_resilient_redis, redis_health
                redis_client = get_resilient_redis()
                if redis_client is None:
                    error_msg = (
                        "REDIS_UNAVAILABLE_LIVE_BLOCK - Live mode requires Redis; "
                        "set MERID_REDIS_ENABLED=0 to degrade to in-memory fallback."
                    )
                    logger.error("=" * 60 + "\n" + error_msg + "\n" + "=" * 60)
                    self._kill_switch_active = True
                    self._startup_blocked_reason = error_msg
                    
                    # Fire critical alert
                    try:
                        from merid.prediction.alerts import get_alert_manager
                        mgr = get_alert_manager()
                        mgr.fire_kill_switch("Redis unavailable in live mode - startup blocked", unwind=False)
                    except Exception as e:
                        logger.debug(f"Kill switch alert failed: {e}")
                    
                    raise RuntimeError(error_msg)
                
                # Check actual health
                health = redis_health()
                if not health.get("healthy", False):
                    logger.warning(f"Redis connected but health check shows degraded: {health}")
                    # Don't block on degraded, just warn - the resilient client handles it
            except Exception as exc:
                # Redis check itself failed
                logger.error(f"Redis startup validation failed: {exc}")
                # In live mode, this is critical
                error_msg = f"REDIS_VALIDATION_FAILED_LIVE_BLOCK: {exc}"
                self._kill_switch_active = True
                self._startup_blocked_reason = error_msg
                raise RuntimeError(error_msg) from exc
        
        # CRITICAL FIX: Use live bankroll for self-check, not static settings
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        live_equity_usd = get_equity_for_risk_calc_sync()
        
        if live_equity_usd is not None and live_equity_usd > 0:
            bankroll_cents = int(live_equity_usd * 100)
            logger.info("[PORTFOLIO_RISK_SELF_CHECK] Using live bankroll: $%.2f", live_equity_usd)
        else:
            # Fail closed - no bankroll available from bankroll_service_v2
            logger.error("[PORTFOLIO_RISK_SELF_CHECK] Bankroll unavailable from bankroll_service_v2. Trading blocked.")
            bankroll_cents = 0
            
        # Use unified risk settings from core.settings (SINGLE SOURCE OF TRUTH)
        notional_pct = MAX_TOTAL_RISK_PCT * 100
        daily_loss_pct = DAILY_LOSS_CAP_PCT * 100
        per_asset_pct = MAX_CYCLE_RISK_PCT * 100
        
        # Self-check: verify derived values match expected bankroll * percentage
        expected_notional = int(bankroll_cents * MAX_TOTAL_RISK_PCT)
        expected_daily_loss = int(bankroll_cents * DAILY_LOSS_CAP_PCT)
        expected_per_asset = int(bankroll_cents * MAX_CYCLE_RISK_PCT)
        
        actual_notional = int(self._config.max_total_notional_usd * 100)
        actual_daily_loss = int(self._config.max_daily_loss_usd * 100)
        actual_per_asset = int(self._config.max_notional_per_asset_usd * 100)
        
        # Check for policy violations
        mismatches = []
        if actual_notional != expected_notional:
            mismatches.append(f"max_notional: actual=${actual_notional/100:.2f} != expected=${expected_notional/100:.2f}")
        if actual_daily_loss != expected_daily_loss:
            mismatches.append(f"max_daily_loss: actual=${actual_daily_loss/100:.2f} != expected=${expected_daily_loss/100:.2f}")
        if actual_per_asset != expected_per_asset:
            mismatches.append(f"max_per_asset: actual=${actual_per_asset/100:.2f} != expected=${expected_per_asset/100:.2f}")
        
        # LIVE MODE ENFORCEMENT: Hard fail if limits don't match policy
        is_live_mode = os.environ.get("KALSHI_ENV", "").lower() == "live"
        has_override = os.environ.get("MERID_RISK_LIMIT_OVERRIDE", "").strip() == "1"
        
        if mismatches and is_live_mode and not has_override:
            error_msg = (
                "RISK LIMIT POLICY VIOLATION - Live trading blocked\n"
                "Runtime risk limits do not match bankroll-derived policy:\n"
                + "\n".join(f"  - {m}" for m in mismatches)
                + "\nTo override (requires operator acknowledgment): MERID_RISK_LIMIT_OVERRIDE=1"
            )
            logger.error("=" * 60 + "\n" + error_msg + "\n" + "=" * 60)
            
            # Block live trading by activating kill switch
            self._kill_switch_active = True
            self._startup_blocked_reason = error_msg
            
            # Fire critical alert
            try:
                from merid.prediction.alerts import get_alert_manager
                mgr = get_alert_manager()
                mgr.fire_kill_switch("Risk limit policy violation - live mode blocked", unwind=False)
            except Exception as e:
                logger.debug(f"Risk limit alert failed: {e}")
                
            raise RuntimeError(error_msg)
        
        if mismatches and is_live_mode and has_override:
            # Log override as audit event
            logger.warning(
                "=" * 60 + "\n"
                "RISK LIMIT OVERRIDE ACTIVE - Operator acknowledged deviation\n"
                + "\n".join(f"  - {m}" for m in mismatches)
                + "\nOverride flag set: MERID_RISK_LIMIT_OVERRIDE=1"
                + "\n" + "=" * 60
            )
            # Record audit event
            try:
                from core.session_log import record_event
                record_event(
                    category="risk",
                    severity="warning",
                    title="Risk limit policy override",
                    detail="; ".join(mismatches),
                    metadata={"override": True, "live_mode": True}
                )
            except Exception:
                pass
        
        # Log configuration self-check
        status_mark = "✓" if not mismatches else "✗"
        logger.info(
            "=" * 60 + "\n"
            "PORTFOLIO RISK AGENT STARTUP - CONFIG SELF-CHECK\n"
            f"  Mode: {'LIVE' if is_live_mode else 'PAPER/DEMO'}\n"
            f"  Bankroll: ${bankroll_cents/100:.2f}\n"
            f"  MAX_TOTAL_RISK_PCT (core.settings): {MAX_TOTAL_RISK_PCT} ({notional_pct:.0f}%)\n"
            f"  DAILY_LOSS_CAP_PCT (core.settings): {DAILY_LOSS_CAP_PCT} ({daily_loss_pct:.0f}%)\n"
            f"  MAX_CYCLE_RISK_PCT (core.settings): {MAX_CYCLE_RISK_PCT} ({per_asset_pct:.0f}%)\n"
            f"  Derived: max_notional_cents={expected_notional} (bankroll × {notional_pct:.0f}%)\n"
            f"  Derived: max_daily_loss_cents={expected_daily_loss} (bankroll × {daily_loss_pct:.0f}%)\n"
            f"  Derived: max_per_asset_cents={expected_per_asset} (bankroll × {per_asset_pct:.0f}%)\n"
            f"  Actual config: max_notional=${self._config.max_total_notional_usd} {status_mark}\n"
            f"  Actual config: max_daily_loss=${self._config.max_daily_loss_usd} {status_mark}\n"
            f"  Actual config: max_per_asset=${self._config.max_notional_per_asset_usd} {status_mark}\n"
            f"  Check interval: {self._config.rebalance_check_interval_seconds}s\n"
            + (f"  Override: MERID_RISK_LIMIT_OVERRIDE=1\n" if has_override else "")
            + "=" * 60
        )

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        async with self._start_stop_lock:
            if not self._running:
                return  # Already stopped
            self._shutdown.set()
            self._running = False
            self._ready_event.set()  # unblock any waiters so they don't hang on shutdown
            if self._task and not self._task.done() and not self._task.cancelled():
                self._task.cancel()
        # Wait outside lock to avoid deadlock
        if self._task and not self._task.done():
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
                logger.warning(f"Portfolio risk check error (will retry): {exc}")

            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                logger.debug("silent catch in portfolio_risk_agent:139")

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

                # Aggregate notional per asset
                for pos in positions:
                    ticker = pos.get("ticker", "")
                    if not ticker:
                        # Position with no ticker — no asset to attribute risk to, skip silently
                        continue
                    size = Decimal(pos.get("size", "0"))
                    avg_price = Decimal(pos.get("avg_entry_price", "0"))
                    notional = abs(size) * avg_price

                    # Infer asset from ticker
                    asset = self._infer_asset(ticker)
                    if asset is None:
                        # Skip risk contribution for unknown assets - integrity gate will catch systematic issues
                        # Rate-limit: only warn once per ticker per session
                        is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
                        if ticker not in self._seen_uninferable_tickers:
                            self._seen_uninferable_tickers.add(ticker)
                            logger.warning(
                                "Skipping risk contribution for ticker=%s because asset could not be inferred. "
                                "Integrity gate will flag if this becomes systematic. "
                                "mode=%s session_tickers_affected=%d",
                                ticker,
                                "LIVE" if is_live else "PAPER",
                                len(self._seen_uninferable_tickers),
                                extra={
                                    "ticker": ticker,
                                    "mode": "live" if is_live else "paper",
                                    "event": "asset_inference_failed",
                                    "source": "portfolio_risk_agent",
                                }
                            )
                        continue
                    
                    snapshot.notional_per_asset[asset] = (
                        snapshot.notional_per_asset.get(asset, Decimal("0")) + notional
                    )
                    snapshot.total_notional_usd += notional

                    # Accumulate total unrealized PnL (informational only)
                    pnl = Decimal(pos.get("unrealized_pnl", "0"))
                    snapshot.total_unrealized_pnl_usd += pnl

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

        # 1b. Source daily PnL from KalshiRiskManager (properly resets daily)
        #     The unrealized_pnl from the API is CUMULATIVE (entry-to-now),
        #     NOT today's change — using it as "daily PnL" causes false
        #     kill switches on accounts with old losing positions (BUG-15).
        # Pull daily P&L from fills_ledger (canonical source), NOT from
        # risk.state.daily_pnl_usd which was stale because record_pnl() was
        # never called.  Falls back to KalshiRiskManager.summary() which also
        # syncs from fills_ledger now.
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            _ledger = get_fills_ledger()
            _s = _ledger.summary()
            # FIX: Include both realized and unrealized PnL for daily PnL to show mark-to-market performance
            daily_realized = float(_s.get("daily_realized_pnl_usd", 0))
            total_unrealized = float(_s.get("total_unrealized_pnl_usd", 0))
            snapshot.daily_pnl_usd = Decimal(str(round(daily_realized + total_unrealized, 4)))
        except Exception:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk = get_kalshi_risk()
                risk._sync_pnl_from_ledger()
                snapshot.daily_pnl_usd = Decimal(str(round(risk.state.daily_pnl_usd, 4)))
            except Exception:
                snapshot.daily_pnl_usd = Decimal("0")

        # 2. Check limits
        breaches = self._check_limits(snapshot)
        snapshot.breaches = breaches

        # 3. Store snapshot
        self._latest_snapshot = snapshot
        self._snapshots.append(snapshot)
        # Signal that the first check is complete — unblocks AgentGrid.start()
        self._ready_event.set()
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        # 3b. Feed live state into KalshiRiskManager so sizing-metrics / risk
        #     endpoints reflect real positions, not paper defaults.
        self._sync_to_risk_manager(snapshot)

        # 3b2. Update balance calibrator to trigger dynamic limit recalibration
        #      including computed drawdown thresholds based on equity tier
        try:
            from merid.event_venues.kalshi.balance_calibrator import (
                get_balance_calibrator,
                dollars_to_cents,
            )
            total_balance_cents = dollars_to_cents(
                snapshot.available_balance_usd + snapshot.locked_balance_usd
            )
            if total_balance_cents > 0:
                did_recalibrate = get_balance_calibrator().update(total_balance_cents)
                if did_recalibrate:
                    logger.info(
                        "[portfolio-risk] Balance calibrator triggered recalibration "
                        "— balance=$%.2f, dynamic drawdown thresholds updated",
                        total_balance_cents / 100.0
                    )
        except Exception as exc:
            logger.debug(f"[portfolio-risk] Balance calibrator update failed (non-fatal): {exc}")

        # 3c. Update PositionSizer realized vol from rolling PnL series.
        self._sync_to_position_sizer()

        # 3d. Sprint H: Publish RiskView message to streaming bus
        await self._publish_risk_view(snapshot, breaches)

        # 4. Enforce breaches OR auto-recover
        if breaches:
            logger.warning(f"Portfolio risk breaches: {breaches}")
            await self._enforce_breaches(breaches)
        elif self._kill_switch_active:
            # AUTO-RECOVERY: No breaches on this check — clear the kill switch
            # so trading can resume. The kill switch was a *transient* pause
            # triggered by a momentary limit breach, not a permanent halt.
            logger.info(
                "[portfolio-risk] AUTO-RECOVERY: All limits now within bounds — "
                "clearing kill switch and resuming paused agents"
            )
            self._kill_switch_active = False
            # Resume agents that were paused by _enforce_breaches
            for agent_name in list(self._paused_agents):
                for agent in self._agents:
                    if agent.config.name == agent_name:
                        try:
                            agent.resume()
                            logger.info(f"[portfolio-risk] Resumed agent {agent_name} after breach recovery")
                        except Exception as _re:
                            logger.debug(f"[portfolio-risk] Failed to resume {agent_name}: {_re}")
            self._paused_agents.clear()
            # Clear KalshiRiskManager kill switch too
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                _risk = get_kalshi_risk()
                if _risk.kill_switch_active and _risk.state.kill_switch_reason == "Portfolio risk agent: limit breach":
                    _risk.reset_kill_switch()
                    logger.info("[portfolio-risk] AUTO-RECOVERY: Cleared KalshiRiskManager kill switch")
            except Exception as _rme:
                logger.debug(f"[portfolio-risk] KalshiRiskManager reset failed: {_rme}")
            # Telegram notification for recovery
            try:
                import asyncio as _aio
                from merid.alerts.webhook_client import tg_send
                _aio.get_running_loop().create_task(tg_send(
                    "\u2705 [PortfolioRiskAgent] All limits recovered — kill switch cleared, agents resumed"
                ))
            except Exception as e:
                logger.debug(f"Recovery notification failed: {e}")

        # 5. Auto-rollback check for live agents
        self._check_agent_auto_rollback(snapshot)
        
        # 6. Periodic integrity check (every 30s)
        await self._run_periodic_integrity_check()

    def _check_limits(self, snapshot: PortfolioSnapshot) -> List[str]:
        """Check portfolio against configured limits. Returns list of breach descriptions."""
        breaches: List[str] = []
        
        # CRITICAL FIX: Use live bankroll from bankroll_service_v2, not static settings
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        live_equity_usd = get_equity_for_risk_calc_sync()
        
        if live_equity_usd is not None and live_equity_usd > 0:
            bankroll_usd = float(live_equity_usd)
            bankroll_cents = int(bankroll_usd * 100)
            logger.debug("[PORTFOLIO_RISK] Using live bankroll: $%.2f", bankroll_usd)
        else:
            # Fail closed - no bankroll available from bankroll_service_v2
            logger.error("[PORTFOLIO_RISK] Bankroll unavailable from bankroll_service_v2. Trading blocked.")
            bankroll_cents = 0
            bankroll_usd = 0.0

        # Total notional
        # 2026-07-08 UPDATE: Fixed $1 exposure model - disable percentage-based portfolio limits
        # The $1 fixed exposure cap is enforced at the order sizing level (unified_sizing.py)
        # Portfolio-level percentage limits are DISABLED to prevent conflicts with fixed $1 model
        # Check fixed $1 exposure cap instead
        from core.settings import FIXED_EXPOSURE_CAP_USD
        if snapshot.total_notional_usd > Decimal(str(FIXED_EXPOSURE_CAP_USD)):
            breaches.append(
                f"Total notional ${snapshot.total_notional_usd} > "
                f"fixed exposure cap ${FIXED_EXPOSURE_CAP_USD}"
            )

        # Per-asset notional (with correlation-adjusted caps)
        # 2026-07-08 UPDATE: Fixed $1 exposure model - disable percentage-based per-asset limits
        # The $1 fixed exposure cap is enforced at the order sizing level (unified_sizing.py)
        # Per-asset percentage limits are DISABLED to prevent conflicts with fixed $1 model
        # Check fixed $1 exposure cap instead (applies to total across all assets)
        for asset, notional in snapshot.notional_per_asset.items():
            # Per-asset check is now redundant with total $1 cap, but kept for visibility
            if notional > Decimal(str(FIXED_EXPOSURE_CAP_USD)):
                breaches.append(
                    f"{asset} notional ${notional} > "
                    f"fixed exposure cap ${FIXED_EXPOSURE_CAP_USD}"
                )

        # Sprint D: Correlation-adjusted combined exposure check
        # 2026-07-08 UPDATE: Fixed $1 exposure model - disable correlation-adjusted caps
        # The $1 fixed exposure cap is enforced at the order sizing level (unified_sizing.py)
        # Correlation-adjusted percentage limits are DISABLED to prevent conflicts with fixed $1 model
        # Check fixed $1 exposure cap instead (applies to total across all assets)
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
                # Check against fixed $1 exposure cap
                if cluster_notional > Decimal(str(FIXED_EXPOSURE_CAP_USD)):
                    breaches.append(
                        f"Correlated cluster {cluster_name} notional ${cluster_notional} > "
                        f"fixed exposure cap ${FIXED_EXPOSURE_CAP_USD}"
                    )
        except Exception as exc:
            logger.debug(f"Correlation check skipped: {exc}")

        # Open markets
        if snapshot.open_market_count > self._config.max_open_markets:
            breaches.append(
                f"Open markets {snapshot.open_market_count} > "
                f"limit {self._config.max_open_markets}"
            )

        # Daily loss - use stable baseline (starting_bankroll_usd) not current bankroll
        # Track day rollover to reset baseline
        today = datetime.now(timezone.utc).date()
        if self._last_daily_reset_date != today:
            # New day - capture starting bankroll
            if bankroll_usd > 0:
                self._starting_bankroll_usd = Decimal(str(bankroll_usd))
                self._last_daily_reset_date = today
                logger.info("[PORTFOLIO_RISK] New day detected, setting starting_bankroll_usd=%.2f", bankroll_usd)
        
        # Calculate percentage against stable baseline
        if self._starting_bankroll_usd > 0:
            loss_pct = (float(abs(snapshot.daily_pnl_usd)) / float(self._starting_bankroll_usd) * 100)
            # Sanity clamp to [-100, 100]
            if loss_pct < -100.0 or loss_pct > 100.0:
                logger.error(
                    "[DAILY-LOSS-SANITY-FAIL] portfolio loss_pct=%.2f%% outside valid range [-100, 100]. "
                    "daily_pnl=%.2f, starting_bankroll=%.2f. Clamping to valid range.",
                    loss_pct, float(snapshot.daily_pnl_usd), float(self._starting_bankroll_usd)
                )
                loss_pct = max(-100.0, min(100.0, loss_pct))
        else:
            # No valid baseline - disable percentage guard
            loss_pct = 0.0
        
        # Check absolute dollar limit AND percentage limit
        if snapshot.daily_pnl_usd < -self._config.max_daily_loss_usd:
            limit_pct = DAILY_LOSS_CAP_PCT * 100
            breaches.append(
                f"Daily loss ${abs(snapshot.daily_pnl_usd)} ({loss_pct:.1f}% of starting bankroll) > "
                f"limit ${self._config.max_daily_loss_usd} ({limit_pct:.0f}% of starting bankroll)"
            )
        elif loss_pct > DAILY_LOSS_CAP_PCT * 100:
            # Percentage-based guard (even if absolute dollar limit not hit)
            breaches.append(
                f"Daily loss percentage {loss_pct:.1f}% of starting bankroll > limit {DAILY_LOSS_CAP_PCT * 100:.0f}%"
            )

        # Margin utilization
        if snapshot.margin_utilization_pct > self._config.max_margin_utilization_pct:
            breaches.append(
                f"Margin utilization {snapshot.margin_utilization_pct}% > "
                f"limit {self._config.max_margin_utilization_pct}%"
            )

        return breaches

    async def _enforce_breaches(self, breaches: List[str]) -> None:
        """Pause agents when critical breaches detected.
        
        Kill switch activation is RESERVED for truly unrecoverable situations
        (daily loss limit). Notional/margin breaches pause agents but do NOT
        latch the kill switch — breaches may resolve when positions close or
        expire, and auto-recovery in _check_portfolio will resume agents.
        """
        if not breaches:
            return
        
        # CRITICAL (kill switch): Only daily loss warrants a hard halt —
        # once you've lost real money past the limit, you must stop.
        # Notional/margin breaches are transient — positions expire, sells
        # close exposure, and the next _check_portfolio will auto-recover.
        daily_loss_breach = any("Daily loss" in b for b in breaches)
        
        if daily_loss_breach and not self._kill_switch_active:
            logger.error(f"CRITICAL PORTFOLIO BREACH (daily loss) - Pausing all agents: {breaches}")
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

        # NON-DAILY-LOSS critical breaches (total notional, margin util):
        # Pause all agents temporarily but do NOT set kill switch.
        # Auto-recovery in _check_portfolio will resume them when limits clear.
        non_daily_critical = ["Total notional", "Margin utilization"]
        has_non_daily_critical = any(
            any(kw in b for kw in non_daily_critical) for b in breaches
        )
        if has_non_daily_critical:
            logger.warning(f"Portfolio exposure breach — pausing agents (auto-recoverable): {breaches}")
            for agent in self._agents:
                if agent.state.enabled:
                    agent.pause()
                    if agent.config.name not in self._paused_agents:
                        self._paused_agents.append(agent.config.name)
                    logger.warning(f"Paused agent {agent.config.name} due to exposure breach")
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
            # NOTE: Do NOT overwrite state.daily_pnl_usd here — it is
            # maintained by KalshiRiskManager.record_pnl() with proper
            # daily resets.  The old code corrupted it with cumulative
            # unrealized PnL (BUG-15 secondary).
            # Equity = available + locked balance
            live_equity = float(snapshot.available_balance_usd + snapshot.locked_balance_usd)
            if live_equity > 0:
                state.current_equity_usd = live_equity
                if live_equity > state.peak_equity_usd:
                    state.peak_equity_usd = live_equity
            # BUG-G fix: aggregate per-asset notional into category buckets.
            # Original code wrote keys like "btc"/"eth" but KalshiRiskManager
            # reads keys like "crypto"/"economics" — the sync was silently misaligned.
            try:
                from merid.event_venues.kalshi.category_exposure import (
                    infer_category as _infer_cat,
                )
                _cat_totals: dict = {}
                for asset, notional in snapshot.notional_per_asset.items():
                    _cat = _infer_cat(asset)
                    _cat_totals[_cat] = _cat_totals.get(_cat, 0.0) + float(notional)
                for _cat, _total in _cat_totals.items():
                    state.category_notional[_cat] = _total
            except Exception:
                # Fallback: original (misaligned) behaviour — non-fatal
                for asset, notional in snapshot.notional_per_asset.items():
                    state.category_notional[asset.lower()] = float(notional)
            # Record equity snapshot for pnl-history endpoint
            if live_equity > 0:
                risk.record_equity_snapshot(live_equity)
            # Propagate kill switch if portfolio agent triggered it.
            # Use direct state set instead of fire_kill_switch() to avoid
            # cascading to global risk_controller which persists to disk and
            # blocks trading across restarts (BUG: persistent kill switch).
            if self._kill_switch_active and not state.kill_switch_active:
                state.kill_switch_active = True
                state.kill_switch_reason = "Portfolio risk agent: limit breach"
                logger.warning("[portfolio-risk] Set KalshiRiskManager kill switch (local only, recoverable)")
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

    async def _run_periodic_integrity_check(self) -> None:
        """Run portfolio integrity check every 30 seconds.
        
        Cross-checks fills ledger, risk state, and Redis health to catch
        mismatches early before they compound into trading errors.
        """
        import os
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone.utc)
        
        # Check if enough time has passed since last check
        if (self._last_integrity_check is not None and 
            (now - self._last_integrity_check).total_seconds() < self._integrity_check_interval):
            return
        
        self._last_integrity_check = now
        
        try:
            # Gather components for integrity check
            fills_ledger = None
            risk_state = None
            portfolio_state = None
            
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                fills_ledger = get_fills_ledger()
            except Exception as e:
                logger.debug(f"Fills ledger unavailable: {e}")
            
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                risk = get_kalshi_risk()
                risk_state = risk.state if risk else None
            except Exception as e:
                logger.debug(f"Risk state unavailable: {e}")
            
            # Build simple portfolio state from latest snapshot
            if self._latest_snapshot:
                class SimplePortfolioState:
                    def __init__(self, snapshot):
                        self.positions = snapshot.notional_per_asset
                        self.total_exposure = float(snapshot.total_notional_usd)
                portfolio_state = SimplePortfolioState(self._latest_snapshot)
            
            # Run integrity check
            from core.execution_gate import check_portfolio_integrity
            from merid.settings import settings
            
            is_healthy, reason = check_portfolio_integrity(
                fills_ledger=fills_ledger,
                portfolio_state=portfolio_state,
                risk_state=risk_state,
                cfb_rti=None,  # CFB RTI checked separately
                settings=settings,
            )
            
            # Cache result for cheap status snapshot reads
            try:
                from merid.infra.status_snapshot import _update_cached_integrity_result
                _update_cached_integrity_result(is_healthy, reason)
            except Exception:
                pass  # Non-critical - cache update is optional
            
            self._integrity_issues = []
            if reason:
                if reason.startswith("CRITICAL:"):
                    self._integrity_issues.append(reason)
                    is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
                    if is_live:
                        logger.error(f"PORTFOLIO INTEGRITY CRITICAL: {reason}")
                        # Fire kill switch on critical issues in live mode
                        if not self._kill_switch_active:
                            self._kill_switch_active = True
                            try:
                                from merid.prediction.alerts import get_alert_manager
                                mgr = get_alert_manager()
                                mgr.fire_kill_switch(f"Portfolio integrity: {reason}", unwind=False)
                            except Exception:
                                pass
                    else:
                        logger.warning(f"Portfolio integrity issues: {reason}")
                else:
                    # DEGRADED - log but don't block
                    self._integrity_issues.append(reason)
                    logger.info(f"Portfolio integrity degraded: {reason}")
            
        except Exception as exc:
            logger.debug(f"Periodic integrity check error: {exc}")

    def _infer_asset(
        self,
        ticker: str,
        market_id: Optional[str] = None,
    ) -> Optional[str]:
        """Best-effort inference of asset from ticker/market identifiers.

        This method is designed for graceful degradation:
        - Uses in-process data first (market catalog, local cache)
        - Optionally enriches via Redis but never requires it
        - Returns None on failure (never raises) for integrity gate handling
        - Logs at appropriate levels for observability

        Args:
            ticker: Kalshi market ticker (e.g., "KXBTC-25DEC-ABOVE-100000")
            market_id: Optional market ID for catalog lookup

        Returns:
            Asset symbol (e.g., "BTC") or None if inference fails
        """
        if not ticker:
            logger.debug("_infer_asset: empty ticker provided")
            return None

        normalized_ticker = ticker.upper().strip()

        # 1) Short-circuit: check if we already inferred this ticker in this session
        cache_key = f"{normalized_ticker}:{market_id or ''}"
        if hasattr(self, '_asset_inference_cache'):
            cached = self._asset_inference_cache.get(cache_key)
            if cached:
                return cached
        else:
            self._asset_inference_cache = {}

        # 2) Try market catalog lookup (in-process, no external dependency)
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            # Try by ticker first
            m = catalog.get_market(normalized_ticker)
            if m and hasattr(m, 'asset') and m.asset:
                asset = m.asset.upper()
                self._asset_inference_cache[cache_key] = asset
                return asset
            # Try by market_id if provided
            if market_id:
                m = catalog.get_market(market_id)
                if m and hasattr(m, 'asset') and m.asset:
                    asset = m.asset.upper()
                    self._asset_inference_cache[cache_key] = asset
                    return asset
        except Exception as exc:
            # Catalog lookup failed - log debug, continue to fallback
            logger.debug("Market catalog lookup failed for %s: %s", normalized_ticker, exc)

        # 3) Optional Redis metadata enrichment (tolerant of failure)
        # Uses resilient Redis - returns None on failure, never raises
        try:
            from merid.infra.redis_resilient import redis_get
            redis_key = f"market_meta:{market_id or normalized_ticker}"
            meta = redis_get(redis_key)
            if meta:
                # Parse asset from metadata (implementation depends on your schema)
                # If metadata exists, extract asset field
                import json
                try:
                    meta_dict = json.loads(meta.decode('utf-8')) if isinstance(meta, bytes) else meta
                    if isinstance(meta_dict, dict) and 'asset' in meta_dict:
                        asset = meta_dict['asset'].upper()
                        self._asset_inference_cache[cache_key] = asset
                        return asset
                except (json.JSONDecodeError, AttributeError, KeyError):
                    pass  # Malformed metadata, continue to next fallback
        except Exception as exc:
            # Redis failure - log at debug, continue (graceful degradation)
            logger.debug("Redis unavailable when inferring asset for %s: %s", normalized_ticker, exc)

        # 4) Fallback: Kalshi series-prefix table (longest match), then substring keywords
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset

            mapped = kalshi_ticker_to_asset(normalized_ticker)
            if mapped:
                self._asset_inference_cache[cache_key] = mapped
                return mapped
        except Exception as exc:
            logger.debug("kalshi_ticker_to_asset fallback failed for %s: %s", normalized_ticker, exc)

        asset_keywords = [
            ("BTC", "BTC"),
            ("ETH", "ETH"),
            ("SOL", "SOL"),
            ("XRP", "XRP"),
            ("DOGE", "DOGE"),
            ("PEPE", "PEPE"),
            ("WIF", "WIF"),
            ("BONK", "BONK"),
            ("SHIB", "SHIB"),
        ]

        for keyword, asset in asset_keywords:
            if keyword in normalized_ticker:
                self._asset_inference_cache[cache_key] = asset
                return asset

        # 5) Category-based inference from ticker prefix
        # Kalshi tickers often start with category codes
        category_prefixes = {
            "KX": "CRYPTO",  # Kalshi crypto markets
            "KE": "ECONOMICS",  # Kalshi econ markets
            "KS": "SPORTS",  # Kalshi sports markets
        }
        for prefix, category in category_prefixes.items():
            if normalized_ticker.startswith(prefix):
                # Return category as pseudo-asset for risk bucketing
                self._asset_inference_cache[cache_key] = category
                return category

        # 6) Inference failed - log warning for integrity gate to catch
        logger.warning(
            "Unable to infer asset from ticker=%s market_id=%s; "
            "position/fill will be categorized as 'UNKNOWN' for risk calculation. "
            "Integrity gate will flag if this becomes systematic.",
            normalized_ticker,
            market_id,
        )

        # Cache the None to avoid repeated lookups
        self._asset_inference_cache[cache_key] = None
        return None

    # ── Public API ─────────────────────────────────────────────────────

    def is_crypto_vol_elevated(self, asset: str) -> bool:
        """Return True if realized vol for the asset is above its baseline.

        Uses CryptoRTIMonitor to check if vol ratio exceeds threshold.
        """
        try:
            from merid.risk.crypto_rti_monitor import get_crypto_rti_monitor
            monitor = get_crypto_rti_monitor()
            if monitor is None:
                return False
            
            metrics = monitor.get_rti_metrics(asset)
            if metrics is None:
                return False
            
            # Check if 60s vol is elevated (simple threshold)
            vol_60s = metrics.get("rti_60s_vol", 0.0)
            return vol_60s > 0.02  # 2% vol threshold
        except Exception:
            return False

    def get_exposure_pct(
        self,
        venue: str = "",
        category: str = "",
        product: str = "",
    ) -> float:
        """Return current notional exposure as a fraction of bankroll for the
        given venue/category/product filter.

        For crypto assets, uses per-asset notional from snapshot.
        Falls back to total margin utilisation when a latest snapshot exists,
        otherwise returns 0.0.
        """
        if self._latest_snapshot is None:
            return 0.0
        
        # If product is specified and it's a crypto asset, use per-asset exposure
        if product and category == "crypto":
            # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
            from merid.utils.kalshi_identity import extract_asset
            asset = extract_asset(product)
            if asset in self._latest_snapshot.notional_per_asset:
                asset_notional = float(self._latest_snapshot.notional_per_asset[asset])
                bankroll = float(self._latest_snapshot.starting_bankroll_usd)
                if bankroll > 0:
                    return asset_notional / bankroll
        
        # Fallback to total margin utilization
        return float(self._latest_snapshot.margin_utilization_pct) / 100.0

    def get_kelly_size_pct(
        self,
        asset: str = "",
        timeframe: str = "",
        edge: float = 0.0,
        confidence: float = 0.5,
    ) -> float:
        """Return a Kelly-fraction position size as a percent of bankroll.

        Delegates to PositionSizer when available; otherwise returns 0 (safe fail).
        """
        try:
            from merid.event_venues.kalshi.position_sizer import get_position_sizer
            sizer = get_position_sizer()
            return sizer.kelly_size_pct(edge=edge, confidence=confidence)
        except Exception as exc:
            logger.warning(f"[PORTFOLIO-RISK] PositionSizer failed, returning 0: {exc}")
            return 0.0  # Safe fail: no position sizing on error

    def reset_kill_switch(self) -> None:
        """Reset kill switch and resume all paused agents."""
        self._kill_switch_active = False
        for agent in self._agents:
            if agent.config.name in self._paused_agents:
                agent.resume()
        self._paused_agents.clear()
        logger.info("Kill switch reset — all agents resumed")

    async def wait_ready(self, timeout: float = 15.0) -> bool:
        """Wait until the first portfolio check completes. Returns True if ready, False on timeout."""
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def is_ready(self) -> bool:
        """True after the first successful portfolio snapshot."""
        return self._ready_event.is_set()

    @property
    def latest_snapshot(self) -> Optional[PortfolioSnapshot]:
        return self._latest_snapshot

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable summary with bankroll context."""
        # CRITICAL FIX: Use live bankroll for summary
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        from merid.settings import settings
        
        live_equity_usd = get_equity_for_risk_calc_sync()
        
        if live_equity_usd is not None and live_equity_usd > 0:
            bankroll_cents = int(live_equity_usd * 100)
        else:
            # Fail closed - no bankroll available
            bankroll_cents = 0
        return {
            "running": self._running,
            "kill_switch_active": self._kill_switch_active,
            "paused_agents": self._paused_agents,
            "latest_snapshot": self._latest_snapshot.to_dict() if self._latest_snapshot else None,
            "config": {
                "bankroll_cents": bankroll_cents,
                "max_total_notional_usd": str(self._config.max_total_notional_usd),
                "max_total_notional_pct": MAX_TOTAL_RISK_PCT,
                "max_notional_per_asset_usd": str(self._config.max_notional_per_asset_usd),
                "max_notional_per_asset_pct": MAX_CYCLE_RISK_PCT,
                "max_open_markets": self._config.max_open_markets,
                "max_daily_loss_usd": str(self._config.max_daily_loss_usd),
                "max_daily_loss_pct": DAILY_LOSS_CAP_PCT,
                "max_margin_utilization_pct": str(self._config.max_margin_utilization_pct),
                "check_interval_s": self._config.rebalance_check_interval_seconds,
            },
            "snapshot_count": len(self._snapshots),
        }

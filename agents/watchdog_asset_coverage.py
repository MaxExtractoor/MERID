"""Asset/Timeframe-Aware Watchdog Coordinator

Extends base watchdog with per-asset/timeframe coverage for:
- Data freshness monitoring per market series
- Execution health per asset/timeframe
- Aggregate exposure tracking per asset/timeframe
- Market availability checks

Usage:
    from agents.watchdog_asset_coverage import get_asset_watchdog_coordinator
    
    # Check BTC 15m health
    health = await coordinator.check_asset_timeframe_health("BTC", "15m")
    
    # Get full coverage report
    report = coordinator.get_coverage_report()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict

from agents.watchdog_agents import (
    WatchdogCoordinator,
    WatchdogAlert,
    LivenessWatchdog,
    ConsensusWatchdog,
    ModeWatchdog,
    StalenessWatchdog,
)
from agents.alert_manager import get_alert_manager, AlertSeverity
from config.kalshi_crypto_series_meta import SERIES_META_LIST, get_series_meta
from config.crypto_universe import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_TIMEFRAMES
from utils.logger import get_logger

logger = get_logger("agents.watchdog_asset_coverage")


@dataclass
class AssetTimeframeHealth:
    """Health status for a specific asset/timeframe combination."""
    asset: str
    timeframe: str
    series_ticker: str
    
    # Agent coverage
    assigned_agents: List[str] = field(default_factory=list)
    healthy_agents: int = 0
    paused_agents: int = 0
    
    # Data freshness
    last_price_update: Optional[float] = None
    data_staleness_seconds: float = float('inf')
    
    # Market state
    market_open: bool = False
    last_market_check: Optional[float] = None
    
    # Execution health
    recent_trades_count: int = 0
    failed_trades_count: int = 0
    
    # Risk exposure
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    
    # Overall status
    status: str = "unknown"  # healthy, degraded, critical, unknown
    issues: List[str] = field(default_factory=list)
    
    def compute_status(self) -> str:
        """Compute overall status from component health."""
        if self.data_staleness_seconds > 300:  # > 5 min stale
            self.issues.append(f"Data stale: {self.data_staleness_seconds:.0f}s")
            return "critical"
        
        if self.healthy_agents == 0 and self.assigned_agents:
            self.issues.append("No healthy agents")
            return "critical"
        
        if self.failed_trades_count > self.recent_trades_count * 0.3:  # > 30% failure
            self.issues.append(f"High trade failure rate: {self.failed_trades_count}/{self.recent_trades_count}")
            return "degraded"
        
        if self.data_staleness_seconds > 60:  # > 1 min stale
            self.issues.append(f"Data lag: {self.data_staleness_seconds:.0f}s")
            return "degraded"
        
        if self.healthy_agents < len(self.assigned_agents) // 2:
            self.issues.append(f"Only {self.healthy_agents}/{len(self.assigned_agents)} agents healthy")
            return "degraded"
        
        return "healthy"


class AssetTimeframeWatchdog:
    """
    Per-asset/timeframe watchdog that monitors coverage and health.
    """
    
    # Staleness thresholds per timeframe
    STALENESS_THRESHOLDS = {
        "15m": 60,      # 1 minute for 15m markets
        "1h": 300,      # 5 minutes for hourly
        "hourly": 300,
        "daily": 900,   # 15 minutes for daily
        "weekly": 1800, # 30 minutes for weekly
        "monthly": 3600,
    }
    
    def __init__(self):
        self._health_cache: Dict[Tuple[str, str], AssetTimeframeHealth] = {}
        self._cache_ttl = 5.0  # 5 second cache
        self._last_update: Dict[Tuple[str, str], float] = {}
        
    async def check_health(
        self,
        asset: str,
        timeframe: str,
        force_refresh: bool = False
    ) -> AssetTimeframeHealth:
        """
        Check health for specific asset/timeframe.
        
        Checks:
        - Data freshness from market state store
        - Agent liveness
        - Recent execution success/failure
        - Risk exposure
        """
        cache_key = (asset.upper(), timeframe.lower())
        
        # Check cache
        if not force_refresh:
            last = self._last_update.get(cache_key, 0)
            if time.time() - last < self._cache_ttl:
                return self._health_cache.get(cache_key, self._empty_health(asset, timeframe))
        
        # Build health record
        health = self._empty_health(asset, timeframe)
        
        # Get series ticker
        meta = get_series_meta(asset, timeframe)
        if meta:
            health.series_ticker = meta.series_ticker
        
        # Check agent coverage
        await self._check_agent_coverage(health)
        
        # Check data freshness
        await self._check_data_freshness(health)
        
        # Check execution health
        await self._check_execution_health(health)
        
        # Check exposure
        await self._check_exposure(health)
        
        # Compute status
        health.status = health.compute_status()
        
        # Update cache
        self._health_cache[cache_key] = health
        self._last_update[cache_key] = time.time()
        
        return health
    
    def _empty_health(self, asset: str, timeframe: str) -> AssetTimeframeHealth:
        """Create empty health record."""
        return AssetTimeframeHealth(
            asset=asset.upper(),
            timeframe=timeframe.lower(),
            series_ticker=f"KX{asset.upper()}",
        )
    
    async def _check_agent_coverage(self, health: AssetTimeframeHealth) -> None:
        """Check which agents cover this asset/timeframe."""
        try:
            from agents.agent_framework import get_agent_registry
            
            registry = get_agent_registry()
            all_agents = registry.get_all_agents()
            
            pattern = f"{health.asset}_{health.timeframe.upper().replace('H', 'H')}"
            
            for agent in all_agents:
                agent_id_upper = agent.agent_id.upper()
                
                # Check if agent covers this asset/timeframe
                covers = (
                    health.asset in agent_id_upper and
                    (health.timeframe in agent_id_upper or 
                     (health.timeframe == "1h" and "HOURLY" in agent_id_upper) or
                     (health.timeframe == "15m" and "15M" in agent_id_upper))
                )
                
                if covers:
                    health.assigned_agents.append(agent.agent_id)
                    
                    # Check if healthy
                    is_running = hasattr(agent, '_running') and getattr(agent, '_running', False)
                    is_paused = hasattr(agent, '_paused') and getattr(agent, '_paused', False)
                    
                    if is_running and not is_paused:
                        health.healthy_agents += 1
                    elif is_paused:
                        health.paused_agents += 1
        
        except Exception as exc:
            logger.error(f"Failed to check agent coverage: {exc}")
    
    async def _check_data_freshness(self, health: AssetTimeframeHealth) -> None:
        """Check data freshness from market state store."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            store = get_kalshi_market_state_store()
            state = store.get_state(health.series_ticker)
            
            if state and state.last_update_time:
                health.last_price_update = state.last_update_time
                health.data_staleness_seconds = time.time() - state.last_update_time
                health.market_open = state.is_tradable if hasattr(state, 'is_tradable') else True
                health.last_market_check = time.time()
        
        except Exception as exc:
            logger.debug(f"Failed to check data freshness: {exc}")
    
    async def _check_execution_health(self, health: AssetTimeframeHealth) -> None:
        """Check recent execution success/failure."""
        try:
            from core.decision_log import get_decision_log
            
            log = get_decision_log()
            # Query recent decisions for this asset/timeframe
            recent = log.get_recent_decisions(limit=100)
            
            for decision in recent:
                # Check if decision relates to this asset/timeframe
                if health.asset in str(decision.inputs) or health.timeframe in str(decision.inputs):
                    # Simple heuristic: OUTCOME vs decision match
                    if hasattr(decision, 'outcome'):
                        if decision.outcome.value == "success":
                            health.recent_trades_count += 1
                        elif decision.outcome.value == "failed":
                            health.failed_trades_count += 1
                            health.recent_trades_count += 1
        
        except Exception as exc:
            logger.debug(f"Failed to check execution health: {exc}")
    
    async def _check_exposure(self, health: AssetTimeframeHealth) -> None:
        """Check current exposure for this asset/timeframe."""
        try:
            from trading.paper_portfolio import get_paper_portfolio
            
            pf = get_paper_portfolio()
            
            gross = 0.0
            net = 0.0
            
            for position in pf.positions.values():
                # Check if position matches asset/timeframe
                symbol = getattr(position, 'symbol', '')
                if health.asset in symbol.upper():
                    value = getattr(position, 'market_value', 0.0)
                    gross += abs(value)
                    net += value
            
            health.gross_exposure = gross
            health.net_exposure = net
        
        except Exception as exc:
            logger.debug(f"Failed to check exposure: {exc}")


class AssetWatchdogCoordinator(WatchdogCoordinator):
    """
    Extended watchdog coordinator with per-asset/timeframe coverage.
    
    Adds:
    - Asset/timeframe health monitoring
    - Coverage gap detection
    - Series-level alerting
    """
    
    def __init__(
        self,
        expected_mode=None,
        check_interval_seconds: float = 30.0,
    ):
        super().__init__(expected_mode, check_interval_seconds)
        self._asset_watchdog = AssetTimeframeWatchdog()
        self._alert_manager = get_alert_manager()
        
        # Assets to monitor - use canonical lists from crypto_universe config
        self._monitored_assets = ACTIVE_CRYPTO_ASSETS
        self._monitored_timeframes = ACTIVE_CRYPTO_TIMEFRAMES
    
    async def _run_checks(self) -> List[WatchdogAlert]:
        """Run all watchdog checks including asset/timeframe coverage."""
        # Run base checks
        alerts = await super()._run_checks()
        
        # Run asset/timeframe checks
        asset_alerts = await self._check_asset_coverage()
        alerts.extend(asset_alerts)
        
        return alerts
    
    async def _check_asset_coverage(self) -> List[WatchdogAlert]:
        """Check coverage for all asset/timeframe combinations."""
        alerts = []
        now = time.time()
        
        for asset in self._monitored_assets:
            for timeframe in self._monitored_timeframes:
                health = await self._asset_watchdog.check_health(asset, timeframe)
                
                # Generate alerts based on status
                if health.status == "critical":
                    alert = WatchdogAlert(
                        alert_id=f"asset_critical_{asset}_{timeframe}_{int(now)}",
                        watchdog_type="asset_coverage",
                        severity="critical",
                        agent_id=None,
                        symbol=f"{asset}-{timeframe}",
                        message=f"Critical health for {asset} {timeframe}: {', '.join(health.issues)}",
                        details={
                            "asset": asset,
                            "timeframe": timeframe,
                            "series_ticker": health.series_ticker,
                            "healthy_agents": health.healthy_agents,
                            "total_agents": len(health.assigned_agents),
                            "data_staleness": health.data_staleness_seconds,
                            "gross_exposure": health.gross_exposure,
                            "issues": health.issues,
                        }
                    )
                    alerts.append(alert)
                    
                    # Also send to alert manager
                    await self._alert_manager.alert(
                        severity=AlertSeverity.CRITICAL,
                        title=f"Asset Health Critical: {asset} {timeframe}",
                        message=f"{', '.join(health.issues)}",
                        source="asset_watchdog",
                        affected_assets=[asset],
                        affected_timeframes=[timeframe],
                        metadata={
                            "series_ticker": health.series_ticker,
                            "agent_count": len(health.assigned_agents),
                            "healthy_count": health.healthy_agents,
                        }
                    )
                
                elif health.status == "degraded":
                    alert = WatchdogAlert(
                        alert_id=f"asset_degraded_{asset}_{timeframe}_{int(now)}",
                        watchdog_type="asset_coverage",
                        severity="warning",
                        agent_id=None,
                        symbol=f"{asset}-{timeframe}",
                        message=f"Degraded health for {asset} {timeframe}: {', '.join(health.issues)}",
                        details={
                            "asset": asset,
                            "timeframe": timeframe,
                            "issues": health.issues,
                        }
                    )
                    alerts.append(alert)
        
        return alerts
    
    def get_coverage_report(self) -> Dict[str, Any]:
        """Get full coverage report for all assets/timeframes."""
        # Use cached data
        report = {
            "generated_at": time.time(),
            "assets": {},
            "timeframes": {},
            "overall": {
                "total_combinations": 0,
                "healthy": 0,
                "degraded": 0,
                "critical": 0,
                "unknown": 0,
            },
            "coverage_matrix": {}
        }
        
        for asset in self._monitored_assets:
            report["assets"][asset] = {"timeframes": {}}
            
            for timeframe in self._monitored_timeframes:
                cache_key = (asset, timeframe)
                health = self._asset_watchdog._health_cache.get(cache_key)
                
                if health:
                    report["assets"][asset]["timeframes"][timeframe] = {
                        "status": health.status,
                        "agents": {
                            "total": len(health.assigned_agents),
                            "healthy": health.healthy_agents,
                            "paused": health.paused_agents,
                        },
                        "data": {
                            "staleness_seconds": health.data_staleness_seconds,
                            "market_open": health.market_open,
                        },
                        "exposure": {
                            "gross": health.gross_exposure,
                            "net": health.net_exposure,
                        },
                        "issues": health.issues,
                    }
                    
                    # Update overall stats
                    report["overall"]["total_combinations"] += 1
                    report["overall"][health.status] += 1
                    
                    # Build matrix
                    matrix_key = f"{asset}-{timeframe}"
                    report["coverage_matrix"][matrix_key] = health.status
        
        # Aggregate by timeframe
        for timeframe in self._monitored_timeframes:
            tf_stats = {"healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}
            for asset in self._monitored_assets:
                cache_key = (asset, timeframe)
                health = self._asset_watchdog._health_cache.get(cache_key)
                if health:
                    tf_stats[health.status] += 1
            report["timeframes"][timeframe] = tf_stats
        
        return report
    
    async def force_health_check(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None
    ) -> Dict[str, Any]:
        """Force immediate health check for specific asset/timeframe or all."""
        if asset and timeframe:
            health = await self._asset_watchdog.check_health(asset, timeframe, force_refresh=True)
            return {
                "asset": asset,
                "timeframe": timeframe,
                "health": {
                    "status": health.status,
                    "agents_total": len(health.assigned_agents),
                    "agents_healthy": health.healthy_agents,
                    "data_staleness": health.data_staleness_seconds,
                    "exposure_gross": health.gross_exposure,
                    "exposure_net": health.net_exposure,
                    "issues": health.issues,
                }
            }
        else:
            # Check all
            results = {}
            for a in self._monitored_assets:
                for tf in self._monitored_timeframes:
                    health = await self._asset_watchdog.check_health(a, tf, force_refresh=True)
                    results[f"{a}-{tf}"] = {
                        "status": health.status,
                        "issues": health.issues,
                    }
            return {"health_checks": results}


# Global instance
_asset_watchdog_coordinator: Optional[AssetWatchdogCoordinator] = None


def get_asset_watchdog_coordinator(expected_mode=None) -> AssetWatchdogCoordinator:
    """Get or create global asset watchdog coordinator."""
    global _asset_watchdog_coordinator
    if _asset_watchdog_coordinator is None:
        _asset_watchdog_coordinator = AssetWatchdogCoordinator(expected_mode)
    return _asset_watchdog_coordinator

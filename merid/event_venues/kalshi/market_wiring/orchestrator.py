"""
Kalshi Market Wiring Orchestrator

Main coordinator for the complete market wiring layer that ensures
full coverage, explicit mapping, and strong safety constraints.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, List, Optional, Any

from merid.event_venues.kalshi.market_wiring.models import (
    MarketMapping,
    KalshiMarketRecord,
    MarketContextConfig,
)
from merid.event_venues.kalshi.market_wiring.safety import SafetyCheckResult, ContextStatus
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.market_wiring.sync import get_kalshi_universe_sync
from merid.event_venues.kalshi.market_wiring.mapping import get_market_mapping_builder
from merid.event_venues.kalshi.market_wiring.safety import get_kalshi_safety_layer
from merid.event_venues.kalshi.market_wiring.coverage import get_kalshi_coverage_checker
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.orchestrator")


class KalshiWiringOrchestrator:
    """Main orchestrator for Kalshi market wiring"""
    
    def __init__(self):
        self._store = get_kalshi_market_store()
        self._universe_sync = None
        self._mapping_builder = get_market_mapping_builder()
        self._safety_layer = get_kalshi_safety_layer()
        self._coverage_checker = None
        self._running = False
        
        # Task references
        self._sync_task = None
        self._coverage_task = None
    
    async def initialize(self):
        """Initialize all wiring components"""
        logger.info("Initializing Kalshi market wiring orchestrator")
        
        # Initialize components
        self._universe_sync = await get_kalshi_universe_sync()
        self._coverage_checker = await get_kalshi_coverage_checker()
        
        logger.info("Kalshi market wiring orchestrator initialized")
    
    async def start_wiring_services(self):
        """Start all background wiring services"""
        if self._running:
            logger.warning("Wiring services already running")
            return
        
        self._running = True
        
        def _task_done_cb(task: asyncio.Task) -> None:
            """Log unhandled exceptions from orchestrator tasks."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error("KalshiWiringOrchestrator task %s crashed: %s", task.get_name(), exc, exc_info=exc)

        # Start universe sync
        self._sync_task = asyncio.create_task(self._universe_sync.run_sync_loop(), name="kalshi-orchestrator-sync")
        self._sync_task.add_done_callback(_task_done_cb)
        logger.info("Started Kalshi universe sync service")
        
        # Start coverage checker
        self._coverage_task = asyncio.create_task(self._coverage_checker.run_coverage_loop(), name="kalshi-orchestrator-coverage")
        self._coverage_task.add_done_callback(_task_done_cb)
        logger.info("Started Kalshi coverage checker service")
        
        logger.info("All Kalshi wiring services started")
    
    async def stop_wiring_services(self):
        """Stop all background wiring services"""
        if not self._running:
            return
        
        self._running = False
        
        # Stop services
        if self._universe_sync:
            self._universe_sync.stop()
        
        if self._coverage_checker:
            self._coverage_checker.stop()
        
        # Cancel tasks
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        
        if self._coverage_task:
            self._coverage_task.cancel()
            try:
                await self._coverage_task
            except asyncio.CancelledError:
                pass
        
        logger.info("All Kalshi wiring services stopped")
    
    async def perform_full_sync(self) -> Dict[str, Any]:
        """Perform complete synchronization of universe and mappings"""
        logger.info("Starting full Kalshi wiring sync")
        
        results = {
            "universe_sync": None,
            "mapping_build": None,
            "success": False,
            "duration_seconds": 0.0,
            "errors": [],
        }
        
        start_time = time.time()
        
        try:
            # Sync universe
            logger.info("Syncing Kalshi universe...")
            universe_result = await self._universe_sync.sync_universe()
            results["universe_sync"] = universe_result
            
            if not universe_result["success"]:
                results["errors"].extend(universe_result.get("errors", []))
            
            # Build mappings
            logger.info("Building market mappings...")
            mapping_result = await self._mapping_builder.build_all_mappings()
            results["mapping_build"] = mapping_result
            
            if mapping_result["errors"]:
                results["errors"].extend(mapping_result["errors"])
            
            # Check coverage
            logger.info("Checking coverage...")
            coverage_result = await self._coverage_checker.check_coverage()
            if not coverage_result["success"]:
                results["errors"].append(coverage_result.get("error", "Coverage check failed"))
            
            results["success"] = len(results["errors"]) == 0
            results["duration_seconds"] = time.time() - start_time
            
            logger.info(
                f"Full sync completed: "
                f"success={results['success']}, "
                f"duration={results['duration_seconds']:.2f}s, "
                f"errors={len(results['errors'])}"
            )
            
        except Exception as e:
            logger.error(f"Full sync failed: {e}")
            results["errors"].append(f"Sync exception: {e}")
            results["duration_seconds"] = time.time() - start_time
        
        return results
    
    def get_market_context_config(self, market_ticker: str) -> Optional[MarketContextConfig]:
        """Get complete context configuration for a market"""
        try:
            # Get mapping and market
            mapping = self._store.get_mapping(market_ticker)
            market = self._store.get_market(market_ticker)
            
            if not mapping or not market:
                return None
            
            # Check context availability
            context_check = self._safety_layer.check_context_freshness(mapping)
            
            # Get CQI info
            cqi_value, cqi_band = self._safety_layer.get_segment_cqi(mapping.risk_profile)
            
            # Calculate effective limits
            effective_notional, effective_daily, effective_open = self._safety_layer.calculate_effective_limits(
                market, cqi_band
            )
            
            config = MarketContextConfig(
                market_mapping=mapping,
                kalshi_market=market,
                crypto_context_available=(context_check.crypto_status == ContextStatus.AVAILABLE),
                crypto_fresh=(context_check.crypto_status == ContextStatus.AVAILABLE),
                sentiment_context_available=(context_check.sentiment_status == ContextStatus.AVAILABLE),
                sentiment_fresh=(context_check.sentiment_status == ContextStatus.AVAILABLE),
                debate_context_available=(context_check.debate_status == ContextStatus.AVAILABLE),
                debate_fresh=(context_check.debate_status == ContextStatus.AVAILABLE),
                effective_max_notional=effective_notional,
                effective_daily_notional=effective_daily,
                effective_open_risk=effective_open,
            )
            
            return config
            
        except Exception as e:
            logger.error(f"Error getting market context config for {market_ticker}: {e}")
            return None
    
    def check_market_safety(self, market_ticker: str, signal: Optional[Dict[str, Any]] = None, proposed_notional: float = 0.0) -> SafetyCheckResult:
        """Perform complete safety check for a market"""
        return self._safety_layer.perform_safety_check(market_ticker, signal, proposed_notional)
    
    def get_enabled_markets_for_symbol(self, underlying_symbol: str) -> List[MarketContextConfig]:
        """Get all enabled markets for a given underlying symbol"""
        try:
            mappings = self._store.get_mappings_by_underlying(underlying_symbol)
            configs = []
            
            for mapping in mappings:
                config = self.get_market_context_config(mapping.market_ticker)
                if config and config.safe_to_trade:
                    configs.append(config)
            
            return configs
            
        except Exception as e:
            logger.error(f"Error getting enabled markets for {underlying_symbol}: {e}")
            return []
    
    def get_enabled_mappings(self) -> List[MarketMapping]:
        """Get all enabled market mappings"""
        return self._store.get_enabled_mappings()
    
    def get_coverage_checker(self):
        """Get coverage checker instance"""
        return self._coverage_checker
    
    def get_latest_coverage_report(self):
        """Get latest coverage report"""
        return self._coverage_checker.get_latest_report()
    
    def get_wiring_status(self) -> Dict[str, Any]:
        """Get complete wiring system status"""
        try:
            # Get sync timestamps
            sync_timestamps = self._store.get_sync_timestamps()
            
            # Get coverage report
            coverage_report = self._coverage_checker.get_latest_report()
            
            # Get market counts
            total_markets = len(self._store.get_open_markets())
            enabled_mappings = len(self._store.get_enabled_mappings())
            
            # Get risk profile distribution
            risk_profile_counts = {}
            for risk_profile in ["crypto_linked", "macro_election", "equity_linked", "idiosyncratic"]:
                markets = self._store.get_markets_by_risk_profile(risk_profile)
                risk_profile_counts[risk_profile] = len(markets)
            
            return {
                "running": self._running,
                "sync_timestamps": sync_timestamps,
                "total_open_markets": total_markets,
                "enabled_mappings": enabled_mappings,
                "risk_profile_distribution": risk_profile_counts,
                "coverage_report": {
                    "coverage_percentage": coverage_report.coverage_percentage if coverage_report else 0.0,
                    "enablement_percentage": coverage_report.enablement_percentage if coverage_report else 0.0,
                    "unmapped_markets": coverage_report.unmapped_markets if coverage_report else 0,
                    "disabled_markets": coverage_report.disabled_markets if coverage_report else 0,
                    "last_check": coverage_report.checked_at if coverage_report else 0.0,
                } if coverage_report else None,
                "services": {
                    "universe_sync": self._universe_sync is not None,
                    "mapping_builder": self._mapping_builder is not None,
                    "safety_layer": self._safety_layer is not None,
                    "coverage_checker": self._coverage_checker is not None,
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting wiring status: {e}")
            return {
                "running": False,
                "error": str(e)
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check of all wiring components"""
        health = {
            "overall": "healthy",
            "components": {},
            "issues": []
        }
        
        try:
            # Check database connectivity
            try:
                self._store._conn()
                health["components"]["database"] = "healthy"
            except Exception as e:
                health["components"]["database"] = "unhealthy"
                health["issues"].append(f"Database error: {e}")
            
            # Check sync status
            sync_timestamps = self._store.get_sync_timestamps()
            current_time = time.time()
            
            # Check universe sync freshness
            universe_age = current_time - sync_timestamps.get("kalshi", 0)
            if universe_age > 1800:  # 30 minutes
                health["components"]["universe_sync"] = "stale"
                health["issues"].append(f"Universe sync is {universe_age/60:.0f} minutes old")
            else:
                health["components"]["universe_sync"] = "healthy"
            
            # Check mapping sync freshness
            mapping_age = current_time - sync_timestamps.get("mapping", 0)
            if mapping_age > 1800:
                health["components"]["mapping_sync"] = "stale"
                health["issues"].append(f"Mapping sync is {mapping_age/60:.0f} minutes old")
            else:
                health["components"]["mapping_sync"] = "healthy"
            
            # Check coverage
            coverage_report = self._coverage_checker.get_latest_report()
            if coverage_report:
                if coverage_report.coverage_percentage < 90.0:
                    health["components"]["coverage"] = "degraded"
                    health["issues"].append(f"Low coverage: {coverage_report.coverage_percentage:.1f}%")
                else:
                    health["components"]["coverage"] = "healthy"
            else:
                health["components"]["coverage"] = "unknown"
                health["issues"].append("No coverage report available")
            
            # Overall health
            if any(status != "healthy" for status in health["components"].values()):
                health["overall"] = "degraded" if "unhealthy" not in health["components"].values() else "unhealthy"
            
        except Exception as e:
            health["overall"] = "unhealthy"
            health["issues"].append(f"Health check error: {e}")
        
        return health


# Singleton instance
_wiring_orchestrator: Optional[KalshiWiringOrchestrator] = None
_wiring_orchestrator_lock: Optional[asyncio.Lock] = None
_wiring_orchestrator_lock_init = threading.Lock()


def _ensure_wiring_orchestrator_lock() -> asyncio.Lock:
    """Lazy-initialize the wiring orchestrator lock in the current event loop."""
    global _wiring_orchestrator_lock
    if _wiring_orchestrator_lock is None:
        with _wiring_orchestrator_lock_init:
            if _wiring_orchestrator_lock is None:
                _wiring_orchestrator_lock = asyncio.Lock()
    return _wiring_orchestrator_lock


async def get_kalshi_wiring_orchestrator() -> KalshiWiringOrchestrator:
    """Get singleton wiring orchestrator instance"""
    global _wiring_orchestrator
    if _wiring_orchestrator is None:
        async with _ensure_wiring_orchestrator_lock():
            if _wiring_orchestrator is None:
                _wiring_orchestrator = KalshiWiringOrchestrator()
                await _wiring_orchestrator.initialize()
    return _wiring_orchestrator

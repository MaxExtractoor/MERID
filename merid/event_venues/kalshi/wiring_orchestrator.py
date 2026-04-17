"""
DEPRECATED — use merid.event_venues.kalshi.market_wiring.orchestrator instead.

This module is an orphan duplicate.  All production consumers import from
``merid.event_venues.kalshi.market_wiring.orchestrator``.  This file is
retained only for reference during migration and will be removed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any

from merid.event_venues.kalshi.market_wiring.models import (
    MarketMapping,
    KalshiMarketRecord,
    MarketContextConfig,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.universe_sync import get_kalshi_universe_sync
from merid.event_venues.kalshi.market_mapping import get_market_mapping_registry
from merid.event_venues.kalshi.market_context import get_market_context_resolver
from merid.event_venues.kalshi.coverage_checker import get_coverage_checker
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.wiring_orchestrator")


class KalshiWiringOrchestrator:
    """Main orchestrator for Kalshi market wiring"""
    
    def __init__(self):
        self._store = get_kalshi_market_store()
        self._universe_sync = None
        self._mapping_registry = get_market_mapping_registry()
        self._context_resolver = get_market_context_resolver()
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
        self._coverage_checker = await get_coverage_checker()
        
        logger.info("Kalshi market wiring orchestrator initialized")
    
    async def start_wiring_services(self):
        """Start all background wiring services"""
        if self._running:
            logger.warning("Wiring services already running")
            return
        
        self._running = True

        def _task_done_cb(task: asyncio.Task) -> None:
            """Log unhandled exceptions from wiring tasks."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error("KalshiWiringOrchestrator task crashed: %s", exc, exc_info=exc)

        # Start universe sync
        self._sync_task = asyncio.create_task(self._universe_sync.run_sync_loop(), name="kalshi-wiring-sync")
        self._sync_task.add_done_callback(_task_done_cb)
        logger.info("Started Kalshi universe sync service")

        # Start coverage checker
        self._coverage_task = asyncio.create_task(self._coverage_checker.run_coverage_loop(), name="kalshi-wiring-coverage")
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
            "coverage_check": None,
            "success": False,
            "duration_seconds": 0.0,
            "errors": [],
        }
        
        start_time = time.time()
        
        try:
            # Sync universe
            logger.info("Syncing Kalshi universe...")
            universe_count = await self._universe_sync.sync_markets_async()
            results["universe_sync"] = {"markets_updated": universe_count}
            
            # Build mappings
            logger.info("Building market mappings...")
            mapping_result = self._mapping_registry.build_all_mappings()
            results["mapping_build"] = mapping_result
            
            if mapping_result["errors"]:
                results["errors"].extend(mapping_result["errors"])
            
            # Check coverage
            logger.info("Checking coverage...")
            coverage_result = await self._coverage_checker.compute_report_async()
            if not coverage_result["success"]:
                results["errors"].append(coverage_result.get("error", "Coverage check failed"))
            else:
                results["coverage_check"] = {
                    "coverage_percentage": coverage_result["report"].coverage_percentage,
                    "unmapped_markets": coverage_result["report"].unmapped_markets,
                }
            
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
        return self._context_resolver.get_context(market_ticker)
    
    def get_enabled_markets_for_symbol(self, underlying_symbol: str) -> List[MarketContextConfig]:
        """Get all enabled markets for a given underlying symbol"""
        return self._context_resolver.get_contexts_for_symbol(underlying_symbol)
    
    def get_safe_contexts(self) -> List[MarketContextConfig]:
        """Get all safe-to-trade contexts"""
        return self._context_resolver.get_safe_contexts()
    
    def get_wiring_status(self) -> Dict[str, Any]:
        """Get complete wiring system status"""
        try:
            # Get sync timestamps
            sync_timestamps = self._store.get_sync_timestamps()
            
            # Get coverage report
            coverage_report = self._coverage_checker.get_latest_report()
            
            # Get market counts
            total_markets = len(self._store.get_open_markets())
            enabled_mappings = len(self._mapping_registry.get_enabled_mappings())
            
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
                    "mapping_registry": self._mapping_registry is not None,
                    "context_resolver": self._context_resolver is not None,
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
_wiring_orchestrator_lock = asyncio.Lock()


async def get_kalshi_wiring_orchestrator() -> KalshiWiringOrchestrator:
    """Get singleton wiring orchestrator instance"""
    global _wiring_orchestrator
    if _wiring_orchestrator is None:
        async with _wiring_orchestrator_lock:
            if _wiring_orchestrator is None:
                _wiring_orchestrator = KalshiWiringOrchestrator()
                await _wiring_orchestrator.initialize()
    return _wiring_orchestrator

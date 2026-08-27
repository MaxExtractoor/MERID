"""
Coverage Checker

Ensures complete coverage of all open Kalshi markets and identifies gaps
that need mapping or explicit disablement.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, List, Set, Any, Optional
from dataclasses import dataclass

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.market_wiring.models import (
    CoverageReport,
    RiskProfile,
    MarketStatus,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.market_mapping import get_market_mapping_registry
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.coverage_checker")


@dataclass
class CoverageConfig:
    """Configuration for coverage checking"""
    check_interval_seconds: float = 3600.0  # 1 hour
    auto_disable_unmapped: bool = True
    alert_threshold_unmapped: float = 0.05  # Alert if >5% unmapped
    alert_threshold_disabled: float = 0.10  # Alert if >10% disabled
    
    # Risk profile coverage requirements
    required_coverage_by_profile: Dict[RiskProfile, float] = None
    
    def __post_init__(self):
        if self.required_coverage_by_profile is None:
            self.required_coverage_by_profile = {
                RiskProfile.CRYPTO_LINKED: 0.95,  # 95% coverage required
                RiskProfile.MACRO_ELECTION: 0.90,
                RiskProfile.EQUITY_LINKED: 0.80,
                RiskProfile.IDIOSYNCRATIC: 0.50,  # Lower requirement for idiosyncratic
            }


class CoverageChecker:
    """Checks and reports on market coverage completeness"""
    
    def __init__(self, config: Optional[CoverageConfig] = None):
        self._config = config or CoverageConfig()
        self._store = get_kalshi_market_store()
        self._mapping_registry = get_market_mapping_registry()
        self._client: Optional[KalshiVenueClient] = None
        self._running = False
        self._last_check_time = 0.0
    
    async def _get_client(self) -> KalshiVenueClient:
        """Get Kalshi client instance"""
        if self._client is None:
            from merid.event_venues.kalshi.client import get_kalshi_client
            self._client = get_kalshi_client()
        return self._client
    
    async def _fetch_open_markets_from_kalshi(self) -> Set[str]:
        """Fetch current open market tickers from Kalshi"""
        try:
            client = await self._get_client()
            
            # Fetch all open markets
            result = await client._request_with_resilience(
                "GET", "/markets", params={"status": "open"}, operation_name="fetch_open_markets"
            )
            
            if result.success:
                markets = result.data.get("markets", [])
                open_tickers = {market.get("ticker") for market in markets if market.get("ticker")}
                logger.info(f"Fetched {len(open_tickers)} open markets from Kalshi")
                return open_tickers
            else:
                logger.error(f"Failed to fetch open markets from Kalshi: {result.error}")
                return set()
                
        except Exception as e:
            logger.error(f"Exception fetching open markets from Kalshi: {e}")
            return set()
    
    def _get_stored_open_markets(self) -> Dict[str, Any]:
        """Get open markets from local storage"""
        try:
            open_markets = self._store.get_open_markets()
            market_dict = {
                market.market_ticker: market
                for market in open_markets
            }
            logger.info(f"Found {len(market_dict)} open markets in local storage")
            return market_dict
        except Exception as e:
            logger.error(f"Error getting stored open markets: {e}")
            return {}
    
    def _get_market_mappings(self) -> Dict[str, Any]:
        """Get all market mappings"""
        try:
            mappings = self._mapping_registry.get_enabled_mappings()
            mapping_dict = {
                mapping.market_ticker: mapping
                for mapping in mappings
            }
            logger.info(f"Found {len(mapping_dict)} enabled mappings")
            return mapping_dict
        except Exception as e:
            logger.error(f"Error getting market mappings: {e}")
            return {}
    
    def _analyze_coverage_gaps(self, kalshi_open: Set[str], stored_open: Dict[str, Any], mappings: Dict[str, Any]) -> CoverageReport:
        """Analyze coverage gaps and generate report"""
        # Basic counts
        total_open_markets = len(kalshi_open)
        mapped_markets = len(set(kalshi_open) & set(mappings.keys()))
        enabled_markets = len([
            ticker for ticker in kalshi_open
            if ticker in mappings and mappings[ticker].enabled
        ])
        
        # Find unmapped markets
        unmapped_market_tickers = list(kalshi_open - set(mappings.keys()))
        unmapped_markets = len(unmapped_market_tickers)
        
        # Find disabled markets
        disabled_market_tickers = [
            ticker for ticker in kalshi_open
            if ticker in mappings and not mappings[ticker].enabled
        ]
        disabled_markets = len(disabled_market_tickers)
        
        # Coverage by risk profile
        coverage_by_risk_profile = {}
        for risk_profile in RiskProfile:
            profile_markets = [
                ticker for ticker in kalshi_open
                if ticker in stored_open and stored_open[ticker].risk_profile == risk_profile
            ]
            profile_mapped = len([
                ticker for ticker in profile_markets
                if ticker in mappings
            ])
            coverage_by_risk_profile[risk_profile.value] = {
                "total": len(profile_markets),
                "mapped": profile_mapped,
                "coverage_percentage": (profile_mapped / len(profile_markets) * 100) if profile_markets else 0.0
            }
        
        return CoverageReport(
            total_open_markets=total_open_markets,
            mapped_markets=mapped_markets,
            enabled_markets=enabled_markets,
            unmapped_markets=unmapped_markets,
            disabled_markets=disabled_markets,
            unmapped_market_tickers=unmapped_market_tickers,
            disabled_market_tickers=disabled_market_tickers,
            coverage_by_risk_profile=coverage_by_risk_profile,
        )
    
    def _generate_alerts(self, report: CoverageReport) -> List[str]:
        """Generate alerts based on coverage report"""
        alerts = []
        
        # Overall coverage alerts
        if report.coverage_percentage < 95.0:
            alerts.append(f"Low overall coverage: {report.coverage_percentage:.1f}%")
        
        # Unmapped markets alert
        unmapped_percentage = (report.unmapped_markets / report.total_open_markets * 100) if report.total_open_markets > 0 else 0
        if unmapped_percentage > (self._config.alert_threshold_unmapped * 100):
            alerts.append(f"High unmapped percentage: {unmapped_percentage:.1f}% ({report.unmapped_markets} markets)")
        
        # Disabled markets alert
        disabled_percentage = (report.disabled_markets / report.total_open_markets * 100) if report.total_open_markets > 0 else 0
        if disabled_percentage > (self._config.alert_threshold_disabled * 100):
            alerts.append(f"High disabled percentage: {disabled_percentage:.1f}% ({report.disabled_markets} markets)")
        
        # Risk profile coverage alerts
        for risk_profile, required_coverage in self._config.required_coverage_by_profile.items():
            profile_data = report.coverage_by_risk_profile.get(risk_profile.value, {})
            profile_coverage = profile_data.get("coverage_percentage", 0.0)
            
            if profile_coverage < (required_coverage * 100):
                alerts.append(
                    f"Low {risk_profile.value} coverage: {profile_coverage:.1f}% "
                    f"(required: {required_coverage * 100:.0f}%)"
                )
        
        return alerts
    
    async def _auto_disable_unmapped(self, unmapped_tickers: List[str]) -> int:
        """Automatically disable unmapped markets"""
        if not self._config.auto_disable_unmapped:
            return 0
        
        disabled_count = 0
        for ticker in unmapped_tickers:
            try:
                # Update market to disabled
                success = self._store.update_market_status(ticker, MarketStatus.CLOSED)
                if success:
                    disabled_count += 1
                    logger.info(f"Auto-disabled unmapped market: {ticker}")
                else:
                    logger.warning(f"Failed to auto-disable market: {ticker}")
            except Exception as e:
                logger.error(f"Error auto-disabling market {ticker}: {e}")
        
        if disabled_count > 0:
            logger.info(f"Auto-disabled {disabled_count} unmapped markets")
        
        return disabled_count
    
    def compute_report(self) -> CoverageReport:
        """Compute coverage report"""
        try:
            # This is a synchronous version for compatibility
            # In practice, this should be called from an async context
            logger.warning("compute_report() called synchronously - use compute_report_async() for full functionality")
            
            # Get stored data
            stored_open = self._get_stored_open_markets()
            mappings = self._get_market_mappings()
            
            # Use stored open markets as proxy for Kalshi open markets
            kalshi_open = set(stored_open.keys())
            
            # Analyze coverage
            report = self._analyze_coverage_gaps(kalshi_open, stored_open, mappings)
            
            return report
            
        except Exception as e:
            logger.error(f"Failed to compute coverage report: {e}")
            # Return empty report
            return CoverageReport(
                total_open_markets=0,
                mapped_markets=0,
                enabled_markets=0,
                unmapped_markets=0,
                disabled_markets=0,
                unmapped_market_tickers=[],
                disabled_market_tickers=[],
                coverage_by_risk_profile={},
            )
    
    async def compute_report_async(self) -> Dict[str, Any]:
        """Compute coverage report with full Kalshi API integration"""
        start_time = time.time()
        
        try:
            # Fetch current open markets from Kalshi
            kalshi_open = await self._fetch_open_markets_from_kalshi()
            
            # Get stored markets and mappings
            stored_open = self._get_stored_open_markets()
            mappings = self._get_market_mappings()
            
            # Analyze coverage
            report = self._analyze_coverage_gaps(kalshi_open, stored_open, mappings)
            
            # Generate alerts
            alerts = self._generate_alerts(report)
            
            # Auto-disable unmapped markets if configured
            auto_disabled = 0
            if self._config.auto_disable_unmapped and report.unmapped_market_tickers:
                auto_disabled = await self._auto_disable_unmapped(report.unmapped_market_tickers)
            
            # Save report
            self._store.save_coverage_report(report)
            
            # Update sync timestamp
            self._store.update_sync_timestamp("coverage", start_time)
            self._last_check_time = start_time
            
            # Log results
            logger.info(
                f"Coverage check completed: "
                f"total={report.total_open_markets}, "
                f"coverage={report.coverage_percentage:.1f}%, "
                f"enablement={report.enablement_percentage:.1f}%, "
                f"unmapped={report.unmapped_markets}, "
                f"disabled={report.disabled_markets}, "
                f"alerts={len(alerts)}, "
                f"auto_disabled={auto_disabled}"
            )
            
            # Log alerts
            for alert in alerts:
                logger.warning(f"Coverage alert: {alert}")
            
            return {
                "success": True,
                "report": report,
                "alerts": alerts,
                "auto_disabled": auto_disabled,
                "duration_seconds": time.time() - start_time,
            }
            
        except Exception as e:
            logger.error(f"Coverage check failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": time.time() - start_time,
            }
    
    async def run_coverage_loop(self):
        """Run continuous coverage checking loop"""
        self._running = True
        logger.info("Starting Kalshi coverage checker loop")
        
        while self._running:
            try:
                # Check if it's time to run coverage check
                current_time = time.time()
                time_since_check = current_time - self._last_check_time
                
                if time_since_check >= self._config.check_interval_seconds:
                    logger.info(f"Starting scheduled coverage check (last was {time_since_check:.0f}s ago)")
                    await self.compute_report_async()
                else:
                    # Sleep until next check
                    sleep_time = self._config.check_interval_seconds - time_since_check
                    logger.debug(f"Sleeping {sleep_time:.0f}s until next coverage check")
                    await asyncio.sleep(min(sleep_time, 60))  # Max 60s sleep for responsiveness
                
            except Exception as e:
                logger.error(f"Error in coverage check loop: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying
        
        logger.info("Kalshi coverage checker loop stopped")
    
    def stop(self):
        """Stop the coverage checker"""
        self._running = False
        logger.info("Stopping Kalshi coverage checker")
    
    def get_latest_report(self) -> Optional[CoverageReport]:
        """Get the latest coverage report"""
        return self._store.get_latest_coverage_report()
    
    def get_coverage_summary(self) -> Dict[str, Any]:
        """Get current coverage summary"""
        latest_report = self.get_latest_report()
        sync_timestamps = self._store.get_sync_timestamps()
        
        if latest_report:
            return {
                "last_check": latest_report.checked_at,
                "total_open_markets": latest_report.total_open_markets,
                "coverage_percentage": latest_report.coverage_percentage,
                "enablement_percentage": latest_report.enablement_percentage,
                "unmapped_markets": latest_report.unmapped_markets,
                "disabled_markets": latest_report.disabled_markets,
                "coverage_by_risk_profile": latest_report.coverage_by_risk_profile,
                "sync_timestamps": sync_timestamps,
            }
        else:
            return {
                "last_check": 0.0,
                "total_open_markets": 0,
                "coverage_percentage": 0.0,
                "enablement_percentage": 0.0,
                "unmapped_markets": 0,
                "disabled_markets": 0,
                "coverage_by_risk_profile": {},
                "sync_timestamps": sync_timestamps,
            }


# Singleton instance
_coverage_checker: Optional[CoverageChecker] = None
_coverage_checker_lock: Optional[asyncio.Lock] = None
_coverage_checker_lock_init = threading.Lock()


def _ensure_coverage_checker_lock() -> asyncio.Lock:
    """Lazy-initialize the coverage checker lock in the current event loop."""
    global _coverage_checker_lock
    if _coverage_checker_lock is None:
        with _coverage_checker_lock_init:
            if _coverage_checker_lock is None:
                _coverage_checker_lock = asyncio.Lock()
    return _coverage_checker_lock


async def get_coverage_checker() -> CoverageChecker:
    """Get singleton coverage checker instance"""
    global _coverage_checker
    if _coverage_checker is None:
        lock = _ensure_coverage_checker_lock()
        async with lock:
            if _coverage_checker is None:
                _coverage_checker = CoverageChecker()
    return _coverage_checker

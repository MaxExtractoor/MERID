"""
Base Arbitrage Scanner - Abstract base for all arbitrage scanners.

All scanners are READ-ONLY by default. They detect opportunities
but do not execute trades.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from schemas.arbitrage import ArbitrageOpportunity, ArbitrageType, ArbitrageStatus
from utils.logger import get_logger


def _default_arb_symbols() -> List[str]:
    try:
        from data.asset_universe import get_arb_candidates
        return [a.symbol for a in get_arb_candidates()
                if '/' in a.symbol and ':' not in a.symbol]
    except Exception:
        return ["BTC/USDT", "ETH/USDT"]


class ScannerState(Enum):
    """Scanner operational state."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ScannerConfig:
    """Configuration for arbitrage scanners."""
    # Identification
    scanner_id: str = ""
    scanner_type: ArbitrageType = ArbitrageType.CROSS_CEX
    
    # Scanning parameters
    scan_interval_seconds: float = 5.0
    min_profit_usd: float = 10.0
    min_profit_margin_pct: float = 0.1  # 0.1%
    max_opportunities_per_scan: int = 10
    
    # Venues
    enabled_venues: List[str] = field(default_factory=list)
    disabled_venues: List[str] = field(default_factory=list)
    
    # Symbols
    enabled_symbols: List[str] = field(default_factory=_default_arb_symbols)
    disabled_symbols: List[str] = field(default_factory=list)
    
    # Risk limits
    max_position_usd: float = 10000.0
    max_slippage_pct: float = 0.5
    min_liquidity_usd: float = 50000.0
    
    # Execution (DISABLED by default)
    execution_enabled: bool = False
    alert_only: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanner_id": self.scanner_id,
            "scanner_type": self.scanner_type.value,
            "scan_interval_seconds": self.scan_interval_seconds,
            "min_profit_usd": self.min_profit_usd,
            "min_profit_margin_pct": self.min_profit_margin_pct,
            "max_opportunities_per_scan": self.max_opportunities_per_scan,
            "enabled_venues": self.enabled_venues,
            "disabled_venues": self.disabled_venues,
            "enabled_symbols": self.enabled_symbols,
            "disabled_symbols": self.disabled_symbols,
            "max_position_usd": self.max_position_usd,
            "max_slippage_pct": self.max_slippage_pct,
            "min_liquidity_usd": self.min_liquidity_usd,
            "execution_enabled": self.execution_enabled,
            "alert_only": self.alert_only,
        }


@dataclass
class ScannerMetrics:
    """Metrics for scanner performance."""
    total_scans: int = 0
    opportunities_found: int = 0
    profitable_opportunities: int = 0
    total_potential_profit_usd: float = 0.0
    avg_scan_time_ms: float = 0.0
    last_scan_time: float = 0.0
    errors: int = 0
    uptime_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scans": self.total_scans,
            "opportunities_found": self.opportunities_found,
            "profitable_opportunities": self.profitable_opportunities,
            "total_potential_profit_usd": self.total_potential_profit_usd,
            "avg_scan_time_ms": self.avg_scan_time_ms,
            "last_scan_time": self.last_scan_time,
            "errors": self.errors,
            "uptime_seconds": self.uptime_seconds,
        }


class ArbitrageScanner(ABC):
    """
    Abstract base class for arbitrage scanners.
    
    All scanners:
    - Run continuously in the background
    - Detect opportunities but DO NOT execute by default
    - Emit opportunities to callbacks/event bus
    - Track metrics for monitoring
    """
    
    def __init__(self, config: ScannerConfig):
        self.config = config
        self.logger = get_logger(f"arbitrage.{config.scanner_id}")
        
        # State
        self.state = ScannerState.STOPPED
        self._task: Optional[asyncio.Task] = None
        self._start_time: float = 0.0
        
        # Metrics
        self.metrics = ScannerMetrics()
        
        # Callbacks
        self._opportunity_callbacks: List[Callable[[ArbitrageOpportunity], None]] = []
        
        # Recent opportunities (for deduplication)
        self._recent_opportunities: Dict[str, float] = {}
        self._dedup_window_seconds: float = 60.0
    
    async def start(self) -> None:
        """Start the scanner."""
        if self.state == ScannerState.RUNNING:
            self.logger.warning(f"{self.config.scanner_id} already running")
            return
        
        self.state = ScannerState.STARTING
        self._start_time = time.time()
        
        # Initialize scanner-specific resources
        await self._initialize()
        
        # Start scan loop
        self._task = asyncio.create_task(self._scan_loop())
        self.state = ScannerState.RUNNING
        
        self.logger.info(f"{self.config.scanner_id} started (execution_enabled={self.config.execution_enabled})")
    
    async def stop(self) -> None:
        """Stop the scanner."""
        self.state = ScannerState.STOPPED
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Cleanup scanner-specific resources
        await self._cleanup()
        
        self.logger.info(f"{self.config.scanner_id} stopped")
    
    def pause(self) -> None:
        """Pause scanning (does not stop the loop)."""
        self.state = ScannerState.PAUSED
        self.logger.info(f"{self.config.scanner_id} paused")
    
    def resume(self) -> None:
        """Resume scanning."""
        if self.state == ScannerState.PAUSED:
            self.state = ScannerState.RUNNING
            self.logger.info(f"{self.config.scanner_id} resumed")
    
    def add_callback(self, callback: Callable[[ArbitrageOpportunity], None]) -> None:
        """Add callback for opportunity notifications."""
        self._opportunity_callbacks.append(callback)
    
    async def _scan_loop(self) -> None:
        """Main scanning loop."""
        while self.state in [ScannerState.RUNNING, ScannerState.PAUSED]:
            try:
                if self.state == ScannerState.PAUSED:
                    await asyncio.sleep(1)
                    continue
                
                # Run scan
                start_time = time.time()
                opportunities = await self._scan()
                scan_time_ms = (time.time() - start_time) * 1000
                
                # Update metrics
                self.metrics.total_scans += 1
                self.metrics.last_scan_time = time.time()
                self.metrics.avg_scan_time_ms = (
                    (self.metrics.avg_scan_time_ms * (self.metrics.total_scans - 1) + scan_time_ms)
                    / self.metrics.total_scans
                )
                self.metrics.uptime_seconds = time.time() - self._start_time
                
                # Process opportunities
                for opp in opportunities[:self.config.max_opportunities_per_scan]:
                    await self._process_opportunity(opp)
                
                # Wait for next scan
                await asyncio.sleep(self.config.scan_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Scan error: {e}")
                self.metrics.errors += 1
                self.state = ScannerState.ERROR
                await asyncio.sleep(5)  # Back off on error
                self.state = ScannerState.RUNNING
    
    async def _process_opportunity(self, opp: ArbitrageOpportunity) -> None:
        """Process a detected opportunity."""
        # Deduplicate
        opp_hash = opp.compute_hash()
        if opp_hash in self._recent_opportunities:
            if time.time() - self._recent_opportunities[opp_hash] < self._dedup_window_seconds:
                return  # Skip duplicate
        
        self._recent_opportunities[opp_hash] = time.time()
        
        # Clean old entries
        cutoff = time.time() - self._dedup_window_seconds
        self._recent_opportunities = {
            k: v for k, v in self._recent_opportunities.items() if v > cutoff
        }
        
        # Update metrics
        self.metrics.opportunities_found += 1
        if opp.is_profitable():
            self.metrics.profitable_opportunities += 1
            self.metrics.total_potential_profit_usd += opp.net_profit_usd
        
        # Notify callbacks
        for callback in self._opportunity_callbacks:
            try:
                callback(opp)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")
        
        # Log opportunity
        self.logger.info(
            f"Opportunity: {opp.arb_type.value} | "
            f"Profit: ${opp.net_profit_usd:.2f} ({opp.profit_margin_pct:.3f}%) | "
            f"Executable: {opp.can_execute()}"
        )
    
    @abstractmethod
    async def _initialize(self) -> None:
        """Initialize scanner-specific resources."""
        pass
    
    @abstractmethod
    async def _cleanup(self) -> None:
        """Cleanup scanner-specific resources."""
        pass
    
    @abstractmethod
    async def _scan(self) -> List[ArbitrageOpportunity]:
        """
        Perform a single scan for opportunities.
        
        Returns:
            List of detected opportunities
        """
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """Get scanner status."""
        return {
            "scanner_id": self.config.scanner_id,
            "scanner_type": self.config.scanner_type.value,
            "state": self.state.value,
            "execution_enabled": self.config.execution_enabled,
            "alert_only": self.config.alert_only,
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict(),
        }

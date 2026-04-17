"""
OracleCoordinator - Triple-redundant oracle consensus per MASTER_SPEC v1.0

This module implements the oracle coordination layer that:
- Manages the triple-redundant oracle stack (Chainlink, Pyth, Switchboard)
- Requires 2-of-3 consensus for price acceptance
- Implements query coalescing (100ms dedup window)
- Handles fallback order and degraded operation

Reference: MASTER_SPEC.md Section 3 (Layer 5: Oracle Stack)
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 2 (Oracle Coordination)
"""

from __future__ import annotations

import threading
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from oracles.base_oracle import BaseOracle, OraclePrice, OracleStatus
from oracles.chainlink import ChainlinkOracle, get_chainlink_oracle
from oracles.pyth import PythOracle, get_pyth_oracle
from oracles.switchboard import SwitchboardOracle, get_switchboard_oracle
from utils.logger import get_logger

logger = get_logger("oracles.coordinator")


@dataclass
class OracleConsensusResult:
    """Result of oracle consensus."""
    symbol: str
    consensus_price: float
    confidence: float
    timestamp: float
    
    contributing_oracles: List[str]
    prices_by_oracle: Dict[str, float]
    spread_pct: float
    
    is_degraded: bool = False
    degraded_reason: Optional[str] = None


@dataclass
class CoordinatorConfig:
    """Configuration for oracle coordinator."""
    
    consensus_threshold: int = 2
    max_spread_pct: float = 0.02
    
    dedup_window_ms: int = 100
    
    rate_limit_per_asset: int = 3
    rate_limit_window_seconds: float = 1.0
    rate_limit_global: int = 30
    
    stale_threshold_seconds: float = 60.0
    
    fallback_confidence: float = 0.5


class OracleCoordinator:
    """
    Coordinates triple-redundant oracle stack.
    
    Responsibilities:
    - Query all three oracles for price data
    - Achieve 2-of-3 consensus on prices
    - Coalesce identical requests within dedup window
    - Handle fallback when oracles are unavailable
    - Track oracle health and reliability
    """
    
    def __init__(self, config: Optional[CoordinatorConfig] = None) -> None:
        """
        Initialize oracle coordinator.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or CoordinatorConfig()
        
        self._oracles: List[BaseOracle] = []
        self._pending_requests: Dict[str, asyncio.Task[OracleConsensusResult]] = {}
        self._request_timestamps: Dict[str, List[float]] = {}
        self._global_request_times: List[float] = []
        
        self._consensus_cache: Dict[str, OracleConsensusResult] = {}
        
        self._logger = get_logger("oracles.coordinator")
    
    async def initialize(self) -> None:
        """Initialize and connect all oracles."""
        chainlink = get_chainlink_oracle()
        pyth = get_pyth_oracle()
        switchboard = get_switchboard_oracle()
        
        self._oracles = [chainlink, pyth, switchboard]
        self._oracles.sort(key=lambda o: o.priority)
        
        for oracle in self._oracles:
            try:
                await oracle.connect()
                self._logger.info(
                    "Oracle connected: %s (priority=%d)",
                    oracle.oracle_id, oracle.priority
                )
            except Exception as e:
                self._logger.error(
                    "Failed to connect oracle %s: %s",
                    oracle.oracle_id, e
                )
    
    async def shutdown(self) -> None:
        """Disconnect all oracles."""
        for oracle in self._oracles:
            try:
                await oracle.disconnect()
            except Exception as e:
                self._logger.error(
                    "Error disconnecting %s: %s",
                    oracle.oracle_id, e
                )
    
    async def get_price(self, symbol: str) -> OracleConsensusResult:
        """
        Get consensus price for a symbol.
        
        Implements query coalescing - identical requests within
        the dedup window will share the same result.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            
        Returns:
            OracleConsensusResult with consensus price
        """
        cache_key = self._get_cache_key(symbol)
        
        if cache_key in self._pending_requests:
            return await self._pending_requests[cache_key]
        
        if cache_key in self._consensus_cache:
            cached = self._consensus_cache[cache_key]
            if not self._is_stale(cached):
                return cached
        
        if not self._check_rate_limit(symbol):
            if cache_key in self._consensus_cache:
                cached = self._consensus_cache[cache_key]
                cached.is_degraded = True
                cached.degraded_reason = "rate_limited"
                return cached
            
            return OracleConsensusResult(
                symbol=symbol,
                consensus_price=0.0,
                confidence=0.0,
                timestamp=time.time(),
                contributing_oracles=[],
                prices_by_oracle={},
                spread_pct=0.0,
                is_degraded=True,
                degraded_reason="rate_limited_no_cache",
            )
        
        task = asyncio.create_task(self._fetch_consensus(symbol))
        self._pending_requests[cache_key] = task
        
        try:
            result = await task
            self._consensus_cache[cache_key] = result
            return result
        finally:
            self._pending_requests.pop(cache_key, None)
    
    async def get_prices(
        self,
        symbols: List[str],
    ) -> Dict[str, OracleConsensusResult]:
        """
        Get consensus prices for multiple symbols.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping symbol to consensus result
        """
        tasks = [self.get_price(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        output: Dict[str, OracleConsensusResult] = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                self._logger.error("Price fetch failed for %s: %s", symbol, result)
                continue
            output[symbol] = result
        
        return output
    
    def get_oracle_health(self) -> Dict[str, Dict[str, object]]:
        """Get health status for all oracles."""
        return {
            oracle.oracle_id: {
                "status": oracle.status.value,
                "priority": oracle.priority,
                "health": oracle.get_health().__dict__,
            }
            for oracle in self._oracles
        }
    
    async def _fetch_consensus(self, symbol: str) -> OracleConsensusResult:
        """
        Fetch prices from all oracles and compute consensus.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Consensus result
        """
        self._record_request(symbol)
        
        prices: Dict[str, OraclePrice] = {}
        
        for oracle in self._oracles:
            if oracle.status != OracleStatus.CONNECTED:
                continue
            
            try:
                price = await oracle.get_price(symbol)
                if price and not price.is_stale(self.config.stale_threshold_seconds):
                    prices[oracle.oracle_id] = price
            except Exception as e:
                self._logger.warning(
                    "Oracle %s failed for %s: %s",
                    oracle.oracle_id, symbol, e
                )
        
        return self._compute_consensus(symbol, prices)
    
    def _compute_consensus(
        self,
        symbol: str,
        prices: Dict[str, OraclePrice],
    ) -> OracleConsensusResult:
        """
        Compute consensus from oracle prices.
        
        Requires 2-of-3 agreement within spread tolerance.
        """
        if len(prices) == 0:
            return OracleConsensusResult(
                symbol=symbol,
                consensus_price=0.0,
                confidence=0.0,
                timestamp=time.time(),
                contributing_oracles=[],
                prices_by_oracle={},
                spread_pct=0.0,
                is_degraded=True,
                degraded_reason="no_oracle_data",
            )
        
        if len(prices) == 1:
            oracle_id, price = next(iter(prices.items()))
            return OracleConsensusResult(
                symbol=symbol,
                consensus_price=price.price,
                confidence=self.config.fallback_confidence,
                timestamp=time.time(),
                contributing_oracles=[oracle_id],
                prices_by_oracle={oracle_id: price.price},
                spread_pct=0.0,
                is_degraded=True,
                degraded_reason="single_oracle_fallback",
            )
        
        price_values = [p.price for p in prices.values()]
        oracle_ids = list(prices.keys())
        
        min_price = min(price_values)
        max_price = max(price_values)
        spread_pct = (max_price - min_price) / min_price if min_price > 0 else 0
        
        if spread_pct > self.config.max_spread_pct:
            sorted_prices = sorted(prices.items(), key=lambda x: x[1].confidence, reverse=True)
            best_oracle_id, best_price = sorted_prices[0]
            
            return OracleConsensusResult(
                symbol=symbol,
                consensus_price=best_price.price,
                confidence=best_price.confidence * 0.7,
                timestamp=time.time(),
                contributing_oracles=[best_oracle_id],
                prices_by_oracle={oid: p.price for oid, p in prices.items()},
                spread_pct=spread_pct,
                is_degraded=True,
                degraded_reason=f"spread_exceeded_{spread_pct:.2%}",
            )
        
        consensus_price = sum(price_values) / len(price_values)
        
        avg_confidence = sum(p.confidence for p in prices.values()) / len(prices)
        consensus_confidence = avg_confidence * (len(prices) / 3)
        
        return OracleConsensusResult(
            symbol=symbol,
            consensus_price=consensus_price,
            confidence=min(consensus_confidence, 1.0),
            timestamp=time.time(),
            contributing_oracles=oracle_ids,
            prices_by_oracle={oid: p.price for oid, p in prices.items()},
            spread_pct=spread_pct,
            is_degraded=len(prices) < self.config.consensus_threshold,
            degraded_reason=None if len(prices) >= self.config.consensus_threshold else "insufficient_oracles",
        )
    
    def _get_cache_key(self, symbol: str) -> str:
        """Generate cache key with time bucket for dedup."""
        time_bucket = int(time.time() * 1000 / self.config.dedup_window_ms)
        return f"{symbol}:{time_bucket}"
    
    def _is_stale(self, result: OracleConsensusResult) -> bool:
        """Check if consensus result is stale."""
        age = time.time() - result.timestamp
        return age > self.config.stale_threshold_seconds
    
    def _check_rate_limit(self, symbol: str) -> bool:
        """Check if request is within rate limits."""
        now = time.time()
        
        self._global_request_times = [
            t for t in self._global_request_times
            if now - t < self.config.rate_limit_window_seconds
        ]
        if len(self._global_request_times) >= self.config.rate_limit_global:
            return False
        
        if symbol not in self._request_timestamps:
            self._request_timestamps[symbol] = []
        
        self._request_timestamps[symbol] = [
            t for t in self._request_timestamps[symbol]
            if now - t < self.config.rate_limit_window_seconds
        ]
        
        if len(self._request_timestamps[symbol]) >= self.config.rate_limit_per_asset:
            return False
        
        return True
    
    def _record_request(self, symbol: str) -> None:
        """Record a request for rate limiting."""
        now = time.time()
        self._global_request_times.append(now)
        
        if symbol not in self._request_timestamps:
            self._request_timestamps[symbol] = []
        self._request_timestamps[symbol].append(now)


_oracle_coordinator: Optional[OracleCoordinator] = None
_oracle_coordinator_lock = threading.Lock()


def get_oracle_coordinator() -> OracleCoordinator:
    """Get or create oracle coordinator singleton."""
    global _oracle_coordinator
    if _oracle_coordinator is None:
        with _oracle_coordinator_lock:
            if _oracle_coordinator is None:
                _oracle_coordinator = OracleCoordinator()
    return _oracle_coordinator


async def initialize_oracles() -> OracleCoordinator:
    """Initialize the oracle coordinator and all oracles."""
    coordinator = get_oracle_coordinator()
    await coordinator.initialize()
    return coordinator


async def shutdown_oracles() -> None:
    """Shutdown the oracle coordinator."""
    global _oracle_coordinator
    if _oracle_coordinator is not None:
        await _oracle_coordinator.shutdown()

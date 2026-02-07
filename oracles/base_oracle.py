"""
BaseOracle - Canonical oracle interface per MASTER_SPEC v1.0

This module defines the foundational interface for all price oracles.
MERID uses a triple-redundant oracle stack requiring 2-of-3 consensus.

Reference: MASTER_SPEC.md Section 3 (Layer 5: Oracle Stack)
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 2 (Oracle Coordination)
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("oracles.base")


class OracleStatus(Enum):
    """Oracle connection status."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass
class OraclePrice:
    """Price data from an oracle."""
    oracle_id: str
    symbol: str
    price: float
    timestamp: float
    confidence: float = 1.0
    source_timestamp: Optional[float] = None
    metadata: Dict[str, object] = field(default_factory=dict)
    
    def age_seconds(self) -> float:
        """Get age of price data in seconds."""
        return time.time() - self.timestamp
    
    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Check if price is stale."""
        return self.age_seconds() > max_age_seconds


@dataclass
class OracleHealth:
    """Oracle health status."""
    oracle_id: str
    status: OracleStatus
    last_update: float
    request_count: int
    error_count: int
    avg_latency_ms: float
    uptime_seconds: float
    
    def is_healthy(self) -> bool:
        """Check if oracle is healthy."""
        return self.status == OracleStatus.CONNECTED


class BaseOracle(ABC):
    """
    Abstract base class for price oracles.
    
    All oracle implementations must:
    - Implement get_price() for single symbol
    - Implement get_prices() for batch queries
    - Handle rate limiting
    - Report health status
    """
    
    def __init__(self, oracle_id: str, priority: int = 1) -> None:
        """
        Initialize oracle.
        
        Args:
            oracle_id: Unique identifier for this oracle
            priority: Priority in fallback order (1 = highest)
        """
        self._oracle_id = oracle_id
        self._priority = priority
        self._status = OracleStatus.DISCONNECTED
        self._start_time = time.time()
        self._last_update = 0.0
        self._request_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._price_cache: Dict[str, OraclePrice] = {}
        self._logger = get_logger(f"oracles.{oracle_id}")
    
    @property
    def oracle_id(self) -> str:
        """Oracle identifier."""
        return self._oracle_id
    
    @property
    def priority(self) -> int:
        """Priority in fallback order."""
        return self._priority
    
    @property
    def status(self) -> OracleStatus:
        """Current status."""
        return self._status
    
    def get_health(self) -> OracleHealth:
        """Get current health status."""
        avg_latency = (
            self._total_latency_ms / self._request_count
            if self._request_count > 0 else 0.0
        )
        return OracleHealth(
            oracle_id=self._oracle_id,
            status=self._status,
            last_update=self._last_update,
            request_count=self._request_count,
            error_count=self._error_count,
            avg_latency_ms=avg_latency,
            uptime_seconds=time.time() - self._start_time,
        )
    
    def get_cached_price(self, symbol: str) -> Optional[OraclePrice]:
        """Get cached price if available and fresh."""
        if symbol in self._price_cache:
            cached = self._price_cache[symbol]
            if not cached.is_stale():
                return cached
        return None
    
    async def connect(self) -> bool:
        """
        Connect to oracle data source.
        
        Returns:
            True if connected successfully
        """
        self._status = OracleStatus.CONNECTING
        try:
            success = await self._connect_impl()
            if success:
                self._status = OracleStatus.CONNECTED
                self._logger.info("Oracle connected: %s", self._oracle_id)
            else:
                self._status = OracleStatus.ERROR
            return success
        except Exception as e:
            self._status = OracleStatus.ERROR
            self._error_count += 1
            self._logger.error("Connection failed: %s", e)
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from oracle."""
        await self._disconnect_impl()
        self._status = OracleStatus.DISCONNECTED
        self._logger.info("Oracle disconnected: %s", self._oracle_id)
    
    async def get_price(self, symbol: str) -> Optional[OraclePrice]:
        """
        Get price for a single symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            
        Returns:
            OraclePrice if available, None otherwise
        """
        cached = self.get_cached_price(symbol)
        if cached:
            return cached
        
        start_time = time.time()
        self._request_count += 1
        
        try:
            price = await self._fetch_price_impl(symbol)
            
            latency_ms = (time.time() - start_time) * 1000
            self._total_latency_ms += latency_ms
            self._last_update = time.time()
            
            if price:
                self._price_cache[symbol] = price
            
            return price
            
        except Exception as e:
            self._error_count += 1
            self._logger.error("Price fetch failed for %s: %s", symbol, e)
            return None
    
    async def get_prices(self, symbols: List[str]) -> Dict[str, OraclePrice]:
        """
        Get prices for multiple symbols.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping symbol to OraclePrice
        """
        results: Dict[str, OraclePrice] = {}
        
        for symbol in symbols:
            price = await self.get_price(symbol)
            if price:
                results[symbol] = price
        
        return results
    
    @abstractmethod
    async def _connect_impl(self) -> bool:
        """Implementation-specific connection logic."""
        raise NotImplementedError
    
    @abstractmethod
    async def _disconnect_impl(self) -> None:
        """Implementation-specific disconnection logic."""
        raise NotImplementedError
    
    @abstractmethod
    async def _fetch_price_impl(self, symbol: str) -> Optional[OraclePrice]:
        """Implementation-specific price fetching."""
        raise NotImplementedError

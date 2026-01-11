"""
Pyth Oracle - Secondary oracle per MASTER_SPEC v1.0

Oracle ID: pyth
Priority: 2 (Secondary - lowest latency)

Pyth Network provides high-frequency price updates with low latency.
This is the secondary oracle in the triple-redundant stack.

Reference: MASTER_SPEC.md Section 3 (Layer 5: Oracle Stack)
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 2.3 (Fallback Order)
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from oracles.base_oracle import BaseOracle, OraclePrice, OracleStatus
from utils.logger import get_logger

logger = get_logger("oracles.pyth")


PYTH_PRICE_FEED_IDS: Dict[str, str] = {
    "BTC/USD": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH/USD": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "SOL/USD": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    "LINK/USD": "0x8ac0c70fff57e9aefdf5edf44b51d62c2d433653cbb2cf5cc06bb115af04d221",
    "AVAX/USD": "0x93da3352f9f1d105fdfe4971cfa80e9dd777bfc5d0f683ebb6e1294b92137bb7",
}


class PythOracle(BaseOracle):
    """
    Pyth Network price oracle implementation.
    
    Uses Pyth's high-frequency price feeds for low-latency data.
    In production, this would query Pyth's Hermes API or on-chain feeds.
    For development, uses simulated data with realistic behavior.
    """
    
    ORACLE_ID = "pyth"
    PRIORITY = 2
    
    def __init__(self) -> None:
        """Initialize Pyth oracle."""
        super().__init__(
            oracle_id=self.ORACLE_ID,
            priority=self.PRIORITY,
        )
        self._feed_ids = PYTH_PRICE_FEED_IDS.copy()
        self._hermes_client: Optional[object] = None
        self._simulated_prices: Dict[str, float] = {
            "BTC/USD": 97500.0,
            "ETH/USD": 3450.0,
            "SOL/USD": 195.0,
            "LINK/USD": 14.5,
            "AVAX/USD": 38.0,
        }
    
    async def _connect_impl(self) -> bool:
        """
        Connect to Pyth Hermes API.
        
        In production: Initialize connection to Pyth Hermes.
        In development: Use simulated connection.
        """
        try:
            self._logger.info("Connecting to Pyth Network...")
            self._status = OracleStatus.CONNECTED
            return True
        except Exception as e:
            self._logger.error("Pyth connection failed: %s", e)
            return False
    
    async def _disconnect_impl(self) -> None:
        """Disconnect from Pyth."""
        self._hermes_client = None
    
    async def _fetch_price_impl(self, symbol: str) -> Optional[OraclePrice]:
        """
        Fetch price from Pyth feed.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            
        Returns:
            OraclePrice with Pyth data
        """
        if symbol not in self._feed_ids:
            self._logger.warning("No Pyth feed for %s", symbol)
            return None
        
        base_price = self._simulated_prices.get(symbol, 100.0)
        import random
        noise = base_price * random.uniform(-0.0015, 0.0015)
        price = base_price + noise
        
        confidence_interval = base_price * 0.0005
        
        return OraclePrice(
            oracle_id=self._oracle_id,
            symbol=symbol,
            price=price,
            timestamp=time.time(),
            confidence=0.98,
            source_timestamp=time.time(),
            metadata={
                "feed_id": self._feed_ids[symbol],
                "confidence_interval": confidence_interval,
                "expo": -8,
                "publish_time": int(time.time()),
            },
        )
    
    def update_simulated_price(self, symbol: str, price: float) -> None:
        """Update simulated price for testing."""
        self._simulated_prices[symbol] = price


_pyth_oracle: Optional[PythOracle] = None


def get_pyth_oracle() -> PythOracle:
    """Get or create Pyth oracle singleton."""
    global _pyth_oracle
    if _pyth_oracle is None:
        _pyth_oracle = PythOracle()
    return _pyth_oracle

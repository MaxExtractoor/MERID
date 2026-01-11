"""
Switchboard Oracle - Tertiary oracle per MASTER_SPEC v1.0

Oracle ID: switchboard
Priority: 3 (Tertiary - backup)

Switchboard provides decentralized oracle feeds as backup.
This is the tertiary oracle in the triple-redundant stack.

Reference: MASTER_SPEC.md Section 3 (Layer 5: Oracle Stack)
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 2.3 (Fallback Order)
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from oracles.base_oracle import BaseOracle, OraclePrice, OracleStatus
from utils.logger import get_logger

logger = get_logger("oracles.switchboard")


SWITCHBOARD_FEED_ADDRESSES: Dict[str, str] = {
    "BTC/USD": "8SXvChNYFhRq4EZuZvnhjrB3jJRQCv4k3P4W6hesH3Ee",
    "ETH/USD": "JBu1AL4obBcCMqKBBxhpWCNUt136ijcuMZLFvTP7iWdB",
    "SOL/USD": "GvDMxPzN1sCj7L26YDK2HnMRXEQmQ2aemov8YBtPS7vR",
}


class SwitchboardOracle(BaseOracle):
    """
    Switchboard price oracle implementation.
    
    Uses Switchboard's decentralized oracle network as backup.
    In production, this would query Switchboard feeds on Solana.
    For development, uses simulated data with realistic behavior.
    """
    
    ORACLE_ID = "switchboard"
    PRIORITY = 3
    
    def __init__(self) -> None:
        """Initialize Switchboard oracle."""
        super().__init__(
            oracle_id=self.ORACLE_ID,
            priority=self.PRIORITY,
        )
        self._feed_addresses = SWITCHBOARD_FEED_ADDRESSES.copy()
        self._solana_client: Optional[object] = None
        self._simulated_prices: Dict[str, float] = {
            "BTC/USD": 97500.0,
            "ETH/USD": 3450.0,
            "SOL/USD": 195.0,
        }
    
    async def _connect_impl(self) -> bool:
        """
        Connect to Switchboard feeds.
        
        In production: Initialize Solana RPC connection.
        In development: Use simulated connection.
        """
        try:
            self._logger.info("Connecting to Switchboard oracle network...")
            self._status = OracleStatus.CONNECTED
            return True
        except Exception as e:
            self._logger.error("Switchboard connection failed: %s", e)
            return False
    
    async def _disconnect_impl(self) -> None:
        """Disconnect from Switchboard."""
        self._solana_client = None
    
    async def _fetch_price_impl(self, symbol: str) -> Optional[OraclePrice]:
        """
        Fetch price from Switchboard feed.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            
        Returns:
            OraclePrice with Switchboard data
        """
        if symbol not in self._feed_addresses:
            self._logger.warning("No Switchboard feed for %s", symbol)
            return None
        
        base_price = self._simulated_prices.get(symbol, 100.0)
        import random
        noise = base_price * random.uniform(-0.002, 0.002)
        price = base_price + noise
        
        return OraclePrice(
            oracle_id=self._oracle_id,
            symbol=symbol,
            price=price,
            timestamp=time.time(),
            confidence=0.95,
            source_timestamp=time.time(),
            metadata={
                "feed_address": self._feed_addresses[symbol],
                "aggregator_round": int(time.time()),
            },
        )
    
    def update_simulated_price(self, symbol: str, price: float) -> None:
        """Update simulated price for testing."""
        self._simulated_prices[symbol] = price


_switchboard_oracle: Optional[SwitchboardOracle] = None


def get_switchboard_oracle() -> SwitchboardOracle:
    """Get or create Switchboard oracle singleton."""
    global _switchboard_oracle
    if _switchboard_oracle is None:
        _switchboard_oracle = SwitchboardOracle()
    return _switchboard_oracle

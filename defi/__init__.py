"""
DeFi Integration Layer for MERID Treasury.

Provides integration with DeFi protocols for yield generation:
- Aave V3 lending/borrowing
- Health factor monitoring
- Auto-rebalancing
"""

from defi.aave import (
    AaveClient,
    AaveConfig,
    AavePosition,
    AaveAccountData,
    AaveTransaction,
    AaveOperationType,
    get_aave_client,
    stash_profits,
)

__all__ = [
    "AaveClient",
    "AaveConfig",
    "AavePosition",
    "AaveAccountData",
    "AaveTransaction",
    "AaveOperationType",
    "get_aave_client",
    "stash_profits",
]

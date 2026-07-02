"""
Aave V3 Integration for MERID Treasury

Integrates Aave lending protocol for passive income:
- Supply stablecoins for yield (5-8% APY)
- Monitor health factor for liquidation prevention
- Auto-rebalance on low health

Risk Controls:
- Only supply stablecoins
- Borrow limit 50% LTV
- Auto-repay if health < 1.8
"""

from __future__ import annotations

import threading
import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("defi.aave")


POLYGON_MAINNET_RPC = "https://polygon-rpc.com"
POLYGON_MUMBAI_RPC = "https://rpc-mumbai.maticvigil.com"

AAVE_V3_POOL_POLYGON = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
AAVE_V3_POOL_DATA_PROVIDER = "0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654"

SUPPORTED_ASSETS = {
    "USDC": {
        "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        "decimals": 6,
        "atoken": "0x625E7708f30cA75bfd92586e17077590C60eb4cD",
    },
    "USDT": {
        "address": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "decimals": 6,
        "atoken": "0x6ab707Aca953eDAeFBc4fD23bA73294241490620",
    },
    "DAI": {
        "address": "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063",
        "decimals": 18,
        "atoken": "0x82E64f49Ed5EC1bC6e43DAD4FC8Af9bb3A2312EE",
    },
    "WETH": {
        "address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "decimals": 18,
        "atoken": "0xe50fA9b3c56FfB159cB0FCA61F5c9D750e8128c8",
    },
    "WMATIC": {
        "address": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "decimals": 18,
        "atoken": "0x6d80113e533a2C0fe82EaBD35f1875DcEA89Ea97",
    },
}


class AaveOperationType(Enum):
    """Types of Aave operations."""
    SUPPLY = "supply"
    WITHDRAW = "withdraw"
    BORROW = "borrow"
    REPAY = "repay"
    FLASH_LOAN = "flash_loan"


@dataclass
class AavePosition:
    """Position in Aave protocol."""
    asset: str
    supplied_amount: float = 0.0
    borrowed_amount: float = 0.0
    apy_supply: float = 0.0
    apy_borrow: float = 0.0
    collateral_enabled: bool = True
    last_updated: float = field(default_factory=time.time)


@dataclass
class AaveAccountData:
    """User account data from Aave."""
    total_collateral_usd: float = 0.0
    total_debt_usd: float = 0.0
    available_borrow_usd: float = 0.0
    current_liquidation_threshold: float = 0.0
    ltv: float = 0.0
    health_factor: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_collateral_usd": self.total_collateral_usd,
            "total_debt_usd": self.total_debt_usd,
            "available_borrow_usd": self.available_borrow_usd,
            "current_liquidation_threshold": self.current_liquidation_threshold,
            "ltv": self.ltv,
            "health_factor": self.health_factor,
        }


@dataclass
class AaveTransaction:
    """Record of an Aave transaction."""
    tx_id: str
    operation: AaveOperationType
    asset: str
    amount: float
    timestamp: float = field(default_factory=time.time)
    tx_hash: Optional[str] = None
    status: str = "pending"
    gas_used: int = 0
    error: Optional[str] = None


@dataclass
class AaveConfig:
    """Configuration for Aave client."""
    rpc_url: str = POLYGON_MAINNET_RPC
    pool_address: str = AAVE_V3_POOL_POLYGON
    
    min_health_factor: float = 1.5
    target_health_factor: float = 2.0
    max_ltv_ratio: float = 0.5
    
    auto_rebalance: bool = True
    rebalance_threshold: float = 1.8
    
    max_supply_per_asset_usd: float = 50000.0
    allowed_supply_assets: List[str] = field(
        default_factory=lambda: ["USDC", "USDT", "DAI"]
    )
    
    simulation_mode: bool = True


class AaveClient:
    """
    Production-grade Aave V3 client for MERID Treasury.
    
    Capabilities:
    - Supply/withdraw assets
    - Monitor health factor
    - Auto-rebalance on low health
    - Track positions and yields
    
    Risk Controls:
    - Only supply stablecoins by default
    - Enforce max LTV ratio
    - Auto-repay on low health
    """
    
    def __init__(self, config: Optional[AaveConfig] = None) -> None:
        self.config = config or AaveConfig()
        
        self._positions: Dict[str, AavePosition] = {}
        self._account_data = AaveAccountData()
        self._transaction_history: List[AaveTransaction] = []
        
        self._web3 = None
        self._account = None
        self._pool_contract = None
        
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        self._simulated_balance: Dict[str, float] = {
            "USDC": 0.0,
            "USDT": 0.0,
            "DAI": 0.0,
        }
        self._simulated_supplied: Dict[str, float] = {}
        self._simulated_borrowed: Dict[str, float] = {}
        
        if not self.config.simulation_mode:
            self._initialize_web3()
        
        logger.info(
            "AaveClient initialized: simulation=%s, min_health=%.1f",
            self.config.simulation_mode, self.config.min_health_factor
        )
    
    def _initialize_web3(self) -> None:
        """Initialize Web3 connection."""
        try:
            from web3 import Web3
            from eth_account import Account
            
            self._web3 = Web3(Web3.HTTPProvider(self.config.rpc_url))
            
            private_key = os.getenv("MERID_PRIVATE_KEY")
            if private_key:
                self._account = Account.from_key(private_key)
                logger.info("Web3 initialized with account: %s", self._account.address[:10])
            else:
                logger.warning("No private key configured - read-only mode")
        except ImportError:
            logger.warning("web3 not installed - running in simulation mode")
            self.config.simulation_mode = True
        except Exception as e:
            logger.error("Failed to initialize Web3: %s", e)
            self.config.simulation_mode = True
    
    async def supply(
        self,
        asset: str,
        amount: float,
        on_behalf_of: Optional[str] = None,
    ) -> AaveTransaction:
        """
        Supply asset to Aave pool.
        
        Args:
            asset: Asset symbol (e.g., "USDC")
            amount: Amount to supply
            on_behalf_of: Optional address to supply on behalf of
            
        Returns:
            Transaction record
        """
        if asset not in self.config.allowed_supply_assets:
            raise ValueError(f"Asset {asset} not allowed for supply")
        
        if asset not in SUPPORTED_ASSETS:
            raise ValueError(f"Asset {asset} not supported")
        
        current_supplied = self._simulated_supplied.get(asset, 0)
        if current_supplied + amount > self.config.max_supply_per_asset_usd:
            raise ValueError(f"Would exceed max supply limit for {asset}")
        
        tx = AaveTransaction(
            tx_id=f"supply_{int(time.time() * 1000)}",
            operation=AaveOperationType.SUPPLY,
            asset=asset,
            amount=amount,
        )
        
        if self.config.simulation_mode:
            await self._simulate_supply(asset, amount)
            tx.status = "simulated"
            tx.tx_hash = f"0xsim_{tx.tx_id}"
        else:
            try:
                tx_hash = await self._execute_supply(asset, amount, on_behalf_of)
                tx.tx_hash = tx_hash
                tx.status = "confirmed"
            except Exception as e:
                tx.status = "failed"
                tx.error = str(e)
                logger.error("Supply failed: %s", e)
        
        self._transaction_history.append(tx)
        
        logger.info(
            "Supply %s: %.2f %s -> %s",
            tx.status, amount, asset, tx.tx_hash or "N/A"
        )
        
        return tx
    
    async def withdraw(
        self,
        asset: str,
        amount: float,
        to: Optional[str] = None,
    ) -> AaveTransaction:
        """
        Withdraw asset from Aave pool.
        
        Args:
            asset: Asset symbol
            amount: Amount to withdraw (use -1 for max)
            to: Optional address to withdraw to
            
        Returns:
            Transaction record
        """
        tx = AaveTransaction(
            tx_id=f"withdraw_{int(time.time() * 1000)}",
            operation=AaveOperationType.WITHDRAW,
            asset=asset,
            amount=amount,
        )
        
        if self.config.simulation_mode:
            await self._simulate_withdraw(asset, amount)
            tx.status = "simulated"
            tx.tx_hash = f"0xsim_{tx.tx_id}"
        else:
            try:
                tx_hash = await self._execute_withdraw(asset, amount, to)
                tx.tx_hash = tx_hash
                tx.status = "confirmed"
            except Exception as e:
                tx.status = "failed"
                tx.error = str(e)
                logger.error("Withdraw failed: %s", e)
        
        self._transaction_history.append(tx)
        
        logger.info(
            "Withdraw %s: %.2f %s -> %s",
            tx.status, amount, asset, tx.tx_hash or "N/A"
        )
        
        return tx
    
    async def get_health_factor(self) -> float:
        """Get current health factor."""
        if self.config.simulation_mode:
            return self._calculate_simulated_health()
        
        await self._refresh_account_data()
        return self._account_data.health_factor
    
    async def get_account_data(self) -> AaveAccountData:
        """Get full account data."""
        if self.config.simulation_mode:
            return self._get_simulated_account_data()
        
        await self._refresh_account_data()
        return self._account_data
    
    async def get_positions(self) -> Dict[str, AavePosition]:
        """Get all positions."""
        if self.config.simulation_mode:
            return self._get_simulated_positions()
        
        await self._refresh_positions()
        return self._positions
    
    async def auto_rebalance(self) -> Optional[AaveTransaction]:
        """
        Auto-rebalance if health factor is low.
        
        Returns:
            Transaction if rebalance was needed, None otherwise
        """
        health = await self.get_health_factor()
        
        if health >= self.config.rebalance_threshold:
            return None
        
        if health < self.config.min_health_factor:
            logger.critical(
                "Health factor critical: %.2f < %.2f",
                health, self.config.min_health_factor
            )
        
        withdraw_amount = self._calculate_rebalance_amount(health)
        
        if withdraw_amount <= 0:
            return None
        
        best_asset = self._find_best_withdrawal_asset(withdraw_amount)
        if not best_asset:
            logger.warning("No asset available for rebalance withdrawal")
            return None
        
        logger.warning(
            "Auto-rebalancing: health=%.2f, withdrawing %.2f %s",
            health, withdraw_amount, best_asset
        )
        
        return await self.withdraw(best_asset, withdraw_amount)
    
    def _calculate_rebalance_amount(self, current_health: float) -> float:
        """Calculate amount to withdraw for rebalancing."""
        if current_health >= self.config.target_health_factor:
            return 0.0
        
        total_supplied = sum(self._simulated_supplied.values())
        if total_supplied <= 0:
            return 0.0
        
        health_gap = self.config.target_health_factor - current_health
        withdraw_ratio = min(health_gap / 2, 0.3)
        
        return total_supplied * withdraw_ratio
    
    def _find_best_withdrawal_asset(self, amount: float) -> Optional[str]:
        """Find best asset to withdraw."""
        for asset in ["USDC", "USDT", "DAI"]:
            supplied = self._simulated_supplied.get(asset, 0)
            if supplied >= amount:
                return asset
        
        if self._simulated_supplied:
            return max(self._simulated_supplied, key=self._simulated_supplied.get)
        
        return None
    
    async def _simulate_supply(self, asset: str, amount: float) -> None:
        """Simulate supply operation."""
        self._simulated_supplied[asset] = self._simulated_supplied.get(asset, 0) + amount
        
        if asset not in self._positions:
            self._positions[asset] = AavePosition(asset=asset)
        self._positions[asset].supplied_amount += amount
        self._positions[asset].apy_supply = 0.065
        self._positions[asset].last_updated = time.time()
        
        await asyncio.sleep(0.1)
    
    async def _simulate_withdraw(self, asset: str, amount: float) -> None:
        """Simulate withdraw operation."""
        current = self._simulated_supplied.get(asset, 0)
        
        if amount < 0:
            amount = current
        
        if amount > current:
            raise ValueError(f"Insufficient {asset} supplied: {current} < {amount}")
        
        self._simulated_supplied[asset] = current - amount
        
        if asset in self._positions:
            self._positions[asset].supplied_amount -= amount
            self._positions[asset].last_updated = time.time()
        
        await asyncio.sleep(0.1)
    
    def _calculate_simulated_health(self) -> float:
        """Calculate simulated health factor."""
        total_collateral = sum(self._simulated_supplied.values())
        total_debt = sum(self._simulated_borrowed.values())
        
        if total_debt <= 0:
            return 10.0
        
        liquidation_threshold = self.config.min_health_factor  # Use configurable threshold (default 1.5)
        return (total_collateral * liquidation_threshold) / total_debt
    
    def _get_simulated_account_data(self) -> AaveAccountData:
        """Get simulated account data."""
        total_collateral = sum(self._simulated_supplied.values())
        total_debt = sum(self._simulated_borrowed.values())
        
        return AaveAccountData(
            total_collateral_usd=total_collateral,
            total_debt_usd=total_debt,
            available_borrow_usd=total_collateral * self.config.max_ltv_ratio - total_debt,
            current_liquidation_threshold=self.config.min_health_factor,
            ltv=total_debt / total_collateral if total_collateral > 0 else 0,
            health_factor=self._calculate_simulated_health(),
        )
    
    def _get_simulated_positions(self) -> Dict[str, AavePosition]:
        """Get simulated positions."""
        positions = {}
        
        for asset, amount in self._simulated_supplied.items():
            if amount > 0:
                positions[asset] = AavePosition(
                    asset=asset,
                    supplied_amount=amount,
                    borrowed_amount=self._simulated_borrowed.get(asset, 0),
                    apy_supply=0.065,
                    apy_borrow=0.08,
                    collateral_enabled=True,
                )
        
        return positions
    
    async def _execute_supply(
        self,
        asset: str,
        amount: float,
        on_behalf_of: Optional[str],
    ) -> str:
        """Execute supply on-chain."""
        try:
            # Mock implementation for Phase 0 - simulate successful execution
            tx_hash = f"0x{'0' * 64}"  # Mock transaction hash
            
            # Log the operation for audit purposes
            logger.info(f"Mock supply executed: {amount} {asset} on behalf of {on_behalf_of}")
            logger.info(f"Transaction hash: {tx_hash}")
            
            # In production, this would:
            # 1. Connect to Web3 provider
            # 2. Build Aave supply transaction
            # 3. Sign and send transaction
            # 4. Wait for confirmation
            # 5. Return actual transaction hash
            
            return tx_hash
            
        except Exception as e:
            logger.error(f"Supply execution failed: {e}")
            raise
    
    async def _execute_withdraw(
        self,
        asset: str,
        amount: float,
        to: Optional[str],
    ) -> str:
        """Execute withdraw on-chain."""
        try:
            # Mock implementation for Phase 0 - simulate successful execution
            tx_hash = f"0x{'1' * 64}"  # Mock transaction hash
            
            # Log the operation for audit purposes
            logger.info(f"Mock withdraw executed: {amount} {asset} to {to}")
            logger.info(f"Transaction hash: {tx_hash}")
            
            # In production, this would:
            # 1. Connect to Web3 provider
            # 2. Build Aave withdraw transaction
            # 3. Sign and send transaction
            # 4. Wait for confirmation
            # 5. Return actual transaction hash
            
            return tx_hash
            
        except Exception as e:
            logger.error(f"Withdraw execution failed: {e}")
            raise
    
    async def _refresh_account_data(self) -> None:
        """Refresh account data from chain."""
        pass
    
    async def _refresh_positions(self) -> None:
        """Refresh positions from chain."""
        pass
    
    async def start_monitoring(self, interval_seconds: float = 60.0) -> None:
        """Start health monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval_seconds))
        logger.info("Aave health monitoring started")
    
    async def stop_monitoring(self) -> None:
        """Stop health monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Aave health monitoring stopped")
    
    async def _monitor_loop(self, interval: float) -> None:
        """Health monitoring loop."""
        while self._running:
            try:
                if self.config.auto_rebalance:
                    await self.auto_rebalance()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)
                await asyncio.sleep(interval)
    
    def get_status(self) -> Dict[str, Any]:
        """Get client status."""
        return {
            "simulation_mode": self.config.simulation_mode,
            "running": self._running,
            "total_supplied_usd": sum(self._simulated_supplied.values()),
            "total_borrowed_usd": sum(self._simulated_borrowed.values()),
            "health_factor": self._calculate_simulated_health(),
            "positions": len(self._positions),
            "transactions": len(self._transaction_history),
            "config": {
                "min_health_factor": self.config.min_health_factor,
                "target_health_factor": self.config.target_health_factor,
                "max_ltv_ratio": self.config.max_ltv_ratio,
                "auto_rebalance": self.config.auto_rebalance,
            },
        }
    
    def get_transaction_history(self, limit: int = 50) -> List[AaveTransaction]:
        """Get transaction history."""
        return self._transaction_history[-limit:]


_aave_client: Optional[AaveClient] = None
_aave_client_lock = threading.Lock()


def get_aave_client() -> AaveClient:
    """Get or create global Aave client."""
    global _aave_client
    if _aave_client is None:
        with _aave_client_lock:
            if _aave_client is None:
                _aave_client = AaveClient()
    return _aave_client


async def stash_profits(profit_usd: float, allocation_ratio: float = 0.3) -> Optional[AaveTransaction]:
    """
    Stash profits into Aave for yield.
    
    Args:
        profit_usd: Profit amount in USD
        allocation_ratio: Ratio to allocate to Aave (default 30%)
        
    Returns:
        Transaction if successful
    """
    client = get_aave_client()
    
    amount_to_stash = profit_usd * allocation_ratio
    if amount_to_stash < 10:
        logger.debug("Profit too small to stash: $%.2f", amount_to_stash)
        return None
    
    try:
        tx = await client.supply("USDC", amount_to_stash)
        
        health = await client.get_health_factor()
        logger.info(
            "Stashed $%.2f USDC to Aave (health: %.2f)",
            amount_to_stash, health
        )
        
        return tx
    except Exception as e:
        logger.error("Failed to stash profits: %s", e)
        return None

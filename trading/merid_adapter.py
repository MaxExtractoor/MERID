"""
MERID Trading Adapter - Connects MERID strategies to self-hosted execution

This adapter integrates MERID's trading system with the self-hosted execution simulator,
providing a drop-in replacement for external brokers like Alpaca.
"""

from __future__ import annotations

import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
import time
import json

from merid.execution.router import ExecutionRouter, get_execution_router
from utils.logger import get_logger

logger = get_logger("trading.merid_adapter")


class MeridExecutionAdapter:
    """
    Adapter that connects MERID's trading system to the self-hosted execution service.
    
    Provides the same interface as external broker adapters but uses local execution.
    """
    
    def __init__(self, execution_service_url: str = "http://127.0.0.1:8012"):
        self.execution_service_url = execution_service_url
        self._router: Optional[ExecutionRouter] = None
        self.account_id = "merid_sim_account"
        self.session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        
        logger.info(f"MeridExecutionAdapter initialized (service: {execution_service_url})")
    
    async def connect(self) -> None:
        """Connect to the execution service."""
        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
            
            # Check if service is healthy
            async with self.session.get(f"{self.execution_service_url}/health") as response:
                if response.status == 200:
                    health = await response.json()
                    if health.get("status") == "healthy":
                        # Create account if it doesn't exist
                        await self._ensure_account_exists()
                        self._connected = True
                        logger.info("Connected to execution service")
                        return
            
            raise RuntimeError("Execution service not healthy")
            
        except Exception as e:
            logger.error(f"Failed to connect to execution service: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from the execution service."""
        if self.session:
            await self.session.close()
            self.session = None
        self._connected = False
        logger.info("Disconnected from execution service")
    
    async def _ensure_account_exists(self) -> None:
        """Ensure the MERID account exists in the execution service."""
        try:
            async with self.session.get(f"{self.execution_service_url}/accounts/{self.account_id}") as response:
                if response.status == 404:
                    # Create account
                    account_data = {
                        "account_id": self.account_id,
                        "initial_cash": 100000.0
                    }
                    async with self.session.post(
                        f"{self.execution_service_url}/accounts",
                        json=account_data
                    ) as create_response:
                        if create_response.status == 200:
                            logger.info(f"Created account {self.account_id}")
                        else:
                            raise RuntimeError(f"Failed to create account: {create_response.status}")
        except Exception as e:
            logger.error(f"Error ensuring account exists: {e}")
            raise
    
    async def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an order to the execution service."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            # Add account_id to order data
            order_data["account_id"] = self.account_id
            
            async with self.session.post(
                f"{self.execution_service_url}/orders",
                json=order_data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Submitted order {result.get('order_id')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Order submission failed: {response.status} - {error_text}")
                    raise RuntimeError(f"Order submission failed: {response.status}")
        
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            raise
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            async with self.session.delete(f"{self.execution_service_url}/orders/{order_id}") as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Cancelled order {order_id}")
                    return result.get("status") == "cancelled"
                else:
                    logger.warning(f"Failed to cancel order {order_id}: {response.status}")
                    return False
        
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get orders."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            params = {}
            if status:
                params["status"] = status
            
            async with self.session.get(
                f"{self.execution_service_url}/orders",
                params=params
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("orders", [])
                else:
                    logger.error(f"Failed to get orders: {response.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get positions."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            async with self.session.get(f"{self.execution_service_url}/positions") as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("positions", [])
                else:
                    logger.error(f"Failed to get positions: {response.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    async def get_account(self) -> Dict[str, Any]:
        """Get account information."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            async with self.session.get(f"{self.execution_service_url}/accounts/{self.account_id}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get account: {response.status}")
                    raise RuntimeError(f"Failed to get account: {response.status}")
        
        except Exception as e:
            logger.error(f"Error getting account: {e}")
            raise
    
    async def update_market_data(self, market_data: Dict[str, Any]) -> None:
        """Update market data (for testing)."""
        if not self._connected or not self.session:
            raise RuntimeError("Not connected to execution service")
        
        try:
            async with self.session.post(
                f"{self.execution_service_url}/market-data",
                json=market_data
            ) as response:
                if response.status != 200:
                    logger.warning(f"Failed to update market data: {response.status}")
        
        except Exception as e:
            logger.error(f"Error updating market data: {e}")
    
    def is_connected(self) -> bool:
        """Check if connected to execution service."""
        return self._connected


class MeridPaperTradingEngine:
    """
    Paper trading engine that uses the self-hosted execution service.
    
    This replaces the external paper trading broker with our own infrastructure.
    """
    
    def __init__(self, execution_service_url: str = "http://127.0.0.1:8012"):
        self.adapter = MeridExecutionAdapter(execution_service_url)
        self._running = False
        
        logger.info("MeridPaperTradingEngine initialized")
    
    async def start(self) -> None:
        """Start the paper trading engine."""
        if self._running:
            return
        
        try:
            await self.adapter.connect()
            self._running = True
            logger.info("MeridPaperTradingEngine started")
        
        except Exception as e:
            logger.error(f"Failed to start paper trading engine: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the paper trading engine."""
        if not self._running:
            return
        
        try:
            await self.adapter.disconnect()
            self._running = False
            logger.info("MeridPaperTradingEngine stopped")
        
        except Exception as e:
            logger.error(f"Error stopping paper trading engine: {e}")
    
    def is_running(self) -> bool:
        """Check if the engine is running."""
        return self._running
    
    async def place_order(self, symbol: str, side: str, order_type: str, quantity: float,
                        price: Optional[float] = None, stop_price: Optional[float] = None) -> Dict[str, Any]:
        """Place an order."""
        order_data = {
            "symbol": symbol,
            "side": side.lower(),
            "order_type": order_type.lower(),
            "quantity": quantity
        }
        
        if price is not None:
            order_data["price"] = price
        if stop_price is not None:
            order_data["stop_price"] = stop_price
        
        return await self.adapter.submit_order(order_data)
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        return await self.adapter.cancel_order(order_id)
    
    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get orders."""
        return await self.adapter.get_orders(status)
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get positions."""
        return await self.adapter.get_positions()
    
    async def get_portfolio(self) -> Dict[str, Any]:
        """Get portfolio information."""
        account = await self.adapter.get_account()
        return {
            "cash": account.get("cash", 0.0),
            "buying_power": account.get("buying_power", 0.0),
            "total_unrealized_pnl": account.get("total_unrealized_pnl", 0.0),
            "total_realized_pnl": account.get("total_realized_pnl", 0.0),
            "total_pnl": account.get("total_unrealized_pnl", 0.0) + account.get("total_realized_pnl", 0.0)
        }


# Global paper trading engine instance
_paper_engine: Optional[MeridPaperTradingEngine] = None


def get_paper_engine() -> MeridPaperTradingEngine:
    """Get the global paper trading engine instance."""
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = MeridPaperTradingEngine()
    return _paper_engine


# Integration function for MERID's existing paper trading system
async def initialize_self_hosted_paper_trading(execution_service_url: str = "http://127.0.0.1:8012") -> MeridPaperTradingEngine:
    """
    Initialize self-hosted paper trading for MERID.
    
    This function should be called instead of the external broker initialization
    when using the self-hosted execution infrastructure.
    """
    engine = MeridPaperTradingEngine(execution_service_url)
    await engine.start()
    
    logger.info("Self-hosted paper trading initialized")
    return engine


# Utility function to check if execution service is available
async def is_execution_service_available(url: str = "http://127.0.0.1:8012") -> bool:
    """Check if the execution service is available."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=5)) as response:
                return response.status == 200
    except:
        return False

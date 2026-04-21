"""
Self-Hosted Execution Service - Main service for paper trading without third parties

Integrates:
- Execution simulator
- Market data ingestor  
- Venue adapters
- Risk management
- REST/WebSocket API for MERID integration
"""

from __future__ import annotations

import threading
import asyncio
import json
import time
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
from contextlib import asynccontextmanager

from execution.simulator import get_execution_simulator, MarketData
from execution.simulator_adapter import create_simulator_adapter
from execution.venue_adapter import get_venue_manager, VenueOrder, OrderStatus
from execution.market_data_ingestor import get_market_data_ingestor, create_binance_websocket_config, create_kraken_websocket_config
from utils.logger import get_logger

logger = get_logger("execution.service")


class ExecutionService:
    """Main execution service orchestrator."""
    
    def __init__(self):
        self.simulator = get_execution_simulator()
        self.venue_manager = get_venue_manager()
        self.market_data_ingestor = get_market_data_ingestor()
        self.app = FastAPI(title="MERID Execution Service", version="1.0.0")
        self._setup_routes()
        self._running = False
        
        logger.info("ExecutionService initialized")
    
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Manage application lifecycle."""
        # Startup
        await self.start()
        yield
        # Shutdown
        await self.stop()
    
    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "simulator_running": self.simulator._running if self.simulator else False,
                "venue_connected": self.venue_manager.is_connected(),
                "market_data_running": self.market_data_ingestor._running if self.market_data_ingestor else False
            }
        
        @self.app.post("/accounts")
        async def create_account(account_data: Dict[str, Any]):
            """Create a new trading account."""
            try:
                account_id = account_data.get("account_id", "default")
                initial_cash = account_data.get("initial_cash", 100000.0)
                
                account = self.simulator.create_account(account_id, initial_cash)
                return {
                    "account_id": account.account_id,
                    "cash": account.cash,
                    "buying_power": account.buying_power
                }
            except (ValueError, TypeError) as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/accounts/{account_id}")
        async def get_account(account_id: str):
            """Get account information."""
            try:
                summary = self.simulator.get_account_summary(account_id)
                return summary
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=404, detail=str(e))
        
        @self.app.post("/orders")
        async def submit_order(order_data: Dict[str, Any]):
            """Submit a new order."""
            try:
                account_id = order_data["account_id"]
                symbol = order_data["symbol"]
                side = order_data["side"]
                order_type = order_data["order_type"]
                quantity = order_data["quantity"]
                price = order_data.get("price")
                stop_price = order_data.get("stop_price")
                
                _t0 = time.perf_counter()
                result = self.simulator.submit_order(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    stop_price=stop_price
                )
                _latency_ms = (time.perf_counter() - _t0) * 1000
                if isinstance(result, dict):
                    result["submit_latency_ms"] = round(_latency_ms, 1)
                if _latency_ms > 500:
                    logger.warning("High order submit latency: %.1fms for %s", _latency_ms, symbol)
                
                return result
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.delete("/orders/{order_id}")
        async def cancel_order(order_id: str):
            """Cancel an order."""
            try:
                # Find the account that owns this order
                account_id = None
                for acc in self.simulator.accounts.values():
                    if order_id in acc.orders:
                        account_id = acc.account_id
                        break
                
                if not account_id:
                    raise HTTPException(status_code=404, detail="Order not found")
                
                result = self.simulator.cancel_order(account_id, order_id)
                return result
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/orders")
        async def get_orders(account_id: str, status: Optional[str] = None):
            """Get orders for an account."""
            try:
                orders = self.simulator.get_orders(account_id, status)
                return {"orders": orders}
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=404, detail=str(e))
        
        @self.app.get("/positions")
        async def get_positions(account_id: str):
            """Get positions for an account."""
            try:
                positions = self.simulator.get_positions(account_id)
                return {"positions": positions}
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=404, detail=str(e))
        
        @self.app.post("/market-data")
        async def update_market_data(market_data: Dict[str, Any]):
            """Update market data (for testing)."""
            try:
                data = MarketData(
                    symbol=market_data["symbol"],
                    timestamp=market_data.get("timestamp", 0.0),
                    last_price=market_data.get("last_price"),
                    bid_price=market_data.get("bid_price"),
                    ask_price=market_data.get("ask_price"),
                    last_size=market_data.get("last_size"),
                    bid_size=market_data.get("bid_size"),
                    ask_size=market_data.get("ask_size")
                )
                self.simulator.update_market_data(data)
                return {"status": "updated"}
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.websocket("/ws/market-data/{account_id}")
        async def websocket_market_data(websocket: WebSocket, account_id: str):
            """WebSocket for real-time market data and order updates."""
            await websocket.accept()
            
            # Subscribe to updates
            def on_order_update(order):
                try:
                    asyncio.create_task(websocket.send_text(json.dumps({
                        "type": "order_update",
                        "data": order.__dict__
                    })))
                except (ConnectionError, RuntimeError):
                    pass
            
            def on_market_data(data):
                try:
                    asyncio.create_task(websocket.send_text(json.dumps({
                        "type": "market_data",
                        "data": {
                            "symbol": data.symbol,
                            "timestamp": data.timestamp,
                            "last_price": data.last_price,
                            "bid_price": data.bid_price,
                            "ask_price": data.ask_price
                        }
                    })))
                except (ConnectionError, RuntimeError):
                    pass
            
            # Get account and subscribe to orders
            account = self.simulator.get_account(account_id)
            if not account:
                await websocket.send_text(json.dumps({"error": "Account not found"}))
                await websocket.close()
                return
            
            # Subscribe to market data
            self.market_data_ingestor.subscribe(on_market_data)
            
            try:
                while True:
                    # Send account updates periodically
                    await asyncio.sleep(1)
                    summary = self.simulator.get_account_summary(account_id)
                    await websocket.send_text(json.dumps({
                        "type": "account_update",
                        "data": summary
                    }))
            
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for account {account_id}")
    
    async def start(self) -> None:
        """Start the execution service."""
        if self._running:
            return
        
        try:
            # Start simulator
            await self.simulator.start()
            
            # Setup venue adapter
            simulator_adapter = create_simulator_adapter()
            self.venue_manager.add_adapter("simulator", simulator_adapter, is_primary=True)
            await self.venue_manager.connect_all()
            
            # Setup market data sources
            binance_config = create_binance_websocket_config(["BTCUSD", "ETHUSD"])  # Binance USD pairs
            kraken_config = create_kraken_websocket_config(["BTC/USD", "ETH/USD"])
            
            self.market_data_ingestor.add_source("binance", binance_config)
            self.market_data_ingestor.add_source("kraken", kraken_config)
            await self.market_data_ingestor.start()
            
            self._running = True
            logger.info("ExecutionService started successfully")
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to start ExecutionService: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the execution service."""
        if not self._running:
            return
        
        try:
            await self.market_data_ingestor.stop()
            await self.venue_manager.disconnect_all()
            await self.simulator.stop()
            
            self._running = False
            logger.info("ExecutionService stopped")
            
        except (ConnectionError, RuntimeError) as e:
            logger.error(f"Error stopping ExecutionService: {e}")
    
    def run(self, host: str = "127.0.0.1", port: int = 8012) -> None:
        """Run the execution service."""
        self.app.router.lifespan_context = self.lifespan
        
        logger.info(f"Starting ExecutionService on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port, log_level="info")


# Global execution service instance
_execution_service: Optional[ExecutionService] = None
_execution_service_lock = threading.Lock()


def get_execution_service() -> ExecutionService:
    """Get the global execution service instance."""
    global _execution_service
    if _execution_service is None:
        with _execution_service_lock:
            if _execution_service is None:
                _execution_service = ExecutionService()
    return _execution_service


# CLI entry point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID Execution Service")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8012, help="Port to bind to")
    parser.add_argument("--mode", choices=["sim", "live"], default="sim", help="Trading mode")
    
    args = parser.parse_args()
    
    service = get_execution_service()
    
    if args.mode == "sim":
        logger.info("Starting in simulation mode")
        service.run(args.host, args.port)
    else:
        logger.info("Live mode not yet implemented")
        # TODO: Setup live venue adapters
        # - Alpaca adapter for stocks
        # - Binance/Kraken adapters for crypto
        # - FIX adapters for institutional

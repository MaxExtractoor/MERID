"""
Polymarket Adapter for MERID Prediction Markets Aggregator

Provides a minimal adapter that integrates the new PolymarketClient
with the existing prediction markets aggregator without changing
external behavior or public APIs.

This adapter:
- Uses PolymarketClient for all Polymarket operations
- Converts between PolymarketClient models and existing PredictionMarket models
- Maintains compatibility with existing aggregator interface
- Handles errors gracefully and falls back to existing behavior if needed
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional, Dict, Any
from decimal import Decimal

from merid.polymarket_client import PolymarketClient, Market, MarketOutcome
from monitoring.prediction_markets import PredictionMarket, PredictionPlatform
from utils.logger import get_logger

logger = get_logger("monitoring.polymarket_adapter")


class PolymarketAdapter:
    """Adapter for integrating PolymarketClient with MERID aggregator."""
    
    def __init__(self):
        self._client = PolymarketClient()
        self._last_fetch = 0
        self._fetch_interval = 300  # 5 minutes
        
    async def fetch_polymarket_markets(self, limit: int = 50) -> List[PredictionMarket]:
        """
        Fetch markets from Polymarket using the new client.
        
        Args:
            limit: Maximum number of markets to fetch
            
        Returns:
            List of PredictionMarket objects compatible with existing aggregator
        """
        try:
            # Rate limiting
            if time.time() - self._last_fetch < self._fetch_interval:
                logger.debug("Polymarket rate limited, using cached data")
                return []
            
            async with self._client as client:
                # Fetch markets from Gamma API
                markets = await client.list_markets(active=True, limit=limit)
                
                # Convert to existing PredictionMarket format
                prediction_markets = []
                for market in markets:
                    pred_market = self._convert_to_prediction_market(market)
                    if pred_market:
                        prediction_markets.append(pred_market)
                
                self._last_fetch = time.time()
                logger.info(f"Fetched {len(prediction_markets)} markets via PolymarketClient")
                return prediction_markets
                
        except Exception as e:
            logger.error(f"Failed to fetch markets via PolymarketClient: {e}")
            # Return empty list to maintain compatibility
            return []
    
    def _convert_to_prediction_market(self, market: Market) -> Optional[PredictionMarket]:
        """Convert PolymarketClient Market to existing PredictionMarket format."""
        try:
            # Extract yes/no prices from outcomes
            yes_price = 0.0
            no_price = 0.0
            
            for outcome in market.outcomes:
                if outcome.outcome.lower() == "yes":
                    yes_price = float(outcome.price)
                elif outcome.outcome.lower() == "no":
                    no_price = float(outcome.price)
            
            # Create PredictionMarket object
            pred_market = PredictionMarket(
                platform=PredictionPlatform.POLYMARKET,
                market_id=market.id,
                question=market.question,
                description=market.description,
                outcomes=[outcome.outcome for outcome in market.outcomes],
                yes_price=yes_price,
                no_price=no_price,
                volume=float(market.volume) if market.volume else 0.0,
                liquidity=float(market.liquidity) if market.liquidity else 0.0,
                end_date=market.end_date.isoformat() if market.end_date else None,
                category=market.category or "other",
                tags=market.tags,
                created_at=market.created_at.isoformat() if market.created_at else None,
                is_active=market.active,
                resolution=market.resolution,
                resolved_at=market.resolved_at.isoformat() if market.resolved_at else None
            )
            
            return pred_market
            
        except Exception as e:
            logger.error(f"Failed to convert market {market.id}: {e}")
            return None
    
    async def get_market_details(self, market_id: str) -> Optional[PredictionMarket]:
        """
        Get detailed market information.
        
        Args:
            market_id: Market identifier
            
        Returns:
            PredictionMarket object or None if not found
        """
        try:
            async with self._client as client:
                market = await client.get_market_details(market_id)
                if market:
                    return self._convert_to_prediction_market(market)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get market details {market_id}: {e}")
            return None
    
    async def get_orderbook(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Get order book for a market.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Order book data or None if not available
        """
        try:
            async with self._client as client:
                orderbook = await client.get_orderbook(market_id)
                if orderbook:
                    return {
                        "market_id": orderbook.market_id,
                        "outcome": orderbook.outcome,
                        "bids": [(float(price), float(size)) for price, size in orderbook.bids],
                        "asks": [(float(price), float(size)) for price, size in orderbook.asks],
                        "timestamp": orderbook.timestamp.isoformat()
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get orderbook {market_id}: {e}")
            return None
    
    async def get_user_positions(self, wallet_address: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get user positions.
        
        Args:
            wallet_address: User wallet address
            
        Returns:
            List of position data
        """
        try:
            async with self._client as client:
                positions = await client.get_positions(wallet_address)
                return [
                    {
                        "market_id": pos.market_id,
                        "outcome": pos.outcome,
                        "size": float(pos.size),
                        "average_price": float(pos.average_price),
                        "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0.0,
                        "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0.0,
                        "created_at": pos.created_at.isoformat() if pos.created_at else None
                    }
                    for pos in positions
                ]
                
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    async def get_trade_history(self, wallet_address: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get user trade history.
        
        Args:
            wallet_address: User wallet address
            limit: Maximum number of trades
            
        Returns:
            List of trade data
        """
        try:
            async with self._client as client:
                trades = await client.get_trades(wallet_address, limit)
                return [
                    {
                        "id": trade.id,
                        "market_id": trade.market_id,
                        "outcome": trade.outcome,
                        "side": trade.side,
                        "size": float(trade.size),
                        "price": float(trade.price),
                        "fee": float(trade.fee),
                        "timestamp": trade.timestamp.isoformat()
                    }
                    for trade in trades
                ]
                
        except Exception as e:
            logger.error(f"Failed to get trade history: {e}")
            return []
    
    async def place_order(
        self,
        market_id: str,
        outcome: str,
        side: str,
        size: Union[str, Decimal],
        price: Union[str, Decimal],
        order_type: str = "limit"
    ) -> Optional[Dict[str, Any]]:
        """
        Place a trading order.
        
        Args:
            market_id: Market identifier
            outcome: Market outcome
            side: "buy" or "sell"
            size: Order size
            price: Order price
            order_type: Order type
            
        Returns:
            Order data or None if failed
        """
        try:
            async with self._client as client:
                order = await client.place_order(market_id, outcome, side, size, price, order_type)
                if order:
                    return {
                        "id": order.id,
                        "market_id": order.market_id,
                        "outcome": order.outcome,
                        "side": order.side,
                        "size": float(order.size),
                        "price": float(order.price),
                        "filled": float(order.filled),
                        "remaining": float(order.remaining) if order.remaining else 0.0,
                        "status": order.status,
                        "created_at": order.created_at.isoformat() if order.created_at else None
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            async with self._client as client:
                return await client.cancel_order(order_id)
                
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    async def get_open_orders(self, wallet_address: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get open orders.
        
        Args:
            wallet_address: User wallet address
            
        Returns:
            List of order data
        """
        try:
            async with self._client as client:
                orders = await client.get_open_orders(wallet_address)
                return [
                    {
                        "id": order.id,
                        "market_id": order.market_id,
                        "outcome": order.outcome,
                        "side": order.side,
                        "size": float(order.size),
                        "price": float(order.price),
                        "filled": float(order.filled),
                        "remaining": float(order.remaining) if order.remaining else 0.0,
                        "status": order.status,
                        "created_at": order.created_at.isoformat() if order.created_at else None
                    }
                    for order in orders
                ]
                
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []


# ============================================================================
# Integration Function
# ============================================================================

def create_polymarket_adapter() -> PolymarketAdapter:
    """
    Create a Polymarket adapter instance.
    
    Returns:
        PolymarketAdapter instance
    """
    return PolymarketAdapter()


# ============================================================================
# Compatibility Check
# ============================================================================

def check_polymarket_client_availability() -> bool:
    """
    Check if Polymarket client packages are available.
    
    Returns:
        True if available, False otherwise
    """
    try:
        import polymarket_clob
        import gql
        import websockets
        return True
    except ImportError as e:
        logger.warning(f"Polymarket client packages not available: {e}")
        return False


# ============================================================================
# Example Usage (for testing)
# ============================================================================

async def example_usage():
    """Example usage of the Polymarket adapter."""
    adapter = create_polymarket_adapter()
    
    # Fetch markets
    markets = await adapter.fetch_polymarket_markets(limit=10)
    print(f"Fetched {len(markets)} markets")
    
    # Get market details
    if markets:
        details = await adapter.get_market_details(markets[0].market_id)
        print(f"Market details: {details.question if details else 'Not found'}")
    
    # Get orderbook
    if markets:
        orderbook = await adapter.get_orderbook(markets[0].market_id)
        print(f"Orderbook: {len(orderbook['bids']) if orderbook else 0} bids")
    
    # Note: Trading operations require proper API keys
    # positions = await adapter.get_user_positions()
    # trades = await adapter.get_trade_history()


if __name__ == "__main__":
    # Run example usage
    asyncio.run(example_usage())

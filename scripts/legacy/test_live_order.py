"""
Test live order to verify end-to-end system operation.
Places a small 1-contract order on an active Kalshi market.
"""
import asyncio
from decimal import Decimal
from merid.event_venues.kalshi.client import get_kalshi_client
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.base import VenueOrder
from utils.logger import get_logger

logger = get_logger("test_live_order")

async def main():
    logger.info("[TEST-ORDER] Starting live test order...")
    
    # Get Kalshi client
    client = get_kalshi_client()
    logger.info("[TEST-ORDER] Kalshi client initialized")
    
    # Get catalog and refresh it
    catalog = get_market_catalog()
    logger.info("[TEST-ORDER] Refreshing catalog...")
    await catalog.refresh()
    logger.info(f"[TEST-ORDER] Catalog refreshed, {len(catalog.snapshot().markets)} markets available")
    
    # Use known active ticker from WS logs
    ticker = "KXBTC15M-26MAY242045-45"
    logger.info(f"[TEST-ORDER] Using active ticker from WS logs: {ticker}")
    
    # Get current orderbook
    result = await client.get_orderbook(ticker)
    logger.info(f"[TEST-ORDER] get_orderbook returned type: {type(result)}")
    
    # Handle tuple return format - unwrap recursively
    orderbook = result
    while isinstance(orderbook, tuple):
        logger.info(f"[TEST-ORDER] Unwrapping tuple with {len(orderbook)} elements")
        orderbook = orderbook[0] if orderbook else None
    
    if orderbook and hasattr(orderbook, 'bids') and hasattr(orderbook, 'asks'):
        # VenueOrderBook has bids/asks as List[tuple[Decimal, Decimal]] (price, size)
        bid_price = orderbook.bids[0][0] if orderbook.bids else None
        ask_price = orderbook.asks[0][0] if orderbook.asks else None
        logger.info(f"[TEST-ORDER] Orderbook: bid={bid_price} ask={ask_price}")
    else:
        logger.error(f"[TEST-ORDER] Invalid orderbook format: {type(orderbook)}")
        return
    
    # Place a small YES order (1 contract) at valid price (50 cents = 0.50)
    # Kalshi requires price in cents (1-99 range)
    if orderbook.bids and orderbook.asks:
        price_cents = Decimal("0.50")  # 50 cents
        logger.info(f"[TEST-ORDER] Placing YES order for 1 contract at ${price_cents}")
        
        # Construct VenueOrder
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal("1"),
            price=price_cents,
            order_type="limit",
            client_order_id=f"test-{ticker}"
        )
        
        try:
            result = await client.place_order(order)
            logger.info(f"[TEST-ORDER] Order placed successfully: {result}")
        except Exception as e:
            logger.error(f"[TEST-ORDER] Order failed: {e}", exc_info=True)
    else:
        logger.error("[TEST-ORDER] No liquidity in orderbook")

if __name__ == "__main__":
    asyncio.run(main())

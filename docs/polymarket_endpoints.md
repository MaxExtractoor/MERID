# Polymarket Integration Endpoints Documentation

This document describes all Polymarket endpoints and operations exposed through the MERID PolymarketClient integration.

## Overview

The MERID Polymarket integration provides access to Polymarket's various APIs through a unified client interface. It combines:

- **Gamma API** for market discovery and data (public, no auth required)

- **CLOB API** for trading operations (requires API keys)

- **Data API** for user analytics and positions (requires authentication)

- **GraphQL** for complex queries (requires authentication)

- **WebSocket** for real-time streaming (requires authentication)

## Configuration

Environment variables required:

```bash

# CLOB Trading API (required for trading operations)

POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_SECRET=your_api_secret_here
POLYMARKET_WALLET_ADDRESS=your_wallet_address_here
POLYMARKET_PRIVATE_KEY=your_private_key_here  # Optional, for signing

```

## Endpoints by Category

### Market Discovery & Details

#### List Markets

- Method: `list_markets()`

- API: Gamma API

- URL: `https://gamma-api.polymarket.com/markets`

- Authentication: None (public)

Parameters:

- `active` (bool): Filter for active markets only

- `limit` (int): Maximum number of markets to return

- `category` (str): Filter by category

- `search` (str): Search term for market questions

Response: List of `Market` objects

#### Get Market Details

- Method: `get_market_details(market_id: str)`

- API: Gamma API

- URL: `https://gamma-api.polymarket.com/markets/{market_id}`

- Authentication: None (public)

Response: Single `Market` object

#### Get Order Book

- Method: `get_orderbook(market_id: str)`

- API: Gamma API

- URL: `https://gamma-api.polymarket.com/markets/{market_id}/orderbook`

- Authentication: None (public)

Response: `OrderBook` object with bids/asks

### User Data / Positions

#### Get User Positions

 - Method: `get_positions(wallet_address: Optional[str])`

 - API: GraphQL

 - URL: `https://polymarket.com/graphql`

 - Authentication: Required (wallet address)

Query:

```graphql

query GetPositions($address: String!) {
    user(address: $address) {
        positions {
            id
            market {
                id
                question
            }
            outcome
            size
            averagePrice
            unrealizedPnl
            realizedPnl
            createdAt
        }
    }
}

```

Response: List of `Position` objects

#### Get Trade History

- Method: `get_trades(wallet_address: Optional[str], limit: int)`

- API: Data API

- URL: `https://data.polymarket.com/trades`

- Authentication: Required (wallet address)

Parameters:

- `address` (str): User wallet address

- `limit` (int): Maximum number of trades

Response: List of `Trade` objects

#### Get Activity Feed

- Method: `get_activity(wallet_address: Optional[str])`

- API: Data API

- URL: `https://data.polymarket.com/activity`

- Authentication: Required (wallet address)

Parameters:

- `address` (str): User wallet address

Response: List of activity items

### Trading Operations (CLOB)

#### Place Order

- Method: `place_order(market_id, outcome, side, size, price, order_type)`

- API: CLOB API

- Authentication: Required (API key + secret)

Parameters:

- `market_id` (str): Market identifier

- `outcome` (str): Market outcome ("Yes" or "No")

- `side` (str): Order side ("buy" or "sell")

- `size` (Decimal): Order size

- `price` (Decimal): Order price

- `order_type` (str): Order type ("limit" or "market")

Response: `Order` object

#### Cancel Order

- Method: `cancel_order(order_id: str)`

- API: CLOB API

- Authentication: Required (API key + secret)

Parameters:

- `order_id` (str): Order identifier

Response: Boolean success status

#### Get Open Orders

- Method: `get_open_orders(wallet_address: Optional[str])`

- API: CLOB API

- Authentication: Required (API key + secret)

Parameters:

- `wallet_address` (str): User wallet address

Response: List of `Order` objects

### Analytics / Data API

#### Get Positions

- Endpoint: `GET /positions`

- API: Data API

- Authentication: Required

- Parameters:

  - `address` (str): Wallet address

- Response: Position data with PnL calculations

#### Get Trades

- Endpoint: `GET /trades`

- API: Data API

- Authentication: Required

- Parameters:

  - `address` (str): Wallet address

  - `limit` (int): Maximum trades

- Response: Trade history with timestamps and fees

#### Get Activity

- Endpoint: `GET /activity`

- API: Data API

- Authentication: Required

- Parameters:

  - `address` (str): Wallet address

- Response: User activity feed

#### Get Holders

- Endpoint: `GET /holders`

- API: Data API

- Authentication: Required

- Parameters:

  - `marketId` (str): Market identifier

- Response: List of market holders

#### Get Value

- Endpoint: `GET /value`

- API: Data API

- Authentication: Required

- Parameters:

  - `marketId` (str): Market identifier

- Response: Market valuation data

### WebSockets / Streaming

#### Connect to WebSocket

- URL: `wss://ws.polymarket.com`

- Authentication: Required

- Channels:

  - `markets`: Market price updates

  - `orderbook`: Order book updates

  - `trades`: Trade notifications

#### Subscribe to Market Updates

- Method: `subscribe_markets(market_ids: List[str])`

- Message:

```json

{
    "type": "subscribe",
    "channel": "markets",
    "market_ids": ["market1", "market2"]
}

```

#### Subscribe to Orderbook

- Method: `subscribe_orderbook(market_id: str)`

- Message:

```json

{
    "type": "subscribe",
    "channel": "orderbook",
    "market_id": "market1"
}

```

## Data Models

### Market

```python

@dataclass
class Market:
    id: str
    question: str
    description: str
    outcomes: List[MarketOutcome]
    end_date: Optional[datetime]
    active: bool
    volume: Optional[Decimal]
    liquidity: Optional[Decimal]
    category: Optional[str]
    tags: List[str]
    created_at: Optional[datetime]
    resolution: Optional[str]
    resolved_at: Optional[datetime]

```

### MarketOutcome

```python

@dataclass
class MarketOutcome:
    outcome: str
    price: Decimal
    probability: Decimal
    best_ask_price: Optional[Decimal]
    best_bid_price: Optional[Decimal]

```

### Order

```python

@dataclass
class Order:
    id: str
    market_id: str
    outcome: str
    side: str  # "buy" or "sell"
    size: Decimal
    price: Decimal
    filled: Decimal
    remaining: Optional[Decimal]
    status: str  # pending, filled, cancelled
    created_at: Optional[datetime]

```

### Position

```python

@dataclass
class Position:
    market_id: str
    outcome: str
    size: Decimal
    average_price: Decimal
    unrealized_pnl: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    created_at: Optional[datetime]

```

### Trade

```python

@dataclass
class Trade:
    id: str
    market_id: str
    outcome: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime

```

### OrderBook

```python

@dataclass
class OrderBook:
    market_id: str
    outcome: str
    bids: List[Tuple[Decimal, Decimal]]  # (price, size)
    asks: List[Tuple[Decimal, Decimal]]  # (price, size)
    timestamp: datetime

```

## SDK vs Direct HTTP/GraphQL

### SDK Operations (polymarket-clob)

- Trading operations: `place_order()`, `cancel_order()`, `get_open_orders()`

- Authentication: API key + secret

- Network: Polygon POS

- Usage: Official Python SDK for CLOB trading

### Direct HTTP/GraphQL Operations

- Market data: Gamma API (HTTP)

- User analytics: Data API (HTTP)

- Complex queries: GraphQL (HTTP POST)

- Real-time data: WebSocket

- Usage: `httpx` or `aiohttp` clients

## Error Handling

The client implements robust error handling:

1. Network errors: Automatic retry with exponential backoff

2. Authentication errors: Clear error messages with required credentials

3. Rate limiting: Automatic rate limiting for public endpoints

4. Data parsing errors: Graceful fallback with default values
5. WebSocket errors: Automatic reconnection attempts

## Rate Limits

- Gamma API: 100 requests/minute (public endpoints)

- CLOB API: 1000 requests/minute (authenticated)

- Data API: 100 requests/minute (authenticated)

- GraphQL: 1000 requests/minute (authenticated)

## Examples

### Basic Market Discovery

```python

from merid.polymarket_client import PolymarketClient

async def example_market_discovery():
    async with PolymarketClient() as client:

        # List active markets

        markets = await client.list_markets(active=True, limit=10)
        
        for market in markets:
            print(f"Market: {market.question}")
            print(f"Outcomes: {[o.outcome for o in market.outcomes]}")
            print(f"Volume: {market.volume}")

```

### Trading Operations

```python

from merid.polymarket_client import PolymarketClient
from decimal import Decimal

async def example_trading():
    async with PolymarketClient() as client:

        # Place a limit order

        order = await client.place_order(
            market_id="bitcoin-price-2024",
            outcome="Yes",
            side="buy",
            size=Decimal("1.0"),
            price=Decimal("0.65")
        )
        
        print(f"Order placed: {order.id}")
        
        # Cancel the order

        success = await client.cancel_order(order.id)
        print(f"Order cancelled: {success}")

```

### User Data

```python

from merid.polymarket_client import PolymarketClient

async def example_user_data():
    async with PolymarketClient() as client:

        # Get user positions

        positions = await client.get_positions()
        
        for position in positions:
            print(f"Position: {position.market_id}")
            print(f"Size: {position.size}")
            print(f"PnL: {position.unrealized_pnl}")

```

### Real-time Streaming

```python

from merid.polymarket_client import PolymarketClient, PolymarketWebSocket
import asyncio

async def example_streaming():
    client = PolymarketClient()
    ws = PolymarketWebSocket(client)
    
    async def handle_message(data):
        print(f"Received: {data}")
    
    await ws.connect()
    await ws.subscribe_markets(["bitcoin-price-2024"])
    
    # Listen for messages

    await ws.listen(handle_message)

```

## Integration with MERID

The PolymarketAdapter provides a bridge between the new client and the existing MERID prediction markets aggregator:

```python

from merid.monitoring.polymarket_adapter import create_polymarket_adapter

async def integrate_with_merid():
    adapter = create_polymarket_adapter()
    
    # Fetch markets compatible with existing aggregator

    markets = await adapter.fetch_polymarket_markets(limit=50)
    
    # Use with existing aggregator

    for market in markets:

        # Add to aggregator's internal state

        aggregator.add_market(market)

```

## Remaining Gaps

The following endpoints are documented but not yet implemented:

1. Advanced GraphQL queries: Complex nested queries for analytics

2. Historical data: Deep historical market data beyond basic trade history

3. Market creation: Creating new markets (requires elevated permissions)

4. Oracle operations: Oracle management and resolution data
5. Advanced analytics: Volume profiles, liquidity analysis

These can be added as needed by extending the client class with additional methods.

## Testing

Run the test suite to verify integration:

```bash

python -m pytest tests/test_polymarket_integration.py -v

```

The test suite covers:

- Client initialization and configuration

- Market discovery and details

- Trading operations (mocked)

- User data retrieval

- Error handling

- Integration with adapter

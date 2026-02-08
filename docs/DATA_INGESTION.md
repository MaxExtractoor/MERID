# MERID Data Ingestion

> **Primary Module**: `data/ingestion/data_ingestion.py`  
> **Test File**: `tests/test_sections_8_14.py`

---

## Overview

MERID's data ingestion framework provides pluggable data sources that feed into the existing Kafka/Flink backbone. All external data is normalized to canonical schemas before publishing—**LLMs never see raw vendor responses**.

### Key Principles

1. **LLMs never scrape directly** – Dedicated services handle API calls
2. **All data normalized** – Vendor-specific formats converted to MERID schemas
3. **Rate limiting built-in** – Per-source limits prevent API abuse
4. **Reuse existing topics** – New sources publish to established topic families

---

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌───────────┐
│ External API │────▶│   DataSource     │────▶│   Kafka     │────▶│ LLM Agent │
│  (Raw Data)  │     │  (Normalizes)    │     │  (Schema)   │     │           │
└──────────────┘     └──────────────────┘     └─────────────┘     └───────────┘
                            │
                            ▼
                     Canonical Schema
                     (events.py)
```

---

## Data Source Types

| Type | Description | Example Sources |
|------|-------------|-----------------|
| `MARKET_API` | Exchange price/orderbook data | CCXT, direct APIs |
| `SENTIMENT_API` | Social sentiment scores | StockGeist, LunarCrush |
| `NEWS_API` | Financial headlines | Benzinga, CryptoNews |
| `ONCHAIN_API` | Blockchain data | Glassnode, Nansen |
| `WEBSOCKET` | Real-time streams | Exchange WS feeds |
| `SCRAPER` | Web scraping (isolated) | Reddit, Twitter |

---

## Canonical Schemas & Topics

### Price Data

**Topic**: `prices.spot.*`, `prices.perps.*`, `prices.ohlcv.*`

```python
{
    "event_type": "price.tick",
    "event_id": "evt_abc123",
    "timestamp": 1738750800.0,
    "schema_version": "1.0.0",
    "source": "kraken",
    "symbol": "BTC/USD",
    "venue": "kraken",
    "asset_type": "spot",
    "bid": 50000.0,
    "ask": 50010.0,
    "last": 50005.0,
    "volume_24h": 15000.0
}
```

### Sentiment Data

**Topic**: `social.sentiment.*`

```python
{
    "event_type": "social.sentiment",
    "event_id": "evt_def456",
    "timestamp": 1738750800.0,
    "schema_version": "1.0.0",
    "source": "stockgeist",
    "symbol": "BTC",
    "sentiment_score": 0.65,
    "bullish_percent": 60.0,
    "bearish_percent": 25.0,
    "neutral_percent": 15.0,
    "mention_count": 5420,
    "engagement_score": 0.78
}
```

### News Data

**Topic**: `news.headlines.*`

```python
{
    "event_type": "news.headline",
    "event_id": "evt_ghi789",
    "timestamp": 1738750800.0,
    "schema_version": "1.0.0",
    "source": "benzinga",
    "news_id": "news_abc123",
    "headline": "Bitcoin Breaks $50K Resistance",
    "summary": "Bitcoin surged past $50,000...",
    "url": "https://...",
    "symbols": ["BTC"],
    "sentiment_score": 0.4,
    "published_at": 1738750700.0,
    "content_hash": "a1b2c3d4e5f6"
}
```

### On-Chain Data

**Topic**: `onchain.whale_tx.*`, `onchain.defi.*`

```python
{
    "event_type": "onchain.whale_tx",
    "event_id": "evt_jkl012",
    "timestamp": 1738750800.0,
    "schema_version": "1.0.0",
    "source": "glassnode",
    "tx_hash": "0xabc...",
    "chain": "ethereum",
    "from_address": "0x123...",
    "to_address": "0x456...",
    "from_label": "exchange",
    "to_label": "whale",
    "amount": 1000.0,
    "amount_usd": 3000000.0,
    "asset": "ETH",
    "tx_type": "exchange_withdrawal"
}
```

---

## Creating a Data Source

### 1. Extend Base Class

```python
from data.ingestion.data_ingestion import (
    DataSource,
    IngestionConfig,
    DataSourceType,
)

class MyNewSource(DataSource):
    """Custom data source."""
    
    async def connect(self) -> bool:
        # Initialize connection
        self.status = IngestionStatus.ACTIVE
        return True
    
    async def disconnect(self) -> None:
        # Cleanup
        pass
    
    async def fetch(self) -> List[Dict[str, Any]]:
        # Fetch and normalize data
        raw_data = await self._call_api()
        return [self._normalize(item) for item in raw_data]
    
    def _normalize(self, raw: Dict) -> Dict:
        # Convert to canonical schema
        return {
            "event_type": "social.sentiment",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "symbol": raw.get("ticker"),
            "sentiment_score": raw.get("score"),
            # ... other fields
        }
```

### 2. Configure Source

```python
config = IngestionConfig(
    source_id="my_sentiment",
    source_name="My Sentiment Provider",
    source_type=DataSourceType.SENTIMENT_API,
    output_topic="social.sentiment.my_provider",
    requests_per_minute=60,
    burst_size=10,
    max_retries=3,
)
```

### 3. Register with Manager

```python
from data.ingestion.data_ingestion import get_ingestion_manager

manager = get_ingestion_manager()
manager.register_source(MyNewSource(config))
await manager.start_all()
```

---

## Built-in Sources

### MockSentimentSource

For testing and development:

```python
from data.ingestion.data_ingestion import MockSentimentSource, IngestionConfig

config = IngestionConfig(
    source_id="mock_sentiment",
    source_name="Mock Sentiment",
    source_type=DataSourceType.SENTIMENT_API,
    output_topic="social.sentiment.mock",
)

source = MockSentimentSource(config)
await source.connect()
records = await source.fetch()
# Returns normalized sentiment for BTC, ETH, SOL
```

### MockNewsSource

```python
from data.ingestion.data_ingestion import MockNewsSource

source = MockNewsSource(config)
records = await source.fetch()
# Returns normalized news headlines with deduplication
```

### CCXTMarketSource

```python
from data.ingestion.data_ingestion import CCXTMarketSource

config = IngestionConfig(
    source_id="kraken_prices",
    source_name="Kraken",
    source_type=DataSourceType.MARKET_API,
    output_topic="prices.spot.kraken",
)

source = CCXTMarketSource(config, exchange_id="kraken")
await source.connect()
records = await source.fetch()
# Returns normalized price ticks
```

---

## Ingestion Manager

The `IngestionManager` coordinates all data sources:

```python
from data.ingestion.data_ingestion import get_ingestion_manager

manager = get_ingestion_manager()

# Set Kafka handler
manager.set_kafka_handler(kafka_producer.send)

# Register sources
manager.register_source(sentiment_source)
manager.register_source(news_source)
manager.register_source(price_source)

# Start all
await manager.start_all()

# Check status
status = manager.get_status()
print(f"Active sources: {status['source_count']}")

# Stop all
await manager.stop_all()
```

### Metrics

```python
metrics = manager.get_metrics()

# Output:
# {
#   "total_records_ingested": 15420,
#   "total_errors": 12,
#   "success_rate": 0.9992,
#   "active_sources": 5,
#   "errored_sources": 0,
# }
```

---

## Reuse Inventory Check

**Every new source must reuse existing topics.** The `check_reuse_inventory` function validates this:

```python
from data.ingestion.data_ingestion import check_reuse_inventory

config = IngestionConfig(
    source_id="new_source",
    source_name="New Provider",
    source_type=DataSourceType.SENTIMENT_API,
    output_topic="social.sentiment.new_provider",  # Uses existing family
)

result = check_reuse_inventory(config)

# Output:
# {
#   "output_topic": "social.sentiment.new_provider",
#   "reuses_existing_topic": True,  # ✓ Good
#   "design_suspect": False,
# }
```

If a source tries to create a new topic family, it's flagged:

```python
config = IngestionConfig(
    output_topic="custom.new.topic",  # New family!
)

result = check_reuse_inventory(config)
# {
#   "reuses_existing_topic": False,
#   "design_suspect": True,  # ⚠️ Requires review
#   "warning": "Source does not use existing topic schema - requires review"
# }
```

---

## Topic Families

All data must publish to one of these existing topic families:

| Family | Description |
|--------|-------------|
| `prices.*` | Market prices (spot, perps, fx, ohlcv) |
| `orderbook.*` | Order book data (l1, l2) |
| `trades.*` | Executed trades |
| `social.*` | Social/sentiment data |
| `news.*` | News headlines |
| `onchain.*` | Blockchain data (whale_tx, defi) |
| `agent.*` | Agent outputs (opinions, heartbeats) |
| `consensus.*` | Consensus decisions |
| `risk.*` | Risk alerts and metrics |

---

## Rate Limiting

Each source has built-in rate limiting:

```python
config = IngestionConfig(
    requests_per_minute=60,  # Max 60 requests/min
    burst_size=10,           # Allow burst of 10
    retry_delay_seconds=5.0, # Wait 5s on failure
)
```

The ingestion loop automatically respects these limits:

```python
# Inside DataSource.start()
await asyncio.sleep(60 / self.config.requests_per_minute)
```

---

## Error Handling

Sources track errors and can be monitored:

```python
source = manager._sources["my_source"]

print(f"Total records: {source.metrics.total_records}")
print(f"Failed records: {source.metrics.failed_records}")
print(f"Last error: {source.metrics.last_error}")
print(f"Errors (1h): {source.metrics.error_count_1h}")
```

---

*See also*: `docs/PROGRESS_CHECKPOINT_2026-02-05.md` for full module context.

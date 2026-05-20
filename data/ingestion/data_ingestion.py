"""
MERID Data Ingestion Framework - Section 10: Data Ingestion Across Markets, Assets, and Signals

Pluggable data ingestion that feeds into the existing Kafka/Flink backbone.
All external data normalized to MERID canonical schemas before publishing.

Data Sources:
- Market data (spot, perps, options, FX)
- Social/sentiment (Twitter, Reddit, Telegram, APIs)
- News (financial headlines)
- On-chain (whale transactions, DeFi flows)

Key Rules:
- LLMs NEVER scrape directly
- All data goes through normalized topics
- Scrapers are isolated services with rate limits
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("data.ingestion")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """T-031: Safe float conversion — handles None, 'N/A', '', NaN, Inf."""
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        logger.debug("safe_float: could not convert %r, using default %s", value, default)
        return default


class DataSourceType(str, Enum):
    """Types of data sources."""
    MARKET_API = "market_api"
    SENTIMENT_API = "sentiment_api"
    NEWS_API = "news_api"
    ONCHAIN_API = "onchain_api"
    WEBSOCKET = "websocket"
    SCRAPER = "scraper"


class IngestionStatus(str, Enum):
    """Status of an ingestion source."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    OFFLINE = "offline"


@dataclass
class IngestionConfig:
    """Configuration for a data source."""
    source_id: str
    source_name: str
    source_type: DataSourceType
    
    # Target topics
    output_topic: str
    
    # Rate limiting
    requests_per_minute: int = 60
    burst_size: int = 10
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    
    # SLA
    expected_latency_ms: float = 1000.0
    max_latency_ms: float = 5000.0
    
    # Enabled
    enabled: bool = True


@dataclass
class IngestionMetrics:
    """Metrics for an ingestion source."""
    source_id: str
    
    # Counters
    total_records: int = 0
    successful_records: int = 0
    failed_records: int = 0
    
    # Latency
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Rate
    records_per_minute: float = 0.0
    
    # Errors
    last_error: str = ""
    error_count_1h: int = 0
    
    # Timing
    last_success: float = 0.0
    last_failure: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "total_records": self.total_records,
            "success_rate": self.successful_records / max(1, self.total_records),
            "avg_latency_ms": self.avg_latency_ms,
            "records_per_minute": self.records_per_minute,
            "error_count_1h": self.error_count_1h,
        }


class DataSource(ABC):
    """Abstract base class for data sources."""
    
    def __init__(self, config: IngestionConfig):
        self.config = config
        self.status = IngestionStatus.OFFLINE
        self.metrics = IngestionMetrics(source_id=config.source_id)
        self._event_handlers: List[Callable] = []
        self._running = False
    
    def subscribe(self, handler: Callable) -> None:
        """Subscribe to ingested data."""
        self._event_handlers.append(handler)
    
    async def _emit(self, data: Dict[str, Any]) -> None:
        """Emit normalized data to subscribers."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(self.config.output_topic, data)
                else:
                    handler(self.config.output_topic, data)
            except Exception as e:
                logger.error(f"Handler error for {self.config.source_id}: {e}")
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the data source."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the data source."""
        pass
    
    @abstractmethod
    async def fetch(self) -> List[Dict[str, Any]]:
        """Fetch data from the source."""
        pass
    
    async def start(self) -> None:
        """Start the ingestion loop."""
        self._running = True
        self.status = IngestionStatus.ACTIVE
        logger.info(f"Starting ingestion: {self.config.source_name}")
        
        while self._running:
            try:
                start_time = time.time()
                records = await self.fetch()
                latency = (time.time() - start_time) * 1000
                
                for record in records:
                    await self._emit(record)
                    self.metrics.total_records += 1
                    self.metrics.successful_records += 1
                
                self.metrics.last_success = time.time()
                self._update_latency(latency)
                
                # Rate limiting delay
                await asyncio.sleep(60 / self.config.requests_per_minute)
                
            except Exception as e:
                self.metrics.failed_records += 1
                self.metrics.last_error = str(e)
                self.metrics.last_failure = time.time()
                self.metrics.error_count_1h += 1
                
                logger.error(f"Ingestion error for {self.config.source_id}: {e}")
                await asyncio.sleep(self.config.retry_delay_seconds)
    
    async def stop(self) -> None:
        """Stop the ingestion loop."""
        self._running = False
        self.status = IngestionStatus.PAUSED
        await self.disconnect()
    
    def _update_latency(self, latency_ms: float) -> None:
        """Update latency metrics."""
        # Simple moving average
        alpha = 0.1
        self.metrics.avg_latency_ms = (
            alpha * latency_ms + (1 - alpha) * self.metrics.avg_latency_ms
        )


# ============================================
# MARKET DATA SOURCES
# ============================================

class MarketDataSource(DataSource):
    """Base class for market data sources."""
    
    async def normalize_price(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize raw price data to MERID schema."""
        return {
            "event_type": "price.tick",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "symbol": raw.get("symbol", ""),
            "venue": raw.get("venue", self.config.source_name),
            "asset_type": raw.get("asset_type", "spot"),
            "bid": _safe_float(raw.get("bid", 0)),
            "ask": _safe_float(raw.get("ask", 0)),
            "last": _safe_float(raw.get("last", raw.get("price", 0))),
            "volume_24h": _safe_float(raw.get("volume", 0)),
        }


class CCXTMarketSource(MarketDataSource):
    """Market data from CCXT exchanges."""
    
    def __init__(self, config: IngestionConfig, exchange_id: str):
        super().__init__(config)
        self.exchange_id = exchange_id
        self._exchange = None
        self._symbols: List[str] = []
    
    async def connect(self) -> bool:
        try:
            import ccxt.async_support as ccxt
            exchange_class = getattr(ccxt, self.exchange_id)
            self._exchange = exchange_class({"enableRateLimit": True})
            await self._exchange.load_markets()
            self._symbols = list(self._exchange.markets.keys())[:50]  # Limit symbols
            self.status = IngestionStatus.ACTIVE
            return True
        except Exception as e:
            logger.error(f"CCXT connect error: {e}")
            self.status = IngestionStatus.ERROR
            return False
    
    async def disconnect(self) -> None:
        if self._exchange:
            await self._exchange.close()
    
    async def fetch(self) -> List[Dict[str, Any]]:
        if not self._exchange:
            return []
        
        records = []
        for symbol in self._symbols[:10]:  # Batch fetch
            try:
                ticker = await self._exchange.fetch_ticker(symbol)
                normalized = await self.normalize_price({
                    "symbol": symbol,
                    "venue": self.exchange_id,
                    "bid": ticker.get("bid"),
                    "ask": ticker.get("ask"),
                    "last": ticker.get("last"),
                    "volume": ticker.get("baseVolume"),
                })
                records.append(normalized)
            except Exception as e:
                logger.debug(f"Ticker fetch error for {symbol}: {e}")
        
        return records


# ============================================
# SENTIMENT DATA SOURCES
# ============================================

class SentimentSource(DataSource):
    """Base class for sentiment data sources."""
    
    async def normalize_sentiment(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize raw sentiment data to MERID schema."""
        return {
            "event_type": "social.sentiment",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "symbol": raw.get("symbol", ""),
            "sentiment_score": float(raw.get("sentiment", raw.get("score", 0))),
            "bullish_percent": float(raw.get("bullish", 0)),
            "bearish_percent": float(raw.get("bearish", 0)),
            "neutral_percent": float(raw.get("neutral", 0)),
            "mention_count": int(raw.get("mentions", raw.get("count", 0))),
            "engagement_score": float(raw.get("engagement", 0)),
        }


class MockSentimentSource(SentimentSource):
    """Mock sentiment source for testing."""
    
    def __init__(self, config: IngestionConfig):
        super().__init__(config)
        from merid.constants import CRYPTO_15M_ASSETS
        self._symbols = list(CRYPTO_15M_ASSETS)
    
    async def connect(self) -> bool:
        self.status = IngestionStatus.ACTIVE
        return True
    
    async def disconnect(self) -> None:
        pass
    
    async def fetch(self) -> List[Dict[str, Any]]:
        import random
        records = []
        
        for symbol in self._symbols:
            sentiment = random.uniform(-1, 1)
            normalized = await self.normalize_sentiment({
                "symbol": symbol,
                "sentiment": sentiment,
                "bullish": max(0, sentiment) * 50 + 25,
                "bearish": max(0, -sentiment) * 50 + 25,
                "neutral": 50 - abs(sentiment) * 25,
                "mentions": random.randint(100, 10000),
            })
            records.append(normalized)
        
        return records


# ============================================
# NEWS DATA SOURCES
# ============================================

class NewsSource(DataSource):
    """Base class for news data sources."""
    
    def __init__(self, config: IngestionConfig):
        super().__init__(config)
        self._seen_hashes: set = set()
        self._dedup_lock = threading.Lock()  # ZT2-16: Init lock in __init__, not lazily
    
    async def normalize_news(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize raw news data to MERID schema."""
        headline = raw.get("headline", raw.get("title", ""))
        content_hash = hashlib.sha256(headline.encode()).hexdigest()[:16]
        
        return {
            "event_type": "news.headline",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "news_id": f"news_{content_hash}",
            "headline": headline,
            "summary": raw.get("summary", raw.get("description", ""))[:500],
            "url": raw.get("url", ""),
            "symbols": raw.get("symbols", raw.get("tickers", [])),
            "sentiment_score": _safe_float(raw.get("sentiment", 0)),
            "published_at": raw.get("published_at", time.time()),
            "content_hash": content_hash,
        }
    
    def _is_duplicate(self, content_hash: str) -> bool:
        """Check if we've already seen this content (T-044: thread-safe)."""
        with self._dedup_lock:
            if content_hash in self._seen_hashes:
                return True
            self._seen_hashes.add(content_hash)
            # Limit memory
            if len(self._seen_hashes) > 10000:
                self._seen_hashes = set(list(self._seen_hashes)[-5000:])
            return False


class MockNewsSource(NewsSource):
    """Mock news source for testing."""
    
    async def connect(self) -> bool:
        self.status = IngestionStatus.ACTIVE
        return True
    
    async def disconnect(self) -> None:
        pass
    
    async def fetch(self) -> List[Dict[str, Any]]:
        import random
        
        headlines = [
            ("Bitcoin breaks through resistance level", ["BTC"], 0.3),
            ("Ethereum 2.0 upgrade progress update", ["ETH"], 0.2),
            ("Market volatility increases amid uncertainty", ["BTC", "ETH"], -0.1),
            ("New DeFi protocol launches with strong TVL", ["ETH"], 0.4),
        ]
        
        # Return one random headline
        headline, symbols, sentiment = random.choice(headlines)
        normalized = await self.normalize_news({
            "headline": f"{headline} - {int(time.time())}",
            "symbols": symbols,
            "sentiment": sentiment,
        })
        
        if self._is_duplicate(normalized["content_hash"]):
            return []
        
        return [normalized]


# ============================================
# ON-CHAIN DATA SOURCES
# ============================================

class OnChainSource(DataSource):
    """Base class for on-chain data sources."""
    
    async def normalize_whale_tx(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize whale transaction data."""
        return {
            "event_type": "onchain.whale_tx",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "tx_hash": raw.get("hash", ""),
            "chain": raw.get("chain", "ethereum"),
            "from_address": raw.get("from", "")[:20] + "...",  # Truncate for privacy
            "to_address": raw.get("to", "")[:20] + "...",
            "from_label": raw.get("from_label", "unknown"),
            "to_label": raw.get("to_label", "unknown"),
            "amount": float(raw.get("amount", 0)),
            "amount_usd": float(raw.get("amount_usd", 0)),
            "asset": raw.get("asset", raw.get("token", "")),
            "tx_type": raw.get("type", "transfer"),
        }
    
    async def normalize_defi_flow(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize DeFi flow data."""
        return {
            "event_type": "onchain.defi_flow",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "schema_version": "1.0.0",
            "source": self.config.source_name,
            "protocol": raw.get("protocol", ""),
            "chain": raw.get("chain", "ethereum"),
            "tvl_usd": float(raw.get("tvl", 0)),
            "tvl_change_24h": float(raw.get("tvl_change", 0)),
            "inflow_usd": float(raw.get("inflow", 0)),
            "outflow_usd": float(raw.get("outflow", 0)),
            "net_flow_usd": float(raw.get("inflow", 0)) - float(raw.get("outflow", 0)),
        }


# ============================================
# INGESTION MANAGER
# ============================================

class IngestionManager:
    """Manages all data ingestion sources."""
    
    _instance: Optional["IngestionManager"] = None
    
    def __init__(self):
        self._sources: Dict[str, DataSource] = {}
        self._configs: Dict[str, IngestionConfig] = {}
        self._kafka_handler: Optional[Callable] = None
        self._running = False
        
        logger.info("IngestionManager initialized")
    
    @classmethod
    def get_instance(cls) -> "IngestionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_kafka_handler(self, handler: Callable) -> None:
        """Set the handler for publishing to Kafka."""
        self._kafka_handler = handler
        
        # Subscribe all sources
        for source in self._sources.values():
            source.subscribe(handler)
    
    def register_source(self, source: DataSource) -> None:
        """Register a data source."""
        self._sources[source.config.source_id] = source
        self._configs[source.config.source_id] = source.config
        
        if self._kafka_handler:
            source.subscribe(self._kafka_handler)
        
        logger.info(f"Registered source: {source.config.source_name}")
    
    def remove_source(self, source_id: str) -> None:
        """Remove a data source."""
        if source_id in self._sources:
            del self._sources[source_id]
            del self._configs[source_id]
    
    async def start_all(self) -> None:
        """Start all enabled sources."""
        self._running = True
        tasks = []
        
        for source in self._sources.values():
            if source.config.enabled:
                tasks.append(asyncio.create_task(source.start()))
        
        logger.info(f"Started {len(tasks)} ingestion sources")
    
    async def stop_all(self) -> None:
        """Stop all sources."""
        self._running = False
        
        for source in self._sources.values():
            await source.stop()
        
        logger.info("All ingestion sources stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all sources."""
        return {
            "running": self._running,
            "source_count": len(self._sources),
            "sources": {
                source_id: {
                    "name": source.config.source_name,
                    "status": source.status.value,
                    "metrics": source.metrics.to_dict(),
                }
                for source_id, source in self._sources.items()
            }
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregate metrics."""
        total_records = sum(s.metrics.total_records for s in self._sources.values())
        total_errors = sum(s.metrics.failed_records for s in self._sources.values())
        
        return {
            "total_records_ingested": total_records,
            "total_errors": total_errors,
            "success_rate": (total_records - total_errors) / max(1, total_records),
            "active_sources": sum(1 for s in self._sources.values() if s.status == IngestionStatus.ACTIVE),
            "errored_sources": sum(1 for s in self._sources.values() if s.status == IngestionStatus.ERROR),
        }


def get_ingestion_manager() -> IngestionManager:
    """Get the global ingestion manager."""
    return IngestionManager.get_instance()


# ============================================
# REUSE INVENTORY CHECK
# ============================================

def check_reuse_inventory(source_config: IngestionConfig) -> Dict[str, Any]:
    """
    Check what existing MERID components a new source reuses.
    
    Per checklist: Every new source must declare what it reuses.
    """
    reuses = {
        "output_topic": source_config.output_topic,
        "reuses_existing_topic": source_config.output_topic.split(".")[0] in [
            "prices", "orderbook", "trades", "social", "news", "onchain"
        ],
        "reuses_flink_job": False,  # Check if topic has existing Flink consumer
        "reuses_adapter": False,
        "design_suspect": False,
    }
    
    # Flag if not reusing anything
    if not reuses["reuses_existing_topic"]:
        reuses["design_suspect"] = True
        reuses["warning"] = "Source does not use existing topic schema - requires review"
    
    return reuses

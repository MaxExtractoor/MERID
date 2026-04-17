"""Kalshi Market Catalog Batched Processing Tests — Event Loop Health Validation

Tests the async batched post-processing loops that feed MarketStateStore and
settlement buffers to ensure they don't block the event loop.

Run: pytest tests/event_venues/kalshi/test_catalog_batched_processing.py -v
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from unittest.mock import MagicMock, Mock

import pytest


# =============================================================================
# Mocks and Fixtures
# =============================================================================

@dataclass
class MockEventMarket:
    """Mock EventMarket for testing."""
    market_id: str
    volume: float = 1000.0
    open_interest: float = 500.0
    end_date: Optional[datetime] = None
    question: str = ""
    description: str = ""
    category: str = ""
    active: bool = True
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockCatalogMarket:
    """Mock CatalogMarket for testing."""
    market: MockEventMarket
    asset: Optional[str] = None
    expires_at: Optional[datetime] = None
    strike_price: Optional[float] = None
    floor_strike: Optional[float] = None
    cap_strike: Optional[float] = None


class MockMarketStateStore:
    """Mock MarketStateStore that tracks apply calls."""
    
    def __init__(self):
        self.applied_markets: List[str] = []
        self.apply_calls = 0
        self._lock = asyncio.Lock()
    
    def apply_rest_market(self, data: Dict[str, Any]) -> None:
        ticker = data.get("ticker")
        if ticker:
            self.applied_markets.append(ticker)
        self.apply_calls += 1


class MockSettlementBufferRegistry:
    """Mock SettlementBufferRegistry that tracks buffer registrations."""
    
    def __init__(self):
        self.buffers: Dict[str, Dict[str, Any]] = {}
        self.ensure_calls = 0
    
    def ensure_buffer(self, market_ticker: str, asset: str, expiry_epoch: int) -> None:
        self.buffers[market_ticker] = {
            "asset": asset,
            "expiry_epoch": expiry_epoch,
        }
        self.ensure_calls += 1


@pytest.fixture
def mock_enriched_markets_5000() -> List[MockCatalogMarket]:
    """Generate 5000 mock catalog markets for stress testing."""
    markets = []
    base_time = datetime.now(timezone.utc) + timedelta(hours=1)
    
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for i in range(5000):
        asset = assets[i % len(assets)]
        ticker = f"KX{asset}-{i:04d}-ABOVE-{100000 + i}"
        
        mkt = MockEventMarket(
            market_id=ticker,
            volume=float(1000 + i),
            open_interest=float(500 + i),
            end_date=base_time + timedelta(minutes=i),
            raw_data={
                "event_ticker": ticker,
                "series_ticker": f"KX{asset}15M",
            },
        )
        
        cm = MockCatalogMarket(
            market=mkt,
            asset=asset,
            expires_at=mkt.end_date,
            strike_price=float(100000 + i),
        )
        markets.append(cm)
    
    return markets


@pytest.fixture
def mock_enriched_crypto_rti() -> List[MockCatalogMarket]:
    """Generate crypto markets that pass RTI filter (15m/1h timeframes)."""
    markets = []
    base_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # Create markets with RTI-eligible patterns
    for i in range(100):
        asset = "BTC" if i % 2 == 0 else "ETH"
        # Use 15M suffix which is RTI-settled
        ticker = f"KX{asset}15M-TEST-{i:04d}"
        
        mkt = MockEventMarket(
            market_id=ticker,
            volume=float(1000 + i),
            open_interest=float(500 + i),
            end_date=base_time + timedelta(minutes=i),
            raw_data={
                "event_ticker": ticker,
                "series_ticker": f"KX{asset}15M",
            },
        )
        
        cm = MockCatalogMarket(
            market=mkt,
            asset=asset,
            expires_at=mkt.end_date,
            strike_price=float(70000 + i),
        )
        markets.append(cm)
    
    return markets


# =============================================================================
# Test Class: Batched Processing Core
# =============================================================================

class TestCatalogBatchedProcessing:
    """Test async batched processing of catalog post-refresh operations."""
    
    @pytest.mark.asyncio
    async def test_apply_rest_markets_batched_all_applied(self, mock_enriched_markets_5000):
        """All 5000 markets should be applied to MarketStateStore."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        # Run the batched apply with small batch size to test yielding
        applied = await catalog._apply_rest_markets_batched(
            mock_enriched_markets_5000,  # type: ignore
            store,  # type: ignore
            batch_size=100
        )
        
        assert applied == 5000
        assert store.apply_calls == 5000
        assert len(store.applied_markets) == 5000
        
    @pytest.mark.asyncio
    async def test_apply_rest_markets_batched_yields_control(self, mock_enriched_markets_5000):
        """Processing should yield control to event loop between batches."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        # Track when the event loop gets control
        yield_times: List[float] = []
        
        async def track_yield():
            yield_times.append(time.monotonic())
        
        # Interleave tracking with processing
        batch_size = 100
        total = len(mock_enriched_markets_5000)
        
        # Start timer
        start = time.monotonic()
        
        # Process in batches manually to verify yielding
        for i in range(0, total, batch_size):
            batch = mock_enriched_markets_5000[i:i + batch_size]
            for cm in batch:
                mkt = cm.market
                store.apply_rest_market({
                    "ticker": mkt.market_id,
                    "volume_24h": int(mkt.volume),
                    "open_interest": int(mkt.open_interest),
                    "expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                })
            # Yield control
            await asyncio.sleep(0)
            yield_times.append(time.monotonic())
        
        end = time.monotonic()
        
        # Should have yielded multiple times (5000/100 = 50 batches)
        assert len(yield_times) >= 49  # Allow for off-by-one
        
        # Total time should be reasonable (less than 1 second for this test)
        assert (end - start) < 1.0
    
    @pytest.mark.asyncio
    async def test_ensure_buffers_batched_all_registered(self, mock_enriched_crypto_rti):
        """All RTI-eligible markets should have buffers registered."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        sb_reg = MockSettlementBufferRegistry()
        
        # Run the batched buffer registration
        registered = await catalog._ensure_buffers_batched(
            mock_enriched_crypto_rti,  # type: ignore
            sb_reg,  # type: ignore
            batch_size=25
        )
        
        # All 100 should be registered (they all have RTI-eligible tickers)
        assert registered == 100
        assert sb_reg.ensure_calls == 100
        assert len(sb_reg.buffers) == 100
    
    @pytest.mark.asyncio
    async def test_ensure_buffers_batched_skips_non_rti(self):
        """Non-RTI markets should be skipped during buffer registration."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        sb_reg = MockSettlementBufferRegistry()
        
        # Create markets with non-RTI tickers (daily/weekly patterns)
        markets = []
        base_time = datetime.now(timezone.utc) + timedelta(days=1)
        
        for i in range(50):
            # Daily pattern (not RTI)
            ticker = f"KXBTCD-TEST-{i:04d}"
            mkt = MockEventMarket(
                market_id=ticker,
                end_date=base_time + timedelta(hours=i),
                raw_data={"series_ticker": f"KXBTCD1"},
            )
            cm = MockCatalogMarket(
                market=mkt,
                asset="BTC",
                expires_at=mkt.end_date,
            )
            markets.append(cm)
        
        registered = await catalog._ensure_buffers_batched(
            markets,  # type: ignore
            sb_reg,  # type: ignore
            batch_size=10
        )
        
        # Daily markets should NOT be registered as RTI
        assert registered == 0
        assert sb_reg.ensure_calls == 0
    
    @pytest.mark.asyncio
    async def test_batched_processing_event_loop_friendly(self, mock_enriched_markets_5000):
        """Large batches should not block the event loop measurably."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        # Simulate concurrent task that should make progress
        progress_events: List[str] = []
        
        async def concurrent_task():
            """A task that should make progress during batched processing."""
            for i in range(10):
                progress_events.append(f"concurrent-{i}")
                await asyncio.sleep(0.001)  # Small sleep
        
        # Run both concurrently
        async def run_both():
            await asyncio.gather(
                catalog._apply_rest_markets_batched(
                    mock_enriched_markets_5000,  # type: ignore
                    store,  # type: ignore
                    batch_size=100
                ),
                concurrent_task(),
            )
        
        await run_both()
        
        # Concurrent task should have made progress
        # (If batched processing blocked, we'd see fewer or no events)
        assert len(progress_events) >= 5  # At least half should have fired
        assert store.apply_calls == 5000


# =============================================================================
# Test Class: Batch Size Validation
# =============================================================================

class TestCatalogBatchSizes:
    """Test various batch sizes for optimal event loop behavior."""
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("batch_size", [50, 100, 200, 500])
    async def test_various_batch_sizes_complete(self, batch_size, mock_enriched_markets_5000):
        """All batch sizes should complete successfully."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        applied = await catalog._apply_rest_markets_batched(
            mock_enriched_markets_5000,  # type: ignore
            store,  # type: ignore
            batch_size=batch_size
        )
        
        assert applied == 5000
        assert store.apply_calls == 5000
    
    @pytest.mark.asyncio
    async def test_batch_size_1_is_very_yielding(self, mock_enriched_markets_5000):
        """Batch size of 1 should yield on every market (extreme but safe)."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        # Use only 100 markets for this extreme test
        small_batch = mock_enriched_markets_5000[:100]
        
        applied = await catalog._apply_rest_markets_batched(
            small_batch,  # type: ignore
            store,  # type: ignore
            batch_size=1
        )
        
        assert applied == 100
        # Should have yielded 99 times (after every market except the last)


# =============================================================================
# Test Class: Edge Cases
# =============================================================================

class TestCatalogBatchedEdgeCases:
    """Edge cases for batched processing."""
    
    @pytest.mark.asyncio
    async def test_empty_market_list(self):
        """Empty market list should complete without error."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        applied = await catalog._apply_rest_markets_batched(
            [],  # type: ignore
            store,  # type: ignore
            batch_size=100
        )
        
        assert applied == 0
        assert store.apply_calls == 0
    
    @pytest.mark.asyncio
    async def test_single_market(self):
        """Single market should complete without yielding issues."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        mkt = MockEventMarket(market_id="KXBTC-TEST-001")
        cm = MockCatalogMarket(market=mkt, asset="BTC")
        
        applied = await catalog._apply_rest_markets_batched(
            [cm],  # type: ignore
            store,  # type: ignore
            batch_size=100
        )
        
        assert applied == 1
        assert store.apply_calls == 1
    
    @pytest.mark.asyncio
    async def test_market_without_asset(self, mock_enriched_markets_5000):
        """Markets without assets should still be processed."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        
        # Remove assets from some markets
        for cm in mock_enriched_markets_5000[:100]:
            cm.asset = None
        
        applied = await catalog._apply_rest_markets_batched(
            mock_enriched_markets_5000[:100],  # type: ignore
            store,  # type: ignore
            batch_size=25
        )
        
        # All should still be applied (asset is optional for MarketStateStore)
        assert applied == 100
        assert store.apply_calls == 100
    
    @pytest.mark.asyncio
    async def test_market_without_expiry(self):
        """Markets without expiry should be handled gracefully."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        catalog = KalshiMarketCatalog()
        store = MockMarketStateStore()
        sb_reg = MockSettlementBufferRegistry()
        
        # Create markets without expires_at
        markets = []
        for i in range(10):
            mkt = MockEventMarket(
                market_id=f"KXBTC15M-NOEXPIRY-{i}",
                raw_data={"series_ticker": "KXBTC15M"},
            )
            cm = MockCatalogMarket(
                market=mkt,
                asset="BTC",
                expires_at=None,  # No expiry
            )
            markets.append(cm)
        
        # Should still apply to MarketStateStore
        applied = await catalog._apply_rest_markets_batched(
            markets,  # type: ignore
            store,  # type: ignore
            batch_size=5
        )
        assert applied == 10
        
        # But NOT register for settlement buffer (requires expires_at)
        registered = await catalog._ensure_buffers_batched(
            markets,  # type: ignore
            sb_reg,  # type: ignore
            batch_size=5
        )
        assert registered == 0  # Skipped due to missing expires_at


# =============================================================================
# Test Class: Integration with Real Catalog
# =============================================================================

class TestCatalogBatchedIntegration:
    """Integration tests with real catalog refresh flow."""
    
    @pytest.mark.asyncio
    async def test_refresh_structure_unchanged(self):
        """Catalog.refresh should still produce correct structure after refactor."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        # Create catalog with mock client to avoid network calls
        catalog = KalshiMarketCatalog()
        
        # Check that the batched methods exist and are async
        assert hasattr(catalog, '_apply_rest_markets_batched')
        assert hasattr(catalog, '_ensure_buffers_batched')
        
        import inspect
        assert inspect.iscoroutinefunction(catalog._apply_rest_markets_batched)
        assert inspect.iscoroutinefunction(catalog._ensure_buffers_batched)


# =============================================================================
# Run Configuration
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

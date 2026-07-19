"""Test concurrent fill ingestion with PostgreSQL.

This test verifies that PostgreSQL handles concurrent fill ingestion
without database lock errors, which was the root cause of position tracking desync.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger


@pytest.fixture
async def ledger(monkeypatch, tmp_path) -> AsyncGenerator[KalshiFillsLedger, None]:
    """Provide an isolated fills ledger that never writes to production DBs."""
    # TEST-ISOLATION FIX (2026-07-19): Redirect DB writes away from production.
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "test_fills.db"))
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None
    
    l = KalshiFillsLedger()
    l._fills = {}
    l._intents = {}
    l._fills_by_order = {}
    l._fills_by_market = {}
    
    yield l
    
    await l.shutdown()
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None


@pytest.mark.asyncio
async def test_concurrent_fill_ingestion(ledger: KalshiFillsLedger):
    """Test that concurrent fill ingestion works without lock errors."""
    
    # Create 100 fills to ingest concurrently
    fills = []
    for i in range(100):
        fill = {
            "fill_id": f"concurrent-fill-{i}",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy" if i % 2 == 0 else "sell",
            "count": 10,
            "price": 50 + i,
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fills.append(fill)
    
    # Ingest all fills concurrently
    tasks = [ledger.ingest_ws_fill(fill) for fill in fills]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check that all succeeded
    success_count = sum(1 for r in results if r is True)
    duplicate_count = sum(1 for r in results if r is False)
    error_count = sum(1 for r in results if isinstance(r, Exception))
    
    print(f"Concurrent ingestion results: {success_count} success, {duplicate_count} duplicates, {error_count} errors")
    
    # All should succeed (no duplicates in this test)
    assert success_count == 100, f"Expected 100 successful ingestions, got {success_count}"
    assert duplicate_count == 0, f"Expected 0 duplicates, got {duplicate_count}"
    assert error_count == 0, f"Expected 0 errors, got {error_count}"
    
    # Verify all fills are in the ledger
    assert ledger.summary()["fills_total"] == 100


@pytest.mark.asyncio
async def test_concurrent_duplicate_fills(ledger: KalshiFillsLedger):
    """Test that concurrent duplicate fills are handled correctly."""
    
    # Create the same fill 50 times
    fill = {
        "fill_id": "duplicate-test-fill",
        "market_ticker": "KXBTC-15M",
        "side": "yes",
        "action": "buy",
        "count": 10,
        "price": 50,
        "created_time": datetime.now(timezone.utc).isoformat(),
    }
    
    # Ingest the same fill 50 times concurrently
    tasks = [ledger.ingest_ws_fill(fill) for _ in range(50)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Check results
    success_count = sum(1 for r in results if r is True)
    duplicate_count = sum(1 for r in results if r is False)
    error_count = sum(1 for r in results if isinstance(r, Exception))
    
    print(f"Concurrent duplicate results: {success_count} success, {duplicate_count} duplicates, {error_count} errors")
    
    # First should succeed, rest should be duplicates
    assert success_count == 1, f"Expected 1 successful ingestion, got {success_count}"
    assert duplicate_count == 49, f"Expected 49 duplicates, got {duplicate_count}"
    assert error_count == 0, f"Expected 0 errors, got {error_count}"
    
    # Verify only one fill is in the ledger
    assert ledger.summary()["fills_total"] == 1


@pytest.mark.asyncio
async def test_position_reconciliation_after_concurrent_fills(ledger: KalshiFillsLedger):
    """Test that position reconciliation works correctly after concurrent fills."""
    
    # Create fills that result in a net position
    now = datetime.now(timezone.utc)
    fills = [
        {"fill_id": "pos-1", "market_ticker": "KXBTC-15M", "side": "yes", "action": "buy", "count": 100, "price": 50, "created_time": now},
        {"fill_id": "pos-2", "market_ticker": "KXBTC-15M", "side": "yes", "action": "buy", "count": 50, "price": 51, "created_time": now},
        {"fill_id": "pos-3", "market_ticker": "KXBTC-15M", "side": "yes", "action": "sell", "count": 30, "price": 52, "created_time": now},
    ]
    
    # Ingest concurrently
    tasks = [ledger.ingest_ws_fill(fill) for fill in fills]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # All should succeed
    assert all(r is True for r in results)
    
    # Verify fills are in the ledger
    assert ledger.summary()["fills_total"] == 3
    
    # Verify fills are indexed by market
    assert "KXBTC-15M" in ledger._fills_by_market
    assert len(ledger._fills_by_market["KXBTC-15M"]) == 3
    
    # Compute position for the specific market (bypasses time filtering)
    position = ledger.compute_position_from_fills("KXBTC-15M")
    
    # Should have net 120 yes contracts (100 + 50 - 30)
    assert position is not None
    assert position["contracts"] == 120
    assert position["side"] == "yes"

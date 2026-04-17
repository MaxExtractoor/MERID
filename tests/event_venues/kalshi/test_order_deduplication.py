"""Tests for order deduplication / idempotency cache (Story 1.2)."""
from datetime import datetime, timedelta, timezone

import pytest

from merid.event_venues.kalshi.order_deduplication import (
    OrderDeduplicationCache,
    get_order_cache,
)


def test_first_order_creates_new_entry():
    cache = OrderDeduplicationCache()
    coid, is_dup = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    assert is_dup is False
    assert coid != ""


def test_identical_order_returns_same_coid():
    cache = OrderDeduplicationCache()
    coid1, _ = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    coid2, is_dup = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    assert coid1 == coid2
    assert is_dup is True


def test_different_count_is_not_duplicate():
    cache = OrderDeduplicationCache()
    coid1, _ = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    coid2, is_dup = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 20)
    assert coid1 != coid2
    assert is_dup is False


def test_different_ticker_is_not_duplicate():
    cache = OrderDeduplicationCache()
    coid1, _ = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    coid2, is_dup = cache.get_or_create("KXETH-T2000", "buy", "yes", 55, 10)
    assert coid1 != coid2
    assert is_dup is False


def test_confirmed_order_not_deduplicated():
    """Once an order is confirmed (has order_id) it should not block fresh orders."""
    cache = OrderDeduplicationCache()
    coid1, _ = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    cache.mark_completed(coid1, "ORDER-123")

    coid2, is_dup = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    assert is_dup is False
    assert coid2 != coid1


def test_expired_order_not_deduplicated():
    """Orders past TTL are pruned and don't block new orders."""
    cache = OrderDeduplicationCache(ttl_seconds=300)
    coid1, _ = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)

    # Backdate submission to simulate expiry
    cache._cache[coid1].submitted_at = (
        datetime.now(timezone.utc) - timedelta(seconds=400)
    )

    coid2, is_dup = cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    assert is_dup is False
    assert coid2 != coid1


def test_mark_completed_unknown_coid_is_noop():
    cache = OrderDeduplicationCache()
    # Should not raise
    cache.mark_completed("nonexistent-id", "ORDER-999")


def test_get_metrics():
    cache = OrderDeduplicationCache()
    cache.get_or_create("KXBTC-T3550", "buy", "yes", 55, 10)
    cache.get_or_create("KXETH-T2000", "buy", "yes", 40, 5)
    metrics = cache.get_metrics()
    assert metrics["cached_orders"] == 2
    assert metrics["pending"] == 2
    assert metrics["confirmed"] == 0


def test_singleton_returns_same_instance():
    c1 = get_order_cache()
    c2 = get_order_cache()
    assert c1 is c2

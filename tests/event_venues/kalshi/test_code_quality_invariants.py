"""Code quality invariant tests for Kalshi lane.

Tests enforce:
- Asset coverage: ALL_CRYPTO_ASSETS exact match across all grids
- RTI validation: hard-fail on undefined series shapes
- Settlement types: dedupe key hashability and equality
"""

import pytest

from merid.event_venues.kalshi.constants import (
    ALL_CRYPTO_ASSETS,
    assert_exact_assets,
)
from merid.event_venues.kalshi.market_filter import MIN_EDGE_GRID, MAX_PRICE_GRID
from merid.event_venues.kalshi.market_selector import CRYPTO_SERIES_BASE
from merid.event_venues.kalshi.series_shapes import get_series_timeframe_bucket
from merid.event_venues.kalshi.settlement_poller import SettlementDedupeKey

pytestmark = pytest.mark.kalshi_live_ready


class TestAssetCoverage:
    """Enforce 5-asset grid coverage everywhere."""

    def test_min_edge_covers_all_assets(self):
        assert set(MIN_EDGE_GRID.keys()) == ALL_CRYPTO_ASSETS

    def test_max_price_covers_all_assets(self):
        assert set(MAX_PRICE_GRID.keys()) == ALL_CRYPTO_ASSETS

    def test_crypto_series_base_covers_all_assets(self):
        assert set(CRYPTO_SERIES_BASE.keys()) == ALL_CRYPTO_ASSETS

    def test_assert_exact_assets_raises_on_missing(self):
        with pytest.raises(ValueError, match="ASSET-COVERAGE-FAIL"):
            assert_exact_assets({"BTC", "ETH"}, "test_context")

    def test_assert_exact_assets_raises_on_extra(self):
        with pytest.raises(ValueError, match="ASSET-COVERAGE-FAIL"):
            assert_exact_assets(
                {"BTC", "ETH", "SOL", "XRP", "DOGE", "SHIB"},
                "test_context",
            )


class TestRTIBucketValidation:
    """Hard-fail on undefined series shapes."""

    def test_undefined_series_raises_empty(self):
        with pytest.raises(ValueError, match="RTI-UNDEFINED"):
            get_series_timeframe_bucket("")

    def test_undefined_series_raises_no_dash(self):
        with pytest.raises(ValueError, match="RTI-UNDEFINED"):
            get_series_timeframe_bucket("INVALID")

    def test_undefined_series_raises_bad_tf(self):
        with pytest.raises(ValueError, match="RTI-UNDEFINED"):
            get_series_timeframe_bucket("KXBTC-INVALID_TF")


class TestSettlementPaginationTypes:
    """Settlement dedupe key types and hashability."""

    def test_duplicate_settlement_key_equality(self):
        seen = set()
        key1 = SettlementDedupeKey("mkt-123", "KXBTC", "2024-01-01T00:00:00Z")
        key2 = SettlementDedupeKey("mkt-123", "KXBTC", "2024-01-01T00:00:00Z")

        seen.add(key1)
        assert key2 in seen  # frozen dataclass equality + hashability

    def test_settlement_dedupe_key_str(self):
        key = SettlementDedupeKey("mkt-123", "KXBTC", "2024-01-01T00:00:00Z")
        assert str(key) == "mkt-123|KXBTC|2024-01-01T00:00:00Z"

    def test_different_keys_not_equal(self):
        key1 = SettlementDedupeKey("mkt-123", "KXBTC", "2024-01-01T00:00:00Z")
        key2 = SettlementDedupeKey("mkt-124", "KXBTC", "2024-01-01T00:00:00Z")
        key3 = SettlementDedupeKey("mkt-123", "KXBTC", "2024-01-02T00:00:00Z")

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

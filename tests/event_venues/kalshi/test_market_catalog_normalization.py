"""Integration tests for market_catalog normalization.

Tests the end-to-end normalization flow from raw API data to catalog markets:
- close_ts extraction from raw_data
- Normalization through contract_normalization.py
- Propagation to CatalogMarket
- Integration with market_state and downstream consumers
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi.market_catalog import (
    KalshiMarketCatalog,
    CatalogMarket,
)


def generate_future_ticker(minutes_ahead: int, asset: str = "BTC", strike: int = 15) -> str:
    """Generate a realistic 15m ticker with a future date.
    
    Args:
        minutes_ahead: How many minutes in the future the ticker should be
        asset: Asset prefix (BTC, ETH, SOL, XRP, DOGE)
        strike: Strike price
        
    Returns:
        A ticker string like "KXBTC15M-26JUL110615-15"
    """
    now = datetime.now(timezone.utc)
    # Convert to ET for ticker generation (Kalshi uses ET)
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now_et = now.astimezone(et)
    
    future_et = now_et + timedelta(minutes=minutes_ahead)
    
    # Format: YY MON DD HHMM
    yy = str(future_et.year)[-2:]
    mon = future_et.strftime("%b").upper()
    dd = f"{future_et.day:02d}"
    hhmm = f"{future_et.hour:02d}{future_et.minute:02d}"
    
    return f"KX{asset}15M-{yy}{mon}{dd}{hhmm}-{strike}"


class TestCloseTsExtraction:
    """Test extraction of close_ts from raw API data."""

    def test_close_ts_from_raw_data(self):
        """Test that close_ts is correctly extracted from raw_data."""
        now = datetime.now(timezone.utc)
        close_ts = (now + timedelta(minutes=10)).timestamp()

        market = EventMarket(
            market_id="KXBTC15M-26JUL110615-15",
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),  # Wrong time
            raw_data={
                "close_ts": close_ts,
                "status": "open",
            }
        )

        # Extract close_ts as catalog does
        raw_data = market.raw_data or {}
        extracted_close_ts = raw_data.get("close_ts") or raw_data.get("close_time_ts")

        assert extracted_close_ts == close_ts

    def test_close_time_ts_fallback(self):
        """Test that close_time_ts is used as fallback."""
        now = datetime.now(timezone.utc)
        close_ts = (now + timedelta(minutes=10)).timestamp()

        market = EventMarket(
            market_id="KXBTC15M-26JUL110615-15",
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),
            raw_data={
                "close_time_ts": close_ts,  # Alternative field name
                "status": "open",
            }
        )

        raw_data = market.raw_data or {}
        extracted_close_ts = raw_data.get("close_ts") or raw_data.get("close_time_ts")

        assert extracted_close_ts == close_ts

    def test_no_close_ts_in_raw_data(self):
        """Test handling when close_ts is missing from raw_data."""
        market = EventMarket(
            market_id="KXBTC15M-26JUL110615-15",
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=datetime.now(timezone.utc) + timedelta(hours=6),
            raw_data={
                "status": "open",
            }
        )

        raw_data = market.raw_data or {}
        extracted_close_ts = raw_data.get("close_ts") or raw_data.get("close_time_ts")

        assert extracted_close_ts is None


class TestCatalogNormalizationFlow:
    """Test the full normalization flow from EventMarket to CatalogMarket.
    
    NOTE: For 15m contracts, ticker-based inference is PRIMARY. The close_ts/end_date
    fields are only used for non-15m contracts or when ticker inference fails.
    """

    def test_15m_crypto_normalization_with_close_ts(self):
        """Test normalization of 15m crypto market with close_ts."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")
        close_ts = (now + timedelta(minutes=10)).timestamp()
        close_time_utc = datetime.fromtimestamp(close_ts, tz=timezone.utc)

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),  # Wrong time (should be ignored)
            raw_data={
                "close_ts": close_ts,
                "status": "open",
            }
        )

        # Simulate catalog normalization logic
        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            close_time=close_time_utc,
            now=now,
        )

        # For 15m contracts, ticker inference is PRIMARY
        assert normalized.status == "ok"
        assert normalized.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)
        assert "ticker_inference_primary" in normalized.status_reason

    def test_15m_crypto_normalization_without_close_ts(self):
        """Test normalization of 15m crypto market without close_ts (uses ticker inference)."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")
        end_date = now + timedelta(minutes=10)

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=end_date,
            raw_data={
                "status": "open",
            }
        )

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            close_time=None,
            now=now,
        )

        # For 15m contracts, ticker inference is PRIMARY (not end_date)
        assert normalized.status == "ok"
        assert normalized.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)
        assert "ticker_inference_primary" in normalized.status_reason

    def test_15m_crypto_normalization_invariant_guard_rejection(self):
        """Test that invariant guard rejects 15m contracts with wrong expiry."""
        now = datetime.now(timezone.utc)
        # Use a ticker with far future date (outside 24 hour tolerance)
        ticker = generate_future_ticker(minutes_ahead=1500, asset="BTC")  # 25 hours

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),
            raw_data={
                "status": "open",
            }
        )

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            now=now,
        )

        # Should be rejected by invariant guard
        assert normalized.status == "invalid_metadata"
        assert "15m contract expiry out of bounds" in normalized.status_reason


class TestAllFiveAssetsIntegration:
    """Test integration for all 5 crypto assets."""

    @pytest.mark.parametrize("asset,prefix", [
        ("BTC", "KXBTC"),
        ("ETH", "KXETH"),
        ("SOL", "KXSOL"),
        ("XRP", "KXXRP"),
        ("DOGE", "KXDOGE"),
    ])
    def test_all_assets_normalization_with_close_ts(self, asset, prefix):
        """Test that normalization works for all 5 assets with close_ts."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset=asset)
        close_ts = (now + timedelta(minutes=10)).timestamp()
        close_time_utc = datetime.fromtimestamp(close_ts, tz=timezone.utc)

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question=f"{asset} > 50000",
            description=f"{asset} > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),
            raw_data={
                "close_ts": close_ts,
                "status": "open",
            }
        )

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            close_time=close_time_utc,
            now=now,
        )

        assert normalized.asset == asset
        assert normalized.status == "ok"
        # For 15m contracts, ticker inference is PRIMARY
        assert normalized.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)
        assert "ticker_inference_primary" in normalized.status_reason


class TestDownstreamPropagation:
    """Test that normalized data propagates to downstream consumers."""

    def test_catalog_market_minutes_to_expiry_propagation(self):
        """Test that minutes_to_expiry is set on CatalogMarket."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")
        close_ts = (now + timedelta(minutes=10)).timestamp()
        close_time_utc = datetime.fromtimestamp(close_ts, tz=timezone.utc)

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),
            raw_data={
                "close_ts": close_ts,
                "status": "open",
            }
        )

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            close_time=close_time_utc,
            now=now,
        )

        # Create CatalogMarket with normalized data
        catalog_market = CatalogMarket(
            market=market,
            asset=normalized.asset,
            timeframe="15m",
            expires_at=normalized.expiry_ts,
            minutes_to_expiry=normalized.minutes_to_expiry,
            api_status="open",
            health_status=normalized.status,
            tradeable=normalized.status == "ok",
        )

        # For 15m contracts, ticker inference is PRIMARY
        assert catalog_market.minutes_to_expiry == pytest.approx(10.0, abs=1.0)  # Allow parsing tolerance
        assert catalog_market.health_status == "ok"
        assert catalog_market.tradeable is True

    def test_invalid_metadata_propagation(self):
        """Test that invalid_metadata status propagates correctly."""
        now = datetime.now(timezone.utc)
        # Use a ticker with far future date (outside 24 hour tolerance)
        ticker = generate_future_ticker(minutes_ahead=1500, asset="BTC")  # 25 hours

        market = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question="BTC > 50000",
            description="BTC > 50000",
            outcomes=[],
            end_date=now + timedelta(hours=6),
            raw_data={
                "status": "open",
            }
        )

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=market.market_id,
            end_date=market.end_date,
            now=now,
        )

        # Create CatalogMarket with invalid metadata
        catalog_market = CatalogMarket(
            market=market,
            asset=normalized.asset,
            timeframe="15m",
            expires_at=normalized.expiry_ts,
            minutes_to_expiry=normalized.minutes_to_expiry,
            api_status="open",
            health_status=normalized.status,
            tradeable=normalized.status == "ok",
        )

        assert catalog_market.health_status == "invalid_metadata"
        assert catalog_market.tradeable is False


class TestSourceTracking:
    """Test that expiry source is tracked and logged.
    
    NOTE: For 15m contracts, ticker-based inference is PRIMARY.
    """

    def test_source_extraction_from_status_reason(self):
        """Test extraction of expiry source from status_reason for 15m contracts."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        # Extract source as catalog does
        expiry_source = "unknown"
        if "(source:" in normalized.status_reason:
            expiry_source = normalized.status_reason.split("(source:")[-1].rstrip(")").strip()

        assert expiry_source == "ticker_inference_primary"

    def test_end_date_source_extraction(self):
        """Test extraction of end_date source for non-15m contracts."""
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(minutes=10)

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            end_date=end_date,
            now=now,
        )

        expiry_source = "unknown"
        if "(source:" in normalized.status_reason:
            expiry_source = normalized.status_reason.split("(source:")[-1].rstrip(")").strip()

        assert expiry_source == "end_date"

    def test_separate_close_time_and_end_date_priority(self):
        """Test that for 15m contracts, ticker inference is PRIMARY over close_time/end_date."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")
        close_time = now + timedelta(minutes=10)  # Correct 15m expiry
        end_date = now + timedelta(hours=6)  # Wrong expiry (should be ignored)

        from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract

        normalized = normalize_kalshi_contract(
            ticker=ticker,
            end_date=end_date,  # Pass separately
            close_time=close_time,  # Pass separately
            now=now,
        )

        # For 15m contracts, ticker inference is PRIMARY (not close_time or end_date)
        assert normalized.status == "ok"
        assert "ticker_inference_primary" in normalized.status_reason

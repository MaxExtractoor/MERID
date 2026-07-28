"""Unit tests for contract_normalization.py.

Tests the time-source normalization bug fix:
- close_time should be prioritized over end_date for 15m contracts
- Invariant guard rejects 15m contracts with expiry outside expected window
- Explicit logging of expiry source
- Alert for missing close_ts on 15m contracts
"""

import pytest
from datetime import datetime, timezone, timedelta
from merid.event_venues.kalshi.contract_normalization import (
    normalize_kalshi_contract,
    map_ticker_to_asset,
    NormalizedKalshiContract,
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


class TestTickerToAssetMapping:
    """Test ticker to asset mapping for all 5 crypto assets."""

    def test_btc_ticker_mapping(self):
        assert map_ticker_to_asset("KXBTC15M-26JUL110615-15") == "BTC"
        assert map_ticker_to_asset("KXBTC-26JUL110615-15") == "BTC"

    def test_eth_ticker_mapping(self):
        assert map_ticker_to_asset("KXETH15M-26JUL110615-15") == "ETH"
        assert map_ticker_to_asset("KXETH-26JUL110615-15") == "ETH"

    def test_sol_ticker_mapping(self):
        assert map_ticker_to_asset("KXSOL15M-26JUL110615-15") == "SOL"
        assert map_ticker_to_asset("KXSOL-26JUL110615-15") == "SOL"

    def test_xrp_ticker_mapping(self):
        assert map_ticker_to_asset("KXXRP15M-26JUL110615-15") == "XRP"
        assert map_ticker_to_asset("KXXRP-26JUL110615-15") == "XRP"

    def test_doge_ticker_mapping(self):
        assert map_ticker_to_asset("KXDOGE15M-26JUL110615-15") == "DOGE"
        assert map_ticker_to_asset("KXDOGE-26JUL110615-15") == "DOGE"

    def test_unrecognized_ticker_mapping(self):
        assert map_ticker_to_asset("KXINVALID15M-26JUL110615-15") is None
        assert map_ticker_to_asset("INVALID-TICKER") is None


class TestExpirySourcePriority:
    """Test expiry source priority order for 15m contracts.
    
    CRITICAL UPDATE 2026-07-28: For 15m contracts, ticker-based inference is PRIMARY.
    The ticker format KXBTC15M-26JUL110515-15 contains the correct contract expiry.
    Priority for 15m: ticker inference > expected_expiration_time > expiration_time > close_time > end_date
    
    NOTE: Ticker inference is PRIMARY and cannot be overridden by expected_expiration_time
    for 15m contracts. The ticker contains the authoritative expiry time.
    """

    def test_ticker_inference_primary_for_15m(self):
        """Test that ticker-based inference is primary for 15m contracts."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")
        
        close_time = now + timedelta(hours=6)  # Wrong (should be ignored)
        end_date = now + timedelta(hours=12)  # Wrong (should be ignored)

        result = normalize_kalshi_contract(
            ticker=ticker,
            end_date=end_date,
            close_time=close_time,
            now=now,
        )

        # Should use ticker inference (primary for 15m), not close_time or end_date
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)
        assert "ticker_inference_primary" in result.status_reason

    def test_expected_expiration_time_fallback_when_ticker_inference_fails(self):
        """Test that expected_expiration_time is used when ticker inference fails."""
        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(minutes=10)
        # Use non-15m ticker so ticker inference fails
        ticker = "KXBTC-26JUL110615-15"

        result = normalize_kalshi_contract(
            ticker=ticker,
            expected_expiration_time=expected_expiry.isoformat(),
            now=now,
        )

        # Should use expected_expiration_time (ticker inference fails for non-15m)
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)
        assert "expected_expiration_time" in result.status_reason

    def test_close_time_fallback_for_non_15m(self):
        """Test that close_time is used for non-15m contracts."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)
        # Use non-15m ticker to avoid ticker inference
        result = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            close_time=close_time,
            now=now,
        )

        # Should use close_time for non-15m contracts
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)
        assert "close_time" in result.status_reason


class Test15mInvariantGuard:
    """Test invariant guard for 15m contracts.
    
    CRITICAL UPDATE 2026-07-28: For 15m contracts, ticker-based inference is PRIMARY.
    The invariant guard checks that the inferred expiry is within a reasonable window.
    """

    def test_15m_contract_within_allowed_window(self):
        """Test that 15m contracts within allowed window are accepted."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)

    def test_15m_contract_outside_allowed_window_rejected(self):
        """Test that 15m contracts outside allowed window are rejected."""
        now = datetime.now(timezone.utc)
        # Use a ticker with far future date (outside 24 hour tolerance)
        # Invariant guard allows -1 hour to +24 hours for ticker-inferred expiry
        ticker = generate_future_ticker(minutes_ahead=1500, asset="BTC")  # 25 hours

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        # Should be rejected as invalid_metadata
        assert result.status == "invalid_metadata"
        assert "15m contract expiry out of bounds" in result.status_reason
        assert result.seconds_to_expiry == 0.0

    def test_15m_contract_exactly_at_boundary_accepted(self):
        """Test that 15m contracts at exactly 20 minute boundary are accepted."""
        now = datetime.now(timezone.utc)
        # Use a ticker with exactly 20 minute future date
        ticker = generate_future_ticker(minutes_ahead=20, asset="BTC")

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(1200, abs=60)  # ~20 minutes (allow parsing tolerance)

    def test_non_15m_contract_no_invariant_guard(self):
        """Test that non-15m contracts don't have invariant guard applied."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(hours=6)  # Would be rejected for 15m

        result = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            close_time=close_time,
            now=now,
        )

        # Should be accepted (no invariant guard for non-15m)
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(21600, abs=1)


class TestAllFiveAssetsSymmetricTreatment:
    """Test that all 5 assets are treated symmetrically.
    
    CRITICAL UPDATE 2026-07-28: For 15m contracts, ticker-based inference is PRIMARY.
    """

    @pytest.mark.parametrize("asset,prefix", [
        ("BTC", "KXBTC"),
        ("ETH", "KXETH"),
        ("SOL", "KXSOL"),
        ("XRP", "KXXRP"),
        ("DOGE", "KXDOGE"),
    ])
    def test_all_assets_ticker_inference(self, asset, prefix):
        """Test that ticker-based inference works for all 5 assets."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset=asset)
        
        close_time = now + timedelta(hours=6)  # Wrong (should be ignored)
        end_date = now + timedelta(hours=12)  # Wrong (should be ignored)

        result = normalize_kalshi_contract(
            ticker=ticker,
            end_date=end_date,
            close_time=close_time,
            now=now,
        )

        assert result.asset == asset
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=60)  # ~10 minutes (allow parsing tolerance)
        assert "ticker_inference_primary" in result.status_reason

    @pytest.mark.parametrize("asset,prefix", [
        ("BTC", "KXBTC"),
        ("ETH", "KXETH"),
        ("SOL", "KXSOL"),
        ("XRP", "KXXRP"),
        ("DOGE", "KXDOGE"),
    ])
    def test_all_assets_invariant_guard(self, asset, prefix):
        """Test that invariant guard works for all 5 assets."""
        now = datetime.now(timezone.utc)
        # Use a ticker with far future date (outside 24 hour tolerance)
        # Invariant guard allows -1 hour to +24 hours for ticker-inferred expiry
        ticker = generate_future_ticker(minutes_ahead=1500, asset=asset)  # 25 hours

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        assert result.asset == asset
        assert result.status == "invalid_metadata"
        assert "15m contract expiry out of bounds" in result.status_reason


class TestExpiredContracts:
    """Test handling of expired contracts.
    
    CRITICAL UPDATE 2026-07-28: For 15m contracts, ticker-based inference is PRIMARY.
    """

    def test_expired_contract_status(self):
        """Test that expired contracts are marked as expired."""
        now = datetime.now(timezone.utc)
        # Use a ticker with past date (already expired)
        ticker = generate_future_ticker(minutes_ahead=-10, asset="BTC")

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        assert result.status == "expired"
        assert result.seconds_to_expiry < 0
        assert "expired at" in result.status_reason.lower()


class TestInvalidMetadata:
    """Test handling of invalid metadata."""

    def test_unrecognized_ticker_invalid_metadata(self):
        """Test that unrecognized tickers are marked as invalid_metadata."""
        result = normalize_kalshi_contract(
            ticker="INVALID-TICKER",
            now=datetime.now(timezone.utc),
        )

        assert result.status == "invalid_metadata"
        assert result.asset is None
        assert "Unrecognized ticker prefix" in result.status_reason

    def test_no_resolvable_expiry_invalid_metadata(self):
        """Test that contracts with no resolvable expiry are marked as invalid_metadata."""
        # Use a non-15m ticker to avoid ticker inference fallback
        result = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            end_date=None,
            close_time=None,
            now=datetime.now(timezone.utc),
        )

        assert result.status == "invalid_metadata"
        assert "No resolvable expiry" in result.status_reason
        assert result.seconds_to_expiry == 0.0


class TestSourceLogging:
    """Test that expiry source is correctly logged in status_reason.
    
    CRITICAL UPDATE 2026-07-28: For 15m contracts, ticker-based inference is PRIMARY.
    For non-15m contracts, close_time/end_date sources are used.
    """

    def test_ticker_inference_source_logged(self):
        """Test that ticker_inference_primary source is logged for 15m contracts."""
        now = datetime.now(timezone.utc)
        ticker = generate_future_ticker(minutes_ahead=10, asset="BTC")

        result = normalize_kalshi_contract(
            ticker=ticker,
            now=now,
        )

        assert "ticker_inference_primary" in result.status_reason

    def test_close_time_source_logged_for_non_15m(self):
        """Test that close_time source is logged for non-15m contracts."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            close_time=close_time,
            now=now,
        )

        assert "close_time" in result.status_reason

    def test_end_date_source_logged_for_non_15m(self):
        """Test that end_date source is logged for non-15m contracts."""
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC-26JUL110615-15",  # Not a 15m ticker
            end_date=end_date,
            now=now,
        )

        assert "end_date" in result.status_reason

    def test_expected_expiration_time_source_logged(self):
        """Test that expected_expiration_time source is logged for non-15m contracts."""
        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(minutes=10)
        # Use non-15m ticker so ticker inference fails
        ticker = "KXBTC-26JUL110615-15"

        result = normalize_kalshi_contract(
            ticker=ticker,
            expected_expiration_time=expected_expiry.isoformat(),
            now=now,
        )

        assert "expected_expiration_time" in result.status_reason

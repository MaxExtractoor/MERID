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
    """Test expiry source priority order for 15m contracts."""

    def test_close_time_priority_over_end_date(self):
        """Test that close_time is prioritized over end_date for 15m contracts."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)  # 10 minutes from now
        end_date = now + timedelta(hours=6)  # 6 hours from now (wrong)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            end_date=end_date,
            close_time=close_time,
            now=now,
        )

        # Should use close_time (10 minutes), not end_date (6 hours)
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)  # 10 minutes
        assert "source: close_time" in result.status_reason
        assert "source: end_date" not in result.status_reason

    def test_end_date_fallback_when_close_time_missing(self):
        """Test that end_date is used as fallback when close_time is missing."""
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            end_date=end_date,
            close_time=None,
            now=now,
        )

        # Should use end_date as fallback
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)
        assert "source: end_date" in result.status_reason

    def test_expected_expiration_time_highest_priority(self):
        """Test that expected_expiration_time has highest priority."""
        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(minutes=10)
        close_time = now + timedelta(minutes=20)
        end_date = now + timedelta(hours=6)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            expected_expiration_time=expected_expiry.isoformat(),
            end_date=end_date,
            close_time=close_time,
            now=now,
        )

        # Should use expected_expiration_time (highest priority)
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)
        assert "source: expected_expiration_time" in result.status_reason


class Test15mInvariantGuard:
    """Test invariant guard for 15m contracts."""

    def test_15m_contract_within_allowed_window(self):
        """Test that 15m contracts within allowed window are accepted."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)  # Within 20 minute tolerance

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            close_time=close_time,
            now=now,
        )

        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)

    def test_15m_contract_outside_allowed_window_rejected(self):
        """Test that 15m contracts outside allowed window are rejected."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(hours=6)  # Way outside 20 minute tolerance

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            close_time=close_time,
            now=now,
        )

        # Should be rejected as invalid_metadata
        assert result.status == "invalid_metadata"
        assert "15m contract expiry out of bounds" in result.status_reason
        assert result.seconds_to_expiry == 0.0

    def test_15m_contract_exactly_at_boundary_accepted(self):
        """Test that 15m contracts at exactly 20 minute boundary are accepted."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=20)  # Exactly at boundary

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            close_time=close_time,
            now=now,
        )

        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(1200, abs=1)

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
    """Test that all 5 assets are treated symmetrically."""

    @pytest.mark.parametrize("asset,prefix", [
        ("BTC", "KXBTC"),
        ("ETH", "KXETH"),
        ("SOL", "KXSOL"),
        ("XRP", "KXXRP"),
        ("DOGE", "KXDOGE"),
    ])
    def test_all_assets_close_time_priority(self, asset, prefix):
        """Test that close_time priority works for all 5 assets."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)
        end_date = now + timedelta(hours=6)

        ticker = f"{prefix}15M-26JUL110615-15"
        result = normalize_kalshi_contract(
            ticker=ticker,
            end_date=end_date,
            close_time=close_time,
            now=now,
        )

        assert result.asset == asset
        assert result.status == "ok"
        assert result.seconds_to_expiry == pytest.approx(600, abs=1)
        assert "source: close_time" in result.status_reason

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
        close_time = now + timedelta(hours=6)  # Outside allowed window

        ticker = f"{prefix}15M-26JUL110615-15"
        result = normalize_kalshi_contract(
            ticker=ticker,
            close_time=close_time,
            now=now,
        )

        assert result.asset == asset
        assert result.status == "invalid_metadata"
        assert "15m contract expiry out of bounds" in result.status_reason


class TestExpiredContracts:
    """Test handling of expired contracts."""

    def test_expired_contract_status(self):
        """Test that expired contracts are marked as expired."""
        now = datetime.now(timezone.utc)
        close_time = now - timedelta(minutes=10)  # Already expired

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            close_time=close_time,
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
    """Test that expiry source is correctly logged in status_reason."""

    def test_close_time_source_logged(self):
        """Test that close_time source is logged."""
        now = datetime.now(timezone.utc)
        close_time = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            close_time=close_time,
            now=now,
        )

        assert "source: close_time" in result.status_reason

    def test_end_date_source_logged(self):
        """Test that end_date source is logged."""
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            end_date=end_date,
            now=now,
        )

        assert "source: end_date" in result.status_reason

    def test_expected_expiration_time_source_logged(self):
        """Test that expected_expiration_time source is logged."""
        now = datetime.now(timezone.utc)
        expected_expiry = now + timedelta(minutes=10)

        result = normalize_kalshi_contract(
            ticker="KXBTC15M-26JUL110615-15",
            expected_expiration_time=expected_expiry.isoformat(),
            now=now,
        )

        assert "source: expected_expiration_time" in result.status_reason

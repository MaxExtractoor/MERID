"""
Venue compliance enforcement tests (S9-03 gap closure).

Validates:
- Blocked venues (Bybit, global Binance, BitMEX, etc.) are rejected
- US-compliant venues are allowed
- Optional/data-only venues blocked for live trading
- UniversalRouter.validate_venue() raises on blocked venues
- Asset class routing returns only compliant venues
"""

import unittest

from core.us_compliance_config import (
    US_COMPLIANT_VENUES,
    BLOCKED_VENUES,
    OPTIONAL_VENUES,
    ALLOWED_VENUES,
    is_venue_allowed,
    is_venue_blocked,
    is_venue_optional,
    is_venue_us_compliant,
    get_venues_for_asset_class,
    validate_venue_selection,
)
from core.universal_router import UniversalRouter


class TestBlockedVenueRejection(unittest.TestCase):
    """Blocked venues are rejected at every level."""

    def test_bybit_is_blocked(self):
        self.assertTrue(is_venue_blocked("bybit"))

    def test_global_binance_is_blocked(self):
        self.assertTrue(is_venue_blocked("binance"))

    def test_bitmex_is_blocked(self):
        self.assertTrue(is_venue_blocked("bitmex"))

    def test_deribit_is_blocked(self):
        self.assertTrue(is_venue_blocked("deribit"))

    def test_ftx_is_blocked(self):
        self.assertTrue(is_venue_blocked("ftx"))

    def test_huobi_is_blocked(self):
        self.assertTrue(is_venue_blocked("huobi"))

    def test_blocked_venues_not_allowed(self):
        for venue in BLOCKED_VENUES:
            self.assertFalse(
                is_venue_allowed(venue),
                f"Blocked venue '{venue}' should not be allowed",
            )

    def test_blocked_venues_not_us_compliant(self):
        for venue in BLOCKED_VENUES:
            self.assertFalse(
                is_venue_us_compliant(venue),
                f"Blocked venue '{venue}' should not be US-compliant",
            )


class TestRouterRejectsBlockedVenues(unittest.TestCase):
    """UniversalRouter.validate_venue() raises ValueError on blocked venues."""

    def setUp(self):
        self.router = UniversalRouter()

    def test_bybit_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.router.validate_venue("bybit")
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_binance_global_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.router.validate_venue("binance")
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_bitmex_raises(self):
        with self.assertRaises(ValueError):
            self.router.validate_venue("bitmex")

    def test_unknown_venue_raises(self):
        with self.assertRaises(ValueError):
            self.router.validate_venue("totally_fake_exchange")

    def test_compliant_venue_passes(self):
        self.assertTrue(self.router.validate_venue("alpaca"))
        self.assertTrue(self.router.validate_venue("kalshi"))
        self.assertTrue(self.router.validate_venue("coinbase"))


class TestUSCompliantVenues(unittest.TestCase):
    """US-compliant venues are properly categorized."""

    def test_alpaca_is_compliant(self):
        self.assertTrue(is_venue_us_compliant("alpaca"))

    def test_kalshi_is_compliant(self):
        self.assertTrue(is_venue_us_compliant("kalshi"))

    def test_coinbase_is_compliant(self):
        self.assertTrue(is_venue_us_compliant("coinbase"))

    def test_binanceus_is_compliant(self):
        self.assertTrue(is_venue_us_compliant("binanceus"))

    def test_compliant_venues_are_allowed(self):
        for venue in US_COMPLIANT_VENUES:
            self.assertTrue(
                is_venue_allowed(venue),
                f"Compliant venue '{venue}' should be allowed",
            )


class TestOptionalVenuesBlockedForLive(unittest.TestCase):
    """Optional/data-only venues blocked for live trading."""

    def test_okx_is_optional(self):
        self.assertTrue(is_venue_optional("okx"))

    def test_kucoin_is_optional(self):
        self.assertTrue(is_venue_optional("kucoin"))

    def test_optional_venues_allowed_for_data(self):
        for venue in OPTIONAL_VENUES:
            self.assertTrue(
                is_venue_allowed(venue),
                f"Optional venue '{venue}' should be allowed for data",
            )

    def test_optional_venues_blocked_for_live_trading(self):
        for venue in OPTIONAL_VENUES:
            self.assertFalse(
                validate_venue_selection(venue, "crypto_spot", live=True),
                f"Optional venue '{venue}' should be blocked for live trading",
            )


class TestAssetClassRouting(unittest.TestCase):
    """Asset class routing returns only compliant venues."""

    def test_equities_routes_to_alpaca_ibkr(self):
        venues = get_venues_for_asset_class("equities")
        self.assertIn("alpaca", venues)
        self.assertIn("ibkr", venues)

    def test_prediction_routes_to_kalshi(self):
        venues = get_venues_for_asset_class("prediction")
        self.assertIn("kalshi", venues)

    def test_crypto_spot_has_compliant_venues(self):
        venues = get_venues_for_asset_class("crypto_spot")
        self.assertTrue(len(venues) > 0)
        for v in venues:
            self.assertNotIn(v, BLOCKED_VENUES)

    def test_no_blocked_venues_in_any_asset_class(self):
        for asset_class in ["equities", "etfs", "options", "futures",
                            "fx", "crypto_spot", "crypto_perp", "prediction"]:
            venues = get_venues_for_asset_class(asset_class)
            for v in venues:
                self.assertNotIn(
                    v, BLOCKED_VENUES,
                    f"Blocked venue '{v}' found in {asset_class} routing",
                )


class TestValidateVenueSelection(unittest.TestCase):
    """validate_venue_selection() enforces all rules."""

    def test_blocked_venue_fails(self):
        self.assertFalse(validate_venue_selection("bybit", "crypto_spot"))

    def test_compliant_venue_passes(self):
        self.assertTrue(validate_venue_selection("alpaca", "equities"))

    def test_kalshi_for_prediction(self):
        self.assertTrue(validate_venue_selection("kalshi", "prediction"))

    def test_wrong_asset_class_fails(self):
        self.assertFalse(validate_venue_selection("kalshi", "equities"))

    def test_optional_venue_data_only(self):
        self.assertFalse(validate_venue_selection("okx", "crypto_spot", live=True))


if __name__ == "__main__":
    unittest.main()

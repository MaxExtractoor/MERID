"""Kalshi Trade API v2 time_in_force must use OpenAPI enum strings, not gtc/ioc/fok."""

import unittest

from merid.event_venues.kalshi.client import merid_time_in_force_to_kalshi_api


class TestMeridTimeInForceToKalshiApi(unittest.TestCase):
    def test_legacy_short_and_upper(self):
        self.assertEqual(merid_time_in_force_to_kalshi_api("gtc"), "good_till_canceled")
        self.assertEqual(merid_time_in_force_to_kalshi_api("GTC"), "good_till_canceled")
        self.assertEqual(merid_time_in_force_to_kalshi_api("ioc"), "immediate_or_cancel")
        self.assertEqual(merid_time_in_force_to_kalshi_api("IOC"), "immediate_or_cancel")
        self.assertEqual(merid_time_in_force_to_kalshi_api("fok"), "fill_or_kill")
        self.assertEqual(merid_time_in_force_to_kalshi_api("FOK"), "fill_or_kill")

    def test_api_native_strings_passthrough(self):
        self.assertEqual(
            merid_time_in_force_to_kalshi_api("good_till_canceled"),
            "good_till_canceled",
        )
        self.assertEqual(
            merid_time_in_force_to_kalshi_api("immediate_or_cancel"),
            "immediate_or_cancel",
        )
        self.assertEqual(
            merid_time_in_force_to_kalshi_api("fill_or_kill"),
            "fill_or_kill",
        )

    def test_default_and_empty(self):
        self.assertEqual(merid_time_in_force_to_kalshi_api(None), "good_till_canceled")
        self.assertEqual(merid_time_in_force_to_kalshi_api(""), "good_till_canceled")


if __name__ == "__main__":
    unittest.main()

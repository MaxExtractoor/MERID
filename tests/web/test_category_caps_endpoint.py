"""Contract tests for GET /api/v1/kalshi/universe/category-caps response shape."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock


class TestCategoryCapsEndpoint(unittest.TestCase):
    def test_get_category_caps_returns_expected_keys_and_usd_fields(self) -> None:
        from merid.event_venues.kalshi.category_exposure import ExposureSnapshot
        from web.api import kalshi_api

        snap = ExposureSnapshot(
            category_notional={"crypto": 10.5},
            corr_notional={"BTC": 20.0},
            category_caps={"crypto": 2000.0},
            corr_cap=800.0,
            asset_caps={"BTC": 250.0},
        )
        tracker = mock.Mock()
        tracker.get_snapshot.return_value = snap

        with mock.patch(
            "merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker",
            return_value=tracker,
        ):
            out = asyncio.run(kalshi_api.get_category_caps())

        self.assertEqual(out["category_notional"], {"crypto": 10.5})
        self.assertEqual(out["corr_notional"], {"BTC": 20.0})
        self.assertEqual(out["category_caps"], {"crypto": 2000.0})
        self.assertEqual(out["corr_cap"], 800.0)
        self.assertEqual(out["corr_cap_usd"], 800.0)
        self.assertEqual(out["asset_caps"], {"BTC": 250.0})
        self.assertNotIn("error", out)

    def test_get_category_caps_includes_empty_asset_caps_on_tracker_error(self) -> None:
        from web.api import kalshi_api

        with mock.patch(
            "merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker",
            side_effect=RuntimeError("tracker down"),
        ):
            out = asyncio.run(kalshi_api.get_category_caps())

        self.assertEqual(out["category_notional"], {})
        self.assertEqual(out["corr_notional"], {})
        self.assertEqual(out["category_caps"], {})
        self.assertEqual(out["corr_cap"], 0.0)
        self.assertEqual(out["corr_cap_usd"], 0.0)
        self.assertEqual(out["asset_caps"], {})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()

"""Contract tests: Kalshi venue recon fail-closed in live when REST snapshot unavailable."""

from __future__ import annotations

import os
import unittest
from unittest import mock


class TestKalshiReconcileFailClosedLive(unittest.TestCase):
    def tearDown(self) -> None:
        import merid.reconciliation.venue_reconciler as vr

        with vr._recon_lock:
            vr._last_discrepancies = []
            vr._reconciliation_has_run = False
            vr._last_reconciliation_ts = 0.0

    def test_fetch_failure_live_emits_critical_and_blocks_gate(self) -> None:
        import merid.reconciliation.venue_reconciler as vr

        with mock.patch.dict(os.environ, {"MERID_PM_TRADING_MODE": "live"}):
            with mock.patch(
                "merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter",
            ) as m_ad:
                m_ad.side_effect = RuntimeError("network down")
                discs = vr.reconcile_venue("kalshi")

        self.assertEqual(len(discs), 1)
        self.assertEqual(discs[0].symbol, vr._KALSHI_UNREACHABLE_SYMBOL)
        self.assertEqual(discs[0].severity, "critical")
        self.assertTrue(vr.has_critical_discrepancies())

    def test_fetch_failure_paper_clears_kalshi_slice_without_critical(self) -> None:
        import merid.reconciliation.venue_reconciler as vr

        with mock.patch.dict(os.environ, {"MERID_PM_TRADING_MODE": "paper"}):
            with mock.patch(
                "merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter",
            ) as m_ad:
                m_ad.side_effect = RuntimeError("network down")
                discs = vr.reconcile_venue("kalshi")

        self.assertEqual(discs, [])
        self.assertFalse(vr.has_critical_discrepancies())


if __name__ == "__main__":
    unittest.main()

"""Tests for merid.alerts.trade_notifier — Telegram trade notification system.

Validates:
  - FillRecord / CycleDigest data structures
  - Message formatting (fills, digests, lifecycle events)
  - TradeNotifier accumulation, flush logic, digest cadence
  - Anti-spam: quiet cycles produce no messages
  - Continuous trader integration points
"""

import unittest
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
CT_FILE = ROOT / "merid" / "trading" / "kalshi_continuous_trader.py"
NOTIFIER_FILE = ROOT / "merid" / "alerts" / "trade_notifier.py"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------

class TestFillRecord(unittest.TestCase):
    def test_fill_record_fields(self):
        from merid.alerts.trade_notifier import FillRecord
        f = FillRecord(
            ticker="KXBTC-26MAR20-T85000",
            side="yes",
            contracts=3,
            price_cents=42,
            fee_cents=2,
            edge=0.045,
            status="executed",
            order_id="abc123",
        )
        self.assertEqual(f.ticker, "KXBTC-26MAR20-T85000")
        self.assertEqual(f.side, "yes")
        self.assertEqual(f.contracts, 3)
        self.assertEqual(f.price_cents, 42)
        self.assertEqual(f.fee_cents, 2)
        self.assertAlmostEqual(f.edge, 0.045)
        self.assertEqual(f.status, "executed")
        self.assertEqual(f.order_id, "abc123")


class TestCycleDigest(unittest.TestCase):
    def test_cycle_digest_defaults(self):
        from merid.alerts.trade_notifier import CycleDigest
        d = CycleDigest(
            cycle=10,
            balance_cents=5000,
            portfolio_cents=2000,
            total_value_cents=7000,
            peak_cents=7500,
            drawdown_pct=6.67,
            pnl_cents=200,
            fee_drag_pct=1.5,
            vol_band="mid",
            annualized_vol_pct=45.0,
            orders_placed=2,
            orders_filled=1,
        )
        self.assertEqual(d.cycle, 10)
        self.assertEqual(d.positions, {})
        self.assertEqual(d.fills, [])
        self.assertFalse(d.halted)
        self.assertEqual(d.halt_reason, "")
        self.assertFalse(d.dry_run)


# ---------------------------------------------------------------------------
# Formatter tests
# ---------------------------------------------------------------------------

class TestFormatters(unittest.TestCase):
    def setUp(self):
        from merid.alerts.trade_notifier import FillRecord, CycleDigest
        self.fill = FillRecord(
            ticker="KXBTC-T85000",
            side="yes",
            contracts=5,
            price_cents=38,
            fee_cents=3,
            edge=0.052,
            status="executed",
            order_id="ord1",
        )
        self.digest = CycleDigest(
            cycle=8,
            balance_cents=4500,
            portfolio_cents=1500,
            total_value_cents=6000,
            peak_cents=6200,
            drawdown_pct=3.23,
            pnl_cents=150,
            fee_drag_pct=2.1,
            vol_band="mid",
            annualized_vol_pct=42.0,
            orders_placed=3,
            orders_filled=2,
            positions={"KXBTC-T85000": 5, "KXBTC-T84000": 3},
            fills=[self.fill],
            dry_run=False,
            fee_drag_tightening=True,
        )

    def test_format_fill_contains_key_info(self):
        from merid.alerts.trade_notifier import _format_fill
        s = _format_fill(self.fill)
        self.assertIn("YES", s)
        self.assertIn("5x", s)
        self.assertIn("KXBTC-T85000", s)
        self.assertIn("38¢", s)
        self.assertIn("edge=0.052", s)
        self.assertIn("fee=3¢", s)
        self.assertIn("✅", s)  # executed

    def test_format_fill_resting_icon(self):
        from merid.alerts.trade_notifier import FillRecord, _format_fill
        f = FillRecord("T", "no", 1, 50, 0, 0.01, "resting")
        s = _format_fill(f)
        self.assertIn("⏳", s)
        self.assertIn("NO", s)

    def test_format_cycle_digest_contains_all_sections(self):
        from merid.alerts.trade_notifier import _format_cycle_digest
        msg = _format_cycle_digest(self.digest)
        self.assertIn("Cycle 8", msg)
        self.assertIn("LIVE", msg)
        self.assertIn("Balance", msg)
        self.assertIn("$45.00", msg)
        self.assertIn("PnL", msg)
        self.assertIn("DD:", msg)
        self.assertIn("Fee drag: 2.1%", msg)
        self.assertIn("TIGHT", msg)
        self.assertIn("mid", msg)
        self.assertIn("Orders", msg)
        self.assertIn("Positions", msg)
        self.assertIn("KXBTC-T85000", msg)
        self.assertIn("KXBTC-T84000", msg)

    def test_format_cycle_digest_halted(self):
        from merid.alerts.trade_notifier import _format_cycle_digest
        self.digest.halted = True
        self.digest.halt_reason = "Drawdown > 10%"
        msg = _format_cycle_digest(self.digest)
        self.assertIn("HALTED", msg)
        self.assertIn("Drawdown > 10%", msg)

    def test_format_cycle_digest_dry_run(self):
        from merid.alerts.trade_notifier import _format_cycle_digest
        self.digest.dry_run = True
        msg = _format_cycle_digest(self.digest)
        self.assertIn("DRY", msg)

    def test_format_fill_batch(self):
        from merid.alerts.trade_notifier import _format_fill_batch
        msg = _format_fill_batch([self.fill], cycle=5, dry_run=False)
        self.assertIn("C5", msg)
        self.assertIn("1 filled", msg)
        self.assertIn("KXBTC-T85000", msg)

    def test_format_fill_batch_empty(self):
        from merid.alerts.trade_notifier import _format_fill_batch
        msg = _format_fill_batch([], cycle=5, dry_run=False)
        self.assertEqual(msg, "")

    def test_format_lifecycle(self):
        from merid.alerts.trade_notifier import _format_lifecycle
        msg = _format_lifecycle("start", "Config details here", cycle=1)
        self.assertIn("🚀", msg)
        self.assertIn("START", msg)
        self.assertIn("cycle 1", msg)
        self.assertIn("Config details here", msg)

    def test_format_lifecycle_halt(self):
        from merid.alerts.trade_notifier import _format_lifecycle
        msg = _format_lifecycle("halt", "Drawdown breach")
        self.assertIn("⛔", msg)
        self.assertIn("HALT", msg)


# ---------------------------------------------------------------------------
# TradeNotifier logic tests
# ---------------------------------------------------------------------------

class TestTradeNotifier(unittest.TestCase):
    def setUp(self):
        from merid.alerts.trade_notifier import TradeNotifier
        self.notifier = TradeNotifier(digest_every_n_cycles=4, quiet_cycles=True)

    def _make_digest(self, cycle, fills=None):
        from merid.alerts.trade_notifier import CycleDigest
        return CycleDigest(
            cycle=cycle,
            balance_cents=5000,
            portfolio_cents=1000,
            total_value_cents=6000,
            peak_cents=6500,
            drawdown_pct=7.69,
            pnl_cents=100,
            fee_drag_pct=1.0,
            vol_band="low",
            annualized_vol_pct=20.0,
            orders_placed=len(fills) if fills else 0,
            orders_filled=len(fills) if fills else 0,
            fills=fills or [],
        )

    def _make_fill(self):
        from merid.alerts.trade_notifier import FillRecord
        return FillRecord("KXBTC-T80000", "yes", 2, 45, 2, 0.03, "executed", "o1")

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_digest_cycle_sends_full_digest(self, mock_ff):
        """Cycle divisible by digest_every sends a full digest."""
        digest = self._make_digest(4)
        self.notifier.flush_cycle(digest)
        mock_ff.assert_called_once()
        msg = mock_ff.call_args[0][0]
        self.assertIn("Cycle 4", msg)
        self.assertIn("Balance", msg)

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_non_digest_cycle_with_fills_sends_batch(self, mock_ff):
        """Non-digest cycle with fills sends a compact fill batch."""
        fill = self._make_fill()
        self.notifier.record_fill(
            fill.ticker, fill.side, fill.contracts, fill.price_cents,
            fill.fee_cents, fill.edge, fill.status, fill.order_id,
        )
        digest = self._make_digest(3, fills=[fill])
        self.notifier.flush_cycle(digest)
        mock_ff.assert_called_once()
        msg = mock_ff.call_args[0][0]
        self.assertIn("C3", msg)
        self.assertIn("filled", msg)

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_quiet_cycle_no_fills_sends_nothing(self, mock_ff):
        """Quiet cycle with no fills between digests sends nothing."""
        digest = self._make_digest(3)
        self.notifier.flush_cycle(digest)
        mock_ff.assert_not_called()

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_record_fill_accumulates(self, mock_ff):
        """record_fill accumulates; flush_cycle includes them."""
        self.notifier.record_fill("T1", "yes", 1, 30, 1, 0.02, "executed")
        self.notifier.record_fill("T2", "no", 2, 60, 3, 0.04, "resting")
        self.assertEqual(len(self.notifier._pending_fills), 2)
        # Flush clears pending
        digest = self._make_digest(4)
        self.notifier.flush_cycle(digest)
        self.assertEqual(len(self.notifier._pending_fills), 0)

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_lifecycle_start(self, mock_ff):
        self.notifier.notify_start("Config info")
        mock_ff.assert_called_once()
        msg = mock_ff.call_args[0][0]
        self.assertIn("START", msg)
        # immediate=True
        self.assertTrue(mock_ff.call_args[1].get("immediate", False))

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_lifecycle_stop(self, mock_ff):
        self.notifier.notify_stop("Final stats")
        msg = mock_ff.call_args[0][0]
        self.assertIn("STOP", msg)

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_lifecycle_halt(self, mock_ff):
        self.notifier.notify_halt("Drawdown > 10%", cycle=5)
        msg = mock_ff.call_args[0][0]
        self.assertIn("HALT", msg)
        self.assertIn("Drawdown > 10%", msg)

    @patch("merid.alerts.trade_notifier._fire_and_forget")
    def test_lifecycle_error(self, mock_ff):
        self.notifier.notify_error("Connection timeout", cycle=7)
        msg = mock_ff.call_args[0][0]
        self.assertIn("ERROR", msg)


# ---------------------------------------------------------------------------
# Integration: continuous trader has notifier wiring
# ---------------------------------------------------------------------------

class TestContinuousTraderNotifierIntegration(unittest.TestCase):
    """Verify the continuous trader source code integrates TradeNotifier."""

    @classmethod
    def setUpClass(cls):
        cls.src = CT_FILE.read_text(encoding="utf-8", errors="replace")

    def test_notifier_import(self):
        self.assertIn("from merid.alerts.trade_notifier import TradeNotifier", self.src)

    def test_notifier_attribute(self):
        self.assertIn("self._notifier", self.src)

    def test_record_fill_called(self):
        self.assertIn("self._notifier.record_fill(", self.src)

    def test_flush_cycle_called(self):
        self.assertIn("self._notifier.flush_cycle(", self.src)

    def test_notify_start_called(self):
        self.assertIn("self._notifier.notify_start(", self.src)

    def test_notify_stop_called(self):
        self.assertIn("self._notifier.notify_stop(", self.src)

    def test_notify_halt_called(self):
        self.assertIn("self._notifier.notify_halt(", self.src)

    def test_notify_error_called(self):
        self.assertIn("self._notifier.notify_error(", self.src)

    def test_cycle_digest_import(self):
        self.assertIn("from merid.alerts.trade_notifier import CycleDigest", self.src)

    def test_env_configurable_digest_interval(self):
        self.assertIn("CT_TG_DIGEST_EVERY", self.src)


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------

class TestNotifierModuleStructure(unittest.TestCase):
    """Verify the trade_notifier module exports the expected API."""

    def test_module_importable(self):
        import merid.alerts.trade_notifier as m
        self.assertTrue(hasattr(m, "TradeNotifier"))
        self.assertTrue(hasattr(m, "FillRecord"))
        self.assertTrue(hasattr(m, "CycleDigest"))

    def test_fire_and_forget_exists(self):
        from merid.alerts.trade_notifier import _fire_and_forget
        self.assertTrue(callable(_fire_and_forget))

    def test_formatters_exist(self):
        from merid.alerts.trade_notifier import (
            _format_fill,
            _format_cycle_digest,
            _format_fill_batch,
            _format_lifecycle,
        )
        for fn in (_format_fill, _format_cycle_digest, _format_fill_batch, _format_lifecycle):
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()

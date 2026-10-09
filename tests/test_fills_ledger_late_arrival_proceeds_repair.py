"""Regression tests for out-of-order fill ingestion proceeds repair.

2026-10-09 ETH incident: the entry fill for KXETH15M-26OCT091045-45 traded at
14:40:54 UTC but was ingested +115s late via http_poller, while the reduce-only
exit fill landed via a faster lane ~1.4s after its trade.  When the exit was
indexed, ``_prior_signed_yes_cc`` saw zero prior exposure and booked the
covered NO close as a fresh pair-mint: proceeds recorded -$0.18 instead of
+$0.82 — a $1.00/contract inversion that propagated into a bogus -$0.90
settlement attribution row.

``_repair_stale_proceeds_for_market`` (hooked into ``_index_fill``) recomputes
each trusted fill's proceeds under the now-complete market fill set whenever a
new fill lands, so late-arriving priors self-repair.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ledger():
    import merid.event_venues.kalshi.fills_ledger as mod
    # TEST-ISOLATION: redirect DB writes away from production before init.
    fd, db_path = tempfile.mkstemp(suffix="_test_fills.db")
    os.close(fd)
    os.environ["MERID_FILLS_DB_PATH"] = db_path
    mod.KalshiFillsLedger._initialized = False
    mod.KalshiFillsLedger._instance = None
    return mod.KalshiFillsLedger(), mod


def _insert(ledger, fill):
    ledger._fills[fill.fill_id] = fill
    ledger._index_fill(fill)


def _eth_entry(mod, ticker):
    """Entry reported in execution form: sell YES @ $0.28 (acquires NO @ $0.72)."""
    return mod.KalshiFill(
        fill_id="eth_entry_f",
        order_id="eth_entry_o",
        market_ticker=ticker,
        action="sell",
        side="yes",
        count_fp=Decimal("1"),
        quantity_cc=100,
        yes_price_dollars=Decimal("0.28"),
        no_price_dollars=Decimal("0.72"),
        fee_cost=Decimal("0.0047"),
        proceeds_dollars=Decimal("-0.7247"),
        created_time=datetime(2026, 10, 9, 14, 40, 54, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 10, 9, 14, 42, 49, tzinfo=timezone.utc),
        canonical_position_side="yes",
        canonical_position_action="sell",
        canonical_leg_price_cents=28,
        canonical_yes_delta_cc=-100,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_exit=False,
    )


def _eth_exit(mod, ticker):
    """Reduce-only exit: buy YES @ $0.17 execution form = sell NO @ $0.83.

    At ingest the entry was not yet present, so proceeds were booked as a
    fresh mint: -yes_price - fee = -0.18.  Correct value is +no_price - fee.
    """
    return mod.KalshiFill(
        fill_id="eth_exit_f",
        order_id="eth_exit_o",
        market_ticker=ticker,
        action="buy",
        side="yes",
        count_fp=Decimal("1"),
        quantity_cc=100,
        yes_price_dollars=Decimal("0.17"),
        no_price_dollars=Decimal("0.83"),
        fee_cost=Decimal("0.0102"),
        proceeds_dollars=Decimal("-0.1802"),
        created_time=datetime(2026, 10, 9, 14, 41, 41, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 10, 9, 14, 41, 43, tzinfo=timezone.utc),
        canonical_position_side="yes",
        canonical_position_action="buy",
        canonical_leg_price_cents=17,
        canonical_yes_delta_cc=100,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_exit=True,
        reduce_only=True,
    )


class TestLateArrivingPriorFillRepairsProceeds(unittest.TestCase):
    """ETH 2026-10-09 reproduction: exit ingested 1.4s post-trade, entry +115s."""

    def test_exit_proceeds_repaired_when_entry_arrives_late(self):
        ledger, mod = _ledger()
        ticker = "KXETH15M-26OCT091045-45"

        # Ingestion order: exit lands first (fast lane), entry arrives 68s later.
        _insert(ledger, _eth_exit(mod, ticker))
        _insert(ledger, _eth_entry(mod, ticker))

        exit_fill = ledger._fills["eth_exit_f"]
        entry_fill = ledger._fills["eth_entry_f"]

        # Exit was a covered close: +no_price * count - fee = +0.83 - 0.0102.
        self.assertAlmostEqual(float(exit_fill.proceeds_dollars), 0.8198, places=4)
        # Entry stays a mint payment: -no_price - fee.
        self.assertAlmostEqual(float(entry_fill.proceeds_dollars), -0.7247, places=4)
        # Audit trail preserved in raw_payload.
        self.assertEqual(
            (exit_fill.raw_payload or {}).get("proceeds_repaired_reason"),
            "late_prior_fill_arrival",
        )

    def test_repair_is_idempotent(self):
        ledger, mod = _ledger()
        ticker = "KXETH15M-26OCT091045-45"
        _insert(ledger, _eth_exit(mod, ticker))
        _insert(ledger, _eth_entry(mod, ticker))
        once = ledger._fills["eth_exit_f"].proceeds_dollars

        # A third fill arriving for the market must not re-invert anything.
        again = ledger._repair_stale_proceeds_for_market(ticker)
        self.assertEqual(again, 0)
        self.assertEqual(ledger._fills["eth_exit_f"].proceeds_dollars, once)

    def test_lifecycle_pnl_reflects_repaired_proceeds(self):
        ledger, mod = _ledger()
        ticker = "KXETH15M-26OCT091045-45"
        _insert(ledger, _eth_exit(mod, ticker))
        _insert(ledger, _eth_entry(mod, ticker))

        closed, open_tail = ledger._replay_market_lifecycle_pnl(ticker)
        # -0.7247 entry + 0.8198 exit = +0.0951 realized.
        self.assertAlmostEqual(float(closed), 0.0951, places=4)
        self.assertAlmostEqual(float(open_tail), 0.0, places=4)


class TestRepairHandlesPartialQuantities(unittest.TestCase):
    def test_partial_cover_repair(self):
        """Exit covers only half the late-arriving entry exposure."""
        ledger, mod = _ledger()
        ticker = "KXSOL15M-PARTIAL-TEST"

        # Entry: buy NO @ 0.40 executed as sell YES @ 0.60 — 2 contracts.
        _insert(ledger, mod.KalshiFill(
            fill_id="sol_exit_f", order_id="sol_exit_o", market_ticker=ticker,
            action="buy", side="yes",
            count_fp=Decimal("1"), quantity_cc=100,
            yes_price_dollars=Decimal("0.30"), no_price_dollars=Decimal("0.70"),
            fee_cost=Decimal("0.01"), proceeds_dollars=Decimal("-0.31"),
            created_time=datetime(2026, 10, 9, 15, 1, 0, tzinfo=timezone.utc),
            ingested_at=datetime(2026, 10, 9, 15, 1, 1, tzinfo=timezone.utc),
            canonical_position_side="yes", canonical_position_action="buy",
            canonical_leg_price_cents=30, canonical_yes_delta_cc=100,
            canonicalization_state="TRUSTED_LIVE_V1", is_exit=True,
        ))
        _insert(ledger, mod.KalshiFill(
            fill_id="sol_entry_f", order_id="sol_entry_o", market_ticker=ticker,
            action="sell", side="yes",
            count_fp=Decimal("2"), quantity_cc=200,
            yes_price_dollars=Decimal("0.60"), no_price_dollars=Decimal("0.40"),
            fee_cost=Decimal("0.02"), proceeds_dollars=Decimal("-0.82"),
            created_time=datetime(2026, 10, 9, 15, 0, 0, tzinfo=timezone.utc),
            ingested_at=datetime(2026, 10, 9, 15, 2, 0, tzinfo=timezone.utc),
            canonical_position_side="yes", canonical_position_action="sell",
            canonical_leg_price_cents=60, canonical_yes_delta_cc=-200,
            canonicalization_state="TRUSTED_LIVE_V1",
        ))

        exit_fill = ledger._fills["sol_exit_f"]
        # Prior: -200cc (long 2 NO).  Buy YES @0.30 covers 100cc at no_price 0.70.
        # +0.70 * 1 - 0.01 = +0.69.
        self.assertAlmostEqual(float(exit_fill.proceeds_dollars), 0.69, places=4)


class TestRepairLeavesCorrectRowsAlone(unittest.TestCase):
    def test_in_order_normal_fills_untouched(self):
        """Fills whose proceeds were already right must not be rewritten."""
        ledger, mod = _ledger()
        ticker = "KXBTC15M-NORMAL-TEST"
        t0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

        # Entry: buy YES @ 0.55 for 1 contract.
        _insert(ledger, mod.KalshiFill(
            fill_id="b_entry", order_id="b_o1", market_ticker=ticker,
            action="buy", side="yes",
            count_fp=Decimal("1"), quantity_cc=100,
            yes_price_dollars=Decimal("0.55"), no_price_dollars=Decimal("0.45"),
            fee_cost=Decimal("0.01"), proceeds_dollars=Decimal("-0.56"),
            created_time=t0, ingested_at=t0,
            canonical_position_side="yes", canonical_position_action="buy",
            canonical_leg_price_cents=55, canonical_yes_delta_cc=100,
            canonicalization_state="TRUSTED_LIVE_V1",
        ))
        # Exit: sell YES @ 0.70 — covered credit +0.70 - fee.
        _insert(ledger, mod.KalshiFill(
            fill_id="b_exit", order_id="b_o2", market_ticker=ticker,
            action="sell", side="yes",
            count_fp=Decimal("1"), quantity_cc=100,
            yes_price_dollars=Decimal("0.70"), no_price_dollars=Decimal("0.30"),
            fee_cost=Decimal("0.01"), proceeds_dollars=Decimal("0.69"),
            created_time=t0 + timedelta(seconds=30),
            ingested_at=t0 + timedelta(seconds=30),
            canonical_position_side="yes", canonical_position_action="sell",
            canonical_leg_price_cents=70, canonical_yes_delta_cc=-100,
            canonicalization_state="TRUSTED_LIVE_V1", is_exit=True,
        ))

        self.assertEqual(ledger._repair_stale_proceeds_for_market(ticker), 0)
        self.assertAlmostEqual(float(ledger._fills["b_entry"].proceeds_dollars), -0.56, places=4)
        self.assertAlmostEqual(float(ledger._fills["b_exit"].proceeds_dollars), 0.69, places=4)

    def test_untrusted_fill_skipped(self):
        ledger, mod = _ledger()
        ticker = "KXBTC15M-UNTRUSTED-TEST"
        _insert(ledger, mod.KalshiFill(
            fill_id="u_f", order_id="u_o", market_ticker=ticker,
            action="buy", side="yes",
            count_fp=Decimal("1"), quantity_cc=100,
            yes_price_dollars=Decimal("0.50"), no_price_dollars=Decimal("0.50"),
            fee_cost=Decimal("0.01"), proceeds_dollars=Decimal("-9.99"),
            created_time=datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc),
            canonical_position_side="yes", canonical_position_action="buy",
            canonical_leg_price_cents=50, canonical_yes_delta_cc=100,
            canonicalization_state="UNTRUSTED_SIDE_CONFLICT", unmatched=True,
        ))
        self.assertEqual(ledger._repair_stale_proceeds_for_market(ticker), 0)
        self.assertEqual(ledger._fills["u_f"].proceeds_dollars, Decimal("-9.99"))


if __name__ == "__main__":
    unittest.main()

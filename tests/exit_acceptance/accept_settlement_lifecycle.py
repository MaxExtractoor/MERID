"""Bounded settlement-lifecycle fixture (2026-10-17).

Exercises the settlement reconciler across the five lifecycles required to
establish (or refute) exchange-count semantics:

  1. fully_closed_xrp     KXXRP15M-26OCT171530-30 â€” paired nonzero counts on a
                          fully closed lifecycle (the incident payload)
  2. winning_residual     local YES residual held to a YES settlement
  3. losing_residual      local YES residual held to a NO settlement
                          (revenue=0 despite a HELD position â€” proves
                          revenue=0 alone cannot prove flatness)
  4. partial_close        local residual smaller than the entry leg
  5. close_and_reopen     flat leg then a new entry in the same market

Assertions cover reconciliation_status, local_history_complete,
exchange_counts_interpretation, exchange_count_semantics, and
cash_reconciliation (fee cross-check + revenue-vs-local-residual payout).

Exchange counts remain PRESERVED OBSERVATIONS; this fixture pins the
interpretation contract, it does not promote counts to a residual calculator.
"""
import os
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("PYTEST_CURRENT_TEST", "settlement_lifecycle")

import merid.event_venues.kalshi.fills_ledger as _fl_mod
from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlement, KalshiSettlementPoller, _settlement_result_fields,
)

SETTLED_TS = "2026-10-17T19:30:01.825148Z"


class _StubLedger:
    """Minimal ledger: residual, round-trip PnL, and fee total per market."""

    def __init__(self, residual_cc=None, pnl_dollars=None, fee_dollars=None):
        self._resid = residual_cc
        self._pnl = pnl_dollars
        self._fee = fee_dollars

    def get_market_residual_yes_cc(self, ticker, asof_ts=None):
        return self._resid

    def get_market_round_trip_pnl_dollars(self, ticker, outcome):
        return self._pnl

    def get_settlement_pnl_dollars(self, ticker, outcome):
        return self._pnl

    def get_market_fee_total_dollars(self, ticker, asof_ts=None):
        return self._fee


_poller = KalshiSettlementPoller.__new__(KalshiSettlementPoller)


def _api_item(ticker, y, n, result, revenue, fee_usd, yes_cost="0", no_cost="0"):
    return {
        "market_id": ticker, "ticker": ticker,
        "yes_count_fp": y, "no_count_fp": n,
        "market_result": result, "revenue": revenue, "value": 0 if result == "no" else 100,
        "fee_cost": fee_usd, "settled_time": SETTLED_TS,
        "yes_total_cost_dollars": yes_cost, "no_total_cost_dollars": no_cost,
    }


def _grade(item, ledger):
    s = KalshiSettlement.from_api(item)
    _fl_mod.get_fills_ledger = lambda: ledger
    s = _poller._hydrate_pnl_from_ledger(s)
    fields = _settlement_result_fields(s)
    s = replace(s, **fields[6])
    return s, fields


results = []

# â”€â”€ 1. Fully closed (the XRP incident payload, verbatim economics) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXXRP15M-26OCT171530-30", "3.00", "3.00", "no", 0, "0.069500",
              yes_cost="2.610000", no_cost="0.960000"),
    _StubLedger(residual_cc=0, pnl_dollars=Decimal("1.58"),
                fee_dollars=Decimal("0.0695")),
)
print(f"1 closed   : recon={s.reconciliation_status} interp={s.exchange_counts_interpretation} "
      f"cash={s.cash_reconciliation} hist={s.local_history_complete} "
      f"residual={s.local_residual_at_settlement}")
assert s.reconciliation_status == "paired_counts_observed", s.reconciliation_status
assert s.exchange_counts_interpretation == "paired_counts_observed"
assert s.exchange_count_semantics == "not_universally_established"
assert s.local_history_complete is True
assert s.local_residual_at_settlement == 0
assert s.cash_reconciliation == "matched"
results.append("1 fully-closed paired-counts -> paired_counts_observed/matched")

# â”€â”€ 2. Winning residual â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-WIN-45", "3.00", "0", "yes", 300, "0.0350"),
    _StubLedger(residual_cc=300, pnl_dollars=Decimal("1.90"),
                fee_dollars=Decimal("0.035")),
)
print(f"2 win-res  : recon={s.reconciliation_status} interp={s.exchange_counts_interpretation} "
      f"cash={s.cash_reconciliation} result={f[2]}")
assert s.reconciliation_status == "matched_exposure", s.reconciliation_status
assert s.exchange_counts_interpretation == "single_side_yes"
assert s.cash_reconciliation == "matched"  # revenue 300Â¢ == residual 300cc
assert f[2] == "WIN"  # position_result
results.append("2 winning-residual -> matched_exposure/WIN/matched")

# â”€â”€ 3. Losing residual â€” revenue=0 on a HELD position â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-LOSE-45", "3.00", "0", "no", 0, "0.0350"),
    _StubLedger(residual_cc=300, pnl_dollars=Decimal("-1.10"),
                fee_dollars=Decimal("0.035")),
)
print(f"3 lose-res : recon={s.reconciliation_status} cash={s.cash_reconciliation} result={f[2]}")
assert s.reconciliation_status == "matched_exposure", s.reconciliation_status
assert s.cash_reconciliation == "matched"  # revenue=0 consistent w/ losing residual
assert s.local_residual_at_settlement == 300  # HELD â€” revenue=0 proved nothing
assert f[2] == "LOSS"
results.append("3 losing-residual revenue=0 -> matched_exposure/LOSS/matched")

# â”€â”€ 4. Partially closed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-PART-45", "1.50", "0", "yes", 150, "0.0200"),
    _StubLedger(residual_cc=150, pnl_dollars=Decimal("0.80"),
                fee_dollars=Decimal("0.020")),
)
print(f"4 partial  : recon={s.reconciliation_status} cash={s.cash_reconciliation} result={f[2]}")
assert s.reconciliation_status == "matched_exposure", s.reconciliation_status
assert s.cash_reconciliation == "matched"
results.append("4 partial-close -> matched_exposure/matched")

# â”€â”€ 5. Close-and-reopen (flat leg, then new entry same market) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-REOP-45", "0", "2.00", "no", 200, "0.0140"),
    _StubLedger(residual_cc=-200, pnl_dollars=Decimal("0.90"),
                fee_dollars=Decimal("0.014")),
)
print(f"5 reopen   : recon={s.reconciliation_status} cash={s.cash_reconciliation} result={f[2]}")
assert s.reconciliation_status == "matched_exposure", s.reconciliation_status
assert s.exchange_counts_interpretation == "single_side_no"
assert s.cash_reconciliation == "matched"
assert f[2] == "WIN"
results.append("5 close-and-reopen -> matched_exposure/WIN/matched")

# â”€â”€ Negative: local held but all exchange counts zero = impossible â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-BAD-45", "0", "0", "yes", 0, "0"),
    _StubLedger(residual_cc=300, pnl_dollars=Decimal("2.0"),
                fee_dollars=Decimal("0")),
)
print(f"6 held/flat: recon={s.reconciliation_status}")
assert s.reconciliation_status == "held_vs_exchange_flat", s.reconciliation_status
results.append("6 held-vs-all-zero-counts -> held_vs_exchange_flat")

# â”€â”€ Negative: missing settlement_time = timing ambiguity, not counts â”€â”€â”€â”€â”€â”€â”€â”€
item = _api_item("KXBTC15M-T-NOTS-45", "3.00", "0", "yes", 300, "0.0350")
item["settled_time"] = None
s, f = _grade(item, _StubLedger(residual_cc=300, pnl_dollars=Decimal("1"),
                                fee_dollars=Decimal("0.035")))
print(f"7 no-settle: recon={s.reconciliation_status}")
assert s.reconciliation_status == "boundary_unavailable", s.reconciliation_status
assert s.exchange_counts_interpretation == "single_side_yes"  # counts still classified
results.append("7 missing settlement_time -> boundary_unavailable (timing only)")

# â”€â”€ Negative: fee divergence surfaces as cash mismatch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(
    _api_item("KXBTC15M-T-FEE-45", "3.00", "0", "yes", 300, "0.0999"),
    _StubLedger(residual_cc=300, pnl_dollars=Decimal("1"),
                fee_dollars=Decimal("0.035")),
)
print(f"8 fee-diff : recon={s.reconciliation_status} cash={s.cash_reconciliation}")
assert s.cash_reconciliation == "mismatch"
results.append("8 fee divergence -> cash_reconciliation=mismatch")

# â”€â”€ Negative: no local history -> incomplete, cash n/a â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
s, f = _grade(_api_item("KXBTC15M-T-NOHIST-45", "0", "0", "yes", 0, "0"),
              _StubLedger())
print(f"9 no-hist  : recon={s.reconciliation_status} cash={s.cash_reconciliation} "
      f"hist={s.local_history_complete}")
assert s.reconciliation_status == "local_history_incomplete"
assert s.local_history_complete is False
assert s.cash_reconciliation == "not_applicable"
results.append("9 no local history -> local_history_incomplete/n-a")

print("\nSETTLEMENT LIFECYCLE FIXTURE: ALL CHECKS PASSED")
for r in results:
    print(f"  {r}")


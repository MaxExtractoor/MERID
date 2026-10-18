"""Min-proceeds floor enforcement across all four exit representations.

Held-NO entry at 32c => fee-adjusted breakeven floor ~= 36c held-side.
Assertions per user spec:
  - final approved price obeys the economic floor AFTER conversion
  - held-equivalent proceeds net of the clamp satisfy the floor
  - emergency-class reasons are exempt (may submit below the floor)
  - a floor above 99c rejects (hold), never submits below it
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("PYTEST_CURRENT_TEST", "floor_payload")  # quarantine decision writes
os.environ["MERID_EXIT_STATE_PATH"] = str(
    Path(__file__).resolve().parents[2] / "data" / "_test_exit_state_nonexistent.json"
)

from merid.event_venues.kalshi.execution_risk_firewall import (
    BookDepth, ExecutionRiskFirewall, PositionSnapshot,
)
from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent

TICKER = "KXXRP15M-TESTFL-30"
ENTRY = 32
FLOOR_APPROX = 36  # 32 + ~1.5c entry fee + ~1.5c exit fee at ~33c


def mk_intent(contract, action, limit, reason="take_profit", **auth):
    return CanonicalOrderIntent(
        market_ticker=TICKER,
        contract=contract,
        action=action,
        purpose="close",
        qty_cc=300,
        limit_cents=limit,
        strategy_signal="up",
        expected_position_before=0,
        expected_position_after=0,
        expected_realized_pnl_cents=None,
        reason=reason,
        intent_id=f"intent_{contract}_{action}_{limit}_{reason}",
        reduce_only=True,
        time_in_force="ioc",
        **auth,
    )


def mk_pos(position_cc, side):
    return PositionSnapshot(
        position_cc=position_cc, side=side, avg_price_cents=ENTRY,
        version="t1", snapshot_age_ms=0, parent_entry_fill_id="f_entry",
    )


def mk_fw(pos, book):
    fw = ExecutionRiskFirewall()
    fw._decisions.clear()
    async def _fp(t): return pos
    fw._fetch_position = _fp
    fw._fetch_book = lambda c: book
    fw._market_active_and_before_deadline = lambda t: True
    fw._has_in_flight_exit = lambda c: None
    return fw


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


results = []

# -- Case 1: close NO, held-side form: sell no @ 33 (floor ~36) -------------
# Book: no_bids [(33,10)] -> sell vwap 33 < floor -> clamp to ~36
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=33, available_qty_cc=1000,
           levels=[(33, 1000)], best_bid_cents=33, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=33))
d = run(fw.validate_exit(mk_intent("no", "sell", 33)))
print("sell-no  :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert d.approved_limit_cents >= FLOOR_APPROX - 1  # sell: min held-side price
held_proceeds = d.approved_limit_cents
assert held_proceeds >= 35  # never below fee-adjusted floor
results.append(("close-NO held-side sell", d.approved_limit_cents))

# -- Case 2: close NO, complementary form: buy yes @ 67 ---------------------
# held proceeds = 100 - 67 = 33 < floor -> clamp limit DOWN to ~64
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=67, available_qty_cc=1000,
           levels=[(67, 1000)], best_bid_cents=None, best_ask_cents=67,
           book_age_ms=10, book_sequence=1, marginal_price_cents=67))
d = run(fw.validate_exit(mk_intent("yes", "buy", 67)))
print("buy-yes  :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert d.approved_limit_cents <= 100 - 35  # YES buy max = 100 - floor
assert 100 - d.approved_limit_cents >= 35
results.append(("close-NO complementary buy-YES", d.approved_limit_cents))

# -- Case 3: close YES, held-side form: sell yes @ 33 -----------------------
fw = mk_fw(mk_pos(300, "yes"), BookDepth(vwap_cents=33, available_qty_cc=1000,
           levels=[(33, 1000)], best_bid_cents=33, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=33))
d = run(fw.validate_exit(mk_intent("yes", "sell", 33)))
print("sell-yes :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert d.approved_limit_cents >= FLOOR_APPROX - 1
results.append(("close-YES held-side sell", d.approved_limit_cents))

# -- Case 4: close YES, complementary form: buy no @ 67 ---------------------
fw = mk_fw(mk_pos(300, "yes"), BookDepth(vwap_cents=67, available_qty_cc=1000,
           levels=[(67, 1000)], best_bid_cents=None, best_ask_cents=67,
           book_age_ms=10, book_sequence=1, marginal_price_cents=67))
d = run(fw.validate_exit(mk_intent("no", "buy", 67)))
print("buy-no   :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert d.approved_limit_cents <= 100 - 35
assert 100 - d.approved_limit_cents >= 35
results.append(("close-YES complementary buy-NO", d.approved_limit_cents))

# -- Case 5: bare reason="hard_stop" is NOT authorization -------------------
# Free-text reason must not exempt a below-floor exit â€” the structured
# fields are required.  Expected: clamped to the ~36c floor.
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=13, available_qty_cc=1000,
           levels=[(13, 1000)], best_bid_cents=13, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=13))
d = run(fw.validate_exit(mk_intent("no", "sell", 13, reason="hard_stop")))
print("bare-stop:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"reason-text 'hard_stop' must not authorize below-floor: {d.approved_limit_cents}")
results.append(("bare reason=hard_stop -> floored", d.approved_limit_cents))

# -- Case 5b: structured emergency authorization IS exempt -----------------
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=13, available_qty_cc=1000,
           levels=[(13, 1000)], best_bid_cents=13, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=13))
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
    authorization_source="position_monitor",
    position_generation_id="f_entry",
)))
print("struct   :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents == 13
results.append(("structured emergency exempt", d.approved_limit_cents))

# -- Case 5c: incomplete structured auth (no source) -> denied -------------
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=13, available_qty_cc=1000,
           levels=[(13, 1000)], best_bid_cents=13, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=13))
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
)))
print("no-source:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"missing authorization_source must deny exemption: {d.approved_limit_cents}")
results.append(("no-source emergency -> floored", d.approved_limit_cents))

# -- Case 5d: generation mismatch -> denied --------------------------------
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=13, available_qty_cc=1000,
           levels=[(13, 1000)], best_bid_cents=13, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=13))
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
    authorization_source="position_monitor",
    position_generation_id="f_OTHER_position",
)))
print("gen-mism :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"generation-mismatched authorization must deny: {d.approved_limit_cents}")
results.append(("gen-mismatch emergency -> floored", d.approved_limit_cents))

# -- Case 6: look-alike discretionary reason must NOT get the exemption -----
fw = mk_fw(mk_pos(-300, "no"), BookDepth(vwap_cents=33, available_qty_cc=1000,
           levels=[(33, 1000)], best_bid_cents=33, best_ask_cents=None,
           book_age_ms=10, book_sequence=1, marginal_price_cents=33))
d = run(fw.validate_exit(mk_intent("no", "sell", 33, reason="counterparty_risk_review")))
print("lookalike:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1
results.append(("counterparty_risk_review clamped", d.approved_limit_cents))

# -- Case 7: unattainable floor (entry 99 -> floor>99) -> reject-as-hold ----
# NB: a >99c floor implies entry>=99 so any ordinary exit is below water and
# adverse_pnl (step 9) may reject first â€” either rejection is correct hold
# semantics; the floor check is the defensive backstop.
fw = mk_fw(PositionSnapshot(position_cc=-300, side="no", avg_price_cents=99,
           version="t1", snapshot_age_ms=0, parent_entry_fill_id="f_entry"), BookDepth(vwap_cents=97,
           available_qty_cc=1000, levels=[(97, 1000)], best_bid_cents=97,
           best_ask_cents=None, book_age_ms=10, book_sequence=1, marginal_price_cents=97))
d = run(fw.validate_exit(mk_intent("no", "sell", 97)))
print("unattain :", d.status, d.reason)
assert d.status == "rejected" and (
    "min_proceeds_unattainable" in d.reason or "adverse_pnl" in d.reason
), d.reason
results.append(("floor>99 reject-as-hold", d.reason))

# -- Case 8/9: generation-scoped trail lock â€” archived state must not leak --
# Gen A: ARCHIVED record, locked floor 75c.
# Gen B: live position (different entry_fill_id) with breakeven floor ~36c.
from merid.position_management import position_exit_state as _pes


def _seed_store(records):
    """Point the singleton store at a fresh file holding `records`."""
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    Path(p).write_text(json.dumps(
        {"schema_version": 1, "records": records}), encoding="utf-8")
    os.environ["MERID_EXIT_STATE_PATH"] = p
    _pes._store = _pes.PositionExitStateStore(Path(p))
    return p


def _mk_rec(gen, held, floor, archived):
    return {
        "position_key": f"{TICKER}|{gen}",
        "generation_id": gen,
        "market_id": TICKER,
        "held_outcome": held,
        "ratchet_floor_price_cents": floor,
        "archived": archived,
        "state_version": 3,
        "updated_at": 1000.0 if archived else 2000.0,
    }


# Seed: Gen A archived @75c lock; Gen B live @55c lock (a real persisted lock).
_seed_store({
    f"{TICKER}|gen_A": _mk_rec("gen_A", "no", 75, True),
    f"{TICKER}|gen_B": _mk_rec("gen_B", "no", 55, False),
})

# Case 8: B's exit (parent gen_B) must clamp to B's 55c lock, NOT A's 75c.
fw = mk_fw(PositionSnapshot(position_cc=-300, side="no", avg_price_cents=ENTRY,
           version="t1", snapshot_age_ms=0, parent_entry_fill_id="gen_B"),
           BookDepth(vwap_cents=33, available_qty_cc=1000, levels=[(33, 1000)],
           best_bid_cents=33, best_ask_cents=None, book_age_ms=10,
           book_sequence=1, marginal_price_cents=33))
d = run(fw.validate_exit(mk_intent("no", "sell", 33)))
print("gen-B    :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert d.approved_limit_cents == 55, (
    f"Gen B must inherit its own 55c lock, not A's 75c; got "
    f"{d.approved_limit_cents}")
results.append(("gen-B gets own 55c lock", d.approved_limit_cents))

# Case 9: B's record must still be retrievable (not shadowed by archived A).
rec = _pes._store.find_record(TICKER, generation_id="gen_B",
                              held_outcome="no", require_generation=True)
assert rec is not None and rec["ratchet_floor_price_cents"] == 55
results.append(("gen-B record survives archived-A lookup", 55))

# Case 10: exit for a position with NO persisted record (generationless or
# unknown gen) must fall back to the breakeven floor â€” never to A's 75c.
fw = mk_fw(PositionSnapshot(position_cc=-300, side="no", avg_price_cents=ENTRY,
           version="t1", snapshot_age_ms=0, parent_entry_fill_id="gen_C_norec"),
           BookDepth(vwap_cents=33, available_qty_cc=1000, levels=[(33, 1000)],
           best_bid_cents=33, best_ask_cents=None, book_age_ms=10,
           book_sequence=1, marginal_price_cents=33))
d = run(fw.validate_exit(mk_intent("no", "sell", 33)))
print("gen-C    :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved", d.reason
assert FLOOR_APPROX - 1 <= d.approved_limit_cents < 55, (
    f"Unknown generation must get breakeven floor ~36, got "
    f"{d.approved_limit_cents}")
results.append(("unknown-gen -> breakeven floor", d.approved_limit_cents))

# ============================================================================
# NEGATIVE AUTHORIZATION TESTS (2026-10-17)
# Classification is not authorization.  Each case below supplies a
# plausible-looking request and must receive NO below-floor privilege
# (clamped to the ~36c floor, not the submitted 13c).
# ============================================================================
def _book13():
    return BookDepth(vwap_cents=13, available_qty_cc=1000,
                     levels=[(13, 1000)], best_bid_cents=13,
                     best_ask_cents=None, book_age_ms=10, book_sequence=1,
                     marginal_price_cents=13)


# -- N1: ordinary producer self-manufactures a complete emergency tuple ------
# source=market_maker_15m is not an issuer for POSITION_LOSS_BUDGET.
fw = mk_fw(mk_pos(-300, "no"), _book13())
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
    authorization_source="market_maker_15m",
    position_generation_id="f_entry",
)))
print("N1 self-tuple:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"ordinary producer self-manufactured tuple must be denied: "
    f"{d.approved_limit_cents}")
results.append(("N1 ordinary-producer emergency tuple -> floored",
                d.approved_limit_cents))

# -- N2: reason-derived classification grants no privilege -------------------
# normalize_order classifies (exit_class/emergency_type derived from reason)
# but the derived tuple must not authorize â€” issuer scope still applies.
from merid.event_venues.kalshi.order_intent_contract import normalize_order
from merid.event_venues.kalshi.order_router import OrderIntent

_raw = OrderIntent(
    ticker=TICKER, price_cents=13, count=3.0, side="no", action="sell",
    time_in_force="ioc", source="market_maker_15m",
    entry_or_exit="exit", reduce_only=True, exit_reason="loss_cap",
    reason="loss_cap", parent_entry_fill_id="f_entry",
    parentage_status="CANONICAL_FILL",
)
_c = normalize_order(_raw, exchange_position_cc=-300,
                     position_avg_price_cents=ENTRY, position_side="no")
assert _c.exit_class == "emergency" and _c.emergency_type == "POSITION_LOSS_BUDGET", (
    f"classification should still derive: {_c.exit_class}/{_c.emergency_type}")
assert _c.authorization_source == "market_maker_15m"
fw = mk_fw(mk_pos(-300, "no"), _book13())
d = run(fw.validate_exit(_c, _raw))
print("N2 derived  :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"reason-derived emergency class must not grant privilege: "
    f"{d.approved_limit_cents}")
results.append(("N2 derived class, unauthorized issuer -> floored",
                d.approved_limit_cents))

# -- N3: authorized issuer, emergency type outside its scope -----------------
fw = mk_fw(mk_pos(-300, "no"), _book13())
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="ACCOUNT_LOSS_BUDGET",
    authorization_source="position_monitor",
    position_generation_id="f_entry",
)))
print("N3 out-scope:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"out-of-scope emergency type must be denied: {d.approved_limit_cents}")
results.append(("N3 authorized issuer + out-of-scope type -> floored",
                d.approved_limit_cents))

# -- N4: missing-parent exception + below-floor without loss authority -------
# UNKNOWN parentage may be *tolerated* operationally, but tolerance is not
# loss authority: gen cannot bind to a missing generation -> floored.
fw = mk_fw(PositionSnapshot(position_cc=-300, side="no", avg_price_cents=ENTRY,
           version="t1", snapshot_age_ms=0, parent_entry_fill_id=None),
           _book13())
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="expiry_liquidation",
    exit_class="operational",
    authorization_source="position_monitor",
    parentage_status="UNKNOWN",
)))
print("N4 no-parent:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"missing-parent below-floor without loss authority must be denied: "
    f"{d.approved_limit_cents}")
results.append(("N4 missing-parent below-floor -> floored",
                d.approved_limit_cents))

# -- N4b: both-generations-empty is NOT generation consistency ---------------
# Same position (no resolvable generation) but the intent supplies a full
# emergency tuple except the generation itself.  Empty-vs-empty must not
# satisfy the binding.
fw = mk_fw(PositionSnapshot(position_cc=-300, side="no", avg_price_cents=ENTRY,
           version="t1", snapshot_age_ms=0, parent_entry_fill_id=None),
           _book13())
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="loss_cap",
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
    authorization_source="position_monitor",
    parentage_status="UNKNOWN",
)))
print("N4b empty-gen:", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"empty-vs-empty generation must not satisfy consistency: "
    f"{d.approved_limit_cents}")
results.append(("N4b empty-vs-empty generation -> floored",
                d.approved_limit_cents))

# -- N5: shadowed/degraded stop path cannot mint emergency authority ---------
# The degraded producer is a fallback construction path; it retains
# operational (parentage) tolerance but is absent from every loss-type
# issuer set.
fw = mk_fw(mk_pos(-300, "no"), _book13())
d = run(fw.validate_exit(mk_intent(
    "no", "sell", 13, reason="hard_stop",
    exit_class="operational", emergency_type="GENERIC_EMERGENCY",
    authorization_source="stop_candidate_degraded",
    position_generation_id="f_entry",
)))
print("N5 degraded :", d.status, d.reason, "limit=", d.approved_limit_cents)
assert d.status == "approved" and d.approved_limit_cents >= FLOOR_APPROX - 1, (
    f"degraded stop path must not acquire emergency authority: "
    f"{d.approved_limit_cents}")
results.append(("N5 degraded-path emergency -> floored", d.approved_limit_cents))

print("\nFLOOR PAYLOAD MATRIX: ALL CHECKS PASSED")
for name, lim in results:
    print(f"  {name}: limit={lim}")


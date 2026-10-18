"""Acceptance gate for the position-owned exit arbiter.

Deterministic fixture â€” no live orders. Covers:

  1. Higher executable liquidation value ratchets the same generation's floor.
  2. Stale / wrong-side quotes cannot ratchet it.
  3. A profit proposal cannot silently become a loss-taking order.
  4. An authorized emergency can override the floor (exception recorded).
  5. Competing proposals produce only one active attempt per generation.
  6. Partial fills preserve protection for the remaining quantity.
  7. Unknown submission outcomes reconcile before replacement.
  8. Restart neither erases the lock nor duplicates an unresolved attempt.
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="arbiter_test_"))
os.environ["MERID_EXIT_STATE_PATH"] = str(_TMP / "exit_state.json")
os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(_TMP / "exit_attempts.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.exit_arbiter import (  # noqa: E402
    AttemptState, ArbiterResult, ExitArbiter, ExitAttemptStore, ExitBook,
    ExitProposal, ProposalKind, ReconcileEvidence,
)
from merid.position_management.position_exit_state import (  # noqa: E402
    PositionExitStateStore,
)
from merid.event_venues.kalshi.exit_authorization import (  # noqa: E402
    register_producer,
)

PASS = []
TICKER = "KXXRP15M-ARB-30"
GEN = "fill_entry_001"
BE_FLOOR = 36   # entry 32c + round-trip fees â‰ˆ 36c breakeven


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def fresh_arbiter(state_path=None, att_path=None):
    ss = PositionExitStateStore(state_path) if state_path else \
        PositionExitStateStore()
    ats = ExitAttemptStore(att_path) if att_path else ExitAttemptStore()
    return ExitArbiter(state_store=ss, attempt_store=ats)


def prop(kind, pid, limit, qty=300, **kw):
    # Match production: approve_intent attaches a registered producer token
    # for the producing module; emergency authorization requires it.
    issuer = kw.get("producer_issuer") or kw.get("authorization_source")
    if issuer and "producer_token" not in kw:
        kw["producer_token"] = register_producer(issuer)
        kw.setdefault("producer_issuer", issuer)
    return ExitProposal(kind=kind, proposal_id=pid, limit_cents=limit,
                        qty_cc=qty, reason="test", **kw)


# ---------------------------------------------------------------- 1: ratchet
print("== 1. executable book ratchets same-generation floor ==")
arb = fresh_arbiter()
r = arb.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=55, qty_cc=500, age_ms=50),
    proposals=[prop("profit_lock", "pl1", 40)],
)
check("ratcheted floor above breakeven", r.floor_cents == 55,
      f"floor={r.floor_cents}")
check("floor_source=ratcheted", r.floor_source == "ratcheted")
check("selected clamped to ratcheted floor",
      r.submitted_limit_cents == 55, f"limit={r.submitted_limit_cents}")

# persisted across calls â€” a lower book cannot lower it
r2 = arb.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=40, qty_cc=500, age_ms=50),
    proposals=[],
)
check("floor never decreases", r2.floor_cents == 55, f"floor={r2.floor_cents}")

# explicit increase sequence on a fresh generation: 45 -> 55 -> stays 55
sp = _TMP / "s1b_state.json"; ap = _TMP / "s1b_att.json"
arb1b = fresh_arbiter(sp, ap)
rA = arb1b.arbitrate(
    market_id=TICKER, generation_id="gen1b", held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=45, qty_cc=500, age_ms=10),
    proposals=[],
)
rB = arb1b.arbitrate(
    market_id=TICKER, generation_id="gen1b", held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=55, qty_cc=500, age_ms=10),
    proposals=[],
)
rC = arb1b.arbitrate(
    market_id=TICKER, generation_id="gen1b", held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=48, qty_cc=500, age_ms=10),
    proposals=[],
)
check("ratchet 45 -> 55 -> stays 55",
      (rA.floor_cents, rB.floor_cents, rC.floor_cents) == (45, 55, 55),
      f"{rA.floor_cents},{rB.floor_cents},{rC.floor_cents}")
check("watermark tracked 55", rC.high_watermark_cents == 55)

# watermark observation vs giveback formula: giveback 10 -> floor = hw-10
sp = _TMP / "s1c_state.json"; ap = _TMP / "s1c_att.json"
arb1c = fresh_arbiter(sp, ap)
rD = arb1c.arbitrate(
    market_id=TICKER, generation_id="gen1c", held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, trail_giveback_cents=10,
    book=ExitBook(held_side="no", liquidation_cents=70, qty_cc=500, age_ms=10),
    proposals=[],
)
check("giveback splits watermark from floor",
      rD.high_watermark_cents == 70 and rD.floor_cents == 60,
      f"hw={rD.high_watermark_cents} floor={rD.floor_cents}")

# ------------------------------------------------------- 2: stale/wrong-side
print("== 2. stale / wrong-side quotes cannot ratchet ==")
sp = _TMP / "s2_state.json"; ap = _TMP / "s2_att.json"
arb2 = fresh_arbiter(sp, ap)
r = arb2.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=80, qty_cc=500,
                  age_ms=60_000),
    proposals=[],
)
check("stale book cannot ratchet", r.floor_cents == BE_FLOOR and
      "book_stale" in (r.book_note or ""), r.book_note)
r = arb2.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="yes", liquidation_cents=90, qty_cc=500,
                  age_ms=10),
    proposals=[],
)
check("wrong-side book cannot ratchet", r.floor_cents == BE_FLOOR and
      "book_side_mismatch" in (r.book_note or ""), r.book_note)
r = arb2.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=70, qty_cc=0, age_ms=10),
    proposals=[],
)
check("empty-depth book cannot ratchet", r.floor_cents == BE_FLOOR)

# -------------------------------------------------- 3: profit cannot take loss
print("== 3. profit proposal cannot silently become loss-taking ==")
sp = _TMP / "s3_state.json"; ap = _TMP / "s3_att.json"
arb3 = fresh_arbiter(sp, ap)
r = arb3.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("model_exit", "me1", 20)],   # below floor
)
check("below-floor profit clamped to floor",
      r.status == "submitted" and r.submitted_limit_cents == BE_FLOOR,
      f"limit={r.submitted_limit_cents}")
check("no exception recorded for ordinary clamp", r.exception is None)

# ----------------------------------------------------- 4: authorized emergency
print("== 4. authorized emergency overrides floor, exception recorded ==")
sp = _TMP / "s4_state.json"; ap = _TMP / "s4_att.json"
arb4 = fresh_arbiter(sp, ap)
emg = prop("emergency", "emg1", 13,
           authorization_source="position_monitor",
           emergency_type="POSITION_LOSS_BUDGET",
           position_generation_id=GEN)
r = arb4.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[emg, prop("profit_lock", "pl2", 60)],
)
check("emergency selected over higher protective proposal",
      r.selected is not None and r.selected.proposal_id == "emg1")
check("emergency below-floor bound preserved",
      r.submitted_limit_cents == 13)
check("emergency economics recorded distinctly",
      r.trigger_value_cents == 13 and r.min_acceptable_cents == 13,
      f"trigger={r.trigger_value_cents} min={r.min_acceptable_cents}")
check("exception recorded",
      r.exception == "emergency:POSITION_LOSS_BUDGET", r.exception)
check("loser recorded with reason",
      any(pid == "pl2" for pid, _ in r.not_selected), str(r.not_selected))

# unauthorized emergency WITHOUT ordinary fallback -> rejected entirely
sp = _TMP / "s4b_state.json"; ap = _TMP / "s4b_att.json"
arb4b = fresh_arbiter(sp, ap)
r = arb4b.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("emergency", "emg_bad", 13)],
)
check("unauthorized emergency rejected (no implicit ordinary exit)",
      r.status == "rejected" and r.attempt is None,
      f"status={r.status}")
check("denial recorded",
      any(pid == "emg_bad" for pid, _ in r.denied_exceptions),
      str(r.denied_exceptions))
check("rejection reason carries denial",
      any("emergency_denied" in w for _, w in r.not_selected),
      str(r.not_selected))

# denied emergency WITH explicit ordinary fallback -> evaluates as ordinary
sp = _TMP / "s4c_state.json"; ap = _TMP / "s4c_att.json"
arb4c = fresh_arbiter(sp, ap)
r = arb4c.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("emergency", "emg_fb", 13, fallback_kind="model_exit")],
)
check("explicit fallback evaluates as ordinary (floored)",
      r.status == "submitted" and r.submitted_limit_cents == BE_FLOOR and
      r.exception is None, f"limit={r.submitted_limit_cents}")
check("denial still recorded alongside fallback",
      any(pid == "emg_fb" for pid, _ in r.denied_exceptions))

# --------------------------------------------- 5: one active attempt per gen
print("== 5. competing proposals -> single attempt ==")
sp = _TMP / "s5_state.json"; ap = _TMP / "s5_att.json"
arb5 = fresh_arbiter(sp, ap)
r = arb5.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("profit_lock", "pl", 50),
               prop("trailing_profit", "tp", 55),
               prop("model_exit", "me", 45)],
)
check("exactly one submitted", r.status == "submitted" and
      r.attempt is not None and r.attempt.state == AttemptState.SUBMITTING)
check("highest locked value wins", r.selected.proposal_id == "tp",
      r.selected.proposal_id)
check("both losers recorded", len(r.not_selected) == 2, str(r.not_selected))
# second call while in-flight: no second attempt
r2 = arb5.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("profit_lock", "pl_b", 60)],
)
check("in-flight suppresses new attempt", r2.status == "in_flight" and
      r2.attempt.attempt_id == r.attempt.attempt_id)
check("in-flight reason recorded",
      all("attempt_in_flight" in why for _, why in r2.not_selected))

# -------------------------------------- 6: partial fill preserves protection
print("== 6. partial fills preserve protection for residual ==")
a = arb5.record_fill(f"{TICKER}|{GEN}", 100)
check("partial keeps attempt working",
      a.state == AttemptState.WORKING_OR_PARTIALLY_FILLED and
      a.filled_cc == 100, f"state={a.state} filled={a.filled_cc}")
# floor still applies to the residual 200cc
r = arb5.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=200,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=62, qty_cc=500, age_ms=10),
    proposals=[prop("model_exit", "me2", 10)],
)
check("residual still floor-protected (no replacement while working)",
      r.status in ("in_flight", "reconcile_required") and
      r.attempt.attempt_id == a.attempt_id)
check("floor ratcheted for residual", r.floor_cents == 62,
      f"floor={r.floor_cents}")
# covering fill -> FLAT
a = arb5.record_fill(f"{TICKER}|{GEN}", 200)
check("covering fill -> FLAT", a.state == AttemptState.FLAT)
# after flat, next decision may arbitrate fresh
r = arb5.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=0,
    breakeven_floor_cents=BE_FLOOR, proposals=[],
)
check("flat position", r.status == "flat")

# ----------------------------------- 7: unknown outcome reconciles before retry
print("== 7. unknown submission reconciled before replacement ==")
sp = _TMP / "s7_state.json"; ap = _TMP / "s7_att.json"
arb7 = fresh_arbiter(sp, ap)
r = arb7.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, proposals=[prop("model_exit", "me", 40)],
)
pk = f"{TICKER}|{GEN}"
arb7.mark_ack_unknown(pk)
check("lost ack -> ACK_UNKNOWN",
      arb7._attempts.get_active(pk).state == AttemptState.ACK_UNKNOWN)
r2 = arb7.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, proposals=[prop("model_exit", "me2", 40)],
)
check("no replacement while ack unknown", r2.status == "reconcile_required")
# reconcile: order confirmed dead -> RETRY_ELIGIBLE -> fresh attempt allowed
a = arb7.begin_reconcile(pk)
check("begin_reconcile -> RECONCILING", a.state == AttemptState.RECONCILING)
a = arb7.resolve_reconcile(pk, ReconcileEvidence(
    order_found=True, terminal=True, filled_cc=0, source="order_id"))
check("dead order -> RETRY_ELIGIBLE", a.state == AttemptState.RETRY_ELIGIBLE)
r3 = arb7.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, proposals=[prop("model_exit", "me3", 40)],
)
check("retry submits new attempt", r3.status == "submitted" and
      r3.attempt.attempt_id != r.attempt.attempt_id,
      r3.attempt.attempt_id)
# alive-but-unfilled -> stays working, still no replacement
a = arb7.resolve_reconcile(pk, ReconcileEvidence(
    order_found=True, terminal=False, filled_cc=0, source="order_id"))
check("alive order -> back to WORKING",
      a.state == AttemptState.WORKING_OR_PARTIALLY_FILLED)

# inconclusive lookup is NOT proof of death - stays unresolved
sp = _TMP / "s7b_state.json"; ap = _TMP / "s7b_att.json"
arb7b = fresh_arbiter(sp, ap)
arb7b.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, proposals=[prop("model_exit", "me", 40)],
)
pk7b = f"{TICKER}|{GEN}"
arb7b.bind_attempt_identity(pk7b, "coid_7b")
arb7b.mark_ack_unknown(pk7b)
arb7b.begin_reconcile(pk7b)
a = arb7b.resolve_reconcile(pk7b, ReconcileEvidence(
    order_found=False, terminal=False, source="order_id"))
check("inconclusive lookup stays unresolved",
      a.state == AttemptState.RECONCILING, a.state.value)
# but a never-transmitted attempt (no coid) IS provably dead
sp = _TMP / "s7c_state.json"; ap = _TMP / "s7c_att.json"
arb7c = fresh_arbiter(sp, ap)
arb7c.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR, proposals=[prop("model_exit", "me", 40)],
)
pk7c = f"{TICKER}|{GEN}"
arb7c.begin_reconcile(pk7c)
a = arb7c.resolve_reconcile(pk7c, ReconcileEvidence(
    order_found=False, terminal=False, source="local_no_transmit"))
check("never-transmitted attempt -> RETRY_ELIGIBLE",
      a.state == AttemptState.RETRY_ELIGIBLE, a.state.value)

# ------------------------------------------- 8: restart preserves, not resubmit
print("== 8. restart: lock kept, unresolved attempt reconciled ==")
sp = _TMP / "s8_state.json"; ap = _TMP / "s8_att.json"
arb8 = fresh_arbiter(sp, ap)
r = arb8.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=58, qty_cc=500, age_ms=10),
    proposals=[prop("profit_lock", "pl", 58)],
)
aid = r.attempt.attempt_id
# simulate restart: fresh stores over same files
arb8b = fresh_arbiter(sp, ap)
a = arb8b._attempts.get_active(f"{TICKER}|{GEN}")
check("restart downgrades SUBMITTING -> RECONCILING",
      a is not None and a.state == AttemptState.RECONCILING,
      a.state.value if a else "none")
r2 = arb8b.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    proposals=[prop("model_exit", "me", 40)],
)
check("restart does not duplicate attempt",
      r2.status == "reconcile_required" and
      r2.attempt.attempt_id == aid)
check("restart keeps ratcheted lock", r2.floor_cents == 58,
      f"floor={r2.floor_cents}")
check("positions_requiring_reconcile lists it",
      f"{TICKER}|{GEN}" in arb8b.positions_requiring_reconcile())

# floor_unattainable sanity
sp = _TMP / "s9_state.json"; ap = _TMP / "s9_att.json"
arb9 = fresh_arbiter(sp, ap)
r = arb9.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=100,   # floor exceeds contract max
    proposals=[prop("model_exit", "me", 40)],
)
check("floor>99 rejects (hold rather than lose)",
      r.status == "rejected" and r.attempt is None and
      any("floor_unattainable" in w for _, w in r.not_selected),
      str(r.not_selected))

# unmarketable proposals cannot defeat executable exits
sp = _TMP / "s10_state.json"; ap = _TMP / "s10_att.json"
arb10 = fresh_arbiter(sp, ap)
r = arb10.arbitrate(
    market_id=TICKER, generation_id=GEN, held_side="no", remaining_cc=300,
    breakeven_floor_cents=BE_FLOOR,
    book=ExitBook(held_side="no", liquidation_cents=55, qty_cc=500, age_ms=10),
    proposals=[prop("profit_lock", "pl_hi", 60),   # unmarketable: 60 > book 55
               prop("model_exit", "me_lo", 45)],   # marketable
)
check("unmarketable limit cannot beat executable exit",
      r.selected is not None and r.selected.proposal_id == "me_lo",
      r.selected.proposal_id if r.selected else "none")
check("economics recorded distinctly",
      r.trigger_value_cents == 45 and r.executable_value_cents == 55 and
      r.min_acceptable_cents == 55 and r.submitted_limit_cents == 55,
      f"t={r.trigger_value_cents} x={r.executable_value_cents} "
      f"min={r.min_acceptable_cents} s={r.submitted_limit_cents}")
check("unmarketable recorded",
      any("unmarketable" in w for _, w in r.not_selected),
      str(r.not_selected))

# ------------------------------------------------------------------- summary
fails = [n for n, ok in PASS if not ok]
print(f"\nEXIT ARBITER MATRIX: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)


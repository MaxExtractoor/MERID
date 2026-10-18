"""Exit-attempt fault-injection replay â€” crashes INSIDE side-effect events.

Each boundary simulates a crash between two durable effects, then restarts
(fresh stores on the same files) and asserts the invariant:

  no duplicate approved exposure reduction | no lost fill |
  no inflated remaining quantity | no lowered lock | no unauthorized
  exception

Boundaries:
 B1 attempt persisted -> before HTTP submission
 B2 request accepted remotely -> before ack reaches process
 B3 ack received -> before order_id persisted
 B4 fill persisted -> before attempt state updated
 B5 attempt terminal -> before position state updated
 B6 trail floor persisted -> before next attempt created
Delivery pathologies:
 P1 duplicate fill delivery (same fill_id twice)
 P2 out-of-order events (fill arrives before ack)
 P3 late ack after reconcile already started
 P4 partial-fill IOC + cancel (terminal partial)
 P5 two concurrent arbitrations, one generation
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="exit_fault_"))
ES = _TMP / "es.json"
EA = _TMP / "ea.json"
os.environ["MERID_EXIT_STATE_PATH"] = str(ES)
os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(EA)
os.environ["MERID_EXIT_ARBITER_REQUIRED"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.exit_arbiter import (        # noqa: E402
    ExitArbiter, ExitAttemptStore, ExitBook, ExitProposal,
    ProposalKind, ReconcileEvidence,
)
from merid.position_management.position_exit_state import (  # noqa: E402
    PositionExitStateStore,
)

T = "KXSOL15M-FAULT-30"
PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def arbiter():
    a = ExitArbiter(state_store=PositionExitStateStore(),
                    attempt_store=ExitAttemptStore())
    import merid.position_management.exit_arbiter as m
    m._ARBITER = a
    return a


def key(gen):
    return f"{T}|{gen}"


def book(px, age=0, qty=1000):
    return ExitBook(held_side="no", liquidation_cents=px,
                    qty_cc=qty, age_ms=age)


def propose(a, gen, limit=60, giveback=None, reason="lock"):
    return a.arbitrate(
        market_id=T, generation_id=gen, held_side="no",
        remaining_cc=300, breakeven_floor_cents=35,
        trail_giveback_cents=giveback, book=book(limit),
        proposals=[ExitProposal(
            kind=ProposalKind.PROFIT_LOCK.value,
            proposal_id=f"p_{gen}", limit_cents=limit, qty_cc=300,
            reason=reason, authorization_source="position_monitor")])


def attempt(a, gen):
    return a.attempt_store.get_active(key(gen))


print("== B1 crash: attempt persisted, before HTTP submission ==")
a = arbiter()
r = propose(a, "b1")
check("attempt persisted as SUBMITTING",
      r.status == "submitted" and
      attempt(a, "b1").state.value == "SUBMITTING")
a2 = arbiter()   # restart
att = attempt(a2, "b1")
check("restart -> RECONCILING (never resubmit)",
      att is not None and att.state.value == "RECONCILING",
      att.state.value if att else "none")
r2 = propose(a2, "b1")
check("no duplicate attempt while reconciling",
      r2.status == "reconcile_required" and
      r2.attempt.attempt_id == att.attempt_id, r2.status)

print("== B2 crash: accepted remotely, ack never reached process ==")
a = arbiter()
propose(a, "b2")
a.mark_ack_unknown(key("b2"), note="ack_lost_in_transit")
a2 = arbiter()
att = attempt(a2, "b2")
check("unresolved outcome survives restart",
      att is not None and att.state.value == "RECONCILING")
r2 = propose(a2, "b2")
check("unknown outcome -> no replacement",
      r2.status == "reconcile_required", r2.status)
# exchange lookup: order found, terminal, zero fills -> confirmed dead
a2.begin_reconcile(key("b2"))
a2.resolve_reconcile(key("b2"), ReconcileEvidence(
    order_found=True, terminal=True, filled_cc=0,
    source="exchange_order_lookup"))
check("confirmed dead -> RETRY_ELIGIBLE",
      attempt(a2, "b2").state.value == "RETRY_ELIGIBLE")

print("== B3 crash: ack received, before order_id persisted ==")
a = arbiter()
propose(a, "b3")
a.bind_attempt_identity(key("b3"), client_order_id="coid_b3")
# ack lands; order_id write never happens
a.mark_acked(key("b3"))
a2 = arbiter()
att = attempt(a2, "b3")
check("working order restores with client_order_id lineage",
      att is not None and att.state.value == "RECONCILING"
      and att.client_order_id == "coid_b3",
      f"state={att.state.value} coid={att.client_order_id}")
# client-id discovery finds it: found, still active -> keep tracking
a2.resolve_reconcile(key("b3"), ReconcileEvidence(
    order_found=True, terminal=False, filled_cc=0,
    source="client_order_id_lookup"))
check("still-active order -> back to WORKING (no replacement)",
      attempt(a2, "b3").state.value == "WORKING_OR_PARTIALLY_FILLED")
r2 = propose(a2, "b3")
check("no replacement while order works",
      r2.status in ("in_flight", "reconcile_required"), r2.status)

print("== B4 crash: fill persisted, before attempt state updated ==")
a = arbiter()
propose(a, "b4")
a.mark_acked(key("b4"))
# fills ledger records 300cc; crash before attempt update -> restart
a2 = arbiter()
att = attempt(a2, "b4")
check("attempt unaware of landed fill after restart",
      att is not None and att.state.value == "RECONCILING"
      and att.filled_cc == 0, f"filled={att.filled_cc}")
a2.resolve_reconcile(key("b4"), ReconcileEvidence(
    order_found=True, terminal=True, filled_cc=300,
    source="exchange_order_lookup"))
check("no lost fill: exchange truth flattens attempt",
      attempt(a2, "b4") is None,   # FLAT attempts are cleared to history
      "active cleared on FLAT")

print("== B5 crash: attempt terminal, before position state updated ==")
a = arbiter()
propose(a, "b5")
a.record_fill(key("b5"), 300, fill_id="f_b5")
check("covering fill -> attempt FLAT (cleared to history)",
      attempt(a, "b5") is None)
a2 = arbiter()
# position state was never updated: exchange/ledger recon marks flat
r2 = propose(a2, "b5")
check("fresh generation decision permitted after flat",
      r2.status == "submitted", r2.status)

print("== B6 crash: trail floor persisted, before next attempt ==")
a = arbiter()
propose(a, "b6", limit=60, giveback=15)   # floor 45 persisted + giveback 15
a.mark_flat(key("b6"))
a2 = arbiter()
# giveback not restated by caller -> persisted 15 applies; book@50 -> 50>=45
r2 = a2.arbitrate(market_id=T, generation_id="b6", held_side="no",
                  remaining_cc=300, breakeven_floor_cents=35,
                  book=book(50),
                  proposals=[ExitProposal(
                      kind=ProposalKind.TRAILING_PROFIT.value,
                      proposal_id="t_b6", limit_cents=46, qty_cc=300,
                      reason="trail",
                      authorization_source="position_monitor")])
check("lock survived restart; giveback persisted, not tightened",
      r2.status == "submitted" and r2.floor_cents == 45
      and r2.submitted_limit_cents == 46,
      f"floor={r2.floor_cents} sub={r2.submitted_limit_cents}")

print("== P1 duplicate fill delivery ==")
a = arbiter()
propose(a, "p1")
a.mark_acked(key("p1"))
a.record_fill(key("p1"), 100, fill_id="fill_x")
a.record_fill(key("p1"), 100, fill_id="fill_x")   # duplicate delivery
att = attempt(a, "p1")
check("duplicate fill_id ignored (no inflated fill count)",
      att is not None and att.filled_cc == 100,
      f"filled={att.filled_cc} ids={att.fill_ids}")

print("== P2 out-of-order: fill lands before ack ==")
a = arbiter()
propose(a, "p2")
a.record_fill(key("p2"), 100, fill_id="fill_ooo")  # fill first
a.mark_acked(key("p2"))                            # ack second
att = attempt(a, "p2")
check("out-of-order converges to working partial",
      att is not None and att.filled_cc == 100 and
      att.state.value == "WORKING_OR_PARTIALLY_FILLED",
      f"{att.state.value} {att.filled_cc}")

print("== P3 late ack after reconcile began ==")
a = arbiter()
propose(a, "p3")
a.mark_ack_unknown(key("p3"))
a.begin_reconcile(key("p3"))
a.mark_acked(key("p3"))     # late ack lands mid-reconcile
att = attempt(a, "p3")
check("late ack revives attempt -> WORKING",
      att is not None and att.state.value == "WORKING_OR_PARTIALLY_FILLED",
      att.state.value if att else "none")

print("== P4 partial-fill IOC then cancel ==")
a = arbiter()
propose(a, "p4")
a.mark_acked(key("p4"))
a.record_fill(key("p4"), 100, fill_id="fill_ioc")
# IOC cancels the residual -> terminal partial -> RETRY_ELIGIBLE, not flat
a.begin_reconcile(key("p4"))
a.resolve_reconcile(key("p4"), ReconcileEvidence(
    order_found=True, terminal=True, filled_cc=100,
    source="exchange_order_lookup"))
att = attempt(a, "p4")
check("terminal partial -> RETRY_ELIGIBLE for 200cc residual",
      att is not None and att.state.value == "RETRY_ELIGIBLE"
      and att.filled_cc == 100, f"{att.state.value} {att.filled_cc}")
r2 = a.arbitrate(market_id=T, generation_id="p4", held_side="no",
                 remaining_cc=200, breakeven_floor_cents=35,
                 book=book(58),
                 proposals=[ExitProposal(
                     kind=ProposalKind.MODEL_EXIT.value,
                     proposal_id="m_p4", limit_cents=58, qty_cc=200,
                     reason="model", authorization_source="model_exit")])
check("residual below the 60c lock is held (no lowered lock)",
      r2.status == "held_unmarketable", r2.status)
r3 = a.arbitrate(market_id=T, generation_id="p4", held_side="no",
                 remaining_cc=200, breakeven_floor_cents=35,
                 book=book(60),
                 proposals=[ExitProposal(
                     kind=ProposalKind.MODEL_EXIT.value,
                     proposal_id="m_p4b", limit_cents=60, qty_cc=200,
                     reason="model", authorization_source="model_exit")])
check("residual exit at the lock, recomputed qty",
      r3.status == "submitted" and r3.effective_qty_cc == 200,
      f"{r3.status} qty={r3.effective_qty_cc}")

print("== P5 two concurrent arbitrations, same generation ==")
a = arbiter()
results = []
barrier = threading.Barrier(2)


def _t():
    barrier.wait()
    results.append(propose(a, "p5"))


t1, t2 = threading.Thread(target=_t), threading.Thread(target=_t)
t1.start(); t2.start(); t1.join(); t2.join()
subs = [r for r in results if r.status == "submitted"]
blocked = [r for r in results if r.status in ("in_flight",
                                             "reconcile_required")]
check("atomic reservation: exactly one submission",
      len(subs) == 1 and len(blocked) == 1,
      f"sub={len(subs)} blocked={len(blocked)}")
check("single attempt minted",
      attempt(a, "p5").attempt_id.endswith("#1"))

fails = [n for n, ok in PASS if not ok]
print(f"\nFAULT MATRIX: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)


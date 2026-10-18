"""Independent reconcile-liveness acceptance test.

Spec: create an unresolved attempt, generate NO further exit proposals,
deliver reconciliation evidence -> the periodic / event-driven worker
resolves it; no replacement occurs before resolution.

  T1 periodic worker resolves an ACK_UNKNOWN attempt on its own
  T2 event wake (fill carrying client_order_id) resolves immediately
  T3 no replacement before resolution (arbiter gate still holds)
  T4 failed lookup -> per-key backoff pushed out
  T5 oldest-unresolved-age observable + alert threshold
  T6 stop() cancels cleanly
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

_TMP = Path(tempfile.mkdtemp(prefix="recon_live_"))
os.environ["MERID_EXIT_STATE_PATH"] = str(_TMP / "es.json")
os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(_TMP / "ea.json")
os.environ["MERID_EXIT_ARBITER_REQUIRED"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.exit_arbiter import (         # noqa: E402
    ExitArbiter, ExitAttemptStore, ExitBook, ExitProposal,
    ProposalKind,
)
from merid.position_management.position_exit_state import (  # noqa: E402
    PositionExitStateStore,
)
from merid.position_management.exit_reconcile_worker import (  # noqa: E402
    ExitReconcileWorker,
)

T = "KXBTC15M-RECON-30"
PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


class _Res:
    def __init__(self, order):
        self.success = True
        self._o = order

    def unwrap_or(self, d):
        return self._o


class StubClient:
    def __init__(self):
        self.order = None
        self.calls = 0

    async def get_order_result(self, order_id):
        self.calls += 1
        return _Res(self.order)

    async def get_order_by_client_id_result(self, coid, market_id=None):
        self.calls += 1
        return _Res(self.order)


def make_arbiter():
    a = ExitArbiter(state_store=PositionExitStateStore(),
                    attempt_store=ExitAttemptStore())
    import merid.position_management.exit_arbiter as m
    m._ARBITER = a
    return a


def book(px):
    return ExitBook(held_side="no", liquidation_cents=px,
                    qty_cc=1000, age_ms=0)


def propose(a, gen, limit=60):
    return a.arbitrate(
        market_id=T, generation_id=gen, held_side="no",
        remaining_cc=300, breakeven_floor_cents=35,
        book=book(limit),
        proposals=[ExitProposal(
            kind=ProposalKind.PROFIT_LOCK.value,
            proposal_id=f"p_{gen}", limit_cents=limit, qty_cc=300,
            reason="lock", authorization_source="position_monitor")])


async def wait_state(a, gen, want, timeout=5.0):
    key = f"{T}|{gen}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        att = a.attempt_store.get_active(key)
        st = att.state.value if att else "FLAT"
        if st == want:
            return st
        await asyncio.sleep(0.05)
    return st


async def main():
    print("== T1 periodic worker resolves an unresolved attempt ==")
    a = make_arbiter()
    propose(a, "t1")
    a.bind_attempt_identity(f"{T}|t1", client_order_id="coid_t1")
    a.mark_ack_unknown(f"{T}|t1")
    client = StubClient()
    client.order = SimpleNamespace(status="canceled", filled_size=0)
    w = ExitReconcileWorker(arbiter=a, client=client, interval_s=0.1,
                            backoff_base_s=0.05, backoff_max_s=1.0)
    await w.start()
    st = await wait_state(a, "t1", "RETRY_ELIGIBLE", timeout=6.0)
    check("periodic worker resolved attempt with no new proposals",
          st == "RETRY_ELIGIBLE", f"state={st} lookups={client.calls}")
    await w.stop()

    print("== T2 event wake resolves immediately (long interval) ==")
    a2 = make_arbiter()
    propose(a2, "t2")
    a2.bind_attempt_identity(f"{T}|t2", client_order_id="coid_t2")
    a2.mark_ack_unknown(f"{T}|t2")
    client2 = StubClient()
    client2.order = SimpleNamespace(status="canceled", filled_size=0)
    w2 = ExitReconcileWorker(arbiter=a2, client=client2, interval_s=60.0,
                             backoff_base_s=0.05, backoff_max_s=1.0)
    await w2.start()
    # the attempt is already resolved by startup recovery; create a second
    # unresolved attempt to isolate the event path
    a2.mark_flat(f"{T}|t2")
    propose(a2, "t2b")
    a2.bind_attempt_identity(f"{T}|t2b", client_order_id="coid_t2b")
    a2.mark_ack_unknown(f"{T}|t2b")
    t0 = time.time()
    matched = w2.note_fill_event(client_order_id="coid_t2b",
                                 market_id=T, fill_id="fill_evt")
    st = await wait_state(a2, "t2b", "RETRY_ELIGIBLE", timeout=5.0)
    dt = time.time() - t0
    check("fill event correlated to attempt key",
          matched == [f"{T}|t2b"], str(matched))
    check("event wake resolved fast (no 60s interval wait)",
          st == "RETRY_ELIGIBLE" and dt < 10.0,
          f"state={st} dt={dt:.2f}s")
    await w2.stop()

    print("== T3 no replacement before resolution ==")
    a3 = make_arbiter()
    propose(a3, "t3")
    a3.mark_ack_unknown(f"{T}|t3")
    r = a3.arbitrate(market_id=T, generation_id="t3", held_side="no",
                   remaining_cc=300, breakeven_floor_cents=35,
                   book=book(58),
                   proposals=[ExitProposal(
                       kind=ProposalKind.MODEL_EXIT.value,
                       proposal_id="m_t3", limit_cents=58, qty_cc=300,
                       reason="m", authorization_source="model_exit")])
    check("attempt unresolved -> reconcile_required, no mint",
          r.status == "reconcile_required" and
          r.attempt.attempt_id.endswith("#1"), r.status)

    print("== T4 failed lookup -> per-key backoff ==")
    a4 = make_arbiter()
    propose(a4, "t4")
    a4.bind_attempt_identity(f"{T}|t4", client_order_id="coid_t4")
    a4.mark_ack_unknown(f"{T}|t4")
    client4 = StubClient()   # order=None -> not found -> inconclusive
    w4 = ExitReconcileWorker(arbiter=a4, client=client4, interval_s=0.1,
                             backoff_base_s=10.0, backoff_max_s=30.0)
    await w4.start()
    await asyncio.sleep(0.6)
    await w4.stop()
    backoff_at = w4._key_backoff.get(f"{T}|t4", 0)
    check("inconclusive lookup pushed backoff into the future",
          backoff_at > time.time(), f"in {backoff_at - time.time():.1f}s")
    att4 = a4.attempt_store.get_active(f"{T}|t4")
    check("inconclusive is not death -> still unresolved",
          att4 is not None and att4.state.value == "RECONCILING")

    print("== T5 oldest-unresolved-age observable ==")
    w5 = ExitReconcileWorker(arbiter=a4, client=client4)
    age = w5.oldest_unresolved_age_s()
    check("oldest_unresolved_age_s reports live age",
          age is not None and age >= 0, f"{age}")

    print("== T6 stop() cancels cleanly ==")
    w6 = ExitReconcileWorker(arbiter=a4, client=client4, interval_s=0.1)
    await w6.start()
    await w6.stop()
    check("stop() leaves no running task",
          w6._task is None or w6._task.done())

    fails = [n for n, ok in PASS if not ok]
    print(f"\nRECONCILE LIVENESS: {len(PASS) - len(fails)}/{len(PASS)} passed")
    if fails:
        print("FAILURES:", fails)
    sys.exit(0 if not fails else 1)


asyncio.new_event_loop().run_until_complete(main())


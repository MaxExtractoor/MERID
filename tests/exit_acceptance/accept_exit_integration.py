"""Exit-integration acceptance gate â€” 10 enforcing scenarios.

Producer -> ExitArbiter -> enforcing firewall -> approval-bound port ->
captured HTTP (transport stubbed).  No live exposure; this is a
transport-boundary suite.

Each scenario runs under its own position generation â€” durable state is
generation-scoped by design, so cross-scenario keys must not alias.

Scenarios (per spec):
 1  profit lock             producer->arbiter->firewall->captured payload
 2  armed trail retracement persisted floor constrains the final request
 3  shadowed tail-loss stop telemetry only; no authorized attempt
 4  emergency               authorized exception survives binding checks
 5  unauthorized emergency  rejected; no implicit ordinary exit
 6  partial fill            residual reconciled before another decision
 7  lost acknowledgment     no replacement until outcome resolved
 8  restart                 same unresolved attempt restored; no dup
 9  competing producers     one atomic attempt reservation
10  approval mutation       changed economics rejected before transport
"""
import asyncio
import os
import sys
import threading
import tempfile
from decimal import Decimal
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="exit_int_"))
os.environ["MERID_ENV"] = "production"
os.environ["MERID_EXIT_STATE_PATH"] = str(_TMP / "es.json")
os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(_TMP / "ea.json")
os.environ["MERID_EXIT_FIREWALL_OBSERVE_ONLY"] = "0"   # ENFORCING
os.environ["MERID_EXIT_ARBITER_REQUIRED"] = "1"
os.environ.pop("DEBUG_ALLOW_MANUAL_ORDERS", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import merid.position_management.exit_arbiter as EA             # noqa: E402
from merid.position_management.exit_arbiter import (            # noqa: E402
    ExitArbiter, ExitAttemptStore, ExitBook, ExitProposal,
    ProposalKind, ReconcileEvidence,
)
from merid.position_management.position_exit_state import (     # noqa: E402
    PositionExitStateStore,
)
from merid.position_management.exit_pipeline import (           # noqa: E402
    ExitContext, approve_intent,
)
from merid.event_venues.kalshi.order_router import OrderIntent  # noqa: E402
from merid.event_venues.kalshi.order_intent_contract import (   # noqa: E402
    normalize_order,
)
from merid.event_venues.kalshi.execution_risk_firewall import (  # noqa: E402
    BookDepth, ExecutionRiskFirewall, PositionSnapshot,
)
from merid.event_venues.kalshi.venue_client_port import (       # noqa: E402
    KalshiVenueClientExecutionPort,
)
from merid.event_venues.kalshi.port import CreateOrderRequest    # noqa: E402
from merid.event_venues.kalshi.client import (                   # noqa: E402
    KalshiVenueClient, OperationResult,
)
import merid.event_venues.kalshi.client as client_mod            # noqa: E402

from merid.settings import settings                              # noqa: E402
settings.MERID_ENV = "production"

TICKER = "KXXRP15M-INTG-30"
ENTRY = 32

PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def fresh_arbiter():
    a = ExitArbiter(state_store=PositionExitStateStore(),
                    attempt_store=ExitAttemptStore())
    EA._ARBITER = a   # producers + router gate share the singleton
    return a


def ctx(gen, remaining=300, floor=35, giveback=None, book=None):
    return ExitContext(market_id=TICKER, generation_id=gen,
                       held_side="no", remaining_cc=remaining,
                       breakeven_floor_cents=floor,
                       trail_giveback_cents=giveback, book=book)


def book(px, qty=1000, age=0):
    return ExitBook(held_side="no", liquidation_cents=px,
                    qty_cc=qty, age_ms=age)


def intent(gen, **kw):
    d = dict(ticker=TICKER, side="no", action="sell", price_cents=40,
             count=3.0, order_type="limit", mode=None,
             time_in_force="ioc", source="position_monitor_exit",
             entry_or_exit="exit", reduce_only=True,
             exit_reason="take_profit", reason="take_profit",
             parent_entry_fill_id=gen, parentage_status="CANONICAL_FILL",
             exchange_index=2, position_generation_id=gen,
             intent_id="i_intg", client_order_id="coid_intg")
    d.update(kw)
    return OrderIntent(**d)


# ---- transport stub -------------------------------------------------------
class _Capture:
    def __init__(self):
        self.calls = []

    async def __call__(self, method, path, *, params=None, json_data=None,
                       operation_name="", headers=None):
        self.calls.append({"method": method, "path": path,
                           "json_data": json_data})
        return OperationResult.ok({"order": {"order_id": "oid-1"}})


async def _ok_true(t):
    return True, None


def mk_port(gen, book_px=33):
    fw = ExecutionRiskFirewall.get_instance()
    fw._decisions.clear()
    pos = PositionSnapshot(position_cc=-300, side="no",
                           avg_price_cents=ENTRY, version="t",
                           snapshot_age_ms=0, parent_entry_fill_id=gen)

    async def _fp(t):
        return pos
    fw._fetch_position = _fp
    fw._fetch_book = lambda c: BookDepth(
        vwap_cents=book_px, available_qty_cc=1000,
        levels=[(book_px, 1000)],
        best_bid_cents=book_px, best_ask_cents=None, book_age_ms=10,
        book_sequence=1, marginal_price_cents=book_px)
    fw._market_active_and_before_deadline = lambda t: True
    fw._has_in_flight_exit = lambda c: None
    client = KalshiVenueClient.__new__(KalshiVenueClient)
    cap = _Capture()
    client._request_with_resilience = cap
    client_mod._validate_ticker_exists = _ok_true
    return fw, KalshiVenueClientExecutionPort(client=client), cap


def req_for(d, **over):
    kw = dict(ticker=TICKER, side="sell", outcome="no",
              size=Decimal("3.0"), price_cents=d.approved_limit_cents,
              order_type="limit", time_in_force="IOC",
              client_order_id=d.client_order_id, reduce_only=True,
              source="position_monitor_exit", exchange_index=2,
              metadata={"firewall_decision_id": d.decision_id,
                        "entry_or_exit": "exit"})
    kw.update(over)
    return CreateOrderRequest(**kw)


def firewall_path(i, gen, book_px=33):
    can = normalize_order(i, exchange_position_cc=-300,
                          position_avg_price_cents=ENTRY,
                          position_side="no")
    fw, port, cap = mk_port(gen, book_px=book_px)
    return run(fw.validate_exit(can, i)), port, cap


print("== S1 profit lock: producer -> arbiter -> firewall -> wire ==")
G1 = "gen_s1"
a = fresh_arbiter()
i1 = intent(G1, price_cents=60)
prep = approve_intent(i1, ctx(G1, book=book(60)), issuer="position_monitor")
check("arbiter approved profit lock",
      prep.approved and i1.exit_attempt_id == prep.result.attempt.attempt_id,
      prep.result.status)
# book@60 executable -> trail floor locks at 60 (giveback 0)
check("submitted limit = 60, floor locked at executable 60",
      prep.result.submitted_limit_cents == 60
      and prep.result.floor_cents == 60,
      f"sub={prep.result.submitted_limit_cents} floor={prep.result.floor_cents}")
d, port, cap = firewall_path(i1, G1, book_px=60)
check("firewall approved same economics",
      d.status == "approved" and d.approved_limit_cents == 60,
      f"{d.status}@{d.approved_limit_cents} reason={d.reason}")
r = run(port.create_order(req_for(d)))
ok = (r.success and cap.calls and
      int(round(float(cap.calls[0]["json_data"]["price"]) * 100)) == 100 - 60)
check("captured wire carries approved economics", bool(ok),
      cap.calls[0]["json_data"] if cap.calls else f"no call: {r.error}")

print("== S2 armed trail retracement: persisted floor binds request ==")
G2 = "gen_s2"
K2 = f"{TICKER}|{G2}"
a2 = fresh_arbiter()
approve_intent(intent(G2, price_cents=55, client_order_id="t1"),
               ctx(G2, giveback=10, book=book(55)),
               issuer="position_monitor")
a2.mark_flat(K2)
approve_intent(intent(G2, price_cents=55, client_order_id="t2"),
               ctx(G2, giveback=10, book=book(65)),
               issuer="position_monitor")
a2.mark_flat(K2)
# retracement: trail proposes 50 but persisted floor is 65-10=55
prep2 = approve_intent(intent(G2, price_cents=50, client_order_id="t3"),
                       ctx(G2, giveback=10, book=book(56)),
                       issuer="position_monitor")
check("retracement floored to persisted 55",
      prep2.approved and prep2.result.submitted_limit_cents == 55
      and prep2.result.floor_cents == 55,
      f"sub={prep2.result.submitted_limit_cents} "
      f"floor={prep2.result.floor_cents} st={prep2.result.status}")

print("== S3 shadowed tail-loss stop: telemetry only ==")
try:
    from merid.event_venues.kalshi.stop_candidate import (
        price_stop_shadow_enabled, SHADOWED_PRICE_STOP_TRIGGERS,
    )
    shadow_on = price_stop_shadow_enabled()
    check("shadow gate enabled and covers stop triggers",
          shadow_on and "HARD_STOP" in SHADOWED_PRICE_STOP_TRIGGERS
          and "STOP_LOSS" in SHADOWED_PRICE_STOP_TRIGGERS,
          f"on={shadow_on}")
except Exception as e:
    check("shadow gate present", False, str(e))
# A producer honoring the shadow emits telemetry and builds NO proposal.
# Defense-in-depth: if a shadowed reason still reached the arbiter with no
# emergency tuple, it is rejected outright (emergency-class reason, no
# authorization) â€” never an implicit ordinary loss order.
G3 = "gen_s3"
K3 = f"{TICKER}|{G3}"
a3 = fresh_arbiter()
prep3 = approve_intent(
    intent(G3, price_cents=13, exit_reason="hard_stop",
           reason="hard_stop", authorization_source=None,
           source="unclassified_agent", agent_id="unclassified_agent"),
    ctx(G3, book=book(30)), issuer="unclassified_agent")
check("leaked stop w/o authorization rejected, no attempt",
      not prep3.approved
      and a3.attempt_store.get_active(K3) is None,
      f"st={prep3.result.status} exc={prep3.result.exception}")

print("== S4 authorized emergency: exception survives binding ==")
G4 = "gen_s4"
a4 = fresh_arbiter()
i4 = intent(G4, price_cents=13, exit_reason="loss_cap", reason="loss_cap",
            exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
            authorization_source="position_monitor")
prep4 = approve_intent(i4, ctx(G4, book=book(30)),
                       issuer="position_monitor")
check("emergency approved below floor with exception",
      prep4.approved and prep4.result.submitted_limit_cents == 13
      and prep4.result.exception is not None,
      f"exc={prep4.result.exception} sub={prep4.result.submitted_limit_cents}")
d4, port4, cap4 = firewall_path(i4, G4)
check("firewall revalidates emergency",
      d4.status == "approved" and d4.emergency is True
      and d4.approved_limit_cents == 13, f"{d4.status}@{d4.approved_limit_cents}")
r4 = run(port4.create_order(req_for(d4)))
check("wire carries 13c", r4.success and cap4.calls and
      int(round(float(cap4.calls[0]["json_data"]["price"]) * 100)) == 87,
      cap4.calls[0]["json_data"] if cap4.calls else f"no call: {r4.error}")

print("== S5 unauthorized emergency: rejected, no downgrade ==")
G5 = "gen_s5"
a5 = fresh_arbiter()
i5 = intent(G5, price_cents=13, exit_reason="loss_cap", reason="loss_cap",
            exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
            authorization_source="model_exit")
prep5 = approve_intent(i5, ctx(G5, book=book(30)),
                       issuer="model_exit")
check("unauthorized emergency rejected (no implicit ordinary exit)",
      not prep5.approved and i5.exit_attempt_id is None,
      f"status={prep5.result.status} denial={prep5.denial}")
check("denial recorded in telemetry",
      bool(prep5.result.denied_exceptions),
      f"denied={prep5.result.denied_exceptions}")

print("== S6 partial fill: residual reconciled before next decision ==")
G6 = "gen_s6"
K6 = f"{TICKER}|{G6}"
a6 = fresh_arbiter()
approve_intent(intent(G6, price_cents=60, client_order_id="p1"),
               ctx(G6, book=book(60)), issuer="position_monitor")
a6.mark_acked(K6)
a6.record_fill(K6, 100, fill_id="f1")   # 100/300 partial
res2 = a6.arbitrate(market_id=TICKER, generation_id=G6, held_side="no",
                    remaining_cc=200, breakeven_floor_cents=35,
                    book=book(55),
                    proposals=[ExitProposal(
                        kind=ProposalKind.MODEL_EXIT.value,
                        proposal_id="m2", limit_cents=55, qty_cc=200,
                        reason="model", authorization_source="model_exit")])
att6 = a6.attempt_store.get_active(K6)
check("partial: in-flight attempt blocks replacement",
      res2.status in ("in_flight", "reconcile_required"), res2.status)
check("partial: one attempt, residual protection intact",
      att6 is not None and att6.filled_cc == 100,
      f"filled={att6.filled_cc if att6 else 'none'}")

print("== S7 lost ack: no replacement until resolved ==")
G7 = "gen_s7"
K7 = f"{TICKER}|{G7}"
a7 = fresh_arbiter()
approve_intent(intent(G7, price_cents=60, client_order_id="l1"),
               ctx(G7, giveback=15, book=book(60)),
               issuer="position_monitor")
a7.mark_ack_unknown(K7, note="lost_ack")
r_lost = a7.arbitrate(market_id=TICKER, generation_id=G7, held_side="no",
                      remaining_cc=300, breakeven_floor_cents=35,
                      book=book(58),
                      proposals=[ExitProposal(
                          kind=ProposalKind.MODEL_EXIT.value,
                          proposal_id="m3", limit_cents=58, qty_cc=300,
                          reason="model", authorization_source="model_exit")])
check("lost ack -> reconcile_required, no replacement",
      r_lost.status == "reconcile_required", r_lost.status)
a7.begin_reconcile(K7)
a7.resolve_reconcile(K7, ReconcileEvidence(
    order_found=True, terminal=True, filled_cc=0,
    source="exchange_order_lookup"))
# giveback not restated -> persisted policy (15) must apply, not 0
r_retry = a7.arbitrate(market_id=TICKER, generation_id=G7, held_side="no",
                       remaining_cc=300, breakeven_floor_cents=35,
                       book=book(58),
                       proposals=[ExitProposal(
                           kind=ProposalKind.MODEL_EXIT.value,
                           proposal_id="m4", limit_cents=58, qty_cc=300,
                           reason="model",
                           authorization_source="model_exit")])
check("terminal zero-fill -> fresh decision permitted",
      r_retry.status == "submitted" and r_retry.attempt is not None,
      f"{r_retry.status} sub={r_retry.submitted_limit_cents}")

print("== S8 restart: unresolved attempt restored, no duplicate ==")
G8 = "gen_s8"
K8 = f"{TICKER}|{G8}"
a8a = fresh_arbiter()
approve_intent(intent(G8, price_cents=60, client_order_id="r1"),
               ctx(G8, giveback=15, book=book(60)),
               issuer="position_monitor")
del a8a   # crash without updating attempt state: stays SUBMITTING on disk
a8 = ExitArbiter(state_store=PositionExitStateStore(),
                 attempt_store=ExitAttemptStore())
att8 = a8.attempt_store.get_active(K8)
check("restart restored attempt as RECONCILING",
      att8 is not None and att8.state.value == "RECONCILING",
      att8.state.value if att8 else "none")
r8 = a8.arbitrate(market_id=TICKER, generation_id=G8, held_side="no",
                  remaining_cc=300, breakeven_floor_cents=35,
                  book=book(58),
                  proposals=[ExitProposal(
                      kind=ProposalKind.MODEL_EXIT.value,
                      proposal_id="m5", limit_cents=58, qty_cc=300,
                      reason="model", authorization_source="model_exit")])
check("restart: no replacement while reconciling",
      r8.status == "reconcile_required"
      and r8.attempt is not None
      and r8.attempt.attempt_id == f"{K8}#1",
      f"{r8.status} attempt={r8.attempt.attempt_id if r8.attempt else None}")

print("== S9 competing producers: one atomic reservation ==")
G9 = "gen_race"
a9 = fresh_arbiter()
outs = []
lock = threading.Lock()


def _race(n):
    r = a9.arbitrate(market_id=TICKER, generation_id=G9,
                     held_side="no", remaining_cc=300,
                     breakeven_floor_cents=35, book=book(60),
                     proposals=[ExitProposal(
                         kind=ProposalKind.PROFIT_LOCK.value,
                         proposal_id=f"race{n}", limit_cents=60,
                         qty_cc=300, reason="lock",
                         authorization_source="position_monitor")])
    with lock:
        outs.append(r)


ts = [threading.Thread(target=_race, args=(n,)) for n in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
submitted = [r for r in outs if r.status == "submitted"]
blocked = [r for r in outs if r.status in ("in_flight", "reconcile_required")]
check("exactly one winner under concurrency",
      len(submitted) == 1 and len(blocked) == 5,
      f"submitted={len(submitted)} blocked={len(blocked)}")

print("== S10 approval mutation: changed economics rejected ==")
# fresh decision: intermediate mk_port calls cleared the decision store
d10, port10, _cap10 = firewall_path(intent(G1, price_cents=60), G1,
                                    book_px=60)
check("baseline approval live for mutation tests",
      d10.status == "approved", f"{d10.status}:{d10.reason}")
bad = run(port10.create_order(req_for(d10, price_cents=30)))
check("mutated price rejected before transport",
      not bad.success and "price_c:" in (bad.error or ""), bad.error)
bad2 = run(port10.create_order(req_for(d10, reduce_only=False)))
check("mutated reduce_only rejected",
      not bad2.success and "reduce_only:" in (bad2.error or ""), bad2.error)
bad3 = run(port10.create_order(req_for(
    d10, metadata={"firewall_decision_id": "forged",
                   "entry_or_exit": "exit"})))
check("forged approval token rejected",
      not bad3.success and "invalid" in (bad3.error or ""), bad3.error)

fails = [n for n, ok in PASS if not ok]
print(f"\nINTEGRATION GATE: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)


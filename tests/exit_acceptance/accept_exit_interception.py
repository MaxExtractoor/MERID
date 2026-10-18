"""Interception test: producers cannot reach the wire without the arbiter.

The router gate inside ``route_order_async`` rejects any exit intent
(``entry_or_exit=="exit"`` or ``reduce_only``) that lacks a live approved
attempt for ``{ticker}|{generation}``.  This test drives the REAL gate with
a stubbed inner implementation (``_route_order_async_impl``) so transport
never runs:

  1. exit intent with no attempt            -> rejected, impl never called
  2. forged/foreign attempt id              -> rejected
  3. approved attempt (approve_intent)      -> passes gate into impl
  4. second approval while attempt in flight-> no second attempt minted
  5. each producer issuer                   -> exactly one attempt per gen
  6. entry intents                          -> gate does not apply
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="intercept_"))
os.environ["MERID_EXIT_STATE_PATH"] = str(_TMP / "es.json")
os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(_TMP / "ea.json")
os.environ["MERID_EXIT_ARBITER_REQUIRED"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.exit_arbiter import (  # noqa: E402
    ExitArbiter, ExitAttemptStore,
)
from merid.position_management.exit_pipeline import (  # noqa: E402
    ExitContext, approve_intent,
)
from merid.position_management.position_exit_state import (  # noqa: E402
    PositionExitStateStore,
)
from merid.event_venues.kalshi.order_router import OrderIntent  # noqa: E402
import merid.event_venues.kalshi.order_router as OR  # noqa: E402

PASS = []
TICKER = "KXETH15M-INT-30"
GEN = "fill_gen_abc"
KEY = f"{TICKER}|{GEN}"


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def make_intent(**kw):
    d = dict(
        ticker=TICKER, side="no", action="sell", price_cents=40,
        count=3.0, order_type="limit", mode=None,
        time_in_force="ioc", source="position_monitor_exit",
        agent_id="pm1", intent_id="intent_x",
        client_order_id="coid_x", entry_or_exit="exit",
        reduce_only=True, exit_reason="take_profit",
        exit_policy_id="pol1", position_generation_id=GEN,
    )
    d.update(kw)
    return OrderIntent(**d)


def arb():
    return ExitArbiter(state_store=PositionExitStateStore(),
                       attempt_store=ExitAttemptStore())


# Stub the inner implementation â€” the gate is the real code under test.
IMPL_CALLS = []


class _R:
    """Result stub tolerant of post-impl attribute access."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


async def fake_impl(intent):
    IMPL_CALLS.append(intent)
    return _R(status="submitted", mode=None, reason="stub_impl",
              submission_attempted=True, has_execution=True,
              executed_quantity_cc=0, fill={},
              client_order_id=intent.client_order_id)


OR._route_order_async_impl = fake_impl


def ctx(remaining=300):
    return ExitContext(market_id=TICKER, generation_id=GEN, held_side="no",
                       remaining_cc=remaining, breakeven_floor_cents=36)


print("== interception: the router gate is the submission boundary ==")
a = arb()
# Production has one arbiter per process; the gate resolves the singleton.
# Inject the test instance so approve + gate share one attempt store.
import merid.position_management.exit_arbiter as _EA  # noqa: E402
_EA._ARBITER = a

# 1. exit intent with no attempt -> gate rejects, impl never called
r = asyncio.run(OR.route_order_async(make_intent()))
check("bare exit intent rejected at gate",
      r.status == "rejected" and
      "exit_arbiter" in (r.reason or ""), r.reason)
check("impl never saw it", len(IMPL_CALLS) == 0)

# 2. forged attempt id -> rejected
r = asyncio.run(OR.route_order_async(
    make_intent(exit_attempt_id=f"{TICKER}|{GEN}#99")))
check("forged attempt id rejected",
      r.status == "rejected" and len(IMPL_CALLS) == 0, r.reason)

# 3. approve via pipeline -> attempt stamped -> gate passes into impl
intent = make_intent(client_order_id="coid_a")
prep = approve_intent(intent, ctx(), issuer="position_monitor", arbiter=a)
check("pipeline approved", prep.approved and
      intent.exit_attempt_id == prep.result.attempt.attempt_id,
      getattr(intent, "exit_attempt_id", None))
r = asyncio.run(OR.route_order_async(intent))
check("approved attempt reaches impl",
      r.status == "submitted" and IMPL_CALLS[-1] is intent,
      f"calls={len(IMPL_CALLS)}")

# 4. second approval while in-flight -> suppressed, no second attempt
prep2 = approve_intent(make_intent(client_order_id="coid_b"), ctx(),
                       issuer="position_monitor", arbiter=a)
check("in-flight suppresses second attempt",
      not prep2.approved and
      prep2.result.status in ("in_flight", "reconcile_required"),
      prep2.result.status)
n = len(IMPL_CALLS)
r = asyncio.run(OR.route_order_async(make_intent()))
check("suppressed intent still rejected at gate",
      r.status == "rejected" and len(IMPL_CALLS) == n, r.reason)

# 5. each producer issuer -> one attempt per generation
for gen, issuer, kind, extra in (
    ("gen_pm", "position_monitor", None, {}),
    ("gen_sc", "stop_candidate", None, {}),
    ("gen_hedge", "hedge_engine", "emergency",
     {"authorization_source": "hedge_engine",
      "emergency_type": "OPERATIONAL_RISK"}),
):
    g_ctx = ExitContext(market_id=TICKER, generation_id=gen, held_side="no",
                        remaining_cc=200, breakeven_floor_cents=30)
    i = make_intent(position_generation_id=gen,
                    client_order_id=f"coid_{gen}", **extra)
    p = approve_intent(i, g_ctx, kind=kind, issuer=issuer, arbiter=a)
    check(f"{issuer}: proposal -> one approved attempt",
          p.approved and p.result.attempt is not None and
          p.result.attempt.attempt_id.endswith("#1"),
          getattr(i, "exit_attempt_id", None))

# 6. entry intents: exit-arbiter gate does NOT apply — but the submit-time
# revalidation gate does. A bare entry with no book/probability must fail
# closed with a submit_* reason, never exit_arbiter:*.
IMPL_CALLS.clear()
r = asyncio.run(OR.route_order_async(make_intent(
    entry_or_exit="entry", reduce_only=None, exit_reason=None,
    client_order_id="coid_entry")))
check("entry intent not exit-gated",
      r.status == "rejected" and len(IMPL_CALLS) == 0
      and not str(r.reason).startswith("exit_arbiter")
      and str(r.reason).startswith("submit_"),
      f"{r.status}:{r.reason}")

# reduce_only alone (no entry_or_exit) is also gated
IMPL_CALLS.clear()
r = asyncio.run(OR.route_order_async(make_intent(
    entry_or_exit=None, reduce_only=True,
    position_generation_id="nope_gen",
    client_order_id="coid_ro")))
check("reduce_only-without-exit-class also gated",
      r.status == "rejected" and len(IMPL_CALLS) == 0, r.reason)

fails = [n for n, ok in PASS if not ok]
print(f"\nINTERCEPTION MATRIX: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)




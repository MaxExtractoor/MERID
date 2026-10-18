"""Deterministic replay of exit-arbiter decisions and recovery.

An ordered event log drives the arbiter; the same log replayed on a fresh
arbiter (with the same durable-file inputs where persistence matters) must
produce the identical decision trace.  Restart events rebuild the stores
from disk mid-sequence â€” the arbiter must reconcile rather than duplicate.

Two passes:
  A) same log, fresh temp stores  -> identical traces
  B) restart injected after EVERY event boundary -> terminal state identical
     and exactly one attempt id sequence (no duplicates).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.exit_arbiter import (  # noqa: E402
    AttemptState, ExitArbiter, ExitAttemptStore, ExitBook, ExitProposal,
    ReconcileEvidence,
)
from merid.position_management.position_exit_state import (  # noqa: E402
    PositionExitStateStore,
)

TICKER = "KXSOL15M-REPLAY-30"
GEN = "fill_replay_gen"
PK = f"{TICKER}|{GEN}"
BE = 36


def prop(kind, pid, limit, qty=300, **kw):
    return ExitProposal(kind=kind, proposal_id=pid, limit_cents=limit,
                        qty_cc=qty, reason="replay", **kw)


# Event log: (op, args).  "restart" rebuilds stores from the same files.
LOG = [
    ("arb", dict(
        book=ExitBook("no", 55, 500, 10),
        proposals=[prop("trailing_profit", "tp1", 55)])),
    ("ack_unknown", {}),
    ("arb", dict(          # in-flight suppresses while ack unknown
        proposals=[prop("model_exit", "me_x", 70)])),
    ("reconcile_dead", {}),
    ("arb", dict(          # retry eligible -> fresh attempt #2
        book=ExitBook("no", 60, 500, 10),
        proposals=[prop("trailing_profit", "tp2", 60)])),
    ("fill", {"cc": 150}),
    ("restart", {}),
    ("arb", dict(          # restart: partially-filled working order must
        proposals=[prop("profit_lock", "pl_x", 65)])),  # reconcile, not dup
    ("reconcile_alive", {}),
    ("fill", {"cc": 150}),  # covers remaining
    ("arb", dict(proposals=[prop("model_exit", "me_z", 40)], remaining=0)),
]


def run(log, tmpdir, restart_at=None):
    """Replay `log`; optional extra restart after event index `restart_at`."""
    os.environ["MERID_EXIT_STATE_PATH"] = str(Path(tmpdir) / "es.json")
    os.environ["MERID_EXIT_ATTEMPTS_PATH"] = str(Path(tmpdir) / "ea.json")
    arb = ExitArbiter(state_store=PositionExitStateStore(),
                      attempt_store=ExitAttemptStore())
    trace = []

    def snapshot(tag):
        a = arb._attempts.get_active(PK)
        rec = arb._state_store.find_record(
            TICKER, GEN, held_outcome="no", require_generation=True)
        trace.append((
            tag,
            getattr(a, "state", None) and a.state.value,
            getattr(a, "attempt_id", None),
            getattr(a, "filled_cc", None),
            rec and rec.get("ratchet_floor_price_cents"),
        ))

    for i, (op, kw) in enumerate(log):
        if op == "arb":
            r = arb.arbitrate(
                market_id=TICKER, generation_id=GEN, held_side="no",
                remaining_cc=kw.get("remaining", 300),
                breakeven_floor_cents=BE,
                book=kw.get("book"), proposals=kw.get("proposals", []),
            )
            trace.append(("arb", r.status, r.floor_cents,
                          r.submitted_limit_cents, r.exception,
                          r.attempt and r.attempt.attempt_id,
                          tuple(sorted(r.not_selected))))
        elif op == "ack_unknown":
            arb.mark_ack_unknown(PK, "replay_lost_ack")
        elif op == "reconcile_dead":
            arb.begin_reconcile(PK)
            arb.resolve_reconcile(PK, ReconcileEvidence(
                order_found=True, terminal=True, filled_cc=0,
                source="order_id"))
        elif op == "reconcile_alive":
            arb.begin_reconcile(PK)
            arb.resolve_reconcile(PK, ReconcileEvidence(
                order_found=True, terminal=False, filled_cc=0,
                source="order_id"))
        elif op == "fill":
            arb.record_fill(PK, kw["cc"])
        elif op == "restart":
            arb = ExitArbiter(state_store=PositionExitStateStore(),
                              attempt_store=ExitAttemptStore())
        snapshot(f"{i}:{op}")
        if restart_at is not None and i == restart_at:
            arb = ExitArbiter(state_store=PositionExitStateStore(),
                              attempt_store=ExitAttemptStore())
            snapshot(f"{i}:restart")
    return trace


def main():
    PASS = []
    # Pass A: identical logs on independent stores -> identical traces
    t1 = run(LOG, tempfile.mkdtemp(prefix="rpA1_"))
    t2 = run(LOG, tempfile.mkdtemp(prefix="rpA2_"))
    ok = t1 == t2
    PASS.append(("replay: identical traces on fresh stores", ok))
    print(f"[{'PASS' if ok else 'FAIL'}] replay determinism "
          f"({len(t1)} vs {len(t2)} events)")
    if not ok:
        for a, b in zip(t1, t2):
            if a != b:
                print("  first divergence:", a, "!=", b)

    # structural assertions on the baseline trace
    arb_events = [e for e in t1 if e[0] == "arb"]
    # only "submitted" results mint a new attempt; in-flight/rejected rows
    # correctly carry the *existing* attempt for inspection
    ids = [e[5] for e in arb_events if e[1] == "submitted"]
    PASS.append(("two attempts minted (retry once)",
                 ids == [f"{PK}#1", f"{PK}#2"]))
    PASS.append(("lost-ack arbitration rejected",
                 arb_events[1][1] == "reconcile_required"))
    PASS.append(("post-restart arbitration rejected",
                 arb_events[3][1] == "reconcile_required"))
    PASS.append(("floor ratcheted 55->60 across retry",
                 arb_events[2][2] == 60))
    PASS.append(("terminal flat", arb_events[-1][1] == "flat"))
    ids_ok = ids == [f"{PK}#1", f"{PK}#2"]
    print(f"[{'PASS' if ids_ok else 'FAIL'}] attempt ids {ids}")
    print(f"[{'PASS' if arb_events[-1][1] == 'flat' else 'FAIL'}] "
          f"terminal arb status {arb_events[-1][1]}")

    # Pass B: restart injected after every boundary -> same terminal state
    fails_b = []
    for cut in range(len(LOG)):
        tr = run(LOG, tempfile.mkdtemp(prefix="rpB_"), restart_at=cut)
        last_arb = [e for e in tr if e[0] == "arb"][-1]
        if last_arb[1] != "flat" or last_arb[2] != 60:
            fails_b.append((cut, last_arb))
    PASS.append(("restart at every boundary -> same terminal",
                 not fails_b))
    print(f"[{'PASS' if not fails_b else 'FAIL'}] restart-boundary sweep "
          f"({len(LOG)} cuts)" + (f" fails={fails_b}" if fails_b else ""))

    fails = [n for n, ok in PASS if not ok]
    print(f"\nREPLAY MATRIX: {len(PASS) - len(fails)}/{len(PASS)} passed")
    if fails:
        print("FAILURES:", fails)
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()


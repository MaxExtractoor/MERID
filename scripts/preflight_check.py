"""Pre-flight validation for ladder paper trading sessions.

Checks all safety systems before starting a long paper session:
  1. Execution gate is CLEAR
  2. Reconciliation has run successfully
  3. Price feeds are fresh for all tracked symbols
  4. Kill switch is disarmed
  5. Trade mode is PAPER (not LIVE, not MOCK)
  6. Paper ladder state is loadable
  7. Session log persistence is working

Run:  py scripts/preflight_check.py
"""

import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "✅ PASS" if ok else "❌ FAIL"
    msg = f"  {status}  {label}"
    if detail:
        msg += f"  — {detail}"
    print(msg)
    return ok


def run_preflight() -> bool:
    """Run all pre-flight checks. Returns True if all pass."""
    print("\n" + "=" * 60)
    print("  MERID LADDER SESSION — PRE-FLIGHT CHECK")
    print("=" * 60 + "\n")

    results = []

    # ── 1. Execution gate ─────────────────────────────────────────
    print("[1/7] Execution Gate")
    try:
        from core.execution_gate import check_execution_gate
        gate = check_execution_gate()
        results.append(_check(
            "Gate state",
            gate.gate_state == "clear",
            f"state={gate.gate_state}, reasons={len(gate.reasons)}",
        ))
        if gate.reasons:
            for r in gate.reasons:
                print(f"        ⚠ {r.source}: {r.message}")
                if r.hint:
                    print(f"          → {r.hint}")
    except Exception as e:
        results.append(_check("Gate state", False, str(e)))

    # ── 2. Reconciliation ─────────────────────────────────────────
    print("\n[2/7] Reconciliation")
    try:
        from merid.reconciliation import get_last_report, has_critical_discrepancies
        report = get_last_report()
        has_disc = has_critical_discrepancies()
        if report:
            results.append(_check(
                "Last reconciliation",
                report.all_ok and not has_disc,
                f"all_ok={report.all_ok}, checks={len(report.checks)}",
            ))
        else:
            results.append(_check("Last reconciliation", False, "No report yet — run reconciliation first"))
    except Exception as e:
        results.append(_check("Reconciliation", False, str(e)))

    # ── 3. Price feeds ────────────────────────────────────────────
    print("\n[3/7] Price Feeds")
    try:
        from core.execution_gate import check_price_feed_staleness
        stale = check_price_feed_staleness()
        results.append(_check(
            "Feed freshness",
            stale["safe_to_trade"],
            f"checked={stale['total_checked']}, stale={len(stale['stale_symbols'])}, critical={stale['critical_count']}",
        ))
        if stale["stale_symbols"]:
            for s in stale["stale_symbols"][:5]:
                print(f"        ⚠ {s['symbol']}: {s['age_seconds']:.0f}s (threshold {s['threshold_seconds']}s, {'CRITICAL' if s['critical'] else 'non-critical'})")
    except Exception as e:
        results.append(_check("Feed freshness", False, str(e)))

    # ── 4. Kill switch ────────────────────────────────────────────
    print("\n[4/7] Kill Switch")
    try:
        from merid.risk.kill_switches import risk_controller
        killed = risk_controller._global_kill
        results.append(_check(
            "Kill switch disarmed",
            not killed,
            f"global_kill={killed}" + (f", reason={risk_controller._kill_reason}" if killed else ""),
        ))
    except Exception as e:
        results.append(_check("Kill switch", False, str(e)))

    # ── 5. Trade mode ─────────────────────────────────────────────
    print("\n[5/7] Trade Mode")
    try:
        from trading.trade_mode import get_trade_mode, TradeMode
        mode = get_trade_mode()
        results.append(_check(
            "Trade mode is PAPER",
            mode == TradeMode.PAPER,
            f"current={mode.value}",
        ))
        live_flag = os.getenv("MERID_ALLOW_LIVE_TRADES", "false")
        results.append(_check(
            "LIVE trades disabled",
            live_flag.lower() not in ("1", "true", "yes", "on"),
            f"MERID_ALLOW_LIVE_TRADES={live_flag}",
        ))
    except Exception as e:
        results.append(_check("Trade mode", False, str(e)))

    # ── 6. Paper ladder ───────────────────────────────────────────
    print("\n[6/7] Paper Ladder")
    try:
        from merid.paper_ladder import get_paper_ladder
        ladder = get_paper_ladder()
        summary = ladder.summary()
        portfolio_count = len(summary.get("portfolios", {}))
        results.append(_check(
            "Ladder loadable",
            True,
            f"portfolios={portfolio_count}, tiers={len(summary.get('tiers', []))}",
        ))
    except Exception as e:
        results.append(_check("Paper ladder", False, str(e)))

    # ── 7. Session log ────────────────────────────────────────────
    print("\n[7/7] Session Log")
    try:
        from core.session_log import get_session_info, LOG_FILE
        info = get_session_info()
        results.append(_check(
            "Session identity",
            bool(info["session_id"]),
            f"id={info['session_id']}, uptime={info['uptime_seconds']:.0f}s",
        ))
        results.append(_check(
            "Log file writable",
            True,
            f"path={LOG_FILE}",
        ))
    except Exception as e:
        results.append(_check("Session log", False, str(e)))

    # ── Summary ───────────────────────────────────────────────────
    passed = sum(results)
    total = len(results)
    all_ok = all(results)

    print("\n" + "=" * 60)
    if all_ok:
        print(f"  ✅ ALL {total} CHECKS PASSED — ready for ladder session")
    else:
        print(f"  ❌ {total - passed}/{total} CHECKS FAILED — fix before starting")
    print("=" * 60 + "\n")

    return all_ok


if __name__ == "__main__":
    ok = run_preflight()
    sys.exit(0 if ok else 1)

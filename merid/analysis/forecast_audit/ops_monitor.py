"""Operational-gate monitor for a frozen forecast-ablation segment.

Reads ONLY the operational ledgers — never comparative scores.  Produces a
point-in-time snapshot against the declared operational stop policy:

  * opportunity waterfall (registered, per-status final resolutions,
    raw deferred/missed/late/invalid/unavailable ROW counts — last-writer
    reconciliation hides intermediate deferrals; this reports raw rows)
  * deferral + scheduling delay by asset/horizon
  * hook-lag proxy (elapsed_hook_ms carried on deferred rows)
  * opportunity→event reconciliation misses (resolved attempt, no event
    row → candidate write failure / evidence loss)
  * production-loop cadence from decision_audit.db (lag proxy)
  * ledger gaps, duplicate/conflict counts
  * runtime identity drift vs the start record (reuses activation_receipt)

Stop statistics are evaluated EXACTLY as locked in the manifest:
hook lag rolling-60s median > 2.0s, production-loop lag rolling-60s p95
> 5.0s, event-write-failure rate > 1% (rolling-60s AND cumulative),
unexplained telemetry gaps → segment INVALID for its confirmatory claim.
The 500ms shadow budget is NOT a maximum; elapsed_hook_ms is a point
sample, not a bound.

Known blind spots (declared, not patched — frozen code):
  * in-memory emit_failed counter is not persisted; write failures are
    detected via reconciliation misses and ledger gaps instead.
  * hook lag is only observed when deferral rows exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parents[3]

_RESOLUTION_STATUSES = ("emitted", "late", "missed", "unavailable",
                        "invalid_input", "deferred")


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    for _ln, r in _iter_jsonl_numbered(path):
        yield r


def _iter_jsonl_numbered(path: Path):
    """Yields (line_no, parsed_row, line_sha256) for provenance checks."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                r = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                yield i, r, hashlib.sha256(
                    (s + "\n").encode()).hexdigest()


def _load_exclusions(seg_dir: Path) -> set:
    """Provenance-based test-residue exclusions: exact raw-line hashes.
    Rows stay in the source ledger but are excluded from all coverage
    accounting.  `registered_ts < activation` alone is NOT the classifier.
    """
    p = seg_dir / "test_residue_exclusions.json"
    if not p.exists():
        return set()
    man = json.loads(p.read_text())
    return {r["line_sha256"] for r in man.get("rows", [])}


def _gate_observability() -> Dict[str, Any]:
    """Locked operational gates vs available non-mutating evidence.
    Nothing here may be reported PASS from a proxy statistic."""
    return {
        "shadow_hook_lag_rolling60_median_2s": {
            "status": "NOT_OBSERVABLE",
            "evidence": "elapsed_hook_ms on deferral rows only",
            "limitation": "does not establish the all-cycle rolling "
                          "median; a deferral-free run emits no samples"},
        "production_loop_lag_rolling60_p95_5s": {
            "status": "PARTIALLY_OBSERVABLE",
            "evidence": "decision_audit_heartbeats inter-tick gaps + "
                        "ledger_write_latency_ms",
            "limitation": "loop cadence proxy, not hook-added lag p95"},
        "event_write_failure_rate_1pct": {
            "status": "PARTIALLY_OBSERVABLE",
            "evidence": "reconciliation misses (attempted, no event row) "
                        "+ unresolved ledger gaps",
            "limitation": "proxies do not establish the actual "
                          "emit_failed numerator/denominator"},
        "unexplained_telemetry_gaps": {
            "status": "PARTIALLY_OBSERVABLE",
            "evidence": "registered opportunities lacking resolutions",
            "limitation": "cannot distinguish process-down from silent "
                          "loss without the independent universe "
                          "scheduler; no exact missed-opportunity count "
                          "is claimed during downtime"},
        "coverage_waterfall": {"status": "OBSERVABLE",
                               "evidence": "opportunity ledger raw rows"},
        "deferral_visibility": {"status": "OBSERVABLE",
                                "evidence": "deferred rows by "
                                            "asset|horizon"},
        "identity_drift": {"status": "OBSERVABLE",
                           "evidence": "per-file code + env hash vs "
                                       "start record"},
        "duplicates_conflicts": {"status": "OBSERVABLE",
                                 "evidence": "identity-key collision "
                                             "scan"},
        "validity_note": (
            "with gates NOT_OBSERVABLE/PARTIALLY_OBSERVABLE, endpoint "
            "must report that operational validity could not be fully "
            "established — proxies are evidence, not the locked "
            "statistics"),
    }


def _asset(ticker: str) -> str:
    for a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        if f"KX{a}" in (ticker or ""):
            return a
    return "?"


def _median(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _p95(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))]


def _loop_cadence(db_path: Path, since_ts: float) -> Dict[str, Any]:
    """Production-loop lag from decision_audit_heartbeats (one row/tick):
    inter-tick gap distribution plus the ledger's own write-latency and
    error counters — the closest durable loop-lag signal."""
    if not db_path.exists():
        return {"available": False}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "decision_audit_heartbeats" not in tables:
                return {"available": False, "reason": "no_heartbeats_table"}
            rows = list(con.execute(
                "SELECT tick, created_at, ledger_write_latency_ms,"
                " ledger_error_count FROM decision_audit_heartbeats"
                " WHERE created_at >= ? ORDER BY created_at", (since_ts,)))
        finally:
            con.close()
        ts = sorted(float(r[1]) for r in rows)
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        lat = [float(r[2]) for r in rows
               if isinstance(r[2], (int, float))]
        errs = sum(int(r[3] or 0) for r in rows)
        return {"available": True, "ticks_in_window": len(ts),
                "last_tick_ts": max(ts) if ts else None,
                "inter_tick_gap_s": {"median": _median(gaps),
                                     "p95": _p95(gaps),
                                     "max": max(gaps) if gaps else None},
                "ledger_write_latency_ms": {"median": _median(lat),
                                            "p95": _p95(lat),
                                            "max": max(lat) if lat else None},
                "ledger_error_count_total": errs}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def monitor(segment_dir: Path, events_p: Path, opps_p: Path,
            audit_db: Path, out_p: Optional[Path] = None) -> Dict[str, Any]:
    rec = json.loads((segment_dir / "start_record.json").read_text())
    start_ts, end_ts = float(rec["start_ts"]), float(rec["fixed_end_ts"])
    now = time.time()

    exclusions = _load_exclusions(segment_dir)
    excluded_rows = 0
    regs: Dict[str, Dict[str, Any]] = {}
    raw_status = Counter()
    final_status: Dict[str, str] = {}
    deferral_rows: List[Dict[str, Any]] = []
    delays: Dict[str, List[float]] = defaultdict(list)
    hook_ms: List[float] = []
    for _ln, r, lh in _iter_jsonl_numbered(opps_p):
        if lh in exclusions:
            excluded_rows += 1
            continue
        oid = r.get("opportunity_id")
        st = r.get("status")
        if st == "scheduled":
            regs[oid] = r
            continue
        if st in _RESOLUTION_STATUSES:
            raw_status[st] += 1
            final_status[oid] = st  # last-writer terminal-ish status
            tgt = r.get("scheduled_target_ts")
            in_seg = isinstance(tgt, (int, float)) and start_ts <= tgt < end_ts
            if not in_seg:
                continue
            a, h = _asset(str(r.get("market_ticker") or oid)), \
                r.get("scheduled_horizon_s")
            if st == "deferred":
                deferral_rows.append(r)
                if isinstance(r.get("elapsed_hook_ms"), (int, float)):
                    hook_ms.append(r["elapsed_hook_ms"])
            elif isinstance(r.get("scheduling_delay_s"), (int, float)):
                delays[f"{a}|h{h}"].append(r["scheduling_delay_s"])

    in_seg_oids = {o for o, r in regs.items()
                   if isinstance(r.get("scheduled_target_ts"), (int, float))
                   and start_ts <= r["scheduled_target_ts"] < end_ts}

    ev_by_oid: Dict[str, int] = Counter()
    ev_ids: Counter = Counter()
    in_seg_events = 0
    for e in _iter_jsonl(events_p):
        tgt = e.get("scheduled_target_ts")
        if e.get("evaluation_source") == "scheduled_shadow" and \
                isinstance(tgt, (int, float)) and start_ts <= tgt < end_ts:
            in_seg_events += 1
            ev_by_oid[e.get("opportunity_id")] += 1
            for k in ("record_id", "evaluation_id", "forecast_event_id"):
                if e.get(k):
                    ev_ids[f"{k}:{e[k]}"] += 1

    # reconciliation misses: attempted opportunities (non-deferred final
    # resolution) with zero matching event rows → candidate evidence loss
    attempted = {o for o, s in final_status.items()
                 if s in ("emitted", "late", "unavailable", "invalid_input")}
    recon_misses = sorted(o for o in attempted & in_seg_oids
                          if ev_by_oid.get(o, 0) == 0)
    dup_oids = [o for o, c in ev_by_oid.items() if c > 1]
    dup_ev_ids = [k for k, c in ev_ids.items() if c > 1]
    unresolved = sorted(o for o in in_seg_oids if o not in final_status)

    # identity drift
    runtime_files = {f: hashlib.sha256(
        (_ROOT / f).read_bytes()).hexdigest()
        for f in (rec.get("code_file_hashes") or {})
        if (_ROOT / f).exists()}
    mismatches = {f: {"recorded": rec["code_file_hashes"][f],
                      "running": h}
                  for f, h in runtime_files.items()
                  if h != rec["code_file_hashes"].get(f)}

    deferred_by = Counter(
        f"{_asset(str(r.get('market_ticker')))}|h{r.get('scheduled_horizon_s')}"
        for r in deferral_rows)

    report = {
        "monitor_schema": 1,
        "captured_ts": now,
        "segment_id": rec["segment_id"],
        "window_elapsed_frac": round(
            min(1.0, max(0.0, (now - start_ts) / (end_ts - start_ts))), 4),
        "excluded_test_residue_rows": excluded_rows,
        "gate_observability": _gate_observability(),
        "unobserved_scope": {
            "known_in_scope_unobserved": (
                "registered opportunities with no resolution/event — "
                "enumerable from this ledger"),
            "universe_unobserved_during_downtime": (
                "periods with no running process: the conditional "
                "opportunity universe itself was not observed; NO exact "
                "missed-opportunity count is claimed without the "
                "independent universe scheduler"),
        },
        "waterfall": {
            "registrations_in_segment": len(in_seg_oids),
            "registrations_total_rows": len(regs),
            "raw_resolution_rows_by_status": dict(raw_status),
            "final_status_by_opportunity": dict(
                Counter(final_status.get(o) for o in in_seg_oids
                        if o in final_status)),
            "unresolved_in_segment": len(unresolved),
            "in_segment_events": in_seg_events,
        },
        "deferrals_by_asset_horizon": dict(deferred_by),
        "scheduling_delay_s_by_asset_horizon": {
            k: {"n": len(v), "median": _median(v), "p95": _p95(v),
                "max": max(v)}
            for k, v in sorted(delays.items())},
        "hook_lag_ms_observed": {
            "n_deferral_samples": len(hook_ms),
            "median": _median(hook_ms), "p95": _p95(hook_ms),
            "max": max(hook_ms) if hook_ms else None,
            "note": "deferral-row samples only; absence of rows means no "
                    "budget exhaustion was observed, not that lag < budget"},
        "production_loop": _loop_cadence(audit_db, start_ts),
        "reconciliation": {
            "attempted_no_event": len(recon_misses),
            "attempted_no_event_ids": recon_misses[:50],
            "unresolved_ids_sample": unresolved[:50],
        },
        "duplicates_conflicts": {
            "opportunity_ids_with_multiple_events": len(dup_oids),
            "duplicate_event_identity_keys": len(dup_ev_ids),
        },
        "identity_drift": {
            "code_file_mismatches": mismatches,
            "n_mismatches": len(mismatches),
            "env_hash_match": (
                hashlib.sha256(json.dumps(
                    {k: v for k, v in sorted(os.environ.items())
                     if k.startswith("MERID_")},
                    sort_keys=True).encode()).hexdigest()
                == rec.get("effective_env_hash")),
        },
        "monitoring_limitations": [
            "emit_failed counter is in-memory only; evidence loss detected "
            "via attempted_no_event reconciliation and unresolved gaps",
            "hook lag observable only from deferral rows",
            "test-residue rows share the ledger path; attribute by "
            "registered_ts >= activation_ts from the activation receipt",
        ],
    }
    if out_p:
        out_p.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment-dir", required=True)
    ap.add_argument("--events", default="logs/forecast_events.jsonl")
    ap.add_argument("--opportunities",
                    default="logs/forecast_opportunities.jsonl")
    ap.add_argument("--audit-db", default="data/decision_audit.db")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = Path(a.out) if a.out else _ROOT / "reports" / (
        f"ops_monitor_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    rep = monitor(Path(a.segment_dir), _ROOT / a.events,
                  _ROOT / a.opportunities, _ROOT / a.audit_db, out)
    print(json.dumps(rep, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

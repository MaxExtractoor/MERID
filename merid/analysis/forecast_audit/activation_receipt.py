"""Segment activation receipt — verifies the RUNNING process loaded the
frozen configuration, without inspecting comparative outcomes.

Captures, at the moment the collection process is detected:

  * segment_id / process detection evidence / process_start_ts
  * running per-file code hashes, resolved effective_env_hash, artifact
    hashes — compared field-by-field with the start record (mismatches
    preserved, never silently rewritten)
  * first in-segment registered opportunity, first attempted evaluation,
    first emitted event, first successful opportunity/event reconciliation
  * in-scope-but-unobserved accounting: opportunities whose scheduled
    target lay inside the segment window but before collection activated
    are counted as unobserved, not removed — membership never moves.

Usage::

    python -m merid.analysis.forecast_audit.activation_receipt \\
        --segment-dir experiments/forecast_ablation_v1/seg_20261023T2226Z \\
        --events logs/forecast_events.jsonl \\
        --opportunities logs/forecast_opportunities.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[3]


def _sha_file(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _env_hash(env: Optional[Dict[str, str]] = None) -> str:
    env = {k: v for k, v in sorted(
        (env if env is not None else os.environ).items())
        if k.startswith("MERID_")}
    return hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()


def _resolved_app_env(root: Path) -> Dict[str, str]:
    """Simulate the RUNNING process's effective env: start_15m.ps1 loads
    .env into the process env (overriding inherited shell values), then
    applies its explicit $env: sets; the app's load_dotenv() adds nothing
    further (process env wins, override=False).  Returns the resolved
    MERID_* map the production process is expected to see."""
    env = {k: v for k, v in os.environ.items()
           if k.startswith("MERID_")}
    dotenv = root / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                if k.startswith("MERID_"):
                    env[k] = v.strip()  # ps1 loads .env over shell env
    ps1 = root / "start_15m.ps1"
    script_set: Dict[str, str] = {}
    if ps1.exists():
        import re
        for m in re.finditer(r'(?m)^\s*\$env:(\w+)\s*=\s*"([^"]*)"',
                             ps1.read_text(encoding="utf-8",
                                           errors="replace")):
            k = m.group(1)
            if k.startswith("MERID_"):
                script_set[k] = m.group(2)
        # unsets (Remove-Item Env:X) — value absent in the process
        for m in re.finditer(r'(?m)^\s*Remove-Item\s+Env:(\w+)',
                             ps1.read_text(encoding="utf-8",
                                           errors="replace")):
            env.pop(m.group(1), None)
            script_set.pop(m.group(1), None)
    env.update(script_set)  # script sets are process env of the child
    return env


def _detect_process() -> Dict[str, Any]:
    """Best-effort detection of a running production agent process."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
             "Select-Object ProcessId,CreationDate,CommandLine | "
             "ConvertTo-Json -Depth 3"],
            text=True, timeout=30)
        rows = json.loads(out or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        hits = [r for r in rows
                if "agent_grid" in (r.get("CommandLine") or "")
                or "loop_15m" in (r.get("CommandLine") or "")]
        return {"queried": len(rows), "agent_processes": hits,
                "detected": bool(hits)}
    except Exception as exc:
        return {"detected": None, "error": f"{type(exc).__name__}: {exc}"}


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                yield r


def _load_exclusions(seg_dir: Path) -> set:
    p = seg_dir / "test_residue_exclusions.json"
    if not p.exists():
        return set()
    man = json.loads(p.read_text())
    return {r["line_sha256"] for r in man.get("rows", [])}


def _scan_ledgers(events_p: Path, opps_p: Path,
                  start_ts: float, end_ts: float,
                  exclusions: set = frozenset()) -> Dict[str, Any]:
    """First in-segment rows + reconciliation counters (no scores read).
    Excluded residue rows are skipped by exact raw-line hash — never by
    timestamp heuristics."""
    first_reg = first_event = None
    n_reg = n_evt = 0
    n_reg_in_seg = n_evt_in_seg = 0
    pre_seg_reg = excluded = 0
    status_counts: Dict[str, int] = {}
    if opps_p.exists():
        opp_lines = open(opps_p, encoding="utf-8").read().splitlines()
    else:
        opp_lines = []
    for line in opp_lines:
        s = line.strip()
        if not s:
            continue
        lh = hashlib.sha256((s + "\n").encode()).hexdigest()
        if lh in exclusions:
            excluded += 1
            continue
        try:
            r = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(r, dict):
            continue
        if r.get("status") != "scheduled":
            st = str(r.get("status"))
            status_counts[st] = status_counts.get(st, 0) + 1
            continue
        n_reg += 1
        tgt = r.get("scheduled_target_ts")
        in_seg = isinstance(tgt, (int, float)) and start_ts <= tgt < end_ts
        if in_seg:
            n_reg_in_seg += 1
            if first_reg is None:
                first_reg = {"opportunity_id": r.get("opportunity_id"),
                             "registered_ts": r.get("registered_ts"),
                             "scheduled_target_ts": tgt,
                             "market_ticker": r.get("market_ticker"),
                             "horizon_s": r.get("scheduled_horizon_s")}
        elif isinstance(tgt, (int, float)) and tgt < start_ts:
            pre_seg_reg += 1
    src_counts: Dict[str, int] = {}
    for r in _iter_jsonl(events_p) or ():
        n_evt += 1
        src = str(r.get("evaluation_source"))
        src_counts[src] = src_counts.get(src, 0) + 1
        tgt = r.get("scheduled_target_ts")
        in_seg = (r.get("evaluation_source") == "scheduled_shadow"
                  and isinstance(tgt, (int, float))
                  and start_ts <= tgt < end_ts)
        if in_seg:
            n_evt_in_seg += 1
            if first_event is None:
                first_event = {
                    "forecast_event_id": r.get("forecast_event_id"),
                    "record_id": r.get("record_id"),
                    "evaluation_id": r.get("evaluation_id"),
                    "attempt_index": r.get("attempt_index"),
                    "opportunity_id": r.get("opportunity_id"),
                    "evaluation_end_ts": r.get("evaluation_end_ts"),
                    "schema_version": r.get("schema_version"),
                }
    return {
        "registrations_total": n_reg,
        "excluded_residue_rows": excluded,
        "registrations_in_segment": n_reg_in_seg,
        "pre_segment_registrations": pre_seg_reg,
        "resolution_status_counts": status_counts,
        "first_in_segment_registration": first_reg,
        "events_total": n_evt,
        "events_by_source": src_counts,
        "events_in_segment": n_evt_in_seg,
        "first_in_segment_event": first_event,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--segment-dir", required=True)
    ap.add_argument("--events", default="logs/forecast_events.jsonl")
    ap.add_argument("--opportunities",
                    default="logs/forecast_opportunities.jsonl")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    seg_dir = Path(args.segment_dir)
    rec = json.loads((seg_dir / "start_record.json").read_text())
    start_ts = float(rec["start_ts"])
    end_ts = float(rec["fixed_end_ts"])

    # runtime identity vs frozen record
    runtime_files = {
        f: _sha_file(_ROOT / f)
        for f in (rec.get("code_file_hashes") or {})}
    file_mismatch = {
        f: {"recorded": rec["code_file_hashes"][f], "running": h}
        for f, h in runtime_files.items()
        if h != rec["code_file_hashes"].get(f)}
    runtime_env_hash = _env_hash()
    resolved_env = _resolved_app_env(_ROOT)
    resolved_env_hash = _env_hash(resolved_env)
    exclusions = _load_exclusions(seg_dir)
    ledger = _scan_ledgers(_ROOT / args.events, _ROOT / args.opportunities,
                           start_ts, end_ts, exclusions)
    proc = _detect_process()
    activated = (
        ledger["first_in_segment_registration"] is not None
        and ledger["first_in_segment_event"] is not None)
    receipt = {
        "receipt_schema": 1,
        "captured_ts": time.time(),
        "segment_id": rec["segment_id"],
        "collection_status": ("awaiting_production_start"
                              if not activated else "collecting"),
        "exclusion_manifest": (
            "test_residue_exclusions.json" if exclusions else None),
        "segment_window_utc": [rec["start_utc"], rec["fixed_end_utc"]],
        "process_detection": proc,
        "identity_comparison": {
            "manifest_hash_recorded": rec.get("manifest_hash"),
            "code_file_mismatches": file_mismatch,
            "n_file_mismatches": len(file_mismatch),
            "effective_env_hash": {
                "recorded": rec.get("effective_env_hash"),
                "recorded_scope": "shell_env_at_record_time",
                "runtime_shell": runtime_env_hash,
                "runtime_resolved_app": resolved_env_hash,
                "match_shell": runtime_env_hash
                    == rec.get("effective_env_hash"),
                "match_resolved_app": resolved_env_hash
                    == rec.get("effective_env_hash"),
                "n_merid_vars_resolved": len(resolved_env),
                "note": ("recorded hash is shell-scope; the running "
                         "process resolves .env + start_15m.ps1 sets — "
                         "match_resolved_app is the running-process "
                         "comparison"),
            },
        },
        "collection_state": ledger,
        "activated": activated,
        "unobserved_scope": {
            "known_in_scope_unobserved": (
                "registered opportunities lacking resolution/event — "
                "enumerable from the opportunity ledger"),
            "universe_unobserved_during_downtime": (
                "no running process: the conditional opportunity "
                "universe itself was unobserved; NO exact missed count "
                "claimed without the independent universe scheduler"),
            "rule": ("opportunities whose scheduled_target_ts lay inside "
                     "the segment window but before collection activated "
                     "are UNOBSERVED — never backfilled; membership is "
                     "by scheduled_target_ts and never moves"),
        },
    }
    out = Path(args.out) if args.out else seg_dir / "activation_receipt.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

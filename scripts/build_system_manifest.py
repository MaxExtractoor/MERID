"""Assemble the frozen current-system manifest (audit Track: current-code replay).

Collects the effective state that determines trading behavior — not just a
git commit — into one versioned JSON artifact:

  * deployment sha + dirty-diff hash + production-path dirty files
  * runtime config hash (from live_runtime_state release record) + .env hash
  * model/calibration artifact hashes
  * persisted runtime state file hashes (probation/cooldown/gates)
  * fee-rule + boundary-resolver versions
  * data snapshot references and cutoffs

Read-only: never mutates repo, DBs, or state files.

CLI::

    py -3 scripts/build_system_manifest.py --out reports/system_manifest_2026-11-14.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True,
            timeout=60).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"<error: {exc}>"


def _file_meta(path: str) -> dict:
    p = REPO / path
    if not p.exists():
        return {"path": path, "exists": False}
    st = p.stat()
    return {
        "path": path, "exists": True, "bytes": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "sha256": _sha256(p),
    }


def _dirty_state() -> dict:
    modified = [l[3:] for l in _git("status", "--porcelain").splitlines()
                if l.startswith(" M") or l.startswith("M ")]
    untracked = [l[3:] for l in _git("status", "--porcelain").splitlines()
                 if l.startswith("??")]
    diff = _git("diff", "HEAD")
    diff_hash = hashlib.sha256(diff.encode("utf-8", "replace")).hexdigest()
    prod_prefixes = ("merid/event_venues/", "merid/data/", "merid/config/",
                     "merid/prediction/", "merid/execution", "web/",
                     "merid/ticker_time.py")
    prod_dirty = sorted(
        f for f in modified + untracked
        if f.startswith(prod_prefixes) or f == "merid/ticker_time.py")
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_diff_sha256": diff_hash,
        "n_modified": len(modified), "n_untracked": len(untracked),
        "production_path_dirty_files": prod_dirty,
        "all_modified": sorted(modified),
        "stash_count": len(_git("stash", "list").splitlines()),
    }


def _live_release() -> dict:
    p = REPO / "data" / "live_runtime_state.json"
    if not p.exists():
        return {"exists": False}
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "parse_error": str(exc)}
    ra = s.get("release_assertion") or {}
    keep = ("state", "entry_halted", "run_id", "process_id",
            "deployment_sha", "config_hash", "venue_environment",
            "reconciliation_snapshot_id", "fill_watermark",
            "model_release_id", "tail_calibration_artifact_hash",
            "started_at", "last_transition_at")
    out = {k: s.get(k) for k in keep}
    out["release_assertion_subset"] = {
        k: ra.get(k) for k in (
            "startup_phases_completed", "p0_preflight_passed",
            "kalshi_account_id", "enabled_at", "auto_enable",
            "live_latches", "model_release_id",
            "tail_calibration_artifact_hash")}
    return out


def _env_summary() -> dict:
    env_path = REPO / ".env"
    meta = _file_meta(".env")
    out = {"env_file": meta}
    if not env_path.exists():
        return out
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    flags = {}
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        k = k.strip()
        if k.startswith("MERID_"):
            flags[k] = v.strip()
    out["n_merid_flags"] = len(flags)
    out["flags_sha256"] = hashlib.sha256(
        json.dumps(flags, sort_keys=True).encode()).hexdigest()
    # Lane / mode flags surfaced for the restriction registry
    lane_keys = [k for k in flags if any(
        t in k for t in ("LANE", "CANARY", "PINNED_FAV", "SETTLEMENT_LANE",
                         "CHEAP_NO", "MBAND", "PROBATION", "COOLDOWN",
                         "VETO", "DRIFT_SCOPE", "FADE_GATE", "OBSERVE",
                         "EXECUTION_MODE", "LIVE_TRADES", "TRADING_MODE"))]
    out["lane_and_restriction_flags"] = {k: flags[k] for k in sorted(lane_keys)}
    return out


def _artifacts() -> dict:
    paths = [
        "data/probability_tail_calibration.json",
        "data/streaming_calibration.json",
        "data/empirical_price_calibration.json",
        "data/epc_wide_fit.json",
        "data/calibration_health.json",
        "data/fade_gate_state.json",
        "data/drift_lane_state.json",
        "data/directional_regime_state.json",
        "data/live_runtime_state.json",
        "data/promotion_states.json",
        "data/position_exit_state.json",
        "data/reconcile_fill_outcomes_state.json",
        "data/window_plan_state.json",
        "data/contract_boundaries_v1.jsonl",
        "logs/settlement_outcomes.jsonl",
        "logs/model_calibration_observations.jsonl",
        "logs/bankroll_reconciliation.jsonl",
        "data/kalshi_fills.db",
        "data/cf_rti_ticks.db",
        "data/_audit_hot/decision_audit.db",
    ]
    return {p: _file_meta(p) for p in paths}


def _versions() -> dict:
    out = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "boundary_resolver_version": "boundary_resolver_v1",
        "fee_rule": {
            "function": "kalshi_fee_cents_exact",
            "module": "merid/event_venues/kalshi/parabolic_fees.py",
            "module_sha256": _sha256(
                REPO / "merid/event_venues/kalshi/parabolic_fees.py"),
            "verified_examples": "1 contract @47c -> $0.0175; @1.1c -> $0.0008",
            "note": "6dp model fee ceiled, bounded at $0.0001 balance "
                    "precision; NOT whole-cent rounded",
        },
    }
    try:
        import importlib.metadata as md
        for pkg in ("numpy", "pandas", "scipy", "sklearn", "fastapi",
                    "uvicorn", "websockets", "python-dotenv", "pydantic"):
            try:
                out.setdefault("packages", {})[pkg] = md.version(pkg)
            except md.PackageNotFoundError:
                pass
    except Exception:
        pass
    req = REPO / "requirements.txt"
    if req.exists():
        out["requirements_txt_sha256"] = _sha256(req)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    manifest = {
        "schema": "merid_system_manifest_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git": _dirty_state(),
        "runtime_release": _live_release(),
        "env": _env_summary(),
        "artifacts_and_state": _artifacts(),
        "versions": _versions(),
        "provenance_notes": [
            "deployment_sha is the running process's own recorded release SHA",
            "config_hash is the runtime's hash of effective configuration",
            "production_path_dirty_files must be reviewed before treating "
            "replay-of-current-code as identical to the deployed process",
            "expiry_fallback.py delegates parsing to merid/ticker_time.py "
            "(untracked new module) — refactor intended behavior-preserving; "
            "verify before replay claims",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, default=str),
                   encoding="utf-8")
    print(f"wrote {out}")
    print(f"  sha={manifest['git']['head'][:12]} "
          f"dirty_diff={manifest['git']['dirty_diff_sha256'][:16]} "
          f"prod_dirty={manifest['git']['production_path_dirty_files']}")
    print(f"  config_hash="
          f"{(manifest['runtime_release'].get('config_hash') or '?')[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

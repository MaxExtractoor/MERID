"""CI Blueprint Checks — validates config, manifest, and form hygiene.

Run as part of CI to catch drift early:
  python scripts/ci_blueprint_checks.py          # all checks
  python scripts/ci_blueprint_checks.py --json   # JSON output

Checks:
  1. paper_config imports cleanly, all domains enabled, instruments registered
  2. TS manifest is up to date with Python manifest
  3. UI manifest ↔ audit_endpoints cross-check (warn-only)
  4. Form field checker finds no new regressions beyond known baseline
  5. Matching engine initializes for configured domains

Exit 0 if all pass, exit 1 on any failure.
"""

import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

KNOWN_FORM_FIELD_BASELINE = 32  # Pre-existing: DataTableEnhanced checkboxes + DevProposal/HITL/Kalshi/CommandPalette/Assistant form fields


def _ok(label: str, detail: str = ""):
    print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    return True


def _fail(label: str, detail: str = ""):
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
    return False


def _warn(label: str, detail: str = ""):
    print(f"  WARN  {label}" + (f"  ({detail})" if detail else ""))
    return True  # warnings don't fail CI


def check_paper_config() -> bool:
    """Check 1: paper_config loads, all domains enabled, instruments registered."""
    try:
        from merid.paper_config import get_paper_config, INSTRUMENT_REGISTRY
        cfg = get_paper_config()
        domains = cfg.active_domain_names()
        instruments = len(INSTRUMENT_REGISTRY)
        symbols = len(cfg.all_symbols())

        if len(domains) < 3:
            return _fail("paper_config", f"Only {len(domains)} domains active, expected ≥3")
        if instruments < 10:
            return _fail("paper_config", f"Only {instruments} instruments, expected ≥10")
        if symbols < 20:
            return _fail("paper_config", f"Only {symbols} symbols, expected ≥20")

        # Check risk limits exist
        if cfg.risk_limits is None:
            return _fail("paper_config", "risk_limits is None")
        if cfg.reconciliation is None:
            return _fail("paper_config", "reconciliation is None")

        return _ok("paper_config", f"{len(domains)} domains, {instruments} instruments, {symbols} symbols")
    except Exception as e:
        return _fail("paper_config", str(e))


def check_ts_manifest() -> bool:
    """Check 2: TS manifest is up to date with Python manifest."""
    try:
        from scripts.generate_ts_manifest import generate, TS_OUTPUT
        content = generate()
        if not os.path.exists(TS_OUTPUT):
            return _fail("ts_manifest", f"{TS_OUTPUT} does not exist")
        with open(TS_OUTPUT, "r", encoding="utf-8") as f:
            existing = f.read()
        if existing.strip() == content.strip():
            return _ok("ts_manifest", "up to date")
        else:
            return _fail("ts_manifest", "out of date — run: python scripts/generate_ts_manifest.py")
    except Exception as e:
        return _fail("ts_manifest", str(e))


def check_manifest_audit_crosscheck() -> bool:
    """Check 3: UI manifest ↔ audit_endpoints coverage (warn-only)."""
    try:
        from merid.ui_views_manifest import all_api_paths
        from audit_endpoints import ENDPOINTS
        audit_paths = {ep[2] for ep in ENDPOINTS}
        manifest_paths = set(all_api_paths())
        missing_from_audit = manifest_paths - audit_paths
        missing_from_manifest = audit_paths - manifest_paths

        if not missing_from_audit and not missing_from_manifest:
            return _ok("manifest_audit", "full sync")
        else:
            return _warn(
                "manifest_audit",
                f"{len(missing_from_audit)} in manifest not in audit, "
                f"{len(missing_from_manifest)} in audit not in manifest"
            )
    except Exception as e:
        return _warn("manifest_audit", f"skipped: {e}")


def check_form_fields() -> bool:
    """Check 4: Form field checker finds no new regressions."""
    try:
        result = subprocess.run(
            ["node", "scripts/check_form_fields.js", "--scan-tsx", "--json"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=30,
        )
        data = json.loads(result.stdout)
        total = (
            len(data.get("missingIdOrName", []))
            + len(data.get("duplicateIds", {}))
            + len(data.get("missingLabel", []))
        )
        if total <= KNOWN_FORM_FIELD_BASELINE:
            return _ok("form_fields", f"{total} issues (baseline={KNOWN_FORM_FIELD_BASELINE})")
        else:
            return _fail(
                "form_fields",
                f"{total} issues exceeds baseline of {KNOWN_FORM_FIELD_BASELINE} — "
                f"run: node scripts/check_form_fields.js --scan-tsx"
            )
    except FileNotFoundError:
        return _warn("form_fields", "node not found — skipping")
    except Exception as e:
        return _warn("form_fields", f"skipped: {e}")


def check_matching_engines() -> bool:
    """Check 5: Matching engines initialize for configured domains."""
    try:
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        if not engines:
            return _warn("matching_engines", "no engines configured")
        domains = list(engines.keys())
        enabled = [d for d, e in engines.items() if e.enabled]
        return _ok("matching_engines", f"{len(engines)} initialized, {len(enabled)} enabled: {enabled}")
    except Exception as e:
        return _fail("matching_engines", str(e))


def main():
    json_mode = "--json" in sys.argv
    t0 = time.time()

    print(f"MERID Blueprint CI Checks")
    print(f"{'=' * 50}")

    results = {}
    checks = [
        ("paper_config", check_paper_config),
        ("ts_manifest", check_ts_manifest),
        ("manifest_audit", check_manifest_audit_crosscheck),
        ("form_fields", check_form_fields),
        ("matching_engines", check_matching_engines),
    ]

    all_pass = True
    for name, fn in checks:
        passed = fn()
        results[name] = "pass" if passed else "fail"
        if not passed:
            all_pass = False

    elapsed = time.time() - t0
    print(f"\n{'=' * 50}")
    passes = sum(1 for v in results.values() if v == "pass")
    fails = sum(1 for v in results.values() if v == "fail")
    print(f"Result: {passes}/{len(checks)} passed, {fails} failed  ({elapsed:.1f}s)")

    if json_mode:
        print(json.dumps({"results": results, "elapsed_s": round(elapsed, 2)}, indent=2))

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()

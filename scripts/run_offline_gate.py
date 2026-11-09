"""Run canonical acceptance checks in a credential-free source sandbox."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree


SUITES = (
    "tests/test_offline_gate_acceptance.py",
    "tests/data/test_ingress_replay.py",
    "tests/data/test_replay_state_diff.py",
    "tests/data/test_replay_zero_network.py",
    "tests/test_runtime_recovery_evidence.py",
    "tests/event_venues/kalshi/test_kalshi_p0_exit_order_simulator.py",
    "tests/event_venues/kalshi/test_kalshi_p0_maker_taker_simulator.py",
    "tests/test_startup_preserves_reservations.py",
    "tests/test_execution_gate_fail_closed_order_paths.py",
    "tests/test_orchestrator_bug_fix_regressions.py::TestBugH7HealthEndpointLive",
)


def copy_source(root: Path, sandbox: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True,
    )
    paths = {Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p}
    paths.update(Path(p) for p in (
        "scripts/run_offline_gate.py", "scripts/offline_gate_plugin.py",
        "tests/test_offline_gate_acceptance.py",
        "tests/data/golden/replay_state_diff_golden.jsonl",
        "tests/data/golden/replay_tape/ingress_20260827T120000Z_0001_0001.jsonl",
    ))
    for relative in sorted(paths):
        if relative.name.startswith(".env") or relative.parts[:2] == ("data", "shadow"):
            continue
        if not (
            relative.suffix in {".py", ".toml", ".ini"}
            or relative.parts[0] in {"config", "tests"}
            or relative.name == ".merid_safeguard.yml"
        ):
            continue
        source = root / relative
        if source.is_symlink() or not source.is_file():
            continue
        destination = sandbox / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def gate_environment(sandbox: Path) -> dict[str, str]:
    keys = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "COMSPEC", "PATHEXT"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keys}
    env.update({
        "HOME": str(sandbox), "USERPROFILE": str(sandbox),
        "PYTHONPATH": str(sandbox), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "MERID_ENV": "testing",
        "MERID_AUTO_EXECUTION_MODE": "0", "MERID_OBSERVE_ONLY": "1",
        "TRADING_ENABLED": "false", "MERID_PM_LIVE_ENABLED": "false",
        "MERID_ALLOW_LIVE_TRADES": "false", "MERID_TRADE_MODE": "paper",
        "MERID_PM_TRADING_MODE": "mock", "KALSHI_API_KEY_ID": "",
        "KALSHI_PRIVATE_KEY_PATH": "",
    })
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--soak-seconds", type=int, default=0)
    args = parser.parse_args()
    if args.soak_seconds < 0:
        parser.error("--soak-seconds must be nonnegative")
    root = Path(__file__).resolve().parent.parent
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    runs = []
    passed = True
    with tempfile.TemporaryDirectory(prefix="merid_offline_gate_") as temporary:
        sandbox = Path(temporary)
        copy_source(root, sandbox)
        while True:
            number = len(runs) + 1
            junit = output / f"offline_{number}.xml"
            log = output / f"offline_{number}.log"
            command = [
                sys.executable, "-m", "pytest", "-p", "scripts.offline_gate_plugin",
                "-p", "pytest_asyncio.plugin", "-p", "pytest_timeout",
                *SUITES, "-q", "--tb=short", "--timeout=90", "-o", "addopts=",
                f"--junitxml={junit}",
            ]
            with log.open("w", encoding="utf-8") as stream:
                try:
                    result = subprocess.run(
                        command, cwd=sandbox, env=gate_environment(sandbox),
                        stdout=stream, stderr=subprocess.STDOUT, timeout=600,
                    )
                    returncode = result.returncode
                except subprocess.TimeoutExpired:
                    returncode = 124
            counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
            if junit.exists():
                for suite in ElementTree.parse(junit).getroot().iter("testsuite"):
                    for key in counts:
                        counts[key] += int(suite.get(key, "0"))
            passed = returncode == 0 and counts["tests"] > 0 and not any(
                counts[key] for key in ("failures", "errors", "skipped")
            )
            runs.append({"returncode": returncode, **counts, "passed": passed})
            print(f"Offline acceptance run {number}: {runs[-1]}", flush=True)
            if not passed:
                print(log.read_text(encoding="utf-8", errors="replace"), flush=True)
            if not passed or time.monotonic() - started >= args.soak_seconds:
                break
    report = {
        "gate": "canonical_offline_acceptance", "passed": passed,
        "live_readiness_authorized": False, "runs": runs,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    (output / "offline_gate.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

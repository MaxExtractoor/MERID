"""Minimal coverage loop helpers for MERID dev swarm."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.tools.run_swarm_tests import run_swarm_tests

HIGH_RISK_MODULES = [
    "swarm/dev_swarm_orchestrator.py",
    "swarm/collab_orchestrator.py",
    "swarm/swarm_lab.py",
    "swarm/swarm_lab_orchestrator.py",
    "swarm/emergent_behavior_safeguards.py",
    "swarm/failure_recovery_system.py",
    "swarm/security_defense_system.py",
    "swarm/secure_agent_communication.py",
    "swarm/scam_protection.py",
    "swarm/sniper_scanner.py",
    "swarm/mev_rewards.py",
    "swarm/hsm_key_management.py",
    "swarm/invariants_enforcement.py",
    "swarm/llm_gateway.py",
]

FAILURE_LOG_DIR = Path("artifacts/coverage_loop_failures")


def simple_coverage_cycle() -> Dict[str, Any]:
    """Run a single coverage cycle using the run_swarm_tests helper."""
    result = run_swarm_tests()
    return {
        "tests_passed": result.get("tests_passed", False),
        "total_coverage": result.get("total_coverage", 0.0),
        "files": result.get("files", []),
        "raw_output": result.get("raw_output", ""),
    }


def suggest_coverage_targets(coverage_result: Dict[str, Any], max_files: int = 2) -> List[Dict[str, Any]]:
    """Suggest high-priority files to target for additional coverage."""

    files = coverage_result.get("files", []) or []

    def priority_for(name: str) -> int:
        return 0 if name in HIGH_RISK_MODULES else 1

    ranked = sorted(
        (
            {
                "name": file_entry.get("name", ""),
                "coverage": float(file_entry.get("coverage", 0.0)),
                "missing_lines": file_entry.get("missing_lines", []),
                "priority": priority_for(file_entry.get("name", "")),
            }
            for file_entry in files
            if file_entry.get("name")
        ),
        key=lambda entry: (entry["priority"], entry["coverage"]),
    )

    return ranked[: max_files if max_files > 0 else 0]


def extract_failing_tests(raw_output: str) -> List[Dict[str, Any]]:
    """Best-effort parsing of pytest output to identify failing tests."""

    failures: List[Dict[str, Any]] = []
    if not raw_output:
        return failures

    lines = raw_output.splitlines()
    failure_pattern = re.compile(r"^(FAILED|ERROR)\s+(.+?)\s+::\s+(.*)")
    summary_pattern = re.compile(r"^FAILED\s+(.+?)::(.+?)\s+\[(?:\s*\d+%\s*)?\]")

    for line in lines:
        match = failure_pattern.match(line.strip())
        if match:
            nodeid = match.group(2).strip()
            message = match.group(3).strip()
            failures.append({
                "nodeid": nodeid,
                "file": nodeid.split("::")[0],
                "message": message,
            })
            continue

        summary_match = summary_pattern.match(line.strip())
        if summary_match:
            file_part = summary_match.group(1).strip()
            node_rest = summary_match.group(2).strip()
            nodeid = f"{file_part}::{node_rest}" if node_rest else file_part
            failures.append({
                "nodeid": nodeid,
                "file": file_part,
                "message": "test failure",
            })

    return failures


def apply_test_fixes(failing_tests: List[Dict[str, Any]]) -> None:
    """Placeholder hook for DevSwarmCoverageAgent or human operators."""

    # Intentionally empty: real implementations will edit tests/code outside this helper.
    pass


def _persist_failure_output(raw_output: str, label: str) -> Optional[str]:
    """Persist raw pytest output for investigation and return file path."""

    if not raw_output:
        return None

    FAILURE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"failure_{label}_{timestamp}.log"
    path = FAILURE_LOG_DIR / filename
    path.write_text(raw_output, encoding="utf-8")
    return str(path)


def run_coverage_improvement_loop(
    max_rounds_without_improvement: int = 3,
    max_test_fix_attempts: int = 2,
) -> Dict[str, Any]:
    """Run iterative coverage cycles and report history/remaining targets.

    Note: developers (or DevSwarmCoverageAgent) can run the suite in parallel via
    ``pytest tests/swarm --cov=swarm --cov-report=term-missing -n auto``. This helper
    does not force ``-n auto`` itself; it respects whatever command ``run_swarm_tests``
    is configured to execute.
    """

    history: List[Dict[str, Any]] = []
    failure_logs: List[Dict[str, str]] = []
    no_improve_rounds = 0

    while no_improve_rounds < max_rounds_without_improvement:
        result = simple_coverage_cycle()
        history.append(result)

        if not result.get("tests_passed", False):
            failing_tests = extract_failing_tests(result.get("raw_output", ""))
            log_path = _persist_failure_output(result.get("raw_output", ""), "initial")
            if log_path:
                failure_logs.append({"stage": "initial", "path": log_path})
            attempts = 0
            tests_fixed = False
            while attempts < max_test_fix_attempts:
                attempts += 1
                apply_test_fixes(failing_tests)
                retry_result = simple_coverage_cycle()
                history.append(retry_result)
                if retry_result.get("tests_passed", False):
                    tests_fixed = True
                    result = retry_result
                    break
                retry_log_path = _persist_failure_output(
                    retry_result.get("raw_output", ""), f"retry{attempts}"
                )
                if retry_log_path:
                    failure_logs.append({"stage": f"retry_{attempts}", "path": retry_log_path})
            if not tests_fixed:
                break

        targets = suggest_coverage_targets(result)
        if not targets:
            break

        improved_result = simple_coverage_cycle()
        history.append(improved_result)

        if improved_result.get("total_coverage", 0.0) > result.get("total_coverage", 0.0):
            no_improve_rounds = 0
        else:
            no_improve_rounds += 1

    remaining = suggest_coverage_targets(history[-1]) if history else []

    return {
        "history": history,
        "remaining_targets": remaining,
        "failure_logs": failure_logs,
    }

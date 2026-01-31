"""Tests for the coverage loop helper module."""

from __future__ import annotations

import pytest

from swarm import coverage_loop


def test_suggest_coverage_targets_prioritizes_high_risk() -> None:
    coverage_result = {
        "files": [
            {
                "name": "swarm/hsm_key_management.py",
                "coverage": 20.0,
                "missing_lines": ["1-200"],
            },
            {
                "name": "swarm/misc_module.py",
                "coverage": 90.0,
                "missing_lines": [],
            },
        ]
    }

    targets = coverage_loop.suggest_coverage_targets(coverage_result, max_files=2)

    assert targets[0]["name"] == "swarm/hsm_key_management.py"
    assert targets[0]["priority"] == 0
    assert targets[1]["priority"] == 1


def test_extract_failing_tests_parses_failure_lines() -> None:
    raw_output = """
    ============================= test session starts =============================
    FAILED tests/swarm/test_example.py::TestExample::test_one :: AssertionError: boom
    E   AssertionError: boom
    
    FAILED tests/swarm/test_other.py::test_two [50%]
    """

    failures = coverage_loop.extract_failing_tests(raw_output)

    assert len(failures) == 2
    assert failures[0]["nodeid"] == "tests/swarm/test_example.py::TestExample::test_one"
    assert failures[0]["file"] == "tests/swarm/test_example.py"
    assert failures[1]["nodeid"].startswith("tests/swarm/test_other.py")


def test_run_coverage_improvement_loop_improves_until_no_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_results = iter(
        [
            {
                "tests_passed": True,
                "total_coverage": 80.0,
                "files": [
                    {
                        "name": "swarm/hsm_key_management.py",
                        "coverage": 20.0,
                        "missing_lines": ["10", "20"],
                    },
                    {
                        "name": "swarm/coverage_loop.py",
                        "coverage": 5.0,
                        "missing_lines": ["1-50"],
                    },
                ],
                "raw_output": "initial",
            },
            {
                "tests_passed": True,
                "total_coverage": 83.0,
                "files": [
                    {
                        "name": "swarm/hsm_key_management.py",
                        "coverage": 40.0,
                        "missing_lines": ["30"],
                    }
                ],
                "raw_output": "improved",
            },
            {
                "tests_passed": True,
                "total_coverage": 83.0,
                "files": [],
                "raw_output": "plateau",
            },
        ]
    )

    def fake_run_swarm_tests() -> dict:
        try:
            return next(stub_results)
        except StopIteration as exc:  # pragma: no cover - ensures visibility if stub exhausted
            raise AssertionError("No more stubbed results") from exc

    monkeypatch.setattr(coverage_loop, "run_swarm_tests", fake_run_swarm_tests)

    result = coverage_loop.run_coverage_improvement_loop(
        max_rounds_without_improvement=2,
        max_test_fix_attempts=1,
    )

    assert len(result["history"]) == 3
    assert result["failure_logs"] == []
    assert result["remaining_targets"] == []


def test_run_coverage_improvement_loop_records_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_results = iter(
        [
            {
                "tests_passed": False,
                "total_coverage": 70.0,
                "files": [
                    {
                        "name": "swarm/hsm_key_management.py",
                        "coverage": 10.0,
                        "missing_lines": ["1-10"],
                    }
                ],
                "raw_output": "FAILED tests/swarm/test_mod.py::test_fail :: boom",
            },
            {
                "tests_passed": False,
                "total_coverage": 70.0,
                "files": [
                    {
                        "name": "swarm/hsm_key_management.py",
                        "coverage": 10.0,
                        "missing_lines": ["1-10"],
                    }
                ],
                "raw_output": "FAILED tests/swarm/test_mod.py::test_fail :: boom",
            },
        ]
    )

    def fake_run_swarm_tests() -> dict:
        try:
            return next(stub_results)
        except StopIteration as exc:  # pragma: no cover
            raise AssertionError("No more stubbed results") from exc

    fix_calls: list[list[dict]] = []

    def fake_apply_test_fixes(failing_tests: list[dict]) -> None:
        fix_calls.append(failing_tests)

    log_entries: list[str] = []

    def fake_persist(raw: str, label: str) -> str:
        log_entries.append(label)
        return f"/tmp/{label}.log"

    monkeypatch.setattr(coverage_loop, "run_swarm_tests", fake_run_swarm_tests)
    monkeypatch.setattr(coverage_loop, "apply_test_fixes", fake_apply_test_fixes)
    monkeypatch.setattr(coverage_loop, "_persist_failure_output", fake_persist)

    result = coverage_loop.run_coverage_improvement_loop(
        max_rounds_without_improvement=1,
        max_test_fix_attempts=1,
    )

    assert len(result["history"]) == 2
    assert fix_calls and fix_calls[0]
    assert log_entries == ["initial", "retry1"]
    assert result["failure_logs"] == [
        {"stage": "initial", "path": "/tmp/initial.log"},
        {"stage": "retry_1", "path": "/tmp/retry1.log"},
    ]
    assert result["remaining_targets"][0]["name"] == "swarm/hsm_key_management.py"

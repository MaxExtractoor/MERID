"""
Adversarial robustness testing harness for HFT swarm.

Simulates prompt/market perturbations, feeds them through agent pipelines, and
records pass/fail outcomes so regressions are caught early.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime


@dataclass
class AdversarialTestCase:
    test_id: str
    description: str
    perturbation_type: str
    payload: Dict[str, str]


@dataclass
class TestResult:
    test_id: str
    passed: bool
    findings: List[str]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class AdversarialRobustnessTester:
    def __init__(self) -> None:
        self._tests: Dict[str, AdversarialTestCase] = {}
        self._results: List[TestResult] = []

    def register_test(self, test: AdversarialTestCase) -> None:
        self._tests[test.test_id] = test

    def run_test(self, test_id: str, evaluator) -> TestResult:
        test = self._tests[test_id]
        passed, findings = evaluator(test)
        result = TestResult(test_id=test_id, passed=passed, findings=findings)
        self._results.append(result)
        return result

    def recent_failures(self, limit: int = 5) -> List[TestResult]:
        failures = [result for result in self._results if not result.passed]
        return failures[-limit:]

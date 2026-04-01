"""
Unit tests for scripts/run_paper_gate.py.

These tests do NOT require a running MERID server — all HTTP calls are mocked.
They validate:
  - _extract_sample_values() parsing for both response formats
  - run_gate() PASS verdict with good samples
  - run_gate() FAIL verdict for each individual criterion
  - CLI --dry-run exits 0 without connecting
  - GateResult JSON serialisation is complete (no missing fields)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

# ── Import the script under test directly from scripts/ ───────────────────────
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_paper_gate.py"
_spec = importlib.util.spec_from_file_location("run_paper_gate", _SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["run_paper_gate"] = _module  # required so @dataclass can resolve __module__
_spec.loader.exec_module(_module)

run_gate = _module.run_gate
_extract_sample_values = _module._extract_sample_values
_poll_event_loop_health = _module._poll_event_loop_health
GateResult = _module.GateResult
PollSample = _module.PollSample
main = _module.main
P95_LIMIT_MS = _module.P95_LIMIT_MS


# ── Helpers ───────────────────────────────────────────────────────────────────


def _healthy_body(p50: float = 1.0, p95: float = 5.0, p99: float = 8.0) -> dict:
    """Return a /health/event_loop response that represents a healthy system."""
    return {
        "status": "healthy",
        "degraded": False,
        "stats_1m": {
            "sample_count": 600,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "max_ms": p99 * 1.5,
            "samples_above_warn": 0,
            "samples_above_crit": 0,
        },
    }


def _degraded_body(p95: float = 600.0) -> dict:
    """Return a response representing a degraded system."""
    return {
        "status": "degraded",
        "degraded": True,
        "stats_1m": {
            "sample_count": 600,
            "p50_ms": 200.0,
            "p95_ms": p95,
            "p99_ms": p95 * 1.1,
            "max_ms": p95 * 1.5,
            "samples_above_warn": 10,
            "samples_above_crit": 3,
        },
    }


def _run_gate_with_responses(responses: list, *, duration_s: float = 0.05) -> GateResult:
    """
    Run run_gate() for a very short duration, injecting ``responses`` as the
    successive return values of _poll_event_loop_health.
    """
    call_count = [0]

    def fake_poll(base_url: str, timeout: float = 5.0) -> dict:  # noqa: ARG001
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        body = responses[idx]
        if isinstance(body, Exception):
            raise body
        return body

    with patch.object(_module, "_poll_event_loop_health", side_effect=fake_poll):
        return run_gate(
            base_url="http://mock",
            duration_s=duration_s,
            poll_interval_s=0.01,
            verbose=False,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# _extract_sample_values
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractSampleValues(unittest.TestCase):
    """Tests for _extract_sample_values() parser."""

    def test_nested_stats_1m(self):
        body = _healthy_body(p50=2.0, p95=10.0, p99=15.0)
        vals = _extract_sample_values(body)
        self.assertAlmostEqual(vals["p50_ms"], 2.0)
        self.assertAlmostEqual(vals["p95_ms"], 10.0)
        self.assertAlmostEqual(vals["p99_ms"], 15.0)
        self.assertFalse(vals["degraded"])
        self.assertEqual(vals["samples_above_crit"], 0)

    def test_flat_top_level_format(self):
        """Some monitor versions return stats at the top level."""
        body = {
            "degraded": False,
            "p50_ms": 3.0,
            "p95_ms": 12.0,
            "p99_ms": 18.0,
            "samples_above_warn": 0,
            "samples_above_crit": 0,
        }
        vals = _extract_sample_values(body)
        self.assertAlmostEqual(vals["p50_ms"], 3.0)
        self.assertAlmostEqual(vals["p95_ms"], 12.0)
        self.assertFalse(vals["degraded"])

    def test_degraded_body(self):
        body = _degraded_body(p95=620.0)
        vals = _extract_sample_values(body)
        self.assertTrue(vals["degraded"])
        self.assertAlmostEqual(vals["p95_ms"], 620.0)
        self.assertGreater(vals["samples_above_crit"], 0)

    def test_missing_fields_returns_none(self):
        vals = _extract_sample_values({})
        self.assertIsNone(vals["degraded"])
        self.assertIsNone(vals["p95_ms"])


# ═══════════════════════════════════════════════════════════════════════════════
# run_gate — PASS scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestGatePass(unittest.TestCase):
    """run_gate() should return passed=True for consistently healthy responses."""

    def test_all_healthy_samples_pass(self):
        responses = [_healthy_body(p50=1.0, p95=5.0) for _ in range(5)]
        result = _run_gate_with_responses(responses)
        self.assertTrue(result.passed, f"Expected PASS but got violations: {result.violations}")
        self.assertEqual(result.violations, [])

    def test_p95_just_below_limit_passes(self):
        # P95 of 499.9ms is just below the 500ms limit
        responses = [_healthy_body(p95=499.9) for _ in range(3)]
        result = _run_gate_with_responses(responses)
        self.assertTrue(result.passed)

    def test_aggregate_stats_computed_correctly(self):
        responses = [
            _healthy_body(p50=1.0, p95=5.0, p99=8.0),
            _healthy_body(p50=2.0, p95=10.0, p99=15.0),
            _healthy_body(p50=1.5, p95=7.5, p99=11.0),
        ]
        result = _run_gate_with_responses(responses)
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.p50_min_ms, 1.0)
        self.assertAlmostEqual(result.p50_max_ms, 2.0)
        self.assertAlmostEqual(result.p95_min_ms, 5.0)
        self.assertAlmostEqual(result.p95_max_ms, 10.0)

    def test_degraded_count_zero_on_healthy_run(self):
        responses = [_healthy_body() for _ in range(5)]
        result = _run_gate_with_responses(responses)
        self.assertEqual(result.degraded_samples, 0)
        self.assertEqual(result.total_crit_samples, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# run_gate — FAIL scenarios
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateFail(unittest.TestCase):
    """run_gate() should return passed=False when any criterion is violated."""

    def test_p95_at_limit_fails(self):
        # P95 = 500.0ms should fail (criterion is strictly < 500ms)
        responses = [_healthy_body(p95=P95_LIMIT_MS) for _ in range(3)]
        result = _run_gate_with_responses(responses)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("P95" in v for v in result.violations),
            f"Expected P95 violation, got: {result.violations}",
        )

    def test_p95_above_limit_fails(self):
        responses = [_healthy_body(p95=600.0) for _ in range(3)]
        result = _run_gate_with_responses(responses)
        self.assertFalse(result.passed)

    def test_degraded_sample_fails(self):
        responses = [_healthy_body(), _degraded_body(), _healthy_body()]
        result = _run_gate_with_responses(responses)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("degraded" in v for v in result.violations),
            f"Expected degraded violation, got: {result.violations}",
        )

    def test_crit_samples_fails(self):
        body = _healthy_body(p95=100.0)
        body["stats_1m"]["samples_above_crit"] = 2
        result = _run_gate_with_responses([body] * 3)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("critical" in v.lower() for v in result.violations),
            f"Expected critical-lag violation, got: {result.violations}",
        )

    def test_connection_errors_fail(self):
        import urllib.error
        err = urllib.error.URLError("connection refused")
        result = _run_gate_with_responses([err, err, err])
        self.assertFalse(result.passed)
        self.assertTrue(
            any("poll" in v.lower() or "heartbeat" in v.lower() for v in result.violations),
            f"Expected connection error violation, got: {result.violations}",
        )
        self.assertEqual(result.successful_polls, 0)

    def test_no_successful_polls_fails(self):
        import urllib.error
        result = _run_gate_with_responses(
            [urllib.error.URLError("refused")] * 5
        )
        self.assertFalse(result.passed)
        self.assertGreater(len(result.violations), 0)

    def test_mixed_pass_then_fail(self):
        """A gate that starts healthy but degrades mid-run must fail."""
        responses = [_healthy_body()] * 3 + [_degraded_body(p95=600.0)] + [_healthy_body()] * 3
        result = _run_gate_with_responses(responses)
        self.assertFalse(result.passed)


# ═══════════════════════════════════════════════════════════════════════════════
# GateResult serialisation
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateResultSerialisation(unittest.TestCase):
    """GateResult must round-trip through JSON without losing data."""

    def test_json_roundtrip(self):
        responses = [_healthy_body() for _ in range(3)]
        result = _run_gate_with_responses(responses)
        data = asdict(result)
        serialised = json.dumps(data)
        restored = json.loads(serialised)
        self.assertEqual(restored["passed"], result.passed)
        self.assertIsInstance(restored["samples"], list)
        self.assertIsInstance(restored["violations"], list)
        self.assertIn("gate_id", restored)
        self.assertIn("started_at", restored)
        self.assertIn("ended_at", restored)

    def test_all_required_fields_present(self):
        responses = [_healthy_body()]
        result = _run_gate_with_responses(responses)
        data = asdict(result)
        required = [
            "gate_id", "started_at", "ended_at", "duration_s",
            "environment", "trade_mode", "allow_live_trades",
            "total_polls", "successful_polls", "failed_polls",
            "p95_max_ms", "p95_mean_ms",
            "degraded_samples", "total_crit_samples",
            "passed", "violations", "samples",
        ]
        for field in required:
            self.assertIn(field, data, f"Missing field: {field}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI --dry-run
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIDryRun(unittest.TestCase):
    """CLI --dry-run must exit 0 without making any HTTP calls."""

    def test_dry_run_exits_zero(self):
        rc = main(["--dry-run"])
        self.assertEqual(rc, 0)

    def test_dry_run_custom_params(self):
        rc = main(["--dry-run", "--duration", "5", "--base-url", "http://example.com"])
        self.assertEqual(rc, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Gate metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateMetadata(unittest.TestCase):
    """GateResult metadata fields should be populated correctly."""

    def test_gate_id_auto_generated(self):
        result = _run_gate_with_responses([_healthy_body()])
        self.assertTrue(result.gate_id.startswith("paper-gate-"))

    def test_gate_id_custom(self):
        with patch.object(_module, "_poll_event_loop_health", return_value=_healthy_body()):
            result = run_gate(
                base_url="http://mock",
                duration_s=0.05,
                poll_interval_s=0.01,
                gate_id="gate-custom-001",
                verbose=False,
            )
        self.assertEqual(result.gate_id, "gate-custom-001")

    def test_started_at_and_ended_at_populated(self):
        result = _run_gate_with_responses([_healthy_body()] * 2)
        self.assertNotEqual(result.started_at, "")
        self.assertNotEqual(result.ended_at, "")

    def test_trade_mode_is_paper(self):
        result = _run_gate_with_responses([_healthy_body()])
        self.assertEqual(result.trade_mode, "paper")
        self.assertFalse(result.allow_live_trades)


if __name__ == "__main__":
    unittest.main()

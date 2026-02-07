from __future__ import annotations

from scripts import run_e2e


def test_run_e2e_main_returns_zero():
    rc = run_e2e.main(["--steps", "1", "--threshold", "0.1", "--actor", "pytest"])
    assert rc == 0


def test_run_e2e_fails_on_min_orders():
    # With strict min-orders that can't be satisfied, expect non-zero code
    rc = run_e2e.main(["--steps", "1", "--threshold", "0.0", "--actor", "pytest", "--min-orders", "10"])
    assert rc != 0


def test_run_e2e_requires_audit():
    rc = run_e2e.main(["--steps", "1", "--threshold", "0.0", "--actor", "pytest", "--require-audit"])
    # The sim should still create audits even with threshold 0.0, so expect success
    assert rc == 0

# Kalshi live-readiness slice (P0-3 superset). Extend when adding @pytest.mark.kalshi_live_ready tests.
# Full-tree `pytest tests -m kalshi_live_ready` is blocked until repo-wide collection is clean.
# Usage: .\scripts\kalshi_live_ready.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$targets = @(
    "tests/event_venues/kalshi/test_code_quality_invariants.py",
    "tests/event_venues/kalshi/test_invariants_crypto_universe.py",
    "tests/event_venues/kalshi/test_snapshot_replay.py",
    "tests/event_venues/kalshi/test_cycle_snapshot_schema.py",
    "tests/event_venues/kalshi/test_kalshi_runtime_config_snapshot.py",
    "tests/core/test_execution_gate_loop_lag_wiring.py",
    "tests/core/test_execution_gate.py",
    "tests/core/test_kalshi_gate_truth_table.py",
    "tests/event_venues/kalshi/test_risk_posture_snapshot.py",
    "tests/prediction/test_session_guard_exchange_availability.py",
    "tests/event_venues/kalshi/test_exchange_availability.py",
    "tests/test_asset_caps.py::TestIntegration::test_multi_timeframe_aggregation",
    "tests/test_orchestrator_bug_fix_regressions.py::TestBugH7HealthEndpointLive",
    "tests/test_execution_gate_fail_closed_order_paths.py"
)
py -m pytest @targets -q --tb=short

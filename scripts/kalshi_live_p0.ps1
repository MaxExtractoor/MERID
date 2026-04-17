# P0 live blockers — stricter gate before enabling live trading on a venue/account.
# Usage: .\scripts\kalshi_live_p0.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$targets = @(
    "tests/core/test_execution_gate_loop_lag_wiring.py",
    "tests/core/test_kalshi_gate_truth_table.py",
    "tests/core/test_execution_gate.py::TestCheckExecutionGate::test_gate_open_when_all_clear",
    "tests/core/test_execution_gate.py::TestCheckExecutionGate::test_gate_blocked_on_stale_feeds",
    "tests/core/test_execution_gate.py::TestCheckExecutionGate::test_gate_blocked_on_kill_switch",
    "tests/prediction/test_session_guard_exchange_availability.py",
    "tests/event_venues/kalshi/test_exchange_availability.py",
    "tests/test_orchestrator_bug_fix_regressions.py::TestBugH7HealthEndpointLive",
    "tests/test_asset_caps.py::TestIntegration::test_multi_timeframe_aggregation",
    "tests/test_execution_gate_fail_closed_order_paths.py"
)
py -m pytest @targets -q --tb=short

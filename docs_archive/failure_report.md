# Focused Failure Report

## Full Pytest Output (focused suites, `-vv --full-trace -s -rf --maxfail=10`)
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Dev\MERID
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.12.1, langsmith-0.6.2, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 310 items

... (full logs omitted for brevity; see command output in console log)

=========================== short test summary info ===========================
FAILED tests/core/test_poisoning_simulation.py::TestSyntheticPoisoningAttacks::test_sybil_collusion_attack - AssertionError: Sybil collusion was not detected
assert 0 > 0
 +  where 0 = len([])
FAILED tests/test_data_quality_monitors.py::TestLagMetricsCollector::test_record_lag_exceeds_threshold - AssertionError: assert 99.99990463256836 >= 100.0
 +  where 99.99990463256836 = LagMeasurement(stage='test_stage', operation='slow_operation', lag_ms=99.99990463256836, measured_at=datetime.datetime(2026, 1, 16, 19, 44, 50, 794344), metadata={}).lag_ms
FAILED tests/test_execution_guardrails.py::test_live_mode_falls_back_to_paper - trading._execution_core.PositionLimitError: Order value $20000 exceeds max position size $10000
FAILED tests/test_execution_guardrails.py::test_mev_defense_blocks_critical_threat - Failed: DID NOT RAISE <class 'trading._execution_core.OrderRejectedError'>
ERROR tests/test_moat_api.py::test_moat_status_endpoint - AttributeError: property 'moat_service_token' of 'Capabilities' object has no setter
... (remaining moat errors omitted)
```

## Failure Summary

| Category | Test ID | File:Line | Assertion/Failure |
| --- | --- | --- | --- |
| (A) | tests/core/test_poisoning_simulation.py::TestSyntheticPoisoningAttacks::test_sybil_collusion_attack | tests/core/test_poisoning_simulation.py:76 | `assert len(clusters) > 0`
| (A) | tests/test_data_quality_monitors.py::TestLagMetricsCollector::test_record_lag_exceeds_threshold | tests/test_data_quality_monitors.py:208 | `assert measurement.lag_ms >= 100.0`
| (A) | tests/test_execution_guardrails.py::test_live_mode_falls_back_to_paper | trading/execution.py:780 | `raise PositionLimitError("Order value ... exceeds max position size ...")`
| (A) | tests/test_execution_guardrails.py::test_mev_defense_blocks_critical_threat | tests/test_execution_guardrails.py:?? | `with pytest.raises(OrderRejectedError)` (order not rejected)
| (B) | tests/test_moat_api.py::* | core/env/capabilities.py (property setter) | monkeypatch fails: `AttributeError: property 'moat_service_token' ... has no setter`

## Reproduction Commands
```
pytest tests/core/test_poisoning_simulation.py -k test_sybil_collusion_attack -q -s
pytest tests/test_data_quality_monitors.py -k test_record_lag_exceeds_threshold -q -s
pytest tests/test_execution_guardrails.py -k test_live_mode_falls_back_to_paper -q -s
pytest tests/test_execution_guardrails.py -k test_mev_defense_blocks_critical_threat -q -s
pytest tests/test_moat_api.py -k moat_status_endpoint -q -s
```

## Git History (last 5 commits touching relevant files)

### Poisoning sims
```
git log -n 5 --oneline -- tests/core/test_poisoning_simulation.py core/adversarial_hardening.py core/consensus_gate.py
b5796bc Add explainability tracking ... (includes validation changes)
64354ad Replace Flutter-only .gitignore ... (docs)
... (older commits not shown)
```

### Lag metrics / data quality
```
git log -n 5 --oneline -- tests/test_data_quality_monitors.py observability/lag_metrics.py
<no recent commits>
```

### Execution guardrails / MEV
```
git log -n 5 --oneline -- tests/test_execution_guardrails.py trading/execution.py trading/guardrails.py
<older commits; no edits today>
```

### Moat API
```
git log -n 5 --oneline -- tests/test_moat_api.py web/api/moat.py core/env/capabilities.py
<older commits; property has always been read-only>
```

## Diff Since Last Tag
Repository has no tags (`git describe --tags` failed), so diffs vs tags unavailable.

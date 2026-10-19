# E2E Execution-Ready Regression Strategy

## CI Jobs to Implement

### 1. Invariant Scenario Tests
```bash
# Run all invariant scenarios
python scripts/test_invariant_scenarios.py

# Expected: All scenarios pass, no regressions
```

### 2. Live Log Validation
```bash
# Validate recent logs for invariant violations
python scripts/validate_invariants.py --mode dev --duration 300

# Expected: Zero critical invariant violations in normal operation
```

### 3. Execution-Ready Gate Tests
```bash
# Test execution-ready wiring
python scripts/test_execution_ready_wiring.py

# Expected: All components integrated and working
```

### 4. Fault Injection Tests
```bash
# Run fault injection on new invariants
python scripts/test_fault_injection.py

# Expected: All invariants detect intended violations
```

### 5. Comprehensive E2E Audit
```bash
# Run full E2E audit checklist
python scripts/e2e_audit_checklist.py

# Expected: Zero issues across all categories
```

## Regression Criteria

Any change is considered a regression if:

1. **New invariant violations** appear in normal operation
2. **Execution-ready gate** fails to include required components
3. **Guardrail logging** missing expected violation reasons
4. **Environment-aware policies** fail to respect prod/dev boundaries
5. **Syntax errors** or import failures in any module

## Alerting

- **Critical**: Any `EXECUTION_READY_CRITICAL_FAILURE` in production
- **High**: New invariant types appearing in normal operation
- **Medium**: Missing log fields or guardrail reasons
- **Low**: Test failures in synthetic scenarios

## Rollback Criteria

Rollback is required if:

1. Production shows `EXECUTION_READY_CRITICAL_FAILURE`
2. Bankroll or risk profile invariants trigger in production
3. Top3 gate fails closed in production due to missing module
4. Any critical subsystem shows inconsistent state

## Monitoring

Key log patterns to monitor:

- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=bankroll`
- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=risk_profile`
- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=top3_gate`
- `[E2E-GUARDRAIL-TRIP]` with new violation types
- Any `LIVE_BANKROLL_*` or `RISK_PROFILE_*` invariants

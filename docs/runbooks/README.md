# MERID Runbooks

Operations runbooks for the MERID + Kalshi trading system.

## Quick Reference

| Code | Title | When to Use | Severity |
|------|-------|-------------|----------|
| RB-1 | [FIX Endpoint Guard Trip](RB-01-fix-endpoint-guard.md) | 403 error on `/fix/orders` | Medium |
| RB-2 | [REST Fallback Fail-Closed](RB-02-rest-fallback-failclosed.md) | 503 error on `/orders` | High |
| RB-3 | [Kill-Switch Activation](RB-03-kill-switch-activation.md) | Trading halted | **CRITICAL** |
| RB-4 | [Config Violation](RB-04-config-violation.md) | App fails to start | High |
| RB-5 | [Archive Import Blocked](RB-05-archive-import.md) | ImportError on archive | Low |

## Severity Levels

- **CRITICAL**: Immediate operator attention, trading halted
- **High**: System degraded, action needed within 1 hour
- **Medium**: Isolated issue, workarounds available
- **Low**: Development/debugging issue

## Alert to Runbook Mapping

| Alert | Runbook |
|-------|---------|
| `merid_guard_trips_total{guard_type="FIX_ENDPOINT"} > 0` | [RB-1](RB-01-fix-endpoint-guard.md) |
| `merid_executor_available == 0` | [RB-2](RB-02-rest-fallback-failclosed.md) |
| `merid_kill_switch_active == 1` | [RB-3](RB-03-kill-switch-activation.md) |
| `merid_startup_enforcement_checks_total{result="fail"} > 0` | [RB-4](RB-04-config-violation.md) |
| `ImportError: Archive module imports are BLOCKED` | [RB-5](RB-05-archive-import.md) |

## Common Commands

### Health Check

```bash
# Full system health
curl http://localhost:8000/api/v1/health | jq

# Metrics endpoint
curl http://localhost:9100/metrics | grep -E "merid_(executor|kill_switch|guard)"
```

### Log Investigation

```bash
# Recent errors
grep "ERROR\|CRITICAL" /var/log/merid/app.log | tail -20

# Guard trips
jq 'select(.event_type == "GUARD_TRIP")' /var/log/merid/app.log | tail -5

# Mode transitions
jq 'select(.event_type == "MODE_TRANSITION")' /var/log/merid/app.log

# Kill switches
jq 'select(.event_type == "KILL_SWITCH")' /var/log/merid/app.log
```

### Test Verification

```bash
# All scenario tests
pytest tests/scenario/test_pass9_scenarios.py -v

# CI invariants
python scripts/ci/check_kalshi_invariants.py

# Specific guard test
pytest tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure -v
```

## Escalation Contacts

- **#on-call**: All critical alerts, kill switch activations
- **#risk-engineering**: Guard trips, bypass attempts, risk config issues
- **#platform-engineering**: Infrastructure, imports, config sources
- **#executive**: Trading halted > 1 hour during market hours

## Runbook Structure

Each runbook follows this format:

1. **Alert**: Prometheus/alertmanager condition
2. **Symptoms**: What you'll observe
3. **Impact**: Effect on trading/system
4. **Investigation**: Commands and queries
5. **Remediation**: Step-by-step fix
6. **Verification**: How to confirm resolved
7. **Escalation**: When to get help
8. **Related**: Links to code, tests, CI checks

## Maintenance

These runbooks should be updated when:
- New guard types are added
- Error messages change
- Metrics names change
- New failure modes discovered

Update the corresponding guard implementation, tests, and CI invariants when modifying runbooks.

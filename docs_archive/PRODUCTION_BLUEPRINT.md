# MERID Production Blueprint: Domain Priority System & SIGHTED_DEGRADED Mode

## Overview

This document provides a comprehensive blueprint for deploying and operating the MERID domain priority system with SIGHTED_DEGRADED mode in production. The system implements a "hard-safe, soft-aware" operational model that enforces strict domain input priorities while maintaining comprehensive safety and compliance.

## Architecture Summary

### Core Components

1. **Domain Priority Manager** (`core/domain_priority_manager.py`)
   - Enforces domain hierarchy: observe core, block action
   - Core domains: market, onchain, simulation, agent (read-only)
   - Blocked domains: execution, treasury, governance, system (no access)
   - Rate limiting per domain with cascading fallbacks

2. **Reality Auditor** (`core/reality_auditor.py`)
   - Automatic mode transitions: BLIND ↔ SIGHTED_DEGRADED
   - Safety checks: assertion coverage, feed liveness, clock skew
   - Production threshold: ≥5 valid assertions per core domain

3. **Assertion Registry** (`core/reality_registry.py`)
   - Time-bounded claims with automatic decay
   - 8 domains, 5 statuses, conflict preservation
   - SOX-grade audit logging

### Safety Model

```
┌─────────────────────────────────────────────────────────────┐
│                    SAFETY HIERARCHY                          │
├─────────────────────────────────────────────────────────────┤
│ 1. Global Safety Override (emergency access only)           │
│ 2. Domain Priority Rules (hard-safe enforcement)           │
│ 3. Caller Role Permissions (context-aware)                │
│ 4. Default Safe Behavior (fail-safe)                      │
└─────────────────────────────────────────────────────────────┘
```

## CI/CD Pipeline

### Pipeline Stages

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   Stage 1        │    │    Stage 2        │    │      Stage 3         │
│ Commit & Build   │───▶│ Security &        │───▶│ Risk/Reality Tests   │
│                 │    │ Compliance        │    │ (New Lane)           │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
         │                       │                         │
         ▼                       ▼                         ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   Stage 4        │    │    Stage 5        │    │   Post-Deploy        │
│ Staging Deploy   │───▶│ Controlled Prod   │───▶│ Validation          │
│                 │    │ Deploy            │    │                     │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
```

### Stage 1: Commit & Build
- Lint, type-check, unit tests (≥90% coverage)
- Domain priority + assertion logic tests
- Build Docker image/artifact

### Stage 2: Security & Compliance
- SAST (CodeQL), dependency scans (Safety)
- Secrets scanning (TruffleHog), license checks
- Policy-as-code enforcement

### Stage 3: Risk/Reality Tests (New Lane)
- Domain priority unit + integration tests
- SIGHTED_DEGRADED activation test
- Chaos/fault tests in ephemeral environment
- Conflict resolution tests

### Stage 4: Staging Deploy
- Deploy with feature flags
- End-to-end scenarios with mocked trading APIs
- Security tests/DAST against staging

### Stage 5: Controlled Prod Deploy
- Blue-green/canary deployment
- Feature flags for subset of flows
- Auto-rollback on risk-lane failures
- Metrics monitoring (assertions, violations, transitions)

## Testing Strategy

### Unit Tests

#### Domain Priority System
```python
# Table-driven tests for priority resolution
@pytest.mark.parametrize("domain,operation,caller_kind,mode,expected", [
    ("execution", "execute", "agent", "SIGHTED_DEGRADED", "BLOCK"),
    ("market", "read", "human", "SIGHTED_DEGRADED", "ALLOW"),
    ("simulation", "write", "risk_manager", "SIGHTED_DEGRADED", "ALLOW"),
])
def test_priority_resolution(domain, operation, caller_kind, mode, expected):
    # Test implementation
    pass
```

#### Conflict Resolution
- Precedence order: global_safety > domain_priority > caller_role > default
- Idempotence: repeated evaluations yield same decision
- Edge cases: unknown callers, empty context, mode transitions

#### Degraded Signal Handling
- Partial assertion loss → conservative behavior
- Feed latency spikes → domain degradation
- Contradictory signals → conservative interpretation
- High violation rates → alerts/stricter mode

### Integration Tests

#### SIGHTED_DEGRADED Activation
```python
def test_production_activation():
    # 1. Load demo data (≥5 assertions per core domain)
    # 2. Verify mode transition to SIGHTED_DEGRADED
    # 3. Confirm domain priority manager activation
    # 4. Test blocked domain enforcement
    # 5. Validate audit trail completeness
    pass
```

#### Fault Injection Tests
- Feed loss/degradation scenarios
- Assertion engine failures
- Priority manager malfunctions
- Agent misbehavior testing
- Mode thrash protection

### Mock Trading APIs

#### Contract-First Mocks
```python
# Environment-specific profiles
class MockApiProfile(Enum):
    HAPPY_PATH = "happy_path"
    RATE_LIMIT = "rate_limit"
    PARTIAL_OUTAGE = "partial_outage"
    COMPLETE_OUTAGE = "complete_outage"
    ERROR_RESPONSES = "error_responses"
    STALE_DATA = "stale_data"
    MALFORMED_DATA = "malformed_data"
```

#### Failure Scenarios
- Timeouts, 429/5xx responses
- Partial fills, rejected orders
- Nonsense data, malformed responses
- Network connectivity issues

## Monitoring & Observability

### Key Metrics

#### System Health
```prometheus
# Valid assertions per domain
reality_valid_assertions{domain="market"} 7

# Current system mode
reality_mode 1  # 0=BLIND, 1=SIGHTED_DEGRADED, 2=OPERATIONAL

# Priority violations
reality_priority_violations_total{domain="execution",operation="execute"} 42

# Mode transitions
reality_mode_transitions_total{from_mode="BLIND",to_mode="SIGHTED_DEGRADED"} 1
```

#### Latency & Performance
```prometheus
# Assertion evaluation latency
reality_assertion_eval_latency_ms 15.5

# Priority decision latency
reality_priority_decision_latency_ms 2.3
```

#### Safety & Compliance
```prometheus
# Safety check status
reality_safety_checks_passed{check_name="assertion_coverage"} 1

# Rollback events
reality_mode_rollbacks_total{reason="safety_check_failure"} 0
```

### Alert Conditions

#### Critical Alerts
- Valid assertions per core domain < 3 for >5 minutes
- Any execution allowed in SIGHTED_DEGRADED mode
- Priority violations > 10 per minute
- Mode rollbacks outside maintenance windows

#### Warning Alerts
- Query rate limits exceeded
- Assertion evaluation latency > 100ms
- Feed latency > threshold
- Domain health score < 70%

### Dashboards

#### System Overview
- Current mode and blind spots
- Valid assertions per domain
- Recent mode transitions
- Priority violation rate

#### Domain Health
- Per-domain assertion counts
- Feed latency and staleness
- Query rates and limits
- Health scores

#### Safety & Compliance
- Safety check status
- Audit trail completeness
- Mode transition history
- Rollback events

## Deployment Configuration

### Feature Flags

```yaml
feature_flags:
  reality_layer_enabled: true
  priority_system_enabled: true
  enhanced_logging: true
  strict_mode: false
  debug_mode: false
```

### Environment Variables

```bash
# Core configuration
MERID_ENVIRONMENT=production
MERID_API_BASE_URL=https://api.merid.com
MERID_LOG_LEVEL=INFO

# Safety thresholds
MERID_MIN_ASSERTIONS_PER_DOMAIN=5
MERID_VALID_ASSERTION_THRESHOLD=0.8
MERID_FEED_LATENCY_THRESHOLD_MS=5000

# Rate limiting
MERID_RATE_LIMIT_WINDOW_SECONDS=60
MERID_MAX_QUERIES_PER_MINUTE=1000

# Monitoring
MERID_METRICS_PORT=9090
MERID_HEALTH_CHECK_PORT=8080
```

### Security Configuration

```yaml
security:
  sast_enabled: true
  dependency_scanning: true
  secrets_scanning: true
  license_checking: true
  
  compliance:
    audit_logging: true
    sox_compliance: true
    data_retention_days: 2555  # 7 years
    
  access_control:
    rbac_enabled: true
    mfa_required: true
    audit_trail: true
```

## Operational Procedures

### Deployment Checklist

#### Pre-Deployment
- [ ] All unit tests pass (≥90% coverage)
- [ ] Integration tests pass
- [ ] Fault injection tests pass
- [ ] Security scans pass
- [ ] Feature flags configured
- [ ] Monitoring dashboards ready
- [ ] Rollback procedures documented

#### Deployment Steps
1. Deploy to staging environment
2. Run end-to-end scenarios
3. Verify safety checks pass
4. Deploy to production (canary)
5. Monitor metrics for 5 minutes
6. Run health checks
7. Validate audit trail
8. Complete full deployment

#### Post-Deployment
- [ ] Health checks pass
- [ ] Metrics within normal ranges
- [ ] No critical alerts
- [ ] Audit trail complete
- [ ] Performance baseline met

### Incident Response

#### Critical Incidents
1. **System Mode Rollback**
   - Trigger: Safety check failures, critical violations
   - Action: Automatic rollback to BLIND mode
   - Monitoring: Mode transitions, violation rates

2. **Priority System Failure**
   - Trigger: Priority manager malfunction
   - Action: Disable priority system, fail-safe defaults
   - Monitoring: Domain access patterns, error rates

3. **Feed Degradation**
   - Trigger: Market/onchain feed issues
   - Action: Domain degradation, conservative mode
   - Monitoring: Feed latency, assertion validity

#### Escalation Procedures
1. **Level 1**: Automated alerts, auto-rollback
2. **Level 2**: On-call engineer, manual intervention
3. **Level 3**: Incident commander, cross-team coordination
4. **Level 4**: Executive notification, regulatory reporting

### Maintenance Procedures

#### Scheduled Maintenance
- Update assertion thresholds
- Refresh feature flags
- Rotate encryption keys
- Update compliance rules
- Performance tuning

#### Emergency Maintenance
- Critical security patches
- System stability issues
- Regulatory compliance updates
- Data integrity concerns

## Compliance & Audit

### SOX Compliance

#### Audit Trail Requirements
- Immutable JSONL logging
- Complete mode transition history
- Priority violation tracking
- Access control logs
- Change management records

#### Data Retention
- Audit logs: 7 years
- Metrics data: 2 years
- Configuration history: 5 years
- Incident reports: 7 years

### Regulatory Reporting

#### Daily Reports
- System mode summary
- Assertion coverage metrics
- Priority violation statistics
- Health check results

#### Weekly Reports
- Mode transition analysis
- Compliance score trends
- Risk assessment updates
- Performance metrics

#### Monthly Reports
- Comprehensive compliance review
- Risk assessment summary
- Audit trail validation
- Regulatory compliance status

## Troubleshooting Guide

### Common Issues

#### Mode Transition Failures
**Symptoms**: System stuck in BLIND mode, safety check failures
**Causes**: Insufficient assertions, feed issues, clock skew
**Solutions**: 
- Check assertion counts per domain
- Verify feed connectivity and latency
- Validate system time synchronization
- Review safety check logs

#### Priority Violations
**Symptoms**: High violation rates, blocked operations
**Causes**: Misconfigured rules, agent misbehavior, system bugs
**Solutions**:
- Review domain priority configuration
- Check agent behavior logs
- Validate caller context
- Update priority rules if needed

#### Performance Issues
**Symptoms**: High latency, slow response times
**Causes**: Resource exhaustion, assertion engine overload
**Solutions**:
- Monitor resource utilization
- Optimize assertion evaluation
- Scale horizontally if needed
- Tune rate limiting parameters

### Debug Tools

#### System Status
```bash
# Check current mode and assertions
curl http://localhost:8001/api/v1/reality/status

# Check domain priority status
curl http://localhost:8001/api/v1/domain-priority/status

# Get recent violations
curl http://localhost:8001/api/v1/domain-priority/violations
```

#### Health Checks
```bash
# System health
curl http://localhost:8001/health

# Metrics endpoint
curl http://localhost:8001/metrics

# Audit trail status
curl http://localhost:8001/api/v1/reality/audit/status
```

## Future Enhancements

### Planned Features

#### Enhanced Safety
- Machine learning-based anomaly detection
- Predictive failure prevention
- Advanced conflict resolution
- Dynamic threshold adjustment

#### Performance Optimization
- Distributed assertion evaluation
- Caching strategies
- Load balancing
- Resource pooling

#### Compliance Automation
- Automated regulatory reporting
- Compliance score calculation
- Risk assessment automation
- Audit trail optimization

### Research Areas

#### Advanced Algorithms
- Multi-criteria decision making
- Fuzzy logic for priority resolution
- Bayesian inference for uncertainty
- Reinforcement learning for optimization

#### Integration Points
- External trading systems
- Regulatory reporting systems
- Risk management platforms
- Compliance monitoring tools

## Conclusion

The MERID domain priority system with SIGHTED_DEGRADED mode provides a robust, production-ready framework for safe autonomous operation. The comprehensive testing strategy, monitoring infrastructure, and compliance framework ensure reliable operation in regulated environments.

The system's "hard-safe, soft-aware" approach balances safety with functionality, ensuring that critical operations are blocked while maintaining essential observation capabilities. The extensive CI/CD pipeline and automated testing provide confidence in deployments and operational stability.

This blueprint serves as a comprehensive guide for deploying, operating, and maintaining the system in production environments, with specific attention to regulatory compliance, operational excellence, and continuous improvement.

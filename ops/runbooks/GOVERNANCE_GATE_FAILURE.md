# Governance Gate Failure Runbook
**Runbook ID:** OPS-002  
**Service:** Governance System  
**Severity:** Critical  
**Team:** Operations  
**Last Updated:** 2026-01-26

---

## Overview

This runbook provides procedures for responding to governance gate failures, including Technical Readiness Gate, Cohort Gate, and Stress Test Gate failures.

---

## Alert Triggers

- **Alert:** Technical_Readiness_Gate_Failed (Critical)
- **Alert:** Cohort_Governance_Gate_Failed (Critical)  
- **Alert:** Stress_Test_Gate_Failed (Critical)
- **Dashboard:** http://grafana.merid.com/d/governance-gates

---

## Gate Impact Assessment

### Technical Readiness Gate Failure
- **Impact:** Blocks ALL SIGHTED_LIVE promotions
- **Scope:** Infrastructure, CI/CD, Service Reliability
- **Business Impact:** Production deployment blocked

### Cohort Gate Failure
- **Impact:** Blocks cohort-based operations
- **Scope:** Agent swarm coordination
- **Business Impact:** Swarm operations suspended

### Stress Test Gate Failure
- **Impact:** Blocks high-load operations
- **Scope:** Performance validation
- **Business Impact:** Limited operational capacity

---

## Initial Assessment (T+0-5 minutes)

### 1. Verify Gate Status
```bash
# Check Technical Readiness Gate
curl -s http://localhost:8000/api/v1/governance/technical-readiness | jq .

# Check Cohort Gate
curl -s http://localhost:8000/api/v1/governance/cohort-status | jq .

# Check Stress Test Gate
curl -s http://localhost:8000/api/v1/governance/stress-test-status | jq .
```

### 2. Identify Failed Gate Components
```bash
# Check individual gate components
curl -s http://localhost:8000/api/v1/governance/gate-details | jq '.gates[] | select(.status == "FAIL")'

# Check recent gate evaluations
curl -s http://localhost:8000/api/v1/governance/gate-history | jq '.[-5:]'
```

### 3. Determine Failure Type
- [ ] **Configuration Issue** - Gate configuration invalid
- [ ] **Infrastructure Issue** - Required services down
- [ ] **Evidence Stale** - Evidence files outdated
- [ ] **Test Failure** - Validation tests failing
- [ ] **Security Issue** - Security scan failures

---

## Immediate Response (T+5-15 minutes)

### 1. Check Required Evidence Files
```bash
# Technical Readiness Gate evidence
ls -la infra/firewall-rules.yml infra/tls-config.yml infra/rbac-config.yml
ls -la .github/workflows/audit-gates.yml
ls -la core/resilience.py core/tracing.py

# Check file timestamps
find infra/ .github/ core/ -name "*.yml" -o -name "*.py" -exec stat -c "%Y %n" {} \; | sort -n
```

### 2. Validate Gate Configuration
```bash
# Check gate configuration
curl -s http://localhost:8000/api/v1/governance/gate-config | jq .

# Validate configuration syntax
python -c "import yaml; yaml.safe_load(open('governance/technical_readiness_gate.py'))"
```

### 3. Check Dependencies
```bash
# Check if required services are running
docker ps | grep -E "(prometheus|grafana|alertmanager)"

# Check monitoring stack
curl -f http://localhost:9090/api/v1/status/config || echo "Prometheus down"
curl -f http://localhost:3000/api/health || echo "Grafana down"
```

---

## Investigation (T+15-60 minutes)

### Scenario 1: Evidence Files Missing or Stale

#### Check Evidence Freshness
```bash
# Check if evidence files are recent (within 24 hours)
find . -name "*.yml" -o -name "*.py" -mtime -1 | grep -E "(infra|governance|core)"

# Check last gate evaluation
curl -s http://localhost:8000/api/v1/governance/last-evaluation | jq '.timestamp'
```

#### Refresh Evidence
```bash
# Update file timestamps if needed
touch infra/firewall-rules.yml infra/tls-config.yml infra/rbac-config.yml
touch .github/workflows/audit-gates.yml
touch core/resilience.py core/tracing.py

# Re-run gate evaluation
curl -X POST http://localhost:8000/api/v1/governance/evaluate-gates
```

### Scenario 2: Infrastructure Dependencies Down

#### Check Service Health
```bash
# Check all required services
services=("prometheus" "grafana" "alertmanager" "merid-api" "neo4j" "redis")

for service in "${services[@]}"; do
    echo "Checking $service..."
    docker ps | grep $service || echo "$service is down"
done
```

#### Restart Critical Services
```bash
# Restart monitoring stack
docker-compose restart prometheus grafana alertmanager

# Restart MERID services
docker-compose restart merid-api neo4j redis

# Wait for services to start
sleep 30
```

### Scenario 3: Configuration Issues

#### Validate Gate Configuration
```bash
# Check gate configuration syntax
python -c "
import sys
sys.path.append('.')
from governance.technical_readiness_gate import technical_readiness_gate
status = technical_readiness_gate.check_all_gates()
print(f'Gate status: {status.overall_status}')
for gate in status.gate_results:
    print(f'{gate.gate_name}: {gate.status} - {gate.issues}')
"
```

#### Fix Configuration Issues
```bash
# Update gate configuration if needed
# Edit governance/technical_readiness_gate.py

# Reload gate configuration
curl -X POST http://localhost:8000/api/v1/governance/reload-config
```

### Scenario 4: Test Failures

#### Run Manual Gate Tests
```bash
# Run security validation tests
python -m pytest tests/security/test_gate_validation.py -v

# Run resilience tests
python -m pytest tests/integration/test_resilience_gates.py -v

# Check test results
echo "Exit code: $?"
```

#### Fix Test Issues
```bash
# Update test configurations
# Fix failing tests in tests/ directory

# Re-run tests
python -m pytest tests/ -v
```

---

## Resolution Procedures

### 1. Technical Readiness Gate Recovery

#### Step 1: Verify All Evidence
```bash
# Ensure all required files exist
required_files=(
    "infra/firewall-rules.yml"
    "infra/tls-config.yml" 
    "infra/rbac-config.yml"
    ".github/workflows/audit-gates.yml"
    "core/resilience.py"
    "core/tracing.py"
)

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "Missing required file: $file"
        # Restore from backup or recreate
    fi
done
```

#### Step 2: Validate Infrastructure
```bash
# Test firewall rules
nmap -p 8000,8001,7687,6379 localhost

# Test TLS configuration
openssl s_client -connect localhost:8443 -showcerts

# Test RBAC
docker exec merid-api whoami
```

#### Step 3: Re-evaluate Gate
```bash
# Force gate re-evaluation
curl -X POST http://localhost:8000/api/v1/governance/evaluate-technical-readiness

# Check results
curl -s http://localhost:8000/api/v1/governance/technical-readiness | jq '.overall_status'
```

### 2. Cohort Gate Recovery

#### Step 1: Check Agent Health
```bash
# Check agent status
curl -s http://localhost:8000/api/v1/agents/status | jq '.agents[] | select(.health < 0.8)'

# Restart unhealthy agents
curl -X POST http://localhost:8000/api/v1/agents/restart -d '{"agent_id": "unhealthy-agent"}'
```

#### Step 2: Validate Swarm Coordination
```bash
# Check swarm consensus
curl -s http://localhost:8000/api/v1/swarm/consensus | jq '.status'

# Restart swarm if needed
curl -X POST http://localhost:8000/api/v1/swarm/restart
```

### 3. Stress Test Gate Recovery

#### Step 1: Run Stress Test
```bash
# Execute stress test
python tests/stress/test_resilience_under_load.py

# Check results
echo "Stress test exit code: $?"
```

#### Step 2: Update Gate Status
```bash
# Update stress test gate status
curl -X POST http://localhost:8000/api/v1/governance/update-stress-test-status \
  -d '{"status": "PASS", "evidence": "stress_test_report.html"}'
```

---

## Communication Procedures

### 1. Internal Communication
- **Slack Channel:** #merid-governance-alerts
- **PagerDuty:** Notify on-call engineer
- **Stakeholder Update:** Every 15 minutes until resolved

### 2. Status Update Template
```
[INCIDENT] Governance Gate Failure - T+{time}m

Gate: {Technical_Readiness|Cohort|Stress_Test}
Status: {INVESTIGATING|RECOVERING|RESOLVED}
Impact: {Production blocked|Swarm suspended|Limited capacity}
ETA: {Unknown|15 minutes|1 hour}
Actions: {Current actions being taken}
Next Update: {time}
```

### 3. Escalation Matrix
- **Level 1:** On-call Operations Engineer
- **Level 2:** Operations Lead + Engineering Lead
- **Level 3:** CTO + Governance Board
- **Level 4:** Executive Committee

---

## Recovery Verification

### 1. Gate Status Verification
```bash
# Verify all gates are passing
curl -s http://localhost:8000/api/v1/governance/all-gates | jq '.gates[] | select(.status != "PASS")'

# Check promotion eligibility
curl -s http://localhost:8000/api/v1/governance/can-promote-to-sighted-live | jq '.allowed'
```

### 2. End-to-End Validation
```bash
# Test promotion workflow
curl -X POST http://localhost:8000/api/v1/governance/test-promotion \
  -d '{"target_mode": "SIGHTED_LIVE"}' | jq '.allowed'

# Verify monitoring integration
curl -s http://localhost:9090/api/v1/query?query=merid_technical_readiness_gate_status
```

### 3. Business Impact Validation
```bash
# Confirm production deployment is possible
curl -s http://localhost:8000/api/v1/governance/deployment-readiness | jq '.ready'

# Verify swarm operations
curl -s http://localhost:8000/api/v1/swarm/operational-status | jq '.status'
```

---

## Post-Incident Actions

### 1. Documentation
- [ ] Update incident report with root cause
- [ ] Document gate failure patterns
- [ ] Update runbooks with lessons learned
- [ ] Create post-mortem presentation

### 2. Prevention Measures
- [ ] Implement automated gate health checks
- [ ] Add evidence freshness monitoring
- [ ] Improve alerting for gate degradation
- [ ] Schedule regular gate validation

### 3. System Improvements
- [ ] Add gate redundancy and failover
- [ ] Implement automated evidence refresh
- [ ] Enhance gate diagnostic tools
- [ ] Improve monitoring and alerting

---

## Known Issues and Workarounds

### Issue: Evidence File Timestamps
**Symptoms:** Gates fail due to "stale" evidence
**Workaround:** Touch evidence files to update timestamps
**Permanent Fix:** Implement automated evidence validation

### Issue: Monitoring Stack Dependencies
**Symptoms:** Gates fail when monitoring is down
**Workaround:** Implement monitoring stack health checks
**Permanent Fix:** Add monitoring stack redundancy

### Issue: Gate Configuration Drift
**Symptoms:** Configuration changes cause gate failures
**Workaround:** Version control gate configurations
**Permanent Fix:** Implement configuration validation

---

## Contacts and Resources

### Team Contacts
- **On-call Engineer:** ops-oncall@merid.com
- **Operations Lead:** ops-lead@merid.com
- **Engineering Lead:** eng-lead@merid.com
- **Governance Board:** governance@merid.com

### External Resources
- **Dashboard:** http://grafana.merid.com/d/governance-gates
- **Documentation:** https://docs.merid.com/governance
- **Status Page:** http://status.merid.com

### Tools and Commands
- **Gate API:** `curl /api/v1/governance/*`
- **Docker:** `docker ps`, `docker logs`, `docker restart`
- **System:** `find`, `stat`, `python -m pytest`

---

## Runbook Maintenance

- **Review Date:** Monthly
- **Last Updated:** 2026-01-26
- **Next Review:** 2026-02-26
- **Owner:** Operations Team

---

**Runbook Status:** ✅ **ACTIVE**  
**Approval:** Operations Lead + Governance Board  
**Version:** 1.0

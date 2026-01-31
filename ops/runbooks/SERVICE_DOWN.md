# Service Down Runbook
**Runbook ID:** OPS-001  
**Service:** MERID API  
**Severity:** Critical  
**Team:** Operations  
**Last Updated:** 2026-01-26

---

## Overview

This runbook provides step-by-step procedures for responding to MERID API service downtime or degradation incidents.

---

## Alert Triggers

- **Alert:** MERID_API_Down (Critical)
- **Condition:** `up{job="merid-api"} == 0` for 1 minute
- **Dashboard:** http://grafana.merid.com/d/system-health

---

## Initial Assessment (T+0-5 minutes)

### 1. Verify Alert Validity
```bash
# Check if API is actually down
curl -f http://localhost:8000/health || echo "API confirmed down"

# Check Prometheus metrics
curl -s http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22merid-api%22%7D

# Check container status
docker ps | grep merid-api
```

### 2. Gather Context
```bash
# Check recent deployments
kubectl rollout history deployment/merid-api --namespace=merid-prod

# Check recent logs
docker logs merid-api --tail=100

# Check system resources
docker stats merid-api
```

### 3. Determine Impact Scope
- [ ] **API completely down** - No responses
- [ ] **API degraded** - Slow responses or errors
- [ ] **Partial outage** - Specific endpoints failing
- [ ] **Database connectivity** - Check if API can reach databases

---

## Immediate Response (T+5-15 minutes)

### 1. Quick Recovery Attempts

#### Option A: Service Restart
```bash
# Restart Docker container
docker restart merid-api

# Or restart Kubernetes deployment
kubectl rollout restart deployment/merid-api --namespace=merid-prod

# Wait for restart
sleep 30
```

#### Option B: Health Check Investigation
```bash
# Check health endpoint
curl -v http://localhost:8000/health

# Check specific endpoints
curl -v http://localhost:8000/api/v1/health
curl -v http://localhost:8000/api/v1/reality/status
```

#### Option C: Resource Check
```bash
# Check memory usage
docker stats merid-api --no-stream

# Check disk space
df -h

# Check port availability
netstat -tlnp | grep :8000
```

### 2. Escalation Criteria
Escalate to Level 2 if:
- [ ] Service doesn't recover after restart
- [ ] Database connectivity issues detected
- [ ] Multiple services affected
- [ ] Security incident suspected

---

## Investigation (T+15-60 minutes)

### 1. Log Analysis
```bash
# Check application logs
docker logs merid-api --since 1h | grep -i error

# Check system logs
journalctl -u merid-api --since 1h

# Check database logs
docker logs neo4j --tail=50
docker logs redis --tail=50
```

### 2. Dependency Health Check
```bash
# Check Neo4j
curl -f http://localhost:7474 || echo "Neo4j down"

# Check Redis
redis-cli ping || echo "Redis down"

# Check Jaeger
curl -f http://localhost:16686 || echo "Jaeger down"
```

### 3. Network Diagnostics
```bash
# Check network connectivity
telnet localhost 8000

# Check DNS resolution
nslookup localhost

# Check firewall rules
iptables -L -n | grep 8000
```

### 4. Performance Analysis
```bash
# Check system load
top
htop

# Check memory usage
free -h

# Check disk I/O
iostat -x 1
```

---

## Resolution Procedures

### Scenario 1: Container Crash
```bash
# Check container exit code
docker inspect merid-api | grep ExitCode

# Remove dead container
docker rm merid-api

# Recreate container
docker-compose up -d merid-api

# Verify health
curl -f http://localhost:8000/health
```

### Scenario 2: Database Connection Issues
```bash
# Check Neo4j connectivity
cypher-shell -u neo4j -p password "RETURN 1"

# Check Redis connectivity
redis-cli ping

# Restart database services if needed
docker-compose restart neo4j redis
```

### Scenario 3: Resource Exhaustion
```bash
# Check memory usage
docker stats merid-api

# Scale up resources if needed
kubectl patch deployment merid-api -p '{"spec":{"template":{"spec":{"containers":[{"name":"merid-api","resources":{"limits":{"memory":"2Gi"}}}}}}}' --namespace=merid-prod

# Or restart with more resources
docker-compose down && docker-compose up -d --scale merid-api=2
```

### Scenario 4: Port Conflicts
```bash
# Check port usage
netstat -tlnp | grep :8000

# Kill conflicting processes
kill -9 $(lsof -ti:8000)

# Restart service
docker-compose restart merid-api
```

---

## Communication Procedures

### 1. Internal Communication
- **Slack Channel:** #merid-ops-alerts
- **PagerDuty:** Notify on-call engineer
- **Stakeholder Update:** Every 15 minutes until resolved

### 2. Status Update Template
```
[INCIDENT] MERID API Service Down - T+{time}m

Status: {INVESTIGATING|RECOVERING|RESOLVED}
Impact: {API completely down|API degraded|Partial outage}
ETA: {Unknown|5 minutes|30 minutes}
Actions: {Current actions being taken}
Next Update: {time}
```

### 3. Escalation Contacts
- **Level 1:** On-call Operations Engineer
- **Level 2:** Operations Lead (+1-555-XXX-XXXX)
- **Level 3:** Engineering Manager (+1-555-XXX-XXXX)
- **Level 4:** CTO (+1-555-XXX-XXXX)

---

## Recovery Verification

### 1. Service Health Check
```bash
# Basic health check
curl -f http://localhost:8000/health

# Detailed health check
curl -f http://localhost:8000/api/v1/health

# Reality system check
curl -f http://localhost:8000/api/v1/reality/status
```

### 2. Performance Validation
```bash
# Load test
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/health

# Check response times
curl -w "%{time_total}\n" -o /dev/null -s http://localhost:8000/api/v1/health
```

### 3. End-to-End Validation
```bash
# Test critical endpoints
curl -f http://localhost:8000/api/v1/charters
curl -f http://localhost:8000/api/v1/governance/status
curl -f http://localhost:8000/api/v1/reality/assertions
```

---

## Post-Incident Actions

### 1. Documentation
- [ ] Update incident report with timeline
- [ ] Document root cause and resolution
- [ ] Update runbook with lessons learned
- [ ] Create post-mortem report

### 2. Prevention Measures
- [ ] Implement monitoring improvements
- [ ] Add automated recovery procedures
- [ ] Update alert thresholds
- [ ] Schedule follow-up review

### 3. System Improvements
- [ ] Review resource allocation
- [ ] Implement health check improvements
- [ ] Add circuit breaker patterns
- [ ] Enhance logging and observability

---

## Known Issues and Workarounds

### Issue: Container Memory Leaks
**Symptoms:** Gradual memory increase, eventual OOM
**Workaround:** Restart container every 24 hours
**Permanent Fix:** Memory leak investigation and patch

### Issue: Database Connection Pool Exhaustion
**Symptoms:** Database connection errors under load
**Workaround:** Increase pool size temporarily
**Permanent Fix:** Implement connection pooling optimization

### Issue: Port Binding Conflicts
**Symptoms:** Service fails to start on port 8000
**Workaround:** Kill conflicting processes
**Permanent Fix:** Implement proper port management

---

## Contacts and Resources

### Team Contacts
- **On-call Engineer:** ops-oncall@merid.com
- **Operations Lead:** ops-lead@merid.com
- **Engineering Manager:** eng-manager@merid.com

### External Resources
- **Dashboard:** http://grafana.merid.com/d/system-health
- **Documentation:** https://docs.merid.com
- **Status Page:** http://status.merid.com

### Tools and Commands
- **Docker:** `docker logs`, `docker stats`, `docker ps`
- **Kubernetes:** `kubectl logs`, `kubectl describe`, `kubectl get`
- **Monitoring:** `curl` endpoints, Prometheus queries
- **System:** `top`, `htop`, `iostat`, `netstat`

---

## Runbook Maintenance

- **Review Date:** Monthly
- **Last Updated:** 2026-01-26
- **Next Review:** 2026-02-26
- **Owner:** Operations Team

---

**Runbook Status:** ✅ **ACTIVE**  
**Approval:** Operations Lead  
**Version:** 1.0

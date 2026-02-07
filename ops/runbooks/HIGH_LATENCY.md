# High Latency Runbook
**Runbook ID:** OPS-005  
**Service:** API Performance  
**Severity:** Warning  
**Team:** Operations + Engineering  
**Last Updated:** 2026-01-26

---

## Overview

This runbook provides procedures for responding to high latency issues affecting API response times and user experience.

---

## Alert Triggers

- **Alert:** MERID_API_High_Latency (Warning)
- **Condition:** P95 response time > 2.0s for 5 minutes
- **Dashboard:** http://grafana.merid.com/d/api-performance
- **Runbook:** https://docs.merid.com/runbooks/HIGH_LATENCY

---

## Latency Thresholds

### **Warning (P1)**
- P95 latency > 2.0s for 5 minutes
- P99 latency > 5.0s for 5 minutes
- Average response time > 1.0s for 5 minutes

### **Critical (P0)**
- P95 latency > 5.0s for 2 minutes
- P99 latency > 10.0s for 2 minutes
- Average response time > 3.0s for 2 minutes

---

## Initial Assessment (T+0-5 minutes)

### 1. Verify Latency Metrics
```bash
# Check current latency metrics
curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,rate(http_request_duration_seconds_bucket[5m]))"

# Check API health
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/health

# Check system load
uptime
docker stats merid-api --no-stream
```

### 2. Identify Scope
- [ ] **API-wide** - All endpoints affected
- [ ] **Specific endpoints** - Only certain endpoints slow
- [ ] **User-specific** - Only certain users affected
- [ ] **Time-based** - Latency spikes at specific times

### 3. Check Recent Changes
```bash
# Check recent deployments
kubectl rollout history deployment/merid-api --namespace=merid-prod

# Check recent commits
git log --oneline --since="2 hours ago"

# Check configuration changes
git diff HEAD~1 -- config/
```

---

## Investigation (T+5-30 minutes)

### 1. System Resource Analysis
```bash
# Check CPU usage
top -p $(pgrep -f merid-api)
docker stats merid-api --no-stream

# Check memory usage
free -h
docker exec merid-api free -h

# Check disk I/O
iostat -x 1 5 | grep -E "(Device|merid)"

# Check network I/O
sar -n DEV 1 5 | grep -E "(eth0|ens|enp)"
```

### 2. Database Performance
```bash
# Check Neo4j query performance
docker exec neo4j cypher-shell -u neo4j -p password "
CALL dbms.listQueries() YIELD queryId, query, elapsedTime 
RETURN queryId, elapsedTime, query 
ORDER BY elapsedTime DESC 
LIMIT 10"

# Check Redis performance
docker exec redis redis-cli info stats
docker exec redis redis-cli info commandstats

# Check connection pool usage
docker exec neo4j cypher-shell -u neo4j -p password "SHOW DATABASES"
```

### 3. Application Performance
```bash
# Check application logs for errors
docker logs merid-api --tail=100 | grep -i "error\|timeout\|slow"

# Check request patterns
grep -o "endpoint=[^ ]*" /var/log/merid/api.log | sort | uniq -c | sort -nr | head -10

# Check for blocking operations
grep -i "blocking\|waiting\|queue" /var/log/merid/api.log | tail -20
```

---

## Resolution Procedures

### Scenario 1: Resource Exhaustion

#### CPU High Usage
```bash
# Identify CPU-intensive processes
docker exec merid-api ps aux --sort=-%cpu | head -10

# Scale up if needed
kubectl scale deployment merid-api --replicas=3 --namespace=merid-prod

# Add CPU limits if missing
kubectl patch deployment merid-api -p '{"spec":{"template":{"spec":{"containers":[{"name":"merid-api","resources":{"limits":{"cpu":"2000m"}}}]}}}}' --namespace=merid-prod
```

#### Memory High Usage
```bash
# Check memory usage by process
docker exec merid-api ps aux --sort=-%mem | head -10

# Restart service to free memory
docker restart merid-api

# Add memory limits
kubectl patch deployment merid-api -p '{"spec":{"template":{"spec":{"containers":[{"name":"merid-api","resources":{"limits":{"memory":"4Gi"}}}]}}}}' --namespace=merid-prod
```

### Scenario 2: Database Performance Issues

#### Slow Neo4j Queries
```bash
# Identify slow queries
docker exec neo4j cypher-shell -u neo4j -p password "
CALL dbms.listQueries() YIELD queryId, query, elapsedTime 
RETURN queryId, elapsedTime, query 
WHERE elapsedTime > 1000
ORDER BY elapsedTime DESC"

# Kill long-running queries
docker exec neo4j cypher-shell -u neo4j -p password "CALL dbms.killQuery('query-id')"

# Restart Neo4j if needed
docker restart neo4j
```

#### Redis Performance Issues
```bash
# Check Redis memory usage
docker exec redis redis-cli info memory

# Clear expired keys
docker exec redis redis-cli --scan --pattern "*expired*" | xargs docker exec redis redis-cli del

# Restart Redis if needed
docker restart redis
```

### Scenario 3: Application Issues

#### Recent Deployment Issues
```bash
# Rollback to previous version
kubectl rollout undo deployment/merid-api --namespace=merid-prod

# Wait for rollback
kubectl rollout status deployment/merid-api --namespace=merid-prod

# Verify latency improved
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/health
```

#### Configuration Issues
```bash
# Check recent configuration changes
git diff HEAD~1 -- config/

# Reload configuration
docker restart merid-api

# Verify configuration
curl -s http://localhost:8000/api/v1/config | jq .
```

---

## Performance Optimization

### 1. Database Optimization
```bash
# Create missing indexes
docker exec neo4j cypher-shell -u neo4j -p password "
CREATE INDEX assertion_created_at IF NOT EXISTS FOR (a:Assertion) ON (a.created_at)
"

# Update database statistics
docker exec neo4j cypher-shell -u neo4j -p password "CALL db.stats.retrieve('GRAPH COUNTS')"

# Optimize Redis memory
docker exec redis redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

### 2. Application Optimization
```bash
# Enable application caching
echo "cache_enabled = true" >> /etc/merid/config.yml
echo "cache_ttl = 300" >> /etc/merid/config.yml

# Restart with new configuration
docker restart merid-api

# Verify caching is working
curl -I http://localhost:8000/api/v1/health | grep -i cache
```

### 3. Infrastructure Optimization
```bash
# Add more replicas if needed
kubectl scale deployment merid-api --replicas=5 --namespace=merid-prod

# Add horizontal pod autoscaler
kubectl autoscale deployment merid-api --cpu-percent=70 --min=2 --max=10 --namespace=merid-prod

# Verify autoscaler status
kubectl get hpa --namespace=merid-prod
```

---

## Monitoring and Validation

### 1. Real-time Monitoring
```bash
# Watch latency metrics in real-time
watch -n 5 'curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,rate(http_request_duration_seconds_bucket[5m]))" | jq -r ".data.result[0].value[1]"'

# Watch system resources
watch -n 5 'docker stats merid-api --no-stream'

# Watch database performance
watch -n 10 'docker exec redis redis-cli info stats | grep instantaneous'
```

### 2. Load Testing
```bash
# Run simple load test
ab -n 100 -c 10 http://localhost:8000/api/v1/health

# Check latency under load
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/health

# Verify system handles load
docker stats merid-api --no-stream
```

### 3. Performance Validation
```bash
# Check all critical endpoints
endpoints=(
    "/api/v1/health"
    "/api/v1/reality/status"
    "/api/v1/charters"
    "/api/v1/governance/status"
)

for endpoint in "${endpoints[@]}"; do
    echo "Testing $endpoint..."
    curl -w "@curl-format.txt" -o /dev/null -s "http://localhost:8000$endpoint"
    echo ""
done
```

---

## Communication Procedures

### 1. Internal Communication
- **Performance Channel:** #merid-performance-alerts
- **PagerDuty:** Engineering team on-call
- **Stakeholder Updates:** Every 30 minutes during degradation

### 2. Status Update Template
```
[HIGH LATENCY] - T+{time}m

Severity: {WARNING|CRITICAL}
Current P95: {current latency}s
Baseline P95: {baseline latency}s
Impact: {User experience affected}
Actions: {Current optimization actions}
ETA: {Expected recovery time}
Next Update: {time}
```

---

## Escalation Matrix

### **Level 1: On-call Engineer**
- **Contact:** eng-oncall@merid.com
- **Response Time:** 15 minutes
- **Authority:** Basic troubleshooting, restarts

### **Level 2: Engineering Lead**
- **Contact:** eng-lead@merid.com, +1-555-XXX-XXXX
- **Response Time:** 30 minutes
- **Authority:** Scaling, configuration changes, rollbacks

### **Level 3: CTO**
- **Contact:** cto@merid.com, +1-555-XXX-XXXX
- **Response Time:** 1 hour
- **Authority:** Major architectural decisions, service impact

---

## Post-Incident Actions

### 1. Documentation
- [ ] Complete incident report with timeline
- [ ] Document root cause and impact
- [ ] Update performance procedures
- [ ] Create post-mortem presentation

### 2. Prevention Measures
- [ ] Implement automated scaling
- [ ] Add performance monitoring
- [ ] Optimize database queries
- [ ] Implement caching strategies

### 3. System Improvements
- [ ] Add performance benchmarks
- [ ] Implement load testing
- [ ] Enhance monitoring and alerting
- [ ] Improve capacity planning

---

## Known Issues and Workarounds

### Issue: Database Query Performance
**Symptoms:** Gradual increase in query response times
**Workaround:** Restart database, optimize queries
**Permanent Fix:** Query optimization, indexing strategy

### Issue: Memory Leaks
**Symptoms:** Gradual memory increase, latency spikes
**Workaround:** Restart service periodically
**Permanent Fix:** Memory leak investigation and patch

### Issue: Resource Contention
**Symptoms:** Latency spikes under load
**Workaround:** Scale out services
**Permanent Fix:** Load balancing, resource optimization

---

## Contacts and Resources

### Engineering Team
- **On-call Engineer:** eng-oncall@merid.com
- **Engineering Lead:** eng-lead@merid.com
- **CTO:** cto@merid.com

### External Resources
- **Performance Dashboard:** http://grafana.merid.com/d/api-performance
- **Performance Documentation:** https://docs.merid.com/performance
- **Load Testing Tools:** https://docs.merid.com/load-testing

### Tools and Commands
- **Performance:** `curl`, `ab`, `wrk`, `docker stats`
- **Database:** `cypher-shell`, `redis-cli`
- **System:** `top`, `htop`, `iostat`, `sar`

---

## Runbook Maintenance

- **Review Date:** Monthly
- **Last Updated:** 2026-01-26
- **Next Review:** 2026-02-26
- **Owner:** Engineering Team

---

**Runbook Status:** ✅ **ACTIVE**  
**Approval:** Engineering Lead + CTO  
**Version:** 1.0

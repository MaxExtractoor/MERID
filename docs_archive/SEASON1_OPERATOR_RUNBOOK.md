# MERID Season 1 Operator Runbook

## Overview

This runbook provides step-by-step procedures for Season 1 operators to handle common incidents and operational tasks related to the MERID domain priority system and SIGHTED_DEGRADED mode.

## Quick Reference

| Incident Type | Severity | Response Time | Primary Contact |
|---------------|----------|----------------|------------------|
| Mode Rollback | CRITICAL | < 5 minutes | On-call Engineer |
| Assertion Collapse | HIGH | < 15 minutes | Risk Team |
| Priority Violation Spikes | MEDIUM | < 30 minutes | Operations |
| System Degradation | LOW | < 1 hour | DevOps |

## System Status Indicators

### Health Indicators
- **Risk Score**: 90%+ (Healthy), 75-90% (Monitor), 50-75% (Attention), <50% (Critical)
- **System Mode**: OPERATIONAL (optimal), SIGHTED_DEGRADED (monitor), BLIND (attention)
- **Valid Assertions**: 100% of expected (5 per core domain)
- **Priority Violations**: < 10 per hour (normal), 10-50 (elevated), >50 (critical)
- **Mode Transitions**: < 5 per hour (normal), 5-10 (elevated), >10 (critical)

### Key Dashboards
- **Risk Controls Dashboard**: http://localhost:8080/risk-controls-dashboard.html
- **Production Metrics**: https://grafana.merid.com/d/merid-production
- **Security Dashboard**: https://security.merid.com/d/security-overview
- **Audit Trail**: https://audit.merid.com/d/audit-trail

## Incident Procedures

### 1. Mode Rollback (CRITICAL)

**Symptoms:**
- System mode changes from SIGHTED_DEGRADED to BLIND
- Multiple safety check failures
- High number of priority violations
- System alerts indicating "CRITICAL" status

**Immediate Actions (0-5 minutes):**
1. **Check Risk Controls Dashboard**
   ```bash
   curl http://localhost:8001/api/v1/reality/status
   ```

2. **Identify Root Cause**
   ```bash
   # Check recent safety check failures
   curl http://localhost:8001/api/v1/reality/safety-checks
   
   # Check recent violations
   curl http://localhost:8001/api/v1/domain-priority/violations
   ```

3. **Stabilize System**
   ```bash
   # If in BLIND mode, check assertion health
   curl http://localhost:8001/api/v1/reality/assertions
   
   # Restore assertions if needed
   curl -X POST http://localhost:8001/api/v1/reality/restore-assertions
   ```

**Investigation (5-15 minutes):**
1. **Review Audit Trail**
   - Access: https://audit.merid.com/d/audit-trail
   - Filter: Last 30 minutes, mode transitions, safety check failures

2. **Check System Logs**
   ```bash
   # Application logs
   docker logs merid-app --tail=100
   
   # System metrics
   curl http://localhost:8001/metrics | grep reality_mode
   ```

3. **Validate Assertions**
   ```bash
   # Check assertion counts per domain
   curl http://localhost:8001/api/v1/reality/assertions | jq '.domains'
   ```

**Resolution (15-30 minutes):**
1. **Fix Root Cause**
   - If assertion loss: Reload demo data
   - If safety check failure: Fix underlying issue
   - If priority violation: Review domain configuration

2. **Restore Normal Operation**
   ```bash
   # Trigger mode transition back to SIGHTED_DEGRADED
   curl -X POST http://localhost:8001/api/v1/reality/transition-to-sighted-degraded
   ```

3. **Verify Resolution**
   ```bash
   # Confirm mode transition
   curl http://localhost:8001/api/v1/reality/status
   
   # Check risk score
   curl http://localhost:8001/api/v1/risk-controls/status
   ```

**Escalation:**
- If not resolved in 30 minutes: Escalate to Risk Team
- If system instability continues: Escalate to Engineering Lead
- If security concerns: Escalate to Security Team

### 2. Assertion Collapse (HIGH)

**Symptoms:**
- Valid assertions drop below threshold (< 80%)
- Multiple domains showing assertion failures
- Risk score drops below 75%
- System mode may rollback to BLIND

**Immediate Actions (0-15 minutes):**
1. **Assess Assertion Health**
   ```bash
   # Check assertion counts
   curl http://localhost:8001/api/v1/reality/assertions | jq '.domains'
   
   # Check assertion status by domain
   curl http://localhost:8001/api/v1/reality/assertions/market
   curl http://localhost:8001/api/v1/reality/assertions/onchain
   curl http://localhost:8001/api/v1/reality/assertions/simulation
   curl http://localhost:8001/api/v1/reality/assertions/agent
   ```

2. **Identify Failed Assertions**
   ```bash
   # Get detailed assertion status
   curl http://localhost:8001/api/v1/reality/assertions/detailed | jq '.assertions[] | select(.status != "VALID")'
   ```

3. **Check Feed Health**
   ```bash
   # Check market data feed
   curl http://localhost:8001/api/v1/market/assertions
   
   # Check onchain data feed
   curl http://localhost:8001/api/v1/onchain/assertions
   ```

**Investigation (15-30 minutes):**
1. **Review Feed Status**
   ```bash
   # Check feed latency
   curl http://localhost:8001/api/v1/feeds/status
   
   # Check feed errors
   curl http://localhost:8001/api/v1/feeds/errors
   ```

2. **Check System Resources**
   ```bash
   # Check system metrics
   docker stats merid-app
   
   # Check memory usage
   free -h
   
   # Check disk space
   df -h
   ```

3. **Review Recent Changes**
   - Check recent deployments
   - Review recent configuration changes
   - Check recent API changes

**Resolution (30-60 minutes):**
1. **Restore Assertions**
   ```bash
   # Reload demo data
   curl -X POST http://localhost:8001/api/v1/demo-data/reload
   
   # Restart assertion sources if needed
   curl -X POST http://localhost:8001/api/v1/assertion-sources/restart
   ```

2. **Fix Feed Issues**
   ```bash
   # Restart feed services
   docker restart merid-feeds
   
   # Verify feed connectivity
   curl http://localhost:8001/api/v1/feeds/health
   ```

3. **Validate Recovery**
   ```bash
   # Check assertion recovery
   curl http://localhost:8001/api/v1/reality/assertions | jq '.domains'
   
   # Verify system mode
   curl http://localhost:8001/api/v1/reality/status
   ```

### 3. Priority Violation Spikes (MEDIUM)

**Symptoms:**
- Priority violations increase significantly (> 50/hour)
- Risk score drops to 50-75%
- Multiple blocked access attempts
- Possible security concerns

**Immediate Actions (0-30 minutes):**
1. **Assess Violation Pattern**
   ```bash
   # Get recent violations
   curl http://localhost:8001/api/v1/domain-priority/violations?limit=100
   
   # Analyze violation patterns
   curl http://localhost:8001/api/v1/domain-priority/violations/analysis
   ```

2. **Identify Violation Sources**
   ```bash
   # Check actor IDs
   curl http://localhost:8001/api/v1/domain-priority/violations | jq '.violations[] | .actor_id' | sort | uniq -c
   
   # Check domain patterns
   curl http://localhost:8001/api/v1/domain-priority/violations | jq '.violations[] | .domain' | sort | uniq -c
   ```

3. **Check for Security Issues**
   ```bash
   # Check for suspicious activity
   curl http://localhost:8001/api/v1/security/analysis
   
   # Check rate limiting
   curl http://localhost:8001/api/v1/rate-limits/status
   ```

**Investigation (30-60 minutes):**
1. **Review Security Logs**
   ```bash
   # Check authentication logs
   docker logs merid-auth | grep -i "fail\|error"
   
   # Check access patterns
   curl http://localhost:8001/api/v1/access/logs
   ```

2. **Analyze Traffic Patterns**
   ```bash
   # Check API usage patterns
   curl http://localhost:8001/api/v1/metrics | grep http_requests
   
   # Check for bot activity
   curl http://localhost:8001/api/v1/security/bot-detection
   ```

**Resolution (60-90 minutes):**
1. **Block Malicious Actors**
   ```bash
   # Block suspicious IP addresses
   curl -X POST http://localhost:8001/api/v1/security/block-ip -d '{"ip": "suspicious_ip"}'
   
   # Block suspicious actors
   curl -X POST http://localhost:8001/api/v1/security/block-actor -d '{"actor_id": "suspicious_actor"}'
   ```

2. **Adjust Rate Limits**
   ```bash
   # Tighten rate limits
   curl -X POST http://localhost:8001/api/v1/rate-limits/tighten
   
   # Enable additional monitoring
   curl -X POST http://localhost:8001/api/v1/monitoring/enable-enhanced
   ```

3. **Validate Resolution**
   ```bash
   # Monitor violation rate
   watch -n 30 'curl http://localhost:8001/api/v1/domain-priority/violations | jq ".total_count"'
   ```

### 4. System Degradation (LOW)

**Symptoms:**
- Performance degradation
- Increased latency
- Resource utilization spikes
- Minor system issues

**Immediate Actions (0-60 minutes):**
1. **Assess System Performance**
   ```bash
   # Check system metrics
   curl http://localhost:8001/metrics | grep -E "(latency|memory|cpu)"
   
   # Check application health
   curl http://localhost:8001/health
   ```

2. **Check Resource Utilization**
   ```bash
   # Docker stats
   docker stats merid-app --no-stream
   
   # System resources
   top -n 1
   free -h
   df -h
   ```

**Investigation (1-2 hours):**
1. **Review Performance Metrics**
   ```bash
   # Check latency trends
   curl http://localhost:8001/api/v1/metrics/latency-trends
   
   # Check error rates
   curl http://localhost:8001/api/v1/metrics/error-rates
   ```

2. **Analyze Recent Changes**
   - Check recent deployments
   - Review configuration changes
   - Check load patterns

**Resolution (2-4 hours):**
1. **Optimize Performance**
   ```bash
   # Restart application if needed
   docker restart merid-app
   
   # Scale resources if needed
   kubectl scale deployment merid --replicas=2
   ```

2. **Monitor Recovery**
   ```bash
   # Monitor performance
   watch -n 60 'curl http://localhost:8001/health'
   ```

## Monitoring Procedures

### Daily Health Checks

**Morning Check (9:00 AM):**
1. **System Status**
   ```bash
   curl http://localhost:8001/api/v1/reality/status
   curl http://localhost:8001/api/v1/risk-controls/status
   ```

2. **Assertion Health**
   ```bash
   curl http://localhost:8001/api/v1/reality/assertions | jq '.domains'
   ```

3. **Security Status**
   ```bash
   curl http://localhost:8001/api/v1/security/status
   ```

**Evening Check (5:00 PM):**
1. **Daily Summary**
   ```bash
   curl http://localhost:8001/api/v1/daily-summary
   ```

2. **Performance Metrics**
   ```bash
   curl http://localhost:8001/api/v1/metrics/daily
   ```

### Weekly Maintenance

**Sunday Maintenance (2:00 AM):**
1. **System Backup**
   ```bash
   # Backup configuration
   curl http://localhost:8001/api/v1/backup/config
   
   # Backup audit logs
   curl http://localhost:8001/api/v1/backup/audit-logs
   ```

2. **Security Scanning**
   ```bash
   # Run security scan
   curl http://localhost:8001/api/v1/security/scan
   ```

3. **Performance Optimization**
   ```bash
   # Optimize database
   curl http://localhost:8001/api/v1/database/optimize
   
   # Clear cache
   curl http://localhost:8001/api/v1/cache/clear
   ```

## Emergency Contacts

### Primary Contacts
- **On-call Engineer**: +1-555-MERID-ONCALL
- **Risk Team**: risk@merid.com
- **Security Team**: security@merid.com
- **Engineering Lead**: engineering@merid.com

### Escalation Contacts
- **CTO**: cto@merid.com
- **Compliance Officer**: compliance@merid.com
- **Legal Counsel**: legal@merid.com

### External Contacts
- **Cloud Provider**: AWS Support
- **Security Vendor**: security-vendor@merid.com
- **Audit Firm**: audit@merid.com

## Communication Procedures

### Incident Notification

**Critical Incidents:**
1. Immediate notification to all stakeholders
2. Status update every 15 minutes
3. Resolution notification within 1 hour

**High Incidents:**
1. Notification to primary stakeholders
2. Status update every 30 minutes
3. Resolution notification within 4 hours

**Medium Incidents:**
1. Notification to operations team
2. Status update every 2 hours
3. Resolution notification within 24 hours

**Low Incidents:**
1. Notification to relevant team
2. Status update daily
3. Resolution notification within 7 days

### Status Updates

**Status Page Updates:**
- Critical: Update immediately
- High: Update within 15 minutes
- Medium: Update within 1 hour
- Low: Update within 4 hours

**Email Notifications:**
- Use standard templates
- Include incident ID, severity, and impact
- Provide ETA for resolution

## Documentation

### Incident Logging
- All incidents must be logged in the incident tracking system
- Include root cause analysis
- Document resolution steps
- Track prevention measures

### Knowledge Base
- Update runbook based on incident learnings
- Add new procedures for recurring issues
- Maintain troubleshooting guides

### Training
- Monthly training for on-call engineers
- Quarterly review of runbook procedures
- Annual security training for all staff

## Compliance Requirements

### Regulatory Reporting
- SOX compliance: Daily status reports
- FINRA compliance: Weekly risk assessments
- SEC compliance: Monthly security reports

### Audit Requirements
- Maintain audit logs for 7 years
- Regular audit trail validation
- Annual compliance audits

### Data Retention
- System logs: 90 days
- Audit logs: 7 years
- Incident reports: 7 years
- Performance metrics: 2 years

## Appendix

### Common Commands

**System Status:**
```bash
# System status
curl http://localhost:8001/api/v1/reality/status

# Risk controls status
curl http://localhost:8001/api/v1/risk-controls/status

# Health check
curl http://localhost:8001/health
```

**Assertions:**
```bash
# All assertions
curl http://localhost:8001/api/v1/reality/assertions

# Domain-specific assertions
curl http://localhost:8001/api/v1/reality/assertions/market
curl http://localhost:8001/api/v1/reality/assertions/onchain
curl http://localhost:8001/api/v1/reality/assertions/simulation
curl http://localhost:8001/api/v1/reality/assertions/agent
```

**Violations:**
```bash
# Recent violations
curl http://localhost:8001/api/v1/domain-priority/violations

# Violation analysis
curl http://localhost:8001/api/v1/domain-priority/violations/analysis
```

**Security:**
```bash
# Security status
curl http://localhost:8001/api/v1/security/status

# Security scan
curl http://localhost:8001/api/v1/security/scan
```

### Troubleshooting Guide

**Common Issues:**
1. **System won't transition to SIGHTED_DEGRADED**
   - Check assertion counts
   - Verify safety checks
   - Review system logs

2. **High violation rate**
   - Check for malicious activity
   - Review rate limits
   - Analyze traffic patterns

3. **Performance issues**
   - Check resource utilization
   - Review latency metrics
   - Analyze error rates

**Debug Commands:**
```bash
# Debug mode
curl http://localhost:8001/api/v1/debug/status

# Detailed metrics
curl http://localhost:8001/api/v1/metrics/detailed

# System diagnostics
curl http://localhost:8001/api/v1/diagnostics/full
```

This runbook should be reviewed monthly and updated as needed based on operational experience and system changes.

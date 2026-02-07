# Security Incident Runbook
**Runbook ID:** OPS-003  
**Service:** Security  
**Severity:** Critical  
**Team:** Operations + Security  
**Last Updated:** 2026-01-26

---

## Overview

This runbook provides step-by-step procedures for responding to security incidents, including unauthorized access, suspicious activity, and potential breaches.

---

## Alert Triggers

- **Alert:** Security Incident Detected (Critical)
- **Conditions:** Suspicious login, failed authentication, unusual API patterns, scan failures
- **Dashboard:** http://grafana.merid.com/d/security-monitoring
- **Runbook:** https://docs.merid.com/runbooks/SECURITY_INCIDENT

---

## Incident Classification

### **Critical (P0)**
- Confirmed unauthorized access
- Data exfiltration detected
- System compromise confirmed
- Ransomware or malware detected

### **High (P1)**
- Suspicious activity patterns
- Multiple failed authentication attempts
- Unusual API access patterns
- Security scan failures

### **Medium (P2)**
- Single failed authentication
- Minor configuration issues
- Suspicious but not confirmed malicious activity

---

## Initial Assessment

### 1. Alert Verification
```bash
# Check recent authentication logs
grep -i "failed\|error\|unauthorized" /var/log/merid/auth.log | tail -20

# Check API access patterns
grep -i "suspicious\|anomaly" /var/log/merid/api.log | tail -20

# Check system integrity
docker ps | grep -v "merid"  # Look for unknown containers
netstat -tlnp | grep -E ":22|:80|:443|:8000"  # Check for unusual ports
```

### 2. Incident Classification
- [ ] **Confirm incident** - Verify this is not a false positive
- [ ] **Determine scope** - How many systems/users affected
- [ ] **Assess impact** - Data exposure, system availability
- [ ] **Document timeline** - When did the incident start

### 3. Immediate Containment
```bash
# If confirmed compromise, isolate affected systems
docker stop merid-api  # Stop API if compromised
iptables -A INPUT -s <suspicious_ip> -j DROP  # Block suspicious IP

# Rotate credentials if needed
kubectl create secret generic merid-secrets --from-literal=password=$(openssl rand -base64 32)
```

---

## Immediate Response (T+0-5 minutes)

## Investigation (T+5-60 minutes)

### 1. Evidence Collection
```bash
# Create evidence directory
mkdir -p /tmp/security-incident-$(date +%Y%m%d-%H%M%S)
cd /tmp/security-incident-$(date +%Y%m%d-%H%M%S)

# Collect logs
cp /var/log/merid/*.log .
docker logs merid-api > docker-logs.txt
docker logs neo4j > neo4j-logs.txt
docker logs redis > redis-logs.txt

# Collect system state
ps aux > processes.txt
netstat -tlnp > network-connections.txt
docker ps > docker-containers.txt
iptables -L > firewall-rules.txt

# Create hash for evidence integrity
sha256sum * > evidence-hashes.txt
```

### 2. Root Cause Analysis
```bash
# Check authentication logs for patterns
grep -i "failed\|success" /var/log/merid/auth.log | awk '{print $1,$2,$3}' | sort | uniq -c

# Check API access by IP
grep -o "client_ip=[0-9.]*" /var/log/merid/api.log | sort | uniq -c | sort -nr

# Check for unusual user agents
grep -o "user_agent=[^ ]*" /var/log/merid/api.log | sort | uniq -c | sort -nr

# Check for data access patterns
grep -o "endpoint=[^ ]*" /var/log/merid/api.log | sort | uniq -c | sort -nr
```

### 3. Impact Assessment
```bash
# Check data access
grep -i "sensitive\|private\|confidential" /var/log/merid/api.log

# Check for data exfiltration
grep -o "response_size=[0-9]*" /var/log/merid/api.log | awk -F= '{sum+=$2} END {print "Total data transferred:", sum, "bytes"}'

# Check database access
docker exec neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n) as total_nodes"
```

---

## Containment Procedures

### Scenario 1: Unauthorized Access
```bash
# Block malicious IP
iptables -A INPUT -s <malicious_ip> -j DROP
iptables -A OUTPUT -d <malicious_ip> -j DROP

# Rotate API keys
kubectl delete secret merid-api-keys
kubectl create secret generic merid-api-keys --from-file=api-key.txt

# Force logout all sessions
redis-cli FLUSHALL  # Clear all sessions
```

### Scenario 2: System Compromise
```bash
# Isolate affected containers
docker stop merid-api
docker pause neo4j redis

# Create forensic snapshot
docker commit merid-api merid-api-forensic-$(date +%Y%m%d-%H%M%S)

# Restore from backup if needed
docker-compose down
docker-compose up -d --force-recreate
```

### Scenario 3: Data Exfiltration
```bash
# Block outbound traffic
iptables -A OUTPUT -j DROP
iptables -A OUTPUT -d <trusted_ips> -j ACCEPT

# Check for data transfers
grep -o "bytes_sent=[0-9]*" /var/log/merid/api.log | awk -F= '{sum+=$2} END {print "Total sent:", sum}'

# Notify data protection officer
echo "Potential data exfiltration detected at $(date)" | mail -s "SECURITY ALERT" dpo@merid.com
```

---

## Recovery Procedures

### 1. System Restoration
```bash
# Restore from clean backup
docker-compose down
cp -r /backups/merid-$(date +%Y%m%d-1)/* .
docker-compose up -d

# Verify system integrity
curl -f http://localhost:8000/health
docker exec neo4j cypher-shell -u neo4j -p password "RETURN 1"
redis-cli ping
```

### 2. Security Hardening
```bash
# Update firewall rules
iptables -F  # Flush existing rules
iptables -A INPUT -p tcp --dport 22 -s <trusted_ips> -j ACCEPT
iptables -A INPUT -p tcp --dport 8000 -s <trusted_ips> -j ACCEPT
iptables -A INPUT -j DROP

# Update authentication
kubectl create secret generic merid-auth --from-literal=password=$(openssl rand -base64 32)

# Enable additional logging
echo "log_level = DEBUG" >> /etc/merid/config.yml
```

### 3. Monitoring Enhancement
```bash
# Add security monitoring
echo "security_monitoring = true" >> /etc/merid/config.yml
echo "audit_logging = true" >> /etc/merid/config.yml

# Restart services with enhanced monitoring
docker-compose restart merid-api
```

---

## Communication Procedures

### 1. Internal Communication
- **Security Channel:** #merid-security-alerts
- **PagerDuty:** Security team on-call
- **Stakeholder Updates:** Every 30 minutes during incident

### 2. External Communication
- **Data Protection Officer:** Immediate notification for data incidents
- **Legal Team:** Consult before external communications
- **Customers:** Only after containment and assessment complete

### 3. Status Update Template
```
[SECURITY INCIDENT] - T+{time}m

Severity: {CRITICAL|HIGH|MEDIUM}
Status: {INVESTIGATING|CONTAINED|RECOVERING}
Impact: {Systems affected, data exposure}
Actions: {Current containment and investigation actions}
Next Update: {time}
```

---

## Escalation Matrix

### **Level 1: On-call Security Engineer**
- **Contact:** security-oncall@merid.com
- **Response Time:** 15 minutes
- **Authority:** Containment, investigation, basic recovery

### **Level 2: Security Lead**
- **Contact:** security-lead@merid.com, +1-555-XXX-XXXX
- **Response Time:** 30 minutes
- **Authority:** Full incident response, external communications

### **Level 3: CISO**
- **Contact:** ciso@merid.com, +1-555-XXX-XXXX
- **Response Time:** 1 hour
- **Authority:** Strategic decisions, regulatory notifications

### **Level 4: Executive Committee**
- **Contact:** exec-committee@merid.com
- **Response Time:** 2 hours
- **Authority:** Major incident decisions, public statements

---

## Post-Incident Actions

### 1. Documentation
- [ ] Complete incident report with timeline
- [ ] Document root cause and impact
- [ ] Update security procedures based on lessons learned
- [ ] Create post-mortem presentation

### 2. Security Improvements
- [ ] Implement additional monitoring
- [ ] Update firewall rules and access controls
- [ ] Enhance authentication mechanisms
- [ ] Schedule security review and audit

### 3. Compliance Actions
- [ ] Notify regulatory authorities if required
- [ ] Update security policies
- [ ] Schedule compliance audit
- [ ] Document breach notification procedures

---

## Known Security Issues

### Issue: Brute Force Attacks
**Symptoms:** Multiple failed authentication attempts
**Workaround:** Implement rate limiting and account lockout
**Permanent Fix:** Multi-factor authentication, IP whitelisting

### Issue: API Abuse
**Symptoms:** Unusual API access patterns, high request rates
**Workaround:** Rate limiting, API key rotation
**Permanent Fix:** API gateway with abuse detection

### Issue: Container Security
**Symptoms:** Unknown containers, suspicious container activity
**Workaround:** Container isolation, network segmentation
**Permanent Fix:** Container security scanning, runtime protection

---

## Contacts and Resources

### Security Team
- **On-call Security Engineer:** security-oncall@merid.com
- **Security Lead:** security-lead@merid.com
- **CISO:** ciso@merid.com

### External Resources
- **Security Dashboard:** http://grafana.merid.com/d/security-monitoring
- **Security Documentation:** https://docs.merid.com/security
- **Incident Response Plan:** https://docs.merid.com/incident-response

### Tools and Commands
- **Log Analysis:** `grep`, `awk`, `sort`, `uniq`
- **System Analysis:** `ps`, `netstat`, `iptables`, `docker`
- **Forensics:** `sha256sum`, `tcpdump`, `strace`

---

## Runbook Maintenance

- **Review Date:** Monthly
- **Last Updated:** 2026-01-26
- **Next Review:** 2026-02-26
- **Owner:** Security Team

---

**Runbook Status:** ✅ **ACTIVE**  
**Approval:** Security Lead + CISO  
**Version:** 1.0

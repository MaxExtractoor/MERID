# Database Issues Runbook
**Runbook ID:** OPS-004  
**Service:** Database (Neo4j, Redis)  
**Severity:** Critical  
**Team:** Operations + Database Team  
**Last Updated:** 2026-01-26

---

## Overview

This runbook provides procedures for responding to database connectivity issues, performance degradation, and data integrity problems.

---

## Alert Triggers

- **Alert:** Neo4j_Connection_Failed (Critical)
- **Alert:** Redis_Connection_Failed (Critical)
- **Alert:** Database_Connection_Pool_Exhausted (Warning)
- **Dashboard:** http://grafana.merid.com/d/database-health
- **Runbook:** https://docs.merid.com/runbooks/DATABASE_ISSUES

---

## Database Components

### **Neo4j Graph Database**
- **Purpose:** Reality Registry, assertion storage, graph queries
- **Port:** 7687 (Bolt), 7474 (HTTP), 7473 (HTTPS)
- **Container:** neo4j
- **Data Volume:** neo4j_data

### **Redis Cache**
- **Purpose:** Session storage, caching, temporary data
- **Port:** 6379 (Redis), 6380 (Redis TLS)
- **Container:** redis
- **Data Volume:** redis_data

---

## Initial Assessment (T+0-5 minutes)

### 1. Verify Database Status
```bash
# Check Neo4j
docker ps | grep neo4j
curl -f http://localhost:7474 || echo "Neo4j HTTP down"
docker exec neo4j cypher-shell -u neo4j -p password "RETURN 1" || echo "Neo4j Bolt down"

# Check Redis
docker ps | grep redis
docker exec redis redis-cli ping || echo "Redis down"
docker exec redis redis-cli -p 6380 --tls ping || echo "Redis TLS down"
```

### 2. Check Resource Usage
```bash
# Check container resources
docker stats neo4j redis --no-stream

# Check disk space
df -h | grep -E "(neo4j|redis)"

# Check memory usage
docker exec neo4j free -h
docker exec redis redis-cli info memory
```

### 3. Check Logs for Errors
```bash
# Neo4j logs
docker logs neo4j --tail=50 | grep -i "error\|exception\|failed"

# Redis logs
docker logs redis --tail=50 | grep -i "error\|warning\|failed"

# System logs
grep -i "neo4j\|redis" /var/log/merid/*.log | tail -20
```

---

## Immediate Response (T+5-15 minutes)

### Scenario 1: Database Down

#### Neo4j Recovery
```bash
# Check if Neo4j process is running
docker exec neo4j ps aux | grep neo4j

# Restart Neo4j if needed
docker restart neo4j

# Wait for startup
sleep 30

# Verify health
docker exec neo4j cypher-shell -u neo4j -p password "RETURN 1"

# Check data integrity
docker exec neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n) as total_nodes"
```

#### Redis Recovery
```bash
# Check if Redis process is running
docker exec redis ps aux | grep redis

# Restart Redis if needed
docker restart redis

# Wait for startup
sleep 10

# Verify health
docker exec redis redis-cli ping

# Check data
docker exec redis redis-cli info keyspace
```

### Scenario 2: Connection Pool Exhausted
```bash
# Check active connections
docker exec neo4j cypher-shell -u neo4j -p password "SHOW DATABASES"
docker exec redis redis-cli info clients

# Check pool configuration
grep -i "pool" /etc/merid/neo4j.conf
grep -i "maxclients" /etc/redis/redis.conf

# Temporary fix - increase pool size
docker exec neo4j cypher-shell -u neo4j -p password "ALTER DATABASE neo4j SET PROPERTY dbms.connector.bolt.max_connection_pool_size 200"

# Restart application with new pool settings
docker restart merid-api
```

### Scenario 3: Performance Issues
```bash
# Check query performance
docker exec neo4j cypher-shell -u neo4j -p password "CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Transactions') YIELD value RETURN value"

# Check slow queries
docker exec neo4j cypher-shell -u neo4j -p password "CALL dbms.listQueries() YIELD queryId, query RETURN queryId, query LIMIT 10"

# Check Redis performance
docker exec redis redis-cli info stats
docker exec redis redis-cli info commandstats
```

---

## Investigation (T+15-60 minutes)

### 1. Data Integrity Checks
```bash
# Neo4j data integrity
docker exec neo4j cypher-shell -u neo4j -p password "
MATCH (n) 
RETURN count(n) as total_nodes, 
       count(DISTINCT labels(n)) as unique_labels
"

# Check for orphaned nodes
docker exec neo4j cypher-shell -u neo4j -p password "
MATCH (n) WHERE NOT (n)--() 
RETURN count(n) as orphaned_nodes
"

# Redis data integrity
docker exec redis redis-cli info keyspace
docker exec redis redis-cli dbsize
```

### 2. Performance Analysis
```bash
# Neo4j performance metrics
docker exec neo4j cypher-shell -u neo4j -p password "
CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Memory Pools') YIELD value RETURN value
"

# Check index usage
docker exec neo4j cypher-shell -u neo4j -p password "
CALL db.indexes() YIELD name, state RETURN name, state
"

# Redis performance
docker exec redis redis-cli info memory
docker exec redis redis-cli info persistence
```

### 3. Resource Analysis
```bash
# Check disk I/O
iostat -x 1 5 | grep -E "(Device|neo4j|redis)"

# Check memory pressure
free -h
docker stats neo4j redis --no-stream | grep -E "(CONTAINER|MEM)"

# Check network connectivity
netstat -tlnp | grep -E "(7687|6379)"
```

---

## Recovery Procedures

### 1. Data Recovery

#### Neo4j Recovery
```bash
# Create backup before recovery
docker exec neo4j neo4j-admin backup --backup-dir=/backup --name=pre-recovery-$(date +%Y%m%d-%H%M%S)

# Restore from backup if needed
docker-compose down
cp -r /backups/neo4j-<date>/* neo4j_data/
docker-compose up -d neo4j

# Verify data integrity
docker exec neo4j cypher-shell -u neo4j -p password "MATCH (n) RETURN count(n)"
```

#### Redis Recovery
```bash
# Create backup
docker exec redis redis-cli BGSAVE
docker cp redis:/data/dump.rdb /backups/redis-$(date +%Y%m%d-%H%M%S).rdb

# Restore from backup if needed
docker-compose down
cp /backups/redis-<date>.rdb redis_data/dump.rdb
docker-compose up -d redis

# Verify data
docker exec redis redis-cli dbsize
```

### 2. Performance Recovery
```bash
# Optimize Neo4j
docker exec neo4j cypher-shell -u neo4j -p password "CALL db.stats.retrieve('GRAPH COUNTS')"
docker exec neo4j cypher-shell -u neo4j -p password "CALL db.index.fulltext.listAvailableAnalyzers"

# Optimize Redis
docker exec redis redis-cli CONFIG SET maxmemory-policy allkeys-lru
docker exec redis redis-cli CONFIG SET timeout 300
```

### 3. Configuration Recovery
```bash
# Reset Neo4j configuration
docker cp /etc/merid/neo4j.conf neo4j:/conf/
docker restart neo4j

# Reset Redis configuration
docker cp /etc/redis/redis.conf redis:/usr/local/etc/redis/redis.conf
docker restart redis
```

---

## Failover Procedures

### 1. Neo4j Failover
```bash
# Check if replica exists
docker exec neo4j cypher-shell -u neo4j -p password "SHOW DATABASES"

# Promote replica if needed
docker exec neo4j cypher-shell -u neo4j -p password "ALTER DATABASE neo4j SET ACCESS READ WRITE"

# Update application connection string
# Update docker-compose.yml to point to new primary
docker-compose restart merid-api
```

### 2. Redis Failover
```bash
# Check Redis cluster status
docker exec redis redis-cli CLUSTER INFO

# Promote slave if needed
docker exec redis redis-cli CLUSTER FAILOVER

# Update application connection
docker restart merid-api
```

---

## Communication Procedures

### 1. Internal Communication
- **Database Channel:** #merid-database-alerts
- **PagerDuty:** Database team on-call
- **Stakeholder Updates:** Every 15 minutes during outage

### 2. Status Update Template
```
[DATABASE INCIDENT] - T+{time}m

Database: {Neo4j|Redis|Both}
Status: {INVESTIGATING|RECOVERING|RESOLVED}
Impact: {Services affected, data loss risk}
Actions: {Current recovery actions}
ETA: {Estimated recovery time}
Next Update: {time}
```

---

## Escalation Matrix

### **Level 1: On-call Database Engineer**
- **Contact:** db-oncall@merid.com
- **Response Time:** 15 minutes
- **Authority:** Database restart, basic recovery

### **Level 2: Database Lead**
- **Contact:** db-lead@merid.com, +1-555-XXX-XXXX
- **Response Time:** 30 minutes
- **Authority:** Failover, data recovery, configuration changes

### **Level 3: CTO**
- **Contact:** cto@merid.com, +1-555-XXX-XXXX
- **Response Time:** 1 hour
- **Authority:** Major data decisions, service impact decisions

---

## Post-Incident Actions

### 1. Documentation
- [ ] Complete incident report with timeline
- [ ] Document root cause and impact
- [ ] Update database procedures
- [ ] Create post-mortem presentation

### 2. Prevention Measures
- [ ] Implement automated health checks
- [ ] Add monitoring for connection pool usage
- [ ] Implement backup verification
- [ ] Schedule regular maintenance

### 3. System Improvements
- [ ] Add database clustering
- [ ] Implement connection pooling optimization
- [ ] Enhance monitoring and alerting
- [ ] Improve backup and recovery procedures

---

## Known Issues and Workarounds

### Issue: Neo4j Memory Leaks
**Symptoms:** Gradual memory increase, eventual OOM
**Workaround:** Restart Neo4j service
**Permanent Fix:** Memory leak investigation and patch

### Issue: Redis Memory Fragmentation
**Symptoms:** High memory usage with low data
**Workaround:** Restart Redis service
**Permanent Fix:** Memory defragmentation configuration

### Issue: Connection Pool Exhaustion
**Symptoms:** Database connection errors under load
**Workaround:** Increase pool size temporarily
**Permanent Fix:** Connection pooling optimization

---

## Contacts and Resources

### Database Team
- **On-call DB Engineer:** db-oncall@merid.com
- **Database Lead:** db-lead@merid.com
- **CTO:** cto@merid.com

### External Resources
- **Database Dashboard:** http://grafana.merid.com/d/database-health
- **Database Documentation:** https://docs.merid.com/database
- **Neo4j Documentation:** https://neo4j.com/docs/
- **Redis Documentation:** https://redis.io/documentation

### Tools and Commands
- **Neo4j:** `cypher-shell`, `neo4j-admin`, `docker exec neo4j`
- **Redis:** `redis-cli`, `docker exec redis`
- **System:** `docker`, `iostat`, `netstat`, `free`

---

## Runbook Maintenance

- **Review Date:** Monthly
- **Last Updated:** 2026-01-26
- **Next Review:** 2026-02-26
- **Owner:** Database Team

---

**Runbook Status:** ✅ **ACTIVE**  
**Approval:** Database Lead + CTO  
**Version:** 1.0

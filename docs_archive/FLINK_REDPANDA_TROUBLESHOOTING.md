# Flink + Redpanda Troubleshooting Guide

Production troubleshooting reference for MERID's streaming infrastructure.

## Quick Diagnostics

```bash
# Check all services
docker-compose -f docker/docker-compose.full-stack.yml ps

# Tail logs side-by-side (critical for debugging)
docker logs -f merid-redpanda &
docker logs -f merid-flink-jm &

# Check Redpanda cluster health
docker exec merid-redpanda rpk cluster health

# List topics and verify data
docker exec merid-redpanda rpk topic list
docker exec merid-redpanda rpk topic consume prices.kraken.BTCUSD --num 5

# Check Flink jobs
curl http://localhost:8081/jobs/overview
```

---

## Common Errors and Fixes

### 1. Can't Consume / Empty Stream

**Symptoms:**
- Flink job runs but no records processed
- `numRecordsIn` metric stays at 0
- No errors in logs

**Causes & Fixes:**

| Cause | Fix |
|-------|-----|
| Wrong bootstrap.servers | Inside Docker: `redpanda:9092`, Outside: `localhost:19092` |
| Topic doesn't exist | `rpk topic create <topic>` |
| Topic has no data | Verify with `rpk topic consume <topic>` |
| Wrong consumer group | Ensure `group.id` is unique per job |
| Offset reset policy | Set `scan.startup.mode` to `earliest-offset` for testing |

```sql
-- Flink SQL: Check startup mode
CREATE TABLE my_source (
  ...
) WITH (
  'connector' = 'kafka',
  'properties.bootstrap.servers' = 'redpanda:9092',  -- Inside Docker!
  'properties.group.id' = 'merid-unique-group-123',
  'scan.startup.mode' = 'earliest-offset'  -- Start from beginning
);
```

### 2. Checkpoint / Transaction Failures

**Symptoms:**
- Job fails during checkpoint
- `UNKNOWN_SERVER_ERROR` or `INVALID_TXN_STATE`
- Recovery fails after restart

**Root Cause:**
Flink's exactly-once sinks use Kafka transactions. If checkpoint duration + downtime exceeds broker's `transaction.max.timeout.ms`, transactions expire and recovery fails.

**Fix - Align Timeouts:**

```yaml
# redpanda.yaml (broker config)
kafka_api:
  - address: 0.0.0.0
    port: 9092
transaction_coordinator:
  transaction_max_timeout_ms: 900000  # 15 minutes
```

```yaml
# flink-conf.yaml
execution.checkpointing.timeout: 600000  # 10 minutes
```

```sql
-- Flink SQL sink
CREATE TABLE my_sink (
  ...
) WITH (
  'connector' = 'upsert-kafka',
  'properties.transaction.timeout.ms' = '600000'  -- Match checkpoint timeout
);
```

### 3. UNKNOWN_SERVER_ERROR with Redpanda

**Symptoms:**
- Intermittent transaction errors
- Empty transaction commits fail
- Job enters FAILED state

**Cause:**
Known Redpanda issue where Flink commits empty transactions, hitting broker-side validation.

**Fix:**
1. Update to latest Redpanda version
2. If error persists, restart job to recreate producer:

```bash
# Cancel and restart job
curl -X PATCH http://localhost:8081/jobs/<job-id>?mode=cancel
# Resubmit job
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-features.jar
```

### 4. Consumer Group Not Working

**Symptoms:**
- Multiple jobs reading same topic get all messages (no load balancing)
- Offset commits seem ignored

**Fix:**
Ensure all consumers in a group have identical `group.id`:

```sql
-- All jobs that should share load:
'properties.group.id' = 'merid-price-consumers'
```

For independent jobs, use unique group IDs:
```sql
'properties.group.id' = 'merid-btc-features-job-v1'
```

---

## Performance Issues

### High Checkpoint Duration

**Symptoms:**
- Checkpoint takes >30s
- Backpressure increases during checkpoint

**Fixes:**
```yaml
# flink-conf.yaml
state.backend: rocksdb
state.backend.incremental: true  # Incremental checkpoints
execution.checkpointing.unaligned: true  # Reduce backpressure impact
```

### Backpressure

**Symptoms:**
- `backPressuredTimeMsPerSecond` metric > 500
- Downstream operators slow

**Fixes:**
1. Scale TaskManagers:
   ```bash
   docker-compose up -d --scale flink-taskmanager=3
   ```

2. Increase parallelism (align with Kafka partitions):
   ```yaml
   parallelism.default: 4  # Match partition count
   ```

3. Check for slow operators in Flink UI backpressure tab

### Kafka Lag Growing

**Symptoms:**
- Consumer lag increases over time
- Features arrive late to agents

**Diagnosis:**
```bash
# Check consumer lag
docker exec merid-redpanda rpk group describe merid-flink-features
```

**Fixes:**
1. Add TaskManagers
2. Increase topic partitions (requires job restart):
   ```bash
   rpk topic alter-config prices.kraken.BTCUSD --set partition.count=4
   ```

---

## Recovery Procedures

### Job Failed - Clean Restart

```bash
# 1. Check job status
curl http://localhost:8081/jobs/overview

# 2. If job is in FAILED state, get job ID
JOB_ID=$(curl -s http://localhost:8081/jobs/overview | jq -r '.jobs[0].jid')

# 3. Cancel (if still running)
curl -X PATCH "http://localhost:8081/jobs/$JOB_ID?mode=cancel"

# 4. Clear consumer group offsets (start fresh)
docker exec merid-redpanda rpk group delete merid-flink-features

# 5. Restart job
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-features.jar
```

### Job Failed - Resume from Savepoint

```bash
# 1. Trigger savepoint before planned restart
curl -X POST "http://localhost:8081/jobs/$JOB_ID/savepoints" \
  -d '{"target-directory": "/opt/flink/savepoints"}'

# 2. Get savepoint path from response
SAVEPOINT_PATH="/opt/flink/savepoints/savepoint-xxx"

# 3. Restart from savepoint
docker exec merid-flink-jm flink run \
  -s $SAVEPOINT_PATH \
  /opt/flink/jobs/merid-features.jar
```

### Redpanda Broker Recovery

```bash
# Check cluster status
docker exec merid-redpanda rpk cluster health

# If broker is down, restart
docker-compose restart redpanda

# Verify topics intact
docker exec merid-redpanda rpk topic list
```

---

## Monitoring Checklist

### Critical Metrics to Watch

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Checkpoint Duration | >30s | >60s | Enable incremental, add TMs |
| Backpressure | >30% | >50% | Scale out, check slow operators |
| Kafka Lag | >1000 | >10000 | Scale out, add partitions |
| Task Restarts | >1/hr | >5/hr | Check logs, fix root cause |
| Heap Usage | >70% | >85% | Increase TM memory |

### Prometheus Queries

```promql
# Checkpoint duration (should be <30s)
flink_jobmanager_job_lastCheckpointDuration

# Backpressure ratio
flink_taskmanager_job_task_backPressuredTimeMsPerSecond / 1000

# Records per second
rate(flink_taskmanager_job_task_numRecordsIn[1m])

# Task restarts
increase(flink_jobmanager_job_numRestarts[1h])
```

### Grafana Alerts (recommended)

```yaml
# Example alert rule
- alert: FlinkCheckpointSlow
  expr: flink_jobmanager_job_lastCheckpointDuration > 60000
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Flink checkpoint taking >60s"

- alert: FlinkBackpressureHigh
  expr: flink_taskmanager_job_task_backPressuredTimeMsPerSecond > 500
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Flink operator backpressured >50%"
```

---

## Configuration Reference

### Recommended Timeouts (aligned)

| Setting | Value | Location |
|---------|-------|----------|
| `transaction.max.timeout.ms` | 900000 (15m) | Redpanda broker |
| `transaction.timeout.ms` | 600000 (10m) | Flink producer |
| `execution.checkpointing.timeout` | 600000 (10m) | Flink config |
| `execution.checkpointing.interval` | 60000 (1m) | Flink config |

### Network Addresses

| Context | Bootstrap Servers |
|---------|-------------------|
| Inside Docker (Flink) | `redpanda:9092` |
| Outside Docker (dev tools) | `localhost:19092` |
| Schema Registry | `http://redpanda:8083` |

---

## Quick Reference Commands

```bash
# ===== REDPANDA =====
rpk cluster health
rpk topic list
rpk topic describe <topic>
rpk topic consume <topic> --num 10
rpk group list
rpk group describe <group>
rpk group delete <group>

# ===== FLINK =====
# List jobs
curl http://localhost:8081/jobs/overview

# Job details
curl http://localhost:8081/jobs/<job-id>

# Cancel job
curl -X PATCH "http://localhost:8081/jobs/<job-id>?mode=cancel"

# Trigger savepoint
curl -X POST "http://localhost:8081/jobs/<job-id>/savepoints" \
  -d '{"target-directory": "/opt/flink/savepoints"}'

# Submit job
flink run /path/to/job.jar
flink run -s /path/to/savepoint /path/to/job.jar
```

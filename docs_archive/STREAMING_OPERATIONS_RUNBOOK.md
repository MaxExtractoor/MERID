# MERID Streaming Operations Runbook

Operational procedures for managing the Flink + Redpanda streaming infrastructure.

## Quick Reference

| Service | URL | Purpose |
|---------|-----|---------|
| Redpanda Console | http://localhost:8080 | Topic management |
| Flink Dashboard | http://localhost:8081 | Job management |
| Prometheus | http://localhost:9090 | Metrics |
| Grafana | http://localhost:3000 | Dashboards (admin/admin) |

## Startup Procedures

### Full Stack Startup

```bash
cd docker

# Start all services
docker-compose -f docker-compose.full-stack.yml up -d

# Verify all containers running
docker-compose -f docker-compose.full-stack.yml ps

# Check Redpanda health
docker exec merid-redpanda rpk cluster health

# Verify topics created
docker exec merid-redpanda rpk topic list
```

### Submit Flink Jobs

```bash
# Submit SQL job
docker exec -it merid-flink-jm bin/sql-client.sh -f /opt/flink/sql/merid_tables.sql

# Submit JAR job
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-features.jar

# Submit with specific parallelism
docker exec merid-flink-jm flink run -p 4 /opt/flink/jobs/merid-features.jar
```

## Scaling Procedures

### Scale TaskManagers (Horizontal)

Use this when checkpoint times or backpressure increase.

```bash
# Scale to 3 TaskManagers
docker-compose -f docker-compose.full-stack.yml up -d --scale flink-taskmanager=3

# Scale to 5 for high-volume periods
docker-compose -f docker-compose.full-stack.yml up -d --scale flink-taskmanager=5

# Verify TaskManagers registered
curl -s http://localhost:8081/taskmanagers | jq '.taskmanagers | length'
```

### Scale Topic Partitions

Required when TaskManagers can't parallelize further (parallelism = partitions).

```bash
# Check current partition count
docker exec merid-redpanda rpk topic describe prices.kraken.BTCUSD

# Increase partitions (requires job restart)
docker exec merid-redpanda rpk topic alter-config prices.kraken.BTCUSD --set partition.count=4

# Restart jobs to pick up new partitions
# See "Job Restart Procedures" below
```

### Vertical Scaling (TaskManager Resources)

Edit `docker-compose.full-stack.yml`:

```yaml
flink-taskmanager:
  deploy:
    resources:
      limits:
        memory: 4G  # Increase from 2G
        cpus: '2'
```

Then restart:

```bash
docker-compose -f docker-compose.full-stack.yml up -d flink-taskmanager
```

## Job Management

### List Running Jobs

```bash
curl -s http://localhost:8081/jobs/overview | jq '.jobs[] | {id: .jid, name: .name, state: .state}'
```

### Cancel Job

```bash
JOB_ID="<job-id>"
curl -X PATCH "http://localhost:8081/jobs/$JOB_ID?mode=cancel"
```

### Savepoint and Restart

```bash
JOB_ID="<job-id>"

# Trigger savepoint
SAVEPOINT_RESPONSE=$(curl -X POST "http://localhost:8081/jobs/$JOB_ID/savepoints" \
  -H "Content-Type: application/json" \
  -d '{"target-directory": "/opt/flink/savepoints", "cancel-job": true}')

# Get savepoint path (poll until complete)
REQUEST_ID=$(echo $SAVEPOINT_RESPONSE | jq -r '.request-id')
SAVEPOINT_PATH=$(curl -s "http://localhost:8081/jobs/$JOB_ID/savepoints/$REQUEST_ID" | jq -r '.operation.location')

# Restart from savepoint
docker exec merid-flink-jm flink run -s $SAVEPOINT_PATH /opt/flink/jobs/merid-features.jar
```

### Clean Restart (No State)

```bash
JOB_ID="<job-id>"

# Cancel job
curl -X PATCH "http://localhost:8081/jobs/$JOB_ID?mode=cancel"

# Clear consumer group offsets
docker exec merid-redpanda rpk group delete merid-flink-features

# Restart fresh
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-features.jar
```

## Monitoring

### Check Key Metrics

```bash
# Checkpoint duration
curl -s http://localhost:8081/jobs/<job-id>/checkpoints | jq '.history[0].duration'

# Records processed
curl -s "http://localhost:9090/api/v1/query?query=rate(flink_taskmanager_job_task_numRecordsIn[1m])" | jq '.data.result[].value[1]'

# Consumer lag
docker exec merid-redpanda rpk group describe merid-flink-features
```

### Prometheus Queries

```promql
# Throughput (records/sec)
rate(flink_taskmanager_job_task_numRecordsIn[1m])

# Checkpoint duration
flink_jobmanager_job_lastCheckpointDuration

# Backpressure
flink_taskmanager_job_task_backPressuredTimeMsPerSecond / 1000

# Heap usage
flink_taskmanager_Status_JVM_Memory_Heap_Used / flink_taskmanager_Status_JVM_Memory_Heap_Max
```

### Set Up Alerts

In Grafana, create alerts for:

| Metric | Condition | Action |
|--------|-----------|--------|
| Checkpoint Duration | > 60s for 5m | Scale TaskManagers |
| Backpressure | > 50% for 5m | Scale or check slow operators |
| Consumer Lag | > 10000 for 10m | Scale or add partitions |
| Task Restarts | > 3 in 1h | Check logs, fix root cause |

## Maintenance

### Upgrade Flink Version

```bash
# 1. Stop jobs with savepoints
for JOB_ID in $(curl -s http://localhost:8081/jobs/overview | jq -r '.jobs[].jid'); do
  curl -X POST "http://localhost:8081/jobs/$JOB_ID/savepoints" \
    -d '{"target-directory": "/opt/flink/savepoints", "cancel-job": true}'
done

# 2. Update image in docker-compose.full-stack.yml
# flink-jobmanager:
#   image: flink:1.19-scala_2.12  # New version

# 3. Restart Flink cluster
docker-compose -f docker-compose.full-stack.yml up -d flink-jobmanager flink-taskmanager

# 4. Restart jobs from savepoints
# (See "Savepoint and Restart" above)
```

### Upgrade Redpanda Version

```bash
# 1. Stop all Flink jobs (savepoints recommended)

# 2. Update image in docker-compose.full-stack.yml
# redpanda:
#   image: docker.redpanda.com/redpandadata/redpanda:v24.1.1

# 3. Restart Redpanda
docker-compose -f docker-compose.full-stack.yml up -d redpanda

# 4. Verify cluster health
docker exec merid-redpanda rpk cluster health

# 5. Restart Flink jobs
```

### Clean Up Old Checkpoints/Savepoints

```bash
# List checkpoints
docker exec merid-flink-jm ls -la /opt/flink/checkpoints

# Remove old checkpoints (keep recent)
docker exec merid-flink-jm find /opt/flink/checkpoints -mtime +7 -delete

# List savepoints
docker exec merid-flink-jm ls -la /opt/flink/savepoints
```

## Troubleshooting

### Job Stuck in INITIALIZING

```bash
# Check TaskManager availability
curl -s http://localhost:8081/taskmanagers | jq '.taskmanagers | length'

# If 0, check TaskManager logs
docker logs merid-flink-taskmanager

# Common fix: restart TaskManager
docker-compose -f docker-compose.full-stack.yml restart flink-taskmanager
```

### Job Keeps Restarting

```bash
# Check job exceptions
curl -s http://localhost:8081/jobs/<job-id>/exceptions | jq '.root-exception'

# Check TaskManager logs for details
docker logs merid-flink-taskmanager --tail 100
```

### No Data Flowing

```bash
# 1. Check topic has data
docker exec merid-redpanda rpk topic consume prices.kraken.BTCUSD --num 5

# 2. Check consumer group offsets
docker exec merid-redpanda rpk group describe merid-flink-features

# 3. Check Flink metrics
curl -s "http://localhost:9090/api/v1/query?query=flink_taskmanager_job_task_numRecordsIn"
```

### High Checkpoint Duration

```bash
# 1. Check current duration
curl -s http://localhost:8081/jobs/<job-id>/checkpoints | jq '.history[0].duration'

# 2. If > 60s, enable incremental checkpoints
# Edit flink-conf.yaml: state.backend.incremental: true

# 3. Scale TaskManagers
docker-compose -f docker-compose.full-stack.yml up -d --scale flink-taskmanager=3

# 4. Consider unaligned checkpoints for backpressure
# Edit flink-conf.yaml: execution.checkpointing.unaligned: true
```

## Emergency Procedures

### Full Stack Restart

```bash
# Stop everything
docker-compose -f docker-compose.full-stack.yml down

# Clear volumes if needed (DATA LOSS!)
# docker-compose -f docker-compose.full-stack.yml down -v

# Start fresh
docker-compose -f docker-compose.full-stack.yml up -d
```

### Recover from Broker Failure

```bash
# 1. Check Redpanda status
docker exec merid-redpanda rpk cluster health

# 2. If down, restart
docker-compose -f docker-compose.full-stack.yml restart redpanda

# 3. Wait for recovery
sleep 30

# 4. Restart Flink jobs (they may have failed)
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-features.jar
```

### Clear All State and Start Fresh

**WARNING: This deletes all data!**

```bash
# 1. Stop everything
docker-compose -f docker-compose.full-stack.yml down

# 2. Remove all volumes
docker volume rm merid-redpanda-data merid-flink-checkpoints merid-flink-savepoints

# 3. Start fresh
docker-compose -f docker-compose.full-stack.yml up -d
```

## Reference

### Container Names

| Container | Service |
|-----------|---------|
| merid-redpanda | Kafka broker |
| merid-console | Redpanda UI |
| merid-flink-jm | Flink JobManager |
| flink-taskmanager-1 | Flink TaskManager |
| merid-prometheus | Prometheus |
| merid-grafana | Grafana |

### Network

All services on `merid-net` Docker network.

| Service | Internal Address |
|---------|------------------|
| Redpanda | redpanda:9092 |
| Flink JM | flink-jobmanager:6123 |
| Prometheus | prometheus:9090 |

### Ports

| Port | Service |
|------|---------|
| 8080 | Redpanda Console |
| 8081 | Flink Web UI |
| 9090 | Prometheus |
| 3000 | Grafana |
| 9092 | Kafka (internal) |
| 19092 | Kafka (external) |

# MERID Structured Logging Setup

This guide explains how to set up and use the structured JSON logging system for MERID agent performance monitoring.

## Overview

MERID now uses structured JSON logging for:
- Agent run metrics (Brier scores, bucket analysis, latency)
- Error tracking with stack traces
- Performance monitoring and debugging
- Log aggregation with Fluent Bit

## Components

### 1. Python Structured Logging

**Location**: `agents/prediction_arbitrage_analyst.py`

Features:
- **Fallback Design**: Uses `python-json-logger` if available, falls back to custom JSON formatter
- **Rich Metadata**: Includes service name, timestamps, agent IDs, bucket stats
- **Error Handling**: Graceful degradation if logging fails
- **NDJSON Output**: One JSON object per line for easy parsing

**Sample Log Entry**:
```json
{
  "ts": "2026-01-24T10:51:05Z",
  "service": "merid-agent",
  "level": "INFO",
  "logger": "merid.agent",
  "msg": "agent_run_completed",
  "agent_id": "prediction-arbitrage-analyst-01",
  "run_id": "abc123",
  "brier_score": 0.003889,
  "status": "success",
  "bucket_stats": [...],
  "filters": {...}
}
```

### 2. Docker Log Rotation

**Files**:
- `docker-compose.logging.yml` - Service configuration
- `docker.daemon.json` - Global defaults

**Features**:
- **Automatic Rotation**: Logs rotate at specified size limits
- **Compression**: Old logs are gzipped to save space
- **Retention**: Configurable number of log files to keep
- **Per-Service**: Different settings for API vs workers

**Sample Configuration**:
```yaml
logging:
  driver: json-file
  options:
    max-size: "20m"
    max-file: "5"
    compress: "true"
```

### 3. Fluent Bit Integration

**Files**:
- `fluent-bit.conf` - Main configuration
- `parsers.conf` - JSON parsing rules

**Features**:
- **Multi-Source**: Tails both Docker logs and agent JSON files
- **Structured Parsing**: Extracts JSON fields from log lines
- **Flexible Outputs**: Can ship to Elasticsearch, Loki, Kafka, etc.
- **Error Filtering**: Focuses on agent-relevant log messages

## Installation

### 1. Python Dependencies

Add to `requirements.txt`:
```bash
python-json-logger==2.0.7
```

The system works without this dependency but provides better formatting with it.

### 2. Docker Setup

1. **Global Defaults** (optional):
   ```bash
   sudo cp docker.daemon.json /etc/docker/daemon.json
   sudo systemctl restart docker
   ```

2. **Service Configuration**:
   ```bash
   docker-compose -f docker-compose.logging.yml up -d
   ```

### 3. Fluent Bit Backend

Configure your preferred log backend in `fluent-bit.conf`:
- **Elasticsearch**: For search and analytics
- **Loki**: For Grafana integration
- **Kafka**: For streaming pipelines
- **S3**: For long-term storage

## Usage

### Agent Run Logging

Automatic - every agent run logs:
```python
# This happens automatically in the agent
run_log = AgentRunLog(...)
log_agent_run(run_log)
```

### Manual Logging

```python
from agents.prediction_arbitrage_analyst import _json_formatter

# Custom structured log
log_data = {"custom_field": "value", "agent_id": "my-agent"}
json_line = _json_formatter.format_log("custom_event", log_data)
print(json_line)
```

### Error Logging

```python
try:
    risky_operation()
except Exception as e:
    logger.exception("operation_failed", extra={"context": "agent_run"})
```

## Query Examples

### Find High Brier Scores

```bash
# In Elasticsearch/Kibana
msg:"agent_run_completed" AND brier_score:>0.05

# In Fluent Bit/grep
grep '"brier_score":[5-9]' logs/agent_runs.jsonl
```

### Track Performance Trends

```bash
# Extract Brier scores over time
jq -r '[.ts, .brier_score] | @csv' logs/agent_runs.jsonl
```

### Debug Failed Runs

```bash
# Find error runs
jq 'select(.status=="error")' logs/agent_runs.jsonl
```

## Monitoring

### Key Metrics to Track

1. **Brier Score Trends**: Calibration quality over time
2. **Latency**: Agent performance and LLM response times
3. **Error Rates**: Frequency of failed runs
4. **Bucket Distribution**: How opportunities fall into confidence ranges

### Dashboard Integration

The `/debug-v2` dashboard shows:
- **Recent Runs Table**: Last 10 agent runs with performance metrics
- **Brier Score KPI**: Current run's calibration score
- **Bucket Analysis**: Visual calibration charts

### Alerting

Set up alerts for:
- Brier scores > 0.1 (poor calibration)
- Error rate > 10%
- Latency > 5000ms
- No successful runs in 1 hour

## Troubleshooting

### Common Issues

1. **Logs Not Appearing**:
   - Check file permissions on `logs/` directory
   - Verify SERVICE_NAME environment variable
   - Check Fluent Bit configuration

2. **JSON Parse Errors**:
   - Ensure no raw newlines in message fields
   - Validate JSON structure with `jq`
   - Check for encoding issues

3. **Docker Log Rotation**:
   - Verify daemon.json syntax
   - Check Docker service status
   - Review container-specific settings

### Debug Commands

```bash
# Check log file permissions
ls -la logs/agent_runs.jsonl

# Validate JSON syntax
jq . logs/agent_runs.jsonl | head -5

# Check Fluent Bit status
docker logs fluent-bit

# Test logging manually
python -c "from agents.prediction_arbitrage_analyst import _json_formatter; print(_json_formatter.format_log('test', {'test': True}))"
```

## Best Practices

1. **Consistent Field Names**: Use the same field names across all log types
2. **Timestamp Format**: Always use ISO8601 UTC timestamps
3. **Error Context**: Include relevant context in error logs
4. **Log Levels**: Use appropriate levels (INFO, WARN, ERROR)
5. **Performance**: Avoid logging in tight loops
6. **Privacy**: Don't log sensitive data (API keys, personal info)

## Future Enhancements

1. **Real Outcomes**: Replace proxy Brier with actual trade results
2. **REL/RES Metrics**: Add calibration decomposition
3. **Log Sampling**: Reduce volume in high-traffic scenarios
4. **Machine Learning**: Anomaly detection on performance metrics
5. **Cross-Agent**: Unified logging across all MERID agents

# MERID Swarm - Monitoring & Observability Guide

**Complete monitoring setup for production swarm operations.**

---

## Overview

This guide covers setting up comprehensive monitoring for the MERID swarm system, including metrics collection, alerting, dashboards, and log aggregation.

---

## Architecture

```
┌─────────────────────────────────────────┐
│     MERID Swarm Components              │
│  - Agents (emit heartbeats)             │
│  - Consensus (track decisions)          │
│  - Execution (track orders)             │
│  - Watchdogs (emit alerts)              │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│     SwarmTelemetry                      │
│  - Collect metrics                      │
│  - Aggregate stats                      │
│  - Export Prometheus                    │
└──────────────┬──────────────────────────┘
               │
       ┌───────┴────────┐
       ↓                ↓
┌─────────────┐  ┌─────────────┐
│ Prometheus  │  │   Logs      │
│ (Metrics)   │  │ (JSON/Text) │
└──────┬──────┘  └──────┬──────┘
       │                │
       ↓                ↓
┌─────────────┐  ┌─────────────┐
│   Grafana   │  │     ELK     │
│ (Dashboards)│  │  (Search)   │
└─────────────┘  └─────────────┘
```

---

## 1. Prometheus Setup

### Installation

```bash
# Download Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar xvfz prometheus-*.tar.gz
cd prometheus-*

# Or use Docker
docker run -p 9090:9090 -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus
```

### Configuration

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'merid-swarm'
    environment: 'production'

# Alerting configuration
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - localhost:9093

# Load alert rules
rule_files:
  - "swarm_alerts.yml"

# Scrape configurations
scrape_configs:
  # MERID Swarm metrics
  - job_name: 'merid-swarm'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/v1/swarm/metrics/prometheus'
    scrape_interval: 5s
    scrape_timeout: 5s
  
  # System metrics
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
  
  # FastAPI metrics (if using prometheus_fastapi_instrumentator)
  - job_name: 'fastapi'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### Alert Rules

Create `swarm_alerts.yml`:

```yaml
groups:
  - name: swarm_health
    interval: 30s
    rules:
      # Agent health alerts
      - alert: AgentOffline
        expr: merid_agent_last_heartbeat_seconds > 60
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Agent {{ $labels.agent_id }} is offline"
          description: "Agent {{ $labels.agent_id }} hasn't sent heartbeat in {{ $value }} seconds"
      
      - alert: LowParticipationRate
        expr: merid_swarm_participation_rate < 0.7
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Low agent participation rate"
          description: "Only {{ $value | humanizePercentage }} of agents are participating"
      
      # Consensus alerts
      - alert: NoConsensusFormed
        expr: rate(merid_consensus_decisions_total[5m]) == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "No consensus formed in 10 minutes"
          description: "Consensus rate is zero - check if agents are voting"
      
      - alert: HighDisagreementRate
        expr: merid_swarm_avg_disagreement_rate > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High disagreement rate"
          description: "Disagreement rate is {{ $value | humanizePercentage }}"
      
      # Execution alerts
      - alert: HighOrderRejectionRate
        expr: rate(merid_orders_rejected_total[5m]) / rate(merid_orders_total[5m]) > 0.2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High order rejection rate"
          description: "{{ $value | humanizePercentage }} of orders are being rejected"
      
      - alert: HighExecutionLatency
        expr: merid_execution_latency_p99_ms > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High execution latency"
          description: "P99 latency is {{ $value }}ms (>10s)"
      
      # Watchdog alerts
      - alert: StaleStateDetected
        expr: merid_watchdog_staleness_violations_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Stale state detected"
          description: "{{ $value }} stale state violations detected"
      
      - alert: ModeViolation
        expr: merid_watchdog_mode_violations_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Trading mode violation detected"
          description: "{{ $value }} mode violations - check for live calls in simulation"

  - name: system_health
    interval: 30s
    rules:
      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes > 2e9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Process using {{ $value | humanize1024 }}B of memory"
      
      - alert: HighErrorRate
        expr: rate(merid_errors_total[5m]) > 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate"
          description: "{{ $value }} errors per second"
```

---

## 2. Grafana Dashboards

### Installation

```bash
# Docker
docker run -d -p 3000:3000 --name=grafana grafana/grafana

# Access at http://localhost:3000
# Default login: admin/admin
```

### Data Source Setup

1. Navigate to Configuration → Data Sources
2. Add Prometheus data source
3. URL: `http://localhost:9090`
4. Save & Test

### Dashboard JSON

Create `merid_swarm_dashboard.json`:

```json
{
  "dashboard": {
    "title": "MERID Swarm Overview",
    "panels": [
      {
        "title": "Agent Participation Rate",
        "targets": [
          {
            "expr": "merid_swarm_participation_rate",
            "legendFormat": "Participation"
          }
        ],
        "type": "graph"
      },
      {
        "title": "Opinions per Minute",
        "targets": [
          {
            "expr": "rate(merid_opinions_total[1m]) * 60",
            "legendFormat": "Opinions/min"
          }
        ],
        "type": "graph"
      },
      {
        "title": "Consensus Success Rate",
        "targets": [
          {
            "expr": "rate(merid_consensus_successful_total[5m]) / rate(merid_consensus_total[5m])",
            "legendFormat": "Success Rate"
          }
        ],
        "type": "gauge"
      },
      {
        "title": "Active Agents",
        "targets": [
          {
            "expr": "merid_swarm_active_agents",
            "legendFormat": "Active"
          },
          {
            "expr": "merid_swarm_total_agents",
            "legendFormat": "Total"
          }
        ],
        "type": "stat"
      },
      {
        "title": "Pipeline Latency (P99)",
        "targets": [
          {
            "expr": "merid_pipeline_latency_p99_ms",
            "legendFormat": "P99 Latency"
          }
        ],
        "type": "graph"
      }
    ]
  }
}
```

### Key Dashboards to Create

1. **Swarm Overview**
   - Agent participation
   - Opinion/consensus rates
   - Health status
   - Active alerts

2. **Agent Health**
   - Per-agent heartbeats
   - Processing latency
   - Error rates
   - Opinion counts

3. **Trading Performance**
   - Orders executed
   - Fill rates
   - Slippage
   - P&L

4. **System Performance**
   - CPU/Memory usage
   - Request rates
   - Response times
   - Error rates

---

## 3. Logging Setup

### Structured Logging Configuration

Update `utils/logger.py`:

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""
    
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "agent_id"):
            log_data["agent_id"] = record.agent_id
        if hasattr(record, "symbol"):
            log_data["symbol"] = record.symbol
        
        return json.dumps(log_data)

# Configure handlers
json_handler = logging.FileHandler("logs/merid.json.log")
json_handler.setFormatter(JSONFormatter())

logger = logging.getLogger("merid")
logger.addHandler(json_handler)
```

### Log Aggregation with ELK

#### Elasticsearch

```bash
docker run -d --name elasticsearch -p 9200:9200 -e "discovery.type=single-node" elasticsearch:8.8.0
```

#### Logstash

Create `logstash.conf`:

```conf
input {
  file {
    path => "/var/log/merid/*.json.log"
    codec => "json"
    type => "merid-swarm"
  }
}

filter {
  if [type] == "merid-swarm" {
    # Parse timestamp
    date {
      match => [ "timestamp", "ISO8601" ]
      target => "@timestamp"
    }
    
    # Add tags for easier filtering
    if [logger] =~ /agent/ {
      mutate { add_tag => ["agent"] }
    }
    if [logger] =~ /consensus/ {
      mutate { add_tag => ["consensus"] }
    }
    if [logger] =~ /execution/ {
      mutate { add_tag => ["execution"] }
    }
  }
}

output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "merid-swarm-%{+YYYY.MM.dd}"
  }
}
```

#### Kibana

```bash
docker run -d --name kibana -p 5601:5601 kibana:8.8.0
```

---

## 4. Real-Time Monitoring

### Monitoring Dashboard Script

Create `scripts/monitor_live.py`:

```python
"""Real-time monitoring dashboard for terminal."""

import asyncio
import httpx
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()

async def monitor():
    """Display live monitoring dashboard."""
    
    async with httpx.AsyncClient() as client:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                try:
                    # Fetch stats
                    response = await client.get("http://localhost:8000/api/v1/swarm/stats")
                    stats = response.json()
                    
                    # Build table
                    table = Table(title=f"MERID Swarm Monitor - {datetime.now().strftime('%H:%M:%S')}")
                    
                    table.add_column("Metric", style="cyan")
                    table.add_column("Value", style="green")
                    table.add_column("Status", style="yellow")
                    
                    swarm = stats["swarm"]
                    
                    # Add rows
                    table.add_row(
                        "Active Agents",
                        f"{swarm['active_agents']}/{swarm['total_agents']}",
                        "✓" if swarm['participation_rate'] > 0.9 else "⚠"
                    )
                    table.add_row(
                        "Participation",
                        f"{swarm['participation_rate']:.1%}",
                        "✓" if swarm['participation_rate'] > 0.8 else "✗"
                    )
                    table.add_row(
                        "Opinions/min",
                        f"{swarm['opinions_per_minute']:.1f}",
                        "✓" if swarm['opinions_per_minute'] > 5 else "⚠"
                    )
                    table.add_row(
                        "Consensus/min",
                        f"{swarm['consensus_per_minute']:.1f}",
                        "✓" if swarm['consensus_per_minute'] > 1 else "⚠"
                    )
                    table.add_row(
                        "Pipeline Latency",
                        f"{swarm['pipeline_latency_ms']:.0f}ms",
                        "✓" if swarm['pipeline_latency_ms'] < 5000 else "✗"
                    )
                    
                    live.update(table)
                    
                    await asyncio.sleep(1)
                
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(monitor())
```

Run: `python scripts/monitor_live.py`

---

## 5. Alert Notifications

### Alertmanager Setup

Create `alertmanager.yml`:

```yaml
global:
  resolve_timeout: 5m
  slack_api_url: 'YOUR_SLACK_WEBHOOK'

route:
  group_by: ['alertname', 'cluster']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'team-notifications'
  
  routes:
    - match:
        severity: critical
      receiver: 'critical-alerts'
      continue: true
    
    - match:
        severity: warning
      receiver: 'warning-alerts'

receivers:
  - name: 'team-notifications'
    slack_configs:
      - channel: '#merid-alerts'
        title: 'MERID Swarm Alert'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
  
  - name: 'critical-alerts'
    slack_configs:
      - channel: '#merid-critical'
        title: '🚨 CRITICAL: MERID Swarm'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_KEY'
  
  - name: 'warning-alerts'
    slack_configs:
      - channel: '#merid-warnings'
        title: '⚠️ Warning: MERID Swarm'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

---

## 6. Health Check Endpoints

### Implement Health Checks

Add to `web/api/swarm_routes.py`:

```python
@router.get("/health/detailed")
async def detailed_health_check() -> Dict:
    """Comprehensive health check."""
    
    checks = {
        "event_stream": await check_event_stream(),
        "telemetry": await check_telemetry(),
        "consensus": await check_consensus(),
        "execution": await check_execution(),
        "order_router": await check_order_router(),
        "watchdogs": await check_watchdogs(),
    }
    
    all_healthy = all(checks.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks,
        "timestamp": time.time(),
    }
```

---

## 7. Monitoring Queries

### Useful Prometheus Queries

```promql
# Agent health
merid_agent_last_heartbeat_seconds < 60

# Opinion rate by agent
rate(merid_opinions_total[5m]) by (agent_id)

# Consensus success rate
rate(merid_consensus_successful_total[5m]) / rate(merid_consensus_total[5m])

# Execution latency percentiles
histogram_quantile(0.99, rate(merid_execution_latency_ms_bucket[5m]))
histogram_quantile(0.95, rate(merid_execution_latency_ms_bucket[5m]))
histogram_quantile(0.50, rate(merid_execution_latency_ms_bucket[5m]))

# Error rate
rate(merid_errors_total[5m])

# Memory usage
process_resident_memory_bytes / 1024 / 1024

# Agent disagreement
merid_swarm_avg_disagreement_rate
```

---

## 8. Automated Monitoring

### Daily Health Report

Create `scripts/daily_health_report.py`:

```python
"""Generate daily health report."""

import asyncio
import httpx
from datetime import datetime, timedelta

async def generate_report():
    """Generate and send daily report."""
    
    async with httpx.AsyncClient() as client:
        # Fetch 24h stats
        stats = await client.get("http://localhost:8000/api/v1/swarm/stats")
        
        # Generate report
        report = f"""
        MERID Swarm Daily Health Report
        Date: {datetime.now().strftime('%Y-%m-%d')}
        
        Agent Health:
        - Participation Rate: {stats['participation_rate']:.1%}
        - Active Agents: {stats['active_agents']}/{stats['total_agents']}
        
        Performance:
        - Opinions: {stats['opinions_per_minute']:.1f}/min
        - Consensus: {stats['consensus_per_minute']:.1f}/min
        - Pipeline Latency: {stats['pipeline_latency_ms']:.0f}ms
        
        Issues: {len(stats.get('health_issues', {}))}
        """
        
        # Send report (email, Slack, etc.)
        print(report)

if __name__ == "__main__":
    asyncio.run(generate_report())
```

Run daily: `crontab -e` → `0 8 * * * python /path/to/daily_health_report.py`

---

## Quick Reference

### Check System Health
```bash
curl http://localhost:8000/api/v1/swarm/health | jq
```

### View Metrics
```bash
curl http://localhost:8000/api/v1/swarm/metrics/prometheus
```

### Monitor Logs
```bash
tail -f logs/merid.log | jq
```

### Check Prometheus Targets
```bash
curl http://localhost:9090/api/v1/targets | jq
```

---

**Last Updated**: 2026-02-06  
**Version**: 1.0

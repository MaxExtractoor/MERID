# MERID Dev Swarm - Production Deployment Guide

**Version**: 2.0  
**Status**: Production-Ready with 24/7 Operational Support  
**Last Updated**: 2026-02-06

---

## Overview

This guide covers deploying the MERID Dev Swarm for 24/7 production operation with full persistence, monitoring, and operational management.

---

## New Features (Production Hardening)

### ✅ State Persistence
- Tasks survive restarts
- JSONL append-only storage
- Automatic state recovery on startup
- Storage compaction utilities
- Metadata persistence (costs, timestamps)

### ✅ Prometheus Metrics
- 15+ metrics exported
- Task execution tracking
- Cost monitoring
- Agent performance metrics
- Success rate gauges

### ✅ CLI Management Tool
- `swarm_cli.py` for operations
- Status checks
- Task management
- Statistics reporting
- Storage maintenance

### ✅ 24/7 Daemon Support
- Systemd service file
- Auto-restart on failure
- Resource limits
- Security hardening
- Health checks

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer                         │
│                   (nginx/Traefik)                        │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              FastAPI Backend (uvicorn)                   │
│  - Dev Swarm API (9 endpoints)                          │
│  - Metrics endpoint (/metrics)                          │
│  - Health endpoint (/health)                            │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  DevSwarm Core                           │
│  - Task execution engine                                │
│  - Agent orchestration                                  │
│  - Safety limits enforcement                            │
│  - Persistence layer                                    │
│  - Metrics collection                                   │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
┌────────▼──────┐      ┌─────────▼──────────┐
│  Persistence  │      │  Metrics Export    │
│  (JSONL)      │      │  (Prometheus)      │
│               │      │                    │
│  data/        │      │  /metrics          │
│  - tasks.jsonl│      │                    │
│  - metadata   │      └────────┬───────────┘
└───────────────┘               │
                     ┌──────────▼──────────┐
                     │  Monitoring Stack   │
                     │  - Prometheus       │
                     │  - Grafana          │
                     │  - Alertmanager     │
                     └─────────────────────┘
```

---

## Prerequisites

### System Requirements

- **OS**: Linux (Ubuntu 20.04+ / CentOS 8+ / Debian 11+)
- **Python**: 3.9+
- **Memory**: 2GB minimum, 4GB recommended
- **Disk**: 10GB minimum (for task storage)
- **CPU**: 2 cores minimum

### Software Dependencies

```bash
# Python packages
pip install fastapi uvicorn pydantic structlog prometheus_client

# Optional but recommended
pip install rich httpx  # For CLI tool
```

### Network Requirements

- Port 8000: FastAPI application
- Port 9090: Prometheus (if running locally)
- Port 3000: Grafana (if running locally)

---

## Installation

### 1. Prepare System

```bash
# Create merid user
sudo useradd -r -m -s /bin/bash merid

# Create directories
sudo mkdir -p /opt/merid/{data,logs}
sudo chown -R merid:merid /opt/merid

# Switch to merid user
sudo su - merid
```

### 2. Deploy Application

```bash
# Clone/copy MERID to /opt/merid
cd /opt/merid
git clone <repo> . || rsync -av /path/to/MERID/ .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Create .env file
cat > .env << 'EOF'
# Application
PYTHONUNBUFFERED=1
RUN_MODE=simulation

# Dev Swarm
DEV_SWARM_MAX_CONCURRENT_TASKS=5
DEV_SWARM_MAX_DAILY_COST_USD=100.0
DEV_SWARM_STORAGE_PATH=data/dev_swarm
DEV_SWARM_ENABLE_PERSISTENCE=true
DEV_SWARM_ENABLE_METRICS=true

# Monitoring
PROMETHEUS_METRICS_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/merid.log
EOF

chmod 600 .env
```

### 4. Install Systemd Service

```bash
# Copy service file
sudo cp deploy/merid-dev-swarm.service /etc/systemd/system/

# Edit paths if needed
sudo vim /etc/systemd/system/merid-dev-swarm.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable merid-dev-swarm
```

---

## Starting the Service

### Start Service

```bash
# Start immediately
sudo systemctl start merid-dev-swarm

# Check status
sudo systemctl status merid-dev-swarm

# View logs
sudo journalctl -u merid-dev-swarm -f
```

### Verify Deployment

```bash
# Using CLI tool
python scripts/swarm_cli.py status

# Expected output:
# ┏━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
# ┃ Check        ┃ Status    ┃
# ┡━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
# │ API Status   │ healthy   │
# │ Active Tasks │ 0         │
# │ Agents       │ 4         │
# └──────────────┴───────────┘

# Using HTTP
curl http://localhost:8000/api/dev-swarm/health | jq

# Check metrics endpoint
curl http://localhost:8000/metrics | grep merid_dev_swarm
```

---

## Configuration

### Systemd Service Options

Edit `/etc/systemd/system/merid-dev-swarm.service`:

```ini
# Change number of workers
ExecStart=/opt/merid/venv/bin/python -m uvicorn web.main:app --workers 4

# Change port
ExecStart=... --port 8080

# Add custom environment variables
Environment="DEV_SWARM_MAX_CONCURRENT_TASKS=10"
```

After changes:
```bash
sudo systemctl daemon-reload
sudo systemctl restart merid-dev-swarm
```

### DevSwarm Configuration

Edit configuration in code or via environment variables:

```python
# config/dev_swarm_config.py (create if needed)
from core.dev_swarm import SwarmConfig

def get_prod_config():
    return SwarmConfig(
        max_concurrent_tasks=10,
        max_concurrent_agents=20,
        default_task_timeout=3600,  # 1 hour
        max_daily_cost_usd=200.0,
        enable_cost_tracking=True,
        enable_timeouts=True,
        enable_metrics=True
    )
```

---

## Monitoring Setup

### Prometheus Configuration

Create `/etc/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'merid-dev-swarm'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

### Grafana Dashboard

Import dashboard JSON (create `grafana/dev_swarm_dashboard.json`):

```json
{
  "dashboard": {
    "title": "MERID Dev Swarm",
    "panels": [
      {
        "title": "Active Tasks",
        "targets": [{
          "expr": "merid_dev_swarm_tasks_active"
        }]
      },
      {
        "title": "Task Completion Rate",
        "targets": [{
          "expr": "rate(merid_dev_swarm_tasks_completed_total[5m])"
        }]
      },
      {
        "title": "Success Rate",
        "targets": [{
          "expr": "merid_dev_swarm_success_rate"
        }]
      },
      {
        "title": "Daily Cost",
        "targets": [{
          "expr": "merid_dev_swarm_daily_cost_usd"
        }]
      }
    ]
  }
}
```

### Alert Rules

Create `/etc/prometheus/alerts/dev_swarm.yml`:

```yaml
groups:
  - name: dev_swarm_alerts
    interval: 30s
    rules:
      - alert: DevSwarmHighFailureRate
        expr: merid_dev_swarm_success_rate < 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Dev Swarm success rate below 50%"
          
      - alert: DevSwarmCostBudgetNearLimit
        expr: merid_dev_swarm_daily_cost_usd > 90
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Dev Swarm daily cost near budget limit"
          
      - alert: DevSwarmServiceDown
        expr: up{job="merid-dev-swarm"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Dev Swarm service is down"
```

---

## Operations

### CLI Commands

```bash
# Get status
python scripts/swarm_cli.py status

# List tasks
python scripts/swarm_cli.py list-tasks
python scripts/swarm_cli.py list-tasks --status=running --limit=50

# Create task
python scripts/swarm_cli.py create-task --file task.json

# Cancel task
python scripts/swarm_cli.py cancel-task task-1707186300000

# Show stats
python scripts/swarm_cli.py stats

# Compact storage (keep recent 1000 tasks)
python scripts/swarm_cli.py compact-storage
```

### Service Management

```bash
# Restart service
sudo systemctl restart merid-dev-swarm

# Stop service
sudo systemctl stop merid-dev-swarm

# Check logs
sudo journalctl -u merid-dev-swarm -f

# Check last 100 lines
sudo journalctl -u merid-dev-swarm -n 100

# Check logs from today
sudo journalctl -u merid-dev-swarm --since today
```

### Storage Management

```bash
# Check storage size
du -sh /opt/merid/data/dev_swarm

# View recent tasks
tail -n 20 /opt/merid/data/dev_swarm/tasks.jsonl | jq

# Compact storage (removes old tasks)
python scripts/swarm_cli.py compact-storage

# Backup storage
tar -czf dev_swarm_backup_$(date +%Y%m%d).tar.gz /opt/merid/data/dev_swarm
```

---

## Backup & Recovery

### Backup Strategy

**Daily Backups**:
```bash
#!/bin/bash
# /opt/merid/scripts/backup.sh

BACKUP_DIR=/opt/merid/backups
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
tar -czf $BACKUP_DIR/dev_swarm_$DATE.tar.gz \
    /opt/merid/data/dev_swarm \
    /opt/merid/.env

# Keep only last 30 days
find $BACKUP_DIR -name "dev_swarm_*.tar.gz" -mtime +30 -delete

echo "Backup complete: dev_swarm_$DATE.tar.gz"
```

Add to crontab:
```bash
# Run daily at 2 AM
0 2 * * * /opt/merid/scripts/backup.sh >> /opt/merid/logs/backup.log 2>&1
```

### Recovery

```bash
# Stop service
sudo systemctl stop merid-dev-swarm

# Restore data
cd /opt/merid
tar -xzf backups/dev_swarm_20260206_020000.tar.gz

# Start service
sudo systemctl start merid-dev-swarm

# Verify
python scripts/swarm_cli.py status
```

---

## Performance Tuning

### Resource Limits

Edit systemd service:
```ini
# Increase file descriptors
LimitNOFILE=65536

# Limit CPU usage (50%)
CPUQuota=50%

# Limit memory (2GB)
MemoryLimit=2G
```

### Concurrent Tasks

Adjust based on available resources:

- **2 CPU cores**: max_concurrent_tasks=3
- **4 CPU cores**: max_concurrent_tasks=5
- **8 CPU cores**: max_concurrent_tasks=10

### Storage Optimization

```bash
# Compact frequently (keeps recent 500 tasks)
python scripts/swarm_cli.py compact-storage --keep=500

# Use faster disk (SSD) for data/dev_swarm
```

---

## Security Hardening

### File Permissions

```bash
# Restrict data directory
chmod 700 /opt/merid/data
chown -R merid:merid /opt/merid/data

# Protect environment file
chmod 600 /opt/merid/.env
chown merid:merid /opt/merid/.env
```

### Network Security

```bash
# Firewall rules (allow only from trusted IPs)
sudo ufw allow from 10.0.0.0/8 to any port 8000 proto tcp
sudo ufw deny 8000

# Or use nginx reverse proxy with auth
```

### Authentication

Add to `web/api/dev_swarm_routes.py`:

```python
from fastapi import Depends, HTTPException, Header

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("DEV_SWARM_API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Add to routes
@router.post("/tasks", dependencies=[Depends(verify_api_key)])
async def create_task(...):
    ...
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check systemd status
sudo systemctl status merid-dev-swarm

# Check logs
sudo journalctl -u merid-dev-swarm -xe

# Common issues:
# - Port already in use: Change port in service file
# - Permission denied: Check file ownership
# - Module not found: Activate venv, reinstall deps
```

### High Memory Usage

```bash
# Check memory
ps aux | grep uvicorn

# Add memory limit to systemd service
MemoryLimit=2G

# Reduce concurrent tasks
# Edit .env: DEV_SWARM_MAX_CONCURRENT_TASKS=3
```

### Storage Growing Too Large

```bash
# Check size
du -sh /opt/merid/data/dev_swarm

# Compact storage
python scripts/swarm_cli.py compact-storage

# Or manually limit tasks.jsonl
head -n 1000 tasks.jsonl > tasks_new.jsonl
mv tasks_new.jsonl tasks.jsonl
```

### Tasks Not Persisting

```bash
# Check persistence is enabled
grep PERSISTENCE .env

# Check directory permissions
ls -la /opt/merid/data/dev_swarm

# Check logs
grep "persistence" /opt/merid/logs/merid.log
```

---

## Maintenance Schedule

### Daily
- ✅ Check service status
- ✅ Review error logs
- ✅ Monitor active tasks

### Weekly
- ✅ Review stats and success rate
- ✅ Check storage size
- ✅ Compact storage if needed
- ✅ Review cost usage

### Monthly
- ✅ Update dependencies
- ✅ Review and optimize configuration
- ✅ Test backup/recovery
- ✅ Review security logs

---

## Upgrade Procedure

```bash
# 1. Backup current state
/opt/merid/scripts/backup.sh

# 2. Stop service
sudo systemctl stop merid-dev-swarm

# 3. Pull/copy new code
cd /opt/merid
git pull origin main  # or rsync from deployment source

# 4. Update dependencies
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 5. Run migrations if any
# python scripts/migrate.py

# 6. Start service
sudo systemctl start merid-dev-swarm

# 7. Verify
python scripts/swarm_cli.py status

# 8. Monitor logs
sudo journalctl -u merid-dev-swarm -f
```

---

## Production Checklist

### Before Going Live

- [ ] Persistence enabled and tested
- [ ] Systemd service installed and tested
- [ ] Monitoring configured (Prometheus + Grafana)
- [ ] Alerts configured and tested
- [ ] Backups configured and tested
- [ ] Security hardening applied
- [ ] Resource limits set
- [ ] CLI tool tested
- [ ] Documentation reviewed
- [ ] Team trained on operations

### Post-Deployment

- [ ] Monitor for 24 hours
- [ ] Verify tasks persist across restart
- [ ] Check metrics are being collected
- [ ] Verify alerts trigger correctly
- [ ] Test backup/recovery procedure
- [ ] Document any issues

---

## Success Metrics

**Healthy Production System**:
- Uptime: > 99.9%
- Success rate: > 80%
- Average task duration: < 10 minutes
- Daily cost: Within budget
- Storage size: Stable (with compaction)
- Zero critical errors

**Monitor**:
```bash
# Quick health check
python scripts/swarm_cli.py stats

# Should show:
# - Success Rate > 80%
# - Active Tasks < max_concurrent
# - Daily Cost < budget
# - No recent errors
```

---

## Support & Resources

**Documentation**:
- `QUICKSTART_DEV_SWARM.md` - Quick start guide
- `DEV_SWARM_INTEGRATION_SUMMARY.md` - Complete integration details
- `AGENT_SPAWNER_SPEC.md` - Technical specification

**CLI Help**:
```bash
python scripts/swarm_cli.py --help
```

**Logs**:
- Service logs: `sudo journalctl -u merid-dev-swarm -f`
- Application logs: `/opt/merid/logs/merid.log`

**Metrics**:
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Metrics endpoint: `http://localhost:8000/metrics`

---

**Deployment complete!** Your MERID Dev Swarm is now ready for 24/7 production operation.

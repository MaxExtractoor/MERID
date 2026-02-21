# MERID Deployment Guide - Multi-Port Architecture

**Version**: 2.0  
**Date**: 2026-01-13  
**Status**: Production Ready

---

## Overview

MERID now runs as 4 independent services on separate ports, providing proper isolation between user-facing, agent, admin, and monitoring concerns.

### Service Architecture

| Service   | Port | Binding   | Purpose                                | Access         |
|-----------|------|-----------|----------------------------------------|----------------|
| User UI   | 3000 | 0.0.0.0   | Public dashboard, user interactions    | Public         |
| Agent Mesh| 8080 | 127.0.0.1 | Agent communication, coordination      | Localhost only |
| Ops/Admin | 9090 | 127.0.0.1 | System control, administration         | Localhost only |
| Telemetry | 9091 | 127.0.0.1 | Metrics, health checks, monitoring     | Localhost only |

---

## Quick Start

### Single Command Startup

```bash
python start_merid.py
```

This starts all 4 services in separate processes with automatic monitoring and graceful shutdown.

### Individual Service Startup

```bash
# User UI only
python -m web.user_app

# Agent Mesh only
python -m web.agent_app

# Ops/Admin only
python -m web.ops_app

# Telemetry only
python -m web.metrics_app
```

---

## Service Details

### 1. User UI (Port 3000)

**File**: `web/user_app.py`

**Endpoints**:

- `/` - Redirect to dashboard
- `/dashboard` - Main unified dashboard
- `/institutional` - Institutional control center
- `/simulation` - Simulation monitor
- `/live` - Live intelligence monitor
- `/trading/perps` - Perpetual trading
- `/trading/markets` - Prediction markets
- `/betting` - Betting system

**API Routes**:

- `/api/v1/dashboard/*` - Dashboard data
- `/api/v1/live/*` - Live market data
- `/api/v1/intelligence/*` - Market intelligence
- `/api/v1/predictions/*` - Prediction markets
- `/api/v1/institutional/*` - Institutional endpoints
- `/api/v1/trading/*` - Trading operations
- `/api/v1/betting/*` - Betting system
- `/api/v1/wallet/*` - Wallet management
- `/api/v1/notifications/*` - User notifications
- `/api/v1/auth/*` - Authentication
- `/api/v1/referrals/*` - Referral system
- `/api/v1/paper-trading/*` - Paper trading
- `/api/v1/arbitrage/*` - Arbitrage opportunities
- `/api/v1/schemas/*` - Data schemas
- `/api/v1/streams/*` - Data streams

**Access**: Public (0.0.0.0)

**Test**:

```bash
curl http://localhost:3000/dashboard
```

### 2. Agent Mesh (Port 8080)

**File**: `web/agent_app.py`

**Endpoints**:

- `/health` - Service health check
- `/api/v1/mesh/register` - Register agent
- `/api/v1/mesh/unregister` - Unregister agent
- `/api/v1/mesh/message` - Send message
- `/api/v1/mesh/status` - Mesh status
- `/api/v1/mesh/agents` - List agents
- `/api/v1/agents/*` - Agent management
- `/api/v1/reflection/*` - Reflection system

**Access**: Localhost only (127.0.0.1)

**Security**: Enforces localhost binding, rejects public access

**Test**:

```bash
curl http://localhost:8080/health
# Expected: {"status":"ok","service":"agent_mesh","port":8080}
```

### 3. Ops/Admin (Port 9090)

**File**: `web/ops_app.py`

**Endpoints**:

- `/health` - Service health check
- `/api/v1/system/*` - System control
- `/api/v1/ops/*` - Operations (provenance, entropy, conflicts)
- `/api/v1/monitoring/*` - Monitoring
- `/api/v1/backup/*` - Backup management
- `/api/v1/recovery/*` - Recovery operations
- `/api/v1/ratelimit/*` - Rate limiting
- `/api/v1/compliance/*` - Compliance
- `/api/v1/governance/*` - Governance
- `/api/v1/treasury/*` - Treasury management
- `/api/v1/archive/*` - Archive management
- `/api/v1/offline/*` - Offline mode
- `/api/v1/plugins/*` - Plugin management
- `/api/v1/cost-models/*` - Cost models
- `/api/v1/trading-mode/*` - Trading mode control
- `/api/v1/time-exploit/*` - Time exploit detection
- `/api/v1/sniping/*` - Sniping detection
- `/api/v1/mine` - Mining control
- `/api/v1/prediction/*` - Prediction admin

**Access**: Localhost only (127.0.0.1)

**Security**: Enforces localhost binding, rejects public access

**Test**:

```bash
curl http://localhost:9090/health
# Expected: {"status":"ok","service":"ops_admin","port":9090}
```

### 4. Telemetry (Port 9091)

**File**: `web/metrics_app.py`

**Endpoints**:

- `/metrics` - Prometheus-compatible metrics
- `/health` - Overall health
- `/health/agents` - Agent health
- `/health/consensus` - Consensus health
- `/health/database` - Database health
- `/health/external` - External API health
- `/stats/reflection` - Reflection stats
- `/stats/agents` - Agent stats
- `/stats/consensus` - Consensus stats
- `/stats/mesh` - Mesh stats
- `/stats/api` - API stats

**Access**: Localhost only (127.0.0.1)

**Security**: Enforces localhost binding, rejects public access

**Test**:

```bash
curl http://localhost:9091/metrics
# Expected: Prometheus text format metrics
```

---

## Health Checks

### All Services

```bash
# User UI
curl http://localhost:3000/

# Agent Mesh
curl http://localhost:8080/health

# Ops/Admin
curl http://localhost:9090/health

# Telemetry
curl http://localhost:9091/health
```

### Expected Responses

All health endpoints should return `200 OK` with JSON status.

---

## Monitoring

### Prometheus Integration

Point Prometheus to scrape:

```yaml
scrape_configs:
  - job_name: 'merid'
    static_configs:
      - targets: ['localhost:9091']
```

### Metrics Available

- `merid_uptime_seconds` - System uptime
- `merid_requests_total` - Total HTTP requests
- `merid_reflections_total` - Total agent reflections
- `merid_validations_total` - Total outcome validations
- `merid_agents_active` - Currently active agents
- `merid_consensus_rounds_total` - Total consensus rounds

---

## Troubleshooting

### Service Won't Start

**Check port availability**:

```bash
netstat -ano | findstr "3000"
netstat -ano | findstr "8080"
netstat -ano | findstr "9090"
netstat -ano | findstr "9091"
```

**Kill conflicting processes**:

```bash
# Find PID from netstat output
taskkill /PID <PID> /F
```

### Service Crashes

**Check logs**:

- Logs are output to console
- Look for `ERROR` or `CRITICAL` level messages
- Check for import errors or missing dependencies

**Common issues**:

1. Missing dependencies: `pip install -r requirements.txt`
2. Port already in use: Kill conflicting process
3. Import errors: Ensure all modules are in PYTHONPATH

### Agent Mesh Not Accessible

**Verify localhost binding**:

```bash
curl http://127.0.0.1:8080/health
```

**Should fail from external IP** (security feature):

```bash
curl http://<external-ip>:8080/health
# Expected: Connection refused
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] All dependencies installed: `pip install -r requirements.txt`
- [ ] Configuration reviewed: `config/ports.py`
- [ ] Environment variables set (if needed)
- [ ] Firewall rules configured (block 8080, 9090, 9091 from external)

### Deployment

- [ ] Start services: `python start_merid.py`
- [ ] Verify all 4 services started (check console output)
- [ ] Test User UI: `curl http://localhost:3000/`
- [ ] Test Agent Mesh: `curl http://localhost:8080/health`
- [ ] Test Ops/Admin: `curl http://localhost:9090/health`
- [ ] Test Telemetry: `curl http://localhost:9091/metrics`

### Post-Deployment

- [ ] Dashboard accessible in browser
- [ ] No errors in console logs
- [ ] Prometheus scraping metrics (if configured)
- [ ] Agent mesh isolated (not accessible externally)

---

## Graceful Shutdown

### Stop All Services

Press `Ctrl+C` in the terminal running `start_merid.py`

The shutdown handler will:

1. Terminate all 4 service processes
2. Wait 2 seconds for graceful shutdown
3. Force kill any remaining processes
4. Exit cleanly

### Stop Individual Service

```bash
# Find process
ps aux | grep "user_app\|agent_app\|ops_app\|metrics_app"

# Kill process
kill <PID>
```

---

## Migration from Legacy (Port 8001)

### Update Frontend API Calls

**Old** (single port):

```javascript
const API_BASE = 'http://127.0.0.1:8001';
```

**New** (multi-port):

```javascript
const USER_API = 'http://127.0.0.1:3000';
const AGENT_API = 'http://127.0.0.1:8080';  // Internal only
const OPS_API = 'http://127.0.0.1:9090';    // Internal only
const METRICS_API = 'http://127.0.0.1:9091'; // Internal only
```

### Backward Compatibility

The legacy `web/main.py` (port 8001) is still available but deprecated.

**To run legacy**:

```bash
python -m web.main
```

**Recommendation**: Migrate to new architecture for production use.

---

## Security Considerations

### Port Isolation

1. **Port 3000** - Public, accessible from internet
2. **Ports 8080, 9090, 9091** - Localhost only, blocked by firewall

### Firewall Rules

**Linux (iptables)**:

```bash
# Allow port 3000 from anywhere
iptables -A INPUT -p tcp --dport 3000 -j ACCEPT

# Block ports 8080, 9090, 9091 from external
iptables -A INPUT -p tcp --dport 8080 ! -s 127.0.0.1 -j DROP
iptables -A INPUT -p tcp --dport 9090 ! -s 127.0.0.1 -j DROP
iptables -A INPUT -p tcp --dport 9091 ! -s 127.0.0.1 -j DROP
```

**Windows Firewall**:

```powershell
# Allow port 3000
New-NetFirewallRule -DisplayName "MERID User UI" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow

# Block ports 8080, 9090, 9091 from external
New-NetFirewallRule -DisplayName "MERID Agent Mesh" -Direction Inbound -LocalPort 8080 -Protocol TCP -RemoteAddress 127.0.0.1 -Action Allow
New-NetFirewallRule -DisplayName "MERID Ops Admin" -Direction Inbound -LocalPort 9090 -Protocol TCP -RemoteAddress 127.0.0.1 -Action Allow
New-NetFirewallRule -DisplayName "MERID Telemetry" -Direction Inbound -LocalPort 9091 -Protocol TCP -RemoteAddress 127.0.0.1 -Action Allow
```

---

## Performance Tuning

### Uvicorn Workers

For production, use multiple workers:

```bash
# User UI (public-facing, needs more workers)
uvicorn web.user_app:app --host 0.0.0.0 --port 3000 --workers 4

# Agent Mesh (internal, fewer workers)
uvicorn web.agent_app:app --host 127.0.0.1 --port 8080 --workers 2

# Ops/Admin (low traffic)
uvicorn web.ops_app:app --host 127.0.0.1 --port 9090 --workers 1

# Telemetry (metrics only)
uvicorn web.metrics_app:app --host 127.0.0.1 --port 9091 --workers 1
```

### Resource Limits

Monitor resource usage per service:

```bash
# CPU and memory per process
ps aux | grep "user_app\|agent_app\|ops_app\|metrics_app"
```

---

## Support

For issues or questions:

1. Check logs for error messages
2. Verify all services are running: `curl http://localhost:<port>/health`
3. Review this deployment guide
4. Check `docs/PORT_MIGRATION_GUIDE.md` for detailed migration steps

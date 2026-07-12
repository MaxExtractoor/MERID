# Kalshi 15m Monitoring, Alerting, and Health Checks Documentation

## Overview

The Kalshi 15m monitoring system provides comprehensive health checks, alerting, and observability for the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE). The system includes health endpoints, WebSocket monitoring, agent health tracking, and alerting mechanisms.

## Architecture

### Component Hierarchy

```
HealthMonitor (Core Infrastructure)
├── ComponentHealth (Individual Component Status)
│   ├── Event Bus Health
│   ├── Consensus Engine Health
│   ├── Execution Engine Health
│   ├── Agent Mesh Health
│   └── System Resources Health
├── Health Endpoints (FastAPI)
│   ├── /api/health (Global Health)
│   ├── /api/websocket/health (WebSocket Health)
│   └── /api/v1/agents/health (Agent Health)
└── Alerting System
    ├── Alert Rules
    ├── Notification Channels
    └── Escalation Policies
```

### Key Files

- **Core Health**: `core/health.py`
- **Health API**: `web/api/health.py`
- **WebSocket Health**: `web/api/websocket_health.py`
- **Agent Health**: `web/api/agents_health.py`
- **Alert Rules**: `notifications/alert_rules.py`
- **Alerting Utils**: `utils/alerting.py`

## Health Monitor (Core Infrastructure)

### Purpose

The health monitor tracks health of all MERID components and provides status endpoints for observability and k8s probes.

### Health Status Levels

```python
class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
```

### Component Health

```python
@dataclass
class ComponentHealth:
    """Health status of a component."""
    name: str
    status: HealthStatus
    message: str = ""
    last_check: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "last_check": self.last_check,
            "metrics": self.metrics,
        }
```

### Health Monitor Initialization

```python
class HealthMonitor:
    """Monitors health of all MERID components."""
    
    def __init__(self):
        self._components: Dict[str, ComponentHealth] = {}
        self._start_time = time.time()
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
```

### Component Checks

#### Event Bus Health

```python
async def _check_event_bus(self) -> None:
    """Check event bus health."""
    try:
        from core.streaming_bus import streaming_bus
        
        metrics = streaming_bus.get_metrics()
        
        status = HealthStatus.HEALTHY
        message = "Event bus operational"
        
        if metrics.get("total_events", 0) == 0:
            status = HealthStatus.DEGRADED
            message = "No events processed yet"
        
        self._components["event_bus"] = ComponentHealth(
            name="Event Bus",
            status=status,
            message=message,
            metrics={
                "total_events": metrics.get("total_events", 0),
                "subscribers": metrics.get("total_subscribers", 0),
            },
        )
    except (ImportError, AttributeError, RuntimeError) as e:
        self._components["event_bus"] = ComponentHealth(
            name="Event Bus",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )
```

#### Consensus Engine Health

```python
async def _check_consensus_engine(self) -> None:
    """Check consensus engine health."""
    try:
        from core.consensus_engine import get_consensus_engine
        
        engine = get_consensus_engine()
        
        running = getattr(engine, 'running', False)
        status = HealthStatus.HEALTHY if running else HealthStatus.DEGRADED
        message = "Running" if running else "Not running"
        
        pending = getattr(engine, 'pending_votes', {})
        
        self._components["consensus"] = ComponentHealth(
            name="Consensus Engine",
            status=status,
            message=message,
            metrics={
                "running": running,
                "pending_votes": len(pending) if isinstance(pending, dict) else 0,
            },
        )
    except (ImportError, AttributeError, RuntimeError) as e:
        self._components["consensus"] = ComponentHealth(
            name="Consensus Engine",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )
```

#### Execution Engine Health

```python
async def _check_execution_engine(self) -> None:
    """Check execution engine health."""
    try:
        from trading.execution import get_execution_engine
        
        engine = get_execution_engine()
        
        running = getattr(engine, 'running', True)
        mode = getattr(engine.config, 'mode', None)
        mode_value = mode.value if mode else 'unknown'
        
        status = HealthStatus.HEALTHY if running else HealthStatus.DEGRADED
        message = f"Mode: {mode_value}"
        
        self._components["execution"] = ComponentHealth(
            name="Execution Engine",
            status=status,
            message=message,
            metrics={
                "running": running,
                "mode": mode_value,
                "balance": getattr(engine, '_balance', 0),
                "positions": len(getattr(engine, '_positions', {})),
            },
        )
    except (ImportError, AttributeError, RuntimeError) as e:
        self._components["execution"] = ComponentHealth(
            name="Execution Engine",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )
```

#### Agent Mesh Health

```python
async def _check_agent_mesh(self) -> None:
    """Check agent mesh health."""
    try:
        from agents.agent_mesh import agent_mesh
        
        running_agents = sum(1 for a in agent_mesh.agents if a.running)
        total_agents = len(agent_mesh.agents)
        
        status = HealthStatus.HEALTHY
        message = f"{running_agents}/{total_agents} agents running"
        
        if running_agents == 0:
            status = HealthStatus.UNHEALTHY
        elif running_agents < total_agents:
            status = HealthStatus.DEGRADED
        
        self._components["agent_mesh"] = ComponentHealth(
            name="Agent Mesh",
            status=status,
            message=message,
            metrics={
                "running_agents": running_agents,
                "total_agents": total_agents,
            },
        )
    except (ImportError, AttributeError, RuntimeError) as e:
        self._components["agent_mesh"] = ComponentHealth(
            name="Agent Mesh",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )
```

#### System Resources Health

```python
async def _check_system_resources(self) -> None:
    """Check system resources (CPU, memory, disk)."""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        status = HealthStatus.HEALTHY
        message = "System resources OK"
        
        # Check CPU
        if cpu_percent > 90:
            status = HealthStatus.DEGRADED
            message = f"High CPU: {cpu_percent}%"
        
        # Check memory
        if memory.percent > 90:
            status = HealthStatus.DEGRADED
            message = f"High memory: {memory.percent}%"
        
        # Check disk
        if disk.percent > 90:
            status = HealthStatus.DEGRADED
            message = f"High disk: {disk.percent}%"
        
        self._components["system_resources"] = ComponentHealth(
            name="System Resources",
            status=status,
            message=message,
            metrics={
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3),
            },
        )
    except Exception as e:
        self._components["system_resources"] = ComponentHealth(
            name="System Resources",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )
```

### Parallel Health Checks

```python
async def check_all(self) -> Dict[str, ComponentHealth]:
    """Check health of all components in parallel with timeout."""
    try:
        await asyncio.wait_for(
            asyncio.gather(
                self._check_event_bus(),
                self._check_consensus_engine(),
                self._check_execution_engine(),
                self._check_agent_mesh(),
                self._check_simulation_miner(),
                self._check_audit_trail(),
                self._check_system_resources(),
                return_exceptions=True
            ),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.warning("Health check timed out")
    
    return self._components
```

**Timeout**: 5 seconds for all checks to complete

## Health API Endpoints

### Global Health Endpoint

```python
@router.get("/api/health")
async def get_global_health(request: Request) -> dict:
    """Live health check for MERID system.
    
    Checks ExecutionGuard kill switch, Kalshi circuit breaker, MeridLoop
    liveness, and HealthMonitor status. Returns HTTP 503 when any critical
    subsystem is unhealthy so k8s probes and load balancers see real state.
    """
    ts = int(time.time())
    checks: dict = {}
    critical_failures: list = []
    
    # 1. ExecutionGuard — global kill switch
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        ks_active = guard.kill_switch_active
        checks["kill_switch"] = {
            "active": ks_active,
            "reason": guard._global_kill_reason if ks_active else None,
        }
        if ks_active:
            critical_failures.append("kill_switch_active")
    except Exception as _e:
        checks["kill_switch"] = {"error": str(_e)}
        critical_failures.append("kill_switch_check_failed")
    
    # 2. Kalshi circuit breaker
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        checks["kalshi_circuit"] = {"open": False, "note": "validation_mode_skipped"}
    else:
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            kc = get_kalshi_client()
            circuit_open = getattr(kc, "is_circuit_open", False)
            checks["kalshi_circuit"] = {
                "open": circuit_open,
                "stats": kc.get_circuit_status() if hasattr(kc, "get_circuit_status") else {},
            }
            if circuit_open:
                critical_failures.append("kalshi_circuit_open")
        except Exception as _e:
            checks["kalshi_circuit"] = {"error": str(_e)}
            critical_failures.append("kalshi_circuit_check_failed")
    
    # 3. MeridLoop liveness
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    try:
        from merid.loop_15m import get_merid_loop_15m
        loop = get_merid_loop_15m()
        loop_status = loop.status()
        running = loop_status.get("running", False)
        metrics = loop_status.get("metrics", {})
        checks["merid_loop"] = {
            "running": running,
            "total_ticks": metrics.get("total_ticks", 0),
            "tick_errors": metrics.get("tick_errors", 0),
            "last_tick_duration_ms": metrics.get("last_tick_duration_ms"),
        }
        if not running and not _is_validation:
            critical_failures.append("merid_loop_stopped")
    except Exception as _e:
        checks["merid_loop"] = {"error": str(_e)}
        if not _is_validation:
            critical_failures.append("merid_loop_check_failed")
    
    # 4. HealthMonitor (core infrastructure)
    try:
        from core.health import get_health_monitor
        hm = get_health_monitor()
        hm_status = hm.get_status() if hasattr(hm, "get_status") else {}
        checks["health_monitor"] = hm_status
    except Exception as _e:
        checks["health_monitor"] = {"error": str(_e)}
    
    # 5. Fills Ledger Health
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        checks["fills_ledger"] = {"status": "unknown", "note": "validation_mode_skipped"}
    else:
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            fl_health = await ledger.health_check()
            checks["fills_ledger"] = fl_health
            if fl_health.get("circuit_breaker", {}).get("open"):
                critical_failures.append("fills_ledger_circuit_open")
        except Exception as _e:
            checks["fills_ledger"] = {"status": "unknown", "error": str(_e)}
    
    # 6. Event-loop lag (diagnostic, not critical)
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        lag_monitor = get_loop_lag_monitor()
        lag_health = lag_monitor.get_health()
        checks["event_loop_lag"] = lag_health
    except Exception as _e:
        checks["event_loop_lag"] = {"error": str(_e)}
    
    # 7. AgentGrid readiness
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        ag = get_agent_grid()
        if _is_validation:
            checks["agent_grid"] = {
                "startup_complete": True,
                "agents_ready": True,
                "ws_ready": True,
                "running": False,
                "note": "validation_mode_skipped",
            }
        else:
            checks["agent_grid"] = {
                "startup_complete": ag._startup_complete,
                "agents_ready": ag._agents_ready,
                "ws_ready": ag._ws_ready,
                "running": ag._running,
            }
            if not ag._startup_complete:
                critical_failures.append("agent_grid_warming_up")
    except Exception as _e:
        checks["agent_grid"] = {"error": str(_e)}
        if not _is_validation:
            critical_failures.append("agent_grid_check_failed")
    
    overall = "healthy" if not critical_failures else "unhealthy"
    body = {
        "status": overall,
        "timestamp": ts,
        "critical_failures": critical_failures,
        "checks": checks,
    }
    status_code = 503 if critical_failures else 200
    return JSONResponse(content=body, status_code=status_code)
```

**Critical Checks**:
1. **Kill Switch**: Global execution guard kill switch
2. **Kalshi Circuit**: Venue circuit breaker status
3. **MeridLoop**: 15m loop liveness
4. **Fills Ledger**: Circuit breaker and DLQ status
5. **Agent Grid**: Startup completion and readiness

**HTTP Status Codes**:
- **200**: All critical checks passed
- **503**: One or more critical checks failed (k8s probes will detect this)

### Event Loop Profile Endpoint

```python
@router.get("/health/event_loop/profiles")
async def get_event_loop_profiles(request: Request) -> dict:
    """Get captured high-lag profiling data.
    
    Returns list of high-lag events with task snapshots and stack traces.
    """
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        monitor = get_loop_lag_monitor()
        profiles = monitor.get_high_lag_profiles()
        return {
            "profiles": profiles,
            "count": len(profiles),
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to get high-lag profiles: {e}")
        return {"error": str(e), "profiles": []}
```

**Purpose**: Captures high-lag events with task snapshots and stack traces for debugging performance issues.

## WebSocket Health Endpoint

### Purpose

Provides health status for all WebSocket endpoints and their connections.

### Health Check

```python
@router.get("/api/websocket/health")
async def get_websocket_health() -> Dict[str, Any]:
    """Get health status of all WebSocket endpoints."""
    health_status = {
        "status": "healthy",
        "timestamp": int(time.time() * 1000),
        "endpoints": {}
    }
    
    # Check /ws/trades endpoint
    try:
        from web.api.ws_dedicated_streams import get_trades_manager
        trades_manager = get_trades_manager()
        health_status["endpoints"]["trades"] = {
            "path": "/ws/trades",
            "status": "operational",
            "active_connections": len(trades_manager._subscribers),
            "recent_events": len(trades_manager.get_recent_trades(limit=1))
        }
    except Exception as e:
        health_status["endpoints"]["trades"] = {
            "path": "/ws/trades",
            "status": "error",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check /ws/prices endpoint
    try:
        from web.api.ws_dedicated_streams import get_prices_manager
        prices_manager = get_prices_manager()
        health_status["endpoints"]["prices"] = {
            "path": "/ws/prices",
            "status": "operational",
            "active_connections": len(prices_manager._subscribers),
            "tracked_symbols": len(prices_manager.get_current_prices())
        }
    except Exception as e:
        health_status["endpoints"]["prices"] = {
            "path": "/ws/prices",
            "status": "error",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check /ws/portfolio endpoint
    try:
        from web.api.ws_dedicated_streams import get_portfolio_manager
        portfolio_manager = get_portfolio_manager()
        health_status["endpoints"]["portfolio"] = {
            "path": "/ws/portfolio",
            "status": "operational",
            "active_connections": len(portfolio_manager._subscribers),
            "has_data": portfolio_manager.get_current_portfolio() is not None
        }
    except Exception as e:
        health_status["endpoints"]["portfolio"] = {
            "path": "/ws/portfolio",
            "status": "error",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Calculate summary statistics
    total_endpoints = len(health_status["endpoints"])
    operational_endpoints = sum(
        1 for ep in health_status["endpoints"].values() 
        if ep.get("status") == "operational"
    )
    
    health_status["summary"] = {
        "total_endpoints": total_endpoints,
        "operational": operational_endpoints,
        "degraded": total_endpoints - operational_endpoints,
        "health_percentage": round((operational_endpoints / total_endpoints * 100), 2) if total_endpoints > 0 else 0
    }
    
    # Set overall status based on health percentage
    if health_status["summary"]["health_percentage"] < 50:
        health_status["status"] = "unhealthy"
    elif health_status["summary"]["health_percentage"] < 100:
        health_status["status"] = "degraded"
    
    return health_status
```

**Endpoints Monitored**:
- `/ws/trades`: Trade stream endpoint
- `/ws/prices`: Price stream endpoint
- `/ws/portfolio`: Portfolio stream endpoint
- `/ws/paper-trading`: Paper trading endpoint
- `/ws`: General event stream endpoint

**Health Percentage**:
- **100%**: All endpoints operational
- **50-99%**: Degraded (some endpoints down)
- **< 50%**: Unhealthy (majority of endpoints down)

### Connections Endpoint

```python
@router.get("/api/websocket/connections")
async def get_websocket_connections() -> Dict[str, Any]:
    """Get detailed information about active WebSocket connections."""
    connections = {
        "timestamp": int(time.time() * 1000),
        "total_connections": 0,
        "by_endpoint": {}
    }
    
    # Get connection details for each endpoint
    try:
        from web.api.ws_dedicated_streams import (
            get_trades_manager,
            get_prices_manager,
            get_portfolio_manager
        )
        
        trades_manager = get_trades_manager()
        prices_manager = get_prices_manager()
        portfolio_manager = get_portfolio_manager()
        
        trades_count = len(trades_manager._subscribers)
        prices_count = len(prices_manager._subscribers)
        portfolio_count = len(portfolio_manager._subscribers)
        
        connections["by_endpoint"]["trades"] = {
            "path": "/ws/trades",
            "connections": trades_count,
            "recent_events_count": len(trades_manager.get_recent_trades(limit=100))
        }
        connections["by_endpoint"]["prices"] = {
            "path": "/ws/prices",
            "connections": prices_count,
            "tracked_symbols": len(prices_manager.get_current_prices())
        }
        connections["by_endpoint"]["portfolio"] = {
            "path": "/ws/portfolio",
            "connections": portfolio_count,
            "has_data": portfolio_manager.get_current_portfolio() is not None
        }
        
        connections["total_connections"] = trades_count + prices_count + portfolio_count
        
    except Exception as e:
        logger.error(f"Failed to get WebSocket connections: {e}")
        connections["error"] = str(e)
    
    return connections
```

## Agent Health Endpoint

### Purpose

Provides health and status information for all active agents in the system.

### Health Check

```python
@router.get("/api/v1/agents/health")
async def get_agents_health() -> Dict[str, Any]:
    """Get health status of all agents."""
    try:
        from core.agent_orchestrator import get_agent_orchestrator
        
        orchestrator = get_agent_orchestrator()
        agent_status = orchestrator.get_agent_status()
        
        # Transform to expected format
        agents = []
        for agent_id, status in agent_status.items():
            agents.append({
                "id": agent_id,
                "name": status.get("name", agent_id),
                "role": status.get("role", "UNKNOWN"),
                "strategy": status.get("strategy", "UNKNOWN"),
                "cluster": status.get("cluster", "default"),
                "status": status.get("status", "UNKNOWN"),
                "cpuPercent": status.get("cpu_percent", 0.0),
                "memoryMb": status.get("memory_mb", 0.0),
                "taskCount": status.get("task_count", 0),
                "latencyMs": status.get("latency_ms"),
                "lastSeen": status.get("last_seen", "")
            })
        
        # Calculate meta
        meta = {
            "total": len(agents),
            "online": sum(1 for a in agents if a["status"] == "ONLINE"),
            "degraded": sum(1 for a in agents if a["status"] == "DEGRADED"),
            "offline": sum(1 for a in agents if a["status"] == "OFFLINE")
        }
        
        return {
            "agents": agents,
            "meta": meta
        }
        
    except Exception as e:
        logger.error(f"Failed to get agents health: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Agent Status Levels**:
- **ONLINE**: Agent running normally
- **DEGRADED**: Agent running with degraded performance
- **OFFLINE**: Agent not running

**Metrics**:
- **cpuPercent**: CPU usage percentage
- **memoryMb**: Memory usage in MB
- **taskCount**: Number of active tasks
- **latencyMs**: Task latency in milliseconds
- **lastSeen**: Last activity timestamp (ISO format)

## Alerting System

### Alert Rules

Alert rules define conditions that trigger alerts and specify notification channels.

```python
class AlertRule:
    """Alert rule definition."""
    
    def __init__(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        severity: str,  # "info", "warning", "critical"
        channels: List[str],  # ["telegram", "email", "slack"]
        cooldown_seconds: int = 300,  # 5 minutes default
    ):
        self.name = name
        self.condition = condition
        self.severity = severity
        self.channels = channels
        self.cooldown_seconds = cooldown_seconds
        self._last_triggered = 0.0
```

### Common Alert Rules

#### Kill Switch Alert

```python
def check_kill_switch_alert(metrics: Dict[str, Any]) -> bool:
    """Check if kill switch is active."""
    kill_switch = metrics.get("kill_switch", {})
    return kill_switch.get("active", False)
```

#### Circuit Breaker Alert

```python
def check_circuit_breaker_alert(metrics: Dict[str, Any]) -> bool:
    """Check if Kalshi circuit breaker is open."""
    kalshi_circuit = metrics.get("kalshi_circuit", {})
    return kalshi_circuit.get("open", False)
```

#### Agent Grid Not Ready Alert

```python
def check_agent_grid_alert(metrics: Dict[str, Any]) -> bool:
    """Check if agent grid is not ready."""
    agent_grid = metrics.get("agent_grid", {})
    return not agent_grid.get("startup_complete", False)
```

#### High CPU Alert

```python
def check_high_cpu_alert(metrics: Dict[str, Any]) -> bool:
    """Check if CPU usage is high (> 90%)."""
    system_resources = metrics.get("system_resources", {})
    cpu_percent = system_resources.get("cpu_percent", 0)
    return cpu_percent > 90
```

#### High Memory Alert

```python
def check_high_memory_alert(metrics: Dict[str, Any]) -> bool:
    """Check if memory usage is high (> 90%)."""
    system_resources = metrics.get("system_resources", {})
    memory_percent = system_resources.get("memory_percent", 0)
    return memory_percent > 90
```

### Notification Channels

#### Telegram

```python
async def send_telegram_alert(message: str, severity: str) -> None:
    """Send alert via Telegram bot."""
    from interfaces.telegram import send_telegram_message
    
    chat_id = os.getenv("TELEGRAM_ALERT_CHAT_ID")
    if not chat_id:
        logger.warning("TELEGRAM_ALERT_CHAT_ID not set, skipping Telegram alert")
        return
    
    await send_telegram_message(chat_id, message)
```

#### Email

```python
async def send_email_alert(message: str, severity: str) -> None:
    """Send alert via email."""
    import smtplib
    from email.mime.text import MIMEText
    
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    alert_email = os.getenv("ALERT_EMAIL")
    
    if not all([smtp_server, smtp_username, smtp_password, alert_email]):
        logger.warning("SMTP credentials not set, skipping email alert")
        return
    
    msg = MIMEText(message)
    msg['Subject'] = f"MERID Alert [{severity.upper()}]"
    msg['From'] = smtp_username
    msg['To'] = alert_email
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
```

### Escalation Policies

Escalation policies define how alerts are escalated based on severity and duration.

```python
class EscalationPolicy:
    """Escalation policy for alerts."""
    
    def __init__(
        self,
        severity: str,
        initial_channels: List[str],
        escalation_channels: List[str],
        escalation_minutes: int = 15,
    ):
        self.severity = severity
        self.initial_channels = initial_channels
        self.escalation_channels = escalation_channels
        self.escalation_minutes = escalation_minutes
```

**Example Policies**:
- **Info**: Initial: telegram, Escalate: none
- **Warning**: Initial: telegram, Escalate: email (15 min)
- **Critical**: Initial: telegram + email, Escalate: phone call (5 min)

## Monitoring Dashboards

### Grafana Dashboards

The system includes Grafana dashboards for visual monitoring:

- **Merid 15m Pipeline Health**: Overall system health
- **Merid Kalshi Recon Gate**: Reconciliation gate status
- **Merid PnL Exposure**: Profit and loss tracking
- **API Performance**: API latency and error rates
- **Database Health**: Database connection and query performance

### Prometheus Metrics

Key metrics exported to Prometheus:

- **merid_ws_events_dropped_total**: Total WS events dropped due to backpressure
- **merid_ws_fills_dropped_total**: Total WS fill events dropped
- **merid_ws_forwarder_throughput**: WS forwarder throughput (events/sec)
- **merid_health_check_duration_seconds**: Health check duration
- **merid_agent_grid_ticks_total**: Total agent grid ticks
- **merid_agent_grid_errors_total**: Total agent grid errors
- **merid_order_submissions_total**: Total order submissions
- **merid_order_fills_total**: Total order fills
- **merid_position_pnl_cents**: Position PnL in cents

## Critical Fixes

### Fix 1: Validation Mode Skip (BUG-L13)

**Problem**: Health checks failed in validation mode when components were intentionally skipped.

**Solution**: Skip failure in VALIDATION_MODE for MeridLoop and AgentGrid since they are intentionally skipped during validation.

### Fix 2: Event Loop Lag Diagnostic

**Problem**: Event loop lag was treated as a critical failure, causing unnecessary health check failures.

**Solution**: Event loop lag is now reported in checks only, not as a critical failure. It's diagnostic, not a trading or probe block.

### Fix 3: Fills Ledger Circuit Breaker

**Problem**: Fills ledger circuit breaker was not monitored, leading to undetected data integrity issues.

**Solution**: Added fills ledger health check to monitor circuit breaker and DLQ status. Circuit breaker open is a critical failure.

## Monitoring Best Practices

### Health Check Frequency

- **K8s Liveness Probe**: Every 10 seconds
- **K8s Readiness Probe**: Every 30 seconds
- **Component Health Checks**: Every 60 seconds
- **System Resources Check**: Every 30 seconds

### Alert Thresholds

- **CPU**: Warning at 80%, Critical at 90%
- **Memory**: Warning at 80%, Critical at 90%
- **Disk**: Warning at 80%, Critical at 90%
- **Event Loop Lag**: Warning at 100ms, Critical at 500ms
- **Agent Grid Errors**: Warning at 5%, Critical at 10%

### Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: Normal operational events
- **WARNING**: Degraded performance or potential issues
- **ERROR**: Errors that don't prevent operation
- **CRITICAL**: Errors that prevent operation

## References

- **Core Health**: `core/health.py`
- **Health API**: `web/api/health.py`
- **WebSocket Health**: `web/api/websocket_health.py`
- **Agent Health**: `web/api/agents_health.py`
- **Alert Rules**: `notifications/alert_rules.py`
- **Alerting Utils**: `utils/alerting.py`

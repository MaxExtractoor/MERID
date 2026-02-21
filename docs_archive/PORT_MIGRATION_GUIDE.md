# MERID Port Migration Guide

## Overview

This guide provides step-by-step instructions for migrating MERID from a single-port architecture (8001) to a proper multi-port swarm architecture with service separation.

## Migration Strategy

**Approach**: Incremental migration with backward compatibility

**Timeline**: 4 weeks (can be compressed to 2 weeks if needed)

**Risk Level**: LOW - No breaking changes to core logic

---

## Current State (Before Migration)

```text
Port 8001 (EVERYTHING):
├── User UI
├── Agent communication
├── Admin endpoints
├── Metrics
└── WebSockets
```

**Problems**:

- No isolation between concerns
- Security risks (admin on public port)
- Cannot scale services independently
- UI downtime affects agent mesh

---

## Target State (After Migration)

```text
Port 3000 - User UI (Public)
├── Dashboard (unified.html)
├── Public API endpoints
├── User WebSockets
└── Auth-protected actions

Port 8080 - Agent Mesh (Localhost)
├── Agent ↔ Agent messages
├── Consensus coordination
├── Task handoffs
└── Internal event bus

Port 9090 - Ops/Admin (Localhost)
├── Agent lifecycle control
├── System configuration
├── Kill switches
└── Emergency controls

Port 9091 - Telemetry (Localhost)
├── Prometheus metrics
├── Health checks
├── Performance stats
└── Reflection system metrics

Port 8001 - Legacy (Temporary)
└── Backward compatibility during migration
```

---

## Phase 1: Foundation (Week 1)

### Step 1.1: Create Port Configuration

**File**: `config/ports.py` ✅ **DONE**

**Verify**:

```python
from config.ports import get_port, get_service_info

print(get_service_info())
# Should show all 5 services with ports and bindings
```

### Step 1.2: Create Agent Mesh Layer

**File**: `agents/mesh.py` ✅ **DONE**

**Verify**:

```python
from agents.mesh import get_agent_mesh

mesh = get_agent_mesh()
mesh.register_agent("test-agent", "analyst")
print(mesh.get_stats())
```

### Step 1.3: Split FastAPI Applications

**Create**:

- `web/user_app.py` - Port 3000
- `web/agent_app.py` - Port 8080
- `web/ops_app.py` - Port 9090
- `web/metrics_app.py` - Port 9091

**Template** (`web/user_app.py`):

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from config.ports import USER_UI_PORT, get_binding

# Import only user-facing routers
from web.api.dashboard_data import router as dashboard_router
from web.api.live_data import router as live_data_router
from web.api.intelligence import router as intelligence_router
# ... other public routers

app = FastAPI(title="MERID User Interface")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Templates
templates = Jinja2Templates(directory="web/templates")

# Include routers
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(live_data_router, prefix="/api/v1")
app.include_router(intelligence_router, prefix="/api/v1")

@app.get("/")
async def root():
    return templates.TemplateResponse("unified.html", {"request": {}})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=get_binding("user_ui"),
        port=USER_UI_PORT,
        log_level="info"
    )
```

**Template** (`web/agent_app.py`):

```python
from fastapi import FastAPI
from config.ports import AGENT_MESH_PORT, get_binding

# Import only agent mesh routers
from agents.mesh import get_agent_mesh

app = FastAPI(title="MERID Agent Mesh")

# Initialize mesh
mesh = get_agent_mesh()

@app.get("/mesh/status")
async def mesh_status():
    return mesh.get_stats()

@app.get("/mesh/agents")
async def list_agents():
    return mesh.get_all_agents()

# Add agent communication endpoints
# These should NEVER be exposed publicly

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=get_binding("agent_mesh"),  # 127.0.0.1 only
        port=AGENT_MESH_PORT,
        log_level="info"
    )
```

**Template** (`web/ops_app.py`):

```python
from fastapi import FastAPI, HTTPException
from config.ports import OPS_ADMIN_PORT, get_binding

# Import admin routers
from web.api.system_control import router as system_control_router
from web.api.ops import router as ops_router

app = FastAPI(title="MERID Operations")

app.include_router(system_control_router, prefix="/api/v1")
app.include_router(ops_router, prefix="/api/v1")

@app.post("/admin/shutdown")
async def emergency_shutdown():
    """Emergency system shutdown."""
    # Implement shutdown logic
    return {"status": "shutting_down"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=get_binding("ops_admin"),  # 127.0.0.1 only
        port=OPS_ADMIN_PORT,
        log_level="info"
    )
```

**Template** (`web/metrics_app.py`):

```python
from fastapi import FastAPI
from config.ports import TELEMETRY_PORT, get_binding
from agents.reflection.integration import get_reflection_system

app = FastAPI(title="MERID Telemetry")

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    # Format metrics in Prometheus format
    reflection_system = get_reflection_system()
    stats = reflection_system.get_system_stats()
    
    metrics = []
    metrics.append(f"merid_reflections_total {stats['core']['total_reflections']}")
    metrics.append(f"merid_validations_total {stats['validator']['total_validations']}")
    metrics.append(f"merid_agents_active {stats['core']['active_agents']}")
    
    return "\n".join(metrics)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=get_binding("telemetry"),  # 127.0.0.1 only
        port=TELEMETRY_PORT,
        log_level="info"
    )
```

### Step 1.4: Create Startup Script

**File**: `start_merid.py`

```python
"""
MERID Multi-Service Startup Script

Starts all MERID services on their designated ports.
"""

import subprocess
import sys
import time
from pathlib import Path

from config.ports import get_service_info
from utils.logger import get_logger

logger = get_logger("startup")

SERVICES = [
    {
        "name": "User UI",
        "module": "web.user_app",
        "port_key": "user_ui",
        "critical": True,
    },
    {
        "name": "Agent Mesh",
        "module": "web.agent_app",
        "port_key": "agent_mesh",
        "critical": True,
    },
    {
        "name": "Ops Admin",
        "module": "web.ops_app",
        "port_key": "ops_admin",
        "critical": False,
    },
    {
        "name": "Telemetry",
        "module": "web.metrics_app",
        "port_key": "telemetry",
        "critical": False,
    },
]


def start_service(service: dict) -> subprocess.Popen:
    """Start a service."""
    logger.info("Starting %s...", service["name"])
    
    cmd = [
        sys.executable,
        "-m",
        service["module"],
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    return process


def main():
    """Start all MERID services."""
    logger.info("Starting MERID multi-service architecture...")
    
    # Show port configuration
    service_info = get_service_info()
    logger.info("Port configuration:")
    for name, info in service_info.items():
        logger.info("  %s: %s (public: %s)", name, info["url"], info["public"])
    
    # Start services
    processes = []
    
    for service in SERVICES:
        try:
            process = start_service(service)
            processes.append((service, process))
            time.sleep(1)  # Stagger startup
        except Exception as e:
            logger.error("Failed to start %s: %s", service["name"], e)
            if service["critical"]:
                logger.error("Critical service failed, aborting")
                sys.exit(1)
    
    logger.info("All services started successfully")
    logger.info("User UI: http://localhost:3000")
    logger.info("Press Ctrl+C to stop all services")
    
    # Wait for interrupt
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down services...")
        for service, process in processes:
            logger.info("Stopping %s...", service["name"])
            process.terminate()
            process.wait(timeout=5)
        logger.info("All services stopped")


if __name__ == "__main__":
    main()
```

---

## Phase 2: Router Migration (Week 2)

### Step 2.1: Categorize Existing Routers

**User-Facing** (move to `user_app.py`):

- `dashboard_data`
- `live_data`
- `intelligence`
- `predictions`
- `dashboard_ws`
- `wallet`
- `notifications`

**Agent Mesh** (move to `agent_app.py`):

- `reflection` (agent queries only)
- `agents` (agent registration/status)
- Internal consensus endpoints

**Ops/Admin** (move to `ops_app.py`):

- `system_control`
- `ops`
- `backup`
- `recovery`
- `monitoring`
- `ratelimit`

**Telemetry** (move to `metrics_app.py`):

- Health checks
- Metrics export
- Performance stats

### Step 2.2: Update Router Imports

**Example** - Update `web/api/reflection.py`:

```python
# Add service designation
SERVICE = "agent_mesh"  # This router belongs to agent mesh

# Existing router code...
```

### Step 2.3: Update Frontend API Calls

**File**: `web/static/js/unified-master.js`

```javascript
// Old (single port)
const API_BASE = 'http://127.0.0.1:8001';

// New (service-aware)
const API_ENDPOINTS = {
    user: 'http://127.0.0.1:3000',      // User-facing APIs
    agent: 'http://127.0.0.1:8080',     // Agent mesh (not used by UI)
    ops: 'http://127.0.0.1:9090',       // Ops (admin only)
    metrics: 'http://127.0.0.1:9091',   // Telemetry
};

// UI should ONLY call user endpoint
const API_BASE = API_ENDPOINTS.user;
```

---

## Phase 3: Agent Integration (Week 3)

### Step 3.1: Update BaseAgent to Use Mesh

**File**: `agents/base_agent.py`

```python
from agents.mesh import get_agent_mesh, MessageType

class BaseAgent:
    def __init__(self, agent_id: str, role: str):
        self.agent_id = agent_id
        self.role = role
        
        # Register with mesh
        mesh = get_agent_mesh()
        mesh.register_agent(agent_id, role)
        
        # Register message handlers
        mesh.register_handler(
            agent_id,
            MessageType.SIGNAL,
            self._handle_signal
        )
        mesh.register_handler(
            agent_id,
            MessageType.TASK_HANDOFF,
            self._handle_task_handoff
        )
    
    def _handle_signal(self, message):
        """Handle incoming signal."""
        signal = message.payload.get("signal")
        # Process signal
    
    def _handle_task_handoff(self, message):
        """Handle task handoff."""
        task = message.payload.get("task")
        # Process task
```

### Step 3.2: Update Consensus to Use Mesh

**File**: `core/consensus_engine.py`

```python
from agents.mesh import get_agent_mesh, MessageType

def request_votes(energy_id: str, agents: List[str]):
    """Request votes from agents via mesh."""
    mesh = get_agent_mesh()
    
    for agent_id in agents:
        mesh.send_message(
            from_agent="consensus_engine",
            to_agent=agent_id,
            message_type=MessageType.CONSENSUS_VOTE,
            payload={"energy_id": energy_id, "action": "vote"}
        )
```

---

## Phase 4: Testing & Validation (Week 4)

### Test 1: Port Isolation

```bash
# Start all services
python start_merid.py

# Verify ports are listening
netstat -an | grep "3000\|8080\|9090\|9091"

# Test public access (should work)
curl http://localhost:3000/

# Test agent mesh from outside (should fail)
curl http://localhost:8080/mesh/status
# Expected: Connection refused (127.0.0.1 only)
```

### Test 2: UI Independence

```bash
# Kill user UI
kill $(lsof -t -i:3000)

# Verify agent mesh still works
curl http://localhost:8080/mesh/status

# Verify agents can still communicate
# Check logs for agent messages
```

### Test 3: Agent Communication

```python
from agents.mesh import get_agent_mesh

mesh = get_agent_mesh()

# Register test agents
mesh.register_agent("agent-1", "analyst")
mesh.register_agent("agent-2", "risk")

# Send message
mesh.send_signal("agent-1", "agent-2", "test_signal", {"data": "test"})

# Check stats
print(mesh.get_stats())
# Should show 2 agents, 1 message sent
```

### Test 4: Load Test

```bash
# Install locust
pip install locust

# Create load test
# File: tests/load_test.py
from locust import HttpUser, task

class MERIDUser(HttpUser):
    @task
    def dashboard(self):
        self.client.get("http://localhost:3000/")
    
    @task
    def live_data(self):
        self.client.get("http://localhost:3000/api/v1/live/prices")

# Run load test
locust -f tests/load_test.py --host=http://localhost:3000
```

---

## Rollback Plan

If migration fails, rollback is simple:

1. **Stop new services**:

   ```bash
   pkill -f "user_app|agent_app|ops_app|metrics_app"
   ```

2. **Restart legacy service**:

   ```bash
   python -m web.main  # Old single-port app
   ```

3. **No data loss** - All data is in same database/files

---

## Success Criteria

- ✅ All 4 services start successfully
- ✅ User UI accessible on port 3000
- ✅ Agent mesh isolated on 127.0.0.1:8080
- ✅ Ops admin isolated on 127.0.0.1:9090
- ✅ Telemetry exportable on 127.0.0.1:9091
- ✅ UI downtime does not affect agent mesh
- ✅ Agent communication uses mesh, not UI
- ✅ No performance degradation
- ✅ All tests pass

---

## Post-Migration Cleanup

After 2 weeks of stable operation:

1. **Remove legacy port 8001**
2. **Delete old `web/main.py`** (if fully replaced)
3. **Update all documentation**
4. **Remove backward compatibility code**

---

## Monitoring

Add to `web/metrics_app.py`:

```python
@app.get("/metrics/ports")
async def port_status():
    """Check status of all ports."""
    import socket
    
    ports = {
        "user_ui": 3000,
        "agent_mesh": 8080,
        "ops_admin": 9090,
        "telemetry": 9091,
    }
    
    status = {}
    for name, port in ports.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        status[name] = "listening" if result == 0 else "down"
        sock.close()
    
    return status
```

---

## FAQ

**Q: Can I run all services on one port during development?**
A: Yes, keep legacy port 8001 running alongside new ports during migration.

**Q: What if I need to expose agent mesh for debugging?**
A: Use SSH tunnel: `ssh -L 8080:localhost:8080 user@server`

**Q: How do I monitor all services?**
A: Use `http://localhost:9091/health` for aggregated health check.

**Q: Can I deploy services on different machines?**
A: Yes, but agent mesh should stay on same machine as agents for low latency.

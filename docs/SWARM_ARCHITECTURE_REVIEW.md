# MERID Swarm Architecture Review

## Executive Summary

**Status**: ⚠️ **Partially Compliant** - Good foundation, needs port separation and anti-pattern cleanup

**Critical Issues**:

1. Single port (8001) for all traffic - no separation between user UI, agent mesh, and ops
2. UI-coupled architecture in some areas
3. Missing explicit agent communication layer
4. No resource manager for swarm scaling

**Strengths**:

1. ✅ True multi-agent swarm (10+ agents)
2. ✅ Parallel execution via async/event bus
3. ✅ No single point of failure (consensus-based)
4. ✅ Reflection system enables learning/adaptation

---

## Swarm Intelligence Compliance Check

### ✅ Multiple Autonomous Agents

**Current Agents** (from `agents/` directory):

- `analyst_gemma`, `analyst_llama` - Market analysis
- `archivist` - Historical pattern tracking
- `base_agent` - Shared reasoning primitive
- `meta_agent` - Meta-audit and trust scoring
- `news_monitor_agent` - News ingestion and filtering
- `risk` - Risk assessment
- `skeptic` - Adversarial validation
- `strategy_agent` - Strategy generation
- `synthesizer` - Consensus synthesis
- Plus streaming variants in `agents/streaming/`

**Verdict**: ✅ **TRUE SWARM** - 10+ specialized agents operating in parallel

### ✅ No Fixed Agent Count

**Evidence**:

- Agents are instantiated dynamically
- Event bus allows N agents to subscribe
- Consensus engine accepts variable vote counts
- No hardcoded agent array sizes

**Verdict**: ✅ **SCALABLE** - Can add/remove agents without structural rewrites

### ⚠️ Parallel Execution

**Current State**:

- ✅ Async agent processing via `BaseAgent.process()`
- ✅ Event bus for decoupled communication
- ✅ Consensus engine aggregates votes in parallel
- ⚠️ Some sequential bottlenecks in orchestrator

**Verdict**: ⚠️ **MOSTLY PARALLEL** - Good async foundation, some optimization needed

### ✅ Robustness & Redundancy

**Current State**:

- ✅ Consensus requires 2/3 quorum (no single agent failure halts system)
- ✅ Risk agent has VETO power (safety redundancy)
- ✅ Skeptic can trigger re-rounds
- ✅ Reflection system tracks and learns from failures

**Verdict**: ✅ **ROBUST** - Failure of individual agents does not halt system

---

## Critical Architecture Issue: Port Separation

### Current State (WRONG)

```text
Port 8001:
├── User UI (unified.html)
├── Agent API calls
├── WebSocket streams
├── Admin endpoints
├── Internal agent mesh (implicit)
└── Metrics/monitoring
```

**Problems**:

1. **No isolation** - User traffic can DoS agent communication
2. **Security risk** - Admin endpoints exposed on same port as public UI
3. **Coupling** - UI changes can break agent mesh
4. **Observability** - Can't monitor agent traffic separately
5. **Scaling** - Can't scale UI independently from agent mesh

### Required Architecture (CORRECT)

```text
Port 3000 - User UI
├── Dashboard (unified.html)
├── Public API endpoints
├── WebSocket for UI updates
└── Auth-protected user actions

Port 8080 - Agent Mesh (Internal Only)
├── Agent ↔ Agent messages
├── Consensus signals
├── Event bus subscriptions
├── Task handoffs
└── NO UI DEPENDENCY

Port 9090 - Ops/Admin (Localhost/VPN Only)
├── Agent start/stop
├── Scale agent count
├── Kill switches
├── Configuration updates
└── System control

Port 9091 - Telemetry (Metrics Export)
├── Prometheus metrics
├── Health checks
├── Performance stats
├── Reflection system stats
└── UI consumes summaries, not raw streams
```

---

## Anti-Patterns Found

### 🚫 Anti-Pattern 1: UI as Message Bus

**Location**: `web/api/dashboard_ws.py`, `web/static/js/unified-master.js`

**Problem**: WebSocket connections used for agent coordination

**Fix**:

- Agent mesh should use internal event bus
- UI WebSocket should only receive **summaries** for display
- Never route agent ↔ agent messages through UI layer

### 🚫 Anti-Pattern 2: Tight Coupling

**Location**: Multiple API endpoints in `web/api/`

**Problem**: Agents query UI state, UI depends on agent internals

**Fix**:

- Agents should never import from `web/`
- UI should consume agent state via read-only API
- Use event bus for agent → UI updates, not direct calls

### 🚫 Anti-Pattern 3: No Explicit Agent Communication Layer

**Location**: Missing dedicated module

**Problem**: Agent communication is implicit via event bus, no formal protocol

**Fix**: Create `agents/mesh.py`:

```python
class AgentMesh:
    """Dedicated agent-to-agent communication layer."""
    
    def send_signal(self, from_agent: str, to_agent: str, signal: dict)
    def broadcast(self, from_agent: str, message: dict)
    def request_consensus(self, proposal: dict) -> ConsensusResult
    def handoff_task(self, from_agent: str, to_agent: str, task: dict)
```

### 🚫 Anti-Pattern 4: Missing Resource Manager

**Location**: No centralized resource management

**Problem**: No explicit handling of:

- Agent scaling based on load
- Rate limit distribution across agents
- Compute allocation
- Memory management per agent

**Fix**: Create `swarm/resource_manager.py`:

```python
class ResourceManager:
    """Manages swarm resources and scaling."""
    
    def scale_agents(self, agent_type: str, target_count: int)
    def allocate_rate_limits(self, limits: dict) -> dict
    def monitor_compute_usage(self) -> dict
    def enforce_memory_limits(self)
```

---

## Reflection System v2.0 Review

### ✅ Swarm-Compliant Design

**Strengths**:

1. ✅ **Decentralized** - Each agent has independent reflection tracking
2. ✅ **Parallel** - Analytics/learning calculated per-agent in parallel
3. ✅ **No SPOF** - Reflection system failure doesn't halt agents
4. ✅ **Scalable** - Supports unlimited agents with caching

**Compliance**: ✅ **EXCELLENT** - Reflection system is swarm-native

### ⚠️ Minor Issues

1. **Persistence bottleneck**: Single JSON file for all agents
   - **Fix**: Shard by agent_id: `logs/reflections/{agent_id}.json`

2. **No distributed reflection**: Can't share learnings across swarm instances
   - **Fix**: Add `ReflectionSync` layer for multi-node deployments

---

## Recommended Port Map (Immediate Action)

### Phase 1: Split Ports (This Week)

```python
# config/ports.py
PORTS = {
    "user_ui": 3000,           # Public dashboard
    "agent_mesh": 8080,        # Internal agent communication
    "ops_admin": 9090,         # Localhost-only admin
    "telemetry": 9091,         # Metrics export
}

# Firewall rules
FIREWALL = {
    3000: "0.0.0.0",           # Public
    8080: "127.0.0.1",         # Localhost only
    9090: "127.0.0.1",         # Localhost only
    9091: "127.0.0.1",         # Localhost only (Prometheus scrapes)
}
```

### Phase 2: Service Separation (Next Sprint)

```
services/
├── user_ui/          # Port 3000 - FastAPI app for UI
├── agent_mesh/       # Port 8080 - Agent communication service
├── ops_admin/        # Port 9090 - System control service
└── telemetry/        # Port 9091 - Metrics aggregation
```

---

## UI-to-Swarm Contract

### Rule 1: One-Way Dependency

```
UI → Swarm (read-only queries)
Swarm → UI (event-driven updates)
Swarm ↔ Swarm (internal mesh)
```

**Never**: `Swarm → UI → Swarm`

### Rule 2: UI Observes, Does Not Control

**UI Can**:

- Display agent status
- Show consensus results
- Render performance metrics
- Expose user actions (submit energy, configure)

**UI Cannot**:

- Route agent messages
- Store agent state
- Coordinate consensus
- Manage agent lifecycle

### Rule 3: Swarm Continues Without UI

**Test**: Kill port 3000, swarm should:

- ✅ Continue processing energies
- ✅ Reach consensus
- ✅ Execute trades
- ✅ Update reflection system
- ✅ Log all activity

**Only loss**: Human visibility

---

## Practical Implementation Plan

### Week 1: Port Separation

1. **Create port config**

   ```python
   # config/ports.py
   USER_UI_PORT = 3000
   AGENT_MESH_PORT = 8080
   OPS_ADMIN_PORT = 9090
   TELEMETRY_PORT = 9091
   ```

2. **Split FastAPI apps**

   ```python
   # web/user_app.py - Port 3000
   # web/agent_app.py - Port 8080
   # web/ops_app.py - Port 9090
   # web/metrics_app.py - Port 9091
   ```

3. **Update API routers**
   - Move public endpoints to `user_app`
   - Move agent mesh to `agent_app`
   - Move admin to `ops_app`

### Week 2: Agent Mesh Layer

1. **Create `agents/mesh.py`**
   - Formal agent communication protocol
   - Message routing
   - Consensus coordination

2. **Refactor event bus**
   - Separate user events from agent events
   - Add mesh-specific channels

3. **Update agents**
   - Use mesh for agent ↔ agent communication
   - Use event bus for agent → UI updates

### Week 3: Resource Manager

1. **Create `swarm/resource_manager.py`**
   - Agent scaling logic
   - Rate limit distribution
   - Compute monitoring

2. **Integrate with orchestrator**
   - Dynamic agent spawning
   - Load-based scaling

### Week 4: Testing & Validation

1. **Kill-switch tests**
   - UI down, swarm continues
   - Single agent down, consensus still works
   - Network partition handling

2. **Load tests**
   - 100 concurrent energies
   - 20+ agents in parallel
   - Measure latency per layer

---

## Success Metrics

### Swarm Health

- ✅ **Agent count scales** without code changes
- ✅ **Consensus latency** < 500ms for 10 agents
- ✅ **Failure recovery** < 2 seconds
- ✅ **UI downtime** does not halt swarm

### Port Isolation

- ✅ **Agent mesh** never touches port 3000
- ✅ **User traffic** never touches port 8080
- ✅ **Admin endpoints** only on localhost
- ✅ **Metrics** exportable to Prometheus

### Resource Efficiency

- ✅ **Memory per agent** < 100MB
- ✅ **Agent spawn time** < 1 second
- ✅ **Rate limits** distributed fairly
- ✅ **Compute usage** monitored per agent

---

## Verdict

**Current State**: 7/10 swarm compliance

**Blockers**:

1. Port separation (critical)
2. Agent mesh layer (high priority)
3. Resource manager (medium priority)

**Timeline**: 4 weeks to full compliance

**Risk**: Low - incremental changes, no rewrites needed

**Recommendation**: **PROCEED** with port split immediately, defer resource manager to sprint 2.

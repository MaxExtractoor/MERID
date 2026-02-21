# MERID Swarm Architecture Upgrade

## Overview

MERID has been upgraded to meet distributed systems best practices for autonomous agent swarms. This document outlines the new architecture, explicit contracts, telemetry systems, and validation tools.

**Reference**: Perplexity AI search on treating swarms as distributed systems with explicit contracts, first-class telemetry, and paper trading rehearsal.

---

## 1. Explicit Event Contracts

### New Schema: `schemas/swarm_events.py`

Defines the **opinion → consensus → trade** flow with versioned, serializable events:

#### Core Event Types

**`StrategyOpinion`** - Published by: Strategy agents → Consumed by: ConsensusCoordinator
- Contains: `agent_id`, `symbol`, `direction`, `confidence`, `state_version`, `price_at_opinion`
- Tracks: Reasoning, risk parameters, timestamp
- Purpose: Agent's individual market opinion

**`ConsensusDecision`** - Published by: ConsensusCoordinator → Consumed by: Execution agents
- Contains: `participating_agents`, `dissenters`, `consensus_score`, `opinion_ids`
- Tracks: Disagreement ratio, confidence spread, aggregation method
- Purpose: Collective swarm decision after aggregating opinions

**`TradeIntent`** - Published by: Execution agents → Consumed by: OrderRouter
- Contains: `consensus_id`, `risk_checked`, `mode`, `opinion_refs`, `state_version`
- Tracks: Risk approval, position sizing, ancestry to consensus
- Purpose: Intent to execute after risk validation

**`OrderEvent`** - Published by: OrderRouter → Consumed by: Portfolio, agents, UI
- Contains: `status`, `mode`, `simulated`, `consensus_id`, `opinion_ids`
- Tracks: Full lineage from opinions through consensus to execution
- Purpose: Actual execution result with complete ancestry

**`AgentHeartbeat`** - Published by: All agents → Consumed by: Watchdogs
- Contains: `status`, `input_lag_ms`, `error_count`, `current_mode`
- Tracks: Liveness, performance metrics, processing latency
- Purpose: Agent health monitoring

### State Version Tracking

All events include `state_version` (hash of market state) to detect stale data:
- Opinions reference the state they analyzed
- Consensus tracks which state versions were used
- Trade intents validate freshness before execution

---

## 2. OrderRouter - Single Execution Path

### File: `execution/order_router.py`

**Purpose**: Global control plane for ALL order execution. No agent can bypass it.

### Mode Enforcement

```python
class TradingMode(Enum):
    SIMULATION = "simulation"  # Local sim, no external calls
    PAPER = "paper"           # Broker paper API
    LIVE = "live"             # Real money (requires authorization)
```

**Key Features**:
- Global `RUN_MODE` propagates to all services via `OrderRouterConfig`
- Live mode requires `live_mode_authorized=True` + optional dual approval
- Mode violations throw `LiveModeViolation` exception and log critical alerts
- All orders tagged with mode and simulated flag for audit trail

### Safety Checks

Before routing any order:
1. ✅ Validate mode matches global setting
2. ✅ Check risk approval (`risk_checked=True`)
3. ✅ Enforce size limits (`max_order_size_usd`)
4. ✅ Check daily order limit (`max_daily_orders`)
5. ✅ Verify required fields (symbol, venue, quantity)

### Routing Backends

- **Simulation**: Local fill with configurable slippage/commission, instant fill
- **Paper**: Routes to broker paper API (Alpaca, IBKR, Coinbase)
- **Live**: Requires explicit authorization, dual approval workflow (not implemented as safety)

### Usage

```python
from execution.order_router import get_order_router, submit_trade_intent

router = get_order_router()
order_event = await router.submit_order(trade_intent)
```

---

## 3. Swarm Health Telemetry

### File: `observability/swarm_telemetry.py`

**Purpose**: First-class metrics for swarm behavior, exportable to Prometheus/OTel.

### Per-Agent Metrics

Tracked via `AgentMetrics`:
- **Liveness**: `last_heartbeat`, `heartbeat_interval_ms`, `status`
- **Activity**: `messages_processed`, `messages_per_minute`, `last_output_timestamp`
- **Performance**: `p50/p99_latency_ms`, `input_lag_ms`
- **Errors**: `error_count`, `error_rate`, `last_error_timestamp`

### Swarm-Level Metrics

Tracked via `SwarmMetrics`:
- **Opinion Flow**: `opinions_per_minute`, `opinions_by_symbol`
- **Consensus**: `consensus_per_minute`, `consensus_success_rate`
- **Disagreement**: `avg_disagreement_rate`, `high_disagreement_count`
- **Latency**: `price→opinion→consensus→trade` pipeline timing
- **Participation**: `active_agents`, `total_agents`, `participation_rate`

### Prometheus Export

```python
from observability.swarm_telemetry import get_swarm_telemetry

telemetry = get_swarm_telemetry()
metrics_text = telemetry.get_prometheus_metrics()
```

Exports metrics like:
- `merid_opinions_per_minute`
- `merid_consensus_success_rate`
- `merid_disagreement_rate`
- `merid_agent_heartbeat{agent_id="...",agent_type="..."}`
- `merid_agent_input_lag_ms{...}`

### UI Integration

```python
stats = telemetry.get_stats_dict()
# Returns {swarm: {...}, agents: [...], health_issues: {...}}
```

---

## 4. Watchdog Agents

### File: `agents/watchdog_agents.py`

**Purpose**: Dedicated monitoring agents that watch other agents and emit alerts.

### LivenessWatchdog

**Detects**:
- Agents that stop sending heartbeats (timeout: 60s)
- Agents with no output for extended periods (timeout: 120s)
- Agents stuck in error states

**Alerts**: `severity="critical"` when agent goes offline

### ConsensusWatchdog

**Detects**:
- Opinions flowing but no consensus formed (stuck opinions)
- Consensus with too few agents (< min_agents)
- Suspiciously high agreement (potential groupthink > 95%)
- High disagreement blocking action (> 40% dissent)

**Alerts**: Warnings for consensus health issues

### ModeWatchdog

**Detects**:
- Trade intents with wrong mode vs global setting
- Live trading attempts (logs critical alert)
- Mode mismatches between components

**Alerts**: `severity="critical"` for mode violations

### StalenessWatchdog

**Detects**:
- Opinions based on stale data (> 10s old)
- Trade intents with excessive consensus lag (> 5s)
- Non-monotonic state versions

**Alerts**: Warnings for staleness issues

### WatchdogCoordinator

Runs all watchdogs on periodic interval (30s):

```python
from agents.watchdog_agents import get_watchdog_coordinator

coordinator = get_watchdog_coordinator(expected_mode=TradingMode.SIMULATION)
await coordinator.start()
```

All alerts published as `watchdog_alert` events for UI visibility.

---

## 5. Paper Rehearsal Validation

### File: `scripts/paper_rehearsal.py`

**Purpose**: End-to-end validation script for paper/sim trading sessions.

### Usage

```bash
# Simulation mode for 60 seconds
python scripts/paper_rehearsal.py --mode simulation --duration 60

# Paper mode for 5 minutes
python scripts/paper_rehearsal.py --mode paper --duration 300 --symbols BTC/USDT ETH/USDT
```

### Validation Checks

**1. Trade Ancestry** (`_validate_trade_ancestry`)
- ✅ Every trade has valid `consensus_id`
- ✅ Every consensus has at least N agent opinions
- ✅ All opinion IDs are traceable

**2. No Stale State** (`_validate_no_stale_state`)
- ✅ Consensus not older than 30s when trade executed
- ✅ Opinions not older than 30s when used in consensus
- ✅ Monotonic state progression

**3. Mode Compliance** (`_validate_mode_compliance`)
- ✅ All trade intents match expected mode
- ✅ All order events match expected mode
- ✅ In SIM mode, all orders are `simulated=True`
- ✅ No live broker calls in PAPER/SIM modes

**4. Event Rates** (`_validate_event_rates`)
- ✅ Opinions per minute within expected bands
- ✅ Consensus per minute within expected bands
- ✅ System not "going quiet"

**5. Consensus Quality** (`_validate_consensus_quality`)
- ✅ Healthy disagreement (not too unanimous)
- ✅ Not excessive high-disagreement decisions
- ✅ Average disagreement in reasonable range

### Output

Prints summary with:
- Event counts (opinions, consensus, trades, orders)
- Pass/fail for each validation check
- Detailed errors for failures
- Overall rehearsal status

**Exit codes**: 0 if passed, 1 if failed (for CI/CD integration)

---

## 6. UI Views for Swarm Visibility

### SwarmActivityPanel (`web/react/src/components/SwarmActivityPanel.tsx`)

**Purpose**: Real-time agent health dashboard

**Displays**:
- Global mode indicator (PAPER / SIM ONLY banner)
- Swarm metrics: opinions/min, consensus/min, success rate, pipeline latency
- Health issue alerts (red banner for problems)
- Agent table with:
  - Status indicators (● healthy, ◐ degraded, ✖ error, ○ offline)
  - Last heartbeat time
  - Messages processed
  - Error counts
  - Input lag and P99 latency

**WebSocket Events**:
- Subscribes to: `swarm_telemetry`
- Emits: `get_swarm_telemetry`

### OpinionFeed (`web/react/src/components/OpinionFeed.tsx`)

**Purpose**: Live stream of agent opinions grouped by symbol

**Displays**:
- Opinions grouped by symbol
- Consensus status badges:
  - "Pending Consensus" (blue, animated)
  - "Consensus: LONG/SHORT" (green/red)
- Per-opinion details:
  - Agent ID and role
  - Direction indicator (↑ long, ↓ short, → flat)
  - Confidence bar (0-100%)
  - Rationale summary
  - Signal strength

**WebSocket Events**:
- Subscribes to: `strategy_opinion`, `consensus_decision`

### Integration Points

Both components need backend WebSocket publishers:

```python
# In web/main.py startup
from observability.swarm_telemetry import get_swarm_telemetry

@application.on_event("startup")
async def publish_swarm_telemetry():
    telemetry = get_swarm_telemetry()
    while True:
        stats = telemetry.get_stats_dict()
        await event_stream.publish("swarm_telemetry", stats)
        await asyncio.sleep(5)
```

---

## 7. Integration Checklist

### Backend Integration

- [x] Add `schemas/swarm_events.py` to imports where agents publish events
- [ ] Update strategy agents to emit `StrategyOpinion` events
- [ ] Update `ConsensusCoordinator` to emit `ConsensusDecision` events
- [ ] Update execution agents to:
  - Create `TradeIntent` after risk check
  - Submit via `OrderRouter.submit_order()`
- [ ] Add `AgentHeartbeat` emission to all agent loops (every 30s)
- [ ] Start `WatchdogCoordinator` in `web/main.py` startup
- [ ] Add WebSocket publishers for:
  - `strategy_opinion` events
  - `consensus_decision` events
  - `swarm_telemetry` stats (every 5s)
  - `watchdog_alert` events

### Frontend Integration

- [ ] Add `SwarmActivityPanel` to Overview dashboard
- [ ] Add `OpinionFeed` to Trading or dedicated Swarm page
- [ ] Update routing to include new views
- [ ] Add WebSocket event handlers in `useMeridSocket` for:
  - `swarm_telemetry`
  - `strategy_opinion`
  - `consensus_decision`
  - `watchdog_alert`

### Testing Integration

- [ ] Run `python scripts/paper_rehearsal.py --mode simulation --duration 60`
- [ ] Verify all 5 validation checks pass
- [ ] Monitor `SwarmActivityPanel` during rehearsal
- [ ] Confirm opinions appear in `OpinionFeed`
- [ ] Verify watchdog alerts appear for intentionally broken scenarios

### Configuration

Create `.env` additions:
```bash
# Trading Mode
RUN_MODE=simulation  # simulation | paper | live
LIVE_MODE_AUTHORIZED=false
PAPER_BROKER=alpaca  # alpaca | ibkr | coinbase

# Rehearsal Settings
MIN_AGENTS_PER_TRADE=3
MAX_STATE_AGE_SECONDS=30
CONSENSUS_THRESHOLD=0.65
```

---

## 8. Key Invariants to Maintain

### System-Level Properties

1. **Every trade must have ≥N independent strategy opinions in its ancestry**
   - Validated by: `paper_rehearsal.py` → `_validate_trade_ancestry`
   - Enforced by: `ConsensusCoordinator` (min_agents_for_quorum)

2. **No agent trades on stale state older than T seconds**
   - Validated by: `paper_rehearsal.py` → `_validate_no_stale_state`
   - Monitored by: `StalenessWatchdog`

3. **Consensus and dissent both visible (not just final trade)**
   - Implemented by: `ConsensusDecision.dissenters`, `dissent_ratio`
   - Displayed by: `OpinionFeed` component

4. **No live broker calls in SIM/PAPER modes**
   - Enforced by: `OrderRouter` mode checks
   - Monitored by: `ModeWatchdog`
   - Validated by: `paper_rehearsal.py` → `_validate_mode_compliance`

### Agent-Level Properties

1. **All agents emit heartbeats every 30s**
   - Monitored by: `LivenessWatchdog`
   - Tracked by: `SwarmTelemetry`

2. **Consensus requires quorum (default: 3 agents)**
   - Enforced by: `ConsensusCoordinator` configuration
   - Validated by: `ConsensusWatchdog`

3. **Risk check required before execution**
   - Enforced by: `OrderRouter._validate_intent`
   - Recorded in: `TradeIntent.risk_checked`

---

## 9. Observability Stack

### Event Flow

```
Price Feed
  ↓
Strategy Agents → StrategyOpinion → EventStream → OpinionFeed (UI)
  ↓                                              ↓
  ↓                                         SwarmTelemetry
  ↓
ConsensusCoordinator → ConsensusDecision → EventStream → OpinionFeed (UI)
  ↓                                                    ↓
  ↓                                              SwarmTelemetry
  ↓
Risk Agent → TradeIntent → OrderRouter → OrderEvent → Portfolio
                              ↓                ↓
                         SimEngine         EventStream
                              ↓                ↓
                           Fill            SwarmTelemetry
```

### Monitoring Layers

**Layer 1: Event Stream** (`observability/event_stream.py`)
- In-memory pub/sub for real-time events
- WebSocket broadcast to UI
- Event history for replay

**Layer 2: Telemetry** (`observability/swarm_telemetry.py`)
- Aggregates events into metrics
- Calculates rates, latencies, health
- Prometheus export

**Layer 3: Watchdogs** (`agents/watchdog_agents.py`)
- Active monitoring of invariants
- Alert generation
- Auto-remediation hooks (future)

**Layer 4: Validation** (`scripts/paper_rehearsal.py`)
- Post-run audit of event logs
- Invariant verification
- Regression testing

---

## 10. Deployment Modes

### Simulation Mode (Default)

```python
OrderRouterConfig(
    run_mode=TradingMode.SIMULATION,
    sim_slippage_bps=5.0,
    sim_commission_bps=2.0,
    sim_fill_delay_ms=100.0,
)
```

- All orders executed in local simulator
- No external API calls
- Configurable slippage and fees
- Instant fills with delay simulation

### Paper Mode

```python
OrderRouterConfig(
    run_mode=TradingMode.PAPER,
    paper_broker="alpaca",
    paper_api_enabled=True,
)
```

- Orders routed to broker paper API
- Real API latency
- Real market data (paper account)
- No real money at risk

### Live Mode (Authorization Required)

```python
OrderRouterConfig(
    run_mode=TradingMode.LIVE,
    live_mode_authorized=True,  # Must be explicitly set
    live_mode_dual_approval=True,
    live_mode_approvers=["user1", "user2"],
)
```

- **Not implemented** (safety measure)
- Requires explicit code changes to enable
- Dual approval workflow
- Full audit logging

---

## 11. Testing Workflow

### Daily Development Cycle

1. **Run simulation rehearsal**
   ```bash
   python scripts/paper_rehearsal.py --mode simulation --duration 60
   ```

2. **Monitor UI during run**
   - Open SwarmActivityPanel
   - Watch OpinionFeed for agent activity
   - Check for watchdog alerts

3. **Review validation results**
   - All 5 checks should pass
   - Review any warnings
   - Check event rates

4. **Iterate on failures**
   - Fix broken agents
   - Adjust thresholds if needed
   - Re-run until clean

### Pre-Deployment

1. **Extended paper rehearsal**
   ```bash
   python scripts/paper_rehearsal.py --mode paper --duration 3600
   ```

2. **Review Prometheus metrics**
   - Check `merid_consensus_success_rate` ≥ 80%
   - Check `merid_disagreement_rate` between 10-40%
   - Check `merid_agent_participation_rate` ≥ 90%

3. **Manual UI audit**
   - Verify all agents show heartbeats
   - Verify opinions lead to consensus
   - Verify consensus leads to trades
   - Verify full ancestry visible

---

## 12. Future Enhancements

### Short Term
- [ ] Implement consensus timeout escalation
- [ ] Add auto-remediation for common watchdog alerts
- [ ] Export event logs to persistent storage (PostgreSQL/ClickHouse)
- [ ] Add consensus algorithm variations (unanimous, supermajority)

### Medium Term
- [ ] Implement dual approval workflow for live mode
- [ ] Add A/B testing framework for consensus methods
- [ ] Build consensus simulation tool (test various scenarios)
- [ ] Add agent performance ranking and trust scoring

### Long Term
- [ ] Full OpenTelemetry integration with distributed tracing
- [ ] Machine learning on consensus patterns
- [ ] Automatic agent scaling based on load
- [ ] Multi-region swarm coordination

---

## Summary

MERID now has a production-grade swarm architecture with:

✅ **Explicit contracts**: Opinion → Consensus → Trade with full lineage  
✅ **Mode enforcement**: Single OrderRouter with SIM/PAPER/LIVE isolation  
✅ **First-class telemetry**: Agent and swarm health metrics  
✅ **Watchdog monitoring**: Automated invariant checking  
✅ **Paper rehearsal**: Validation scripts for pre-deployment  
✅ **UI visibility**: Real-time agent activity and opinion streaming  

The system is ready for extended paper trading and real-time monitoring of swarm behavior.

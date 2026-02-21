# MERID Swarm Readiness Checklist

**Checklist Version**: 1.0.0  
**Last Updated**: 2026-02-06

**Purpose**: Pre-deployment validation that the swarm is properly wired and autonomous.

Use this checklist before:
- Switching from SIMULATION to PAPER mode
- Deploying to production
- Running extended paper trading sessions
- After major agent updates

**Version History**:
- 1.0.0 (2026-02-06): Initial checklist with version tracking, graceful degradation tests, log capture

---

## 🔌 Phase 1: Agent Wiring

**Goal**: All agents use explicit contracts and proper event flow.

### Strategy Agents
- [ ] All strategy agents emit `StrategyOpinion` events (not direct orders)
- [ ] Opinion events include: `agent_id`, `symbol`, `direction`, `confidence`, `state_version`
- [ ] Opinion events include `price_at_opinion` for staleness detection
- [ ] Opinion events include `rationale_summary` for UI display
- [ ] No strategy agent calls broker APIs directly
- [ ] No strategy agent creates orders directly

**Validation**:
```bash
# Search for direct order creation in strategy agents
grep -r "create_order\|submit_order\|place_order" agents/*strategy*.py
# Should return ZERO results (only OrderRouter should have these)

# Verify StrategyOpinion emission
grep -r "StrategyOpinion" agents/*strategy*.py
# Should show opinion creation and publishing
```

### Consensus Coordinator
- [ ] Subscribes to `strategy_opinion` events on event bus
- [ ] Groups opinions by symbol and time window
- [ ] Emits `ConsensusDecision` events with quorum logic
- [ ] Populates `participating_agents`, `dissenters`, `dissent_ratio`
- [ ] Includes `opinion_ids` list for ancestry tracking
- [ ] Enforces `min_agents_for_quorum` (default: 3)
- [ ] Calculates `consensus_score` using trust-weighted votes

**Validation**:
```python
# In consensus_coordinator.py, verify event emission
from observability.event_stream import publish_event
# Should see: await publish_event("consensus_decision", decision.to_dict())
```

### Execution Agents
- [ ] Subscribe to `consensus_decision` events
- [ ] Create `TradeIntent` after risk validation
- [ ] Call `OrderRouter.submit_order()` as ONLY execution path
- [ ] Include `consensus_id` in every TradeIntent
- [ ] Include `opinion_refs` (opinion_ids from consensus)
- [ ] Set `risk_checked=True` after risk agent approval
- [ ] No direct broker API calls

**Validation**:
```bash
# Search for direct broker calls in execution agents
grep -r "exchange\|broker\|ccxt\|alpaca\|ibkr" agents/*execution*.py
# Should only show imports, not actual trading calls

# Verify OrderRouter usage
grep -r "OrderRouter\|submit_order" agents/*execution*.py
# Should show router import and submit_order calls
```

### All Agents
- [ ] Every agent emits `AgentHeartbeat` every 30 seconds
- [ ] Heartbeat includes: `status`, `messages_processed`, `error_count`, `input_lag_ms`
- [ ] Heartbeat includes `current_mode` (simulation/paper/live)
- [ ] Agent main loops handle graceful shutdown
- [ ] Agents log to structured logger (not print statements)

**Validation**:
```bash
# Search for heartbeat emission
grep -r "AgentHeartbeat" agents/*.py
# Should appear in all agent files
```

### Graceful Degradation Test
- [ ] **Kill one strategy agent mid-session** and verify:
  - [ ] LivenessWatchdog fires within 60 seconds
  - [ ] Agent participation rate dips but stays > 60%
  - [ ] Consensus still forms with (N-1) agents
  - [ ] System recovers when agent restarts
  - [ ] No cascading failures or deadlocks

**Validation**:
```bash
# During rehearsal, in separate terminal:
# 1. Find a strategy agent process
ps aux | grep strategy_agent

# 2. Kill it mid-run
kill -9 <PID>

# 3. Check logs for watchdog alert
tail -f logs/merid.log | grep "liveness.*offline"

# 4. Verify consensus still forming
curl http://localhost:8000/api/v1/swarm/stats | jq '.swarm.consensus_per_minute'
# Should be > 0 even with one agent down

# 5. Restart agent and verify recovery
# Participation should return to 100%
```

---

## 🎛️ Phase 2: Infrastructure Setup

**Goal**: Watchdogs, telemetry, and monitoring are active.

### OrderRouter Configuration
- [ ] `OrderRouter` initialized with correct `RUN_MODE`
- [ ] `RUN_MODE` set to `SIMULATION` for dev/testing
- [ ] `live_mode_authorized=False` (unless explicitly going live)
- [ ] `max_order_size_usd` set to reasonable limit
- [ ] `max_daily_orders` set to prevent runaway trading
- [ ] Router logs mode at startup

**Validation**:
```bash
# Check startup logs for:
"OrderRouter initialized in SIMULATION mode (live_authorized=False)"
```

### Watchdog Coordinator
- [ ] `WatchdogCoordinator` started in `web/main.py` startup
- [ ] Expected mode matches global `RUN_MODE`
- [ ] Check interval set (default: 30s)
- [ ] Watchdog alerts published to event stream
- [ ] UI handlers registered for `watchdog_alert` events

**Validation**:
```bash
# Check startup logs for:
"WatchdogCoordinator initialized (mode=simulation)"
"WatchdogCoordinator started"
```

### Swarm Telemetry
- [ ] `SwarmTelemetry` singleton created
- [ ] WebSocket publisher for `swarm_telemetry` started
- [ ] Publishes stats every 5 seconds
- [ ] Prometheus endpoint exposed at `/metrics`
- [ ] UI handlers registered for telemetry updates

**Validation**:
```bash
# Test Prometheus endpoint
curl http://localhost:8000/metrics | grep merid_

# Should see metrics like:
# merid_opinions_per_minute
# merid_consensus_per_minute
# merid_agent_participation_rate
```

### Event Stream Publishers
- [ ] WebSocket publisher for `strategy_opinion` events
- [ ] WebSocket publisher for `consensus_decision` events
- [ ] WebSocket publisher for `trade_intent` events
- [ ] WebSocket publisher for `order_event` events
- [ ] All publishers started in FastAPI startup

**Validation**:
```bash
# Check WebSocket connections in browser dev tools
# Should see events streaming in Network tab
```

---

## 🖥️ Phase 3: UI Integration

**Goal**: Swarm behavior is observable in real-time.

### SwarmActivityPanel
- [ ] Component added to Overview dashboard
- [ ] Subscribes to `swarm_telemetry` WebSocket events
- [ ] Shows mode indicator (PAPER / SIM ONLY banner)
- [ ] Displays swarm metrics (opinions/min, consensus/min)
- [ ] Shows agent table with heartbeat times
- [ ] Alerts appear for health issues

**Validation**:
```bash
# Open http://localhost:5173
# Navigate to Overview
# Verify SwarmActivityPanel is visible and updating
```

### OpinionFeed
- [ ] Component added to Trading or Swarm page
- [ ] Subscribes to `strategy_opinion` events
- [ ] Subscribes to `consensus_decision` events
- [ ] Groups opinions by symbol
- [ ] Shows "Pending Consensus" badge
- [ ] Shows "Consensus: LONG/SHORT" badge when formed

**Validation**:
```bash
# Open OpinionFeed view
# Trigger strategy agents
# Verify opinions appear within 5 seconds
# Verify consensus badge appears after quorum reached
```

### Ancestry Traversal
- [ ] Can click any order and see its TradeIntent
- [ ] Can click TradeIntent and see its ConsensusDecision
- [ ] Can click ConsensusDecision and see all StrategyOpinions
- [ ] Timestamps show progression (opinion → consensus → trade)
- [ ] All state_versions are within freshness threshold

**Validation**:
```bash
# Manual test:
# 1. Execute a paper trade
# 2. Click order in UI
# 3. Traverse back through consensus to opinions
# 4. Verify all links work and timestamps make sense
```

---

## 🧪 Phase 4: Paper Rehearsal

**Goal**: All invariants pass in automated validation.

### Run Rehearsal Script
```bash
python scripts/paper_rehearsal.py --mode simulation --duration 60
```

### Log Capture
- [ ] Event logs automatically persisted for each rehearsal
- [ ] Logs include: timestamp, checklist version, run duration, mode
- [ ] Raw opinion/consensus/trade events saved for forensics
- [ ] Logs stored in time-stamped files or database table

**Validation**:
```bash
# Check log files are being created
ls -ltr logs/rehearsal_*.jsonl
# Should see new file for each run

# Verify log contents include checklist version
head -1 logs/rehearsal_20260206_010530.jsonl | jq '.checklist_version'
# Should return: "1.0.0"

# Query events from log
cat logs/rehearsal_20260206_010530.jsonl | jq 'select(.event_type == "strategy_opinion") | .payload.symbol' | sort | uniq
# Should list all symbols that had opinions
```

**Log Format** (JSONL):
```json
{"timestamp": 1738806330.5, "checklist_version": "1.0.0", "event_type": "rehearsal_start", "mode": "simulation", "duration": 60}
{"timestamp": 1738806331.2, "event_type": "strategy_opinion", "payload": {...}}
{"timestamp": 1738806332.8, "event_type": "consensus_decision", "payload": {...}}
{"timestamp": 1738806390.5, "event_type": "rehearsal_end", "validation_results": {...}}
```

### Check 1: Trade Ancestry
- [ ] ✅ Every trade has valid consensus_id
- [ ] ✅ Every consensus has ≥3 agent opinions
- [ ] ✅ All opinion IDs are traceable
- [ ] ✅ No orphaned trades (trades without consensus)

**Expected Output**:
```
[✓ PASS] trade_ancestry: All X trades have valid ancestry
```

### Check 2: No Stale State
- [ ] ✅ No consensus older than 30s when trade executed
- [ ] ✅ No opinions older than 30s when used in consensus
- [ ] ✅ State versions are monotonic (no regression)

**Expected Output**:
```
[✓ PASS] no_stale_state: No stale state detected in decision chain
```

### Check 3: Mode Compliance
- [ ] ✅ All trade intents match expected mode
- [ ] ✅ All order events match expected mode
- [ ] ✅ In SIM mode, all orders have simulated=True
- [ ] ✅ No live broker calls detected

**Expected Output**:
```
[✓ PASS] mode_compliance: All events comply with simulation mode
```

### Check 4: Event Rates
- [ ] ✅ Opinions per minute ≥ 50% of expected
- [ ] ✅ Consensus per minute ≥ 50% of expected
- [ ] ✅ System not "going quiet" (event flow continuous)

**Expected Output**:
```
[✓ PASS] event_rates: Event rates within expected bands
```

### Check 5: Consensus Quality
- [ ] ✅ Average disagreement is healthy (10-40%)
- [ ] ✅ Not too many unanimous decisions (< 80%)
- [ ] ✅ Not too much high disagreement (< 30% of decisions)

**Expected Output**:
```
[✓ PASS] consensus_quality: Consensus quality healthy
```

### Overall Result
- [ ] ✅ Exit code 0 (all checks passed)
- [ ] ✅ No validation errors in output
- [ ] ✅ Event counts reasonable for duration

**Expected Output**:
```
Overall: 5/5 checks passed
✓ REHEARSAL PASSED - System ready for extended testing
```

---

## 📊 Phase 5: Live Monitoring

**Goal**: Swarm is behaving correctly during operation.

### During Paper Trading Session

**SwarmActivityPanel Checks** (every 5 minutes):
- [ ] Active agents ≥ 90% of total agents
- [ ] No critical watchdog alerts (red banners)
- [ ] Pipeline latency < 5000ms average
- [ ] Opinions per minute > 5
- [ ] Consensus success rate > 60%

**OpinionFeed Checks** (spot check):
- [ ] Opinions appearing for multiple symbols
- [ ] Multiple agents contributing per symbol
- [ ] Consensus forming within 60 seconds of first opinion
- [ ] Direction indicators match actual market moves

**Prometheus Metrics** (if available):
```bash
# Check key metrics
curl -s http://localhost:8000/metrics | grep merid_ | grep -E "(participation|consensus_success|disagreement)"

# Should see:
merid_agent_participation_rate > 0.9
merid_consensus_success_rate > 0.6
merid_disagreement_rate between 0.1 and 0.4
```

### Watchdog Alert Monitoring
- [ ] No liveness alerts (offline agents)
- [ ] No mode violation alerts
- [ ] No staleness alerts (agents trading on old data)
- [ ] Consensus stuck alerts resolve within 120s

**Action on Alert**:
1. Check SwarmActivityPanel for affected agent
2. Review agent logs for errors
3. If critical, stop trading and investigate
4. Document issue in incident log

---

## 🚨 Pre-Deployment Gate

**BEFORE switching from SIMULATION to PAPER mode:**

### Required Passing Criteria
- [ ] ✅ All Phase 1 checkboxes complete (agents wired)
- [ ] ✅ All Phase 2 checkboxes complete (infrastructure)
- [ ] ✅ All Phase 3 checkboxes complete (UI visible)
- [ ] ✅ Paper rehearsal (60s) passes all 5 checks
- [ ] ✅ Extended rehearsal (30min) shows no watchdog alerts
- [ ] ✅ Manual ancestry traversal works for 5 random orders
- [ ] ✅ Code review: No direct broker calls in agent code
- [ ] ✅ Config review: RUN_MODE=paper, live_authorized=false

### Recommended Additional Validation
- [ ] Run rehearsal with --duration 3600 (1 hour)
- [ ] Monitor Prometheus dashboards for full hour
- [ ] Review event logs for anomalies
- [ ] Test failure scenarios (kill agent, inject bad data)
- [ ] Verify graceful degradation (consensus still forms with N-1 agents)

### Prometheus Metrics Continuity
- [ ] Metrics have no missing time ranges during extended rehearsal
- [ ] All agent heartbeat metrics present continuously
- [ ] No gaps in `merid_opinions_per_minute` time series
- [ ] No gaps in `merid_consensus_per_minute` time series
- [ ] Scrape interval matches expected cadence (default: 15s)

**Validation**:
```bash
# Check for time gaps in metrics (requires Prometheus running)
# Query for missing data points in last hour
curl -s 'http://localhost:9090/api/v1/query_range?query=merid_agent_participation_rate&start=2026-02-06T00:00:00Z&end=2026-02-06T01:00:00Z&step=15s' | jq '.data.result[0].values | length'
# Should return 240 (3600s / 15s) with no gaps

# Check for exporters dying (any agent that stopped reporting)
curl -s 'http://localhost:9090/api/v1/query?query=up{job="merid"}' | jq '.data.result[] | select(.value[1] == "0")'
# Should return empty (all exporters up)
```

**Common gap causes**:
- Agent crashed and didn't restart
- Network partition between agent and Prometheus
- Prometheus scraper overload
- Memory pressure killing exporters

### Sign-Off
```
Validated by: _________________
Date: _________________
Checklist version: 1.0.0
Rehearsal duration: _______ seconds
All checks: PASS / FAIL
Graceful degradation test: PASS / FAIL
Prometheus continuity: PASS / FAIL
Notes: _________________________________________________
```

---

## 🔄 Daily Dev Workflow

Make this part of every development cycle:

### Morning Ritual
1. Pull latest code
2. Run `python scripts/paper_rehearsal.py --mode simulation --duration 60`
3. Check exit code (should be 0)
4. Review any warnings in output
5. If failed: Fix before writing new code

### Before Commit
1. Run rehearsal again
2. Verify all 5 checks still pass
3. Check no new watchdog alert types
4. **REQUIRED**: If adding new agent or major change:
   - [ ] Add at least one new rehearsal assertion OR
   - [ ] Add at least one new watchdog rule
   - [ ] Document the new invariant in `scripts/paper_rehearsal.py`
   - [ ] Update checklist version if new checks added
   - [ ] Commit includes test coverage for new invariant

**Rationale**: Invariants must evolve with the swarm. New agents introduce new failure modes that need automated detection.

### Before Deploy
1. Run extended rehearsal (1 hour minimum)
2. Review Prometheus metrics
3. Complete full checklist
4. Get sign-off from second reviewer

---

## 🐛 Common Issues and Fixes

### Issue: "Trade ancestry validation failed"
**Symptom**: Trades have no consensus_id or missing opinion_ids
**Fix**: 
- Verify execution agents set `consensus_id` in TradeIntent
- Verify ConsensusCoordinator includes `opinion_ids` in ConsensusDecision
- Check event bus subscriptions are active

### Issue: "No stale state - violations detected"
**Symptom**: Timestamps show old data used in decisions
**Fix**:
- Reduce consensus window timeout
- Add timestamp validation in agent logic
- Verify system clocks are synchronized

### Issue: "Mode compliance failed"
**Symptom**: Orders have wrong mode or simulated flag
**Fix**:
- Check OrderRouter config matches global RUN_MODE
- Verify OrderRouter._route_to_simulator sets simulated=True
- Check no agents creating OrderEvent directly

### Issue: "Event rates - Low opinion rate"
**Symptom**: Fewer opinions than expected
**Fix**:
- Check strategy agents are running
- Verify agents receiving price feed
- Check for exceptions in agent loops
- Review heartbeat status in SwarmActivityPanel

### Issue: "Consensus quality - High unanimity"
**Symptom**: All agents always agree
**Fix**:
- Review agent strategy diversity
- Check for correlated data sources
- Verify agents have different parameters/horizons
- Consider adding contrarian agent

### Issue: "Watchdog alerts - Agent offline"
**Symptom**: Liveness alerts for specific agents
**Fix**:
- Check agent process is running
- Review agent logs for crashes
- Verify heartbeat emission in agent loop
- Check system resource limits (CPU/memory)

---

## 📝 Continuous Improvement

Track metrics over time to improve swarm quality:

### Weekly Review
- Average consensus success rate (target: > 70%)
- Average disagreement ratio (target: 20-30%)
- Number of watchdog alerts (target: < 5 per day)
- Pipeline latency P99 (target: < 3000ms)

### Monthly Review
- Agent participation trends (should stay > 90%)
- Most frequent watchdog alert types
- Rehearsal pass/fail rate in CI
- Production incidents related to swarm behavior

### Quarterly Goals
- Increase consensus success rate by 5%
- Reduce pipeline latency by 20%
- Achieve zero mode violations
- Add new consensus algorithms and A/B test

---

## ✅ Quick Reference

### Automated Validation (Recommended)

**Use the CLI tool for consolidated checks:**
```bash
# Standard check (60s rehearsal + infra checks)
python scripts/swarm_readiness.py

# Extended check (1h rehearsal, required for PAPER mode)
python scripts/swarm_readiness.py --extended

# Infrastructure only (skip rehearsal)
python scripts/swarm_readiness.py --skip-rehearsal
```

**Output**:
```
================================================================================
MERID SWARM READINESS VALIDATION
================================================================================

Checklist Version: 1.0.0
Mode: Standard (60s)
Timestamp: 2026-02-06 01:30:00

[1/5] Environment Check
  ✓ Python version
  ✓ .env file exists
  ✓ scripts/paper_rehearsal.py exists
  ✓ Required packages

[2/5] Mode & Config Check
  RUN_MODE: simulation
  LIVE_MODE_AUTHORIZED: false

[3/5] Paper Rehearsal Execution
  Running: python scripts/paper_rehearsal.py --mode simulation --duration 60
  Duration: 60s (1m)
  
  [... rehearsal output ...]

[4/5] Prometheus Metrics Continuity
  Metric: merid_agent_participation_rate
  Expected data points: 240
  Actual data points: 238
  Coverage: 99.2%
  ✓ OK

[5/5] Watchdog Status
  Active agents: 5/5
  Health issues: 0
  ✓ All watchdogs healthy

================================================================================
READINESS VALIDATION SUMMARY
================================================================================

Checklist Version: 1.0.0
Validation Duration: 68.3s

Results:
  [✓ PASS] environment: Environment check passed
  [✓ PASS] mode_config: Mode is simulation, OK
  [✓ PASS] paper_rehearsal: Rehearsal PASSED: 5/5 checks passed
  [✓ PASS] prometheus_metrics: Metrics coverage: 99.2%
  [✓ PASS] watchdog_status: 0 issues, 5/5 agents active

Overall: 5/5 checks passed

================================================================================
✓ SWARM READY FOR DEPLOYMENT
================================================================================

Results saved to: logs/swarm_readiness_20260206_013128.json
```

**Exit codes**:
- `0` = All checks passed (ready)
- `1` = One or more checks failed (not ready)

### Manual Validation

**Is the swarm ready?**
```bash
# 1. Run rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 60

# 2. Check exit code
echo $?  # Should be 0

# 3. Verify UI
open http://localhost:5173
# SwarmActivityPanel shows no red alerts
# OpinionFeed shows opinions flowing

# 4. Check mode
curl http://localhost:8000/api/v1/config/mode
# Should return: {"mode": "simulation", "live_authorized": false}
```

**Quick health check during operation:**
```bash
# Agent participation
curl -s http://localhost:8000/metrics | grep merid_agent_participation_rate

# Recent watchdog alerts
curl -s http://localhost:8000/api/v1/watchdog/alerts?limit=10

# Swarm stats
curl -s http://localhost:8000/api/v1/swarm/stats | jq
```

---

**Last Updated**: Run `paper_rehearsal.py` after any agent changes  
**Next Review**: Before switching to PAPER mode  
**Owner**: Dev team + autonomous dev swarm

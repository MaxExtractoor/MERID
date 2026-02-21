# MERID Production Readiness Roadmap

**Generated**: 2026-02-18  
**Status**: Pre-Production Assessment  
**Target**: Kalshi Live Trading System

---

## Executive Summary

MERID has **strong foundational infrastructure** in place:
- ✅ Kill switch framework (`merid/risk/kill_switches.py`)
- ✅ Execution router with guards (`merid/execution/router.py`)
- ✅ Kalshi executor (`merid/execution/executors/kalshi.py`)
- ✅ Orchestrator pipeline (`merid/agents/orchestrator.py`)
- ✅ Settings & configuration management (`merid/settings.py`, `merid/paper_config.py`)
- ✅ Main event loop (`merid/loop.py`)

**Critical Gaps**:
- ❌ Orchestrator workers not running (shows 6/7 active, 0 tasks)
- ❌ UI displaying stub data ($0.00 balances, 0 positions)
- ❌ Kill switch not wired to backend execution layer
- ❌ No evidence of live Kalshi auth flow working
- ❌ Agent pipeline producing no outputs

---

## 🎯 Critical Path: Production Readiness

### Phase 1: Backend Core (Week 1)

#### 1.1 Orchestrator Worker Activation
**Goal**: Get 7/7 agents running with active task throughput

**Files**:
- `merid/agents/orchestrator.py`
- `merid/loop.py`
- `merid/agents/base.py`

**Tasks**:
1. **Diagnose missing 7th agent**
   - File: `merid/agents/orchestrator.py:36-42`
   - Check `PHASE_ORDER` and `get_canonical_registry()`
   - Verify all 5 phases have registered agents
   - Log: Add startup diagnostics showing which agents are loaded

2. **Enable agent task generation**
   - File: `merid/loop.py:46-100`
   - Set `enable_execution=False` initially (paper mode)
   - Ensure `feature_refresh_interval`, `agent_cycle_interval` are active
   - Verify agents are producing outputs (theses, signals, proposals)

3. **Wire agent outputs to dashboard**
   - Backend endpoint: Create `/api/v1/operator/agent-activity`
   - Return: `{agent_id, task_count, last_seen, status, error_count}`
   - Source: `merid/agents/orchestrator.py` PhaseResult/CycleResult
   - Update UI: `OperatorActivityStream` component (already exists)

**Acceptance Criteria**:
- Dashboard shows 7/7 agents active
- Task count > 0 (e.g., 5-20 tasks/minute)
- Logs show agent outputs: theses, signals, proposals, verdicts

---

#### 1.2 Kalshi Live Path Integration
**Goal**: Complete auth → balances → positions → orders → fills

**Files**:
- `merid/execution/executors/kalshi.py`
- `merid/event_venues/kalshi/client.py`
- `merid/event_venues/kalshi/order_manager.py`
- `merid/settings.py:158-174`

**Tasks**:
1. **Fix Kalshi authentication**
   - File: `merid/execution/executors/kalshi.py:25-29`
   - Current: Uses `KALSHI_API_KEY_ID` (incorrect)
   - Fix: Use `KALSHI_API_KEY` + `KALSHI_PRIVATE_KEY_PATH`
   - Implement JWT signing with RSA private key
   - Reference: https://trading-api.readme.io/reference/authentication

2. **Test full order lifecycle**
   - File: `merid/execution/executors/kalshi.py:51-100`
   - Test sequence:
     ```python
     # 1. Auth
     await kalshi.authenticate()
     # 2. Get balance
     balance = await kalshi.get_balance()
     # 3. Get quote
     quote = await kalshi.get_quote("PRES.BIDEN-2024", "yes", 10)
     # 4. Place order (paper mode first)
     result = await kalshi.execute_trade(...)
     # 5. Check order status
     order = await kalshi.get_order(result.tx_id)
     # 6. Wait for fill
     # 7. Verify position updated
     ```
   - Add retry logic with exponential backoff
   - Add detailed logging at each step

3. **Wire to execution router**
   - File: `merid/execution/router.py:90-100`
   - Ensure `submit_trade()` calls Kalshi executor
   - Add guard checks before execution
   - Emit events for UI updates

**Acceptance Criteria**:
- Authentication succeeds with live Kalshi API
- Can fetch balance (non-zero for funded account)
- Can place paper/sim orders successfully
- Order lifecycle tracked end-to-end
- UI shows real balance, positions, orders

---

#### 1.3 Kill Switch Backend Integration
**Goal**: Make Kill Switch actually halt execution

**Files**:
- `merid/risk/kill_switches.py`
- `merid/execution/router.py`
- `backend/api/endpoints/operator.py` (create)

**Tasks**:
1. **Make kill switch authoritative**
   - File: `merid/execution/router.py:90-120`
   - Add check at start of `submit_trade()`:
     ```python
     from merid.risk.kill_switches import risk_controller
     
     async def submit_trade(self, ...):
         # HARD GATE: Check kill switch BEFORE any execution
         if not risk_controller.can_trade():
             reason = risk_controller.get_kill_reason()
             return TradeResult(
                 success=False,
                 error=f"Trading halted: {reason}",
                 ...
             )
     ```

2. **Expose kill switch state to API**
   - File: `backend/api/endpoints/operator.py` (create if doesn't exist)
   - Endpoint: `GET /api/v1/operator/kill-switch-status`
     ```python
     @router.get("/kill-switch-status")
     async def get_kill_switch_status():
         return {
             "global_kill": risk_controller._global_kill,
             "state": risk_controller.state(),
             "reason": risk_controller.get_kill_reason(),
             "daily_pnl": risk_controller._daily_pnl,
             "daily_loss_limit": risk_controller.daily_loss_limit,
             "can_trade": risk_controller.can_trade(),
         }
     ```
   - Endpoint: `POST /api/v1/operator/emergency-stop`
     ```python
     @router.post("/emergency-stop")
     async def emergency_stop(reason: str):
         risk_controller.emergency_stop(reason)
         return {"status": "halted", "reason": reason}
     ```
   - Endpoint: `POST /api/v1/operator/reset-kill-switch`

3. **Wire UI to backend kill switch**
   - File: `web/react/src/views/KillSwitchView.tsx`
   - Replace hardcoded state with API calls
   - Add confirmation modal for emergency stop
   - Show real daily P&L and limits

**Acceptance Criteria**:
- Kill switch blocks trades when triggered
- UI reflects real kill switch state
- Emergency stop button works
- Daily loss limit enforced
- Can reset kill switch after resolution

---

### Phase 2: Risk & Limits (Week 1-2)

#### 2.1 Risk State Object
**Goal**: Single authoritative risk state checked before every trade

**Files**:
- `merid/risk/kill_switches.py:62-150`
- `merid/pipeline/risk_manager.py`
- `merid/event_venues/kalshi/kalshi_risk.py`

**Tasks**:
1. **Enhance RiskController state**
   - File: `merid/risk/kill_switches.py:76-90`
   - Add real-time tracking:
     ```python
     @dataclass
     class RiskState:
         daily_pnl: float
         daily_loss_limit: float
         total_position_value: float
         max_position_value: float
         open_orders_count: int
         max_open_orders: int
         error_count_1h: int
         error_threshold: int
         per_market_notional: Dict[str, float]  # {ticker: notional}
         max_notional_per_market: float
         venue_health: Dict[str, str]  # {venue: status}
         last_updated: datetime
     ```

2. **Implement per-market notional caps**
   - File: `merid/event_venues/kalshi/kalshi_risk.py` (exists)
   - Check: `settings.MERID_PM_MAX_NOTIONAL_PER_MARKET` (default $500)
   - Enforce in: `risk_controller.check_trade_allowed(symbol, size, price)`

3. **Add error rate circuit breaker**
   - Track failed orders in rolling 1-hour window
   - Trip kill switch if error rate > threshold (e.g., 10 errors/hour)
   - Auto-reset after cooldown period

4. **Expose risk state to API**
   - Endpoint: `GET /api/v1/operator/risk-state`
   - Return full RiskState object
   - Poll every 5 seconds in UI

**Acceptance Criteria**:
- Risk state object updated in real-time
- Per-market notional limits enforced
- Error threshold trips circuit breaker
- UI displays live risk metrics
- All limits configurable via settings

---

#### 2.2 Backend Risk Checks
**Goal**: Multi-layer risk validation before execution

**Files**:
- `merid/execution/router.py:100-150`
- `trading/guards/trading_guard.py`

**Tasks**:
1. **Layer 1: Kill switch**
   - Already implemented in Phase 1.3

2. **Layer 2: Position limits**
   - Check: Total position value < `max_position_value`
   - Check: Per-market notional < `max_notional_per_market`

3. **Layer 3: Loss limits**
   - Check: Daily P&L > `-daily_loss_limit`
   - Check: Per-domain loss limits

4. **Layer 4: Order limits**
   - Check: Open orders count < `max_open_orders`
   - Check: Order size within venue limits

5. **Return structured risk decision**
   ```python
   @dataclass
   class RiskDecision:
       allowed: bool
       reason: Optional[str]
       violated_limits: List[str]
       risk_score: float
   ```

**Acceptance Criteria**:
- All 4 risk layers check before execution
- Trades blocked with clear reason if limits violated
- Risk decisions logged for audit
- UI shows which limit was hit

---

### Phase 3: Agent & Strategy Layer (Week 2)

#### 3.1 Agent Availability & State
**Goal**: Define agent lifecycle and persist state

**Files**:
- `merid/agents/base.py`
- `merid/agents/orchestrator.py`
- Database: Add `agent_status` table

**Tasks**:
1. **Define agent states**
   ```python
   class AgentState(str, Enum):
       DISABLED = "disabled"      # Admin disabled
       AVAILABLE = "available"    # Ready to run
       ACTIVE = "active"          # Currently executing
       FAILED = "failed"          # Crashed, needs attention
       MAINTENANCE = "maintenance" # Temporarily offline
   ```

2. **Persist agent metadata**
   - Table: `agent_status`
   - Columns: `agent_id`, `state`, `last_seen`, `tasks_1h`, `errors_1h`, `config`
   - Update: Every agent cycle completion

3. **Implement agent heartbeat**
   - File: `merid/agents/base.py`
   - Add: `CanonicalAgent.heartbeat()` method
   - Call: Every successful agent run
   - Timeout: Mark as FAILED if no heartbeat in 5 minutes

4. **Wire to dashboard**
   - Endpoint: `/api/v1/operator/agent-status`
   - Show: 7 agents with real state, tasks, errors

**Acceptance Criteria**:
- Agent states persisted to database
- Dashboard shows 7 agents with real status
- "6 of 7 agents active" reflects actual state
- Failed agents flagged for operator attention

---

#### 3.2 End-to-End Strategy Path
**Goal**: At least one working strategy from signal to order

**Files**:
- `merid/agents/` (various strategy agents)
- `merid/event_venues/kalshi/` (Kalshi-specific logic)
- `merid/loop.py`

**Tasks**:
1. **Pick reference strategy**
   - Candidate: Simple Kalshi momentum strategy
   - Input: Market price updates
   - Signal: Price movement > threshold
   - Output: Buy/sell proposal

2. **Implement signal generation**
   - File: `merid/agents/kalshi_momentum_agent.py` (create)
   - Fetch: Recent price history for market
   - Calculate: Price change over window
   - Emit: Signal if change > threshold

3. **Convert signal to trade proposal**
   - File: Same agent
   - Size: Based on conviction (e.g., 10-50 contracts)
   - Risk check: Within per-market notional limit
   - Output: `TradeProposal(symbol, side, size, confidence)`

4. **Risk evaluation**
   - File: `merid/agents/risk_agents.py`
   - Check: Proposal against all risk limits
   - Output: `RiskVerdict(approved, reason)`

5. **Execution**
   - File: `merid/execution/router.py`
   - Only execute if: `enable_execution=True` AND verdict approved
   - Mode: Start with paper/sim, promote to live after testing

**Acceptance Criteria**:
- One strategy generates 5-10 signals/hour
- Signals converted to proposals
- Risk agent evaluates proposals
- Orders placed in paper mode
- Full path logged and observable in UI

---

### Phase 4: UI Real State Wiring (Week 2-3)

#### 4.1 Balance & Portfolio Endpoints
**Goal**: Replace $0.00 with real data

**Files**:
- `backend/api/endpoints/kalshi.py` (verify exists)
- `web/react/src/views/OperatorDashboard.tsx`

**Tasks**:
1. **Balance endpoint**
   - Already exists: `/api/v1/kalshi/balance`
   - Verify: Returns `{usd: 123456}` (cents)
   - UI: Convert cents to dollars
   - Poll: Every 15 seconds

2. **Positions endpoint**
   - Already exists: `/api/v1/kalshi/positions`
   - Return: `{positions: [{ticker, side, quantity, pnl, ...}]}`
   - UI: Display in portfolio view
   - Poll: Every 15 seconds

3. **P&L endpoint**
   - Endpoint: `/api/v1/kalshi/pnl`
   - Return: `{day_pnl, total_pnl, realized, unrealized}`
   - UI: Show in dashboard metrics
   - Poll: Every 15 seconds

4. **Orders endpoint**
   - Already exists: `/api/v1/kalshi/orders`
   - Return: Recent orders with status
   - UI: Display in orders view
   - Poll: Every 5 seconds

**Acceptance Criteria**:
- Dashboard shows real balance (non-zero)
- Positions table populated
- P&L metrics update live
- Orders list shows recent activity
- No more "$0.00" placeholders

---

#### 4.2 System Health & Status
**Goal**: Replace "Operational" with real venue status

**Files**:
- `backend/api/endpoints/system.py`
- `merid/event_venues/kalshi/client.py`

**Tasks**:
1. **Kalshi venue health check**
   - File: `merid/event_venues/kalshi/client.py`
   - Method: `async def health_check() -> VenueHealth`
   - Check: `/health` or `/status` endpoint
   - Return: `{status: "operational" | "degraded" | "down", latency_ms, last_check}`

2. **System health endpoint**
   - Endpoint: `/api/v1/system/health`
   - Return:
     ```json
     {
       "venues": {
         "kalshi": {"status": "operational", "latency_ms": 45}
       },
       "orchestrator": {"active": true, "agents": 7, "tasks_1h": 156},
       "risk": {"kill_switch": false, "can_trade": true},
       "database": {"connected": true}
     }
     ```

3. **Wire to UI**
   - Component: System Health cards
   - Show: Real status instead of "Connected"
   - Alert: Red badge if any degraded

**Acceptance Criteria**:
- System health reflects real backend state
- Kalshi status checked every 60 seconds
- Degraded services flagged
- Orchestrator status shows agent count

---

### Phase 5: Operational Safety (Week 3)

#### 5.1 Configuration Management
**Goal**: Centralized, validated config with mode switching

**Files**:
- `merid/settings.py` (already comprehensive)
- `merid/paper_config.py`
- `.env`

**Tasks**:
1. **Validate required settings**
   - File: `merid/settings.py:23-31`
   - Add: `validate_production_config()` method
   - Check: All required API keys present
   - Check: Risk limits within safe ranges
   - Fail startup if invalid

2. **Mode switching UI**
   - Endpoint: `GET /api/v1/config/mode`
   - Endpoint: `POST /api/v1/config/mode` (with confirmation)
   - Modes: `sim`, `paper`, `live`
   - Require: Clean reconciliation before `paper→live`

3. **Config verification dashboard**
   - UI: Add "System Configuration" view
   - Show: Current mode, active venues, risk limits
   - Show: Which API keys are configured
   - Warning: If live mode enabled without safety checks

**Acceptance Criteria**:
- Config validated on startup
- Can switch modes via UI
- Live mode requires explicit confirmation
- Config view shows all critical settings

---

#### 5.2 Monitoring & Alerting
**Goal**: Know when things go wrong

**Files**:
- `backend/api/endpoints/logs.py`
- `merid/monitoring/` (create)
- `observability/event_stream.py` (exists)

**Tasks**:
1. **Component health tracking**
   - Track: Venue connections, agent cycles, order success rate
   - Alert: If any component fails 3x in 5 minutes

2. **Log streaming**
   - Endpoint: `/api/v1/logs/stream`
   - Filter: By component, severity
   - UI: Logs view with live tail

3. **Alert rules**
   - Rule 1: Kill switch triggered → email/telegram
   - Rule 2: Order error rate > 20% → alert
   - Rule 3: Agent crashed → alert
   - Rule 4: Venue disconnected > 2 min → alert

4. **Audit log**
   - Log: All trades, risk decisions, mode changes
   - Persist: To database for compliance
   - UI: View audit trail

**Acceptance Criteria**:
- Component health tracked
- Logs streamable in UI
- Alerts sent for critical events
- Audit trail complete

---

#### 5.3 Dry Run & Testing
**Goal**: Prove system works before live mode

**Files**:
- `tests/test_production_readiness.py` (create)
- `tests/test_kalshi_integration.py` (create)

**Tasks**:
1. **End-to-end integration test**
   ```python
   async def test_kalshi_paper_trading():
       # 1. Authenticate
       # 2. Fetch markets
       # 3. Generate signal
       # 4. Create proposal
       # 5. Risk check
       # 6. Execute paper trade
       # 7. Verify order placed
       # 8. Check P&L updated
   ```

2. **Risk limit test**
   ```python
   async def test_risk_limits_enforced():
       # Test daily loss limit
       # Test per-market notional
       # Test kill switch blocks trades
   ```

3. **Failure recovery test**
   ```python
   async def test_venue_disconnect_recovery():
       # Simulate Kalshi disconnect
       # Verify system handles gracefully
       # Verify reconnection works
   ```

4. **Production simulation**
   - Run: Full system in paper mode for 24 hours
   - Requirement: No unexpected errors
   - Requirement: Risk violations handled correctly
   - Requirement: All metrics updating

**Acceptance Criteria**:
- Integration tests pass
- Risk limit tests pass
- 24-hour paper run clean
- Ready for live promotion

---

## 📋 File-Level Action Items

### Backend Changes

| File | Action | Priority |
|------|--------|----------|
| `merid/agents/orchestrator.py` | Add startup diagnostics, verify 7 agents loaded | **P0** |
| `merid/loop.py` | Enable agent cycles, verify outputs | **P0** |
| `merid/execution/executors/kalshi.py` | Fix auth (JWT + RSA), test full order lifecycle | **P0** |
| `merid/execution/router.py` | Add kill switch check, wire risk controller | **P0** |
| `merid/risk/kill_switches.py` | Expose state via API, add per-market limits | **P0** |
| `backend/api/endpoints/operator.py` | Create kill switch & risk state endpoints | **P0** |
| `backend/api/endpoints/kalshi.py` | Verify balance/positions/orders endpoints | **P1** |
| `backend/api/endpoints/system.py` | Add system health endpoint | **P1** |
| `merid/agents/base.py` | Add agent state enum, heartbeat mechanism | **P1** |
| `merid/event_venues/kalshi/client.py` | Add health check method | **P1** |
| `merid/settings.py` | Add config validation method | **P2** |
| `tests/test_production_readiness.py` | Create comprehensive integration tests | **P2** |

### Frontend Changes

| File | Action | Priority |
|------|--------|----------|
| `web/react/src/views/OperatorDashboard.tsx` | Wire real balance/P&L data | **P0** |
| `web/react/src/views/KillSwitchView.tsx` | Connect to backend kill switch | **P0** |
| `web/react/src/components/OperatorActivityStream.tsx` | Show real agent tasks | **P0** |
| `web/react/src/views/KalshiPortfolioView.tsx` | Display real positions | **P1** |
| `web/react/src/views/Orders.tsx` | Poll real orders endpoint | **P1** |
| Add: `SystemConfigurationView.tsx` | New view for config/mode management | **P2** |

---

## 🎯 Success Metrics

### Pre-Production (Week 1-2)
- [ ] 7/7 agents active with >0 tasks
- [ ] Real balance displayed ($XXX.XX)
- [ ] Kill switch blocks trades when triggered
- [ ] At least 1 strategy generating signals
- [ ] Paper trades executing successfully

### Production Ready (Week 3)
- [ ] 24-hour paper run with zero unexpected errors
- [ ] All risk limits enforced
- [ ] Monitoring & alerts operational
- [ ] Audit trail complete
- [ ] Integration tests passing
- [ ] Operator confidence: System can be promoted to live

### Live Trading (Week 4+)
- [ ] Live mode enabled with small capital ($500-1000)
- [ ] First live trade executed successfully
- [ ] P&L tracking accurate
- [ ] Risk limits holding under live conditions
- [ ] No incidents requiring emergency stop

---

## 🚨 Red Flags & Blockers

| Issue | Impact | Resolution |
|-------|--------|------------|
| Kalshi auth failing | **BLOCKER** | Fix JWT signing in `kalshi.py`, verify keys | 
| Orchestrator producing 0 tasks | **CRITICAL** | Debug agent registration, enable cycles |
| Kill switch not blocking trades | **CRITICAL** | Wire to `ExecutionRouter.submit_trade()` |
| UI showing stub data | **HIGH** | Wire real endpoints, test polling |
| No agent heartbeats | **HIGH** | Add heartbeat mechanism |
| Missing error rate tracking | **MEDIUM** | Implement error circuit breaker |

---

## 📝 Next Steps

1. **Start with Phase 1.1** - Get agents running (highest ROI)
2. **Then Phase 1.2** - Fix Kalshi auth path
3. **Then Phase 1.3** - Wire kill switch
4. **Run integration tests** after each phase
5. **24-hour paper run** before any live promotion

**Estimated Timeline**: 3 weeks to production-ready (with focused effort)

---

## 🔗 Reference Documents

- [Kalshi API Docs](https://trading-api.readme.io/reference/authentication)
- [Trading System Checklist](https://www.monstertradingsystems.com/trading-system-checklist/)
- [Risk Management Best Practices](https://margex.com/en/blog/simple-trading-checklist-for-traders/)
- MERID Go-Live Checklist: `KALSHI_GO_LIVE_CHECKLIST.md`
- MERID Production Checklist: `PRODUCTION_READY_CHECKLIST.md`

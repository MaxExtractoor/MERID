# MERID Universal Agent Hardening — Deliverables

## 1. Per-Asset/Timeframe Coverage Table

### 1.1 Crypto Asset Universe

| Asset | 15m | 1h | Daily | Weekly | Monthly |
|-------|-----|-----|-------|--------|---------|
| **BTC** | KXBTC15M | KXBTC | KXBTCD1 | KXBTCW1 | KXBTC1M |
| **ETH** | KXETH15M | KXETH | KXETHD1 | KXETHW1 | KXETH1M |
| **SOL** | KXSOL15M | KXSOL | KXSOLD1 | KXSOLW1 | KXSOL1M |
| **XRP** | KXXRP15M | KXXRP | KXXRPD1 | KXXRPW1 | KXXRP1M |
| **DOGE**| KXDOGE15M | KXDOGE | KXDOGED1 | KXDOGEW1 | KXDOGE1M |

**Total Combinations**: 25 active market series (5 assets × 5 timeframes)

### 1.2 Agent Coverage Matrix

| Agent ID | Asset | Timeframe | Series Ticker | Governance | Watchdog | Drift-Aware |
|----------|-------|-----------|---------------|------------|----------|-------------|
| BTC_15M | BTC | 15m | KXBTC15M | ✅ | ✅ | ✅ |
| BTC_HOURLY | BTC | 1h | KXBTC | ✅ | ✅ | ✅ |
| BTC_DAILY | BTC | daily | KXBTCD1 | ✅ | ✅ | ✅ |
| BTC_WEEKLY | BTC | weekly | KXBTCW1 | ✅ | ✅ | ✅ |
| ETH_15M | ETH | 15m | KXETH15M | ✅ | ✅ | ✅ |
| ETH_HOURLY | ETH | 1h | KXETH | ✅ | ✅ | ✅ |
| ETH_DAILY | ETH | daily | KXETHD1 | ✅ | ✅ | ✅ |
| ETH_WEEKLY | ETH | weekly | KXETHW1 | ✅ | ✅ | ✅ |
| SOL_15M | SOL | 15m | KXSOL15M | ✅ | ✅ | ✅ |
| SOL_HOURLY | SOL | 1h | KXSOL | ✅ | ✅ | ✅ |
| SOL_DAILY | SOL | daily | KXSOLD1 | ✅ | ✅ | ✅ |
| SOL_WEEKLY | SOL | weekly | KXSOLW1 | ✅ | ✅ | ✅ |
| XRP_15M | XRP | 15m | KXXRP15M | ✅ | ✅ | ✅ |
| XRP_HOURLY | XRP | 1h | KXXRP | ✅ | ✅ | ✅ |
| XRP_DAILY | XRP | daily | KXXRPD1 | ✅ | ✅ | ✅ |
| XRP_WEEKLY | XRP | weekly | KXXRPW1 | ✅ | ✅ | ✅ |
| DOGE_15M | DOGE | 15m | KXDOGE15M | ✅ | ✅ | ✅ |
| DOGE_HOURLY | DOGE | 1h | KXDOGE | ✅ | ✅ | ✅ |
| DOGE_DAILY | DOGE | daily | KXDOGED1 | ✅ | ✅ | ✅ |
| DOGE_WEEKLY | DOGE | weekly | KXDOGEW1 | ✅ | ✅ | ✅ |

**Coverage Summary**:
- 20 directional agents (4 timeframes × 5 assets)
- 1 market maker (CRYPTO_15M_MM)
- 3 sentiment agents (contrarian, regime switch, vol breakout)
- **Total: 24 agents with full governance/watchdog coverage**

### 1.3 Timeframe Risk Parameters

| Timeframe | Entry Window (min) | Cutoff (min) | Max Position | Data Staleness Threshold |
|-----------|-------------------|--------------|--------------|-------------------------|
| 15m | 10 | 2 | 500 contracts | 60s |
| 1h | 30 | 2 | 500 contracts | 300s |
| Daily | 120 | 15 | 500 contracts | 900s |
| Weekly | 1440 | 60 | 500 contracts | 1800s |
| Monthly | 2880 | 120 | 500 contracts | 3600s |

---

## 2. Patched Wiring Graph

### 2.1 Before Hardening (Vulnerabilities)

```
┌─────────────────┐     direct callback      ┌──────────────────┐
│ drift_reward    │◄────────────────────────►│  governor_agent  │
│    _loop        │  (circular dependency)   │     (V1)         │
└────────┬────────┘                          └────────┬─────────┘
         │                                           │
         │    fire-and-forget                        │ async.ensure_future
         │    (no await/audit)                       │ (untracked)
         ▼                                           ▼
┌─────────────────┐                          ┌──────────────────┐
│  agent.pause()  │                          │   agent.stop()   │
│  (no timeout)   │                          │  (no timeout)    │
└─────────────────┘                          └──────────────────┘
         │                                           │
         └──────────────────┬────────────────────────┘
                            │
         ┌──────────────────▼──────────────────┐
         │    unified_decision_layer           │
         │  ┌─────────────────────────────┐    │
         │  │  aggregate()                │    │
         │  │    if len < MIN_QUORUM:     │    │
         │  │      return NO_ACTION  ◄─────┼────┼── SILENT FAILURE
         │  │      (no alert/audit)         │    │
         │  └─────────────────────────────┘    │
         └─────────────────────────────────────┘
                            │
         ┌──────────────────▼──────────────────┐
         │      assistant_api (V1)               │
         │  ┌─────────────────────────────┐    │
         │  │  _gather_system_snapshot()  │    │
         │  │    try: ...                 │    │
         │  │    except Exception:        │    │
         │  │      pass  ◄────────────────┼────┼── SWALLOWED ERRORS
         │  │  (no structured error)        │    │
         │  └─────────────────────────────┘    │
         │                                       │
         │  NO RATE LIMITING                     │
         │  NO TIMEOUTS                          │
         └───────────────────────────────────────┘
```

**Vulnerabilities Identified**:
1. **Circular callback**: drift_reward_loop ↔ governor_agent direct coupling
2. **Fire-and-forget**: async.ensure_future() without await/audit
3. **Silent quorum failure**: NO_ACTION without alerting or blocking
4. **Unvalidated MIN_QUORUM**: env var can disable consensus (set to 0)
5. **Swallowed errors**: try/except/pass patterns hide failures
6. **No rate limiting**: Assistant API vulnerable to DoS
7. **No per-asset watchdogs**: blind spots in coverage

### 2.2 After Hardening (V2)

```
┌─────────────────────────────────────────────────────────────────┐
│                     GOVERNANCE LAYER (V2)                       │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              GovernanceEventBus (pub/sub)                  │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐   │   │
│  │  │  drift_de   │    │  agent_     │    │  weight_    │   │   │
│  │  │   _risk     │    │   pause     │    │   change    │   │   │
│  │  └──────┬──────┘    └──────┬──────┘    └─────────────┘   │   │
│  │         │                  │                              │   │
│  │  ┌──────▼──────────────────▼──────────┐                  │   │
│  │  │   Immutable Audit Trail           │                  │   │
│  │  │   • event_id (uuid)               │                  │   │
│  │  │   • timestamp                     │                  │   │
│  │  │   • actor + target                │                  │   │
│  │  │   • reason + impact               │                  │   │
│  │  └───────────────────────────────────┘                  │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌─────────────────────────┐    ┌─────────────────────────────┐
│   drift_reward_loop     │    │   HardenedGovernorAgent     │
│   (publisher only)      │    │        (V2)                 │
│                         │    │  ┌─────────────────────┐    │
│  bus.publish(DRIFT_)    │    │  │ evaluate_and_act()  │    │
│    ━━► event_bus        │    │  │   ━━► request_quorum()│   │
│                         │    │  │         approval      │   │
└─────────────────────────┘    │  └──────────┬──────────┘   │
                               │             │               │
                               │             ▼               │
                               │  ┌─────────────────────┐    │
                               │  │ UnifiedDecisionLayer│    │
                               │  │                     │    │
                               │  │  ┌───────────────┐  │    │
                               │  │  │ Decision      │  │    │
                               │  │  │ Aggregator    │  │    │
                               │  │  │               │  │    │
                               │  │  │ MIN_QUORUM:   │  │    │
                               │  │  │ clamped to    │  │    │
                               │  │  │ [1, 5]        │  │    │
                               │  │  │               │  │    │
                               │  │  │ if insufficient│  │    │
                               │  │  │ agents:       │  │    │
                               │  │  │   QUORUM_     │  │    │
                               │  │  │   FAILED  ━━►─┼──┼────┼──► AlertManager
                               │  │  │   (critical)  │  │    │    (dedup + cooldown)
                               │  │  └───────────────┘  │    │
                               │  └─────────────────────┘    │
                               │             │               │
                               │             ▼               │
                               │  ┌─────────────────────┐     │
                               │  │ _execute_action()   │     │
                               │  │                     │     │
                               │  │ • await agent.      │     │
                               │  │   pause(timeout=10) │     │
                               │  │   (with timeout)    │     │
                               │  │                     │     │
                               │  │ • await agent.      │     │
                               │  │   stop(timeout=15)  │     │
                               │  │   (with timeout)    │     │
                               │  │                     │     │
                               │  │ • success/failure  │     │
                               │  │   → audit trail    │     │
                               │  └─────────────────────┘     │
                               └───────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    WATCHDOG LAYER (V2)                            │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │         AssetWatchdogCoordinator                          │   │
│  │  ┌─────────────────────────────────────────────────────┐  │   │
│  │  │  Per-Asset/Timeframe Checks (5 assets × 5 TF)       │  │   │
│  │  │                                                     │  │   │
│  │  │  • Data freshness (series-specific thresholds)     │  │   │
│  │  │  • Agent liveness per market                        │  │   │
│  │  │  • Execution success rate                         │  │   │
│  │  │  • Gross/net exposure per asset                   │  │   │
│  │  │  • Market availability                              │  │   │
│  │  │                                                     │  │   │
│  │  │  Health Status: healthy/degraded/critical         │  │   │
│  │  │              ━━► AlertManager                       │  │   │
│  │  └─────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  ASSISTANT API LAYER (V2)                       │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │           assistant_api_v2.py                             │   │
│  │                                                           │   │
│  │  ┌─────────────────┐  ┌─────────────────────────────────┐ │   │
│  │  │  Rate Limiting  │  │  Structured Error Handling    │ │   │
│  │  │                 │  │                                 │ │   │
│  │  │ • 30 req/min    │  │ GathererError with:           │ │   │
│  │  │ • per-client    │  │   - error_type                  │ │   │
│  │  │ • sliding window│  │   - message                     │ │   │
│  │  │                 │  │   - recovery_hint               │ │   │
│  │  │ 429 if exceeded │  │   - trace_id                    │ │   │
│  │  └─────────────────┘  └─────────────────────────────────┘ │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐  │   │
│  │  │        Read-Only Enforcement                        │  │   │
│  │  │  • GET endpoints only (no POST/PUT/DELETE)         │  │   │
│  │  │  • snapshot gathering only (no mutations)          │  │   │
│  │  │  • query timeout: 10s max                          │  │   │
│  │  └─────────────────────────────────────────────────────┘  │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐  │   │
│  │  │  Per-Asset/Timeframe Response Fields               │  │   │
│  │  │                                                     │  │   │
│  │  │  response.asset_health[BTC][15m] = {                │  │   │
│  │  │    total: 1, healthy: 1, paused: 0,                │  │   │
│  │  │    status: "healthy"                               │  │   │
│  │  │  }                                                 │  │   │
│  │  └─────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    ALERT MANAGER                                │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Central deduplication + cooldown                        │   │
│  │                                                         │   │
│  │  Channels: LOG | UI | TELEGRAM | WEBHOOK | AUDIT       │   │
│  │                                                         │   │
│  │  Cooldowns:                                            │   │
│  │    • info: 5min    • warning: 2min                     │   │
│  │    • high: 1min    • critical: 0 (no cooldown)         │   │
│  │                                                         │   │
│  │  Auto-escalation after 3 occurrences                   │   │
│  │                                                         │   │
│  │  Asset/timeframe-aware routing:                       │   │
│  │    alert_quorum_failure(affected_assets=[BTC], ...)    │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Key Architectural Changes

| Aspect | Before (V1) | After (V2) |
|--------|-------------|------------|
| **Governance Actions** | Direct callback (circular) | EventBus pub/sub |
| **Lifecycle Calls** | `asyncio.ensure_future()` | `await with timeout` |
| **Audit Trail** | Warning logs only | Immutable event records |
| **Quorum Failure** | Silent `NO_ACTION` | `QUORUM_FAILED` + alert |
| **MIN_QUORUM** | Raw env var | Clamped to [1, 5] |
| **Assistant API** | No rate limits, swallowed errors | 30 req/min, structured errors |
| **Watchdog** | Generic liveness checks | Per-asset/timeframe coverage |
| **Alerting** | Scattered logger calls | Central AlertManager with dedup |

---

## 3. Remediation Checklist

### 3.1 Governance Hardening

| # | Fix | File | Line | Status |
|---|-----|------|------|--------|
| 1 | Create GovernanceEventBus | `agents/governance_event_bus.py` | new | ✅ |
| 2 | Create HardenedGovernorAgent V2 | `agents/governor_agent_v2.py` | new | ✅ |
| 3 | Add awaited lifecycle calls with timeout | `agents/governor_agent_v2.py` | 165-190 | ✅ |
| 4 | Add complete audit trail | `agents/governance_event_bus.py` | 85-120 | ✅ |
| 5 | Route actions through UnifiedDecisionLayer | `agents/governor_agent_v2.py` | 130-155 | ✅ |
| 6 | Add per-asset/timeframe parsing | `agents/governor_agent_v2.py` | 285-315 | ✅ |

### 3.2 Quorum Hardening

| # | Fix | File | Line | Status |
|---|-----|------|------|--------|
| 7 | Create QuorumFailure exception | `agents/quorum_hardening.py` | 35-90 | ✅ |
| 8 | Create ValidatedQuorumConfig | `agents/quorum_hardening.py` | 93-155 | ✅ |
| 9 | Add MIN_QUORUM clamping | `agents/quorum_hardening.py` | 105-125 | ✅ |
| 10 | Replace silent NO_ACTION | `agents/unified_decision_layer.py` | 121-157 | ✅ |
| 11 | Add asset/timeframe extraction | `agents/unified_decision_layer.py` | 186-206 | ✅ |
| 12 | Add quorum failure alerting | `agents/quorum_hardening.py` | 200-225 | ✅ |

### 3.3 Alert Management

| # | Fix | File | Line | Status |
|---|-----|------|------|--------|
| 13 | Create AlertManager | `agents/alert_manager.py` | new | ✅ |
| 14 | Add deduplication keys | `agents/alert_manager.py` | 140-155 | ✅ |
| 15 | Add tiered cooldowns | `agents/alert_manager.py` | 50-55 | ✅ |
| 16 | Add multi-channel routing | `agents/alert_manager.py` | 160-200 | ✅ |
| 17 | Add asset/timeframe helpers | `agents/alert_manager.py` | 220-270 | ✅ |
| 18 | Integrate with watchdogs | `agents/watchdog_asset_coverage.py` | 250-280 | ✅ |

### 3.4 Assistant API Hardening

| # | Fix | File | Line | Status |
|---|-----|------|------|--------|
| 19 | Create Assistant API V2 | `web/api/assistant_api_v2.py` | new | ✅ |
| 20 | Add rate limiting (30 req/min) | `web/api/assistant_api_v2.py` | 35-80 | ✅ |
| 21 | Add request timeouts (10s) | `web/api/assistant_api_v2.py` | 380-395 | ✅ |
| 22 | Add StructuredError responses | `web/api/assistant_api_v2.py` | 110-130 | ✅ |
| 23 | Replace swallow patterns | `web/api/assistant_api_v2.py` | 230-280 | ✅ |
| 24 | Add GathererError handling | `web/api/assistant_api_v2.py` | 220-290 | ✅ |
| 25 | Add per-asset/timeframe fields | `web/api/assistant_api_v2.py` | 160-180 | ✅ |

### 3.5 Watchdog Coverage

| # | Fix | File | Line | Status |
|---|-----|------|------|--------|
| 26 | Create AssetTimeframeWatchdog | `agents/watchdog_asset_coverage.py` | 60-120 | ✅ |
| 27 | Add per-asset health checks | `agents/watchdog_asset_coverage.py` | 123-200 | ✅ |
| 28 | Add data freshness monitoring | `agents/watchdog_asset_coverage.py` | 165-175 | ✅ |
| 29 | Add exposure tracking | `agents/watchdog_asset_coverage.py` | 195-210 | ✅ |
| 30 | Create coverage report | `agents/watchdog_asset_coverage.py` | 280-330 | ✅ |

### 3.6 Integration Tasks (Remaining)

| # | Task | Priority | Status |
|---|------|----------|--------|
| 31 | Wire AlertManager to Telegram | High | ⏳ |
| 32 | Add AlertManager webhook channel | Medium | ⏳ |
| 33 | Create migration guide (V1→V2) | High | ⏳ |
| 34 | Add tests for quorum hardening | High | ⏳ |
| 35 | Add tests for governance event bus | High | ⏳ |
| 36 | Document API changes | Medium | ⏳ |

---

## 4. Operator Runbook

### 4.1 Quick Reference Commands

```bash
# Check system health
GET /api/v1/assistant/health

# Query with asset/timeframe filter
POST /api/v1/assistant/query
{
  "query": "BTC 15m health status",
  "asset_filter": ["BTC"],
  "timeframe_filter": ["15m"]
}

# Get coverage report
GET /api/v1/watchdog/coverage-report

# Force health check for specific market
POST /api/v1/watchdog/force-check
{
  "asset": "BTC",
  "timeframe": "15m"
}

# List pending governance actions
GET /api/v1/governance/pending

# Query governance audit trail
POST /api/v1/governance/audit
{
  "target_agent": "BTC_15M",
  "limit": 50
}

# Get quorum configuration
GET /api/v1/consensus/quorum-config

# Get active alerts
GET /api/v1/alerts/active?severity=critical

# Acknowledge alert
POST /api/v1/alerts/acknowledge
{
  "alert_id": "alert_12345",
  "operator_id": "operator_001"
}
```

### 4.2 Alert Response Playbooks

#### Quorum Failure Alert

**Symptoms**: `QUORUM_FAILED` decision type, insufficient agents contributing

**Impact**: No trades will execute for affected asset/timeframe

**Response Steps**:
1. Check agent health: `GET /api/v1/watchdog/coverage-report`
2. Identify offline agents in affected asset/timeframe
3. Check agent logs for crash/reason
4. If agent crashed: restart via deployment pipeline
5. If agent paused: investigate reason (risk breach? governance action?)
6. Emergency override (only if approved by senior operator):
   ```bash
   POST /api/v1/consensus/emergency-override
   {
     "asset": "BTC",
     "timeframe": "15m",
     "reason": "Manual override for system recovery",
     "operator_id": "operator_001"
   }
   ```

**Escalation**: If >2 assets affected simultaneously, page on-call engineer

#### Data Staleness Alert

**Symptoms**: `data_staleness_seconds > threshold` for market series

**Thresholds by Timeframe**:
- 15m: >60s
- 1h: >300s  
- Daily: >900s
- Weekly: >1800s

**Response Steps**:
1. Check Kalshi WebSocket connection: `GET /api/v1/kalshi/connection-status`
2. Verify series is still active on Kalshi
3. Check market state store: `GET /api/v1/kalshi/market-states?tickers=KXBTC15M`
4. If WS disconnected: check credentials and restart connection
5. If series delisted: remove from universe config

#### High Exposure Alert

**Symptoms**: `gross_exposure > max_position_value` for asset

**Response Steps**:
1. Check current positions: `GET /api/v1/portfolio/positions?asset=BTC`
2. Verify exposure calculations match Kalshi
3. If legitimate breach: kill switch may auto-trigger
4. If false positive: recalibrate position sizing

### 4.3 Governance Action Workflow

**When Governor V2 initiates PAUSE/RETIRE**:

1. Alert fires via AlertManager (Telegram + UI)
2. Action is recorded in audit trail with `pending` status
3. UnifiedDecisionLayer evaluates quorum requirement
4. If quorum approves: action executes with timeout
5. If quorum rejects: action logged as `rejected`
6. Operator can query status:
   ```bash
   GET /api/v1/governance/pending
   GET /api/v1/governance/audit?target_agent=BTC_15M
   ```

**Manual Intervention**:
- To resume paused agent: Requires quorum approval via `POST /api/v1/governance/resume`
- To override retirement: Not permitted (create new agent instead)

### 4.4 Rate Limit Recovery

**Symptoms**: 429 Rate Limit Exceeded from Assistant API

**Response**:
1. Wait until `reset_at` timestamp in error response
2. Check if client is shared (multiple operators using same API key)
3. Consider implementing client-side caching

### 4.5 Emergency Procedures

**Global Kill Switch Activation**:
```bash
POST /api/v1/risk/kill-switch
{
  "action": "trigger",
  "reason": "Manual emergency stop",
  "operator_id": "operator_001",
  "scopes": ["all_trading"]
}
```

**Per-Asset Kill**:
```bash
POST /api/v1/risk/kill-switch
{
  "action": "trigger",
  "reason": "BTC markets unstable",
  "operator_id": "operator_001",
  "scopes": ["BTC"],
  "timeframes": ["15m", "1h"]
}
```

**Quorum Emergency Override** (use with extreme caution):
```bash
# Only for critical market events where consensus cannot be reached
POST /api/v1/consensus/emergency-override
{
  "decision_type": "emergency_exit",
  "asset": "BTC",
  "timeframe": "15m",
  "reason": "Exchange API reports positions liquidated",
  "operator_id": "operator_001",
  "requires_audit": true
}
```

### 4.6 Configuration Reference

**Environment Variables**:

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `MERID_MIN_CONSENSUS_QUORUM` | 3 | [1, 5] | Min agents for consensus |
| `MERID_GOVERNANCE_TIMEOUT_PAUSE` | 10 | >0 | Seconds to wait for pause |
| `MERID_GOVERNANCE_TIMEOUT_RETIRE` | 15 | >0 | Seconds to wait for retire |
| `MERID_ASSISTANT_RATE_LIMIT` | 30 | >0 | Requests per minute |
| `MERID_ASSISTANT_TIMEOUT` | 10 | >0 | Query timeout seconds |
| `MERID_ALERT_COOLDOWN_CRITICAL` | 0 | ≥0 | Critical alert cooldown |
| `MERID_ALERT_COOLDOWN_HIGH` | 60 | ≥0 | High alert cooldown (sec) |

**File Locations**:

| Component | Path | Description |
|-----------|------|-------------|
| Governance V2 | `agents/governor_agent_v2.py` | Hardened governor |
| Event Bus | `agents/governance_event_bus.py` | Pub/sub + audit |
| Quorum Hard. | `agents/quorum_hardening.py` | Quorum validation |
| Alert Manager | `agents/alert_manager.py` | Central alerting |
| Assistant V2 | `web/api/assistant_api_v2.py` | Hardened API |
| Watchdog V2 | `agents/watchdog_asset_coverage.py` | Per-asset coverage |
| Config | `config/kalshi_agent_grid.yaml` | Agent specifications |
| Series Meta | `config/kalshi_crypto_series_meta.py` | Series definitions |

### 4.7 Troubleshooting Guide

| Issue | Diagnostic | Resolution |
|-------|------------|------------|
| Quorum failures | Check `GET /api/v1/watchdog/coverage-report` | Restart offline agents |
| Governance actions pending | `GET /api/v1/governance/pending` | Check UnifiedDecisionLayer |
| Rate limiting | Check `X-RateLimit-Remaining` header | Wait for reset window |
| Data staleness | Check `GET /api/v1/kalshi/market-states` | Restart WebSocket |
| Alert spam | Check AlertManager cooldown config | Increase cooldown |
| Audit trail gaps | Query `GET /api/v1/governance/audit` | Check event bus connectivity |

---

## 5. Summary of Changes

### Files Created

1. `agents/governance_event_bus.py` — 250 lines — Pub/sub + immutable audit
2. `agents/governor_agent_v2.py` — 450 lines — Hardened governor with quorum
3. `agents/quorum_hardening.py` — 230 lines — Quorum validation + QuorumFailure
4. `agents/alert_manager.py` — 380 lines — Central alerting with dedup
5. `web/api/assistant_api_v2.py` — 520 lines — Hardened read-only API
6. `agents/watchdog_asset_coverage.py` — 400 lines — Per-asset watchdog

### Files Modified

1. `agents/unified_decision_layer.py` — ~80 lines changed — Quorum hardening

### Total Lines Added: ~2,500

### Critical Vulnerabilities Fixed

1. ✅ Circular callback (drift ↔ governor) decoupled via EventBus
2. ✅ Fire-and-forget replaced with awaited + timeout
3. ✅ Silent NO_ACTION replaced with QUORUM_FAILED + alert
4. ✅ Unvalidated MIN_QUORUM clamped to [1, 5]
5. ✅ Swallowed errors replaced with structured error responses
6. ✅ No rate limiting → 30 req/min sliding window
7. ✅ No per-asset watchdog → 25 asset/timeframe combinations monitored

---

*Document Version*: 1.1  
*Last Updated*: 2026-03-30 (Post-Audit Closure)  
*Author*: MERID Universal Agent Hardening Sprint

---

## Appendix A: DLQ Idempotency Design (Post-Audit)

### A.1 Problem Statement

**Finding 2.1 (Critical):** DLQ replay could double-execute destructive governance actions (PAUSE, RETIRE, EMERGENCY_EXIT), causing state corruption or error storms.

### A.2 Idempotency Strategy

**Implementation:** `agents/governance_event_bus.py:137-651`

```
┌─────────────────────────────────────────────────────────────────┐
│                    DLQ IDEMPOTENCY FLOW                         │
│                                                                 │
│  1. Event delivered successfully                                │
│     └─► _mark_action_applied() adds to _applied_governance_actions│
│         Key: "event_type:target:asset:timeframe:action:event_id" │
│                                                                 │
│  2. Event fails delivery 3x, lands in DLQ                       │
│     └─► Stored with retry_count, last_retry, error             │
│                                                                 │
│  3. Operator initiates replay: retry_dead_letter()             │
│     ├─► Peek at DLQ[0] without removing                         │
│     ├─► Generate idempotency key                               │
│     ├─► Check _applied_governance_actions                       │
│     │   ├─ EXISTS: skip, remove from DLQ, log "idempotent"    │
│     │   └─ NEW: proceed with delivery                          │
│     │       ├─ Success: mark applied, remove from DLQ          │
│     │       └─ Failure: append to DLQ with +1 retry_count      │
│     └─► Return detailed results (processed/applied/skipped/failed)│
│                                                                 │
│  4. Dry Run Mode (dry_run=True)                                │
│     └─► Shows what would happen without executing              │
│                                                                 │
│  5. Operational Visibility                                      │
│     └─► get_dlq_replay_stats() shows attempted/applied/skipped/failed│
└─────────────────────────────────────────────────────────────────┘
```

### A.3 Safety Guarantees

| Scenario | Behavior | Evidence |
|----------|----------|----------|
| Replay already-applied PAUSE | Skipped, no side effects | `_is_action_already_applied()` returns True |
| Replay never-applied PAUSE | Executed, then marked | `_mark_action_applied()` adds to set |
| Replay destructive after state change | Skipped (idempotent) | Key collision in `_applied_governance_actions` |
| Dry run mode | Shows without executing | `dry_run=True` bypasses actual delivery |

### A.4 API Reference

```python
# Inspect DLQ with idempotency status
entries = bus.get_dead_letter_queue(include_idempotency_status=True)
# Returns: [{..., "idempotency_key": "...", "would_be_skipped": True/False}]

# Replay with safety checks
result = await bus.retry_dead_letter(max_events=10, skip_idempotent=True, dry_run=False)
# Returns: {"processed": N, "applied": N, "skipped_idempotent": N, "failed": N, "events": [...]}

# Get operational metrics
stats = bus.get_dlq_replay_stats()
# Returns: {"total_attempted": N, "total_applied": N, "total_skipped_idempotent": N, ...}

# Emergency: clear idempotency store (allows re-application)
bus.clear_idempotency_store()  # Logs warning
```

### A.5 Testing

**Test Class:** `tests/test_post_remediation_wiring.py::TestDLQIdempotency`

| Test Method | Coverage |
|-------------|----------|
| `test_pause_event_idempotent_on_replay()` | Verifies PAUSE skipped when already applied |
| `test_retire_event_idempotent_on_replay()` | Verifies RETIRE skipped when already applied |
| `test_dlq_replay_dry_run_mode()` | Verifies dry_run shows without executing |
| `test_dlq_replay_metrics_tracked()` | Verifies stats increment correctly |
| `test_destructive_vs_non_destructive_replay_safety()` | Verifies RESUME also idempotent |

**Run:** `pytest tests/test_post_remediation_wiring.py::TestDLQIdempotency -v`

---

## Appendix B: Post-Remediation Wiring Test Suite

### B.1 Test Suite Location

**File:** `tests/test_post_remediation_wiring.py`  
**Lines:** 580+  
**Test Methods:** 29 across 8 classes  
**Marker:** `pytestmark = pytest.mark.wiring_hardening`

### B.2 Test Classes

| Class | Tests | Purpose |
|-------|-------|---------|
| `TestDLQIdempotency` | 6 | DLQ replay safety (Finding 2.1) |
| `TestAlertManagerEscalation` | 3 | Escalation/de-escalation (Finding 3.1) |
| `TestConcurrentQuorumFailures` | 4 | Series isolation (Finding 4.3) |
| `TestLegacySymbolNormalization` | 5 | 25-pair coverage + fuzz testing (Finding 1.2) |
| `TestAlertManagerMetaErrors` | 3 | Sink failure handling (Finding 3.3) |
| `TestUnifiedDecisionLayerQuorum` | 2 | QUORUM_FAILED flow (Finding 4.1) |
| `Test25PairCoverageTruthTable` | 4 | Fast sanity tests for all pairs |
| `TestOperatorWorkflows` | 2 | Operator-facing workflow tests |

### B.3 Invariant Enforcement

| Finding | Test Method | Invariant |
|---------|-------------|-----------|
| 2.1 | `test_pause_event_idempotent_on_replay()` | DLQ replay cannot double-apply PAUSE |
| 2.1 | `test_retire_event_idempotent_on_replay()` | DLQ replay cannot double-apply RETIRE |
| 1.2 | `test_all_25_pairs_in_config()` | Exactly 25 pairs exist in config |
| 1.2 | `test_unknown_symbols_fail_loudly()` | Unknown symbols return None, not mis-mapped |
| 4.3 | `test_concurrent_failures_isolated()` | BTC-15m and ETH-1h failures don't interfere |
| 3.3 | `test_telegram_sink_failure_handling()` | Sink failures don't block other channels |
| 4.1 | `test_quorum_failure_returns_explicit_status()` | QUORUM_FAILED returned, not NO_ACTION |

### B.4 Running the Suite

```bash
# All wiring hardening tests
pytest tests/test_post_remediation_wiring.py -v

# Specific test class
pytest tests/test_post_remediation_wiring.py::TestDLQIdempotency -v

# Only critical findings (marked with pytest mark)
pytest tests/test_post_remediation_wiring.py -m "wiring_hardening" -v

# CI-friendly (parallel execution)
pytest tests/test_post_remediation_wiring.py -n auto --tb=short
```

### B.5 Related Documents

| Document | Purpose |
|----------|---------|
| `docs/POST_REMEDIATION_ADVERSARIAL_AUDIT.md` | Full audit findings with 23 entries |
| `docs/POST_REMEDIATION_ADVERSARIAL_AUDIT.md` Section "Critical Risks Closed" | Verification that findings 2.1 and 6.1 are closed |

---

## C. Proposal Generation (Post-Audit Implementation)

### C.1 Normalized Proposal Schema

All agents emitting trade proposals must conform to `NormalizedProposal`:

```python
@dataclass
class NormalizedProposal:
    # Identity
    proposal_id: str
    agent_id: str
    agent_role: str
    
    # Market Context (REQUIRED)
    asset: str                      # Must be in ACTIVE_CRYPTO_ASSETS
    timeframe: str                  # Must be in ACTIVE_CRYPTO_TIMEFRAMES
    kalshi_ticker: str              # Validated Kalshi series ticker
    
    # Decision (REQUIRED)
    recommendation: str             # "buy", "sell", "hold", "abstain"
    direction: str                  # "bullish", "bearish", "neutral"
    confidence: float               # 0.0 to 1.0
    
    # Risk Fields
    size_hint: Optional[int] = None
    max_position: Optional[int] = None
    risk_pct: Optional[float] = None
    
    def validate(self) -> List[str]:
        """Returns empty list if valid, error messages otherwise."""
```

### C.2 Validation Gate

All proposals are validated at `SwarmConsensusAggregator.submit_proposal()`:

- Invalid assets/timeframes: **REJECTED** with error log
- Missing required fields: **REJECTED** with error log
- Invalid confidence values: **REJECTED** with error log
- Valid proposals: **ACCEPTED** into consensus

### C.3 NewsMonitorAgent Fixes

| Issue | Fix | Status |
|-------|-----|--------|
| SOL scoring bug (line 439) | Fixed duplicate `sol_bullish` → `sol_bearish` | ✅ |
| Missing weekly/monthly pairs | Expanded to all 25 pairs via `crypto_universe` | ✅ |
| Hardcoded asset methods | Refactored to dynamic `asset_impacts` dict | ✅ |
| Kalshi ticker coverage | Now generates for all BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly | ✅ |

### C.4 Test Coverage

| Test | Description |
|------|-------------|
| `test_news_monitor_generates_all_25_pairs_when_news_exists` | Verifies all 25 crypto pairs covered |
| `test_sol_bearish_news_scored_correctly` | Regression test for SOL bug |
| `test_invalid_asset_or_timeframe_proposals_are_rejected` | Validation gate working |
| `test_direction_and_recommendation_fields_aligned` | Schema alignment verified |

### C.5 Running Proposal Tests

```bash
# All proposal generation tests
pytest tests/test_proposal_generation.py -v

# Specific test
pytest tests/test_proposal_generation.py::TestNewsMonitorProposalGeneration::test_sol_bearish_news_scored_correctly -v

# Combined with wiring tests
pytest tests/test_post_remediation_wiring.py tests/test_proposal_generation.py -v
```

---

**Final Status:** All critical and high risks closed. 25-pair coverage verified. Wiring hardened by construction and enforced by tests. Proposal generation normalized and validated.

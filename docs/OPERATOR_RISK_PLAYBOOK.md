# MERID Operator Risk Playbook

**Version:** 2026-03-29  
**Applies to:** MERID v2.0+ with risk snapshot endpoint  
**Owner:** Trading Operations

---

## Quick Reference: Risk State Snapshot

The `/api/risk/snapshot` endpoint provides a single source of truth for all risk controls:

```bash
# Quick health check
curl /api/risk/snapshot | jq '{blocked: .trading_blocked, reason: .trading_blocked_reason, guard: .kill_switch_guard.active, rc: .kill_switch_risk_controller.active}'

# Asset utilization check
curl /api/risk/snapshot | jq '.assets | to_entries[] | {asset: .key, used: .value.used, limit: .value.limit, pct: .value.utilization_pct}'
```

---

## 1. Health Check Procedure

### When to Run
- At start of trading session
- After any PROTECT alert
- Before resuming trading post-incident
- Every 30 minutes during active trading

### Steps

1. **Query the snapshot:**
   ```bash
   curl -s /api/risk/snapshot | jq '.'
   ```

2. **Verify critical fields:**
   - `trading_blocked` → should be `false` for normal operations
   - `kill_switch_guard.active` → should be `false`
   - `kill_switch_risk_controller.active` → should be `false`
   - `cqi.score` → should be > 0.3 (above block threshold)

3. **Check utilization:**
   - Asset caps: No asset should exceed 90% utilization
   - Domain caps: No domain should exceed 95% utilization

4. **Validate recent events:**
   - `recent_protect_events` should be empty (or reviewed if present)
   - `recent_cap_events` should show expected clamping behavior

### Decision Matrix

| Condition | Status | Action |
|-----------|--------|--------|
| All clear | ✅ HEALTHY | Proceed with trading |
| `trading_blocked: true` | 🔴 BLOCKED | Investigate reason, do NOT trade |
| Asset > 90% utilized | 🟡 WARNING | Monitor closely, consider reducing size |
| CQI < 0.3 | 🔴 LOW CQI | Trading blocked automatically |
| Cooldown active | 🟡 WAIT | Wait for cooldown to expire |

---

## 2. Incident Triage Procedure

### Trigger: PROTECT Alert Received

When a Telegram PROTECT alert fires (e.g., "🚨 [KILL SWITCH] DAILY_LOSS"):

1. **Immediately query snapshot:**
   ```bash
   curl /api/risk/snapshot | jq '{
     blocked: .trading_blocked,
     reason: .trading_blocked_reason,
     guard_reason: .kill_switch_guard.reason,
     rc_reason: .kill_switch_risk_controller.reason,
     events: .recent_protect_events
   }'
   ```

2. **Identify the trigger:**
   - Check `trading_blocked_reason` for the root cause
   - Review `recent_protect_events` for context
   - Note the timestamp for incident logs

3. **Assess impact:**
   - Check `assets` to see current utilization
   - Check `domains` for domain-specific issues
   - Review `cqi` for market quality issues

4. **Decision:**

   **Option A: Config Issue → Fix & Reset**
   - If caps are too tight or config error caused the trigger
   - Fix the underlying issue
   - Use admin reset command (see Section 4)
   - Verify via `/api/risk/snapshot` that `trading_blocked: false`

   **Option B: Legitimate Risk Event → Stay Blocked**
   - If daily loss limit reached or market anomaly detected
   - Keep trading halted
   - Document in incident log
   - Reassess before market open next day

---

## 3. Safe Re-Enable Procedure

### Prerequisites
- Root cause of kill switch has been addressed
- Operator has reviewed and approved re-enablement
- Telegram notification channel is confirmed working

### Steps

1. **Verify snapshot shows blocked state:**
   ```bash
   curl /api/risk/snapshot | jq '.trading_blocked, .trading_blocked_reason'
   # Expected: true, "some reason"
   ```

2. **Clear guard kill switch (if active):**
   ```bash
   curl -X POST /api/risk/protections/circuit-breaker/reset
   ```

3. **Clear risk_controller kill switch:**
   ```bash
   # Use the kill switch reset endpoint
   curl -X POST /api/risk/kill-switch/disable
   ```

4. **Verify re-enablement:**
   ```bash
   curl /api/risk/snapshot | jq '{
     blocked: .trading_blocked,
     guard: .kill_switch_guard.active,
     rc: .kill_switch_risk_controller.active
   }'
   # Expected: false, false, false
   ```

5. **Confirm via Telegram:**
   - A "Kill switch RESET" message should appear in Telegram
   - If not received, check webhook/alerts configuration

6. **Document:**
   - Record in incident log: operator, timestamp, reason for reset
   - Note any follow-up actions required

---

## 4. API Endpoints Reference

### GET /api/risk/snapshot

Returns complete risk state.

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO timestamp of snapshot |
| `trading_blocked` | boolean | **Convenience flag** — true if any blocker active |
| `trading_blocked_reason` | string | Human-readable reason for block |
| `kill_switch_guard` | object | ExecutionGuard kill switch state |
| `kill_switch_risk_controller` | object | RiskController kill switch state |
| `domains` | object | Domain caps (prediction, crypto, etc.) |
| `venues` | object | Venue caps (kalshi, etc.) |
| `assets` | object | Asset caps (BTC, ETH, SOL, XRP, DOGE) |
| `cqi` | object | CQI score and throttle settings |
| `cooldown` | object | Cooldown status |
| `promotion` | object | Promotion enforcement status |
| `recent_protect_events` | array | Recent kill switch / PROTECT events |
| `recent_cap_events` | array | Recent cap clamping events |

**Example Response:**

```json
{
  "timestamp": "2026-03-29T12:00:00Z",
  "trading_blocked": false,
  "trading_blocked_reason": "",
  "kill_switch_guard": {
    "active": false,
    "reason": ""
  },
  "kill_switch_risk_controller": {
    "active": false,
    "reason": ""
  },
  "assets": {
    "BTC": {
      "name": "BTC",
      "limit": 4000.0,
      "used": 3500.0,
      "remaining": 500.0,
      "utilization_pct": 87.5
    }
  },
  "cqi": {
    "score": 0.95,
    "throttle_pct": 100.0,
    "block_below": 0.3,
    "full_above": 0.8
  }
}
```

### POST /api/risk/kill-switch/enable

**Emergency stop.** Immediately blocks all trading.

Use for:
- Manual emergency halt
- Pre-market shutdown
- Incident response

### POST /api/risk/kill-switch/disable

**Reset kill switch.** Requires explicit operator acknowledgment.

### POST /api/risk/protections/circuit-breaker/reset

Reset circuit breaker state (separate from kill switch).

---

## 5. Risk Architecture Overview

### Kill Switch Layers

1. **ExecutionGuard** (`kill_switch_guard`)
   - Global/domin-level blocks
   - Persisted to disk (survives restart)
   - Manual reset required

2. **RiskController** (`kill_switch_risk_controller`)
   - Automated triggers (daily loss, errors, position limits)
   - Persists to disk
   - Includes RTI feed stale, loop lag, portfolio integrity checks

### Cap Hierarchy

Caps are checked in order during `pre_trade_check`:

1. **CQI Throttle** — reduces size based on market quality
2. **Cooldown** — blocks if < 5s since last trade
3. **Promotion** — blocks non-promoted agents in live mode
4. **Domain Cap** — per-domain daily limits
5. **Venue Cap** — per-venue exposure limits
6. **Asset Cap** — per-asset daily limits (BTC, ETH, SOL, XRP, DOGE)
7. **Single Trade Cap** — per-trade maximums

### Notification Flow

```
Kill Switch Trigger
  → Session log (critical)
  → Telegram PROTECT alert
  → Persistence to disk
  → Agent propagation
  → /api/risk/snapshot reflects immediately
```

---

## 6. Troubleshooting

### Issue: Snapshot shows `trading_blocked: true` but no obvious cause

**Check:**
1. Cooldown: `curl /api/risk/snapshot | jq '.cooldown'`
2. Hidden kill switch: Check both guard and RC reasons
3. CQI block: Verify `.cqi.score > .cqi.block_below`

### Issue: Asset utilization not updating

**Cause:** Execution path not calling `record_execution()` with `asset` parameter.

**Diagnostic:**
- Check fills in logs
- Verify `record_execution("crypto", size, asset="BTC")` is called
- Compare fill timestamps to snapshot timestamp

### Issue: Telegram alerts not received

**Check:**
1. `tg_send` connectivity: Test via `/api/system/health`
2. Telegram credentials: Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
3. Rate limiting: Messages may be suppressed if > 1 per 5 seconds

### Issue: Kill switch persists after reset

**Check:**
1. Both guard AND risk_controller need reset
2. Disk persistence: Check `data/risk_kill_switch.json`
3. Multiple triggers: May re-trigger immediately if condition still present

---

## 7. Runbooks by Scenario

### Scenario: Daily Loss Limit Reached

**Detection:** PROTECT alert: "DAILY_LOSS"

**Response:**
1. Acknowledge alert
2. Query snapshot: `curl /api/risk/snapshot | jq '.kill_switch_risk_controller'`
3. **DO NOT RESET** — This is a legitimate circuit breaker
4. Document: `Daily loss ${amount} reached at ${timestamp}`
5. Resume: Next trading day only

### Scenario: RTI Feed Stale

**Detection:** PROTECT alert: "RTI_FEED_STALE"

**Response:**
1. Check CFB (continuous futures basis) data source
2. Verify network connectivity to RTI provider
3. If resolved → Reset kill switch
4. Monitor CQI score returns to normal

### Scenario: Manual Emergency Stop

**Detection:** PROTECT alert: "MANUAL"

**Response:**
1. Operator initiated — verify intentional
2. Assess market conditions
3. When ready → Reset kill switch
4. Confirm `trading_blocked: false` before placing orders

### Scenario: Position Limit Breach

**Detection:** PROTECT alert: "POSITION_LIMIT"

**Response:**
1. Verify position sizing in snapshot: `.venues[].used`
2. Check if sizing calculation error
3. If config error → Fix config → Reset
4. If legitimate breach → Reduce positions → Reset

---

## Appendix: JSON Path Quick Reference

```bash
# Is trading blocked?
.trading_blocked

# Why is it blocked?
.trading_blocked_reason

# Which kill switch?
.kill_switch_guard.active
.kill_switch_risk_controller.active

# Specific reasons
.kill_switch_guard.reason
.kill_switch_risk_controller.reason

# Asset utilization sorted high→low
.assets | to_entries | sort_by(.value.utilization_pct) | reverse | .[].key

# All at-limit assets
.assets | to_entries[] | select(.value.utilization_pct > 90)

# CQI status
.cqi | {score: .score, throttle: .throttle_pct, blocked: (.score < .block_below)}

# Cooldown remaining
.cooldown | {active: .active, remaining: .seconds_remaining}

# Recent issues
.recent_protect_events, .recent_cap_events
```

---

## 8. Configuration Management

### Asset Caps: Single Source of Truth

**CRITICAL:** All per-asset risk caps must be changed via `settings.asset_caps` in the configuration file. Never call `set_asset_cap()` ad hoc in runtime code outside of test scenarios.

**Correct approach:**
```yaml
# config/settings.yaml — This is the source of truth
merid:
  asset_caps:
    BTC:
      max_daily_notional_usd: 4000
      max_single_trade_usd: 1000
    ETH:
      max_daily_notional_usd: 3000
      max_single_trade_usd: 750
```

**Incorrect approach:**
```python
# Any runtime code outside tests — DO NOT DO THIS
guard.set_asset_cap("BTC", 9999, 9999)  # ❌ Violates single source of truth
```

**Why this matters:**
- Config changes are version-controlled and auditable
- Runtime mutations bypass validation and may conflict with persisted state
- The `RiskSnapshot` endpoint reads from config-synced state, not runtime mutations
- `ensure_core_assets_caps()` validates config at startup, not runtime hacks

### Adding New Kill Switch Types, Caps, or Controls

When adding new risk controls, follow this checklist to maintain snapshot/Telegram synchronization:

**Development Checklist:**
- [ ] **RiskSnapshot Schema:** Add new field to `RiskSnapshot` Pydantic model in `merid/risk_state.py`
- [ ] **Aggregation Logic:** Update `get_risk_snapshot()` to populate the new field
- [ ] **Telegram Alerts:** Ensure new kill-switch triggers call `tg_send()` or `send_protect_alert()`
- [ ] **Playbook Update:** Add new section to OPERATOR_RISK_PLAYBOOK.md:
  - Health check field reference
  - Incident triage procedure
  - JSON path for querying
- [ ] **Meta-Test:** Add test verifying new field appears in snapshot response

**Example:** Adding a new `LatencyKillSwitch`
```python
# 1. Add to schema
class RiskSnapshot(BaseModel):
    latency_kill: KillSwitchSnapshot  # NEW

# 2. Aggregate in get_risk_snapshot()
snapshot["latency_kill"] = KillSwitchSnapshot(
    active=latency_monitor.is_triggered(),
    reason=latency_monitor.last_reason()
)

# 3. Telegram alert in trigger_latency_kill()
await send_protect_alert(
    episode_id="latency",
    summary=f"Latency kill: {latency_ms}ms > {threshold}ms"
)

# 4. Playbook: Add JSON path .latency_kill.active
```

---
- 2026-03-29: Initial version with risk snapshot endpoint
- Covers: ExecutionGuard, RiskController, Telegram alerts, cap hierarchy

**Related Documents:**
- `docs/KALSHI_GO_LIVE_CHECKLIST.md`
- `docs/FEATURE_FLAG_PLAYBOOK.md`
- `docs/PRE_DEPLOY_CHECKLIST.md`

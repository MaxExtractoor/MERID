# Incident Investigation Runbook

## Quick Start: 5-Minute Order Investigation

Use `incident_replay.py` to debug any order in under 5 minutes:

```bash
python scripts/incident_replay.py ORDER_ID --format markdown
```

This pulls: lineage, reconciliation status, fills, positions, risk state, and generates an investigation checklist.

---

## Investigation Checklist Template

When an alert fires or an operator reports unexpected behavior, follow this sequence:

### 1. Identify the Order/Position
- [ ] Get order_id from alert or operator report
- [ ] If no order_id, get ticker + time window from report

### 2. Pull Lineage
```bash
curl http://localhost:8000/api/v1/kalshi/orders/{order_id}/lineage | jq
```
**Check:**
- [ ] `found: true` — Order exists in system
- [ ] `chain_complete: true` — Full trace available (signal→agent→consensus→risk→router)
- [ ] `manual_or_external: false` — Order went through normal pipeline
- [ ] `synthetic: false` — Not simulated/backtest data
- [ ] `warnings: []` — No lineage gaps

### 3. Check Reconciliation
```bash
curl http://localhost:8000/api/v1/kalshi/reconciliation/breaks | jq
```
**Check:**
- [ ] `status: "ok"` — No reconciliation issues
- [ ] `break_count: 0` — No active breaks
- [ ] Order_id not in `unmatched_fills` or `unmatched_positions`

### 4. Verify Kill Switch State
```bash
curl http://localhost:8000/api/v1/kalshi/risk | jq '.kill_switch_active'
```
**Check:**
- [ ] `false` unless emergency — Kill switch should be inactive for normal trading
- [ ] If `true` — Check kill switch trigger reason in state transitions

### 5. Check UI Flags
In the Kalshi Dashboard, verify:
- [ ] **Global Mode Banner** — Shows LIVE/PAPER/SIM/HALTED correctly
- [ ] **Order badges** — Order shows "TRACED" (green) not "EXTERNAL" (orange) or "SIMULATED" (purple)
- [ ] **Reconciliation status** — No red "RECON: BROKEN" indicator

### 6. Cross-Reference Fills
```bash
curl http://localhost:8000/api/v1/kalshi/fills?since_hours=1 | jq
```
**Check:**
- [ ] Order has corresponding fills
- [ ] Fill amounts match order size
- [ ] Fill timestamps align with order creation

---

## Incident Severity Classification

| Severity | Condition | Response |
|----------|-----------|----------|
| **P0 (Critical)** | `chain_complete: false` + `manual_or_external: false` in LIVE mode | Stop trading, page on-call |
| **P1 (High)** | Reconciliation `status: "broken"` | Stop trading, manual reconciliation |
| **P2 (Medium)** | Reconciliation `status: "degraded"` | Monitor closely, investigate within 1hr |
| **P3 (Low)** | `synthetic: true` in LIVE mode | Verify simulation flag intentional |

---

## Common Incident Patterns

### Pattern A: Incomplete Lineage (Ghost Order)
**Symptoms:**
- Order visible in UI
- `found: true`, `chain_complete: false`
- No corresponding fills

**Investigation:**
```bash
# Check lineage gaps
python scripts/incident_replay.py $ORDER_ID --format timeline

# Look for signal/agent/consensus/risk/router links
# Missing link indicates where trace was lost
```

**Resolution:**
1. Check if order was created by migration script (check whitelist)
2. If external/manual, verify `manual_or_external: true` is set
3. If should be full trace, investigate missing link component

---

### Pattern B: Reconciliation Break
**Symptoms:**
- `status: "broken"` or `status: "degraded"`
- Unmatched fills or positions
- PnL divergence

**Investigation:**
```bash
# Get break details
curl http://localhost:8000/api/v1/kalshi/reconciliation/breaks | jq '.breaks'

# Check specific order
curl http://localhost:8000/api/v1/kalshi/orders/{order_id}/lineage | jq '.fills_ledger'
```

**Resolution:**
1. For `unmatched_fill`: Check if fill was recorded but position not updated
2. For `unmatched_position`: Verify position has backing fills in ledger
3. For `pnl_divergence`: Compare fills ledger PnL vs risk controller PnL

---

### Pattern C: Kill Switch Didn't Block
**Symptoms:**
- `kill_switch_active: true` at time T
- Order placed at time T+1 with `mode: "live"`

**Investigation:**
```bash
# Check state transitions
python scripts/incident_replay.py $ORDER_ID --format timeline

# Look for: kill_switch trip → order placement sequence
```

**Resolution:**
1. Verify order_router is checking kill switch before routing
2. Check if order was placed directly via client (bypassing router)
3. Review CI guardrail for direct venue touchpoints

---

## Using incident_replay.py

### Basic Usage
```bash
# Markdown report (default)
python scripts/incident_replay.py ORDER_ID

# JSON output for automation
python scripts/incident_replay.py ORDER_ID --format json

# Timeline view
python scripts/incident_replay.py ORDER_ID --format timeline

# Save to file
python scripts/incident_replay.py ORDER_ID -o incident_report.md
```

### Advanced Usage
```bash
# Specific time window
python scripts/incident_replay.py ORDER_ID \
  --start-time "2026-03-24T00:00:00Z" \
  --end-time "2026-03-24T01:00:00Z"

# Extended window (default 10min, use 30min for complex incidents)
python scripts/incident_replay.py ORDER_ID --window-minutes 30

# Against staging
python scripts/incident_replay.py ORDER_ID --base-url https://staging.merid.io
```

---

## Output Formats

### Markdown Report Sections
1. **Executive Summary** — Key finding (Golden Path / External / Investigation Needed)
2. **Order Lineage** — Full chain with explicit flags
3. **Reconciliation Status** — Current breaks and severity
4. **Fills** — Associated fill records
5. **Risk Status** — Kill switch, PnL, drawdown at incident time
6. **Investigation Checklist** — Action items based on findings
7. **Debug Commands** — Copy-paste curl commands for deeper investigation

### JSON Output Structure
```json
{
  "order_id": "...",
  "investigation_window": ["2026-03-24T00:00:00Z", "2026-03-24T00:10:00Z"],
  "lineage": { /* ... */ },
  "reconciliation": { /* ... */ },
  "fills": [ /* ... */ ],
  "checklist": ["..."]
}
```

### Timeline Format
```
2026-03-24T00:01:00 | lineage:signal    | {"action": "buy", "confidence": 0.85}
2026-03-24T00:01:05 | lineage:consensus | {"approved": true, "confidence": 0.82}
2026-03-24T00:01:06 | lineage:risk      | {"allowed": true, "checks": [...]}
2026-03-24T00:01:07 | lineage:router    | {"order_id": "abc123", "mode": "live"}
2026-03-24T00:01:08 | fill              | {"fill_id": "f001", "size": 10}
```

---

## Integration with Alerting

### PagerDuty/Slack Webhook
Configure `STATE_TRANSITION_WEBHOOK_URL` to receive:
```json
{
  "event": "state_transition",
  "transition_type": "reconciliation|kill_switch|trading_mode",
  "severity": "critical|warning|info",
  "timestamp": "2026-03-24T00:00:00Z",
  "transition": "ok -> broken",
  "context": {...}
}
```

### Telegram Alerts
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for critical transitions.

---

## Training: Synthetic Incident Examples

See [`docs/incident_examples/`](./incident_examples/) for:
1. **Example 1:** Incomplete lineage due to missing signal (investigation walkthrough)
2. **Example 2:** Reconciliation break from unmatched fill (resolution steps)
3. **Example 3:** Kill switch race condition (post-mortem analysis)

Each example includes:
- Timeline reconstruction
- Debug commands used
- Root cause identification
- Fix verification steps

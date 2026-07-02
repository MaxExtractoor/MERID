# Live Run Monitoring Checklist

**Purpose**: Systematic monitoring of first live trading session after Bug 26 fix (duplicate settings fields).
**Session Start**: 2026-05-23 22:03 UTC
**Profile**: kalshi_crypto_15m_v2
**Mode**: LIVE (VenueGate confirmed: mode=live, live_enabled=True)

---

## Pre-Run Verification (✅ Complete)

- [x] Bug 26 fixed: Duplicate field definitions in `merid/settings.py` consolidated
- [x] Environment variables confirmed:
  - `MERID_PM_TRADING_MODE=live`
  - `MERID_PM_LIVE_ENABLED=true`
  - `MERID_ALLOW_LIVE_TRADES=true`
  - `KALSHI_ENV=live`
  - `KALSHI_USE_DEMO=false`
- [x] VenueGate initialized: `mode=live, live_enabled=True`
- [x] Order routing path confirmed: `route_order_async` → `_route_live` → Kalshi API
- [x] Pre-trade gate confirmed functional (one order passed during startup)

---

## Real-Time Monitoring (30-60 minutes)

### 1. Order Submission Signals

**Log Patterns to Watch:**
```
[ORDER-CONSTRUCTION-AUDIT] ... mode=live
[KALSHI-ORDER-LIFECYCLE] ... status=filled_live|submitted_live
[order-router] Live order submitted to Kalshi API
```

**Checks:**
- [ ] Any orders pass edge-threshold (`edge_actual >= edge_req`)
- [ ] Orders flow through `_route_live` (not `_route_sync_non_live`)
- [ ] Kalshi API `place_order_result` called successfully
- [ ] Client order IDs follow deterministic pattern (`merid-` prefix + SHA256)
- [ ] Pre-trade gate allows orders (lease acquired, dedup passed, fill-awareness passed)

**Red Flags:**
- Orders stuck in `decision=REJECT` with `NO_EDGE_YES` for extended periods (may indicate edge thresholds too aggressive)
- Orders passing edge but failing at pre-trade gate (lease, dedup, or fill-awareness issues)
- Orders reaching `_route_live` but failing Kalshi API call (network, auth, or rate limit)

---

### 2. Fill Tracking

**Log Patterns to Watch:**
```
[order-router] FILL CONFIRMED: ticker=... side=... count=... price=...
[KALSHI-ORDER-LIFECYCLE] ... status=filled_live
[FILLS-LEDGER] Fill recorded: ...
```

**Checks:**
- [ ] Fills appear in fills_ledger with correct metadata
- [ ] Fill deduplication working (no duplicate fills for same order)
- [ ] Position cache updates correctly on fills
- [ ] Exposure tracking updates (category, asset, per-contract)
- [ ] Bankroll reconciles with Kalshi balance endpoint

**Red Flags:**
- Fills not appearing in fills_ledger within 30 seconds
- Duplicate fills for same client_order_id
- Position cache desync from fills_ledger
- Exposure tracking not updating after fills

---

### 3. PnL and Reconciliation

**Log Patterns to Watch:**
```
[PNL-UPDATE] Realized PnL: ... Unrealized PnL: ...
[BANKROLL-RECON] Kalshi balance: ... Local bankroll: ... Delta: ...
```

**Checks:**
- [ ] Realized PnL updates correctly on exits
- [ ] Unrealized PnL tracks live mark-to-market
- [ ] Bankroll reconciliation completes successfully
- [ ] No reconciliation alerts fired (large deltas, missing fills)

**Red Flags:**
- Reconciliation delta > $5.00 (indicates data inconsistency)
- Missing fills in reconciliation (Kalshi has fills not tracked locally)
- Unrealized PnL not updating with live market prices

---

### 4. Risk Controls

**Log Patterns to Watch:**
```
[RISK-ENVELOPE] Asset ... min_floor applied
[GLOBAL-RISK-GUARD] APPROVED | REJECTED
[KILL-SWITCH] ...
```

**Checks:**
- [ ] Risk envelope min_floor applied correctly (per-asset floors)
- [ ] Global risk guard approves orders within budget
- [ ] Kelly caps respected (no position exceeds Kelly fraction)
- [ ] Deep-OTM/ITM filters fire as expected
- [ ] Price-band checks reject out-of-range orders
- [ ] Kill switches not triggered (unless intentional)

**Red Flags:**
- Risk guard rejecting valid orders (budget too tight)
- Kelly caps exceeded (sizing logic error)
- Kill switch triggered unexpectedly (sensor malfunction)
- Deep-OTM/ITM not firing (threshold misconfigured)

---

### 5. Market Regime and Execution

**Log Patterns to Watch:**
```
[market-regime-gate] BLOCK | REDUCE | ALLOW
[WS-BRIDGE] Order update: ...
```

**Checks:**
- [ ] Market regime gate allows entries (basket not too flat)
- [ ] WebSocket bridge receives order updates from Kalshi
- [ ] Order status transitions: submitted → working → filled/partial/cancelled
- [ ] Execution latency < 5 seconds from decision to submission

**Red Flags:**
- Market regime gate blocking all entries (basket too flat, may need adjustment)
- WebSocket bridge not receiving order updates (connection issue)
- Orders stuck in "submitted" state for > 30 seconds (Kalshi API issue)

---

### 6. Dashboard Health

**Grafana Dashboards to Monitor:**
- `merid_15m_pipeline_health` → Agent health, catalog refresh, spot feed
- `merid_risk_safety` → Risk envelope, exposure, kill switches
- `merid_pnl_exposure` → Realized/unrealized PnL, bankroll reconciliation

**Checks:**
- [ ] Pipeline health: All agents green, catalog refreshing, spot feed alive
- [ ] Risk safety: Exposure within limits, no kill switches active
- [ ] PnL exposure: Bankroll tracking, PnL updating, reconciliation delta small

**Red Flags:**
- Agent health red (crashed or stuck)
- Catalog refresh failing (market discovery broken)
- Spot feed stale (price data not updating)
- Exposure approaching limits (risk envelope too tight)
- Kill switch active (safety trigger fired)

---

## Post-Run Documentation

### First-Fill Report Template

After observing the first complete entry+exit cycle, document:

**Entry Order:**
- Ticker: `KX____-26MAY____-15`
- Side: YES/NO
- Count: ___ contracts
- Price: ___¢
- Notional: $___
- Model probability: ___
- Implied probability: ___
- Edge: ___%
- Confidence: ___
- Time to expiry: ___ min
- Kalshi order ID: `_____`
- Submission latency: ___ ms
- Fill latency: ___ ms

**Exit Order:**
- Ticker: `KX____-26MAY____-15`
- Side: YES/NO
- Count: ___ contracts
- Price: ___¢
- Notional: $___
- Exit trigger: (take-profit / stop-loss / expiry)
- Kalshi order ID: `_____`
- Submission latency: ___ ms
- Fill latency: ___ ms

**Cycle PnL:**
- Entry cost: $___
- Exit proceeds: $___
- Fees: $___
- Net PnL: $___
- PnL %: ___%

**System Behavior:**
- Any risk controls fired? (yes/no, which)
- Any reconciliation alerts? (yes/no, which)
- Any dashboard anomalies? (yes/no, which)
- Overall system health: (excellent / good / fair / poor)

---

## Escalation Criteria

**Immediate Action Required If:**
- Kill switch triggered (stop trading, investigate)
- Reconciliation delta > $10.00 (stop trading, investigate)
- Orders failing Kalshi API consistently (check credentials/rate limits)
- Exposure approaching 90% of limits (consider manual intervention)
- WebSocket bridge disconnected for > 5 minutes (check network)

**Investigate Within 10 Minutes If:**
- No orders submitted for 30+ minutes despite edge opportunities
- Fills not appearing in fills_ledger within 60 seconds
- Dashboard metrics not updating (stale data)
- Agent health red (crashed agent)

---

## Contact Information

**On-Call**: [TBD]
**Engineering**: [TBD]
**Risk**: [TBD]

**Emergency Stop**: Kill all trading via `MERID_ALLOW_LIVE_TRADES=false` in `.env` and restart server.

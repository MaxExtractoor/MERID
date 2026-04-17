# EXPIRY_LEDGER_INVARIANTS.md

**Purpose:** Document ledger consistency invariants for expiry chaos scenarios, including restart behavior, mismatch detection, and reconciliation procedures.

**Part of:** Kalshi Expiry Chaos Audit (see `EXPIRY_CHAOS_TEST_PLAN.md`)

---

## 1. Ledger Invariant Overview

During the final minutes of RTI-settled market expiry, the following invariants must hold regardless of system restarts or failures:

| Invariant ID | Description | Violation Impact | Detection Method |
|--------------|-------------|------------------|----------------|
| LI-1 | **No ghost trades**: Every recorded trade has a corresponding venue order ID | Double counting, phantom positions | Order ID reconciliation log |
| LI-2 | **Settlement-price alignment**: Final ledger position values use actual settlement price | Incorrect PnL, phantom profits | Post-settlement audit |
| LI-3 | **No position resurrection**: Closed positions cannot reappear after restart | Risk exposure miscalculation | Position hash verification |
| LI-4 | **Consistent exposure**: Pre- and post-restart total exposure must match within tolerance | Capital misallocation | Exposure checksum |
| LI-5 | **Settlement timestamp integrity**: Settlement time cannot be earlier than last known trade | Time-travel arbitrage | Timestamp monotonicity check |

---

## 2. Restart Behavior During Expiry Window

### 2.1 Restart Scenarios

| Scenario | Time Window | Expected Behavior | Risk Level |
|----------|-------------|-------------------|------------|
| Clean shutdown during T-5m to T-60s | 5-1 min before expiry | Agent enters DRAINING → stop accepting signals → flush pending orders → record checkpoint | Low |
| Clean shutdown during T-60s to expiry | Final 60 seconds | **CRITICAL**: Emergency close all positions via market orders, record final checkpoint, do not restart until after settlement | **HIGH** |
| Abrupt failure during T-5m to T-60s | 5-1 min before expiry | Recovery from last checkpoint, verify position state with venue, resume if < 90s to expiry | Medium |
| Abrupt failure during T-60s to expiry | Final 60 seconds | **CRITICAL**: Block auto-restart, alert operator, manual verification required before any trading | **HIGH** |
| Post-settlement restart | After expiry | Full reconciliation with settlement data, verify all positions closed correctly | Low |

### 2.2 Restart Checkpoint Data

Every 30 seconds during the expiry window (T-5m to T+1m), the following must be snapshotted:

```python
EXPIRY_CHECKPOINT = {
    "timestamp_utc": "2025-01-15T14:59:45.123Z",
    "market_id": "KXBTC-20250115-15M",
    "seconds_to_expiry": 15.0,
    "positions": {
        "long_contracts": 10,
        "short_contracts": 0,
        "avg_entry_cents": 4850
    },
    "pending_orders": [
        {
            "order_id": "ord_abc123",
            "side": "sell",
            "count": 10,
            "status": "pending"
        }
    ],
    "settlement_buffer_filled": 58,  # 58/60 RTI slots
    "checksum": "sha256_of_above"
}
```

---

## 3. Mismatch Detection Procedures

### 3.1 Venue-to-Ledger Reconciliation

**Trigger:** Every restart, every 60s during expiry window

**Procedure:**
```python
async def reconcile_venue_ledger(market_id: str) -> ReconciliationResult:
    venue_positions = await fetch_venue_positions(market_id)
    ledger_positions = get_ledger_positions(market_id)
    
    # LI-3: Position resurrection check
    if ledger_positions.is_closed() and venue_positions.is_open():
        raise PositionResurrectionError(
            f"Closed position {market_id} found open on venue"
        )
    
    # LI-4: Exposure consistency
    ledger_exposure = ledger_positions.total_contracts()
    venue_exposure = venue_positions.total_contracts()
    
    if abs(ledger_exposure - venue_exposure) > TOLERANCE:
        raise ExposureMismatchError(
            f"Exposure mismatch: ledger={ledger_exposure}, venue={venue_exposure}"
        )
    
    # LI-1: Order ID reconciliation
    venue_orders = set(o.id for o in venue_positions.orders)
    ledger_orders = set(o.id for o in ledger_positions.orders)
    
    ghost_orders = ledger_orders - venue_orders
    if ghost_orders:
        raise GhostOrderError(f"Orders in ledger not on venue: {ghost_orders}")
```

### 3.2 Settlement Price Verification

**Trigger:** Within 60 seconds of settlement announcement

**LI-2 Enforcement:**
```python
def verify_settlement_price(
    market_id: str,
    ledger_settlement_price: Decimal,
    venue_announced_price: Decimal,
    rti_buffer_data: List[Decimal]
) -> bool:
    """Verify that settlement price matches RTI methodology."""
    
    # Calculate expected settlement from RTI buffer
    expected = calculate_rti_average(rti_buffer_data)
    
    # Allow 1-cent tolerance for rounding
    if abs(ledger_settlement_price - expected) > 1:
        raise SettlementPriceMismatch(
            f"Ledger {ledger_settlement_price} != calculated {expected}"
        )
    
    if abs(venue_announced_price - expected) > 1:
        raise SettlementPriceMismatch(
            f"Venue {venue_announced_price} != calculated {expected}"
        )
    
    return True
```

### 3.3 Timestamp Monotonicity (LI-5)

```python
def verify_timestamp_monotonicity(
    settlement_time: datetime,
    last_trade_time: datetime,
    market_id: str
) -> bool:
    """Ensure settlement time is not earlier than last trade."""
    
    if settlement_time < last_trade_time:
        raise TimestampViolationError(
            f"Settlement {settlement_time} < last trade {last_trade_time} for {market_id}"
        )
    
    return True
```

---

## 4. Reconciliation Actions by Violation Type

| Violation | Immediate Action | Escalation | Audit Trail |
|-----------|-----------------|------------|-------------|
| Ghost Order (LI-1) | Mark order as orphaned, exclude from PnL calculation | Alert operator within 60s | Full order lifecycle export |
| Settlement Mismatch (LI-2) | Freeze position, manual verification required | Page on-call immediately | RTI buffer dump, settlement API response |
| Position Resurrection (LI-3) | Emergency halt agent, manual position audit | Immediate operator intervention | Last 5 checkpoints + venue state |
| Exposure Mismatch (LI-4) | Block new orders, reconcile per-position | Alert within 30s | Exposure diff report |
| Timestamp Violation (LI-5) | Flag for audit, do not use for PnL | Daily batch report | Timeline reconstruction |

---

## 5. Chaos Scenario Ledger Invariants

### Scenario C5: Process Restart During Final Minute

See `EXPIRY_CHAOS_TEST_PLAN.md` Scenario C5.

**Invariant Requirements:**

| Phase | Invariant | Verification Method |
|-------|-----------|---------------------|
| T-30s (pre-kill) | LI-4: Record exact exposure | Snapshot to disk + checksum |
| T-20s (kill) | LI-3: All positions marked with close intent | Position intent metadata |
| T-0s to T+30s (recovery) | LI-1, LI-2: Reconcile against venue | Full reconciliation procedure |
| Post-recovery | All invariants | Automated audit run |

**Recovery Steps:**
1. Read last checkpoint (should be within 30s of kill)
2. Query venue for current position state
3. Run full reconciliation (LI-1 through LI-5)
4. If any mismatch: BLOCK, alert operator, manual fix
5. If match: Resume trading only if > 90s to next expiry

### Scenario C6: Clock Skew During Expiry

See `EXPIRY_CHAOS_TEST_PLAN.md` Scenario C6.

**Invariant Adaptations:**

| Skew Direction | Impact | Invariant Adjustment |
|----------------|--------|---------------------|
| System clock ahead (thinks it's later) | Premature expiry blocking | Use NTP-synchronized time source, max skew 5s |
| System clock behind (thinks it's earlier) | Late expiry detection | Cross-reference with venue timestamp, abort if > 10s diff |

**Clock Skew Detection:**
```python
async def detect_clock_skew() -> Optional[float]:
    """Detect clock skew between system and Kalshi venue."""
    venue_time = await fetch_kalshi_server_time()
    system_time = datetime.now(timezone.utc)
    skew = (system_time - venue_time).total_seconds()
    
    if abs(skew) > 10:  # 10 second threshold
        logger.error(f"Critical clock skew detected: {skew:.1f}s")
        return skew
    elif abs(skew) > 5:  # 5 second warning
        logger.warning(f"Clock skew warning: {skew:.1f}s")
    
    return None
```

---

## 6. Go/No-Go Ledger Criteria

Before any expiry-adjacent trading session:

| Criterion | Check | Pass/Fail |
|-----------|-------|-----------|
| Checkpoint write verified | Last checkpoint within 60s, checksum valid | PASS |
| Venue API accessible | Can fetch positions and orders | PASS |
| Reconciliation clean | Last run within 5m, zero mismatches | PASS |
| NTP sync verified | Skew < 5s | PASS |
| Settlement buffer operational | Filling RTI slots correctly | PASS |

If any criterion **FAILS**: Block trading, alert operator, fix before resuming.

---

## 7. Implementation Checklist

- [ ] Implement checkpoint serialization every 30s during expiry window
- [ ] Implement `reconcile_venue_ledger()` procedure
- [ ] Implement ghost order detection in settlement pipeline
- [ ] Add settlement price verification post-settlement
- [ ] Add timestamp monotonicity checks
- [ ] Implement clock skew detection and alerting
- [ ] Create automated reconciliation job (runs every 60s)
- [ ] Add operator alert integration for all violation types
- [ ] Create manual recovery runbook
- [ ] Test all scenarios from `EXPIRY_CHAOS_TEST_PLAN.md`

---

## 8. Related Documents

- `KALSHI_RTI_SETTLEMENT_WINDOW_REFERENCE.md` — RTI settlement rules
- `EXPIRY_BEHAVIOR_MAP.md` — Current system behavior
- `EXPIRY_CHAOS_TEST_PLAN.md` — Test scenarios
- `EXPIRY_CHAOS_GO_NO_GO.md` — Readiness checklist (this doc)

---

*Document Version: 1.0*
*Last Updated: 2025-01-26*
*Part of: Kalshi Expiry Chaos Audit*

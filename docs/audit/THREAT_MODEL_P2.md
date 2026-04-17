# Threat Model: Remaining P2 Wiring Items

**Scope:** Warm-up dry-run mode and Partial-fill price tracking  
**Context:** MERID Kalshi trading pipeline (DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE)  
**Status:** Post-audit wiring fixes; evaluating whether to promote to P1 before scale-up

---

## P2 Item 1: Warm-Up Dry-Run Mode

### Current State
- `trading_agent.py:1355-1362` - WARMING_UP phase skips execution entirely
- Risk checks in `kalshi_risk.py` are NOT exercised during warm-up
- Comment notes: "BUG-L8: skip execution entirely during WARMING_UP phase"

### Threat: Mode Confusion (Primary)

**Description:** Any path where dry-run/warm-up behavior can leak into live trading or vice versa.

#### Attack Scenarios

| ID | Scenario | Likelihood | Impact | Risk Score |
|----|----------|------------|--------|------------|
| WM-1 | Lifecycle state corruption: Agent stuck in WARMING_UP after intended transition to ACTIVE | Medium | High - Risk checks never run | **P1** |
| WM-2 | Dual-mode execution: Partial code path thinks it's warming up, partial thinks live | Low | Critical - Undefined behavior | **P1** |
| WM-3 | Silent warm-up bypass: Config/environment forces instant ACTIVE without proper initialization | Medium | High - Untested risk paths hit production | **P1** |
| WM-4 | Warm-up duration manipulation: Attacker with config access extends warm-up indefinitely to blind risk system | Low | Medium - DoS on trading | **P2** |

#### Mode Confusion Vectors

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MODE CONFUSION ATTACK TREE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [Goal: Execute live trades with untested risk code paths]                  │
│                                                                             │
│  ├───[State Corruption]─────────────────────────────────────────────┐      │
│  │   │                                                               │      │
│  │   ├─── Database/file corruption → lifecycle state stuck           │      │
│  │   │   └── Mitigation: In-memory state machine with checkpoints     │      │
│  │   │                                                               │      │
│  │   └─── Race condition during state transition                    │      │
│  │       └── Mitigation: Atomic state updates with validation        │      │
│  │                                                                   │      │
│  ├───[Environment Manipulation]──────────────────────────────────────┤      │
│  │   │                                                               │      │
│  │   ├─── MERID_WARMUP_SECONDS=0 bypasses intended warm-up          │      │
│  │   │   └── Mitigation: Minimum enforced warm-up (30s floor)        │      │
│  │   │                                                               │      │
│  │   └─── MERID_FORCE_LIVE=true forces ACTIVE regardless of health   │      │
│  │       └── Mitigation: Remove kill-switch override capability      │      │
│  │                                                                   │      │
│  └───[Code Path Confusion]────────────────────────────────────────────┤      │
│      │                                                               │      │
│      ├─── Partial risk check execution (some checks warm-up, some live)│    │
│      │   └── Mitigation: Unified is_live() predicate everywhere     │      │
│      │                                                               │      │
│      └─── Implicit warm-up bypass via exception handling              │      │
│          └── Mitigation: Explicit warm-up gating, no exceptions      │      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Threat: Latent Risk Path Activation (Secondary)

**Description:** Risk checks work in isolation but fail when first called in production due to:
- Cold-start database connection timeouts
- Uninitialized singleton dependencies
- Cache warming races
- External API (Kalshi) rate limits on first burst of requests

**Evidence from current code:**
```python
# trading_agent.py:1355-1362
if self.state.lifecycle == LifecycleState.WARMING_UP:
    self.logger.debug(
        "WARMING_UP: signal logged but execution skipped for %s",
        market.market_id,
    )
    _execution_skipped_warmup += 1
    continue  # ← Risk checks below this line never execute during warm-up

# Risk checks (check_stop_losses, risk_manager.check_order, etc.)
# are BELOW this line and never exercised during warm-up
```

### Recommended Hardening (Before Promoting to P1)

| Item | Implementation | Validation |
|------|----------------|------------|
| Minimum enforced warm-up | `max(env_warmup, 30)` seconds | Unit test |
| No execution without risk validation | Add `risk_check_warmup()` that runs same checks but doesn't trade | E2E test |
| Lifecycle state persistence | Write state to disk, verify on restart | Integration test |
| State transition logging | Log every lifecycle change to audit chain | Audit verification |
| Dual-mode detection | Assert no code path uses both `is_warming_up()` and `is_live()` | Static analysis |

### Promotion Recommendation

**Promote to P1 if:**
- [ ] Any warm-up bypass incident occurs in staging
- [ ] Risk check cold-start failure observed
- [ ] Lifecycle state corruption detected

**Keep at P2 if:**
- [x] No incidents in first 100 cycles of warm-up
- [x] All risk paths exercised in staging dry-run
- [x] State transitions logged and verified

---

## P2 Item 2: Partial-Fill Price Tracking

### Current State
- `order_router.py:1209-1221` - Releases unfilled notional at `fill_price_cents`
- BUG comment: "PARTIAL FILL: Release reserved exposure for UNFILLED portion"
- Current: `_unfilled_notional = _unfilled * fill_price_cents / 100.0`
- Issue: Uses actual fill price, not original reservation price

### Threat: Exposure Accounting Drift

**Description:** Category exposure caps become inconsistent because:
1. Reserve notional at price X when order submitted
2. Fill occurs at price Y (market moved)
3. Release unfilled at price Y
4. Actual position: filled contracts at Y
5. **Drift:** Reserved vs actual notional differ by (Y-X) * unfilled

#### Attack Scenarios

| ID | Scenario | Likelihood | Impact | Risk Score |
|----|----------|------------|--------|------------|
| PF-1 | Fast market: Price moves >5% between reservation and fill | Medium (volatile assets) | Medium - Category cap overrun by 5% | **P1** |
| PF-2 | Partial fill cascade: Multiple partials at different prices accumulate drift | High | High - 10-20% cap overrun possible | **P1** |
| PF-3 | Adversarial latency: Delayed fills exploited to game exposure system | Low | Medium - Intentional cap avoidance | **P2** |
| PF-4 | Reconciliation failure: End-of-day position notional ≠ sum of release records | Medium | High - Audit/compliance failure | **P1** |

#### Exposure Drift Calculation

```python
# Current (problematic) implementation
_reserved_notional = intent.count * intent.price_cents / 100.0  # At reservation
_filled_notional = filled_count * fill_price_cents / 100.0       # At fill price
_unfilled_notional = _unfilled * fill_price_cents / 100.0        # ← WRONG: should use intent.price_cents

# Actual exposure after partial fill:
# - Filled: filled_count contracts at fill_price_cents
# - Reserved tracking shows: (intent.count - filled_count) * fill_price_cents
# - True remaining: (intent.count - filled_count) * intent.price_cents

# Drift per partial fill:
_drift = _unfilled * abs(fill_price_cents - intent.price_cents) / 100.0
```

### Threat: Fill Ordering Ambiguity

**Description:** When multiple partial fills arrive out of order or with same timestamp, which price is "correct" for exposure tracking?

**Evidence:**
```python
# order_router.py:1177-1180
requested_count = int(placed.size)
filled_count = int(placed.filled_size)
remaining_count = int(placed.remaining_size) if placed.remaining_size is not None else max(0, requested_count - filled_count)

# No tracking of WHICH fills contributed to filled_count
# If multiple partial fills, we lose per-fill price attribution
```

### Recommended Hardening (Before Promoting to P1)

| Item | Implementation | Validation |
|------|----------------|------------|
| Track original reservation price | Store `reservation_price_cents` in OrderIntent | Unit test |
| Release at reservation price | `_unfilled_notional = _unfilled * intent.reservation_price_cents / 100.0` | Property test |
| Per-fill price attribution | Log each fill with its price to audit chain | Audit verification |
| Drift detection | Alert if `abs(released_notional - actual_position_notional) > threshold` | Monitoring |
| EOD reconciliation | Daily job: `sum(releases) == current_position_notional` | Reconciliation test |

### Promotion Recommendation

**Promote to P1 if:**
- [ ] Category cap overrun >5% observed in staging
- [ ] Partial fills on volatile assets (DOGE 15m, SOL 15m) exceed 20% of orders
- [ ] EOD reconciliation fails in any test

**Keep at P2 if:**
- [x] All partial fills <10% of order count in first week
- [x] Price drift <2% between reservation and fill (avg)
- [x] EOD reconciliation passes 7 consecutive days

---

## Combined Systemic Risk Assessment

### Interaction Between P2 Items

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      COMPOUND THREAT: Warm-Up + Partial Fills               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Scenario:                                                                  │
│  1. System restarts, enters WARMING_UP                                      │
│  2. First orders submitted (risk checks bypassed due to warm-up skip)       │
│  3. Orders get partial fills at prices far from reservation               │
│  4. Exposure tracking drifts due to price mismatch                        │
│  5. System transitions to ACTIVE with WRONG exposure baseline             │
│  6. Subsequent risk checks use tainted exposure → over-trading              │
│                                                                             │
│  Result: Warm-up bypass + partial fill drift = Compounded position risk    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Pre-Scale-Up Validation

Before increasing position sizing:

1. **Force warm-up dry-run mode for 7 days**
   - Log all risk checks that WOULD have fired
   - Compare to actual production risk events
   - Validate coverage: >95% of risk paths exercised

2. **Partial fill stress test**
   - Simulate 50% partial fill rate on DOGE 15m
   - Track exposure drift minute-by-minute
   - Validate EOD reconciliation within 1%

3. **Combined failure injection**
   - Restart during high volatility
   - Partial fills + price jumps during warm-up
   - Measure recovery time to consistent state

### Decision Matrix

| Warm-Up Dry-Run | Partial Fill Fix | Combined Risk | Recommendation |
|-----------------|------------------|---------------|----------------|
| Not implemented | Not implemented | **Critical** | Do not scale until both P1 |
| Implemented | Not implemented | **High** | Scale cautiously, partial fills P1 |
| Not implemented | Implemented | **High** | Scale cautiously, warm-up P1 |
| Implemented | Implemented | **Low** | Safe to scale |

---

## Appendix: Threat Modeling References

- [OWASP Threat Modeling](https://owasp.org/www-project-threat-dragon/)
- [Microsoft STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats)
- [Kalshi Market Integrity](https://kalshi.com/market-integrity)
- [NIST 800-30 Risk Assessment](https://csrc.nist.gov/publications/detail/sp/800-30/rev-1/final)

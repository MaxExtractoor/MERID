# CT Canary Rollout Runbook

## Overview
Gradual migration of KalshiContinuousTrader from direct HTTP to canonical router.

## Environment Variable
```bash
CT_USE_ROUTER_PERCENT=0    # HTTP only (Phase 1 - shadow)
CT_USE_ROUTER_PERCENT=10   # 10% router, 90% HTTP (Phase 2 - canary start)
CT_USE_ROUTER_PERCENT=50   # 50/50 split (Phase 2 - mid ramp)
CT_USE_ROUTER_PERCENT=100  # Router only (Phase 3 - complete)
```

## Phase 1: Shadow Mode (Current)
**Config:** `CT_USE_ROUTER_PERCENT=0`

**Validation:**
```bash
# Check shadow parity logs
grep "\[CT-ADAPTER\] parity" /var/log/merid/kalshi_ct.log

# Expected: parity comparisons logged, no live impact
```

**Duration:** 1 week minimum

**Go/No-Go Criteria:**
- [ ] Parity rate > 95% (HTTP vs router fill status matches)
- [ ] No unexpected router rejections
- [ ] Shadow latency acceptable (< 2x HTTP latency)

---

## Phase 2: Canary Ramp

### Step 2.1: Initial Canary (10%)
**Config:** `CT_USE_ROUTER_PERCENT=10`

**Monitoring:**
```bash
# Watch routing decisions
grep "\[AUDIT\] ct_route_decision" /var/log/merid/kalshi_ct.log | tail -20

# Check router path success
grep "\[CT-CANARY\] Routed via canonical router" /var/log/merid/kalshi_ct.log

# Watch for fallback events (router failure -> HTTP)
grep "Router execution failed, falling back" /var/log/merid/kalshi_ct.log
```

**Duration:** 2-3 days

**Go/No-Go Criteria:**
- [ ] Router path success rate > 99%
- [ ] Fallback rate < 1%
- [ ] No PnL divergence vs HTTP path
- [ ] No increase in failed orders

**Rollback:**
```bash
export CT_USE_ROUTER_PERCENT=0
# No restart required - takes effect next cycle
```

### Step 2.2: Mid Ramp (50%)
**Config:** `CT_USE_ROUTER_PERCENT=50`

**Same monitoring as 2.1**

**Duration:** 3-5 days

### Step 2.3: High Ramp (90%)
**Config:** `CT_USE_ROUTER_PERCENT=90`

**Duration:** 2-3 days

---

## Phase 3: Completion (100%)
**Config:** `CT_USE_ROUTER_PERCENT=100`

**Duration:** 1 week minimum at 100% before cleanup

**Final Validation:**
- [ ] 7+ days stable at 100%
- [ ] No HTTP fallback events in logs
- [ ] All fills attributed to router path
- [ ] Parity comparison logs confirm consistency

---

## Phase 3: Code Cleanup (One-time)

After 1+ week stable at 100%:

1. **Delete HTTP path from CT:**
   - Remove `self._post("/portfolio/orders")` block
   - Remove `_build_synthetic_response()` helper
   - Remove shadow mode code paths

2. **Update documentation:**
   - `AGENT_WIRING_AUDIT.md` — mark Section 7 "EMPTY"
   - `.ci/venue_touchpoint_whitelist.txt` — remove CT bypass entry

3. **Update tests:**
   - `test_only_one_documented_bypass_exists` — change to enforce `== 0`
   - Remove CT from `_KNOWN_BYPASS_PATHS`

4. **Update status tool:**
   - `show_wiring_status.py` — show "[EMPTY]" bypass list

---

## Quick Reference: Log Patterns

| Pattern | Meaning |
|---------|---------|
| `[AUDIT] ct_route_decision \| routed_via=router` | Order went through canonical router |
| `[AUDIT] ct_route_decision \| routed_via=http` | Order went through direct HTTP |
| `[CT-CANARY] Routed via canonical router` | Router path successful |
| `Router execution failed, falling back` | Router failed, HTTP fallback used |
| `[CT-ADAPTER] parity \| match=True` | HTTP and router results aligned |
| `[CT-ADAPTER] parity \| match=False` | HTTP and router diverged (investigate) |

---

## Emergency Procedures

### Complete Rollback to HTTP
```bash
# Instant kill switch
export CT_USE_ROUTER_PERCENT=0

# Verify
python scripts/show_wiring_status.py
# Should show: Phase 2 [IMPLEMENTED] with pct=0 effectively
```

### Investigate Parity Mismatch
```bash
# Find mismatches
grep "PARITY_MISMATCH" /var/log/merid/kalshi_ct.log

# Check specific ticker
grep "ticker=KXBTC" /var/log/merid/kalshi_ct.log | grep "parity"
```

### Check Router Health
```bash
# Router caller audit
grep "\[AUDIT\] caller_check" /var/log/merid/order_router.log | tail -20
```

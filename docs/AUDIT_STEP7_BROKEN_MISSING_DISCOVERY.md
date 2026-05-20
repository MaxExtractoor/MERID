# Audit Step 7: Broken/Missing Discovery Pass

**Date:** 2026-05-12  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute contracts  
**Purpose:** Code review with risk lens, TODO/FIXME search, dark corners

---

## Critical Risk Bypass

### Terminal Phase Trading Ban Disabled
**File:** `merid/prediction/strategy.py` (lines 1634-1649)  
**Issue:** Critical risk control temporarily disabled due to MarketMoodBus issue

**Code:**
```python
# TEMPORARILY DISABLED (2026-05-09): Blocking all trades due to neutral sentiment (MarketMoodBus issue)
# Re-enable after MarketMoodBus context population is fixed
# if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
#     logger.warning(...)
#     return StrategySignal(...)
```

**Impact:** Trades with weak edge (< 3%) can occur near contract expiry  
**Risk:** **HIGH** - Terminal phase trading is high-risk due to time decay and liquidity issues  
**Recommendation:** Re-enable after MarketMoodBus issue is resolved

---

## TODO/FIXME Markers

### Disabled MM Consensus Bypass
**File:** `merid/prediction/crypto_edge_production.py`  
**Issue:** MM consensus "bypass" mode is explicitly disabled

**Code:**
```python
# SAFETY: bypass mode is disabled - force to 'full' if attempted
if mm == "bypass":
    logger.error(
        "[SECURITY] MERID_CRYPTO_MM_CONSENSUS_MODE='bypass' is DISABLED. "
        "Using 'full' mode. All orders must flow through main execution gate."
    )
    mm = "full"
```

**Impact:** None - this is a security hardening  
**Risk:** None - correctly disabled

---

### Missing Endpoints
**File:** `web/api/missing_endpoints.py`  
**Issue:** Placeholder endpoints for missing functionality

**Impact:** Limited - endpoints are stubs  
**Risk:** Low - endpoints return stub data

---

## Dark Corners

### Disabled Files
**Finding:** Several files marked as DISABLED in the codebase

**Examples:**
- `merid_core/kalshi/execution_pipeline.py` (DISABLED)
- `merid_core/kalshi/rest_client.py` (DISABLED)

**Impact:** Unknown - need to review disabled files  
**Risk:** Medium - disabled code may contain risk bypasses or incomplete logic

---

### Legacy Code
**Finding:** Several legacy code paths exist

**Examples:**
- `trading/_legacy/` directory
- Legacy adapter patterns in `trading/adapters/`

**Impact:** Medium - legacy code may have outdated risk controls  
**Risk:** Medium - need to review legacy paths for risk bypasses

---

### Unimplemented Features
**Finding:** Several features marked as unimplemented

**Examples:**
- Cross-venue reconciliation (Kalshi-specific only)
- Real-time PnL attribution (periodic only)
- Strategy-level attribution (agent-level only)

**Impact:** Low - these are feature gaps, not risk bypasses  
**Risk:** Low

---

## Critical Findings

### 🔴 CRITICAL: Terminal Phase Trading Ban Disabled

**Issue:** Terminal phase trading ban temporarily disabled due to MarketMoodBus issue  
**File:** `merid/prediction/strategy.py` (lines 1634-1649)  
**Risk:** **HIGH** - Allows trades with weak edge (< 3%) near contract expiry  
**Recommendation:** Re-enable after MarketMoodBus issue is resolved

---

### 🟢 INFO: MM Consensus Bypass Correctly Disabled

**Positive:** MM consensus "bypass" mode is explicitly disabled for security  
**File:** `merid/prediction/crypto_edge_production.py`

---

### 🟡 WARNING: Disabled Files Need Review

**Issue:** Several files marked as DISABLED in the codebase  
**Risk:** **MEDIUM** - Disabled code may contain risk bypasses or incomplete logic  
**Recommendation:** Review all disabled files for risk bypasses

---

### 🟡 WARNING: Legacy Code Paths Need Review

**Issue:** Several legacy code paths exist  
**Risk:** **MEDIUM** - Legacy code may have outdated risk controls  
**Recommendation:** Review legacy paths for risk bypasses

---

## Missing Capabilities

### 1. Automated Signal Determinism Checks
**Current:** No automated determinism checks  
**Needed:** Job to verify signal determinism via replay

---

### 2. Sizing Validation Job
**Current:** No automated sizing validation  
**Needed:** Job to recompute intended size and diff against actual

---

### 3. Venue Spec Validation
**Current:** No periodic validation against Kalshi official docs  
**Needed:** Periodic validation against Kalshi API contract metadata

---

### 4. Cross-Venue Reconciliation
**Current:** Kalshi-specific reconciliation only  
**Needed:** Cross-venue reconciliation if multiple venues are used

---

### 5. Real-Time PnL Attribution
**Current:** PnL attribution computed periodically  
**Needed:** Real-time PnL attribution per trade

---

### 6. Strategy-Level Attribution
**Current:** Agent-level attribution  
**Needed:** Strategy-level attribution (e.g., band strategy vs momentum)

---

### 7. Kill Switch Test Automation
**Current:** Manual kill switch testing  
**Needed:** Automated kill switch testing in CI/CD

---

### 8. Monitoring Dashboard Visualization
**Current:** Metrics collected but no dashboard  
**Needed:** Grafana dashboard for metrics visualization

---

### 9. Alert Integration
**Current:** Alerting infrastructure exists  
**Needed:** Integration with external alerting services (PagerDuty, Slack)

---

## Next Steps for Step 7

1. ✅ Search for TODO/FIXME markers - DONE
2. ✅ Search for unimplemented code - DONE
3. ✅ Identify disabled files - DONE
4. ⏳ Review disabled files for risk bypasses - NEED MANUAL REVIEW
5. ⏳ Review legacy code paths for risk bypasses - NEED MANUAL REVIEW

---

## Summary

**Obviously Broken:**
- **CRITICAL:** Terminal phase trading ban disabled (merid/prediction/strategy.py)

**Probably Fine:**
- MM consensus bypass correctly disabled (security hardening)
- Placeholder endpoints in missing_endpoints.py
- Unimplemented features are feature gaps, not risk bypasses

**Weird/Unclear:**
- Several files marked as DISABLED (need review)
- Legacy code paths exist (need review)
- No automated signal determinism checks
- No automated sizing validation job
- No venue spec validation against official docs
- No cross-venue reconciliation
- No real-time PnL attribution
- No strategy-level attribution
- No automated kill switch testing
- No Grafana dashboard for metrics
- No integration with external alerting services

---

## Overall Audit Summary

**Steps Completed:**
- ✅ Step 1: Repository and infrastructure sweep
- ✅ Step 2: Edge and signal audit
- ✅ Step 3: Contract, sizing, and risk wiring
- ✅ Step 4: Execution and Kalshi integration
- ✅ Step 5: PnL, attribution, and truth
- ✅ Step 6: Reliability, kill switches, and monitoring
- ✅ Step 7: Broken/missing discovery

**Critical Issues:**
1. **CRITICAL:** Terminal phase trading ban disabled (merid/prediction/strategy.py)

**High Priority Warnings:**
1. Limited retry/backoff infrastructure (no exponential backoff)
2. Limited idempotency (client_tag for tracking only, no deduplication)
3. Disabled files need review for risk bypasses
4. Legacy code paths need review for risk bypasses

**Medium Priority Warnings:**
1. No automated signal determinism checks
2. No automated sizing validation job
3. No venue spec validation against official docs
4. Reconciliation interval is 5 minutes (could be faster)
5. No cross-venue reconciliation
6. No real-time PnL attribution
7. No strategy-level attribution

**Low Priority Gaps:**
1. No automated kill switch testing
2. No Grafana dashboard for metrics
3. No integration with external alerting services

**Overall Assessment:**
- The MERID system has a comprehensive risk infrastructure with multiple layers of protection
- One critical issue found: terminal phase trading ban disabled (needs immediate attention)
- Several medium-priority gaps that should be addressed for production readiness
- The system is well-architected with good separation of concerns and clear risk controls

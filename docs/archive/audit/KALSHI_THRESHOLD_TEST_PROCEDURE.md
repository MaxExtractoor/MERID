# Kalshi 15m Crypto Threshold Test Procedure

**SPEC_VERSION:** 1.0.0  
**Date:** 2026-05-16  
**Purpose:** Validate risk threshold behavior (80/90/100%) in controlled environment

## Overview

This procedure validates that the Kalshi 15m crypto risk infrastructure behaves as specified when approaching and breaching exposure thresholds. This is a **manual operational test** that must be performed in a sandbox environment or small production account.

## Prerequisites

- Sandbox Kalshi account or very small production account (minimal capital at risk)
- Kalshi 15m crypto stack running in test environment
- Access to risk metrics dashboard
- Access to gate state monitoring
- Screenshot capability for evidence collection
- Log access for post-test analysis

## Test Environment Setup

1. **Environment Selection**
   - Use sandbox subaccount: `--subaccount 0` (or designated test subaccount)
   - Verify profile: `MERID_PROFILE=kalshi_crypto_15m_v2`
   - Verify risk limits loaded from profile config

2. **Baseline Verification**
   - Confirm zero positions before test
   - Confirm gate state: `OPEN`
   - Confirm no active discrepancies
   - Capture baseline metrics screenshot

## Test Procedure

### Phase 1: 80% Threshold Approach

**Objective:** Observe behavior when approaching 80% exposure limit

1. Place tiny orders to reach 75-80% of exposure limit
   - Use minimum contract size (1 contract)
   - Target asset: BTC_15M (most liquid)
   - Monitor exposure in real-time

2. **Expected Behavior:**
   - Gate state remains `OPEN`
   - Risk measurements show approaching limit
   - No reduction-only mode triggered
   - Orders continue to route normally

3. **Capture Evidence:**
   - Screenshot: Risk metrics at 80%
   - Screenshot: Gate state (should be OPEN)
   - Log snippet: Risk check output
   - Log snippet: Order routing confirmation

### Phase 2: 90% Threshold Breach

**Objective:** Observe behavior when crossing 90% exposure limit

1. Place additional orders to cross 90% exposure limit
   - Incremental exposure: 85% → 92%
   - Use minimum contract size

2. **Expected Behavior:**
   - Gate state transitions to `LIMITED`
   - Risk measurements show breach
   - New orders blocked or reduced-only mode active
   - Alert triggered (if configured)

3. **Capture Evidence:**
   - Screenshot: Risk metrics at 92%
   - Screenshot: Gate state (should be LIMITED)
   - Log snippet: Gate state transition
   - Log snippet: Order rejection or reduction
   - Alert notification (if any)

### Phase 3: 100% Threshold Breach

**Objective:** Observe kill-switch behavior at 100% exposure limit

1. Place additional orders to cross 100% exposure limit
   - Incremental exposure: 92% → 105%
   - Use minimum contract size

2. **Expected Behavior:**
   - Gate state transitions to `BLOCKED`
   - All orders blocked
   - Kill-switch triggered (if configured)
   - Critical alert triggered

3. **Capture Evidence:**
   - Screenshot: Risk metrics at 105%
   - Screenshot: Gate state (should be BLOCKED)
   - Log snippet: Kill-switch activation
   - Log snippet: All orders blocked
   - Alert notification (critical)

### Phase 4: Recovery

**Objective:** Observe behavior when exposure drops below thresholds

1. Reduce exposure by exiting positions
   - Exit positions to return to 70% exposure
   - Monitor gate state transitions

2. **Expected Behavior:**
   - Gate state transitions: `BLOCKED` → `LIMITED` → `OPEN`
   - Orders resume routing normally
   - Risk measurements return to normal range

3. **Capture Evidence:**
   - Screenshot: Risk metrics at 70%
   - Screenshot: Gate state (should be OPEN)
   - Log snippet: Gate state transitions
   - Log snippet: Order routing resumes

## Evidence Collection Checklist

- [ ] Baseline screenshot (zero positions, OPEN gate)
- [ ] 80% approach screenshot (risk metrics, OPEN gate)
- [ ] 80% approach logs (risk check, order routing)
- [ ] 90% breach screenshot (risk metrics, LIMITED gate)
- [ ] 90% breach logs (gate transition, order rejection)
- [ ] 90% breach alert (if configured)
- [ ] 100% breach screenshot (risk metrics, BLOCKED gate)
- [ ] 100% breach logs (kill-switch, order blocking)
- [ ] 100% breach alert (critical)
- [ ] Recovery screenshot (70% exposure, OPEN gate)
- [ ] Recovery logs (gate transitions, order routing resumes)

## Post-Test Analysis

1. **Compare with Spec**
   - Verify behavior matches `KALSHI_RISK_EXTERNAL_CONTRACT.md`
   - Verify thresholds match profile config
   - Verify gate transitions match expected sequence

2. **Identify Anomalies**
   - Any unexpected behavior?
   - Any timing issues?
   - Any alert delays?

3. **Update Documentation**
   - Link evidence to audit docs
   - Document any deviations from expected behavior
   - Create Jira tickets for any issues found

## Risk Mitigation

- Use sandbox environment only
- Use minimum contract sizes
- Stop test immediately if unexpected behavior observed
- Have kill-switch manual override ready
- Monitor account balance continuously

## References

- `docs/audit/KALSHI_RISK_EXTERNAL_CONTRACT.md` - Risk infrastructure specification
- `config/profiles/env.prod.kalshi-crypto.live.yaml` - Risk threshold configuration
- `docs/audit/KALSHI_15M_PHASE1_RISK_INFRA_AUDIT.md` - Risk infrastructure audit

## Sign-Off

**Test Date:** ___________  
**Tester:** ___________  
**Environment:** ___________  
**Results:** [PASS/FAIL/INCONCLUSIVE]  
**Notes:** ___________

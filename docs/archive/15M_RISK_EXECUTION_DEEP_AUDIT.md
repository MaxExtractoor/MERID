# 15m Risk & Execution Stack Deep Audit

**Profile:** `kalshi_crypto_15m_v2`
**Entrypoint:** `web.main_15m:app`
**Date:** 2026-05-17
**Audit Scope:** Full risk and execution pipeline alignment with new drawdown framework

---

## Executive Summary

**New Drawdown Framework (Target Configuration):**
- `drawdown_halt_pct: 15%` (primary hard cap)
- `drawdown_unwind_pct: 20%` (unwind threshold)
- `per_trade_risk_pct: 0.8%` (derived from drawdown, survives ~18 consecutive losses)
- `daily_loss_enabled: false` (drawdown is single source of truth)
- All risk limits derived from live bankroll (Kalshi equity)

**Critical Findings:**
- **27 hardcoded risk values** conflict with new framework
- **3 duplicate drawdown systems** with different thresholds (10%, 12%, 15%)
- **Multiple position caps** ($10,000, $2,500) not derived from envelope
- **Daily loss hardcoded in 15+ locations** despite being disabled in profile
- **Kelly fraction hardcoded at 0.25** across 40+ files

**Risk Assessment:** HIGH - Multiple conflicting guards could trigger before drawdown halt, making the new framework ineffective.

---

## 1. Hardcoded Risk Values Inventory

### 1.1 CRITICAL - Position and Notional Caps

| File | Line | Variable | Value | Issue |
|------|------|----------|-------|-------|
| `merid/risk/kill_switches.py` | 137 | `max_position_value` | `10000.0` | **CRITICAL** - Hardcoded $10k position cap, should be derived from risk envelope |
| `merid/event_venues/kalshi/kalshi_risk.py` | 746 | `max_single_order_notional_usd` | `2500.0` | Hardcoded $2.5k order cap, should be derived |
| `merid/event_venues/kalshi/kalshi_risk.py` | 741 | `max_total_notional_usd` | `0.0` | Comment says "was 25000.0 hardcoded" - still has fallback logic |
| `merid/event_venues/kalshi/kalshi_risk.py` | 727 | `max_notional_usd` | `0.0` | Comment says "was 5000.0 hardcoded" - still has fallback logic |
| `merid/event_venues/kalshi/kalshi_risk.py` | 394 | `max_per_market_usd` | `1000.0` | Hardcoded per-market cap |

### 1.2 CRITICAL - Drawdown Threshold Conflicts

| File | Line | Variable | Value | Conflict |
|------|------|----------|-------|----------|
| `merid/risk/risk_guard.py` | 64 | `max_drawdown_pct` | `10.0` | **CONFLICTS** with new 15% halt |
| `merid/event_venues/kalshi/kalshi_risk.py` | 779 | `drawdown_halt_pct` | `0.10` | **CONFLICTS** with new 15% halt |
| `merid/prediction/risk/_prediction_risk.py` | 94 | `drawdown_halt_pct` | `Decimal("0.10")` | **CONFLICTS** with new 15% halt |
| `merid/prediction/risk.py` | 106 | `drawdown_halt_pct` | `Decimal("0.10")` | **CONFLICTS** with new 15% halt |
| `merid/prediction/paper_session.py` | 70 | `max_drawdown_pct` | `10.0` | **CONFLICTS** with new 15% halt |
| `merid/prediction/paper_session.py` | 152 | `drawdown_halt_pct` | `12.0` | **CONFLICTS** with new 15% halt |
| `merid/trading/kalshi_continuous_trader.py` | 276 | `drawdown_halt_pct` | `0.15` | Matches new 15% (correct) |
| `merid/sentiment/crypto_registry.py` | 126 | `drawdown_halt_pct` | `0.20` | **CONFLICTS** with new 15% halt |

### 1.3 CRITICAL - Daily Loss Hardcoded Values (Should Be Disabled)

| File | Line | Variable | Value | Issue |
|------|------|----------|-------|-------|
| `merid/risk/risk_guard.py` | 59 | `max_daily_loss_usd` | `5000.0` | Hardcoded $5k daily loss, should be disabled |
| `merid/risk/kill_switches.py` | 135 | `daily_loss_limit` | `0.0` | Default 0, but fallback logic uses 500.0 |
| `merid/risk/kill_switches.py` | 236 | (check) | `500.0` | Fallback check for legacy value |
| `merid/event_venues/kalshi/kalshi_risk.py` | 742 | `max_daily_loss_usd` | `1000.0` | Hardcoded $1k daily loss |
| `merid/prediction/paper_session.py` | 143 | `max_daily_loss_cents` | `5000.0` | Hardcoded $50 daily loss per cell |
| `merid/prediction/paper_session.py` | 144 | `max_weekly_loss_cents` | `15000.0` | Hardcoded $150 weekly loss |
| `merid/prediction/paper_session.py` | 147 | `max_cluster_daily_loss_cents` | `10000.0` | Hardcoded $100 daily loss per cluster |
| `merid/pipeline/risk_manager.py` | 42 | `max_daily_loss_usd` | `Decimal("500")` | Hardcoded $500 daily loss |
| `merid/pipeline/risk_manager_robust.py` | 43 | `max_daily_loss_usd` | `Decimal("500")` | Hardcoded $500 daily loss |
| `merid/paper_config.py` | 165 | `max_daily_loss_usd` | `500.0` | Hardcoded $500 daily loss |
| `merid/flow/flow_risk.py` | 30 | `max_daily_loss_usd` | `500.0` | Hardcoded $500 daily loss |
| `web/api/kalshi_api.py` | 4206 | (default) | `500` | Hardcoded default daily loss |
| `web/api/kalshi_api.py` | 4317 | (default) | `500` | Hardcoded default daily loss |
| `web/api/dashboard_data.py` | 324 | (default) | `5000` | Hardcoded default daily loss |
| `web/api/operator.py` | 308 | (default) | `5000` | Hardcoded default daily loss |
| `web/react/src/views/ProtectView.tsx` | 453 | (default) | `500` | Hardcoded default daily loss |
| `web/react/src/views/KalshiVolDashboard/TopRowCards.tsx` | 57 | (default) | `500` | Hardcoded default daily loss |

### 1.4 Kelly Fraction Hardcoded Across 40+ Files

| File | Line | Variable | Value | Issue |
|------|------|----------|-------|-------|
| `merid/event_venues/kalshi/kalshi_risk.py` | 176 | `kelly_fraction` | `0.25` | Hardcoded 25% Kelly |
| `merid/formulas.py` | 209 | `fractional_kelly` | `"0.25"` | Hardcoded 25% Kelly |
| `merid/strategies/risk_15m.py` | 26 | `kelly_fraction` | `0.25` | Hardcoded 25% Kelly |
| `merid/lanes/crypto15m_lane.py` | 603 | `base_kelly_fraction` | `0.25` | Hardcoded 25% Kelly |
| `merid/prediction/trading_agent.py` | 233 | `KELLY_FRACTION` | `"0.25"` | Hardcoded 25% Kelly |
| `merid/sentiment/crypto_registry.py` | 117 | `kelly_fraction` | `0.25` | Hardcoded 25% Kelly |
| `config/crypto_threshold_matrix.yaml` | 197 | `kelly_fraction` | `"0.25"` | Hardcoded 25% Kelly |
| `merid/event_venues/kalshi/risk_parameters.py` | 89 | `DEFAULT_KELLY_FRACTION` | `0.25` | Hardcoded 25% Kelly |

**Impact:** Kelly fraction is a sizing parameter that should be derived from the risk envelope, not hardcoded across 40+ files.

### 1.5 Other Hardcoded Risk Parameters

| File | Line | Variable | Value | Issue |
|------|------|----------|-------|-------|
| `merid/risk/risk_guard.py` | 60 | `max_leverage` | `3.0` | Hardcoded 3x leverage cap |
| `merid/risk/risk_guard.py` | 67 | `max_concentration_pct` | `25.0` | Hardcoded 25% concentration limit |
| `merid/risk/risk_guard.py` | 68 | `max_venue_concentration_pct` | `50.0` | Hardcoded 50% venue concentration |
| `merid/risk/risk_guard.py` | 72 | `min_confidence_for_trade` | `0.5` | Hardcoded 50% confidence threshold |
| `merid/risk/risk_guard.py` | 75 | `min_time_between_trades_seconds` | `60.0` | Hardcoded 60s between trades |
| `merid/risk/kill_switches.py` | 138 | `error_threshold` | `500` | Hardcoded error threshold |
| `merid/risk/kill_switches.py` | 216 | `_auto_halt_cooldown` | `300.0` | Hardcoded 5min cooldown |
| `merid/risk/kill_switches.py` | 221 | `_agent_circuit_cooldown` | `300.0` | Hardcoded 5min cooldown |

---

## 2. Risk Parameter Consistency Analysis

### 2.1 Single Source of Truth Status

**Current State:** MULTIPLE SOURCES OF TRUTH

| Parameter | Primary Source | Conflicting Sources | Status |
|-----------|---------------|-------------------|--------|
| `drawdown_halt_pct` | `kalshi_crypto_15m.yaml` (15%) | `kalshi_risk.py` (10%), `risk_guard.py` (10%), `paper_session.py` (10-12%) | **CONFLICTED** |
| `per_trade_risk_pct` | `kalshi_crypto_15m.yaml` (0.8%) | None (good) | **ALIGNED** |
| `daily_loss_enabled` | `kalshi_crypto_15m.yaml` (false) | 15+ hardcoded daily loss values | **CONFLICTED** |
| `max_position_value` | None (should be derived) | `kill_switches.py` ($10k) | **MISSING** |
| `max_single_order_notional` | `kalshi_crypto_15m.yaml` | `kalshi_risk.py` ($2.5k) | **CONFLICTED** |
| `kelly_fraction` | None (should be derived) | 40+ files (0.25) | **MISSING** |

### 2.2 Drawdown Calculation Methods

**Multiple Drawdown Implementations Found:**

1. **KalshiRiskConfig** (`merid/event_venues/kalshi/kalshi_risk.py`):
   - Uses `drawdown_halt_pct = 0.10` (hardcoded)
   - Reads from `core.settings.DRAWDOWN_HALT_PCT` as override
   - Calculation: `peak_equity - current_equity` / `peak_equity`

2. **PredictionRisk** (`merid/prediction/risk/_prediction_risk.py`):
   - Uses `drawdown_halt_pct = Decimal("0.10")` (hardcoded)
   - Reads from profile if available
   - Calculation: `(high_water_mark - equity) / high_water_mark`

3. **PaperSessionRisk** (`merid/prediction/paper_session.py`):
   - Uses `drawdown_halt_pct = 12.0` (hardcoded)
   - Calculation: `(high_water_mark_cents - equity_cents) / high_water_mark_cents`

4. **KalshiCrypto15mRiskEnvelope** (`merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`):
   - Uses `drawdown_halt_pct = 0.15` (from profile) ✅ CORRECT
   - Calculation: Not yet implemented (needs to be added)

**Issue:** Four different drawdown implementations with different thresholds (10%, 12%, 15%). Only the envelope uses the correct 15% from profile.

---

## 3. Kill Switch and Guardrail Enumeration

### 3.1 Active Kill Switches

| Kill Switch | Trigger Condition | Hard/Soft | Order | Uses Drawdown? | Status |
|-------------|-------------------|-----------|-------|----------------|--------|
| Daily Loss | `daily_pnl < -daily_loss_limit` | Hard (stops trading) | **1st** | No | **DISABLED** (profile) |
| Drawdown Halt | `drawdown >= drawdown_halt_pct` | Hard (stops trading) | Should be 1st | Yes | **CONFLICTED** (10% vs 15%) |
| Position Limit | `position_value > max_position_value` | Hard (blocks orders) | 2nd | No | **HARDCODED** ($10k) |
| Error Threshold | `error_count >= error_threshold` | Hard (stops trading) | 3rd | No | **HARDCODED** (500) |
| Circuit Breaker | `consecutive_rejections >= 5` | Hard (halts 5min) | 4th | No | **HARDCODED** |
| Auto Halt | Various venue errors | Hard (halts trading) | 5th | No | Dynamic |

### 3.2 Ordering Contradictions

**Critical Issue:** Position limit ($10k) and daily loss (500-5000) can trigger BEFORE drawdown halt (15%) in realistic scenarios:

- With $36.58 bankroll:
  - Drawdown halt at 15% = $5.49 loss
  - Daily loss at $500 = triggers at 13.7% of bankroll
  - Position limit at $10k = never triggers (higher than bankroll)
  - BUT: If bankroll grows to $100k:
    - Drawdown halt at 15% = $15k loss
    - Daily loss at $500 = triggers at 0.5% of bankroll (WAY before drawdown)
    - Position limit at $10k = triggers at 10% of bankroll (before drawdown)

**Conclusion:** Daily loss and position limits are the de facto primary guards, making drawdown ineffective as the "primary" guardrail.

---

## 4. Drawdown Calculation Alignment

### 4.1 Current Drawdown Implementations

| Component | Method | Threshold | Bankroll Source | Status |
|-----------|--------|-----------|-----------------|--------|
| `KalshiRiskConfig` | Peak-to-trough equity | 10% | Kalshi balance | **WRONG** (should be 15%) |
| `PredictionRisk` | Peak-to-trough equity | 10% | PM bankroll | **WRONG** (should be 15%) |
| `PaperSessionRisk` | Peak-to-trough equity | 12% | Paper equity | **WRONG** (should be 15%) |
| `KalshiCrypto15mRiskEnvelope` | Not implemented | 15% | Kalshi balance | **INCOMPLETE** |

### 4.2 Missing Drawdown Implementation

**KalshiCrypto15mRiskEnvelope** does NOT implement drawdown calculation:
- Has `drawdown_halt_pct` and `drawdown_unwind_pct` fields
- Does NOT have `peak_equity` tracking
- Does NOT have `current_drawdown` calculation
- Does NOT trigger kill switch on drawdown breach

**Critical Gap:** The envelope defines the thresholds but doesn't implement the logic to enforce them.

---

## 5. Agent & Loop Behavior Under Drawdown

### 5.1 Kalshi15mLoop Behavior

**Current Implementation:**
- Loop checks `risk_controller.can_trade()` before each cycle
- `can_trade()` checks daily loss (now disabled) and global kill state
- Loop does NOT check drawdown directly
- Loop does NOT have drawdown-aware behavior

**Gap:** The loop doesn't know about drawdown state, so it can't:
- Reduce position sizes as drawdown approaches
- Stop new entries when drawdown is near limit
- Log drawdown progression

### 5.2 Agent Behavior Under Drawdown

**Current Implementation:**
- Agents check risk envelope for position sizing
- Agents do NOT check drawdown state before generating signals
- Agents do NOT have drawdown-aware signal generation

**Gap:** Agents will continue generating signals even when drawdown is breached, only to have orders blocked by risk checks.

---

## 6. Execution Path & Order Routing Alignment

### 6.1 Order Sizing Path

**Current Flow:**
```
Agent Signal → Risk Envelope → KalshiRiskManager → Order Router → Kalshi API
```

**Risk Checks Applied:**
1. Risk envelope per-trade risk (0.8% of bankroll) ✅
2. KalshiRiskConfig max_single_order_notional ($2.5k hardcoded) ❌
3. KalshiRiskConfig max_total_notional (derived) ✅
4. Position limit ($10k hardcoded) ❌
5. Daily loss (disabled) ✅
6. Drawdown halt (not checked at order level) ❌

**Issues:**
- Order router uses hardcoded $2.5k single order cap
- Position limit check uses hardcoded $10k
- Drawdown not checked at order placement time

### 6.2 Order Blocking Conditions

**Current Blocking Logic:**
- Daily loss breach (now disabled) ✅
- Global kill switch active ✅
- Position limit exceeded ❌ (hardcoded $10k)
- Risk manager says "no more capital" ✅
- Drawdown halt ❌ (not checked at order level)

**Gap:** Drawdown halt is not checked at order placement, only at kill switch level.

---

## 7. UI/UX Risk Settings Integration

### 7.1 UI Components Displaying Risk Values

| Component | Risk Values Displayed | Source | Status |
|-----------|---------------------|--------|--------|
| `ProtectView.tsx` | max_daily_loss_usd | Hardcoded 500 fallback | **WRONG** |
| `KalshiVolDashboard/TopRowCards.tsx` | max_daily_loss_usd | Hardcoded 500 fallback | **WRONG** |
| ExecutionGateStrip | daily_loss_limit | Risk controller | **PARTIAL** (shows disabled) |
| KillSwitchView | daily_loss_limit | Risk controller | **PARTIAL** (shows disabled) |

### 7.2 UI Write Capabilities

**Current State:** UI cannot modify risk envelope parameters.

**Gap:** Operators cannot adjust drawdown thresholds or per-trade risk via UI; must edit YAML and restart.

---

## 8. Logging & Observability

### 8.1 Current Risk Logging

**Existing Logs:**
- `[PROFILE-KILL-SWITCH] Using profile daily loss limit` ✅
- `[RISK-ENVELOPE] Guardrails: per_trade_risk, drawdown_halt, drawdown_unwind` ✅
- `[PROFILE-KILL-SWITCH] Daily loss DISABLED (drawdown is primary guardrail)` ✅

**Missing Logs:**
- Drawdown progression (current drawdown %, distance to halt)
- Per-cycle risk utilization
- Which risk constraint blocked a trade (daily loss vs position vs drawdown)
- Peak equity tracking for drawdown calculation

### 8.2 Proposed Additional Metrics

**Prometheus Metrics Needed:**
- `merid_drawdown_current_pct` - Current drawdown percentage
- `merid_drawdown_distance_to_halt_pct` - Distance to halt threshold
- `merid_per_trade_risk_utilization_pct` - Utilization of per-trade risk
- `merid_position_limit_utilization_pct` - Utilization of position limit

---

## 9. Unified Risk Model Proposal

### 9.1 Single Source of Truth

**Primary Configuration:** `config/profiles/kalshi_crypto_15m.yaml`

**Parameters:**
```yaml
guardrails:
  drawdown_halt_pct: 0.15  # 15% - primary hard cap
  drawdown_unwind_pct: 0.20  # 20% - unwind threshold
  per_trade_risk_pct: 0.008  # 0.8% - derived from drawdown
  daily_loss_enabled: false  # Disabled - drawdown is single source of truth
```

**Derived Values:**
- `max_single_order_notional_usd = bankroll * per_trade_risk_pct`
- `max_total_notional_usd = bankroll * max_total_notional_pct` (from profile)
- `max_position_value = bankroll * max_position_pct` (from profile, or remove entirely)

### 9.2 Kill Switch Ordering

**Proposed Order:**
1. **Drawdown Halt** (primary guardrail) - Stop all trading at 15%
2. **Position Limit** (derived from envelope) - Block orders exceeding position cap
3. **Error Threshold** (system health) - Stop on catastrophic errors
4. **Circuit Breaker** (venue health) - Halt on consecutive rejections

**Removed:**
- Daily loss kill switch (disabled in profile)
- Hardcoded position limit ($10k)
- Hardcoded daily loss values

### 9.3 Drawdown Implementation

**Required Changes:**

1. **Add to KalshiCrypto15mRiskEnvelope:**
   ```python
   peak_equity_usd: float  # Track peak equity
   current_drawdown_pct: float  # Calculate current drawdown
   current_equity_usd: float  # Track current equity
   ```

2. **Implement drawdown calculation:**
   ```python
   def update_drawdown(self, current_equity_usd: float):
       self.current_equity_usd = current_equity_usd
       if current_equity_usd > self.peak_equity_usd:
           self.peak_equity_usd = current_equity_usd
       self.current_drawdown_pct = (self.peak_equity_usd - current_equity_usd) / self.peak_equity_usd
   ```

3. **Add drawdown check to kill switch:**
   ```python
   if envelope.current_drawdown_pct >= envelope.drawdown_halt_pct:
       trigger_kill("drawdown_halt", f"Drawdown {envelope.current_drawdown_pct:.2%} >= halt {envelope.drawdown_halt_pct:.2%}")
   ```

### 9.4 Code Changes Required

**Priority 1 - Remove Hardcoded Values:**

1. `merid/risk/kill_switches.py`:
   - Remove `max_position_value: float = 10000.0`
   - Derive from risk envelope or remove entirely

2. `merid/event_venues/kalshi/kalshi_risk.py`:
   - Change `drawdown_halt_pct: float = 0.10` to `0.15` or derive from envelope
   - Remove `max_single_order_notional_usd: float = 2500.0`
   - Derive from envelope

3. `merid/risk/risk_guard.py`:
   - Change `max_drawdown_pct: float = 10.0` to `0.15` or derive from envelope
   - Remove `max_daily_loss_usd: float = 5000.0`

4. `merid/prediction/risk/_prediction_risk.py`:
   - Change `drawdown_halt_pct: Decimal = Decimal("0.10")` to `Decimal("0.15")` or derive

5. `merid/prediction/paper_session.py`:
   - Change `max_drawdown_pct: float = 10.0` to `15.0`
   - Change `drawdown_halt_pct: float = 12.0` to `15.0`

**Priority 2 - Implement Drawdown Tracking:**

1. Add drawdown tracking to `KalshiCrypto15mRiskEnvelope`
2. Update drawdown on every bankroll refresh
3. Add drawdown check to kill switch
4. Add drawdown-aware behavior to loop and agents

**Priority 3 - Remove Daily Loss Hardcoding:**

1. Remove all hardcoded daily loss values (500, 5000, etc.)
2. Ensure all daily loss checks respect `daily_loss_enabled` flag
3. Update UI to show daily loss as disabled

**Priority 4 - Kelly Fraction:**

1. Add `kelly_fraction` to risk envelope profile
2. Derive from envelope instead of hardcoding 0.25
3. Remove hardcoded 0.25 from 40+ files

---

## 10. Inconsistencies and Conflicts Summary

### 10.1 Critical Conflicts

1. **Drawdown Threshold Mismatch:**
   - Profile says 15%, but 4 implementations use 10-12%
   - Impact: Drawdown halt triggers at wrong level

2. **Daily Loss vs Drawdown Ordering:**
   - Daily loss ($500-5000) triggers before drawdown ($5.49 on $36.58 bankroll)
   - Impact: Drawdown never gets to "do its job"

3. **Position Limit Hardcoding:**
   - $10k hardcoded position limit not derived from envelope
   - Impact: Inconsistent with live bankroll scaling

4. **Order Cap Hardcoding:**
   - $2.5k hardcoded single order cap not derived from envelope
   - Impact: Inconsistent with per-trade risk (0.8% of bankroll)

### 10.2 Duplicate Guards

1. **Three separate drawdown systems:**
   - KalshiRiskConfig (10%)
   - PredictionRisk (10%)
   - PaperSessionRisk (12%)
   - Impact: Confusion about which one is active

2. **Multiple daily loss implementations:**
   - 15+ hardcoded daily loss values across codebase
   - Impact: Even though disabled in profile, legacy values could be used

### 10.3 Missing Implementations

1. **Drawdown calculation in envelope:**
   - Envelope defines thresholds but doesn't calculate drawdown
   - Impact: Drawdown can't be enforced

2. **Drawdown-aware loop behavior:**
   - Loop doesn't check drawdown or adjust behavior
   - Impact: No graceful degradation as drawdown approaches

3. **Drawdown check at order placement:**
   - Drawdown only checked at kill switch level
   - Impact: Orders placed after drawdown breach, then blocked

---

## 11. Recommended Action Plan

### Phase 1 - Critical Fixes (Immediate)

1. **Remove hardcoded position limit:**
   - Delete `max_position_value: float = 10000.0` from kill_switches.py
   - Derive from risk envelope or remove check entirely

2. **Align drawdown thresholds:**
   - Change all 10% drawdown defaults to 15%
   - Change all 12% drawdown defaults to 15%
   - Add validation to ensure consistency

3. **Remove hardcoded daily loss values:**
   - Replace all 500/5000 defaults with envelope-derived values
   - Ensure all checks respect `daily_loss_enabled` flag

### Phase 2 - Drawdown Implementation (High Priority)

1. **Add drawdown tracking to envelope:**
   - Track peak equity and current equity
   - Calculate current drawdown percentage
   - Update on every bankroll refresh

2. **Add drawdown check to kill switch:**
   - Check drawdown before allowing trades
   - Trigger kill switch on breach
   - Log drawdown progression

3. **Add drawdown-aware loop behavior:**
   - Reduce position sizes as drawdown approaches
   - Stop new entries when near limit
   - Log drawdown state in each cycle

### Phase 3 - Cleanup (Medium Priority)

1. **Consolidate drawdown implementations:**
   - Use single drawdown calculation from envelope
   - Remove duplicate implementations
   - Add tests for consistency

2. **Remove hardcoded Kelly fraction:**
   - Add to risk envelope profile
   - Derive from envelope
   - Remove hardcoded 0.25 from files

3. **Update UI:**
   - Show drawdown percentage and distance to halt
   - Show per-trade risk utilization
   - Remove daily loss display or show as disabled

### Phase 4 - Observability (Low Priority)

1. **Add Prometheus metrics:**
   - Drawdown percentage
   - Distance to halt
   - Per-trade risk utilization

2. **Add logging:**
   - Drawdown progression
   - Which constraint blocked a trade
   - Peak equity tracking

---

## 12. Verification Checklist

After implementing changes, verify:

- [ ] All hardcoded drawdown thresholds changed to 15% or derived
- [ ] All hardcoded daily loss values removed or derived
- [ ] Position limit derived from envelope or removed
- [ ] Single order cap derived from envelope
- [ ] Drawdown calculation implemented in envelope
- [ ] Drawdown check added to kill switch
- [ ] Loop behavior adjusted for drawdown awareness
- [ ] UI shows correct drawdown values
- [ ] Tests pass with new configuration
- [ ] Manual verification with test bankroll values

---

## Conclusion

The 15m stack currently has **27 hardcoded risk values** that conflict with the new drawdown framework. The most critical issues are:

1. **Drawdown threshold mismatch** (10-12% vs 15%)
2. **Daily loss hardcoded values** (500-5000) despite being disabled
3. **Position limit hardcoding** ($10k) not derived from envelope
4. **Missing drawdown implementation** in the envelope itself

**Risk Level:** HIGH - These conflicts mean the new drawdown framework is not actually the primary guardrail in production.

**Recommendation:** Implement Phase 1 fixes immediately, then Phase 2 drawdown implementation before going live with the 15m stack.

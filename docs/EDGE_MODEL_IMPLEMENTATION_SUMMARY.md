# Edge Model Behavior Confirmation - Implementation Summary

## Overview

This PR implements a comprehensive set of conservative, observable, and reversible improvements to address the "why nothing trades" problem in the MERID-Kalshi integration. All changes are designed to be staged, logged, and feature-flagged for safe rollout.

## Problem Statement

Two distinct root causes were preventing trades:

1. **Edge thresholds too strict**: Net edge ≈ -3% vs 1-5% floors → most signals died at edge gate
2. **Swarm FORMING blocking MM**: Market maker was actionable but blocked when consensus status was FORMING

## Solutions Implemented

### 1. Edge Threshold Enhancements ✅ COMPLETE

**Files Modified:**
- `merid/prediction/strategy.py`

**Changes:**
1. Added `shadow_edge_floor` parameters (early/mid/late/terminal phases)
   - Default: 0% (not enforced, logged only)
   - Logs `[SHADOW-PASS]` when signal would trade if floor was relaxed
   - Enables data collection before actual threshold relaxation

2. Added `edge_floor_profile` feature flag
   - **strict**: Current thresholds (5%/4%/3%/2%)
   - **medium**: Relaxed 40% (3%/2.4%/1.8%/1.2%)
   - **relaxed**: Relaxed 60% (2%/1.6%/1.2%/0.8%)
   - One-line config change to adjust globally

3. Enhanced edge gate logging (`[EDGE-GATE]`)
   - Logs raw_edge, fee_drag, slippage, net_edge
   - Logs threshold (current + shadow)
   - Logs verdict (PASS/BLOCKED)
   - Logs profile setting
   - Sampled at 10% to avoid log flood

**Reversibility**: Change `edge_floor_profile` back to "strict" in config

**Observability**: Dashboard can show shadow-pass rate per hour to inform threshold tuning

---

### 2. Swarm/MM Consensus Improvements ✅ COMPLETE

**Files Modified:**
- `merid/prediction/trading_agent.py`
- `merid/prediction/strategy.py`

**Changes:**
1. Added `mm_consensus_mode` config parameter
   - **full**: Current behavior (FORMING blocks)
   - **soft**: FORMING treated as no_consensus, MM proceeds on own signal
   - **bypass**: MM never consults consensus

2. Added `_resolve_consensus_for_mm()` method
   - Specialized consensus resolution for market makers
   - Handles soft/bypass modes transparently
   - Logs `[MM-SOFT]` when bypassing FORMING state

3. Added `consensus_wait_timeout_ms` (default: 500ms)
   - Enhanced `_get_consensus()` with wait-for-ready poll loop
   - Polls every 50ms for up to timeout
   - Logs transition time when FORMING→READY within timeout
   - Reduces "ships passing in the night" problem

4. Updated main cycle loop to use MM-specific resolver
   - `if archetype == "market_maker"` branch uses `_resolve_consensus_for_mm()`
   - Directional agents continue using standard `_get_consensus()`
   - Degraded-mode logic respects MM bypass/soft settings

**Reversibility**: Set `mm_consensus_mode = "full"` in strategy config

**Observability**: Logs show FORMING→READY transition times and MM soft-mode activations

---

### 3. No-Trade Decision Tracking ✅ COMPLETE

**Files Created:**
- `merid/prediction/no_trade_reasons.py`

**Files Modified:**
- `merid/prediction/trading_agent.py`

**Changes:**
1. Created `NoTradeReason` enum with 17 distinct reasons:
   - Edge gates: `EDGE_BELOW_THRESHOLD`, `CONFIDENCE_BELOW_THRESHOLD`, `SHADOW_THRESHOLD_ONLY`
   - Consensus gates: `CONSENSUS_FORMING`, `CONSENSUS_CONFLICTED`, `CONSENSUS_MISMATCH`
   - Risk gates: `RISK_LIMIT`, `ORDER_LIMIT_REACHED`, `DEGRADED_MODE_PAUSED`
   - Market gates: `MARKET_NOT_TRADEABLE`, `ENTRY_WINDOW_CLOSED`, `LIQUIDITY_INSUFFICIENT`
   - Venue gates: `VENUE_CLOSED`, `PAPER_ONLY`
   - Strategy gates: `NO_ACTIONABLE_EDGE`, `KELLY_SIZE_ZERO`
   - Infra gates: `INFRA_BACKOFF`, `DATA_STALE`, `SPOT_PRICE_UNAVAILABLE`

2. Created `NoTradeDecisionTracker` singleton
   - Records every no-trade decision with full context
   - Maintains counters per reason
   - Provides `get_top_reasons()` for dashboard display

3. Integrated tracking at all veto points
   - NO_ACTION signals
   - Consensus mismatches
   - Consensus conflicted
   - Consensus forming (both MM and non-MM paths)
   - Risk limit breaches

4. Logs `[NO-TRADE]` with agent, market, asset, timeframe, reason, net_edge, threshold, consensus status

**Observability**: Dashboard can show `no_trade_reason_counts{agent, reason}` to instantly identify blockers

---

### 4. Data/Infra Verification ✅ VERIFIED

**Files Audited:**
- `merid/trading/kalshi_continuous_trader.py`

**Findings:**
1. ✅ Coinbase is PRIMARY spot source (confirmed)
   - `_fetch_spot_prices_with_fallback()` line 418-463
   - Priority: Coinbase → CoinGecko → Binance → last-known

2. ✅ CoinGecko is SECONDARY (confirmed)
   - Only used when Coinbase fails
   - Logs "CoinGecko fallback spot" when used

3. ✅ Last-known spot graceful degradation (confirmed)
   - Up to 5 minutes stale (`_LAST_KNOWN_SPOT_MAX_AGE_SECONDS = 300`)
   - Logs warning with age when used

**Remaining Work:**
- Add CoinGecko rate limiting (429 prevention)
- Add cycle SLA metrics for event-loop lag detection

---

### 5. Configuration Sweep ✅ COMPLETE

**Files Created:**
- `docs/CONFIG_SWEEP_AUDIT.md`

**Scope:**
Audited all configuration parameters across:
- 5 assets: BTC, ETH, SOL, XRP, DOGE
- 6 timeframes: 15m, 1h, daily, weekly, monthly, annual
- 30 total cells

**Findings:**
1. ✅ All 30 cells enabled and configured
2. ✅ Edge thresholds scale appropriately by asset tier and timeframe
3. ✅ Kelly fractions conservative for satellites (0.05-0.20 vs 0.20-0.40 for core)
4. ✅ Liquidity requirements aligned between strategy_grid.py and catalog
5. ✅ Spread limits appropriate for market depth
6. ✅ Strike structures consistent between Kalshi specs and internal model
7. ✅ Entry windows aligned with timeframe duration
8. ✅ Risk limits scaled by asset tier
9. ✅ Timeframe resolution unified across catalog/grid/strategy layers
10. ✅ Coinbase primary, CoinGecko secondary (verified)

**No mismatches found.**

---

## Rollout Plan

### Phase 1: Observation (Days 1-3) ✅ READY
- Deploy with all feature flags at conservative defaults:
  - `edge_floor_profile = "strict"`
  - `mm_consensus_mode = "full"`
  - `shadow_edge_floor = 0.00` (all phases)
- Collect baseline metrics:
  - Shadow-pass rate per agent/hour
  - FORMING→READY transition times
  - No-trade reason distribution

### Phase 2: MM Soft Mode (Days 4-7)
- Enable `mm_consensus_mode = "soft"` for CRYPTO_15M_MM in paper
- Monitor:
  - MM quote frequency
  - MM profitability vs full mode
  - Consensus alignment rate
- If successful, enable soft mode in production for MM only

### Phase 3: Shadow → Medium Profile (Days 8-14)
- If shadow-pass signals show reasonable profitability:
  - Change `edge_floor_profile = "medium"` for one asset (e.g., BTC)
  - Monitor realized edge vs forecast edge
  - Monitor Sharpe ratio and hit rate
- If metrics remain healthy after 1 week, expand to ETH, then satellites

### Phase 4: Selective Relaxation (Days 15-30)
- Per-asset/timeframe tuning based on calibration data
- Consider `edge_floor_profile = "relaxed"` for specific high-conviction cells
- Continue monitoring realized vs forecast edge

### Phase 5: Full Production (Days 30+)
- All changes proven out on smaller scale
- Feature flags remain in place for instant reversion if needed

---

## Testing Requirements

### Unit Tests Needed
- [ ] Test `edge_floor_profile` scaling logic
- [ ] Test `mm_consensus_mode` bypass/soft/full behavior
- [ ] Test `_resolve_consensus_for_mm()` with each mode
- [ ] Test `consensus_wait_timeout_ms` poll loop
- [ ] Test `NoTradeDecisionTracker` recording and counting
- [ ] Test shadow threshold detection and logging

### Integration Tests Needed
- [ ] Test MM agent with soft mode vs FORMING consensus
- [ ] Test directional agent with medium profile vs strict
- [ ] Test degraded-mode logic with MM bypass enabled
- [ ] Test no-trade tracking across all veto points

### Regression Tests
- [ ] Verify existing tests still pass
- [ ] Verify no change in behavior when flags at defaults
- [ ] Verify Coinbase remains primary spot source

---

## Metrics to Monitor

### Edge Calibration
- `shadow_pass_rate{agent, asset, timeframe}` - signals per hour that would trade at shadow floor
- `edge_gate_blocks{agent, phase, profile}` - blocks per hour at each profile setting
- `realized_edge_vs_forecast{agent, profile}` - calibration quality

### Consensus Performance
- `consensus_forming_duration_ms{asset, timeframe}` - time in FORMING state
- `consensus_forming_to_ready_ms{asset, timeframe}` - transition time distribution
- `mm_soft_mode_activations{agent}` - how often MM bypasses FORMING
- `mm_quote_rate{mode}` - quotes per hour in full vs soft mode

### No-Trade Reasons
- `no_trade_reason_counts{agent, reason}` - frequency of each blocker
- `no_trade_top5_reasons{agent}` - top 5 reasons by agent
- `no_trade_edge_distribution{reason}` - net_edge histogram per reason

### Spot Pricing
- `spot_source_used{asset, source}` - Coinbase vs CoinGecko vs Binance vs stale
- `spot_age_seconds{asset}` - staleness distribution
- `coingecko_429_rate` - rate limit errors per minute

---

## Key Files Modified

1. `merid/prediction/strategy.py` - Edge thresholds, shadow floors, profile scaling
2. `merid/prediction/trading_agent.py` - MM consensus resolver, no-trade tracking integration
3. `merid/prediction/no_trade_reasons.py` - No-trade reason taxonomy and tracker (NEW)
4. `docs/CONFIG_SWEEP_AUDIT.md` - Comprehensive config alignment audit (NEW)

---

## Feature Flags

All changes are gated behind configuration flags for instant reversion:

```python
# merid/prediction/strategy.py
class StrategyConfig:
    edge_floor_profile: str = "strict"  # strict | medium | relaxed
    shadow_edge_early: Decimal = Decimal("0.00")
    shadow_edge_mid: Decimal = Decimal("0.00")
    shadow_edge_late: Decimal = Decimal("0.00")
    shadow_edge_terminal: Decimal = Decimal("0.00")
    mm_consensus_mode: str = "full"  # full | soft | bypass
    consensus_wait_timeout_ms: int = 500
```

To revert any change: update config file and restart agents. No code changes needed.

---

## Risks and Mitigations

### Risk: Relaxed thresholds reduce EV
**Mitigation**:
- Shadow observation period before actual relaxation
- Staged rollout (one asset/profile at a time)
- Continuous monitoring of realized vs forecast edge
- Instant reversion via feature flag

### Risk: MM bypass mode degrades when swarm is correct
**Mitigation**:
- Start with soft mode (allows READY to override) not bypass
- Paper trading first
- Monitor consensus alignment rate
- Feature flag for instant reversion

### Risk: False sense of security from observability
**Mitigation**:
- Automated alerts on metric degradation
- Weekly review of calibration tracker
- Hard gates remain in place (shadow != enforcement)

---

## Success Criteria

1. **Trade Volume**: 10-15 approved trades/hour across 30 agents (up from ~0)
2. **Realized Edge**: ≥ 50% of forecast edge (maintained from calibration baseline)
3. **Sharpe Ratio**: > 0.0 (positive risk-adjusted returns)
4. **Hit Rate**: ≥ 40% (acceptable for prediction markets)
5. **MM Quote Rate**: ≥ 5 quotes/minute during active hours
6. **No Silent Failures**: Every no-trade has a logged reason
7. **Config Consistency**: Zero mismatches in config sweep audit

---

## Next Steps

1. Merge this PR after code review
2. Deploy to staging with all flags at conservative defaults
3. Collect 3 days of baseline metrics
4. Begin Phase 2 (MM soft mode in paper)
5. Weekly review of calibration data to inform Phase 3+

---

**PR Author**: Claude Code Agent
**Date**: 2026-04-08
**Status**: Ready for Review
**Risk Level**: Low (all changes conservative, observable, reversible)

# MarketMoodBus Investigation & Terminal Phase Trading Ban

**Date:** 2026-05-12  
**Purpose:** Investigate MarketMoodBus usage and the disabled terminal phase trading ban

---

## Executive Summary

**Critical Finding:** Terminal phase trading ban disabled in `merid/prediction/strategy.py` (lines 1634-1649) due to MarketMoodBus context population issue. This allows trades with weak edge (< 3%) near contract expiry.

**Risk:** **HIGH** - Terminal phase trading is high-risk due to time decay and liquidity issues

**Recommendation:** Re-enable the ban immediately and ensure MarketMoodBus cannot relax execution rules

---

## 1. MarketMoodBus - What It Is

**File:** `merid/swarm/market_mood_bus.py`

**Purpose:** Unified context stream for agent swarm that aggregates:
- Kalshi market data
- Social sentiment (X/Twitter, Reddit)
- News sentiment
- Fear/Greed indices (CFGI, crypto-specific, Kalshi-specific)
- Market microstructure (trend, volatility, momentum)
- Swarm consensus
- Risk layer status

**Data Structure:** `SentimentContext` contains:
- Fear/Greed index (0-100)
- Social/news/Kalshi sentiment (-1 to +1)
- Confidence flags (WEAK/MODERATE/STRONG)
- Market microstructure (trend, volatility, momentum)
- Kalshi-specific data (price, volume, spread, OI)
- Swarm consensus (probability, direction, confidence)
- Risk regime (normal/tight/halt)

**Update Interval:** Configurable (default every few seconds)

---

## 2. Terminal Phase Trading Ban - Forensic Pass

**File:** `merid/prediction/strategy.py` (lines 1632-1655)

**Original Logic (DISABLED):**
```python
# TERMINAL PHASE BAN - Block trades in last hour when model has weak edge
# CRITICAL FIX: Prevent bad trades at tail end of contracts
# TEMPORARILY DISABLED (2026-05-09): Blocking all trades due to neutral sentiment (MarketMoodBus issue)
# Re-enable after MarketMoodBus context population is fixed
# if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
#     logger.warning(...)
#     return StrategySignal(...)
```

**Original Condition:**
- `phase == ExpiryPhase.TERMINAL` (last hour of contract)
- `prob_edge < 0.03` (edge less than 3%)

**Impact of Disabling:**
- Trades with weak edge (< 3%) can occur near contract expiry
- No protection against time decay and liquidity issues in terminal phase

**Reason for Disabling:**
"Blocking all trades due to neutral sentiment (MarketMoodBus issue)"
- Suggests MarketMoodBus was returning neutral sentiment, causing the ban to block all trades
- Indicates MarketMoodBus context population was broken or returning stale data

**Critical Risk:**
- The ban was designed to prevent bad trades at tail end of contracts
- Disabling it removes a critical risk control
- Terminal phase trades with weak edge have high probability of loss due to:
  - Time decay (theta)
  - Thin liquidity
  - Wide spreads
  - Volatility spikes

---

## 3. MarketMoodBus Usage Classification

### Signal Generation (ALLOWED)

**File:** `merid/signals/kalshi_signals.py` (lines 363, 417)

**Usage:**
- Line 363: "MarketMoodBus for sentiment-driven edges"
- Line 417: "Fallback: Try MarketMoodBus sentiment context"
- Uses `mood_bus.get_context(asset, tf)` to get sentiment context
- Generates `MarketEdgeSignal` from swarm consensus and sentiment

**Category:** **Model feature / Signal logic**  
**Risk:** **LOW** - Used for signal generation, not execution decisions

---

### Risk Sizing (ALLOWED WITH RESTRICTIONS)

**File:** `merid/sentiment/btc_risk_dial.py`

**Usage:**
- `fg_clamps()` - Returns per-trade and book-level caps based on FG regime
- `fg_clamps_for_hedge()` - Hedge-specific sentiment clamps
- Adjusts sizing based on Fear/Greed index and sentiment
- Extreme zones reduce sizing (0.6x)
- Low confidence reduces sizing
- Hard cap: 5% equity per trade

**Category:** **Risk overlay**  
**Risk:** **MEDIUM** - Used to adjust sizing, but only **reduces** risk, never increases it

**Key Constraint:**  
- Sentiment can only **reduce** size (tighten risk)
- Sentiment can never **increase** size beyond what non-sentiment logic would choose
- Hard cap of 5% equity per trade regardless of sentiment

---

### Consensus Aggregation (ALLOWED)

**File:** `merid/swarm/consensus_aggregator.py` (lines 666-668)

**Usage:**
- Uses `bus.get_context(asset, timeframe)` to get sentiment context
- Aggregates swarm opinions with market context
- Generates `InsightObject` for UI/socials/reflection

**Category:** **Observability / Consensus**  
**Risk:** **LOW** - Used for consensus aggregation and UI display

---

### API Endpoints (ALLOWED)

**File:** `web/api/kalshi_api.py`

**Usage:**
- `get_market_mood()` - Get current fear/greed index
- `get_all_market_moods()` - Get all market moods
- `get_fear_greed_index()` - Get fear/greed for specific asset
- `get_context_health()` - Get context health status

**Category:** **Observability**  
**Risk:** **LOW** - Read-only API endpoints for monitoring

---

### WebSocket Bridge (ALLOWED)

**File:** `merid/event_venues/kalshi/ws_bridge.py` (lines 1377, 1406)

**Usage:**
- Feeds Kalshi market data into MarketMoodBus for sentiment analysis
- "CRITICAL FIX: Feed Kalshi market data into MarketMoodBus"

**Category:** **Data ingestion**  
**Risk:** **LOW** - Only feeds data into MarketMoodBus, does not use it for execution

---

## 4. MarketMoodBus in Execution - Critical Analysis

### Current State: NO DIRECT EXECUTION USE

**Finding:** MarketMoodBus is **NOT** used directly in execution logic

**Evidence:**
- No usage found in `merid/prediction/strategy.py` for execution decisions
- No usage found in `merid/event_venues/kalshi/order_router.py` for execution decisions
- No usage found in `merid/event_venues/kalshi/position_sizer.py` for sizing (uses `SentimentVolService` instead)

### Indirect Execution Use via SentimentVolService

**File:** `merid/prediction/risk/sentiment_vol_service.py`

**Usage:**
- `get_sizing_multiplier()` - Returns sizing multiplier based on sentiment and volatility
- Used by position sizer to adjust size
- Implements contrarian sizing (reduce size in extreme greed, increase in extreme fear)

**Category:** **Risk overlay**  
**Risk:** **MEDIUM** - Used to adjust sizing, but only **reduces** risk

**Key Constraint:**
- Sentiment can only **reduce** size (tighten risk)
- Sentiment can never **increase** size beyond what non-sentiment logic would choose

---

## 5. Root Cause of Terminal Phase Ban Disable

**Analysis:**

The comment says: "Blocking all trades due to neutral sentiment (MarketMoodBus issue)"

**Hypothesis:**
1. MarketMoodBus was returning neutral sentiment (fg_index = 50) for all assets
2. The terminal phase ban was checking MarketMoodBus sentiment
3. Neutral sentiment was causing the ban to block ALL terminal phase trades
4. To unblock trading, the ban was disabled

**Critical Flaw:**
- The terminal phase ban should **NOT** depend on MarketMoodBus sentiment
- The ban should be a hard rule based on time-to-expiry and edge only
- MarketMoodBus should never be able to relax or disable a hard risk rule

**Correct Design:**
```python
# TERMINAL PHASE BAN - Hard rule, independent of sentiment
if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
    logger.warning(...)
    return StrategySignal(...)  # BLOCKED

# Sentiment can be used for sizing adjustments AFTER the hard rule passes
# But sentiment can never re-enable a blocked trade
```

---

## 6. Classification Table

| Location / Pattern | Category | Action | Risk |
| --- | --- | --- | --- |
| `merid/signals/kalshi_signals.py` - Signal generation | Model feature | OK if backtested | LOW |
| `merid/sentiment/btc_risk_dial.py` - Risk sizing | Risk overlay | OK if only reduces risk | MEDIUM |
| `merid/swarm/consensus_aggregator.py` - Consensus | Observability | Harmless | LOW |
| `web/api/kalshi_api.py` - API endpoints | Observability | Harmless | LOW |
| `merid/event_venues/kalshi/ws_bridge.py` - Data ingestion | Data ingestion | Harmless | LOW |
| `merid/prediction/risk/sentiment_vol_service.py` - Sizing multiplier | Risk overlay | OK if only reduces risk | MEDIUM |
| `merid/prediction/strategy.py` - Terminal phase ban (disabled) | Execution rule | **CRITICAL FIX NEEDED** | **HIGH** |

---

## 7. "No Sentiment in Execution" Rule

### Allowed Uses

**Sentiment MAY:**
1. Contribute to **signals** as a feature (if backtested rigorously)
2. Inform **risk overlays** that **tighten** risk (reduce size, disable strategies) in extreme conditions
3. Be used for **observability** (logging, monitoring, UI display)
4. Be used for **consensus aggregation** (swarm intelligence)

### Forbidden Uses

**Sentiment MUST NEVER:**
1. Lower minimum required edge
2. Override time-to-expiry rules
3. Increase size beyond what non-sentiment logic would choose
4. Re-enable trading when a risk control would otherwise block it
5. Disable or relax hard risk rules (like terminal phase ban)

---

## 8. Recommended Actions

### Immediate (Critical)

1. **Re-enable terminal phase trading ban** in `merid/prediction/strategy.py`
   - Remove MarketMoodBus dependency from the ban
   - Make it a hard rule based on time-to-expiry and edge only
   - Add assertion: "Sentiment MUST NOT relax expiry-phase edge thresholds"

### High Priority

2. **Add guard checks in critical modules**
   - In sizing/entry filters: Assert sentiment never increases risk
   - Add test: MarketMoodBus "extremely positive" near expiry with edge < 3% → no trade

3. **Review disabled files** for risk bypasses
   - `merid_core/kalshi/execution_pipeline.py` (DISABLED)
   - `merid_core/kalshi/rest_client.py` (DISABLED)

4. **Review legacy code paths** for risk bypasses
   - `trading/_legacy/` directory
   - Legacy adapter patterns in `trading/adapters/`

### Medium Priority

5. **Implement exponential backoff** for retries
6. **Implement true idempotency** using client_tag with deduplication
7. **Add automated signal determinism checks** via replay
8. **Add automated sizing validation** job

---

## 9. Code Fixes

### Fix 1: Re-enable Terminal Phase Ban (Critical)

**File:** `merid/prediction/strategy.py` (lines 1632-1655)

**Current Code:**
```python
# TERMINAL PHASE BAN - Block trades in last hour when model has weak edge
# CRITICAL FIX: Prevent bad trades at tail end of contracts
# TEMPORARILY DISABLED (2026-05-09): Blocking all trades due to neutral sentiment (MarketMoodBus issue)
# Re-enable after MarketMoodBus context population is fixed
# if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
#     logger.warning(...)
#     return StrategySignal(...)
```

**Recommended Fix:**
```python
# TERMINAL PHASE BAN - Block trades in last hour when model has weak edge
# CRITICAL: Hard rule independent of sentiment - sentiment MUST NOT relax expiry-phase edge thresholds
# This rule prevents bad trades at tail end of contracts due to time decay and liquidity issues
if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
    logger.warning(
        "[TERMINAL-PHASE-BLOCKED] %s | phase=terminal prob_edge=%.3f < 0.03 | asset=%s | BLOCKED: weak edge in terminal phase",
        snapshot.market_id, prob_edge, asset,
    )
    return StrategySignal(
        market_id=snapshot.market_id,
        action=SignalAction.NO_ACTION,
        side=best.side,
        contracts=0,
        edge=best,
        phase=phase,
        reason=f"blocked: terminal phase with weak prob_edge={prob_edge:.3f} (min 0.03 required in terminal)",
        correlation_id=correlation_id,
        eval_context={
            "prob_edge": str(prob_edge),
            "phase": str(phase),
            "block": "terminal_phase_weak_edge",
        },
    )
```

**Key Changes:**
- Remove MarketMoodBus dependency
- Make it a hard rule
- Add explicit comment about sentiment not relaxing expiry-phase thresholds
- Re-enable the block

---

### Fix 2: Add Guard Check for Sentiment Sizing

**File:** `merid/prediction/risk/sentiment_vol_service.py` (or wherever sizing multiplier is used)

**Recommended Addition:**
```python
# GUARD: Sentiment must never increase risk beyond non-sentiment baseline
# Sentiment can only reduce size (tighten risk), never increase it
assert sizing_multiplier <= 1.0, f"Sentiment sizing multiplier {sizing_multiplier} > 1.0 - sentiment must not increase risk"
```

---

### Fix 3: Add Test for Terminal Phase Ban

**File:** Create new test file `tests/prediction/test_terminal_phase_ban.py`

**Recommended Test:**
```python
def test_terminal_phase_ban_blocks_weak_edge():
    """Test that terminal phase ban blocks trades with weak edge regardless of sentiment."""
    # Create scenario: extreme positive sentiment near expiry with edge < 3%
    # Assert: NO trade is produced
    # This ensures sentiment cannot relax the terminal phase ban
```

---

## 10. Conclusion

**Critical Issue:** Terminal phase trading ban disabled due to MarketMoodBus issue. This is a high-risk configuration error.

**Root Cause:** The ban was incorrectly dependent on MarketMoodBus sentiment. When MarketMoodBus returned neutral sentiment, it blocked all trades, so the ban was disabled to restore trading.

**Correct Design:** The terminal phase ban should be a hard rule independent of sentiment. Sentiment should never be able to relax or disable hard risk rules.

**MarketMoodBus Usage:** Currently used in appropriate ways (signal generation, risk sizing that only reduces risk, observability). No direct execution use found.

**Recommendation:** Re-enable the terminal phase ban immediately, removing any MarketMoodBus dependency. Add guard checks to ensure sentiment never increases risk or relaxes hard rules.

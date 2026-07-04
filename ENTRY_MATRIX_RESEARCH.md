# Entry Matrix Research and Implementation Plan
**Date:** 2026-07-02  
**Scope:** Kalshi 15-minute crypto YES/NO markets (BTC, ETH, SOL, XRP, DOGE)

---

## Current Setup vs Research Recommendations

### Research Recommendations (TheLines, DefiRate, Perplexity)

**Best Entry Sweet Spots:**
- **50c to 55c**: Cleanest entries with strong signal, convexity still available
- **55c to 65c**: Good when move is established, continuation-focused
- **Avoid > 70c**: Payout too small, fees/slippage matter more
- **Avoid < 15c**: Deep OTM longshots with poor expected returns (our fix)

**Timing Rules:**
- **Entry zone**: First 3-8 minutes after clean impulse/pullback
- **Avoid first minute**: Initial price discovery noisy unless spot/Kalshi tightly aligned
- **Avoid last 2-4 minutes**: Unless mean-reversion or locked-in continuation pattern
- **Selective timing**: Edge in quality, not frequency

**Asset-Specific Behavior:**
| Asset | Best Use Case | Entry Style |
|-------|--------------|-------------|
| BTC | Most stable/liquid | Trend-follow, smaller spreads |
| ETH | Similar to BTC, faster | Momentum continuation after strong candle |
| SOL | More volatile | Pullback re-entry > breakout chasing |
| XRP | Range breaks | Compression then expansion |
| DOGE | Fastest/noisiest | Stricter confirmation, smaller size |

**Practical Entry Rules:**
1. Trade only when spot momentum and Kalshi price direction agree
2. Prefer entries below 65c when candle not overextended
3. Use BTC/ETH for highest-quality signals
4. Treat SOL/XRP/DOGE as higher-volatility confirmation names
5. Skip entries when remaining edge < fees + noise

### Current Setup Analysis

**Price Range:**
- **Current**: 15-70c (fixed from 5-70c)
- **Research**: 50-65c optimal, avoid >70c
- **Gap**: We allow 15-49c entries (should add edge multiplier for deep OTM)

**Time Windows:**
- **Current**: No time-based entry windows defined
- **Research**: 3-8 minutes optimal, avoid first/last minutes
- **Gap**: Missing time-based entry filters

**Momentum Agreement:**
- **Current**: Spot velocity signal used, but no explicit Kalshi price direction check
- **Research**: Trade only when spot momentum and Kalshi price direction agree
- **Gap**: Missing momentum agreement validation

**Per-Asset Thresholds:**
- **Current**: Per-asset edge thresholds in YAML (BTC/ETH: 3%, SOL: 5%, XRP: 4%, DOGE: 5%)
- **Research**: Different thresholds per asset based on volatility
- **Status**: ✅ Already implemented

**Entry Frequency:**
- **Current**: 5-second cadence, no frequency limits per window
- **Research**: Selective timing, not trading every flicker
- **Gap**: Missing entry frequency limits

---

## Proposed Entry Matrix

### Price Bands with Edge Multipliers

| Price Band | BTC Edge Multiplier | ETH Edge Multiplier | SOL Edge Multiplier | XRP Edge Multiplier | DOGE Edge Multiplier |
|------------|-------------------|-------------------|-------------------|-------------------|-------------------|
| 15-29c | 2.0x (very conservative) | 2.0x | 2.5x | 2.5x | 3.0x |
| 30-49c | 1.5x (conservative) | 1.5x | 2.0x | 2.0x | 2.5x |
| 50-55c | 1.0x (baseline) | 1.0x | 1.0x | 1.0x | 1.0x |
| 56-65c | 1.0x (baseline) | 1.0x | 1.0x | 1.0x | 1.0x |
| 66-70c | 1.5x (conservative) | 1.5x | 2.0x | 2.0x | 2.5x |

**Rationale:**
- 50-65c: Sweet spot, baseline edge requirements
- 15-49c: Deep OTM, require higher edge due to poor convexity
- 66-70c: Near max price, require higher edge due to small payout
- Higher volatility assets (SOL, DOGE) need stricter multipliers

### Time Left Bands with Entry Rules

| Time Left (minutes) | Entry Rule | Rationale |
|---------------------|------------|-----------|
| 0-2 | SKIP (unless mean-reversion or locked-in continuation) | Too late, edge decay dominates |
| 2-4 | REDUCED (1.5x edge multiplier) | Late entries need stronger conviction |
| 4-8 | OPTIMAL (baseline) | Sweet spot for edge to play out |
| 8-12 | OPTIMAL (baseline) | Good window for momentum continuation |
| 12-15 | SKIP (first minute) | Initial price discovery noisy |

**Implementation:**
- Add `minutes_to_expiry` check in signal generation
- Apply edge multiplier based on time band
- Skip first minute unless spot/Kalshi tightly aligned

### Momentum Agreement Check

**Rule:** Trade only when spot velocity direction matches Kalshi price direction

**Implementation:**
- Spot velocity > 0 (up) → Only consider BUY YES
- Spot velocity < 0 (down) → Only consider BUY NO
- If Kalshi best bid/ask doesn't align with spot direction → SKIP

### Per-Asset Entry Quality Tiers

| Asset | Quality Tier | Max Entries/Window | Position Size | Confirmation Required |
|-------|--------------|-------------------|---------------|----------------------|
| BTC | Tier 1 (highest) | 3 | 2 contracts | Standard |
| ETH | Tier 1 (highest) | 3 | 2 contracts | Standard |
| SOL | Tier 2 (medium) | 2 | 1 contract | OBI + ADX |
| XRP | Tier 2 (medium) | 2 | 1 contract | OBI + ADX |
| DOGE | Tier 3 (lowest) | 1 | 1 contract | OBI + ADX + Volume |

**Rationale:**
- BTC/ETH: Highest quality, allow more entries
- SOL/XRP: Medium quality, limit entries, require confirmation
- DOGE: Lowest quality, single entry, strictest confirmation

---

## Implementation Plan

### Phase 1: Price Band Edge Multipliers
1. Add `price_band_edge_multiplier` function in agent_grid_15m.py
2. Apply multiplier to min_edge thresholds based on current price
3. Add test for price band multiplier logic

### Phase 2: Time Window Entry Rules
1. Add `time_left_band` function to classify time remaining
2. Apply edge multiplier based on time band
3. Skip first minute and last 2 minutes by default
4. Add test for time window logic

### Phase 3: Momentum Agreement Check
1. Add `momentum_agreement_check` in signal generation
2. Compare spot velocity direction with Kalshi price direction
3. Skip if directions disagree
4. Add test for momentum agreement

### Phase 4: Per-Asset Entry Limits
1. Add `max_entries_per_window` per asset in YAML
2. Track entries per asset in rolling window
3. Skip if limit exceeded
4. Add test for entry limits

### Phase 5: Documentation and Testing
1. Document all changes in ENTRY_MATRIX_IMPLEMENTATION.md
2. Add comprehensive tests for all new logic
3. Run full test suite
4. Restart server with new configuration
5. Monitor trade execution

---

## Current Configuration Summary

**Price Range:** 15-70c (aligned with research on avoiding deep OTM)
**Edge Thresholds:** Per-asset (BTC/ETH: 3%, SOL: 5%, XRP: 4%, DOGE: 5%)
**Time Windows:** Not implemented (gap)
**Momentum Agreement:** Partial (spot velocity used, no Kalshi direction check)
**Entry Limits:** Not implemented (gap)
**Asset Tiers:** Not implemented (gap)

**Priority Gaps to Address:**
1. Time window entry rules (high priority)
2. Momentum agreement check (high priority)
3. Price band edge multipliers (medium priority)
4. Per-asset entry limits (medium priority)

# Deep Audit: Momentum Scalping + Hedging System
## MERID Crypto 15m Strategy Audit Report
**Date:** May 2, 2026  
**Auditor:** Claude (Senior Quantitative Trading Architect)  
**Scope:** BTC, ETH, SOL, XRP, DOGE 15m momentum scalping with Kalshi integration

---

## Executive Summary

This audit examines the MERID system's momentum scalping logic, hedging architecture, and their interactions across five crypto assets (BTC, ETH, SOL, XRP, DOGE) on 15-minute timeframes via Kalshi prediction markets.

**Verdict:** The system has solid foundational components but exhibits **critical architectural conflicts** between scalping and hedging that must be resolved before production deployment. The hedging system is currently **under-developed** relative to the sophisticated scalping stack.

---

## 1. Current System Architecture

### 1.1 Momentum Scalping Stack (`merid/signals/crypto_15m_indicators.py`)

**Signal Architecture:**
- **Trend Filter:** EMA(50) as primary regime filter on 1m price feeds
- **Entry Triggers:** EMA(5)/EMA(20) crossover with RSI(8) confirmation
- **Momentum:** MACD(8,21,5) scalping-tilted configuration
- **Vol Gate:** ATR(14) with 0.03% min-move threshold, realized vol bands (15%-120% annualized)
- **Chop Filters:** 
  - 3+ consecutive closes above/below EMA trend
  - MACD histogram persistence (3+ bars same sign)
  - Histogram magnitude minimum (0.01% of price)

**Parameters by Asset:**
```python
# Current (uniform across assets - PROBLEM IDENTIFIED)
ema_trend_period: int = 50      # All assets
rsi_period: int = 8             # All assets  
macd_fast: int = 8              # All assets
atr_min_move_pct: float = 0.0003 # 0.03% for all

# Asset-specific betas (BTC-anchored model)
PRIOR_BETAS = {
    "ETH":  {"15m": 1.15, "1h": 1.20},
    "SOL":  {"15m": 1.40, "1h": 1.50},  # Higher beta
    "XRP":  {"15m": 1.10, "1h": 1.25},
    "DOGE": {"15m": 1.30, "1h": 1.45},  # Highest beta
}
```

**Key Gap:** No asset-specific indicator tuning. SOL/DOGE need shorter lookbacks due to higher volatility and faster mean-reversion tendencies.

### 1.2 Position Sizing & Risk Controls

**Current Stack (Multiple Layers):**

| Layer | Component | Key Parameters |
|-------|-----------|----------------|
| 1 | TopN Allocator | 1-2% cycle risk, max 3 edges |
| 2 | KalshiRiskEngine | Quarter-Kelly (0.25), 1% per-trade max |
| 3 | Per-Asset Caps | BTC/ETH: 25%, SOL/XRP/DOGE: 20% |
| 4 | Global Exposure | 50% max across all crypto |
| 5 | Drawdown | 15% halt, 8% reduce (tightened from 20%/10%) |
| 6 | Cycle Drawdown | 15-min rolling cycles with 3-7% thresholds |

**Edge Requirements (Phase-Aware):**
```python
min_edge_early:     1.5%  # >24h to expiry
min_edge_mid:       1.2%  # 4-24h
min_edge_late:      1.0%  # 1-4h  
min_edge_terminal:  0.8%  # <1h
```

**Fee-Aware EV:**
- Kalshi fee formula: `ceil(0.07 * C * P * (1-P) * 100)`
- Mid-curve penalty (0.45-0.55): 1.25x edge multiplier
- Penny contract penalty (≤5¢): 2.0x edge multiplier

### 1.3 Hedging System (`merid/hedging/`)

**Current Implementation:**
```python
# From merid/hedging/config.py
@dataclass
class TimeframeHedgeRule:
    max_net_exposure_pct_of_slice: float = 10.0  # % of slice
    target_hedge_ratio: float = 0.5                # 50% hedge
    prefer_same_timeframe: bool = True
```

**Asset Slicing:**
- Default: 10% of bankroll per asset
- Per-trade: 1% of slice
- Max drawdown per slice: 3%

**Status:** The hedging engine exists but has **no integration with the scalping system**. It operates as a separate module with no automatic trigger linkage to scalping state or drawdown conditions.

### 1.4 Market Regime Detection

**MarketRegimeGate (`merid/market_regime/gate.py`):**
- Evaluates basket flatness across all assets
- Returns: ALLOW / REDUCE / BLOCK
- Shadow mode available for testing

**BTC Risk Dial (`merid/sentiment/btc_risk_dial.py`):**
- Fear/Greed index clamps (extreme fear/greed = 60% size reduction)
- ATR-based volatility sizing
- Confidence scaling (low confidence = reduced size)

---

## 2. Conflict & Contradiction Analysis

### 🔴 CRITICAL CONFLICT 1: No Hedging Trigger Integration

**Issue:** The `CryptoHedgeEngine.compute_hedge_orders()` exists but is **never automatically invoked** from the scalping cycle. The CT (`kalshi_continuous_trader.py`) has no call to the hedge engine.

**Evidence:**
```python
# kalshi_continuous_trader.py ~1200+ lines
# No import of: from merid.hedging.engine import CryptoHedgeEngine
# No call to: hedge_engine.compute_hedge_orders()
```

**Impact:** Hedging is effectively dead code. Drawdown protection relies solely on the scalping system's internal drawdown halt (which kills all trading, rather than hedging exposure).

### 🔴 CRITICAL CONFLICT 2: Conflicting Drawdown Philosophies

| System | Drawdown Trigger | Action |
|--------|-----------------|--------|
| KalshiRiskEngine | 15% from peak | HALT all trading |
| CycleDrawdown | 3-7% per 15m cycle | RESTRICT new risk |
| HedgeConfig | 40% max (never used) | No automatic action |

**Contradiction:** When drawdown hits 15%, the system halts entirely rather than transitioning to hedging mode. There's no intermediate "hedge-active" state.

### 🔴 CRITICAL CONFLICT 3: Cross-Asset Beta vs. Independent Sizing

**Issue:** The `btc_anchored_move.py` model computes cross-asset betas (SOL = 1.40x BTC), but the sizing logic treats each asset independently.

**Example:**
- If BTC moves +1%, SOL expected move = +1.40%
- Current system may size SOL position same as BTC despite higher expected move
- No correlation-based position adjustment

### 🟡 MEDIUM CONFLICT 4: Sentiment Filter May Block Hedging Opportunities

The `btc_risk_dial.py` applies FG-based clamps:
- Extreme fear (≤20): Reduces size by 60%
- But extreme fear is precisely when hedging should be MAXIMUM

**Conflict:** The same sentiment that should trigger hedge protection instead reduces all position sizes, including hedge positions.

### 🟡 MEDIUM CONFLICT 5: Time Horizon Mismatch

| Component | Time Horizon |
|-----------|--------------|
| 15m Indicators | 1m feeds, 15m evaluation |
| Kalshi Contracts | 15m, 1h, daily, weekly |
| Cycle Drawdown | 15m cycle |
| Portfolio Drawdown | Daily/Session |

**Gap:** No coherent multi-timeframe risk aggregation. A position can be within 15m cycle limits but violate daily portfolio limits.

---

## 3. Optimal Momentum Scalping Design (15m)

### 3.1 Recommended Signal Architecture

```python
# Asset-specific parameter tuning
ASSET_CONFIGS = {
    "BTC": {
        # Conservative - slower, more established trends
        ema_trend_period: 50,
        ema_fast: 5,
        ema_slow: 20,
        rsi_period: 8,
        atr_mult_stop: 1.5,      # 1.5x ATR for stops
        min_edge_threshold: 0.015,  # 1.5%
        chop_atr_min: 0.0003,    # 0.03%
    },
    "ETH": {
        # Similar to BTC, slightly more aggressive
        ema_trend_period: 45,
        ema_fast: 5,
        ema_slow: 18,
        rsi_period: 8,
        atr_mult_stop: 1.6,
        min_edge_threshold: 0.016,
        chop_atr_min: 0.00035,
    },
    "SOL": {
        # Faster, higher volatility - shorter lookbacks
        ema_trend_period: 35,    # Faster trend detection
        ema_fast: 4,
        ema_slow: 15,
        rsi_period: 6,           # More responsive
        atr_mult_stop: 2.0,      # Wider stops for vol
        min_edge_threshold: 0.020, # Higher edge bar (more false signals)
        chop_atr_min: 0.0005,    # Higher chop threshold
    },
    "XRP": {
        # Medium speed, news-driven
        ema_trend_period: 40,
        ema_fast: 5,
        ema_slow: 16,
        rsi_period: 7,
        atr_mult_stop: 1.8,
        min_edge_threshold: 0.018,
        chop_atr_min: 0.0004,
    },
    "DOGE": {
        # Fastest, meme-driven, most noise
        ema_trend_period: 30,    # Very fast
        ema_fast: 3,
        ema_slow: 12,
        rsi_period: 5,
        atr_mult_stop: 2.5,      # Widest stops
        min_edge_threshold: 0.025, # Highest edge requirement
        chop_atr_min: 0.0006,    # Most chop filtering
    }
}
```

### 3.2 Entry/Exit Rules

**Entry Conditions (ALL must be true):**
1. Price above EMA(trend) for longs, below for shorts
2. EMA(fast) crossed EMA(slow) in direction ≤ 3 bars ago
3. RSI confirms (30-70 band, not extreme)
4. MACD histogram same sign for 3+ bars
5. ATR/move_gate_ok (not choppy)
6. Kalshi implied prob provides 1.5%+ edge after fees
7. Volume/depth check passes

**Exit Conditions (ANY triggers exit):**
1. Stop: 1.5-2.5x ATR (asset-specific) from entry
2. Profit target: 3:1 reward/risk minimum
3. Time: Maximum 8 bars (2 hours) holding period
4. Trend reversal: Price crosses back through EMA(trend)
5. Edge decay: Kalshi implied prob moves against position by 50% of initial edge

### 3.3 Risk Management Per Trade

```python
# Position sizing formula (conservative variant)
def calculate_position_size(edge, confidence, atr, price, asset):
    base_risk = 0.01  # 1% of bankroll
    
    # Kelly adjustment
    kelly = edge / (1 - edge)  # Simplified
    kelly_fraction = 0.25  # Quarter-Kelly
    
    # Asset-specific vol adjustment
    vol_mult = ASSET_CONFIGS[asset].vol_adjustment  # 0.8-1.2
    
    # Confidence scaling
    conf_mult = 0.5 + 0.5 * confidence
    
    # Stop distance in dollars
    atr_mult = ASSET_CONFIGS[asset].atr_mult_stop
    stop_dollars = atr * atr_mult
    
    # Contracts = (bankroll * base_risk * kelly_fraction * vol_mult * conf_mult) / stop_dollars
    return int((bankroll * base_risk * kelly_fraction * vol_mult * conf_mult) / stop_dollars)
```

---

## 4. Hedging System Design

### 4.1 Clear State Machine

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   State A   │─────▶│   State B   │─────▶│   State C   │─────▶│   State D   │
│ SCALP-ONLY  │      │SCALP+PARTIAL│      │ HEDGE-ONLY  │      │    FLAT     │
│             │◀─────│   HEDGE     │◀─────│             │◀─────│             │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
```

### 4.2 State Definitions

| State | Name | Description | Net Beta Target | New Scalp Entries | Hedge Activity |
|-------|------|-------------|-----------------|-------------------|----------------|
| A | SCALP-ONLY | Normal momentum scalping | 0.8-1.2 per active asset | Allowed | None |
| B | SCALP+HEDGE | Drawdown protection active | 0.3-0.6 per asset | Allowed (reduced size) | Active partial hedge |
| C | HEDGE-ONLY | Risk-off, preserve capital | 0.0-0.2 | BLOCKED | Full hedge maintained |
| D | FLAT | No positions | 0.0 | BLOCKED | All hedges unwound |

### 4.3 Transition Rules

**A → B (Add Hedge):**
- Daily drawdown exceeds 5%, OR
- Session loss exceeds 3%, OR
- 15m cycle enters RESTRICTED status, OR
- VIX-equivalent (BTC vol) spikes > 2 standard deviations, OR
- Correlation breakdown detected (alts decouple from BTC in risk-off)

**B → C (Scalping Off):**
- Daily drawdown exceeds 10%, OR
- Consecutive losing trades (3+), OR
- Liquidity degradation (spreads > 2x normal), OR
- Manual risk-off signal

**C → B or A (Normalization):**
- Drawdown recovered to < 50% of max, AND
- 30-minute stabilization period, AND
- Volatility normalized

**Hysteresis:** Minimum 15 minutes in any state before transition back to less restrictive state.

### 4.4 Kalshi-Based Hedging

**Instruments:**

| Asset | Primary Hedge | Secondary Hedge |
|-------|--------------|-----------------|
| BTC | KXBTC-15M opposite direction | KXBTC-1H for longer hedge |
| ETH | KXETH-15M opposite + BTC-15M | KXETH-1H |
| SOL | KXSOL-15M (high beta = larger position) | BTC-15M (beta-hedge) |
| XRP | KXXRP-15M opposite | BTC-15M (if correlation high) |
| DOGE | KXDOGE-15M opposite (rare, high edge bar) | DOGE/BTC ratio proxy |

**Sizing:**
```python
# Hedge sizing formula
def hedge_size(net_delta_cents, asset, timeframe, config):
    # Base: Target hedge ratio from config (e.g., 0.5 = 50%)
    base_hedge = abs(net_delta_cents) * config.target_hedge_ratio
    
    # Beta adjustment for cross-asset hedging
    if asset != "BTC":
        beta = get_beta(asset, timeframe)  # From btc_anchored_move
        base_hedge = base_hedge / beta  # Adjust for beta
    
    # Drawdown scaling: More drawdown = more hedge
    dd_pct = current_drawdown_pct()
    if dd_pct > 0.10:  # >10% drawdown
        base_hedge *= 1.5  # 150% of target (over-hedge)
    elif dd_pct > 0.05:  # >5% drawdown  
        base_hedge *= 1.0  # 100% of target
    else:
        base_hedge *= 0.5  # 50% of target (light hedge)
    
    return base_hedge
```

---

## 5. Implementation Checklist

### Phase 1: Critical Fixes (Week 1)

- [ ] **P1.1** Wire hedge engine into CT cycle
  - File: `merid/trading/kalshi_continuous_trader.py`
  - Add: `from merid.hedging.engine import CryptoHedgeEngine`
  - Add: Call to `compute_hedge_orders()` after sizing, before execution

- [ ] **P1.2** Implement state machine in CT
  - Add state enum: `SCALP_ONLY, SCALP_HEDGE, HEDGE_ONLY, FLAT`
  - Add transition logic with hysteresis timers
  - Add state to status output for monitoring

- [ ] **P1.3** Fix drawdown coordination
  - Unify KalshiRiskEngine, CycleDrawdown, and HedgeConfig thresholds
  - Set consistent: 5% warning, 10% hedge-active, 15% halt
  - Remove conflicting 40% HedgeConfig max_drawdown

### Phase 2: Signal Enhancement (Week 2)

- [ ] **P2.1** Asset-specific indicator configs
  - Create `ASSET_CONFIGS` dataclass in `crypto_15m_indicators.py`
  - Implement parameter lookup by asset symbol
  - Add beta-aware position scaling

- [ ] **P2.2** Cross-asset beta integration
  - Wire `btc_anchored_move.py` into sizing
  - Adjust SOL/DOGE sizes by 1/beta to normalize volatility exposure
  - Add correlation-aware concentration limits

- [ ] **P2.3** FVG-based entry refinement
  - The FVG detection exists but isn't used for entries
  - Add FVG retest confirmation as entry trigger
  - Use FVG as dynamic support/resistance for stop placement

### Phase 3: Kalshi Integration (Week 3)

- [ ] **P3.1** Market selector for hedging
  - Implement hedge market selection logic in `engine.py`
  - Prefer same-asset, same-timeframe contracts
  - Fallback to adjacent timeframes if liquidity insufficient

- [ ] **P3.2** Hedge execution via order_router
  - Tag hedge orders with `source="HEDGE_ENGINE"`
  - Ensure hedge orders bypass certain scalping-specific gates
  - Add hedge PnL tracking separate from alpha PnL

- [ ] **P3.3** Fee-aware hedge sizing
  - Hedge only when expected protection value > 2x fees
  - Skip hedging for small positions (< $5 exposure)
  - Dynamic hedge ratio based on market implied costs

### Phase 4: Testing & Monitoring (Week 4)

- [ ] **P4.1** State machine unit tests
  - Test all state transitions
  - Verify hysteresis delays
  - Test edge cases (rapid flip conditions)

- [ ] **P4.2** Hedge effectiveness backtests
  - Simulate hedge performance during drawdown periods
  - Measure reduction in max drawdown vs. cost of hedging
  - Optimize hedge ratio by asset

- [ ] **P4.3** Monitoring dashboard updates
  - Add current state indicator (A/B/C/D)
  - Show hedge exposure separate from alpha exposure
  - Display net beta by asset and portfolio

---

## Appendix A: State Machine Diagram

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                      MARKET REGIME                          │
                    │  (Flat/Chop detected via MarketRegimeGate)                 │
                    │                      │                                      │
                    │                      ▼                                      │
                    │              ┌───────────────┐                               │
                    │              │    BLOCK      │──────────────┐              │
                    │              │   (No Trade)  │              │              │
                    │              └───────────────┘              │              │
                    │                     ▲                         │              │
                    └─────────────────────┼─────────────────────────┘              │
                                          │                                        │
                                          ▼                                        │
┌─────────────┐    Drawdown < 5%     ┌─────────────┐    Drawdown ≥ 5%     ┌─────────────┐
│   State D   │◀──────────────────────│   State A   │──────────────────────▶│   State B   │
│    FLAT     │                       │ SCALP-ONLY  │                       │ SCALP+HEDGE │
│  (No Pos)   │──────────────────────▶│  (Normal)   │◀──────────────────────│ (Protected) │
└─────────────┘    Re-entry Signal    └─────────────┘    Recovery < 50%     └─────────────┘
       ▲                                                          │                │
       │                                                          │                │
       │                    Drawdown ≥ 10%                        │                │
       └───────────────────────────────────────────────────────────┘                │
                                                                                    │
                                                                   Drawdown ≥ 10%   ▼
                                                            ┌─────────────────────────────┐
                                                            │         State C            │
                                                            │       HEDGE-ONLY           │
                                                            │   (Scalping Disabled)      │
                                                            │                            │
                                                            │  • No new scalp entries     │
                                                            │  • Maintain/reduce hedges │
                                                            │  • Net beta target: 0.0   │
                                                            └─────────────────────────────┘

Transition Conditions:
────────────────────
A → B:  Daily DD > 5% OR Cycle RESTRICTED OR Vol spike > 2σ
B → C:  Daily DD > 10% OR 3+ consecutive losses OR Manual halt
C → B:  DD recovered > 50% AND 30min stabilization
B → A:  DD < 3% AND vol normalized AND 15min hysteresis
C → D:  All positions closed AND no new signals (flat intent)
D → A:  Re-entry signal (trend established, low vol)
```

---

## Appendix B: Parameter Reference Tables

### B.1 Asset-Specific Scalping Parameters (Recommended)

| Asset | EMA Trend | EMA Fast | EMA Slow | RSI | ATR Stop Mult | Min Edge | Beta |
|-------|-----------|----------|----------|-----|---------------|----------|------|
| BTC | 50 | 5 | 20 | 8 | 1.5x | 1.5% | 1.00 |
| ETH | 45 | 5 | 18 | 8 | 1.6x | 1.6% | 1.15 |
| SOL | 35 | 4 | 15 | 6 | 2.0x | 2.0% | 1.40 |
| XRP | 40 | 5 | 16 | 7 | 1.8x | 1.8% | 1.10 |
| DOGE | 30 | 3 | 12 | 5 | 2.5x | 2.5% | 1.30 |

### B.2 State-Specific Risk Limits

| State | Max Positions | Per-Trade Risk | Total Exposure | New Entries | Hedge Ratio |
|-------|---------------|----------------|----------------|-------------|-------------|
| A (SCALP-ONLY) | 8 | 1.0% | 50% | ✓ | 0% |
| B (SCALP+HEDGE) | 5 | 0.6% | 30% | ✓ (reduced) | 50% |
| C (HEDGE-ONLY) | 0 | 0% | 20% | ✗ | 100% |
| D (FLAT) | 0 | 0% | 0% | ✗ | 0% |

### B.3 Kalshi-Specific Constraints

| Parameter | Value | Notes |
|-----------|-------|-------|
| Min Contract Price | 2¢ | Penny markets |
| Max Contract Price | 65¢ | Conservative cap |
| Fee per Contract | ~2¢ | 7% of P*(1-P) |
| Max Position/Market | 8 contracts | Per-ticker limit |
| Max Open Positions | 8 total | Across all markets |
| Series Exposure Mult | 0.80 | 15m timeframe discount |

---

## Appendix C: Code References

### C.1 Key Files Reviewed

| File | Lines | Purpose |
|------|-------|---------|
| `merid/signals/crypto_15m_indicators.py` | 687 | Core indicator stack |
| `merid/trading/kalshi_continuous_trader.py` | 5796 | CT cycle logic |
| `merid/prediction/strategy.py` | 800+ | Signal evaluation |
| `merid/prediction/risk/kalshi_risk_engine.py` | 855 | Risk/sizing engine |
| `merid/hedging/engine.py` | 348 | Hedge computation |
| `merid/hedging/config.py` | 175 | Hedge parameters |
| `merid/event_venues/kalshi/cycle_drawdown.py` | 563 | 15m cycle management |
| `merid/sentiment/btc_risk_dial.py` | 843 | FG-based risk clamps |
| `merid/market_regime/gate.py` | 378 | Flatness detection |
| `merid/signals/btc_anchored_move.py` | 691 | Cross-asset beta model |
| `merid/trading/topn_allocator.py` | 1094 | Edge allocation |

### C.2 Critical Lines for Implementation

```python
# kalshi_continuous_trader.py - Add hedge call in cycle
# Around line 2000, after bankroll.calculate_order_size():

# NEW: Hedge computation
from merid.hedging.engine import CryptoHedgeEngine, get_hedge_engine
hedge_engine = get_hedge_engine()
hedge_orders = hedge_engine.compute_hedge_orders(
    exposure=exposure_snapshot,
    config=hedge_config,
    bankroll_cents=bankroll.balance_cents,
    market_catalog=catalog,
)
for h_order in hedge_orders:
    # Route through order_router with hedge tag
    intent = OrderIntent(
        ticker=h_order.target_ticker,
        side=h_order.side,
        count=h_order.count,
        price_cents=h_order.price_cents,
        source="HEDGE_ENGINE",
        client_tag=f"HEDGE_{h_order.hedge_reason}",
    )
    await route_order_async(intent)
```

---

**End of Audit Report**

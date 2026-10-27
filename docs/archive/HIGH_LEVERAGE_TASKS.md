# High Leverage Tasks — Momentum Scalping + Hedging System

Remaining critical work to complete the audit implementation. Ranked by risk × impact.

---

## 🔴 CRITICAL (Complete First)

### Task 1: Fix Sentiment Filter / Hedge Conflict (2-3 hours)
**Problem**: `btc_risk_dial.py` clamps position sizes when FG ≤ 25 (extreme fear), but this is exactly when hedging should *increase*.

**Current behavior**:
- Extreme fear (FG 15) → Size cap 60% reduction → Smaller positions
- Drawdown 5% → Hedging activates → But smaller positions mean less effective hedge

**Fix**: Decouple sentiment sizing from hedge sizing:
- Apply sentiment clamp to scalp-only sizing
- Hedge sizing uses raw exposure (not sentiment-clamped)
- Or: Hedge sizing increases as sentiment approaches extremes

**Files**: `merid/sentiment/btc_risk_dial.py`, `merid/trading/kalshi_continuous_trader.py` (sizing section)

---

### Task 2: Align KalshiRiskEngine Drawdown with Unified Config (2 hours)
**Problem**: `KalshiRiskConfig` uses hardcoded 20%/10% thresholds that conflict with unified 15%/8%.

**Current**:
```python
drawdown_halt_pct: float = 0.20      # 20% (unified: 15%)
drawdown_reduce_pct: float = 0.10    # 10% (unified: 8%)
```

**Fix**: Read from `UnifiedDrawdownConfig` singleton instead of hardcoded defaults.

**Files**: `merid/prediction/risk/kalshi_risk_engine.py`, `merid/risk/drawdown_config.py`

---

### Task 3: Align CycleDrawdownManager with Unified Config (2 hours)
**Problem**: 15-minute rolling drawdown uses variable 3-7% thresholds that aren't coordinated with the 5% hedge activation.

**Current**: 3%/5%/7% variable based on equity tiers
**Target**: Align with unified thresholds (warning at 3%, restrict at 5%)

**Fix**: Update `CycleDrawdownConfig` to reference `UnifiedDrawdownConfig` for threshold consistency.

**Files**: `merid/event_venues/kalshi/cycle_drawdown.py`

---

## 🟡 HIGH IMPACT (Complete Next)

### Task 4: Dynamic Beta from BTC-Anchored Model (3-4 hours)
**Problem**: `asset_configs.py` has hardcoded betas, but `btc_anchored_move.py` computes real-time betas from price action.

**Current**: SOL beta = 1.40 (static)
**Target**: SOL beta = computed from 20-bar rolling regression (dynamic 1.2-1.6 range)

**Fix**: 
1. Add `get_dynamic_beta(asset, timeframe)` method to `BtcAnchoredMoveModel`
2. Fall back to static beta if model has <20 observations
3. Use dynamic beta in `topn_allocator.py` beta normalization

**Files**: `merid/signals/btc_anchored_move.py`, `merid/trading/topn_allocator.py`

---

### Task 5: Enable Cross-Asset Hedging with Fallback (3 hours)
**Problem**: `HedgeConfig.cross_asset_enabled = False` — when BTC 15m has no liquidity, can't hedge SOL exposure.

**Current**: Only same-asset hedging
**Target**: SOL → BTC hedge when SOL 15m liquidity < threshold

**Fix**:
1. Add liquidity check to `CryptoHedgeEngine._compute_cell()`
2. If same-asset unavailable, use cross-asset with beta adjustment
3. Position sizing: SOL contracts × beta = BTC equivalent

**Files**: `merid/hedging/engine.py`, `merid/hedging/config.py`

---

### Task 6: Asset-Specific Edge Thresholds in Allocator (2 hours)
**Problem**: `topn_allocator.py` uses uniform `min_edge`, but audit specifies asset-specific thresholds (BTC 1.5%, SOL 2.0%, DOGE 2.5%).

**Current**: All assets need edge > 0.015 (1.5%)
**Target**: DOGE needs edge > 0.025 (2.5%) due to noise

**Fix**: 
1. Read `min_edge_threshold` from `AssetIndicatorConfig` 
2. Apply in `_filter_valid_candidates()`
3. Log edge threshold per asset for transparency

**Files**: `merid/trading/topn_allocator.py`, `merid/signals/asset_configs.py`

---

## 🟢 MEDIUM IMPACT (Complete After Critical)

### Task 7: FVG-Aware Hedge Timing (2-3 hours)
**Problem**: Hedge orders enter immediately on drawdown trigger, but FVG zones provide better entry timing.

**Current**: Hedge enters at market (next cycle)
**Target**: Hedge enters at FVG fill level (better price)

**Fix**:
1. Check `IndicatorSnapshot.fvg_zones` for hedge asset
2. If FVG present near current price, adjust hedge order price to FVG level
3. Track "hedge order parked at FVG" state

**Files**: `merid/trading/kalshi_continuous_trader.py` (hedge pass), `merid/signals/crypto_15m_indicators.py`

---

### Task 8: Market Regime Gate → State Machine Integration (2 hours)
**Problem**: Regime gate (flat/reduce/block) and state machine (A/B/C/D) operate independently.

**Current**: Regime BLOCK → No new entries, but state stays SCALP_ONLY
**Target**: Regime BLOCK + flat basket → Transition to SCALP_HEDGE or FLAT

**Fix**: Feed `RegimeDecision.action` into `TradingStateMachine.evaluate_transition()`

**Files**: `merid/market_regime/gate.py`, `merid/trading/kalshi_continuous_trader.py`

---

### Task 9: Hedge Order Lifecycle & Tracking (3-4 hours)
**Problem**: Hedge orders submitted but not tracked — no PnL attribution, no fill reconciliation.

**Current**: Submit hedge → Log success → No further tracking
**Target**: Full lifecycle like alpha orders (fills, PnL, metrics)

**Fix**:
1. Record hedge orders in `fills_ledger` with `source="HEDGE_ENGINE"`
2. Add hedge PnL separate from scalp PnL
3. Alert on hedge fill (different emoji 🛡️ vs 📈)

**Files**: `merid/event_venues/kalshi/fills_ledger.py`, `merid/alerts/trade_notifier.py`

---

### Task 10: State Machine Persistence (2 hours)
**Problem**: State resets to SCALP_ONLY on restart — dangerous if restart happens during 8% drawdown.

**Current**: `_state = TradingState.SCALP_ONLY` in `__init__`
**Target**: Restore previous state from disk (if <5 min old)

**Fix**:
1. Serialize state to `data/trading_state.json` on transition
2. Deserialize on startup (with staleness check)
3. Force FLAT if state file >5 min old (safety)

**Files**: `merid/trading/trading_state.py`

---

## Priority Matrix

| Task | Risk if Ignored | Implementation Effort | Total Priority |
|------|-----------------|----------------------|----------------|
| 1: Sentiment/Hedge Conflict | HIGH | Medium | **P0** |
| 2: KalshiRiskEngine Alignment | HIGH | Low | **P0** |
| 3: CycleDrawdown Alignment | HIGH | Low | **P0** |
| 4: Dynamic Beta | MEDIUM | High | **P1** |
| 5: Cross-Asset Hedge | MEDIUM | Medium | **P1** |
| 6: Asset-Specific Edge | MEDIUM | Low | **P1** |
| 7: FVG Hedge Timing | LOW | Medium | P2 |
| 8: Regime Gate Integration | LOW | Low | P2 |
| 9: Hedge Lifecycle | LOW | Medium | P2 |
| 10: State Persistence | LOW | Low | P3 |

---

## Recommended Sequence

**Week 1 (Days 1-3)**: Tasks 1-3 (Critical conflicts)
**Week 1 (Days 4-5)**: Tasks 4-6 (High impact features)
**Week 2**: Tasks 7-10 (Polish & hardening)

---

## Testing Checklist Per Task

- [ ] Unit tests for new logic
- [ ] Integration test with CT cycle
- [ ] Dry-run validation (paper trading)
- [ ] Logging verification (grep for new log lines)
- [ ] Backward compatibility check (disabled flag path)

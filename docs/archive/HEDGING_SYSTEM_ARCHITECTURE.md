# Hedging System Architecture

**Created:** 2026-07-07  
**Purpose:** Document the dual hedging system architecture in MERID for prediction markets and crypto trading

---

## Overview

MERID implements **two separate hedging systems** with distinct purposes:

1. **Offset Hedging** (Profile-level) - Hedging prediction market positions against spot/derivatives
2. **CryptoHedgeEngine** (Dedicated engine) - Rule-based hedging for crypto positions

These systems are **not interchangeable** and serve different use cases. Understanding the distinction is critical for proper system operation.

---

## System 1: Offset Hedging (Profile-Level)

### Purpose

Hedge prediction market positions (Kalshi binary options) against spot/derivatives markets to neutralize directional exposure.

### Configuration

**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
offset_hedging:
  enabled: false  # DISABLED for crypto
  hedge_ratio: 0.30  # 30% hedge ratio if enabled
```

### Why Disabled for Crypto

**Rationale:** "Binary hedging inefficient for crypto with public markets"

**Detailed Analysis:**
- Prediction markets (Kalshi) have binary outcomes (0 or 1 at settlement)
- Crypto spot/derivatives have continuous price movements
- Hedging binary options with continuous instruments creates:
  - Basis risk (price movements don't correlate 1:1)
  - Timing risk (15-minute expiry vs perpetual/long-term derivatives)
  - Liquidity risk (prediction markets may have lower liquidity)
  - Execution risk (slippage on both legs)

**Best Practice Alignment:**
- Web research confirms binary options hedging requires specialized strategies
- Standard futures/options hedging is more effective for continuous instruments
- For prediction markets, direct position management (TP/SL, trailing stops) is more efficient

### Integration Points

**Profile Adapter:** `merid/risk/profiles/crypto_15m_profile.py`
- Loads `offset_hedging_enabled` from YAML
- Maps to internal `Crypto15mProfile` dataclass

**Risk Envelope:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- Does not directly use offset hedging
- Enforces window-based risk limits independently

**Unified Sizing:** `merid/prediction/unified_sizing.py`
- Does not incorporate hedge ratios into position sizing
- Sizing based solely on risk percentages from profile

### Current Status

- **Enabled:** ❌ Disabled in profile
- **Active:** ❌ No active offset hedging for crypto 15m
- **Recommendation:** Keep disabled for crypto prediction markets

---

## System 2: CryptoHedgeEngine (Dedicated Engine)

### Purpose

Deterministic rule-based hedging for crypto positions across assets and timeframes. Produces hedge orders to neutralize directional exposure per (asset, timeframe) cell.

### Configuration

**File:** `config/kalshi_crypto_hedging.yaml`

```yaml
hedging:
  enabled: true  # Engine is enabled
  use_cross_asset_hedging: false  # Same-asset only
  max_drawdown_pct: 40.0

  # Asset-specific bankroll slices
  asset_slices:
    BTC:
      slice_pct_of_bankroll: 0.20
      per_trade_risk_pct_of_slice: 1.0
      max_drawdown_pct_of_slice: 3.0
    # ... ETH, SOL, XRP, DOGE similar

  # Timeframe-specific hedge rules
  timeframes:
    15m:
      max_net_exposure_pct_of_slice: 10.0
      target_hedge_ratio: 0.5
      prefer_same_timeframe: true
      allow_adjacent_horizons: []

  # Cross-asset hedging (disabled)
  cross_asset:
    enabled: false
    max_pair_correlation: 0.85
    max_cross_hedge_pct_of_base: 0.20
    pairs: []

  # Take profit configuration
  take_profit:
    enabled: true
    BTC:
      tp_1: 2.0
      tp_2: 4.0
      stop_loss: 1.5
    # ... other assets

  # Auto-exit configuration
  auto_exit:
    enabled: true
    close_hedge_when_alpha_closed: true
    max_hedge_hold_minutes: 120
    reduce_on_exposure_flip: true
```

### Implementation

**File:** `merid/hedging/engine.py`

**Key Classes:**
- `CryptoHedgeEngine` - Main hedging engine
- `HedgeOrder` - Single hedge order recommendation
- `HedgeResult` - Output of hedge computation pass

**Key Features:**
- **Deterministic:** Same inputs → same outputs (idempotent)
- **Thread-safe:** All state in arguments, not on instance
- **Strategy group isolation:** Uses `HEDGE_STRATEGY_GROUP = "hedge"` to avoid lease collisions with alpha agents
- **Dedicated tags:** Hedge orders tagged with `HEDGE_` prefix for dedup

### Integration Points

**Config Loader:** `merid/hedging/config.py`
- `load_hedge_config()` - Loads from YAML
- `get_hedge_config()` - Thread-safe singleton accessor
- Returns `HedgeConfig(enabled=False)` on error (fail-safe)

**API Endpoints:** `web/api/prediction.py`
- `POST /api/v1/prediction/hedge/enable` - Enable engine
- `POST /api/v1/prediction/hedge/disable` - Disable engine
- `POST /api/v1/prediction/hedge/propose` - Propose hedge position
- `GET /api/v1/prediction/hedge/positions` - Get active positions
- `POST /api/v1/prediction/hedge/positions/{id}/activate` - Activate position
- `POST /api/v1/prediction/hedge/positions/{id}/close` - Close position

**Startup Integration:** `web/main_15m_lean.py`
- Auto-exit loop started if `hedge_config.enabled` and `hedge_config.auto_exit.enabled`
- Manages hedge position TP/SL exits independently

### Current Status

- **Enabled:** ✅ Engine enabled in config
- **Active:** ✅ Auto-exit loop running for hedge positions
- **Manual Control:** ❌ Hedge proposal/activation requires manual API calls
- **Auto-Integration:** ❌ Not automatically integrated into continuous trader cycle

---

## Comparison: Offset Hedging vs CryptoHedgeEngine

| Aspect | Offset Hedging | CryptoHedgeEngine |
|--------|----------------|-------------------|
| **Purpose** | Hedge prediction market positions | Hedge crypto positions across timeframes |
| **Config File** | `kalshi_crypto_15m_v2.yaml` | `kalshi_crypto_hedging.yaml` |
| **Current Status** | Disabled | Enabled (manual) |
| **Integration** | Profile-level flag | Dedicated engine with API |
| **Asset Scope** | Prediction markets only | Crypto assets (BTC, ETH, SOL, XRP, DOGE) |
| **Timeframe Scope** | 15m only | Multi-timeframe (15m, 1h, daily, etc.) |
| **Hedge Instruments** | Spot/derivatives (offset) | Prediction markets (same-asset) |
| **Risk Guard Interaction** | None (disabled) | Respects window limits |
| **Auto-Execution** | N/A (disabled) | Manual API calls only |

---

## When to Use Each System

### Use Offset Hedging (When Re-Enabled)

**Appropriate for:**
- Traditional prediction markets (non-crypto)
- Markets with high correlation to liquid derivatives
- Long-duration events (hours/days) where basis risk is manageable
- Situations where directional exposure must be neutralized

**Not appropriate for:**
- Crypto prediction markets (current implementation)
- Short-duration events (15m) with high volatility
- Markets with low liquidity or high slippage

### Use CryptoHedgeEngine

**Appropriate for:**
- Multi-timeframe crypto position management
- Reducing directional exposure across timeframes
- Systematic hedging strategies
- Automated hedge position management (TP/SL, auto-exit)

**Not appropriate for:**
- Hedging prediction market positions against spot (use offset hedging)
- Manual one-off hedges (use direct order placement)
- Situations requiring custom hedge logic outside engine rules

---

## Risk Guard Interaction

### Window-Based Risk Limits

Both systems respect the window-based hard stops:

- **3% per agent per 15-minute window**
- **5% total venue per 15-minute window**

**Offset Hedging:**
- Disabled, so no interaction with risk guards
- If re-enabled, hedge orders would need to pass order gate checks

**CryptoHedgeEngine:**
- Hedge orders use dedicated strategy group (`"hedge"`)
- Dedicated strategy group avoids lease collisions with alpha agents
- Hedge orders still subject to window limits via order gate

### Order Gate Checks

**File:** `merid/event_venues/kalshi/order_gate.py`

All orders (including hedge orders) pass through:
1. Idempotency check (duplicate prevention)
2. Fill awareness check (already satisfied)
3. Window limit check (3% per agent, 5% total)
4. Price guard check (deep OTM rejection)
5. Price repeat check (prevent same-price execution)

**Hedge Order Special Handling:**
- `client_tag` prefixed with `HEDGE_` for dedup
- `agent_id = "hedge_engine"`
- `strategy_group = "hedge"` (isolated from alpha)

---

## Future Considerations

### CryptoHedgeEngine Auto-Integration

**Question:** Should CryptoHedgeEngine be automatically integrated into the 15m trading cycle?

**Pros:**
- Automatic hedging reduces manual intervention
- Faster response to exposure changes
- Systematic risk management

**Cons:**
- Adds complexity to trading cycle
- May conflict with existing risk management (trailing stops, ratchet)
- Requires careful testing to avoid over-hedging

**Recommendation:** Assess based on:
- Current hedging needs (is manual sufficient?)
- Backtesting results of auto-hedging vs manual
- Operational complexity vs benefit

### Hedge Config Consolidation

**Question:** Should hedge configs be consolidated into single source of truth?

**Current State:**
- Profile YAML: `offset_hedging` flag
- Hedge config YAML: Full CryptoHedgeEngine configuration

**Consolidation Options:**
1. **Merge into profile YAML** - Single source of truth, but profile becomes large
2. **Keep separate** - Clear separation of concerns, but two config files to manage
3. **Hybrid** - Profile flags, engine config separate (current state)

**Recommendation:** Keep separate for now. The systems serve different purposes and separation aids clarity.

---

## Audit Checklist

When auditing the hedging system, verify:

- [ ] **Offset Hedging Status**
  - [ ] Profile YAML has `offset_hedging.enabled: false` for crypto
  - [ ] Profile adapter correctly maps `offset_hedging_enabled`
  - [ ] No code path attempts offset hedging for crypto 15m

- [ ] **CryptoHedgeEngine Status**
  - [ ] Hedge config YAML exists and is valid
  - [ ] Engine enabled/disabled matches operational intent
  - [ ] Auto-exit loop started if configured
  - [ ] Hedge orders use dedicated strategy group

- [ ] **Risk Guard Compliance**
  - [ ] No hedging logic bypasses window limits
  - [ ] Hedge orders pass order gate checks
  - [ ] Hedge orders do not collide with alpha agent leases
  - [ ] Hedge exposure tracked in window accounting

- [ ] **Documentation**
  - [ ] This architecture document is up-to-date
  - [ ] Offset hedging disable decision is documented
  - [ ] CryptoHedgeEngine integration points are clear
  - [ ] Risk guard interaction is documented

---

## References

**Related Documentation:**
- `docs/MOMENTUM_HEDGE_CONFLICT_REPORT.md` - CryptoHedgeEngine integration analysis
- `docs/15M_ARCHITECTURE_SWEEP_REMEDIATION_PLAN.md` - Risk guard audit checklist
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile configuration
- `config/kalshi_crypto_hedging.yaml` - Hedge engine configuration

**Key Files:**
- `merid/hedging/engine.py` - CryptoHedgeEngine implementation
- `merid/hedging/config.py` - Hedge config loader
- `merid/risk/profiles/crypto_15m_profile.py` - Profile adapter
- `merid/event_venues/kalshi/order_gate.py` - Order gate with risk checks
- `web/api/prediction.py` - Hedge API endpoints

**Web Research:**
- Openware: "Hedging and Risk Management in Crypto Trading"
- Academic: "Efficient Hedging Using a Dynamic Portfolio of Binary Options"

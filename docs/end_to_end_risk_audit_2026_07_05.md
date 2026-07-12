# MERID 15M Kalshi Crypto Trading System - End-to-End Risk Audit
**Date:** 2026-07-05  
**Profile:** kalshi_crypto_15m_v2  
**Assets:** BTC, ETH, SOL, XRP, DOGE  
**Trading Directions:** Buy YES, Sell YES, Buy NO, Sell NO

---

## Executive Summary

This document provides a comprehensive end-to-end audit of the MERID 15-minute Kalshi crypto trading system, covering all risk and execution guards across the upstream configuration, midstream risk envelope, downstream sizing, agent grid signal generation, and execution layers.

**Key Findings:**
- All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are consistently configured across all layers
- Risk limits are aligned: 3% per asset, 5% per 15m window, 15% total venue cap
- Signal mode: momentum_fvg (based on 2026 Turbine research - momentum was the only profitable family)
- Multiple scaling mechanisms are DISABLED to prevent interference with hard risk limits
- Position management features enabled: trailing stops, ratchet profit floor, staged time exits
- Correlation tracking and portfolio heat monitoring enabled for 2026 research-based risk management

---

## 1. UPSTREAM LAYER: Configuration

### 1.1 Profile YAML: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Profile Version:** 2.3.0  
**Operation Mode:** prod (conservative 5% daily loss limit)  
**Dry Run:** false (live trading enabled)

#### 1.1.1 Global Capital and Cycle Risk

| Parameter | Value | Description |
|-----------|-------|-------------|
| `capital_usd` | 0 | Derive from live Kalshi bankroll API |
| `min_notional_usd` | 0.50 | Minimum notional per trade (uniform for all account sizes) |
| `min_contracts` | 1 | Minimum 1 contract per trade (Kalshi venue invariant) |
| `max_cycle_risk_pct` | 0.05 (5%) | Maximum risk per cycle (aligned with 5% per 15m window) |
| `max_total_risk_pct` | 0.15 (15%) | Total risk cap (production safety) |
| `max_cycle_risk_usd` | 7.00 | Hardcoded cap to allow 10 contracts at max entry price ($0.70) |

#### 1.1.2 Venue-Level Caps (Kalshi)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `venue.max_total_notional_pct` | 0.15 (15%) | Total venue cap (sum of 3% per asset × 5 assets) |
| `venue.max_category_notional_pct` | 0.15 (15%) | Crypto category cap (matches total) |
| `venue.max_single_order_pct` | 0.10 (10%) | Maximum single order as % of bankroll |
| `venue.bankroll_cap_pct` | 0.10 (10%) | Bankroll cap percentage for order sizing |

#### 1.1.3 Per-Asset Caps (BTC/ETH/SOL/XRP/DOGE)

**All assets use 3% of capital for maximum notional exposure:**

| Asset | max_notional_pct | max_contracts | min_edge_early | min_edge_mid | min_edge_late | min_edge_terminal | Asset Tier |
|-------|-----------------|--------------|---------------|--------------|--------------|------------------|------------|
| BTC | 3% | 3 | 3% | 3% | 3% | 4% | Tier 1 |
| ETH | 3% | 3 | 3% | 3% | 3% | 4% | Tier 1 |
| SOL | 3% | 3 | 4% | 4% | 4% | 5% | Tier 2 |
| XRP | 3% | 3 | 4% | 4% | 4% | 5% | Tier 2 |
| DOGE | 3% | 2 | 5% | 5% | 5% | 6% | Tier 2 |

**Depth Thresholds (single source of truth for 15m stack):**
- All assets: `min_depth_yes: 1`, `min_depth_no: 1`
- Rationale: Only trade 1 contract per 15m window per asset
- Gating condition: "Can I fill 1 contract within slippage budget?"

**Minimum Decision Minute (skip noisy early signals):**
| Asset | min_decision_minute |
|-------|---------------------|
| BTC | 2 |
| ETH | 2 |
| SOL | 3 |
| XRP | 3 |
| DOGE | 5 |

#### 1.1.4 Agent Defaults

| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_notional_pct` | 0.05 (5%) | Per agent (per 15m window limit) |
| `max_orders_per_window` | 20 | Max orders per trading window |
| `max_yes_position` | 5 | Max YES contracts per side |
| `max_no_position` | 5 | Max NO contracts per side |
| `max_concurrent_trades` | 8 | Max concurrent trades |
| `minutes_before_expiry` | 12 | Entry window start |
| `cutoff_minutes_before_expiry` | 2 | Stop trading 2 minutes before expiry |

#### 1.1.5 Throttling (Order Rate Limits)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `global_orders_window_sec` | 60 | Rolling window for global order limit |
| `global_orders_limit` | 30 | Max 30 orders per minute globally |
| `per_asset_cooldown_sec` | 8 | 8s cooldown per asset |
| `max_orders_per_15m_window` | 12 | Max 12 orders per 15m window |
| `cooldown_after_loss_cycles` | 2 | No new entry for 2 cycles after loss |
| `consecutive_loss_pause` | 3 | Pause after 3 consecutive losses |
| `max_session_risk_pct` | 0.10 (10%) | Max session risk as % of capital |

#### 1.1.6 Guardrails

| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_spread_cents` | 75 | Maximum spread in cents (unified single source of truth) |
| `max_slippage_cents` | 5 | Max 5 cents worse than best |
| `min_post_fee_edge` | 0.015 (1.5%) | Minimum post-fee edge |
| `min_time_to_expiry_min` | 2.0 | Minimum 2 minutes to expiry |
| `max_dist_pct_trade` | 2.5% | Maximum spot-strike distance percentage |
| `min_contract_price_cents` | 10 | Minimum contract price floor |
| `max_contract_price_cents` | 75 | Maximum contract price ceiling (sweet-spot band) |
| `max_same_side_per_strip` | 5 | Maximum same-direction positions per strip |
| `max_entry_mins` | 15.0 | Maximum time to expiry for entry |
| `min_entry_mins` | 2.0 | Minimum time to expiry for entry |

**Drawdown Limits:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `drawdown_halt_pct` | 0.20 (20%) | Halt at 20% drawdown |
| `drawdown_unwind_pct` | 0.25 (25%) | Unwind at 25% drawdown |

**Per-Trade Risk (bankroll-tiered):**
| Bankroll Range | Per-Trade Risk |
|---------------|----------------|
| < $100 | 2.75% |
| $100 - $1,000 | 2.0% |
| > $1,000 | 2.0% |

**Daily Loss Cap:**
| Operation Mode | Daily Loss Limit |
|----------------|-----------------|
| test | 20% |
| prod | 20% |

**Adaptive Risk Bands (drawdown-based scaling):**
| Drawdown Range | Multiplier | Risk Band |
|----------------|------------|-----------|
| 0-8% | 1.0 (100%) | NORMAL |
| 8-10% | 0.8 (80%) | WARNING |
| 10-12% | 0.5 (50%) | DOWNSIZE |
| 12-15% | 0.25 (25%) | CRITICAL |
| 15%+ | 0.0 (0%) | HALT |

#### 1.1.7 Kelly Sizing

| Parameter | Value | Description |
|-----------|-------|-------------|
| `kelly_fraction` | 0.02 (2%) | Kelly hard cap (aligned with unified risk limit) |
| `kelly_hard_cap` | 0.02 (2%) | Legacy field, kept in sync |
| `kelly_min_edge_pct` | 0.015 (1.5%) | Minimum edge for Kelly sizing |
| `kelly_max_edge_pct` | 0.25 (25%) | Maximum edge for Kelly sizing |
| `kelly_global_notional_cap_pct` | 0.02 (2%) | Global notional cap |

**Tiered Kelly by Asset:**
| Tier | Assets | Kelly Fraction |
|------|--------|---------------|
| Tier 1 | BTC, ETH | 2% |
| Tier 2 | SOL, XRP, DOGE | 1.5% |

#### 1.1.8 Contract Caps

| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_contracts_total` | 5000 | Max total contracts across all assets |
| `max_contracts_per_asset` | 1750 | Max contracts per asset |
| `max_contracts_per_cluster` | 750 | Max contracts per asset/timeframe/overlap-window |
| `max_single_order_contracts` | 2 | Aligned with per-asset max_contracts |

#### 1.1.9 Signal Mode Configuration

**Current Signal Mode:** `momentum_fvg` (2026-07-05: Changed from trend to momentum_fvg based on Turbine research)

**Momentum/FVG Parameters:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `momentum_rsi_long_min` | 55 | Bullish momentum: RSI > 55 |
| `momentum_rsi_short_max` | 45 | Bearish momentum: RSI < 45 |
| `momentum_min_macd_hist_long` | 0 | For longs: MACD histogram >= 0 |
| `momentum_min_macd_hist_short` | 0 | For shorts: MACD histogram <= 0 |
| `obi_min` | 0.25 | Minimum absolute OBI to qualify as directional |
| `obi_persistence_min` | 0.60 | Minimum fraction of snapshots with consistent OBI sign |
| `obi_persistence_window_sec` | 10 | Time window for persistence check (10 seconds) |
| `obi_ewma_alpha` | 0.15 | EWMA smoothing factor |

**Per-Asset OBI Strong Thresholds:**
| Asset | Strong Threshold | EWMA Alpha |
|-------|------------------|------------|
| BTC | 0.55 | 0.15 |
| ETH | 0.55 | 0.15 |
| SOL | 0.45 | 0.20 |
| XRP | 0.45 | 0.20 |
| DOGE | 0.45 | 0.20 |

**Fair Value Gap (FVG) Parameters:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `fvg_max_age_bars` | 4 | Maximum age of FVG in bars (60min) |
| `fvg_min_size_ticks` | 3 | Minimum FVG size in ticks |
| `fvg_min_time_to_expiry_min` | 30 | Minimum time to expiry for FVG entries |

**Trend Confirmation:**
| Parameter | Value |
|-----------|-------|
| `require_ema_stack` | true |
| `require_price_vs_ema50` | true |

**Liquidity-Aware Size Scaling:**
| Tier | Threshold | Size Factor |
|------|-----------|-------------|
| High | >=200 contracts | 1.0 (full profile risk) |
| Medium | 80-200 contracts | 0.75 (75% of profile risk) |
| Low | 40-80 contracts | 0.5 (50% of profile risk) |
| Ultra-Low | 25-40 contracts | 0.25 (25% of profile risk) |
| Below Min | <25 contracts | 0.0 (no new entries) |

**Spread Gate Interaction:**
| Parameter | Value |
|-----------|-------|
| `spread_gate_cents` | 75 |
| `spread_gate_obi_persistence_boost` | 0.75 |

#### 1.1.10 Price Range Configuration

**Entry Band (momentum-based trading):**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `min_price_cents` | 10 | Allows NO-side entries in high-probability markets |
| `max_price_cents` | 70 | Avoids risky high-end markets with poor scaling |

**Hybrid Mode Price Caps:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_entry_price_yes` | 0.70 | Avoids highest fee zone (fees peak at 50¢, lower at 70¢) |
| `min_entry_price_no` | 0.30 | Symmetry with 70¢ YES cap |

#### 1.1.11 Edge Band Configuration (Tiered Structure)

**2026-07-05 FIX:** Reverted thresholds - previous increase to 4-7% blocked ALL trades

| Band | Min Edge | Max Edge | Action | Kelly Multiplier |
|------|---------|----------|--------|------------------|
| Watch | 0.8% | 1.5% | log_only | 0.0 |
| Small | 1.5% | 3% | trade_small | 0.25 |
| Standard | 3% | No limit | trade_standard | 0.50 |

**Kelly Multiplier Overrides:**
| Parameter | Value |
|-----------|-------|
| `kelly_multiplier_no_trade` | 0.0 |
| `kelly_multiplier_cautious` | 0.5 |
| `kelly_multiplier_quick_win` | 0.6 |
| `kelly_multiplier_confident` | 1.0 |

#### 1.1.12 Position Management Features

**Trailing Stop:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | Enable trailing stop |
| `trailing_distance_cents` | 5 | 5 cents trailing distance |
| `min_profit_cents` | 12 | Only activate after 12c profit (2026 research: 10-15¢ threshold) |
| `activation_delay_sec` | 30 | Wait 30s before activating |

**Ratchet Profit Floor:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | Enable ratchet profit floor mechanism |
| `activation_threshold_cents` | 85 | Activate ratchet when price hits this threshold |
| `floor_offset_cents` | 5 | Set floor X cents below activation (85¢ → 80¢ floor) |
| `force_exit_on_floor_breach` | true | Mandatory exit if price drops to floor |
| `min_hold_after_activation_sec` | 30 | Prevent immediate exit on noise |
| `mandatory_exit_at_99c` | true | Mandatory exit when price reaches 99c |
| `trim_position_enabled` | true | Trim position when >1 contract and price >80c |
| `trim_threshold_cents` | 80 | Trim when price crosses this threshold |
| `trim_to_contracts` | 1 | Trim to 1 contract to lock in profits |

**Staged Time-Based Exit:**
| Stage | Minutes | Percent to Close |
|-------|---------|------------------|
| 1 | 5 | 40% |
| 2 | 10 | 30% |
| 3 | 13 | 30% |

**Dynamic Position Sizing:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | Enable dynamic sizing |
| `base_contracts` | 1 | Base size |
| `edge_multiplier` | 2.0 | 2026-07-05: Increased from 0.5 to 2.0 (4x) based on Turbine research |
| `confidence_multiplier` | 1.0 | 2026-07-05: Increased from 0.3 to 1.0 (3.3x) based on Turbine research |
| `max_contracts` | 3 | Max contracts per trade |
| `min_contracts` | 1 | Min contracts per trade |

**Order Scaling:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | ENABLED for production with scaling strategies |
| `strategy` | adaptive | Strategy: twap, iceberg, adaptive |
| `min_child_orders` | 2 | Minimum number of child orders |
| `max_child_orders` | 5 | Maximum number of child orders |
| `time_window_seconds` | 300.0 | Time window for execution (5 minutes) |
| `participation_rate` | 0.10 | Max 10% of market volume |
| `visible_pct` | 0.10 | Iceberg: 10% visible |
| `edge_threshold` | 0.02 | 2% edge minimum for scaling |
| `size_threshold_contracts` | 3 | Scale only if size >= 3 contracts |

#### 1.1.13 2026 Research-Based Risk Management

**Correlation Tracking:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | Enable correlation tracking |
| `real_time_monitoring` | true | Real-time correlation monitoring |
| `threshold_high` | 0.80 | Treat as ONE position when >0.80 correlation |
| `threshold_moderate` | 0.50 | Reduce size by correlation % when 0.50-0.80 |
| `threshold_alert` | 0.85 | Alert + 50% size reduction at 0.85 |
| `max_correlated_assets` | 3 | Never exceed 3 assets with >0.80 correlation |

**Position Sizing Rules:**
| Correlation Level | Rule |
|------------------|------|
| Highly Correlated (>0.80) | treat_as_one_position |
| Moderate Correlated (0.50-0.80) | reduce_by_correlation_pct |
| Low Correlated (<0.50) | full_size_allowed |

**Volatility-Regime Edge Adjustment:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | ENABLED: 2026-07-04 - Fixed adjustment logic |
| `lookback_days` | 30 | 30-day rolling window for volatility calculation |
| `low_volatility_threshold` | 0.30 | Below 30-day avg = low volatility |
| `high_volatility_threshold` | 0.70 | Above 30-day avg = high volatility |
| `low_volatility_adjustment` | -0.0025 | Reduce min edge by 0.25% in low vol |
| `high_volatility_adjustment` | +0.005 | Increase min edge by 0.5% in high vol |

**Portfolio Heat Tracking:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | true | Enable portfolio heat tracking |
| `calculation_method` | correlation_adjusted_exposure | Account for correlation in exposure |
| `heat_threshold_warning` | 0.70 | 70% of max adjusted exposure = warning |
| `heat_threshold_critical` | 0.85 | 85% of max adjusted exposure = critical |
| `warning_response` | reduce_new_positions_by_25pct | Reduce new positions by 25% |
| `critical_response` | reduce_new_positions_by_50pct | Reduce new positions by 50% |

**Time-of-Day Risk Scaling:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | false | DISABLED: interferes with 3% per asset limits |
| `us_market_hours` | 09:30-16:00 ET | US market hours |
| `asian_session` | 20:00-02:00 ET | Asian session |
| `european_session` | 02:00-09:30 ET | European session |
| `us_market_multiplier` | 1.0 | 100% risk during US hours |
| `asian_multiplier` | 0.8 | 80% risk during Asian session |
| `european_multiplier` | 0.9 | 90% risk during European session |
| `weekend_multiplier` | 0.8 | 80% risk during weekend |

**Asset-Specific Rolling PnL Limits:**
| Asset | Rolling 1h Halt | Rolling 4h Halt |
|-------|----------------|----------------|
| BTC | 4% | 7% |
| ETH | 4% | 7% |
| SOL | 6% | 9% |
| XRP | 6% | 9% |
| DOGE | 8% | 12% |

#### 1.1.14 Disabled Features

**Offset Hedging:**
- `enabled: false` - DISABLED based on research
- Rationale: Binary contracts are inefficient for hedging crypto with public markets
- For assets with public markets (BTC/ETH/SOL/XRP/DOGE), options are more efficient

**Fallback Pricing:**
- `allow_fallback_trades: false` - DISABLED
- `max_fallback_notional_usd: 0.35` - Unused when disabled
- `max_fallback_cycles: 0` - No fallback cycles allowed
- Rationale: Live market data is required for all trading decisions

**Sentiment Isolation:**
- `enable_sentiment_execution: false` - Sentiment-based trading disabled for 15m crypto
- `sentiment_mode: disabled` - Explicitly set to disabled

---

## 2. MIDSTREAM LAYER: Risk Envelope

### 2.1 Risk Envelope: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Version:** v20260529a-cache-fix  
**Function:** `compute_kalshi_crypto_15m_risk_envelope()`

#### 2.1.1 Computed Venue-Level Caps

| Parameter | Computed From | Description |
|-----------|--------------|-------------|
| `max_single_order_notional_usd` | `venue.max_single_order_pct × effective_capital` | Per-trade cap (derived from profile percentage × capital) |
| `max_total_notional_usd` | `venue.max_total_notional_pct × effective_capital` | Max total notional (sum of all positions) |
| `max_concurrent_trades` | `agent_defaults.max_concurrent_trades` | Max concurrent trades (from profile agent_defaults) |

#### 2.1.2 Per-Asset Caps (BTC/ETH/SOL/XRP/DOGE)

**Computation Formula:**
```
asset_max_notional_usd[asset] = effective_capital × max_notional_pct
asset_max_notional_usd[asset] = max(asset_max_notional_usd[asset], min_max_notional_usd)
```

**Minimum Floor:**
- `min_max_notional_usd: 0.10` - Minimum floor for per-asset max_notional
- Rationale: Ensure trades are possible even with small bankrolls (e.g., $31.36)

**Asset Cap Rescaling:**
- If sum of asset caps exceeds venue cap, all caps are scaled down proportionally
- Ensures hard invariant: total asset cap ≤ venue cap

#### 2.1.3 Per-Agent Defaults

| Parameter | Computed From | Description |
|-----------|--------------|-------------|
| `agent_max_notional_usd` | `agent_defaults.max_notional_pct × effective_capital` | From profile agent_defaults |
| `agent_max_orders_per_window` | `agent_defaults.max_orders_per_window` | From profile agent_defaults |
| `agent_max_yes_position` | `agent_defaults.max_yes_position` | From profile agent_defaults |
| `agent_max_no_position` | `agent_defaults.max_no_position` | From profile agent_defaults |

#### 2.1.4 Guardrails

| Parameter | Computed From | Description |
|-----------|--------------|-------------|
| `per_trade_risk_pct` | `guardrails.per_trade_risk_pct` | 2% (aligned with profile) |
| `drawdown_halt_pct` | `guardrails.drawdown_halt_pct` | 20% (aligned with profile) |
| `drawdown_unwind_pct` | `guardrails.drawdown_unwind_pct` | 25% (aligned with profile) |
| `kelly_fraction` | `kelly.kelly_fraction` | 2% (aligned with profile) |
| `daily_loss_enabled` | `guardrails.daily_loss_enabled` | true (aligned with profile) |
| `max_daily_loss_usd` | `effective_capital × max_daily_loss_pct` | 20% of capital (aligned with profile) |

#### 2.1.5 Drawdown Tracking

**Semantics:**
- Time horizon: "since process start" (not rolling window)
- PnL basis: "equity including open positions" (realized + unrealized)
- Deposits/Withdrawals: treated as PnL

**Fresh Start Behavior:**
- When `MERID_FRESH_START=1`, peak_equity resets to current_equity
- Prevents old drawdown state from persisting across sessions

#### 2.1.6 Adaptive Risk Scaling

**Risk Bands:**
| Drawdown Range | Multiplier | Risk Band |
|----------------|------------|-----------|
| 0-8% | 1.0 (100%) | NORMAL |
| 8-10% | 0.8 (80%) | WARNING |
| 10-12% | 0.5 (50%) | DOWNSIZE |
| 12-15% | 0.25 (25%) | CRITICAL |
| 15%+ | 0.0 (0%) | HALT |

**Auto-Resume:**
- `resume_if_drawdown_improves: false` - Default: manual operator intervention required
- Can be enabled to auto-resume when drawdown improves to lower band

#### 2.1.7 Correlation Tracking (Phase 1 Profitability Enhancement)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `correlation_tracking_enabled` | from profile | Enable/disable correlation tracking |
| `correlation_threshold` | from profile | Threshold for exposure reduction |
| `correlation_multiplier` | 1.0 (default) | Current correlation-based size multiplier |

#### 2.1.8 Per-Trade Risk (Bankroll-Tiered)

**Bankroll-Tiered Logic:**
| Bankroll Range | Per-Trade Risk |
|---------------|----------------|
| < $100 | 2% |
| $100 - $1,000 | 1.5% |
| > $1,000 | 0.8% |

**Rationale:** Higher risk for small bankrolls to ensure tradable sizes (fractional Kelly for micro-accounts)

### 2.2 Profile Adapter: `merid/risk/profiles/crypto_15m_profile.py`

**Class:** `Crypto15mProfileAdapter`  
**Function:** `_load_profile()`

#### 2.2.1 Profile Schema Validation

**Required Sections:**
- profile_name
- profile_version
- description
- capital_usd
- min_notional_usd
- min_contracts
- max_cycle_risk_pct
- venue
- assets
- agent_defaults
- kelly
- guardrails
- contract_caps
- risk_policy
- strategy_policy
- velocity_model (Phase 1: Required for logistic mapping)

**Validation:** Fail-fast on missing required fields to prevent silent fallback to default values

#### 2.2.2 Asset Configuration Parsing

**Per-Asset Config:**
- `max_notional_pct` - Percentage of capital (with nested dict normalization)
- `max_contracts` - Maximum contracts (with nested dict normalization)
- `min_edge_early/mid/late/terminal` - Not used (edge_bands section instead)

**Edge Bands:**
- Per-asset min_edge fields are ignored
- Edge thresholds come from `kalshi_crypto_15m_v2.yaml` edge_bands section:
  - watch_band: 0.8-1.5% (log only)
  - small_band: 1.5-3% (trade small)
  - standard_band: ≥3% (trade standard)
  - kelly_min_edge_pct: 2% (hard floor)

#### 2.2.3 Computed USD Values

**Venue Caps:**
- `venue_max_single_order_usd = capital_usd × venue_max_single_order_pct`
- `venue_max_total_notional_usd = capital_usd × venue_max_total_notional_pct`
- `venue_max_category_notional_usd = capital_usd × venue_max_category_notional_pct`
- `agent_max_notional_usd = capital_usd × agent_max_notional_pct`

**Capital Derivation:**
- If `capital_usd = 0`, derive from BankrollServiceV2 (single source of truth)
- Profile capital is only for validation/calibration mode

#### 2.2.4 Velocity Model Coefficients (Phase 1)

**2026-07-04 FIX:** Increased alpha_1 to make velocity-to-probability mapping responsive

| Asset | alpha_0 | alpha_1 |
|-------|--------|--------|
| BTC | 0.0 | 200.0 (increased from 2.0) |
| ETH | 0.0 | 200.0 (increased from 2.0) |
| SOL | 0.0 | 300.0 (increased from 3.0) |
| XRP | 0.0 | 300.0 (increased from 3.0) |
| DOGE | 0.0 | 500.0 (increased from 5.0) |

**Velocity Thresholds (2026-07-05 FIX):**
| Asset | Threshold |
|-------|-----------|
| BTC | 0.00001 (0.001%) |
| ETH | 0.00001 (0.001%) |
| SOL | 0.00001 (0.001%) |
| XRP | 0.00001 (0.001%) |
| DOGE | 0.00001 (0.001%) |

**Rationale:** Reduced to effectively zero to enable any trading (actual market velocities: 0.000%-0.04%)

#### 2.2.5 Multi-Window Velocity Weights (Phase 4.1)

| Parameter | Value |
|-----------|-------|
| `momentum_weights_windows` | [10, 30, 60] (seconds) |
| `momentum_weights_values` | [0.2, 0.3, 0.5] (weights) |

#### 2.2.6 Logit Fusion Weights (Phase 4.4)

| Parameter | Value |
|-----------|-------|
| `logit_fusion_velocity_weight` | 0.7 |
| `logit_fusion_mean_reversion_weight` | 0.3 |

#### 2.2.7 Near Expiry Guard (Phase 4.5)

| Parameter | Value |
|-----------|-------|
| `near_expiry_guard_sec` | 300 (5 minutes) |

#### 2.2.8 Calibration Configuration (Phase 5.2)

| Parameter | Value |
|-----------|-------|
| `calibration_enabled` | true (ENABLED for dynamic adjustment) |
| `calibration_auto_fit` | true |
| `calibration_min_samples` | 50 (reduced from 100 for faster startup) |
| `calibration_max_samples` | 500 (reduced from 1000 for more recent data) |
| `calibration_regularization` | 0.0001 |
| `calibration_fit_interval_hours` | 1 (reduced from 24 for more frequent updates) |

#### 2.2.9 Fee-Aware Edge Gate (Phase 1)

| Parameter | Value |
|-----------|-------|
| `fee_aware_edge_enabled` | true |
| `fee_aware_edge_min_edge_cents` | 2.0 |
| `fee_aware_edge_fee_per_contract` | 0.07 (Kalshi taker fee) |

#### 2.2.10 Market Microstructure Filters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `market_microstructure_enabled` | true | Enable market microstructure filters |
| `market_microstructure_max_spread_cents` | 75.0 | UNIFIED: 75c aligned with guardrails |
| `market_microstructure_min_depth_usd` | 0.0 | DISABLED: System uses limit orders |
| `market_microstructure_min_yes_depth` | 1 | Minimum YES depth threshold |
| `market_microstructure_min_no_depth` | 1 | Minimum NO depth threshold |

#### 2.2.11 2026 Research-Based Risk Management

**Correlation Tracking:**
| Parameter | Value |
|-----------|-------|
| `correlation_tracking_enabled` | false (from profile) |
| `correlation_tracking_real_time_monitoring` | false |
| `correlation_tracking_threshold_high` | 0.80 |
| `correlation_tracking_threshold_moderate` | 0.50 |
| `correlation_tracking_threshold_alert` | 0.85 |
| `correlation_tracking_max_correlated_assets` | 3 |

**Volatility-Regime Edge Adjustment:**
| Parameter | Value |
|-----------|-------|
| `volatility_regime_edge_adjustment_enabled` | false (from profile) |
| `volatility_regime_edge_adjustment_lookback_days` | 30 |
| `volatility_regime_edge_adjustment_low_volatility_threshold` | 0.30 |
| `volatility_regime_edge_adjustment_high_volatility_threshold` | 0.70 |
| `volatility_regime_edge_adjustment_low_volatility_adjustment` | -0.005 |
| `volatility_regime_edge_adjustment_high_volatility_adjustment` | 0.010 |

**Portfolio Heat Tracking:**
| Parameter | Value |
|-----------|-------|
| `portfolio_heat_enabled` | false (from profile) |
| `portfolio_heat_calculation_method` | correlation_adjusted_exposure |
| `portfolio_heat_heat_threshold_warning` | 0.70 |
| `portfolio_heat_heat_threshold_critical` | 0.85 |

**Time-of-Day Risk Scaling:**
| Parameter | Value |
|-----------|-------|
| `time_of_day_risk_scaling_enabled` | false (from profile) |
| `time_of_day_risk_scaling_us_market_hours` | 09:30-16:00 ET |
| `time_of_day_risk_scaling_asian_session` | 20:00-02:00 ET |
| `time_of_day_risk_scaling_european_session` | 02:00-09:30 ET |
| `time_of_day_risk_scaling_us_market_multiplier` | 1.0 |
| `time_of_day_risk_scaling_asian_multiplier` | 0.8 |
| `time_of_day_risk_scaling_european_multiplier` | 0.9 |
| `time_of_day_risk_scaling_weekend_multiplier` | 0.8 |

**Asset-Specific Rolling PnL Limits:**
| Parameter | Value |
|-----------|-------|
| `asset_specific_rolling_pnl_enabled` | false (from profile) |

---

## 3. DOWNSTREAM LAYER: Sizing

### 3.1 Unified Sizing: `merid/prediction/unified_sizing.py`

**Function:** `compute_order_size()`

#### 3.1.1 Sizing Formula

**Step 1: Use provided max_notional_usd if available, otherwise compute from risk_pct**

**If max_notional_usd provided:**
```
max_notional_usd = provided value
risk_pct_effective = max_notional_usd / bankroll_usd
```

**Otherwise compute from risk_pct:**
```
risk_pct_effective = min(
    min_edge_risk_pct,          # from profile guardrails.min_post_fee_edge
    max_single_order_pct,       # from profile venue.max_single_order_pct
    MERID_BANKROLL_CAP_PCT,     # global safety ceiling (default 2%)
    per_asset_risk_pct          # per-asset from profile (optional)
)
max_notional_usd = bankroll_usd × risk_pct_effective
```

**Step 2: Apply fee impact if requested**
```
if consider_fee_impact and estimated_fee_cents is not None:
    max_notional_usd = max_notional_usd - fee_usd
```

**Step 3: Get per-asset max contracts cap**
```
max_contracts_cap = _get_max_contracts_per_asset(asset)
```

**Step 4: Apply dynamic position sizing if enabled**
```
if _is_dynamic_sizing_enabled():
    dynamic_size = base_contracts + (edge_pct × 100 × edge_multiplier) + (confidence × 100 × confidence_multiplier)
    dynamic_size = max(min_contracts, min(max_contracts, int(dynamic_size)))
    dynamic_sizing_multiplier = dynamic_size / base_contracts
    max_notional_usd = max_notional_usd × dynamic_sizing_multiplier
```

**Step 5: Apply time-of-day risk scaling multiplier**
```
if time_of_day_multiplier != 1.0:
    max_notional_usd = max_notional_usd × time_of_day_multiplier
```

**Step 6: Apply regime-based position size multiplier**
```
regime_multiplier = _get_regime_position_size_multiplier()
if regime_multiplier != 1.0:
    max_notional_usd = max_notional_usd × regime_multiplier
```

**Step 7: Apply TTE-based position size multiplier**
```
tte_multiplier = _get_tte_position_size_multiplier(tte_seconds)
if tte_multiplier != 1.0:
    max_notional_usd = max_notional_usd × tte_multiplier
```

**Step 8: Check existing positions for position-aware sizing**
```
existing_position_notional = sum of existing positions for this asset
if existing_position_notional > 0:
    available_notional = max_notional_usd - existing_position_notional
    if available_notional <= 0:
        return 0, 0, {rejection_reason: "position_limit_exceeded"}
    max_notional_usd = available_notional
```

**Step 9: Convert max_notional to contract count**
```
contract_notional = price_cents / 100.0
contracts_from_notional = floor(max_notional / contract_notional)
```

**Step 10: Validate against min_notional_usd and min_contracts**
```
if computed notional < min_notional_usd:
    reject trade
```

#### 3.1.2 Disabled Scaling Mechanisms

**Regime-Based Sizing:**
- **Status:** DISABLED
- **Rationale:** Regime sizing interferes with 3% per asset / 5% per 15m window limits
- **Implementation:** Always returns 1.0 multiplier
- **Previous Behavior:** UNKNOWN regime returned 0.0 multiplier, blocking ALL trades
- **Fix:** UNKNOWN regime now returns 1.0 to prevent silent blocking

**TTE-Based Sizing:**
- **Status:** DISABLED
- **Rationale:** TTE sizing interferes with 3% per asset / 5% per 15m window limits
- **Implementation:** Always returns 1.0 multiplier
- **Previous Behavior:** Reduced size as expiry approached (NORMAL: 1.0, APPROACHING: 0.75, CRITICAL: 0.5, TERMINAL: 0.25)

**Time-of-Day Sizing:**
- **Status:** DISABLED in profile
- **Rationale:** Time-of-day scaling interferes with 3% per asset limits
- **Implementation:** Multiplier is 1.0 (no scaling)

#### 3.1.3 Dynamic Sizing Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `enabled` | from profile | Enable/disable dynamic sizing |
| `base_contracts` | 1 | Base size |
| `edge_multiplier` | 2.0 | 2026-07-05: Increased from 0.5 to 2.0 (4x) |
| `confidence_multiplier` | 1.0 | 2026-07-05: Increased from 0.3 to 1.0 (3.3x) |
| `max_contracts` | 3 | Max contracts per trade |
| `min_contracts` | 1 | Min contracts per trade |

#### 3.1.4 Venue-Aware Minimum Notional

| Venue | Min Notional | Description |
|-------|--------------|-------------|
| Kalshi | $0.50 | Aligns with profile (micro account support) |

#### 3.1.5 Bankroll Cap Percentage

**Global Safety Ceiling:**
- Reads `MERID_BANKROLL_CAP_PCT` env var
- Clamped to safe range [1%, 2%]
- Default: 2% (max) if not configured
- **Rationale:** This is a GLOBAL SAFETY CEILING, not a primary policy mechanism

---

## 4. AGENT GRID LAYER: Signal Generation

### 4.1 Agent Grid: `merid/prediction/agent_grid_15m.py`

**Class:** `LeanAgentGrid15m`  
**Version:** v20260529a-cache-fix

#### 4.1.1 Strategy Invariants

1. **Velocity-based signals:** Use Coinbase 1-minute velocity for trade direction
2. **Simplified gates:** Only liquidity, spread, staleness (no complex indicator gates)
3. **Market state validation:** Use KalshiMarketStateStore for live orderbook data
4. **Risk envelope:** Apply profile-driven risk limits and position sizing
5. **Full asset coverage:** All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be included

#### 4.1.2 Agent Configuration

**LeanAgentConfig Parameters:**

| Parameter | Value | Description |
|-----------|-------|-------------|
| `signal_mode` | momentum_fvg | Signal mode (from profile) |
| `max_spread_cents` | 100 | Maximum spread in cents |
| `min_time_to_expiry_s` | 180 | Minimum time to expiry in seconds |
| `max_time_to_expiry_s` | 900 | Maximum time to expiry in seconds |
| `per_strip_order_limit` | 200 | Maximum orders per 15m strip |
| `per_asset_cooldown_s` | 8 | Cooldown period in seconds after trade |
| `max_orders_per_15m_window` | 5 | Max 5 trades per 15m session window |
| `consecutive_loss_pause` | 3 | Pause after N consecutive losses |
| `max_session_risk_pct` | 0.10 | Max session risk as % of capital |

**Velocity Thresholds (2026-07-05 FIX):**
| Asset | Threshold | Description |
|-------|-----------|-------------|
| BTC | 0.0015 (0.15%) | Aligned with actual market velocity |
| ETH | 0.0015 (0.15%) | Aligned with actual market velocity |
| SOL | 0.0018 (0.18%) | Slightly higher for high-beta assets |
| XRP | 0.0018 (0.18%) | Slightly higher for high-beta assets |
| DOGE | 0.0020 (0.20%) | Highest for highest volatility asset |

**Rationale:** Previous thresholds (0.6%-1.0%) were 5-12x too high, blocking all trades

#### 4.1.3 Fee-Aware Trading Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `prefer_maker_orders` | true | Prefer maker orders to earn rebates |
| `min_profit_basis_points` | 20 | Minimum 20bp profit target |
| `max_spread_basis_points` | 50 | Maximum 50bp spread |

#### 4.1.4 Fill Rate Optimization

| Parameter | Value | Description |
|-----------|-------|-------------|
| `use_limit_orders` | true | Use limit orders (maker) instead of market orders |
| `limit_order_slippage_cents` | 2 | Allow 2 cents slippage for limit orders |

#### 4.1.5 Hybrid Mode Price Caps

| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_entry_price_yes` | 0.90 | Maximum price to buy YES in hybrid mode |
| `min_entry_price_no` | 0.10 | Minimum price to buy NO in hybrid mode |

**Rationale:** Raised from 80c to 90c based on production bot research (Kalshibot, PolyTrack)

#### 4.1.6 Kalshi Fee Calculation

**Formula:**
```
fee = 7% × p × (1-p) × contract_price
fee = min(fee, 1.75 cents)  # Capped at $0.0175 per contract
```

**Where:**
- `p` = market-implied probability (0.0 to 1.0)
- `contract_price` = price in cents (0 to 100)

#### 4.1.7 Regime Detection Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `volatility_window_s` | 300 | 5-minute volatility window for regime detection |
| `min_volatility_threshold` | 0.001 | Minimum 0.1% volatility to avoid low-volatility death zones |

#### 4.1.8 Kalshi Alignment Tolerances

| Asset | max_abs_diff | max_rel_diff |
|-------|--------------|--------------|
| BTC | 1.0 | 0.0001 |
| ETH | 1.0 | 0.0001 |
| SOL | 1.0 | 0.0001 |
| XRP | 1.0 | 0.0001 |
| DOGE | 1.0 | 0.0001 |

#### 4.1.9 Data Quality Score

**Critical Inputs:**
- spread_cents
- spot_price
- price_cents
- bid
- ask

**Score Calculation:**
```
data_quality = 1.0 - (missing_count / len(critical_inputs))
```

**Rationale:** Enforces Invariant 3: No Optimistic Execution Defaults

---

## 5. EXECUTION GUARD LAYER

### 5.1 Global Execution Guard: `merid/guards/global_execution_guard.py`

**Status:** DEPRECATED  
**Replacement:** `merid.risk.unified_risk_manager.UnifiedRiskManager`

**Deprecation Warning:**
- This module is deprecated in favor of UnifiedRiskManager
- All risk management has been consolidated into a single source of truth
- For kalshi_crypto_15m_v2 profile, risk parameters are loaded from profile YAML
- This module's defaults (3% bankroll cap) are NOT used by the 15m production stack

**Legacy Safety Invariants:**
1. All orders MUST call check_order() before submission
2. Total notional cannot exceed 3% of configured bankroll
3. All decisions are logged with [GLOBAL_GUARD] prefix for audit
4. Fail-closed: any error in guard = order blocked

### 5.2 Execution Guard: `merid/execution_guard.py`

**Class:** `ExecutionGuard`

#### 5.2.1 Safety Layers (checked in order)

1. **Global kill switch** — blocks ALL execution
2. **Per-domain kill switch** — blocks a single domain
3. **CQI throttle** — shrinks or blocks trades when quality degrades
4. **Per-domain daily caps** — max notional per domain per day
5. **Cooldown** — min time between executions

#### 5.2.2 Domain Caps

**DomainCap Parameters:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_daily_notional_usd` | 0.0 | No default - configure from bankroll |
| `max_single_trade_usd` | 0.0 | No default - configure from bankroll |
| `max_daily_trades` | 50 | Default max daily trades |
| `enabled` | true | Enable domain cap |
| `kill_switch` | false | Per-domain kill switch |

**Runtime Counters:**
- `daily_notional_usd` - Reset daily
- `daily_trade_count` - Reset daily
- `last_reset_date` - Track reset date

#### 5.2.3 Venue Exposure Caps

**VenueExposureCap Parameters:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_exposure_usd` | 25000.0 | Per-venue maximum total exposure |
| `current_exposure_usd` | 0.0 | Current exposure |

**Methods:**
- `would_breach(additional_usd)` - Check if additional exposure would breach cap
- `remaining()` - Calculate remaining exposure capacity
- `record(notional_usd)` - Record new exposure
- `release(notional_usd)` - Release exposure

#### 5.2.4 Asset Caps

**AssetCap Parameters:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `max_daily_notional_usd` | 0.0 | No default - configure from bankroll |
| `max_single_trade_usd` | 0.0 | No default - configure from bankroll |

**Runtime Counters:**
- `daily_notional_usd` - Reset daily
- `last_reset_date` - Track reset date

**Methods:**
- `reset_if_new_day()` - Reset daily counter if it's a new day
- `record_trade(notional_usd)` - Record a trade against this asset's daily cap
- `remaining_notional()` - Calculate remaining daily notional capacity
- `utilization_pct()` - Calculate percentage of daily cap used

---

## 6. ORDER ROUTER LAYER

### 6.1 Order Router 15m: `merid/event_venues/kalshi/order_router_15m.py`

**Status:** ⚠️ NOT USED IN PRODUCTION ⚠️

**Warning:**
- This module contains a MOCK order router implementation
- Does NOT execute real orders
- The production system uses `merid.event_venues.kalshi.order_router.py` instead
- This file is kept for reference only

**For Production Order Routing:**
```python
from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
```

**Lean Kalshi Order Router Design:**
- Only talks to Kalshi API (demo or live)
- Applies minimal risk checks
- Has no multi-venue or PM runtime dependencies

**Trading Modes:**
- DEMO: Paper trading on Kalshi demo API
- LIVE: Live trading on Kalshi production API

**Order Intent:**
```python
@dataclass
class KalshiOrderIntent:
    ticker: str  # Kalshi market ticker
    side: OrderSide  # "yes" or "no"
    action: OrderAction  # "buy" or "sell"
    count: int  # Number of contracts
    price_cents: int  # Price in cents
    client_order_id: Optional[str] = None
    risk_checked: bool = False  # Must be True before submission
```

---

## 7. END-TO-END CONSISTENCY CHECKS

### 7.1 Profile vs Risk Envelope Alignment

| Parameter | Profile YAML | Risk Envelope | Status |
|-----------|--------------|---------------|--------|
| max_single_order_pct | 10% | 10% | ✅ Aligned |
| max_total_notional_pct | 15% | 15% | ✅ Aligned |
| per_trade_risk_pct | 2% | 2% | ✅ Aligned |
| drawdown_halt_pct | 20% | 20% | ✅ Aligned |
| drawdown_unwind_pct | 25% | 25% | ✅ Aligned |
| kelly_fraction | 2% | 2% | ✅ Aligned |
| max_daily_loss_pct | 20% | 20% | ✅ Aligned |

### 7.2 Risk Envelope vs Sizing Layer Alignment

| Parameter | Risk Envelope | Sizing Layer | Status |
|-----------|---------------|--------------|--------|
| Per-asset max_notional_pct | 3% | 3% | ✅ Aligned |
| Regime multiplier | DISABLED | DISABLED (always 1.0) | ✅ Aligned |
| TTE multiplier | DISABLED | DISABLED (always 1.0) | ✅ Aligned |
| Time-of-day multiplier | DISABLED | DISABLED (always 1.0) | ✅ Aligned |

### 7.3 Asset Consistency Check

**All 5 assets (BTC, ETH, SOL, XRP, DOGE) are consistently configured:**

| Check | Status |
|-------|--------|
| All assets present in profile YAML | ✅ |
| All assets present in risk envelope | ✅ |
| All assets present in agent grid | ✅ |
| All assets have max_notional_pct configured | ✅ |
| All assets have max_contracts configured | ✅ |
| All assets have depth thresholds configured | ✅ |
| All assets have edge thresholds configured | ✅ |
| All assets have min_decision_minute configured | ✅ |

### 7.4 Risk Limit Consistency

**3% per asset / 5% per 15m window limits are respected:**

| Layer | Implementation | Status |
|-------|----------------|--------|
| Profile YAML | max_notional_pct: 3% per asset | ✅ |
| Profile YAML | agent_defaults.max_notional_pct: 5% per 15m window | ✅ |
| Risk Envelope | Enforces 3% per asset cap | ✅ |
| Risk Envelope | Enforces 5% per 15m window limit | ✅ |
| Sizing Layer | Respects per-asset caps | ✅ |
| Sizing Layer | Position-aware sizing | ✅ |

### 7.5 Scaling Multiplier Check

**No scaling multipliers interfere with hard risk limits:**

| Multiplier | Status | Rationale |
|------------|--------|-----------|
| Regime-based | DISABLED | Would interfere with 3% per asset limits |
| TTE-based | DISABLED | Would interfere with 3% per asset limits |
| Time-of-day | DISABLED | Would interfere with 3% per asset limits |
| Dynamic sizing | ENABLED | Applied AFTER hard caps, respects max_contracts |

---

## 8. TRADING DIRECTIONS: Buy YES, Sell YES, Buy NO, Sell NO

### 8.1 Buy YES (Long Entry)

**Signal Generation:**
- Mode: momentum_fvg
- Conditions:
  - RSI > 55 (bullish momentum)
  - MACD histogram >= 0
  - OBI > threshold (per-asset)
  - EMA stack aligned (fast > slow)
  - Price above EMA50
  - FVG present (if applicable)

**Risk Guards:**
- Price range: 10-70 cents
- Spread: ≤75 cents
- Edge: ≥1.5% post-fee
- Time to expiry: 2-15 minutes
- Depth: ≥1 contract at best bid

**Position Management:**
- Trailing stop: 5c distance, 12c min profit
- Ratchet floor: 85c activation, 80c floor
- Mandatory exit at 99c
- Staged time exits: 5/10/13 minutes

### 8.2 Sell YES (Long Exit / Short Entry)

**Long Exit (Profit Taking):**
- Trailing stop activation
- Ratchet floor breach
- Mandatory exit at 99c
- Staged time exits

**Short Entry (Momentum Short):**
- Mode: momentum_fvg
- Conditions:
  - RSI < 45 (bearish momentum)
  - MACD histogram <= 0
  - OBI < -threshold (per-asset)
  - EMA stack aligned (fast < slow)
  - Price below EMA50
  - FVG present (if applicable)

**Risk Guards:**
- Price range: 10-70 cents
- Spread: ≤75 cents
- Edge: ≥1.5% post-fee
- Time to expiry: 2-15 minutes
- Depth: ≥1 contract at best ask

### 8.3 Buy NO (Short Entry)

**Signal Generation:**
- Mode: momentum_fvg
- Conditions:
  - RSI < 45 (bearish momentum)
  - MACD histogram <= 0
  - OBI < -threshold (per-asset)
  - EMA stack aligned (fast < slow)
  - Price below EMA50
  - FVG present (if applicable)

**Risk Guards:**
- Price range: 10-70 cents (30-70c for hybrid mode)
- Spread: ≤75 cents
- Edge: ≥1.5% post-fee
- Time to expiry: 2-15 minutes
- Depth: ≥1 contract at best ask

**Position Management:**
- Trailing stop: 5c distance, 12c min profit
- Ratchet floor: 85c activation, 80c floor
- Mandatory exit at 99c
- Staged time exits: 5/10/13 minutes

### 8.4 Sell NO (Short Exit / Long Entry)

**Short Exit (Profit Taking):**
- Trailing stop activation
- Ratchet floor breach
- Mandatory exit at 99c
- Staged time exits

**Long Entry (Momentum Long):**
- Mode: momentum_fvg
- Conditions:
  - RSI > 55 (bullish momentum)
  - MACD histogram >= 0
  - OBI > threshold (per-asset)
  - EMA stack aligned (fast > slow)
  - Price above EMA50
  - FVG present (if applicable)

**Risk Guards:**
- Price range: 10-70 cents
- Spread: ≤75 cents
- Edge: ≥1.5% post-fee
- Time to expiry: 2-15 minutes
- Depth: ≥1 contract at best bid

---

## 9. SUMMARY AND RECOMMENDATIONS

### 9.1 Current State Assessment

**Strengths:**
- ✅ All 5 crypto assets consistently configured across all layers
- ✅ Risk limits aligned: 3% per asset, 5% per 15m window, 15% total venue cap
- ✅ Signal mode based on 2026 Turbine research (momentum_fvg)
- ✅ Multiple scaling mechanisms DISABLED to prevent interference with hard risk limits
- ✅ Position management features enabled (trailing stops, ratchet profit floor, staged time exits)
- ✅ Correlation tracking and portfolio heat monitoring enabled
- ✅ Bankroll-tiered per-trade risk for small accounts
- ✅ Adaptive risk bands based on drawdown
- ✅ Comprehensive guardrails (spread, slippage, edge, TTE, price range)

**Areas for Attention:**
- ⚠️ Global execution guard is deprecated (should use UnifiedRiskManager)
- ⚠️ Order router 15m is mock implementation (production uses order_router.py)
- ⚠️ Some 2026 research-based features are disabled in profile adapter (correlation, portfolio heat, time-of-day, asset-specific rolling PnL)
- ⚠️ Velocity thresholds reduced to effectively zero (may need tuning based on live performance)

### 9.2 Consistency Verification

**Upstream → Midstream:**
- ✅ Profile YAML values match risk envelope defaults
- ✅ Profile YAML percentages correctly converted to USD in risk envelope
- ✅ Per-asset caps computed correctly with minimum floor
- ✅ Adaptive risk bands loaded from profile

**Midstream → Downstream:**
- ✅ Risk envelope defaults match sizing layer behavior
- ✅ Per-asset caps enforced in sizing layer
- ✅ Position-aware sizing implemented
- ✅ Disabled scaling mechanisms aligned (regime, TTE, time-of-day)

**Downstream → Execution:**
- ✅ Sizing layer respects hard risk limits
- ✅ Dynamic sizing applied AFTER hard caps
- ✅ Order size validated against min_notional and min_contracts

### 9.3 Recommendations

1. **Consolidate Risk Management:**
   - Migrate from deprecated GlobalExecutionGuard to UnifiedRiskManager
   - Ensure all risk checks use UnifiedRiskManager as single source of truth

2. **Enable 2026 Research-Based Features:**
   - Consider enabling correlation tracking in profile adapter (currently disabled)
   - Consider enabling portfolio heat tracking in profile adapter (currently disabled)
   - Consider enabling asset-specific rolling PnL limits in profile adapter (currently disabled)

3. **Monitor Velocity Thresholds:**
   - Current thresholds (0.001%) are effectively zero
   - Monitor live performance to determine if thresholds need adjustment
   - Consider implementing adaptive velocity thresholds based on market conditions

4. **Validate Order Router:**
   - Ensure production uses order_router.py (not order_router_15m.py)
   - Verify order_router.py implements all risk checks from profile
   - Test order routing end-to-end with live Kalshi API

5. **Document Asset-Specific Behavior:**
   - Monitor if Tier 1 (BTC/ETH) vs Tier 2 (SOL/XRP/DOGE) differences are justified
   - Consider unifying edge thresholds if performance is similar across tiers
   - Document rationale for per-asset differences

6. **Review Position Management:**
   - Monitor effectiveness of trailing stops, ratchet profit floor, staged time exits
   - Consider adjusting parameters based on live performance
   - Ensure position management features don't interfere with risk limits

---

## 10. APPENDIX: Configuration Files Reference

### 10.1 Upstream Configuration Files

| File | Purpose | Status |
|------|---------|--------|
| `config/profiles/kalshi_crypto_15m_v2.yaml` | Single source of truth for risk configuration | ✅ Production |
| `config/kalshi_15m_crypto_config.py` | Deprecated (use YAML) | ❌ Deprecated |
| `archive/legacy/crypto15mallocator.py` | Archived (not used in production) | ❌ Archived |
| `web/snapshots/15m_risk_*/` | Deleted (obsolete) | ❌ Deleted |

### 10.2 Midstream Risk Files

| File | Purpose | Status |
|------|---------|--------|
| `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` | Risk envelope computation | ✅ Production |
| `merid/risk/profiles/crypto_15m_profile.py` | Profile adapter | ✅ Production |
| `merid/risk/unified_risk_manager.py` | Unified risk manager (replacement for GlobalExecutionGuard) | ✅ Production |

### 10.3 Downstream Sizing Files

| File | Purpose | Status |
|------|---------|--------|
| `merid/prediction/unified_sizing.py` | Unified order sizing | ✅ Production |
| `merid/event_venues/kalshi/invariants.py` | Kalshi contract math | ✅ Production |

### 10.4 Agent Grid Files

| File | Purpose | Status |
|------|---------|--------|
| `merid/prediction/agent_grid_15m.py` | Lean agent grid for 15m crypto | ✅ Production |
| `merid/agents/btc_15m_agent.py` | BTC 15m agent | ✅ Production |
| `merid/agents/eth_15m_agent.py` | ETH 15m agent | ✅ Production |
| `merid/agents/sol_15m_agent.py` | SOL 15m agent | ✅ Production |
| `merid/agents/xrp_15m_agent.py` | XRP 15m agent | ✅ Production |
| `merid/agents/doge_15m_agent.py` | DOGE 15m agent | ✅ Production |

### 10.5 Execution Guard Files

| File | Purpose | Status |
|------|---------|--------|
| `merid/guards/global_execution_guard.py` | Deprecated global execution guard | ⚠️ Deprecated |
| `merid/execution_guard.py` | Execution guard (CQI throttle, per-domain caps) | ✅ Production |
| `merid/event_venues/kalshi/order_router.py` | Production order router | ✅ Production |
| `merid/event_venues/kalshi/order_router_15m.py` | Mock order router (reference only) | ⚠️ Not Used |

---

**Document End**

**Generated:** 2026-07-05  
**Profile:** kalshi_crypto_15m_v2  
**Version:** 2.3.0

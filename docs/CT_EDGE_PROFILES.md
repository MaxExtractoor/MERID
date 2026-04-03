# Continuous Trader Edge Profiles

This document describes the edge threshold profiles for the Kalshi Continuous Trader (CT) and how to configure them for different trading scenarios.

## Problem Statement

In live runs, we observed:
- Gate: `state=clear blocked=False safe_to_trade=True` ✓
- Filter pipeline: 5+ good candidates per cycle ✓
- CT logs: `No markets with sufficient edge (edge_too_low=N)` ✗
- **No orders evaluated or sent** ✗

**Root cause**: The default EDGE_THRESHOLDS (2-8%) are too high for initial live trading with micro-size positions. Markets with positive edge (e.g., 0.5-1.5%) were being rejected as "edge_too_low".

## Solution: Two-Profile System

We now support two edge threshold profiles:

### 1. `initial_live` Profile (Permissive)

**Purpose**: Get live with real money at micro-size to validate the entire pipeline.

**Thresholds**:
```python
# BTC - most liquid, tightest spreads
("BTC", "15m"):    0.005  # 0.5%
("BTC", "1h"):     0.008  # 0.8%
("BTC", "daily"):  0.012  # 1.2%
("BTC", "weekly"): 0.015  # 1.5%

# ETH - second most liquid
("ETH", "15m"):    0.008  # 0.8%
("ETH", "1h"):     0.010  # 1.0%
("ETH", "daily"):  0.015  # 1.5%
("ETH", "weekly"): 0.018  # 1.8%

# SOL/XRP/DOGE - wider spreads
("SOL/XRP/DOGE", "15m"):    0.010  # 1.0%
("SOL/XRP/DOGE", "1h"):     0.012  # 1.2%
("SOL/XRP/DOGE", "daily"):  0.015  # 1.5%
("SOL/XRP/DOGE", "weekly"): 0.020  # 2.0%
```

**When to use**:
- Initial live rollout with tiny position limits
- Validating that CT can evaluate and execute trades
- Proving the full pipeline works: indicators → edge → sizing → order send
- Small bankroll ($100-500) with micro-size caps

### 2. `production` Profile (Conservative)

**Purpose**: Full-size trading with higher confidence requirements.

**Thresholds** (original values):
```python
# BTC
("BTC", "15m"):    0.02  # 2%
("BTC", "1h"):     0.03  # 3%
("BTC", "daily"):  0.04  # 4%
("BTC", "weekly"): 0.05  # 5%

# ETH
("ETH", "15m"):    0.03  # 3%
("ETH", "1h"):     0.04  # 4%
("ETH", "daily"):  0.05  # 5%
("ETH", "weekly"): 0.06  # 6%

# SOL/XRP/DOGE
("SOL/XRP/DOGE", "15m"):    0.04  # 4%
("SOL/XRP/DOGE", "1h"):     0.06  # 6%
("SOL/XRP/DOGE", "daily"):  0.06  # 6%
("SOL/XRP/DOGE", "weekly"): 0.08  # 8%
```

**When to use**:
- After initial_live validation succeeds
- Full bankroll ($1000+) with standard position limits
- Steady-state production trading

## Configuration

### Environment Variables

```bash
# Select edge profile (default: "production")
export KALSHI_CT_EDGE_PROFILE="initial_live"  # or "production"

# Other CT config (works with both profiles)
export MERID_GROUP_NOTIONAL_CAP="50.0"         # Max $ per asset/timeframe group
export MERID_MIN_CONFIDENCE="0.55"             # Min confidence (0-1)
export MERID_BANKROLL_FRACTION="0.01"          # 1% of bankroll per trade
export MERID_MAX_YES_PRICE="0.50"              # Max YES price (50¢)
export MERID_KELLY_FRACTION="0.25"             # Kelly multiplier (25% of full Kelly)
export MERID_MIN_EDGE="0.02"                   # Fallback min edge (2%)
```

### Initial Live .env Example

```bash
# ===================================================================
# INITIAL LIVE PROFILE - Micro-size trading for pipeline validation
# ===================================================================

# Edge profile: CRITICAL setting
export KALSHI_CT_EDGE_PROFILE="initial_live"

# Very tight caps for safety
export MERID_GROUP_NOTIONAL_CAP="10.0"         # Only $10 per group
export MERID_MAX_YES_PRICE="0.65"              # Can buy up to 65¢ (higher ceiling)
export MERID_KELLY_FRACTION="0.10"             # Only 10% of Kelly (very conservative)

# Slightly lower confidence bar (to get trades flowing)
export MERID_MIN_CONFIDENCE="0.52"             # 52% vs default 55%

# Bankroll and general limits
export MERID_BANKROLL_FRACTION="0.005"         # 0.5% of bankroll per trade
export MERID_MIN_EDGE="0.005"                  # 0.5% fallback (aligned with profile)
```

### Production .env Example

```bash
# ===================================================================
# PRODUCTION PROFILE - Standard trading after validation
# ===================================================================

# Edge profile: Use conservative thresholds
export KALSHI_CT_EDGE_PROFILE="production"

# Standard caps
export MERID_GROUP_NOTIONAL_CAP="50.0"         # $50 per group
export MERID_MAX_YES_PRICE="0.50"              # 50¢ ceiling
export MERID_KELLY_FRACTION="0.25"             # 25% of full Kelly

# Standard confidence requirements
export MERID_MIN_CONFIDENCE="0.55"             # 55%

# Bankroll and general limits
export MERID_BANKROLL_FRACTION="0.01"          # 1% of bankroll per trade
export MERID_MIN_EDGE="0.02"                   # 2% fallback
```

## Validation: Proving CT Works

### Phase 1: Initial Live (Micro-size)

**Goals**:
- See `[CT-TRACE]` lines with `veto=none` (not all `edge_too_low`)
- See `[PRE-ORDER]` / order intent logs
- Confirm actual Kalshi API sends (POST/WS) and fills

**Expected behavior**:
```log
[CT-TRACE] ticker=KXBTC-15M-T95000 asset=BTC side=YES win_prob=0.5120 payout=45.00 edge_bps=12.0
           kelly_raw=0.0053 kelly_frac=0.0005 size=1 veto=none

[PRE-ORDER] BTC/15m YES 1 contracts @ 55¢ (edge=1.2% kelly=0.53%)

Kalshi API: POST /trade/orders {...} → order_id=abc123
```

**Success criteria**:
- 1-3 trades per hour (not zero)
- No critical errors or downstream vetos
- Tiny fills confirm full pipeline works

### Phase 2: Production (Standard Size)

**After** initial_live succeeds for 24-48 hours:
- Switch to `KALSHI_CT_EDGE_PROFILE="production"`
- Increase caps to standard levels
- Monitor PnL and fill rates

## Logging and Monitoring

CT now logs the active edge profile in status:

```python
trader = get_continuous_trader()
status = trader.status()
print(status["config"]["edge_profile"])  # "initial_live" or "production"
```

Confirm in logs:
```log
ContinuousTrader starting — assets=('BTC', 'ETH', ...) edge_profile=initial_live
                            max_yes_price=0.65 min_confidence=0.52
```

## Decision Story Example

### BTC 15m Market (Initial Live Profile)

```
1. Filter: KXBTC-15M-T95000 passes (volume OK, spread 2¢, strike near spot)

2. Indicators:
   - bias=long, confidence=0.58
   - indicator_age=12s (fresh)
   - vol_band=mid

3. Model:
   - model_yes=0.512 (52% chance YES)
   - implied_yes=0.550 (market mid price)
   - best_edge=-0.038 for YES, +0.012 for NO
   - edge_pct=+1.2% (positive for NO side)

4. Edge check:
   - min_edge_required (BTC/15m, initial_live) = 0.5%
   - edge_pct = 1.2%
   - ✓ PASS: 1.2% > 0.5%

5. Kelly sizing:
   - win_prob=0.512, payout=45¢, kelly_raw=0.0053
   - kelly_frac=0.0053 × 0.10 = 0.00053
   - size = floor(bankroll × kelly_frac / price) = 1 contract
   - ✓ size > 0

6. Risk checks:
   - group_notional_used (BTC/15m) = $0 < $10 cap ✓
   - confidence = 0.58 > 0.52 ✓

7. Downstream:
   - _live_api_orders_allowed() = True ✓
   - guardian.can_trade() = True ✓

8. Result:
   - [CT-TRACE] veto=none
   - [PRE-ORDER] intent created
   - Kalshi API send successful
```

### DOGE 1h Market (Production Profile)

```
1. Filter: KXDOGE-1H-T0.15 passes

2. Model:
   - edge_pct=+1.8%

3. Edge check:
   - min_edge_required (DOGE/1h, production) = 6.0%
   - edge_pct = 1.8%
   - ✗ FAIL: 1.8% < 6.0%
   - [CT-TRACE] veto=edge_too_low

4. Result: No trade (as expected in production with tight thresholds)
```

## Migration Path

1. **Start**: `production` profile (default) → seeing "edge_too_low"
2. **Switch**: `initial_live` profile → start seeing trades
3. **Validate**: 24-48 hours, confirm fills and PnL behavior
4. **Graduate**: Back to `production` OR tune production thresholds based on data

## Summary

| Setting | Initial Live | Production |
|---------|--------------|------------|
| BTC/15m edge | 0.5% | 2.0% |
| BTC/1h edge | 0.8% | 3.0% |
| DOGE/15m edge | 1.0% | 4.0% |
| DOGE/1h edge | 1.2% | 6.0% |
| Group cap | $10 | $50 |
| Kelly frac | 10% | 25% |
| Min confidence | 52% | 55% |
| **Goal** | Prove pipeline | Profitable trading |

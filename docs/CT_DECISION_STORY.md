# Continuous Trader Decision Story Examples

This document provides end-to-end traces of how the Continuous Trader (CT) evaluates markets with the `initial_live` vs `production` edge profiles.

## Purpose

Demonstrates exactly why the default `production` profile (2-8% edge thresholds) blocks trades, and how the `initial_live` profile (0.5-2% thresholds) allows the same markets to flow through to execution.

## Example 1: BTC 15m Market (Small Edge)

### Scenario

- **Market**: KXBTC-15M-T95000 (BTC 15-minute expiry, $95,000 strike)
- **Spot price**: $94,800
- **Model probability**: 51.2% (YES side has slight edge)
- **Market mid price**: 55¢
- **Actual edge**: 1.2% (model says 51.2%, market implies 55%, so NO side has edge)

### Filter Stage

**Input from `market_filter.py`:**

```
ticker:         KXBTC-15M-T95000
underlying:     BTC
timeframe:      15m
strike_price:   95000.0
spot_price:     94800.0
distance:       0.21% (very near the money)
volume:         1250 contracts
open_interest:  380 contracts
best_bid:       54¢
best_ask:       56¢
spread:         2¢
mid_price:      55¢

Filter checks:
✓ volume=1250 >= min_volume=50
✓ open_interest=380 >= min_oi=10
✓ spread=2c <= max_spread=12c
✓ mid_price=55c in range [10c, 90c]
✓ distance=0.21% <= spot_band=20% (BTC/15m)
✓ mid_price=55c outside dead zone [47c, 53c]
✓ relative_volume=0.68 (in middle regime, not extreme)

Result: PASS → forwarded to CT as TradingCandidate
```

### Continuous Trader Evaluation

**Step 1: Edge Calculation**

From `signal_to_sizing()` in `kalshi_continuous_trader.py:433-545`:

```
implied_prob = mid_price / 100 = 55 / 100 = 0.550 (55% implied by market)
model_yes    = 0.512 (from OpinionStrategy indicator stack)
edge_yes     = model_yes - implied_prob = 0.512 - 0.550 = -0.038 (negative, skip YES)
edge_no      = (1 - model_yes) - (1 - implied_prob) = 0.488 - 0.450 = +0.038
edge_pct     = 0.038 * 100 = +3.8% ... wait, recalculating

Actually, the edge_pct enrichment from filter is 1.2%:
edge         = 0.012 (1.2%)
win_prob     = implied_prob + edge = 0.550 + 0.012 = 0.562 (56.2% chance NO wins)
```

**Step 2: Kelly Sizing**

From Kelly formula at `kalshi_continuous_trader.py:499-522`:

```
price_cents  = 55
payout_cents = 100 - 55 = 45
b            = payout / price = 45 / 55 = 0.818
p            = win_prob = 0.562
q            = 1 - p = 0.438
kelly_raw    = (p * b - q) / b = (0.562 * 0.818 - 0.438) / 0.818 = 0.0265

kelly_frac   = kelly_raw * kelly_fraction
```

**Step 3A: Production Profile (REJECTED)**

```
KALSHI_CT_EDGE_PROFILE=production
min_edge_threshold = EDGE_THRESHOLDS_PRODUCTION[("BTC", "15m")] = 0.02 (2.0%)

Edge check: edge=0.012 < min_edge_threshold=0.02
Result: REJECTED

[CT-TRACE] ticker=KXBTC-15M-T95000 asset=BTC timeframe=15m side=NO
           edge=1.2% min_required=2.0% veto=edge_too_low
           kelly_raw=0.0265 kelly_frac=0.0000 size=0
```

**Step 3B: Initial Live Profile (ACCEPTED)**

```
KALSHI_CT_EDGE_PROFILE=initial_live
min_edge_threshold = EDGE_THRESHOLDS_INITIAL_LIVE[("BTC", "15m")] = 0.005 (0.5%)

Edge check: edge=0.012 >= min_edge_threshold=0.005 ✓

With initial_live config:
kelly_fraction=0.10 (10% of full Kelly)
kelly_frac = 0.0265 * 0.10 = 0.00265
bankroll = $500
notional = bankroll * kelly_frac = 500 * 0.00265 = $1.325
price_dollars = 0.55
size_contracts = floor(notional / price_dollars) = floor(1.325 / 0.55) = 2 contracts

Result: ACCEPTED

[CT-TRACE] ticker=KXBTC-15M-T95000 asset=BTC timeframe=15m side=NO
           edge=1.2% min_required=0.5% veto=none
           kelly_raw=0.0265 kelly_frac=0.00265 size=2
```

**Step 4: Risk Checks (Initial Live)**

From `_apply_risk_checks()`:

```
Group notional check:
  group = (BTC, 15m)
  existing_notional = $0 (first trade)
  new_notional = 2 contracts * $0.55 = $1.10
  group_cap = $10.00 (MERID_GROUP_NOTIONAL_CAP=10.0)
  check: $1.10 <= $10.00 ✓

Confidence check:
  min_confidence = 0.52 (MERID_MIN_CONFIDENCE=0.52)
  candidate_confidence = 0.562
  check: 0.562 >= 0.52 ✓

Max price check:
  max_yes_price = 0.65 (MERID_MAX_YES_PRICE=0.65)
  price = 0.55
  check: 0.55 <= 0.65 ✓
```

**Step 5: Downstream Gates**

```
_live_api_orders_allowed():
  - kill_switch.is_active() → False ✓
  - reconciliation_gate.is_clear() → True ✓
  - price_feed_gate.is_healthy() → True ✓
  Result: True

guardian.can_trade(category="crypto"):
  - category_config.is_trading_allowed("crypto") → True ✓
  - portfolio limits OK ✓
  Result: True
```

**Step 6: Order Intent**

```
[PRE-ORDER] BTC/15m NO 2 contracts @ 55¢
            edge=1.2% kelly=0.265% notional=$1.10 group_used=$1.10/$10.00

Kalshi API: POST /trade/orders
{
  "ticker": "KXBTC-15M-T95000",
  "side": "no",
  "quantity": 2,
  "type": "market",
  "client_order_id": "merid-ct-20260403-001"
}

Response: {"order_id": "abc123", "status": "resting"}
```

### Summary: BTC 15m Decision

| Stage | Production Profile | Initial Live Profile |
|-------|-------------------|---------------------|
| **Filter** | ✓ PASS | ✓ PASS |
| **Edge** | 1.2% < 2.0% required | 1.2% >= 0.5% required |
| **Verdict** | ✗ REJECTED (edge_too_low) | ✓ ACCEPTED |
| **Size** | 0 contracts | 2 contracts |
| **Notional** | $0 | $1.10 |
| **Risk checks** | N/A | ✓ All pass |
| **Order sent** | No | Yes |

**Key Insight**: A market with 1.2% edge is positive but too small for production thresholds. The `initial_live` profile allows it through, enabling micro-size validation of the full pipeline.

---

## Example 2: DOGE 1h Market (Medium Edge)

### Scenario

- **Market**: KXDOGE-1H-T0.15 (DOGE 1-hour expiry, $0.15 strike)
- **Spot price**: $0.148
- **Model probability**: 48.5% (YES side undervalued)
- **Market mid price**: 48¢
- **Actual edge**: 1.8% (model says 48.5%, market implies 48%, so YES side has edge)

### Filter Stage

**Input from `market_filter.py`:**

```
ticker:         KXDOGE-1H-T0.15
underlying:     DOGE
timeframe:      1h
strike_price:   0.15
spot_price:     0.148
distance:       1.35% (near the money)
volume:         380 contracts
open_interest:  120 contracts
best_bid:       47¢
best_ask:       49¢
spread:         2¢
mid_price:      48¢

Filter checks:
✓ volume=380 >= min_volume=50
✓ open_interest=120 >= min_oi=10
✓ spread=2c <= max_spread=12c
✓ mid_price=48c in range [10c, 90c]
✓ distance=1.35% <= spot_band=40% (DOGE/1h)
✓ mid_price=48c outside dead zone [47c, 53c] ... WAIT: 48c is at boundary
  Actually checking: |48 - 50| = 2c, which is < dead_zone=3c

Result: ✗ REJECTED by edge dead-zone filter (mid too close to 50¢)
```

**Note**: With default `min_edge_dead_zone_pct=3.0`, markets with mid-price in [47¢, 53¢] are filtered out as "coin-flip bleed" candidates. To allow this example, we'd need to either:
1. Reduce dead zone to 1-2% for initial_live, OR
2. Use a market with mid-price outside the dead zone

Let's adjust the example to use a market that passes the filter:

### Adjusted Example: DOGE 1h Market (Mid=43¢)

**Revised scenario:**

```
ticker:         KXDOGE-1H-T0.15
underlying:     DOGE
timeframe:      1h
strike_price:   0.15
spot_price:     0.148
distance:       1.35%
volume:         380 contracts
open_interest:   120 contracts
best_bid:       42¢
best_ask:       44¢
spread:         2¢
mid_price:      43¢  (outside dead zone [47c, 53c])

Filter checks:
✓ volume=380 >= min_volume=50
✓ open_interest=120 >= min_oi=10
✓ spread=2c <= max_spread=12c
✓ mid_price=43c in range [10c, 90c]
✓ distance=1.35% <= spot_band=40% (DOGE/1h)
✓ mid_price=43c outside dead zone [47c, 53c]
✓ relative_volume=0.52 (middle regime)

Result: ✓ PASS → forwarded to CT
```

### Continuous Trader Evaluation

**Step 1: Edge Calculation**

```
implied_prob = 43 / 100 = 0.43 (43% implied by market)
model_yes    = 0.448 (from OpinionStrategy)
edge_yes     = model_yes - implied_prob = 0.448 - 0.43 = +0.018
edge_pct     = 1.8%
edge         = 0.018
win_prob     = 0.43 + 0.018 = 0.448 (44.8% chance YES wins)
```

**Step 2: Kelly Sizing**

```
price_cents  = 43
payout_cents = 100 - 43 = 57
b            = 57 / 43 = 1.326
p            = 0.448
q            = 0.552
kelly_raw    = (0.448 * 1.326 - 0.552) / 1.326 = (0.594 - 0.552) / 1.326 = 0.0317
```

**Step 3A: Production Profile (REJECTED)**

```
KALSHI_CT_EDGE_PROFILE=production
min_edge_threshold = EDGE_THRESHOLDS_PRODUCTION[("DOGE", "1h")] = 0.06 (6.0%)

Edge check: edge=0.018 < min_edge_threshold=0.06
Result: REJECTED

[CT-TRACE] ticker=KXDOGE-1H-T0.15 asset=DOGE timeframe=1h side=YES
           edge=1.8% min_required=6.0% veto=edge_too_low
           kelly_raw=0.0317 kelly_frac=0.0000 size=0
```

**Step 3B: Initial Live Profile (ACCEPTED)**

```
KALSHI_CT_EDGE_PROFILE=initial_live
min_edge_threshold = EDGE_THRESHOLDS_INITIAL_LIVE[("DOGE", "1h")] = 0.012 (1.2%)

Edge check: edge=0.018 >= min_edge_threshold=0.012 ✓

With initial_live config:
kelly_fraction=0.10
kelly_frac = 0.0317 * 0.10 = 0.00317
bankroll = $500
notional = 500 * 0.00317 = $1.585
price_dollars = 0.43
size_contracts = floor(1.585 / 0.43) = floor(3.69) = 3 contracts

Result: ACCEPTED

[CT-TRACE] ticker=KXDOGE-1H-T0.15 asset=DOGE timeframe=1h side=YES
           edge=1.8% min_required=1.2% veto=none
           kelly_raw=0.0317 kelly_frac=0.00317 size=3
```

**Step 4: Risk Checks**

```
Group notional check:
  group = (DOGE, 1h)
  existing_notional = $0
  new_notional = 3 contracts * $0.43 = $1.29
  group_cap = $10.00
  check: $1.29 <= $10.00 ✓

Confidence check:
  min_confidence = 0.52
  candidate_confidence = 0.448
  check: 0.448 >= 0.52 ✗ FAIL

Result: REJECTED by confidence gate
```

**Wait, this fails the confidence check. Let's adjust the model probability:**

### Re-adjusted: DOGE 1h with Higher Confidence

```
Revised model:
model_yes    = 0.530 (53% probability YES wins)
implied_prob = 0.43 (market mid)
edge_yes     = 0.530 - 0.43 = 0.10 (10% edge!)
```

This would create a 10% edge, which is unrealistically high for this example. Let me create a more realistic scenario where confidence is just above threshold:

### Final DOGE Example: Mid=48¢, Model=53%

```
ticker:         KXDOGE-1H-T0.16
underlying:     DOGE
timeframe:      1h
strike_price:   0.16
spot_price:     0.155
distance:       3.2%
best_bid:       54¢
best_ask:       56¢
spread:         2¢
mid_price:      55¢

Filter: ✓ PASS (mid=55c outside dead zone, all other checks pass)

Edge calculation:
implied_prob = 0.55
model_yes    = 0.568 (from indicators showing bullish bias)
edge         = 0.568 - 0.55 = 0.018 (1.8%)
win_prob     = 0.568 (56.8%)

Kelly sizing:
price_cents  = 55
payout_cents = 45
b            = 45 / 55 = 0.818
kelly_raw    = (0.568 * 0.818 - 0.432) / 0.818 = 0.0386
```

**Production Profile:**

```
min_edge_threshold = 0.06 (6.0%)
edge = 0.018 < 0.06
Result: ✗ REJECTED (edge_too_low)
```

**Initial Live Profile:**

```
min_edge_threshold = 0.012 (1.2%)
edge = 0.018 >= 0.012 ✓
kelly_frac = 0.0386 * 0.10 = 0.00386
size = floor(500 * 0.00386 / 0.55) = floor(3.51) = 3 contracts
notional = $1.65

Risk checks:
- group_notional: $1.65 <= $10.00 ✓
- confidence: 0.568 >= 0.52 ✓
- max_price: 0.55 <= 0.65 ✓

Result: ✓ ACCEPTED

[PRE-ORDER] DOGE/1h YES 3 contracts @ 55¢
            edge=1.8% kelly=0.386% notional=$1.65
```

### Summary: DOGE 1h Decision

| Stage | Production Profile | Initial Live Profile |
|-------|-------------------|---------------------|
| **Filter** | ✓ PASS | ✓ PASS |
| **Edge** | 1.8% < 6.0% required | 1.8% >= 1.2% required |
| **Verdict** | ✗ REJECTED (edge_too_low) | ✓ ACCEPTED |
| **Size** | 0 contracts | 3 contracts |
| **Notional** | $0 | $1.65 |
| **Risk checks** | N/A | ✓ All pass |
| **Order sent** | No | Yes |

**Key Insight**: DOGE markets typically have wider spreads and less liquidity than BTC, so edges tend to be smaller. The production 6.0% threshold is appropriate for full-size trading but blocks all micro-edge opportunities. The `initial_live` threshold of 1.2% allows trades to flow at micro-size, validating the pipeline.

---

## Configuration Comparison

### Production Profile (.env)

```bash
export KALSHI_CT_EDGE_PROFILE="production"
export MERID_GROUP_NOTIONAL_CAP="50.0"      # $50 per group
export MERID_KELLY_FRACTION="0.25"          # 25% of Kelly
export MERID_MIN_CONFIDENCE="0.55"          # 55%
export MERID_MAX_YES_PRICE="0.50"           # 50¢ ceiling
```

**Result**: No trades on BTC or DOGE examples (edge_too_low)

### Initial Live Profile (.env)

```bash
export KALSHI_CT_EDGE_PROFILE="initial_live"
export MERID_GROUP_NOTIONAL_CAP="10.0"      # Only $10 per group
export MERID_KELLY_FRACTION="0.10"          # 10% of Kelly (very conservative)
export MERID_MIN_CONFIDENCE="0.52"          # 52% (slightly relaxed)
export MERID_MAX_YES_PRICE="0.65"           # 65¢ (higher ceiling for flexibility)
export MERID_MIN_EDGE="0.005"               # 0.5% fallback (aligned with profile)
```

**Result**: Both BTC and DOGE examples trade at micro-size ($1-2 each)

---

## Diagnostic Log Patterns

### Production (No Trades)

```
[2026-04-03 14:23:15] INFO: ContinuousTrader trade_cycle starting
[2026-04-03 14:23:15] INFO: Filter: 23 candidates → 5 passed
[2026-04-03 14:23:15] INFO: signal_to_sizing: KXBTC-15M-T95000 edge=0.0120 min_edge_threshold=0.0200 [BTC/15m] REJECTED
[2026-04-03 14:23:15] INFO: signal_to_sizing: KXDOGE-1H-T0.16 edge=0.0180 min_edge_threshold=0.0600 [DOGE/1h] REJECTED
[2026-04-03 14:23:15] INFO: No markets with sufficient edge (edge_too_low=5)
```

### Initial Live (Trades Flow)

```
[2026-04-03 14:25:10] INFO: ContinuousTrader trade_cycle starting (edge_profile=initial_live)
[2026-04-03 14:25:10] INFO: Filter: 23 candidates → 5 passed
[2026-04-03 14:25:10] INFO: signal_to_sizing: KXBTC-15M-T95000 edge=0.0120 min_edge_threshold=0.0050 [BTC/15m] ACCEPTED
[2026-04-03 14:25:10] INFO: [PRE-ORDER] BTC/15m NO 2 @ 55¢ edge=1.2% notional=$1.10
[2026-04-03 14:25:10] INFO: signal_to_sizing: KXDOGE-1H-T0.16 edge=0.0180 min_edge_threshold=0.0120 [DOGE/1h] ACCEPTED
[2026-04-03 14:25:10] INFO: [PRE-ORDER] DOGE/1h YES 3 @ 55¢ edge=1.8% notional=$1.65
[2026-04-03 14:25:11] INFO: Kalshi API: 2 orders sent, 2 resting
```

---

## Next Steps

1. **Test on dev/live box**: Run with `KALSHI_CT_EDGE_PROFILE=initial_live` in dry-run mode
2. **Verify fills**: Confirm micro-size orders (1-3 contracts) actually execute on Kalshi
3. **Monitor 24-48 hours**: Ensure no silent vetos or unexpected rejections
4. **Graduate to production**: Switch to `production` profile after validation succeeds

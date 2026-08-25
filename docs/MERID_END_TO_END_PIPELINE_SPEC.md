# MERID End-to-End Pipeline Specification

## Overview

This document defines the canonical data flow through the MERID 15-minute Kalshi crypto trading system, from raw market data ingestion to realized PnL. It serves as the authoritative reference for cross-layer invariant checks and system validation.

## Pipeline Stages

### Stage 1: Upstream (Data Ingestion & Feature Engineering)

**Input:** Raw market data from external sources
- Spot prices (BTC/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD)
- Orderbook snapshots (bid/ask, depth)
- Volatility feeds (realized, implied)
- Volume metrics

**Transformations:**
- TA frame wiring (candlestick pattern detection)
- Derived feature computation:
  - Velocity (price change rate)
  - Spot→strike distance
  - Realized/implicit volatility
  - Regime tags (normal, crisis, halt)

**Output:** Feature vectors per asset per timeframe
- `TAFrame` objects with OHLCV data
- Derived features in `FeatureVector` objects
- Regime classification

**Key Invariants:**
- All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be processed
- Feature vectors must be complete (no missing required fields)
- Regime tags must be consistent across all assets in same timeframe

---

### Stage 2: Midstream (Modeling & Decision Logic)

**Input:** Feature vectors from upstream
- TA frames with patterns
- Derived features (velocity, vol, distance)
- Regime tags

**Transformations:**
- Model probability computation per contract
  - `p_model_yes` for YES contracts
  - `p_model_no` for NO contracts
- Edge calculation:
  - `edge = p_model - p_market` (where p_market = price_cents/100)
- Confidence scoring:
  - Based on `|p_model - 0.5|` and `|edge|`
  - Must be monotonic with edge magnitude
- Side selection:
  - Long/short based on edge sign
  - Up/down based on price direction thesis
- Intent generation:
  - Maps TA patterns + features to trading intents
  - Intent → thesis_side mapping (UP/DOWN)

**Output:** Trading intents with metadata
- `Intent` objects with:
  - `thesis_side` (UP/DOWN)
  - `edge` (signed, cents)
  - `confidence` (0-1)
  - `regime_tag`
  - `action` (ENTER/EXIT/FLATTEN)

**Key Invariants:**
- If `p_model > 0.5` and `edge > 0`: must not be short YES or long NO
- If `p_model < 0.5` and `edge < 0`: must not be long YES
- Confidence must be monotonic in `|p_model - 0.5|` or `|edge|`
- No trade when `|edge| < threshold` regardless of confidence
- Thesis_side must be consistent with edge sign and model probability

---

### Stage 3: Downstream (Contract Selection & Risk)

**Input:** Trading intents from midstream
- Thesis_side (UP/DOWN)
- Edge magnitude
- Confidence score
- Regime tag

**Transformations:**
- Contract selection:
  - Filter by spot→strike distance (δ = (strike - spot)/spot)
  - Allowed δ window per strategy (e.g., |δ| < 0.1 for baseline)
  - Deep OTM contracts blocked unless extreme edge
- Contract abstraction:
  - Expiry time selection (15m windows)
  - Strike price selection
  - Side mapping (YES/NO based on thesis_side)
- Risk enforcement:
  - Position sizing via global slot allocator ($1 fixed cap)
  - Bankroll allocation (MERID_FIXED_EXPOSURE_CAP_USD=1.00)
  - Velocity/volatility/volume gating
  - Regime-based sizing adjustments

**Output:** Contract selection with risk parameters
- `SelectedContract` objects with:
  - `ticker` (Kalshi market ID)
  - `contract_type` (YES/NO)
  - `strike_price`
  - `expiry`
  - `max_size` (contracts)
  - `risk_limit_usd`

**Key Invariants:**
- Spot→strike distance must be within allowed window for strategy
- Deep OTM contracts (δ > threshold) blocked unless edge extreme
- High volatility regime: position size shrunk or strategy disabled
- Low volume regime: max notional enforced, large orders forbidden
- Extreme velocity: contrarian entries forbidden, momentum only with stricter edge
- Total exposure never exceeds $1 (MERID_FIXED_EXPOSURE_CAP_USD)

---

### Stage 4: Execution (Order Routing & Fills)

**Input:** Selected contracts with risk parameters
- Contract ticker and type
- Max size and risk limit
- Thesis_side (UP/DOWN)

**Transformations:**
- Canonical mapping (thesis_side → contract → order):
  - UP thesis → YES contract → buy_yes (enter) / sell_yes (exit)
  - DOWN thesis → NO contract → buy_no (enter) / sell_no (exit)
- Order construction:
  - Order type (GTC, marketable limit)
  - Price clamping (10-75c canonical range)
  - Post-only policy (only for resting orders, aggressiveness=0)
  - Maker/taker fee calculation
- Duplicate detection:
  - 5-second duplicate order window
  - 60-second price repeat window
  - Open resting order guard (anti-stacking)
- Order routing:
  - Submit to Kalshi venue
  - Track order status (ACCEPTED, FILLED, REJECTED)
- Fill processing:
  - Update position cache with fill data
  - Validate fill side matches thesis_side invariant
  - Calculate slippage vs requested price

**Output:** Orders and fills
- `Order` objects with:
  - `order_id`
  - `client_order_id` (encodes intent metadata)
  - `ticker`
  - `side` (buy_yes, buy_no, sell_yes, sell_no)
  - `price_cents`
  - `count`
  - `status`
- `Fill` objects with:
  - `fill_id`
  - `order_id`
  - `ticker`
  - `side`
  - `price_cents`
  - `count`
  - `timestamp`

**Key Invariants:**
- Canonical mapping must be strictly followed (no semantic flips)
- Marketable orders (aggressiveness>0) must NEVER be post_only
- Anti-stacking guard: no new BUY when open resting order exists for same ticker+side+action
- Fill side must match thesis_side (invariant check)
- Position cache thesis_side is immutable (set from entry intent, never overwritten by REST sync)
- Price clamping to 10-75c canonical range
- No orphan orders (every order belongs to an episode)

---

### Stage 5: Bookkeeping (Positions & PnL)

**Input:** Fills from execution
- Fill data (price, count, side, timestamp)
- Order metadata (client_order_id with intent encoding)

**Transformations:**
- Position tracking:
  - Update net position per contract
  - Track entry price, exit price
  - Calculate unrealized PnL
- PnL calculation:
  - Realized PnL = (exit_price - entry_price) * count * direction
  - Include fees (maker/taker)
  - Edge attribution:
    - Strategy edge = entry_price - fair_value_estimate
    - Execution slippage = fair_value_estimate - actual_fill_price
- Balance reconciliation:
  - Verify bankroll changes match PnL
  - Check for negative balances
  - Validate leverage limits

**Output:** Position state and PnL
- `Position` objects with:
  - `ticker`
  - `thesis_side` (immutable)
  - `net_position` (contracts)
  - `entry_price_cents`
  - `exit_price_cents`
  - `unrealized_pnl_usd`
  - `realized_pnl_usd`
- `Episode` objects with:
  - `episode_id` (unique per trade cycle)
  - `signals` (raw data that triggered trade)
  - `selected_contract`
  - `orders` (all orders in episode)
  - `fills` (all fills in episode)
  - `realized_pnl_usd`
  - `edge_attribution` (strategy vs execution)

**Key Invariants:**
- Net position size per contract equals sum of filled orders
- PnL calculation matches fills × price deltas + fees
- No PnL without corresponding position changes
- No negative balances or leverage beyond risk settings
- Every fill belongs to an episode (orphan fill detection)
- Thesis_side invariant: never overwritten by REST sync

---

## Canonical Mapping Table (Kalshi Binary Options)

| Concept        | "Up" / Bullish Thesis                   | "Down" / Bearish Thesis                   |
|----------------|-----------------------------------------|-------------------------------------------|
| Thesis_side    | UP                                      | DOWN                                      |
| Contract       | YES (event happens)                     | NO (event does not happen)                |
| Position       | Long YES                                | Long NO                                   |
| Enter Order    | buy_yes                                 | buy_no                                    |
| Exit Order     | sell_yes (close long YES)               | sell_no (close long NO)                   |
| Hedge Order    | buy_no (hedge long YES)                 | buy_yes (hedge long NO)                   |

**Illegal Combinations (Forbidden by Invariants):**
- Bullish intent + buy_no
- Bearish intent + buy_yes
- Edge > 0 on UP + short YES
- Edge < 0 on DOWN + short NO

---

## Cross-Layer Invariant Summary

### Edge vs Model Probability
- Sign and magnitude of edge consistent with model probability
- Selected side matches edge sign
- Confidence monotonic with edge magnitude
- No trade when |edge| < threshold

### Regime Gating
- High volatility: position size shrunk or strategy disabled
- Low volume: max notional enforced, large orders forbidden
- Extreme velocity: contrarian entries forbidden
- Trade decisions include regime tag

### Spot→Strike Distance
- Normalized distance δ = (strike - spot) / spot
- Allowed δ window per strategy (e.g., |δ| < 0.1)
- No trades outside allowed δ window unless extreme edge
- Contract selection consistent with TA/intent mapping

### Canonical Mapping
- Strict adherence to mapping table
- No semantic flips between up/down, yes/no, long/short, buy/sell
- Intent → thesis_side → contract → order path validated

### Reconciliation
- Episode_id ties signals → contract → risk → order → fills → PnL
- Net position = sum of filled orders
- PnL = fills × price deltas + fees
- No orphan orders or fills
- No PnL without position changes
- Edge attribution decomposable (strategy vs execution)

### Model vs Execution
- Offline replay of historical data
- Compare "should have traded" vs "actually traded"
- Detect phantom trades (edge < threshold but trade occurred)
- Detect missed trades (edge > threshold but no trade with recorded reason)

---

## Error Taxonomy

When a trade is skipped or invariant violated, log explicit reason codes:

- `EDGE_TOO_SMALL`: |edge| below threshold
- `VOL_TOO_HIGH`: Volatility exceeds regime limit
- `VOL_TOO_LOW`: Volatility below minimum for strategy
- `VOLUME_ILLIQUID`: Volume below minimum threshold
- `VELOCITY_EXTREME`: Velocity exceeds regime limit
- `SPOT_STRIKE_DISTANCE_EXCEEDED`: δ outside allowed window
- `RISK_CAP_REACHED`: $1 fixed exposure cap hit
- `CONFIG_MISMATCH`: Test/production config divergence
- `THESIS_SIDE_INVARIANT_VIOLATION`: Fill side mismatch with thesis_side
- `CANONICAL_MAPPING_VIOLATION`: Illegal semantic combination
- `ORPHAN_FILL`: Fill without corresponding order
- `ORPHAN_ORDER`: Order without corresponding episode
- `PNL_MISMATCH`: PnL calculation inconsistent with fills
- `POSITION_MISMATCH`: Net position inconsistent with fills

---

## Production Configuration Alignment

### Canonical Price Range
- Entry/exit prices clamped to 10-75c
- Deep OTM thresholds: DEEP_OTM_CHEAP_CENTS = 10, DEEP_OTM_EXPENSIVE_CENTS = 75
- Crisis regime expands to 5-95c (multiplier 1.9)

### Risk Limits
- Fixed exposure cap: MERID_FIXED_EXPOSURE_CAP_USD = 1.00
- Per-trade max contracts: 1
- Daily loss limit: 20% of bankroll
- Drawdown halt: 20%, unwind: 25%

### Time Windows
- Duplicate order window: 5 seconds
- Price repeat window: 60 seconds
- 15m trading cycle: 5s cadence

### Assets
- All 5 crypto assets mandatory: BTC, ETH, SOL, XRP, DOGE
- No asset skipping or disabling

---

## References

- FMSB Algorithmic Trading in Fixed Income: https://fmsb.com/wp-content/uploads/2020/06/algorithmic-trading-in-ficc-markets-statement-of-good-practice-for-ficc-market-participants.pdf
- FIA Algorithmic Due Diligence Guide: https://www.fia.org/sites/default/files/2019-05/FIA-Algorithmic-Due-Diligence-Guide--Template-for-Firms-FINAL.pdf
- KPMG Algorithmic Trading Compliance: https://assets.kpmg.com/content/dam/kpmgsites/uk/pdf/2019/12/algorithmic-trading.pdf
- FCA Algorithmic Trading Review: http://www.fca.org.uk/publication/multi-firm-reviews/algorithmic-trading-compliance-wholesale-markets.pdf

# Kalshi 15m Trading Stack - Single Owner Per Concept

This document defines the SINGLE OWNER for each core concept in the Kalshi 15m trading stack.
All other modules should consume these concepts from their designated owners only.

## Purpose

Eliminate "conflicting systems" where multiple modules silently re-implement the same concept.
This ensures:
- Single source of truth for each concept
- Predictable behavior
- Easy debugging and maintenance
- No drift between duplicate implementations

## Concept Ownership

### 1. Market Data Freshness

**Owner:** `KalshiMarketStateStore` (`merid/event_venues/kalshi/market_state.py`)

**Responsibilities:**
- Track last update timestamps for each ticker
- Compute freshness metrics (staleness vs fresh)
- Expose `md_fresh[ticker]` boolean flag
- Enforce staleness thresholds (from `threshold_config.py`)

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

store = get_kalshi_market_state_store()
state = store._states.get(ticker)
is_fresh = (time.time() - state.last_book_update_ts) < MAX_BOOK_STALENESS_MS / 1000
```

**What NOT to do:**
- Do not recompute freshness from timestamps in agents
- Do not implement separate staleness checks in order router
- Do not duplicate freshness logic in health checkers

---

### 2. Liquidity / Spreads / Extreme Prices

**Owner:** `LocalOrderbook` + `KalshiMarketStateStore` (`merid/event_venues/kalshi/orderbook.py`, `market_state.py`)

**Responsibilities:**
- Compute bid-ask spreads using Kalshi YES/NO duality
- Detect extreme YES-equivalent prices (illiquidity signal)
- Track depth at top of book
- Enforce liquidity thresholds (from `threshold_config.py`)
- Expose `liquidity_state[ticker]` with spreads/flags

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

store = get_kalshi_market_state_store()
state = store._states.get(ticker)
spread_cents = state.spread_cents
depth_10c = state.depth_10c
extreme_price = state.extreme_price_flag
```

**What NOT to do:**
- Do not recompute spreads in agents
- Do not implement separate extreme price detection
- Do not duplicate liquidity checks in risk modules

---

### 3. Risk & Bankroll

**Owner:** `BankrollServiceV2` + PnL snapshot (`merid/event_venues/kalshi/bankroll_service_v2.py`)

**Responsibilities:**
- Fetch equity/cash from Kalshi portfolio endpoints
- Compute PnL metrics
- Track bankroll state (fresh/stale)
- Expose `equity_cents`, `available_cash_cents`, `state`

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service

bankroll = await get_bankroll_service()
summary = await bankroll.get_summary(caller_module="agent")
equity = summary.equity_cents
is_fresh = summary.state != "STALE"
```

**What NOT to do:**
- Do not call Kalshi portfolio endpoints directly from agents
- Do not recompute equity from position snapshots
- Do not implement separate balance tracking

---

### 4. Duality Validation

**Owner:** `DualityValidator` (`merid/event_venues/kalshi/duality_validator.py`)

**Responsibilities:**
- Enforce YES + NO = 100c invariant
- Track violation counts per ticker
- Manage quarantine mode with sequence alignment
- Expose `should_pause_trading(ticker)` boolean
- Raise P1 alarms on critical violations

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.duality_validator import get_duality_validator

validator = get_duality_validator()
result = validator.check_yes_no_duality(yes_bid, no_bid, ticker=ticker)
should_pause = validator.should_pause_trading(ticker)
alarms = validator.get_alarms()
```

**What NOT to do:**
- Do not implement separate duality checks in orderbook
- Do not re-implement quarantine logic
- Do not track violation counts separately

---

### 5. Trading Enablement

**Owner:** `TradingPolicy` (`merid/event_venues/kalshi/trading_policy.py`)

**Responsibilities:**
- Evaluate severity signals from all subsystems
- Determine trading mode (HALT/EXITS_ONLY/NORMAL)
- Expose single `TradingMode` decision
- Drive agent grid and order router behavior

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.trading_policy import evaluate_trading_mode

result = evaluate_trading_mode(
    ws_alarms=ws_alarms,
    duality_alarms=duality_alarms,
    bankroll_alarms=bankroll_alarms,
)
mode = result.mode  # TradingMode.HALT, EXITS_ONLY, or NORMAL
allows_entries = mode.allows_new_entries()
```

**What NOT to do:**
- Do not make trading decisions based on scattered flags
- Do not implement separate enablement logic in agents
- Do not bypass the policy for any orders

---

### 6. Asset / Ticker List

**Owner:** `kalshi_crypto_15m_profile.py` (`merid/event_venues/kalshi/kalshi_crypto_15m_profile.py`)

**Responsibilities:**
- Define canonical list of active tickers
- Provide asset metadata (friendly names, series codes)
- Expose convenience functions for ticker/asset resolution

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.kalshi_crypto_15m_profile import (
    get_all_active_tickers,
    get_friendly_name,
    is_active_ticker,
)

tickers = get_all_active_tickers()  # ["KXBTC-15M", "KXETH-15M", ...]
name = get_friendly_name("KXBTC-15M")  # "Bitcoin 15m"
active = is_active_ticker("KXBTC-15M")  # True
```

**What NOT to do:**
- Do not hardcode ticker lists in WS bridge, agent grid, or other modules
- Do not implement separate asset resolution logic
- Do not duplicate series code definitions

---

### 7. Threshold Configuration

**Owner:** `ThresholdConfig` (`merid/event_venues/kalshi/threshold_config.py`)

**Responsibilities:**
- Load threshold values from `kalshi_15m_thresholds.yaml`
- Provide per-asset threshold accessors
- Support runtime reload for configuration updates

**Consumer Pattern:**
```python
from merid.event_venues.kalshi.threshold_config import get_threshold_config

config = get_threshold_config()
spread_thresh = config.get_spread_threshold("BTC")
price_thresh = config.get_extreme_price_threshold("BTC")
liquidity_thresh = config.get_liquidity_threshold("BTC")
```

**What NOT to do:**
- Do not hardcode threshold literals in code
- Do not implement separate configuration systems
- Do not duplicate threshold values across modules

---

## Migration Checklist

To ensure compliance with single ownership:

- [x] **Freshness:** All freshness checks use `KalshiMarketStateStore` timestamps
- [x] **Liquidity:** All spread/depth checks use `LocalOrderbook` + `KalshiMarketStateStore`
- [x] **Risk:** All bankroll queries use `BankrollServiceV2`
- [x] **Duality:** All duality checks use `DualityValidator`
- [x] **Trading:** All trading decisions use `TradingPolicy`
- [x] **Assets:** All ticker lists use `kalshi_crypto_15m_profile.py`
- [x] **Thresholds:** All threshold values use `ThresholdConfig`

## Violation Detection

If you see:
- Duplicate freshness computation in agents → Violation
- Separate spread calculation in risk module → Violation
- Direct Kalshi portfolio calls from trading agent → Violation
- Hardcoded ticker lists in WS bridge → Violation
- Magic numbers for thresholds in orderbook → Violation

These should be refactored to use the designated owner.

## Benefits

1. **Predictability:** Changes to a concept only need to be made in one place
2. **Debugging:** Issues can be traced to a single source
3. **Testing:** Only need to test the owner, not all consumers
4. **Configuration:** Thresholds and asset lists are centralized
5. **Alignment:** Easier to align with Kalshi API semantics

## References

- Kalshi Orderbook API: https://docs.kalshi.com/getting_started/orderbook_responses
- Kalshi Portfolio API: https://help.kalshi.com/en/articles/13823854-kalshi-api
- YES/NO Duality: YES_price + NO_price = 100 cents

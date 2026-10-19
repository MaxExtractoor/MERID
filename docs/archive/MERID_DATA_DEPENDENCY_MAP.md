# MERID Production Stack Data Dependency Map

**Purpose**: End-to-end mapping of data and config flow from Kalshi and profile YAML into signals, candidates, orders, and exits. This document identifies high-leverage bottlenecks where bugs have the most impact.

**Last Updated**: 2026-07-24

---

## Overview

The MERID 15m Kalshi crypto trading system follows a strict data flow pipeline:

```
External Inputs → Internal Transformations → Outputs
```

**Single Source of Truth (SSOT)**: `config/profiles/kalshi_crypto_15m_v2.yaml`

---

## 1. External Inputs

### 1.1 Kalshi Orderbook Snapshots
- **Source**: Kalshi WebSocket/REST API
- **Data**: YES/NO prices, liquidity (depth_10c_yes, depth_10c_no), spread
- **Frequency**: Real-time (WebSocket) + polling (REST)
- **Consumers**: 
  - `merid/prediction/agent_grid_15m.py` (signal generation)
  - `merid/event_venues/kalshi/order_router.py` (order routing)
  - `merid/loop_15m.py` (candidate builder)
- **High-Leverage Impact**: Wrong prices → wrong signals → wrong side → losses

### 1.2 Kalshi Market Metadata
- **Source**: Kalshi Market Catalog API
- **Data**: Strike price, target price, asset symbol, expiry timestamp, market_id
- **Frequency**: Every 60 seconds (catalog refresh)
- **Consumers**:
  - `merid/prediction/agent_grid_15m.py` (market selection)
  - `merid/loop_15m.py` (candidate filtering)
- **High-Leverage Impact**: Wrong market → wrong asset → position limits violated

### 1.3 Profile YAML (SSOT)
- **Source**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Data**: 
  - `signal_mode` (authoritative: "momentum_fvg")
  - `enabled_features` (e.g., ["momentum_fvg"])
  - `disabled_features` (e.g., ["panic_fade", "volatility_reversion"])
  - `price_range` (min_entry_price_cents: 10, max_entry_price_cents: 75)
  - `strict_mode` (boolean)
  - `exit_policies` (TP, SL, trailing, time-based)
  - Per-asset configs (BTC/ETH/SOL/XRP/DOGE)
- **Frequency**: Loaded at startup, never changes during runtime
- **Consumers**:
  - `merid/risk/profiles/crypto_15m_profile.py` (profile adapter)
  - `merid/prediction/agent_grid_15m.py` (signal mode gating)
  - `merid/event_venues/kalshi/order_router.py` (risk limits)
- **High-Leverage Impact**: SSOT drift → wrong strategy → silent losses (e.g., panic fade re-enabled)

### 1.4 Agent Grid YAML
- **Source**: `config/kalshi_agent_grid.yaml`
- **Data**: Per-agent configuration (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- **Frequency**: Loaded at startup
- **Consumers**:
  - `merid/prediction/agent_grid_15m.py` (agent initialization)
- **SSOT Constraint**: Must align with profile YAML (signal_mode, enabled_features)
- **High-Leverage Impact**: Grid drift → agent uses wrong strategy → inconsistent behavior

---

## 2. Internal Transformations

### 2.1 Signal Generation
- **Component**: `merid/prediction/agent_grid_15m.py` → `_generate_signal()`
- **Input**: 
  - Kalshi orderbook (prices, liquidity)
  - Profile YAML (signal_mode, thresholds)
  - Spot price (from external oracle)
- **Transform**:
  - `momentum_fvg`: Velocity, MACD, RSI, OBI, FVG → signal_side, signal_action
  - `price_based`: Price thresholds → signal_side, signal_action
  - `hybrid`: price_based (panic fade) + momentum_fvg → signal_side, signal_action
  - `volatility_reversion`: Statistical extremes → signal_side, signal_action
- **Output**: Trading signal dict with:
  - `signal_side` (YES/NO)
  - `signal_action` (BUY/SELL)
  - `price_cents`
  - `rationale`
  - `strategy` (momentum_fvg, panic_fade, etc.)
- **SSOT Guard**: 
  - `panic_fade_enabled=False` when `signal_mode == "momentum_fvg"`
  - Logs `[SSOT-INVARIANT]` when forcing profile behavior
- **High-Leverage Impact**: Wrong signal → wrong thesis → wrong side → losses

### 2.2 Intent Mapping
- **Component**: `merid/prediction/agent_grid_15m.py` → signal dict construction
- **Input**: 
  - Trading signal (signal_side, signal_action, price_cents)
  - Profile YAML (price_range, strict_mode)
- **Transform**:
  - `thesis_side`: Derived from signal_side (immutable per position)
  - `exposure_direction`: LONG (YES) or SHORT (NO)
  - `price_side_alignment`: YES uses YES price, NO uses NO price
- **Output**: Signal dict with:
  - `thesis_side`
  - `exposure_direction`
  - `price_cents` (correctly aligned to side)
- **Invariant Check**: `[PRICE-SIDE-CHECK]` logs verify price-side alignment
- **High-Leverage Impact**: Wrong intent → wrong order → Kalshi rejection or wrong fill

### 2.3 Candidate Builder
- **Component**: `merid/loop_15m.py` → candidate construction
- **Input**:
  - Signal dict (thesis_side, price_cents, etc.)
  - Profile YAML (price_range, strict_mode)
  - Position cache (current exposure)
- **Transform**:
  - Side selection: `candidate.side = signal.thesis_side`
  - Price selection: `candidate.price_cents = signal.price_cents`
  - Strict mode gating: Enforce 10-75c canonical range
  - Position limits: Check exposure caps ($1 fixed model)
- **Output**: OrderIntent with:
  - `ticker`, `side`, `action`, `price_cents`
  - `aggressiveness`, `post_only`, `order_type`
- **Invariant Check**: `[SIDE-PRESERVATION-CHECK]` logs verify signal→candidate side consistency
- **High-Leverage Impact**: Wrong candidate → wrong order → losses

### 2.4 Router
- **Component**: `merid/event_venues/kalshi/order_router.py` → `route_order_async()`
- **Input**:
  - OrderIntent (ticker, side, action, price_cents)
  - Profile YAML (risk limits, price_range)
  - Position cache (current exposure)
- **Transform**:
  - Side/price/thesis reconciliation: Validate intent consistency
  - Exit vs entry invariants: Check position state
  - Risk enforcement: Apply $1 fixed exposure cap
  - Duplicate detection: 5-second window
  - Open order guard: Prevent stacking
- **Output**: VenueOrder submitted to Kalshi API
- **Invariant Check**: `[EXIT-INVARIANT]` logs verify exit logic
- **High-Leverage Impact**: Router bypass → invalid orders → Kalshi rejection or overfill

### 2.5 Position Cache and Exit Stack
- **Component**: `merid/event_venues/kalshi/position_cache.py`
- **Input**:
  - Kalshi fills (WebSocket/REST)
  - Position state (current holdings)
- **Transform**:
  - Entry/exit reconciliation: Match fills to positions
  - `thesis_side` preservation: Never overwritten by REST sync
  - Close-only deltas: Net exposure calculation
- **Output**: CachedPosition with:
  - `thesis_side` (immutable)
  - `side` (exchange-reported, may differ)
  - `quantity`, `avg_price`
- **Invariant Check**: Thesis side invariant alarms on mismatches
- **High-Leverage Impact**: Wrong position state → wrong exits → overfill or underfill

---

## 3. Outputs

### 3.1 Orders to Kalshi
- **Component**: `merid/event_venues/kalshi/order_router.py` → Kalshi REST API
- **Data**: 
  - `ticker`, `side`, `action`, `price_cents`, `count`
  - `order_type` (limit), `post_only` (False for marketable)
- **Frequency**: Per signal (5-second cadence)
- **Monitoring**: Order status (ACCEPTED, FILLED, REJECTED)
- **High-Leverage Impact**: Wrong order → capital loss or opportunity cost

### 3.2 Logs
- **Component**: All components via `utils.logger`
- **Key Log Types**:
  - `[SIGNAL-RAW-INDICATORS]`: Raw signal inputs (velocity, RSI, MACD, etc.)
  - `[SIDE-PRESERVATION-CHECK]`: Signal→candidate side consistency
  - `[PRICE-SIDE-CHECK]`: Price-side alignment verification
  - `[SSOT-INVARIANT]`: Profile SSOT enforcement (panic fade disabled, etc.)
  - `[EXIT-INVARIANT]`: Exit logic verification
  - `[INTENT-EXPOSURE-MISMATCH]`: Intent vs exposure divergence
  - `[THESIS-SIDE-ALARM]`: Thesis side invariant violations
- **Frequency**: Real-time
- **Monitoring**: Anomaly detection via log scanning
- **High-Leverage Impact**: Silent log failures → undetected bugs → losses

---

## 4. High-Leverage Bottlenecks

### 4.1 Profile SSOT Drift
- **Risk**: Agent grid or code overrides profile settings
- **Impact**: Wrong strategy silently enabled (e.g., panic fade)
- **Mitigation**: 
  - Runtime SSOT guards in `agent_grid_15m.py`
  - Test invariants in `test_config_ssot_invariants.py`
  - Log scanning for `[SSOT-INVARIANT]` warnings

### 4.2 Price-Side Misalignment
- **Risk**: YES order uses NO price or vice versa
- **Impact**: Wrong entry price → poor risk/reward
- **Mitigation**:
  - `[PRICE-SIDE-CHECK]` logs
  - Intent mapping invariant checks
  - Anomaly monitor for price_side_mismatches

### 4.3 Signal-Intent Desynchronization
- **Risk**: Signal side ≠ thesis side ≠ candidate side ≠ order side
- **Impact**: Wrong side → opposite exposure → losses
- **Mitigation**:
  - `[SIDE-PRESERVATION-CHECK]` logs
  - Anomaly monitor for signal_intent_sync_issues
  - Thesis side invariant in position cache

### 4.4 Exit Logic Failures
- **Risk**: Exits don't reconcile ledger state
- **Impact**: Position state corruption → overfill or underfill
- **Mitigation**:
  - `[EXIT-INVARIANT]` logs
  - Thesis side preservation in position cache
  - Anomaly monitor for exit reconciliation failures

### 4.5 Stale Data
- **Risk**: Old orderbook or market metadata used
- **Impact**: Wrong prices → wrong signals → wrong orders
- **Mitigation**:
  - Catalog staleness checks
  - Data freshness monitoring in anomaly scanner
  - Latency anomaly detection

---

## 5. Dependency Graph

```
Kalshi Orderbook (prices, liquidity)
    ↓
Signal Generation (momentum_fvg)
    ↓
Intent Mapping (thesis_side, price_side_alignment)
    ↓
Candidate Builder (side selection, strict mode)
    ↓
Router (risk enforcement, side/price reconciliation)
    ↓
Position Cache (thesis_side preservation, exit reconciliation)
    ↓
Orders to Kalshi
```

**Profile YAML** feeds into:
- Signal Generation (signal_mode gating)
- Intent Mapping (price_range, strict_mode)
- Candidate Builder (position limits)
- Router (risk limits)

**Agent Grid YAML** feeds into:
- Signal Generation (per-agent config)
- Must align with Profile YAML (SSOT constraint)

---

## 6. Change Impact Analysis

When changing a component, trace its impact through the dependency graph:

- **Profile YAML change**: Propagates to signal generation, intent mapping, candidate builder, router
- **Agent Grid YAML change**: Propagates to signal generation (per-agent)
- **Signal generation change**: Propagates to intent mapping, candidate builder, router, orders
- **Router change**: Propagates to orders, position cache
- **Position cache change**: Propagates to exit logic, ledger state

**Rule**: Any change to SSOT fields (signal_mode, enabled_features, price_range) requires:
1. Profile YAML update
2. Agent grid YAML alignment
3. Test invariant update
4. Runtime guard update (if needed)
5. Log monitoring update (if new invariants)

---

## 7. Monitoring and Alerting

### 7.1 Real-Time Anomaly Detection
- **Tool**: `scripts/scan_bias_and_exit_health.py` (to be extended)
- **Checks**:
  - PRICE-SIDE consistency (selected_side == order.side)
  - Signal-intent synchronization (signal_side == thesis_side == candidate.side == order.side)
  - Runtime SSOT checks ([SSOT-INVARIANT] logs)
  - Exit reconciliation (position state consistency)
  - Data freshness (staleness anomalies)

### 7.2 Thresholds
- `price_side_mismatches > 0` (zero tolerance)
- `signal_intent_sync_issues > 0` (zero tolerance)
- `ssot_invariant_fires > 0` (investigate if frequent)
- `exit_reconciliation_failures > 0` (zero tolerance)
- `data_staleness_seconds > 60` (catalog staleness)

### 7.3 Alert Categories
- **Point anomalies**: Individual side/price mismatches
- **Contextual anomalies**: Windows with NO signals but YES orders
- **Pattern anomalies**: Clusters of mismatches around specific assets

---

## 8. Future Enhancements

- **Automated dependency mapping script**: List upstream/downstream relationships per component
- **SSOT schema validation**: JSON schema for profile YAML with enabled/disabled features
- **Profile version gating**: Runtime guards key off `profile_version` not just `signal_mode`
- **Invariant testing framework**: Randomized scenario generators to stress invariants
- **Latency monitoring**: Detect gaps in signal updates or stale orderbook snapshots

# Upstream/Downstream Alignment Audit Checklist

**Purpose:** Explicitly verify end-to-end alignment with what Kalshi expects for responsible trading.

**Scope:** kalshi_crypto_15m_v2 profile, 15m crypto prediction markets

---

## Upstream: Profile & Configuration

### ✅ Profile Defines Risk Parameters

- [x] **Capital allocation** in percentages relative to bankroll
  - `capital_usd` can be 0.0 (derive from live bankroll)
  - `profile_capital_usd` as fallback
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

- [x] **Daily loss limits** as percentage of capital
  - `max_daily_loss_pct` (e.g., 0.005 = 0.5%)
  - Computed as `max_daily_loss_usd = effective_capital * max_daily_loss_pct`
  - Location: `kalshi_crypto_15m_risk_envelope.py`

- [x] **Per-asset caps** in USD
  - `asset_max_notional_usd` per asset
  - Derived from profile capital allocation
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

- [x] **Drawdown thresholds** as percentages
  - `drawdown_halt_pct`, `drawdown_unwind_pct`
  - Used for dynamic position sizing
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

### ✅ Profile Defines Strategy Parameters

- [x] **Edge thresholds** per phase
  - `min_edge_early`, `min_edge_mid`, `min_edge_late`, `min_edge_terminal`
  - Controls minimum edge required to trade
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

- [x] **Distance filters**
  - `max_distance_pct`: maximum spot-to-strike distance
  - `max_z_distance`: maximum sigma-based distance
  - Location: `config/profiles/kalshi_crypto_15m.yaml` or `kalshi_distance_config.py`

- [x] **Kelly parameters**
  - `kelly_hard_cap`: maximum Kelly fraction
  - `kelly_min_edge_pct`, `kelly_max_edge_pct`: edge bounds
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

- [x] **Guardrails**
  - Sentiment isolation: `enable_sentiment_execution: false`
  - Liquidity filters
  - Skew filters
  - Location: `config/profiles/kalshi_crypto_15m.yaml`

---

## Midstream: Risk Management & Enforcement

### ✅ Risk Envelope Computation

- [x] **Risk envelope loads from profile YAML**
  - `get_kalshi_crypto_15m_risk_envelope()` reads profile
  - Computes derived values (max_daily_loss_usd, etc.)
  - Location: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

- [x] **Envelope matches profile exactly**
  - All profile parameters reflected in envelope
  - No hardcoded overrides
  - Validated by `validate_profile_envelope_capability.py`

### ✅ RiskController Integration

- [x] **RiskController uses profile daily loss limit**
  - `get_profile_daily_loss_limit()` fetches from envelope
  - RiskController `__post_init__` uses profile limit for kalshi_crypto_15m_v2
  - Location: `merid/risk/kill_switches.py`

- [x] **Daily PnL tracking from fills_ledger**
  - `can_trade()` pulls fresh daily PnL from fills_ledger
  - Canonical source for realized performance
  - Location: `merid/risk/kill_switches.py`

- [x] **Auto-reset at UTC day rollover**
  - `_daily_pnl_reset_date` compared to current date
  - Resets daily PnL to 0 on new day
  - Location: `merid/risk/kill_switches.py`

### ✅ Kill-Switch Enforcement

- [x] **Kill-switch triggers on daily loss exceeded**
  - `daily_pnl < -max_daily_loss_usd` → trigger
  - Sets `_global_kill = True`
  - Location: `merid/risk/kill_switches.py`

- [x] **Kill-switch checked before trades**
  - Layer 0 in `check_execution_guards()`
  - Returns `allowed=False` if kill-switch active
  - Location: `merid/prediction/trading_agent.py`

- [x] **MeridLoop logs kill-switch status**
  - Logs warning at start of each tick if active
  - Distinguishes "no trades due to freeze" from connectivity issues
  - Location: `merid/loop.py`

### ✅ Watchdog Enforcement

- [x] **Error budget enforcement**
  - Tracks tick errors in 5-minute window
  - Halts if >5 errors in window
  - Location: `merid/loop.py`

- [x] **Stall detection**
  - Detects if no successful tick in 60 seconds
  - Logs stall warning
  - Location: `merid/loop.py`

---

## Downstream: Trading Execution & Observability

### ✅ TradingAgent Uses Profile-Driven Filters

- [x] **Distance caps from profile/config**
  - `check_execution_guards()` uses `max_delta_pct` and `max_z_distance`
  - Fetched from `kalshi_distance_config.py`
  - Location: `merid/prediction/trading_agent.py`

- [x] **Edge floors from profile**
  - `check_execution_guards()` uses `get_min_edge()`
  - Respects phase-specific thresholds
  - Location: `merid/prediction/trading_agent.py`

- [x] **Asset/timeframe whitelist**
  - `ALLOWED_ASSETS`: BTC, ETH, SOL, XRP, DOGE
  - `EXECUTION_TIMEFRAMES`: 15m only
  - Location: `merid/prediction/trading_agent.py`

### ✅ Order Router Respects Kalshi Caps

- [x] **Per-order caps**
  - `max_single_order_notional_usd` from profile
  - Enforced in order sizing
  - Location: Kalshi order router

- [x] **Total caps**
  - `max_total_notional_usd` from profile
  - Enforced in position sizing
  - Location: Kalshi order router

- [x] **Series ticker wiring**
  - Uses 15M series tickers (KXBTC15M, etc.)
  - Correctly resolves 15m markets
  - Location: `merid/event_venues/kalshi/market_selector.py`

### ✅ Forensics Logging

- [x] **Every trade decision logged**
  - `log_15m_forensics()` called for TRADE and NO_TRADE
  - Includes asset, spot, strike, distance, edge, Kelly, notional
  - Location: `merid/prediction/trading_agent.py`

- [x] **Decision outcome tracked**
  - `decision="TRADE"` or `decision="NO_TRADE"`
  - `skip_reason` for guard rejections (edge_too_low, distance_too_far, kill_switch)
  - Location: `merid/prediction/trading_agent.py`

- [x] **Forensics analysis script**
  - Parses logs and computes bucketed EV/win rate
  - Counts guard reasons per asset
  - Location: `scripts/analyze_15m_forensics.py`

### ✅ PnL Logging

- [x] **Fills ledger tracks all fills**
  - Canonical source for realized PnL
  - Per-fill and daily PnL
  - Location: `merid/event_venues/kalshi/fills_ledger.py`

- [x] **Performance dashboard**
  - Generates markdown report per asset
  - Shows best/worst buckets, guard reasons
  - Location: `scripts/report_15m_performance.py`

---

## Startup & Validation

### ✅ Preflight Gate

- [x] **Profile → Envelope → Capability validation**
  - `validate_profile_envelope_chain()` runs at startup
  - Validates YAML consistency across layers
  - Aborts startup on failure
  - Location: `merid/startup_validations.py`

### ✅ Profile Diff Snapshot

- [x] **Profile signature computed at startup**
  - `_compute_profile_signature()` captures critical parameters
  - Compared with previous snapshot
  - Logs parameter changes
  - Location: `merid/loop.py`

- [x] **Snapshot persisted**
  - Saved to `data/profile_snapshots/last.json`
  - Timestamped snapshots for audit trail
  - Location: `merid/loop.py`

---

## Calibration & Iteration

### ✅ Calibration Playbook

- [x] **Concrete tuning rules documented**
  - Rules for negative EV buckets, positive EV buckets, guard reasons
  - Phase-specific and asset-specific adjustments
  - Location: `docs/15m_calibration_playbook.md`

### ✅ Parameter Change Protocol

- [x] **Operational protocol documented**
  - Step-by-step procedure for making changes
  - Validation, deployment, evaluation, rollback
  - Location: `docs/parameter_change_protocol.md`

### ✅ Regression Tests

- [x] **Minimal automated regression suite**
  - Test 1: BTC 15m trade passes all guards
  - Test 2: DOGE 15m trade blocked by distance
  - Test 3: Kill-switch blocks trades
  - Location: `tests/test_15m_regression.py`

---

## Monitoring & Observability

### ✅ Lightweight Monitoring Hooks

- [x] **Per-tick metrics**
  - tick_index, kill_switch_active, errors_last_5m
  - Logged at start of each tick
  - Location: `merid/loop.py`

- [x] **Periodic aggregate stats**
  - Every 60 ticks: daily_pnl, total_fills, trades_since_start
  - Provides high-level health signal
  - Location: `merid/loop.py`

---

## Alignment Summary

### ✅ Upstream Alignment

- Profile defines all risk parameters as percentages/fractions relative to bankroll
- Profile defines all strategy parameters (edge, distance, Kelly)
- Risk envelope computes derived values from profile
- No hardcoded overrides; single source of truth

### ✅ Midstream Alignment

- RiskController uses profile daily loss limit
- Daily PnL tracked from canonical fills_ledger
- Kill-switch enforces daily loss budget
- Watchdog enforces error budget and stall detection
- Auto-reset at UTC day rollover

### ✅ Downstream Alignment

- TradingAgent uses profile-driven filters (distance, edge)
- Order router respects Kalshi's per-order and total caps
- Series ticker wiring correct for 15m markets
- Forensics logging provides full traceability per decision
- PnL logging provides realized performance data

### ✅ Operational Alignment

- Preflight gate validates configuration at startup
- Profile diff snapshot detects configuration drift
- Calibration playbook provides data-driven tuning rules
- Parameter change protocol ensures repeatable iterations
- Regression tests protect pipeline from regressions
- Monitoring hooks provide visibility into system health

---

## Conclusion

**All upstream, midstream, and downstream components are aligned with what Kalshi expects for responsible trading:**

- Risk budget defined as percentage of bankroll
- Dynamic enforcement based on realized performance
- Automatic stop when limits exceeded
- Full traceability per trade/decision
- Repeatable, documented iteration process

The 15m crypto trading system is now:
- **Kalshi-aligned:** Follows responsible trading guidelines
- **Dynamic:** Profile-driven, adapts to bankroll and market conditions
- **Observable:** Full forensics and PnL logging
- **Robust:** Kill-switch, watchdog, regression tests
- **Iterative:** Calibration playbook and parameter change protocol

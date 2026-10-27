# Kalshi Crypto 15m Risk Model

## Overview

This document describes the config-only risk model for BTC/ETH/SOL/XRP/DOGE 15m trading on Kalshi. This profile replaces all balance-derived risk calculations for this scope, ensuring that trading behavior is identical regardless of account balance.

**Activation:** Set `MERID_PROFILE=kalshi_crypto_15m_v2` (or equivalent flag)

**Scope:** BTC/ETH/SOL/XRP/DOGE 15m prediction markets on Kalshi only. Other strategies (sports, paper, generic prediction, other timeframes) continue to use existing risk configurations.

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         config/profiles/kalshi_crypto_15m.yaml          │
│                         (Single Source of Truth)                         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 │ ProfileLoader.load_profile()
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Crypto15mProfileAdapter                           │
│                         (Maps profile → internal configs)                │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                ▼                ▼                ▼
┌──────────────────────┐ ┌──────────────────┐ ┌──────────────────────┐
│ KalshiRiskConfig     │ │ CycleSizingCap    │ │ Per-Agent Configs     │
│                      │ │                  │ │                      │
│ - max_single_order   │ │ - max_cycle_risk │ │ - max_notional       │
│ - max_total_notional │ │ - per_asset_caps │ │ - max_orders/window  │
│ - category_limits    │ │                  │ │ - position limits    │
│ - kelly_hard_cap     │ │                  │ │                      │
└──────────┬───────────┘ └────────┬─────────┘ └──────────┬───────────┘
           │                       │                       │
           │                       │                       │
           ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Risk Manager / Execution Gate                     │
│                         (Enforces caps at trade time)                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                ▼                ▼                ▼
┌──────────────────────┐ ┌──────────────────┐ ┌──────────────────────┐
│ BTC_15M Agent        │ │ ETH_15M Agent    │ │ SOL/XRP/DOGE Agents  │
│                      │ │                  │ │                      │
│ - Reads from profile │ │ - Reads from     │ │ - Reads from profile │
│ - Enforces per-agent │ │   profile        │ │ - Enforces per-agent │
│   limits            │ │ - Enforces       │ │   limits             │
└──────────┬───────────┘ │   per-agent      │ └──────────┬───────────┘
           │             │   limits         │            │
           │             └──────────────────┘            │
           │                                              │
           └──────────────────────┬───────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kalshi Venue (Order Execution)                    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Configuration Knobs (20-30 total)

### Global Capital and Cycle Risk (3 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `capital_usd` | 10000.0 | Logical capital for this strategy (NOT live bankroll) | CycleSizingCap, Kelly sizing |
| `max_cycle_risk_pct` | 0.02 | Maximum risk per cycle as percentage of capital (2%) | CycleSizingCap |
| `max_cycle_risk_usd` | 0.0 | Optional absolute cap on cycle risk (0 = use percentage) | CycleSizingCap |

### Venue-Level Caps (5 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `venue.max_single_order_usd` | 2500.0 | Max notional per single order | KalshiRiskConfig |
| `venue.max_total_notional_usd` | 7500.0 | Max total notional across all 15m crypto (3 concurrent trades) | KalshiRiskConfig |
| `venue.max_category_notional_usd` | 5000.0 | Max notional for "crypto" category | CategoryLimit |
| `venue.max_orders_per_minute` | 30 | Rate limit (orders per minute) | KalshiRiskConfig |
| `venue.max_orders_per_hour` | 300 | Rate limit (orders per hour) | KalshiRiskConfig |

### Per-Asset Caps (5 assets × 2 knobs = 10 knobs)

| Knob | BTC | ETH | SOL | XRP | DOGE | Description | Used In |
|------|-----|-----|-----|-----|------|-------------|---------|
| `assets.X.max_notional_usd` | 3000.0 | 2000.0 | 1500.0 | 1500.0 | 1000.0 | Max notional per asset | Per-asset risk checks |
| `assets.X.max_contracts` | 100 | 100 | 100 | 100 | 100 | Max contracts per asset | Per-asset risk checks |

### Per-Agent Caps (4 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `agent_defaults.max_notional_usd` | 1000.0 | Max notional per agent | Agent risk checks |
| `agent_defaults.max_orders_per_window` | 3 | Max orders per trading window | Agent rate limiting |
| `agent_defaults.max_yes_position` | 3 | Max YES contracts per side | Agent position limits |

### Market Data Staleness (TODO: Document in profile)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `max_md_staleness_sec` | 15.0 (profile) / 120.0 (runtime override) | Maximum allowed market data staleness in seconds | Signal gate, health checks |

**IMPORTANT:** There is a temporary runtime override in `agent_grid_15m.py` that sets `max_md_staleness_sec = 120.0` instead of using the profile value of 15.0s. This was added to match the lag gate threshold. TODO: Remove this override and use the profile value consistently.

### Hardcoded Risk Values (TODO: Make configurable)

| Value | Current Hardcoded Value | Location | TODO |
|-------|------------------------|----------|------|
| `max_cycle_risk_pct` | 0.02 (2%) | `kalshi_crypto_15m.yaml` line 74 | Already in profile - OK |
| `grace_window_seconds` | 20s | `agent_grid_15m.py` lines 9264, 9472 | Move to profile config |

### Entry Window (2 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `agent_defaults.minutes_before_expiry` | 30 | Minutes before expiry to start trading | Agent entry logic |
| `agent_defaults.cutoff_minutes_before_expiry` | 2 | Stop trading 2 minutes before expiry | Agent entry logic |

### Edge Thresholds (4 knobs per asset, or reference to matrix)

| Knob | BTC | ETH | SOL | XRP | DOGE | Description | Used In |
|------|-----|-----|-----|-----|------|-------------|---------|
| `assets.X.min_edge_early` | 0.020 | 0.020 | 0.025 | 0.025 | 0.030 | Minimum edge early in window | Strategy thresholds |
| `assets.X.min_edge_mid` | 0.020 | 0.020 | 0.025 | 0.025 | 0.030 | Minimum edge mid window | Strategy thresholds |
| `assets.X.min_edge_late` | 0.020 | 0.020 | 0.025 | 0.025 | 0.030 | Minimum edge late window | Strategy thresholds |
| `assets.X.min_edge_terminal` | 0.025 | 0.025 | 0.030 | 0.030 | 0.035 | Minimum edge near expiry | Strategy thresholds |

**Note:** These override `crypto_threshold_matrix.yaml` for this profile. If not specified, the profile can reference the matrix instead.

### Confidence Bands (5 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `confidence.use_crypto_threshold_matrix` | true | Use crypto_threshold_matrix.yaml for confidence bands | Kelly multiplier lookup |
| `confidence.profile_name` | modern_tradeable_kalshi_v1 | Profile in crypto_threshold_matrix.yaml | Kelly multiplier lookup |
| `confidence.kelly_multiplier_no_trade` | 0.0 | Override no-trade Kelly multiplier | Kelly sizing |
| `confidence.kelly_multiplier_cautious` | 0.5 | Override cautious Kelly multiplier | Kelly sizing |
| `confidence.kelly_multiplier_quick_win` | 0.6 | Override quick-win Kelly multiplier | Kelly sizing |
| `confidence.kelly_multiplier_confident` | 1.0 | Override confident Kelly multiplier | Kelly sizing |

### Guardrails (7 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `guardrails.max_spread_cents` | 10 | Reject if spread > 10 cents | Pre-trade checks |
| `guardrails.max_slippage_cents` | 3 | Max 3 cents worse than best | Pre-trade checks |
| `guardrails.min_depth_contracts` | 5 | Min depth at target price | Pre-trade checks |
| `guardrails.min_post_fee_edge` | 0.01 | Minimum post-fee edge (1%) | Pre-trade checks |
| `guardrails.drawdown_halt_pct` | 0.10 | Halt at 10% drawdown | Drawdown monitoring |
| `guardrails.drawdown_unwind_pct` | 0.15 | Unwind at 15% drawdown | Drawdown monitoring |
| `guardrails.max_daily_loss_usd` | 200.0 | Daily loss cap (absolute USD) | Daily loss monitoring |

### Kelly Sizing (5 knobs)

| Knob | Default | Description | Used In |
|------|---------|-------------|---------|
| `kelly.kelly_hard_cap` | 0.30 | Max 30% of capital per trade | Kelly sizing |
| `kelly.kelly_min_edge_pct` | 1.0 | Min 1% edge to trade | Kelly sizing |
| `kelly.kelly_max_edge_pct` | 25.0 | Max 25% edge (catches data errors) | Kelly sizing |
| `kelly.kelly_min_win_prob` | 0.01 | Min 1% win probability | Kelly sizing |
| `kelly.kelly_max_win_prob` | 0.99 | Max 99% win probability | Kelly sizing |
| `kelly.kelly_global_notional_cap_pct` | 2.0 | Max 2× capital total exposure | Kelly sizing |

### Legacy Path Control (5 flags)

| Flag | Default | Description | Effect |
|------|---------|-------------|--------|
| `legacy.disable_balance_calibration` | true | Disable calibrate_from_balance() | KalshiRiskConfig uses static values |
| `legacy.disable_dynamic_contract_caps` | true | Disable _compute_dynamic_contract_caps() | Contract caps from profile only |
| `legacy.disable_bankroll_category_limits` | true | Disable bankroll-derived CategoryLimit | Category cap from profile only |
| `legacy.disable_bankroll_prediction_risk` | true | Disable bankroll-derived PredictionRiskConfig | PredictionRiskConfig uses profile |
| `legacy.disable_bankroll_guardrails` | true | Disable bankroll-derived GuardrailConfig | GuardrailConfig uses profile |

**Total knobs: ~45 (but many are per-asset variations; core unique knobs ~25-30)**

## Key Design Principles

1. **Config-only, balance-agnostic:** All risk parameters are defined in the profile. Live bankroll is only used for:
   - Actual trade execution (you can't trade more than you have)
   - Optional Kelly fraction scaling (if enabled)
   - **NOT** for setting max_notional caps, category limits, or contract caps

2. **Single source of truth:** The profile is the only place where 15m crypto risk parameters are defined. No per-agent overrides, no env var overrides for this scope.

3. **Explicit legacy deprecation:** The `legacy` section explicitly disables all balance-derived behavior for this profile. This is a hard deprecation, not a soft fallback.

4. **Per-asset flexibility:** Each asset (BTC/ETH/SOL/XRP/DOGE) can have different notional caps and edge thresholds, allowing fine-tuning based on liquidity and volatility.

5. **Confidence band integration:** The profile can reference `crypto_threshold_matrix.yaml` for confidence bands, or override them inline. This allows reuse of the existing confidence band logic while keeping edge thresholds in the profile.

## Invariant & Testing

### Balance Independence Invariant

**For the `kalshi_crypto_15m_v2` profile, no risk/exposure cap below the cycle level may depend on live balance; all such caps must be derived from `config/profiles/kalshi_crypto_15m.yaml` only.**

This invariant is enforced by:

1. **Profile gating:** All legacy balance-derived functions (`calibrate_from_balance`, `_compute_dynamic_contract_caps`, etc.) are short-circuited when `MERID_PROFILE=kalshi_crypto_15m_v2` is active.

2. **Fixed profile values:** All notional caps, category limits, contract caps, and rate limits in the profile are explicit numbers, not "0 = derive from bankroll".

3. **Test enforcement:** `tests/test_profile_balance_independence.py` asserts that for a fixed profile, changing simulated bankroll does NOT change:
   - `max_single_order_usd`
   - `max_total_notional_usd`
   - Category and per-asset caps
   - Per-agent `max_notional` and `max_orders_per_window`

4. **Smoke test validation:** `tests/test_profile_smoke_test.py` validates the full path (profile → adapter → risk → agent) for all 15m crypto assets.

5. **Guard test:** `tests/test_profile_bankroll_guard.py` scans code for accidental re-introduction of bankroll logic in profile-gated paths.

**What MAY vary with bankroll:**
- Cycle-level risk sizing (based on profile `capital_usd` and `max_cycle_risk_pct`)
- Optional Kelly fraction scaling (if enabled for position sizing)
- Actual trade execution (you cannot trade more than your live balance allows)

**What MUST NOT vary with bankroll:**
- `max_single_order_usd` (venue-level cap)
- `max_total_notional_usd` (venue-level cap)
- Category notional caps (e.g., crypto category)
- Per-asset notional caps (BTC, ETH, SOL, XRP, DOGE)
- Per-agent notional caps and order limits
- Contract caps (total, per-asset, per-cluster)
- Rate limits (orders per minute/hour)
- Guardrail thresholds (spread, slippage, depth, drawdown, daily loss)
- Kelly sizing parameters (hard caps, edge clamps, win probability bounds)

### Test Coverage

| Test File | Purpose | Coverage |
|-----------|---------|----------|
| `tests/test_profile_balance_independence.py` | Assert balance independence across different bankrolls | Profile loading, adapter methods, config mapping |
| `tests/test_profile_smoke_test.py` | Full path integration test (profile → adapter → risk → agent) | All assets (BTC/ETH/SOL/XRP/DOGE), complete pipeline |
| `tests/test_profile_bankroll_guard.py` | Static analysis to prevent re-introduction of bankroll logic | Code scanning, profile gating verification |

### Regression Prevention

To prevent drift back to balance-derived behavior:

1. **Code review:** Any changes to `KalshiRiskConfig`, `PredictionRiskConfig`, `GuardrailConfig`, or agent grid must check for profile gating.

2. **CI gate:** Run `pytest tests/test_profile_balance_independence.py tests/test_profile_smoke_test.py tests/test_profile_bankroll_guard.py` in CI.

3. **Documentation:** This design doc serves as the canonical reference for the invariant.

4. **Profile gating comments:** All profile-gated code blocks have explicit `PROFILE GATING` comments with `kalshi_crypto_15m_v2` references.

## Migration Path

### Phase 1: Profile Creation (DONE)
- ✅ Create `config/profiles/kalshi_crypto_15m.yaml`
- ✅ Draft design doc (this file)

### Phase 2: Profile Adapter
- [ ] Create `merid/risk/profiles/crypto_15m_profile.py` with `Crypto15mProfileAdapter` class
- [ ] Implement `load_profile()` to load YAML and map to internal configs
- [ ] Implement adapter methods:
  - `to_kalshi_risk_config()` → KalshiRiskConfig
  - `to_cycle_sizing_cap()` → CycleSizingCap parameters
  - `to_agent_config(agent_name)` → Per-agent config
  - `to_category_limit(category)` → CategoryLimit

### Phase 3: Profile Gating
- [ ] Add profile detection: check `MERID_PROFILE` env var or equivalent flag
- [ ] In `KalshiRiskConfig.calibrate_from_balance()`, add:
  ```python
  if profile == "kalshi_crypto_15m_v2" and profile_config.legacy.disable_balance_calibration:
      return  # Skip balance calibration
  ```
- [ ] In `_compute_dynamic_contract_caps()`, add:
  ```python
  if profile == "kalshi_crypto_15m_v2" and profile_config.legacy.disable_dynamic_contract_caps:
      return profile_values  # Use profile values instead
  ```
- [ ] In `PredictionRiskConfig` and `GuardrailConfig`, add similar gating for balance-derived defaults

### Phase 4: Agent Wiring
- [ ] Update `config/kalshi_agent_grid.yaml` for 15m crypto agents to reference the profile:
  ```yaml
  agents:
  - name: BTC_15M
    risk_profile: kalshi_crypto_15m_v2
    # Remove max_notional_usd: 0 (derive from bankroll)
    # Remove max_orders_per_window: 0 (auto from bankroll)
  ```
- [ ] Update `KalshiTradingAgent` to load profile-based config when `risk_profile` is set
- [ ] Remove per-agent balance-derived logic for 15m crypto agents

### Phase 5: Testing
- [ ] Add unit test: `test_profile_balance_independence.py`
  - Assert that for a fixed profile, changing live bankroll does NOT change:
    - max_single_order_usd
    - max_total_notional_usd
    - category and per-asset caps
  - Assert that only cycle sizing (and optional Kelly fraction) can vary with bankroll
- [ ] Add integration test: run BTC_15M agent with profile and verify order sizing matches profile
- [ ] Add regression test: ensure legacy paths still work for non-profile agents

### Phase 6: Documentation and Cleanup
- [ ] Mark legacy configs as deprecated in YAML comments
- [ ] Move legacy configs to `config/legacy/` or mark with `deprecated: true`
- [ ] Update README with profile activation instructions
- [ ] Add profile to CI/CD for validation

## Adding New Assets

To add a new asset (e.g., LTC 15m):

1. Add edge thresholds in `config/crypto_threshold_matrix.yaml`:
   ```yaml
   LTC:
     15m: 0.025  # 2.5% min edge
   ```

2. Add per-asset block in `config/profiles/kalshi_crypto_15m.yaml`:
   ```yaml
   assets:
     LTC:
       max_notional_usd: 1000.0
       max_contracts: 100
       min_edge_early: 0.025
       min_edge_mid: 0.025
       min_edge_late: 0.025
       min_edge_terminal: 0.030
   ```

3. Add agent entry in `config/kalshi_agent_grid.yaml`:
   ```yaml
   agents:
   - name: LTC_15M
     risk_profile: kalshi_crypto_15m_v2
     assets:
     - LTC
     timeframes:
     - 15m
   ```

No changes to risk manager code required.

## Adding New Timeframes

To add a new timeframe (e.g., 1h BTC):

1. Create new profile: `config/profiles/kalshi_crypto_1h.yaml` (copy from 15m and adjust thresholds)
2. Add edge thresholds in `config/crypto_threshold_matrix.yaml` for 1h
3. Add agent entries in `config/kalshi_agent_grid.yaml` with `timeframes: [1h]`
4. Set `risk_profile: kalshi_crypto_1h_v2` for 1h agents

No code changes required beyond profile creation.

## References

- Profile: `config/profiles/kalshi_crypto_15m.yaml`
- Confidence matrix: `config/crypto_threshold_matrix.yaml`
- Agent grid: `config/kalshi_agent_grid.yaml`
- Risk audit: See `docs/RISK_EXPOSURE_AUDIT_REPORT.md` (if generated from audit)

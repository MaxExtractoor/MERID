# Risk Configuration Runbook

## Kalshi 15m Crypto Profile Configuration

### Single Source of Truth (SSOT)

- **Profile Name:** `kalshi_crypto_15m_v2`
- **Config File:** `config/profiles/kalshi_crypto_15m.yaml`
- **Environment Variable:** `MERID_PROFILE=kalshi_crypto_15m_v2`
- **Effective Profile Logger:** Logs at startup in `web/main_15m_lean.py` (lines 953-999)

### PM Profile Deprecation

**Status:** DEPRECATED for Kalshi 15m crypto

- `config/pm_profiles.yaml` is **NOT USED** for Kalshi 15m crypto
- `MERID_PM_PROFILE` environment variable is **IGNORED** when `MERID_PROFILE=kalshi_crypto_15m_v2`
- All edge thresholds, Kelly fractions, and risk limits come from `kalshi_crypto_15m.yaml`

**Rationale:**
- PM profiles were designed for a different trading regime (polymarket/multi-venue)
- Kalshi 15m crypto has specific risk requirements that don't map to PM profile structure
- Consolidating to a single YAML file reduces configuration drift and simplifies debugging

### Runtime Guard

**Behavior:** System will refuse startup if both `MERID_PROFILE=kalshi_crypto_15m_v2` and `MERID_PM_PROFILE` are set

**Location:** `web/main_15m_lean.py` (lines 967-979)

**Error Message:**
```
PROFILE-GUARD-ERROR: CONFLICTING PROFILE SIGNALS DETECTED
MERID_PROFILE=kalshi_crypto_15m_v2 but MERID_PM_PROFILE=<value> is set
For kalshi_crypto_15m_v2, PM profile must be unset or ignored.
PM profile YAML (config/pm_profiles.yaml) is deprecated for 15m crypto.
Single source of truth: config/profiles/kalshi_crypto_15m.yaml
```

**Action Required:** Unset `MERID_PM_PROFILE` from environment or `.env` file

### Effective Profile Logger

**Location:** `web/main_15m_lean.py` (lines 953-999)

**Startup Log Output:**
```
================================================================================
[PROFILE-SSOT-AUDIT] Effective Configuration for Kalshi 15m Crypto
================================================================================
MERID_PROFILE: kalshi_crypto_15m_v2
MERID_PM_PROFILE: NOT_SET (ignored for kalshi_crypto_15m_v2)
Asset List: BTC, ETH, SOL, XRP, DOGE (from kalshi_crypto_15m.yaml)
Daily Loss Limit: 0.05 USD (from kalshi_crypto_15m.yaml)
Max Notional Per Trade: <value> USD (from kalshi_crypto_15m.yaml)
Max Concurrent Trades: <value> (from kalshi_crypto_15m.yaml)
EV_K_TERMINAL: 2.0 (env var, default 2.0)
Kelly Fraction: 0.30 (from kalshi_crypto_15m.yaml)
SENTIMENT_MODE: disabled (from kalshi_crypto_15m.yaml)
================================================================================
```

**Verification:** Every time you change the YAML, confirm the logger reflects the new truth. This is your "spec vs implementation" checksum.

### Profile-Driven Configuration

**All risk/edge knobs must be added to `kalshi_crypto_15m.yaml` and surfaced by the effective profile logger.**

**Do NOT:**
- Hard-code risk thresholds in Python code
- Add new environment variables for risk parameters
- Use `pm_profiles.yaml` for Kalshi 15m crypto

**DO:**
- Add new risk/edge parameters to `kalshi_crypto_15m.yaml`
- Update the effective profile logger to log the new parameter
- Use `get_kalshi_risk()` to access profile values in code
- Profile values are applied via `get_kalshi_risk()` in `kalshi_risk.py`

### Key Profile Values (from kalshi_crypto_15m.yaml)

**Capital and Risk:**
- `capital_usd: 0` (derive from live Kalshi bankroll API)
- `min_notional_usd: 0.05` (minimum notional per trade)
- `max_cycle_risk_pct: 0.03` (3% of capital per cycle)
- `max_single_order_pct: 0.05` (5% of capital per single order)
- `max_total_notional_pct: 0.30` (30% of capital total exposure)

**Daily Loss:**
- `daily_loss_enabled: true`
- `max_daily_loss_pct: 0.05` (5% daily loss limit)

**Kelly Sizing:**
- `kelly_fraction: 0.30` (30% Kelly hard cap)
- `kelly_min_edge_pct: 1.0` (min 1% edge to trade)
- `kelly_max_edge_pct: 25.0` (max 25% edge)

**Sentiment Mode:**
- `sentiment_mode: disabled` (hard-coded in profile)

**Per-Asset Edge Thresholds (BTC/ETH/SOL/XRP/DOGE):**
- `min_edge_early: 0.05` (5% early edge)
- `min_edge_mid: 0.05` (5% mid edge)
- `min_edge_late: 0.05` (5% late edge)
- `min_edge_terminal: 0.06` (6% terminal edge)

### Configuration Override Hierarchy

When `MERID_PROFILE=kalshi_crypto_15m_v2` is active, this profile overrides:
1. `kalshi_agent_grid.yaml` risk_limits (set to 0 = profile-gated)
2. `kalshi_15m_crypto_config.py` GLOBAL_RISK_LIMITS (profile takes precedence)
3. `KalshiRiskConfig` defaults (profile values applied at initialization)
4. `capabilities.py` max_concurrent_trades (profile value used)

### Testing Profile Changes

**Before Production:**
1. Update `kalshi_crypto_15m.yaml` with new values
2. Run `web/main_15m_lean.py` in test mode
3. Check effective profile logger output
4. Verify numerical values match YAML exactly
5. Run `pytest tests/test_orchestrator_profile_guards.py` to verify guards

**Unit Tests:**
- `test_pm_profile_guarded_for_15m_profile` - PM profile returns empty dict
- `test_kelly_from_profile_not_hardcoded` - Kelly from profile, not hardcoded
- `test_runtime_guard_refuses_conflicting_profiles` - Guard refuses conflicting env vars

### Troubleshooting

**Issue:** Profile logger shows unexpected values
- **Check:** `MERID_PROFILE` environment variable is set to `kalshi_crypto_15m_v2`
- **Check:** `MERID_PM_PROFILE` is NOT set (or commented out in `.env`)
- **Check:** `kalshi_crypto_15m.yaml` has correct values
- **Check:** No hard-coded overrides in code (grep for hardcoded values)

**Issue:** Runtime guard error on startup
- **Check:** `MERID_PM_PROFILE` is set in `.env` or shell
- **Action:** Comment out or remove `MERID_PM_PROFILE` from `.env`
- **Action:** Run `unset MERID_PM_PROFILE` in shell before starting

**Issue:** Kelly fraction doesn't match profile
- **Check:** `kalshi_api.py` fallback uses `get_kalshi_risk()` (lines 5025-5030, 5210-5216)
- **Check:** No hardcoded `kelly_f = 0.25` or `base_kelly = 0.10` in code
- **Run:** `pytest tests/test_orchestrator_profile_guards.py::test_kelly_from_profile_not_hardcoded`

### References

- Profile YAML: `config/profiles/kalshi_crypto_15m.yaml`
- Effective Profile Logger: `web/main_15m_lean.py` (lines 953-999)
- Runtime Guard: `web/main_15m_lean.py` (lines 967-979)
- Risk Config Access: `merid/event_venues/kalshi/kalshi_risk.py` (`get_kalshi_risk()`)
- PM Profile Stub: `merid/prediction/pm_profiles.py` (guarded for 15m profile)
- Tests: `tests/test_orchestrator_profile_guards.py`

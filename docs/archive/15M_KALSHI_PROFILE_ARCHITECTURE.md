# 15m Kalshi Crypto Profile Architecture

## Single Source of Truth

For the Kalshi 15m crypto trading stack (BTC, ETH, SOL, XRP, DOGE), the `kalshi_crypto_15m_v2` profile is the **canonical single source of truth** for all risk and timing configuration.

### Profile Location
- File: `config/profiles/kalshi_crypto_15m.yaml`
- Profile name: `kalshi_crypto_15m_v2`
- Environment variable: `MERID_PROFILE=kalshi_crypto_15m_v2`

### What the Profile Controls

The profile defines all risk caps, per-asset limits, and bankroll-related policy:

**Global Capital & Risk:**
- `capital_usd`: Set to 0 to derive from live Kalshi bankroll API
- `max_cycle_risk_pct`: Maximum risk per cycle as percentage of capital
- `venue.max_single_order_pct`: Maximum notional per single order
- `venue.max_total_notional_pct`: Maximum total exposure
- `venue.max_category_notional_pct`: Maximum category exposure

**Per-Asset Caps:**
- `assets.{BTC,ETH,SOL,XRP,DOGE}.max_notional_pct`: Per-asset notional cap
- `assets.{BTC,ETH,SOL,XRP,DOGE}.max_contracts`: Per-asset contract cap
- `assets.{BTC,ETH,SOL,XRP,DOGE}.min_edge_*`: Edge thresholds per asset
- `assets.{BTC,ETH,SOL,XRP,DOGE}.max_distance_pct`: Distance-from-target filter

**Agent Defaults:**
- `agent_defaults.max_notional_pct`: Default per-agent notional
- `agent_defaults.max_orders_per_window`: Order rate limit
- `agent_defaults.max_yes_position`: Max YES contracts per side
- `agent_defaults.max_no_position`: Max NO contracts per side
- `agent_defaults.minutes_before_expiry`: Entry window start
- `agent_defaults.cutoff_minutes_before_expiry`: Entry window end

**Guardrails:**
- `guardrails.drawdown_halt_pct`: Drawdown halt threshold
- `guardrails.drawdown_unwind_pct`: Drawdown unwind threshold
- `guardrails.per_trade_risk_pct`: Per-trade risk percentage
- `guardrails.adaptive_risk_bands`: Risk scaling by drawdown

**Kelly Sizing:**
- `kelly.kelly_fraction`: Kelly hard cap
- `kelly.kelly_min_edge_pct`: Minimum edge for Kelly
- `kelly.kelly_max_edge_pct`: Maximum edge for Kelly

### What kalshi_agent_grid.yaml Controls

The agent grid YAML (`config/kalshi_agent_grid.yaml`) is **PROFILE-GATED** for 15m crypto agents:

**Still Used:**
- `series_tickers`: Market series to scan (KXBTC15M, KXETH15M, etc.)
- `assets`: Asset list (BTC, ETH, SOL, XRP, DOGE)
- `timeframes`: Timeframe (15m)
- `archetype`: Agent archetype (directional)
- `market_filter`: Category and frequency filters
- `strategy_overrides.min_edge_*`: Edge thresholds (profile takes precedence)
- `take_profit`: Take-profit configuration
- `strike_selection`: Strike selection parameters

**NOT Used (Profile Overrides):**
- `risk_limits`: Risk limits come from profile
- `entry_window`: Entry window comes from profile

### Profile Override Application

Profile overrides are applied in `merid/prediction/agent_grid_config.py`:

```python
if is_profile_active():
    profile_adapter = get_active_profile()
    overrides = profile_adapter.to_agent_overrides(name)
    if overrides.get('max_yes_position', 0) > 0:
        agent.risk_limits.max_yes_position = overrides['max_yes_position']
    # ... similar for other risk limits
    if 'min_edge_early' in overrides:
        agent.strategy_overrides['min_edge_early'] = overrides['min_edge_early']
    # ... similar for other edge thresholds
```

### Why Profile as Single Source?

1. **Consistency**: All risk caps derived from same source, no drift
2. **Bankroll Scaling**: Risk caps scale with live bankroll automatically
3. **Adaptive Risk**: Risk bands adjust based on drawdown
4. **Audit Trail**: Profile version tracked in metadata
5. **No Duplication**: Single source eliminates config drift

### Migration Path

To migrate from old config to profile-based config:

1. Set `MERID_PROFILE=kalshi_crypto_15m_v2` in environment
2. Remove `risk_limits` sections from `kalshi_agent_grid.yaml`
3. Remove `entry_window` sections from `kalshi_agent_grid.yaml`
4. Add PROFILE-GATED comment to `kalshi_agent_grid.yaml`
5. Verify profile values match intended risk caps

### Verification

To verify profile is active:

```python
from merid.config.agent_modes import is_profile_active, get_active_profile

if is_profile_active():
    profile = get_active_profile()
    print(f"Active profile: {profile.profile_name}")
    print(f"Profile version: {profile.profile_version}")
```

### Legacy Config Deprecation

The following are deprecated for 15m crypto:
- `config/kalshi_15m_crypto_config.py` (ASSET_RISK_LIMITS, GLOBAL_RISK_LIMITS)
- `merid/prediction/risk/kalshi_risk_engine.py` (KalshiRiskConfig dataclass)

These are superseded by the profile and should not be used for 15m crypto trading.

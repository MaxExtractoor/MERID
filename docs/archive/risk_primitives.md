# Risk Primitives: Sources of Truth

**Last Updated:** 2026-05-14  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This document defines the canonical sources of truth for risk-related primitives in the MERID codebase. All fee calculations, drawdown limits, and risk enforcement should flow through these canonical implementations to prevent silent divergence.

---

## Pre-Trade Risk Control Architecture

The canonical fee and drawdown primitives are positioned within the broader pre-trade risk control stack as follows:

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRE-TRADE RISK CONTROLS                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: Market Filter (First Line)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Category filter (crypto only)                         │   │
│  │ • Frequency filter (fifteen_min only)                   │   │
│  │ • Series ticker validation (KXBTC15M, etc.)             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 2: Fat-Finger Limits                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Max single order size (venue_max_single_order_pct)    │   │
│  │ • Min order size (1 contract)                          │   │
│  │ • Max daily exposure (max_cycle_risk_pct)              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 3: Per-Order Notional Bounds (Profile-Driven)         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • max_notional_usd (from profile)                      │   │
│  │ • max_yes_position (from profile)                       │   │
│  │ • max_no_position (from profile)                        │   │
│  │ • Enforced by _prediction_risk.py check_order()         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 4: Fee Calculation (Canonical) ← PRIMARY PRIMITIVE     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • calculate_kalshi_fee_cents() from fees.py            │   │
│  │ • Parabolic tiered formula (7%/5%/3%)                  │   │
│  │ • Minimum 2¢ per contract                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 5: Per-Timeframe Throttles (Profile-Driven)          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • max_orders_per_window (from profile)                 │   │
│  │ • minutes_before_expiry (from profile)                  │   │
│  │ • cutoff_minutes_before_expiry (from profile)           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 6: Drawdown Enforcement (Profile-Driven) ← PRIMARY    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • drawdown_halt_pct (from profile)                     │   │
│  │ • drawdown_unwind_pct (from profile)                   │   │
│  │ • max_daily_loss_usd (from profile)                    │   │
│  │ • Enforced by _prediction_risk.py                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 7: Kill-Switch (Last Line)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Global kill-switch (environment variable)             │   │
│  │ • Per-agent kill-switch (API)                           │   │
│  │ • Immediate halt on trigger                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Order Execution                                            │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Layer 4 (Fee Calculation) and Layer 6 (Drawdown Enforcement) are the canonical primitives documented in this document
- All other layers provide additional safety controls but are not the focus of this document
- The pre-trade controls checklist in `docs/STRATEGY_ONBOARDING.md` provides a complete verification process for all layers

---

## Public API

This section defines the supported public API for fee and drawdown primitives. **All new code that needs fee/drawdown calculations MUST depend on these interfaces, never re-implement.**

### Fee Calculation API

**Primary Function:**
```python
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

def calculate_kalshi_fee_cents(contracts: int, price_cents: int) -> int:
    """
    Calculate total Kalshi fee in cents for a trade.

    Args:
        contracts: Number of contracts (positive integer)
        price_cents: Price per contract in cents (1-99)

    Returns:
        Total fee in cents (integer, rounded up, minimum 2¢ per contract)

    Formula:
        fee = ceil(rate × contracts × price × (1 - price))
        where rate = 7% (1-99 contracts), 5% (100-999), 3% (1000+)
        and price = price_cents / 100

    Raises:
        ValueError: If contracts <= 0 or price_cents not in [1, 99]
    """
```

**Supporting Functions:**
```python
from merid.event_venues.kalshi.fees import (
    calculate_kalshi_fee_per_contract_cents,
    calculate_fee_drag_bps,
    calculate_net_edge_bps,
)

def calculate_kalshi_fee_per_contract_cents(contracts: int, price_cents: int) -> int:
    """Calculate fee per single contract in cents."""

def calculate_fee_drag_bps(contracts: int, price_cents: int) -> float:
    """Calculate fee drag in basis points (fee / notional × 10000)."""

def calculate_net_edge_bps(edge_bps: int, contracts: int, price_cents: int) -> float:
    """Calculate net edge after fees in basis points."""
```

**Usage Example:**
```python
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

# Calculate fee for 10 contracts at 55¢ each
fee = calculate_kalshi_fee_cents(contracts=10, price_cents=55)
# Returns: 17¢ (ceil(0.07 × 10 × 0.55 × 0.45) = ceil(0.17325) = 0.17325 × 100)
```

### Drawdown Enforcement API

**Profile-Driven Drawdown Check (15m Crypto):**
```python
from merid.prediction.risk._prediction_risk import PredictionRiskConfig
from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile

# When profile is active, drawdown limits come from profile YAML
if is_profile_active():
    adapter = get_active_profile()
    profile = adapter.profile
    drawdown_halt_pct = profile.guardrails_drawdown_halt_pct      # e.g., 0.10
    drawdown_unwind_pct = profile.guardrails_drawdown_unwind_pct  # e.g., 0.15
    max_daily_loss_usd = profile.guardrails_max_daily_loss_usd    # e.g., 200.0
```

**Runtime Enforcement:**
```python
from merid.prediction.risk._prediction_risk import PredictionRiskConfig

# Create risk config with profile-driven limits
risk_config = PredictionRiskConfig(
    drawdown_halt_pct=0.10,      # From profile YAML
    drawdown_unwind_pct=0.15,    # From profile YAML
    max_daily_loss_usd=200.0,    # From profile YAML
)

# Check order against drawdown limits
allowed, reason = risk_config.check_order(...)
```

**Profile Override Application:**
```python
from merid.risk.profiles.crypto_15m_profile import get_active_profile

adapter = get_active_profile()
profile = adapter.profile

# Apply profile overrides to agent config
overrides = adapter.to_agent_overrides(agent_name="BTC_15M")
# Returns: dict with max_notional_usd, max_orders_per_window, etc.
```

### Dependency Rules

**DO:**
- Import from `merid.event_venues.kalshi.fees` for all fee calculations
- Use profile-driven drawdown limits via `crypto_15m_profile.py` for 15m crypto
- Call `calculate_kalshi_fee_cents()` directly in strategy/agent code
- Use `to_agent_overrides()` to apply profile parameters to agents

**DO NOT:**
- Reimplement the parabolic fee formula (`0.07 * price * (1 - price)`)
- Hardcode drawdown thresholds in strategy code
- Create new `kalshi_fee_*` functions outside `fees.py`
- Use legacy config files (`trade_hold_config.yaml`, `trading_constants.py`) for 15m crypto
- Bypass profile gating in `_prediction_risk.py`

**Exception:**
- Backtest-only modules may use simplified cost models if clearly marked as legacy
- Non-15m agents may use legacy config paths (documented in Migration Path section)

---

## Canonical Risk Primitives

### 1. Kalshi Fees

**Canonical Implementation:** `merid/event_venues/kalshi/fees.py`

**Functions:**
- `calculate_kalshi_fee_cents(contracts: int, price_cents: int) -> int` - Primary fee calculation
- `calculate_kalshi_fee_per_contract_cents(contracts: int, price_cents: int) -> int` - Per-contract fee
- `calculate_fee_drag_bps(contracts: int, price_cents: int) -> float` - Fee drag in basis points
- `calculate_net_edge_bps(edge_bps: int, contracts: int, price_cents: int) -> float` - Net edge after fees

**Fee Schedule (Tiered, Parabolic Formula):**
```
fee = ceil(rate × contracts × price × (1 - price))
where:
  - rate = 7% for 1-99 contracts
  - rate = 5% for 100-999 contracts  
  - rate = 3% for 1000+ contracts
  - price = price_cents / 100
  - minimum fee = 2¢ per contract
```

**Reference:** [Kalshi Fee Schedule](https://kalshi.com/fee-schedule)

**Usage Rules:**
- All live trading fee calculations MUST use `calculate_kalshi_fee_cents()`
- Backtest strategies SHOULD import from `fees.py` (e.g., `kalshi_15m_backtest.py`)
- No duplicate fee implementations allowed in production code
- UI may use simplified display values (e.g., 7% headline rate) but must clarify it's an estimate

**Delegating Modules (OK):**
- `merid/event_venues/kalshi/kalshi_risk.py` - Delegates to canonical via `calculate_kalshi_fee_cents()`
- `merid/event_venues/kalshi/position_sizer.py` - Delegates to canonical via `calculate_kalshi_fee_cents()`
- `merid/prediction/risk/kalshi_risk_engine.py` - Delegates to canonical (PM-specific, test-only)

**Legacy/Backtest-Only (May Diverge):**
- `merid/strategies/kelly_with_costs.py` - Generic backtesting cost model, not used by 15m live agents
- `merid/strategies/costs.py` - Generic backtesting cost model, not used by 15m live agents

---

### 2. Drawdown Limits

**Canonical Enforcement:** `merid/prediction/risk/_prediction_risk.py`

**Profile-Driven for 15m Crypto:** When `kalshi_crypto_15m_v2` profile is active, drawdown limits are pulled from:
- Profile Config: `config/profiles/kalshi_crypto_15m.yaml`
- Profile Loader: `merid/risk/profiles/crypto_15m_profile.py`

**Profile Fields:**
```yaml
guardrails:
  drawdown_halt_pct: 0.10      # Halt at 10% drawdown
  drawdown_unwind_pct: 0.15    # Unwind at 15% drawdown
  max_daily_loss_usd: 200.0    # Daily loss cap in USD
```

**Profile Gating Logic:**
```python
# In _prediction_risk.py __post_init__():
if is_profile_active():
    adapter = get_active_profile()
    profile = adapter.profile
    self.drawdown_halt_pct = Decimal(str(profile.guardrails_drawdown_halt_pct))
    self.drawdown_unwind_pct = Decimal(str(profile.guardrails_drawdown_unwind_pct))
    self.max_daily_loss_usd = Decimal(str(profile.guardrails_max_daily_loss_usd))
```

**Usage Rules:**
- 15m crypto agents MUST use profile-driven drawdown limits
- Profile gating ensures single source of truth for 15m crypto
- Hardcoded defaults in `_prediction_risk.py` only apply when profile is inactive

**Legacy Configs (Not Used by 15m Crypto):**
- `config/trade_hold_config.yaml` - Legacy for non-crypto, non-15m agents
- `config/trading_constants.py` - Legacy for non-crypto, non-15m agents
- `merid/prediction/trade_hold_config.py` - Legacy for non-crypto, non-15m agents
- `merid/prediction/risk.py` - Legacy for non-crypto, non-15m agents

---

## 15m Crypto Agent Profile Hierarchy

For Kalshi 15m crypto agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M):

```
Single Source of Truth:
  config/profiles/kalshi_crypto_15m.yaml
         ↓
  merid/risk/profiles/crypto_15m_profile.py (loader)
         ↓
  merid/prediction/agent_grid_config.py (profile overrides applied)
         ↓
  merid/prediction/trading_agent.py (runtime config)
         ↓
  merid/prediction/risk/_prediction_risk.py (enforcement)
```

**Profile-Driven Parameters:**
- Edge thresholds (from `crypto_threshold_matrix.yaml` via profile)
- Risk limits (max_notional, max_contracts, etc.)
- Drawdown limits (halt_pct, unwind_pct, daily_loss_usd)
- Entry window parameters (minutes_before_expiry, cutoff_minutes_before_expiry)
- Kelly sizing parameters
- Guardrails (max_spread, max_slippage, min_depth, min_post_fee_edge)

**NOT Used by 15m Crypto:**
- `config/trade_hold_config.yaml` constants
- `config/trading_constants.py` constants
- Hardcoded defaults in `EntryWindowConfig`
- Hardcoded defaults in `_prediction_risk.py` (when profile active)

---

## Legacy Lane Policies

The following modules are marked as legacy/backtest-only and **may differ from live behavior**. These modules should **not** be used for:

- Production risk decisions
- PnL numbers displayed in user-facing dashboards
- Fee calculations for live trading
- Drawdown enforcement for live agents

### Backtest/Simulation Modules

These modules use simplified cost models for backtesting and strategy evaluation. They are **not** used by live 15m crypto agents.

- `merid/strategies/kelly_with_costs.py`
  - **Purpose**: Generic backtesting cost model for Kelly fraction optimization
  - **Fee Model**: Simplified `slippage_bps` and `commission_bps` parameters
  - **Divergence**: Does not use Kalshi's parabolic tiered fee formula
  - **Usage**: Backtesting only - never for live trading
  - **Live Equivalent**: Use `merid/event_venues/kalshi/fees.py`

- `merid/strategies/costs.py`
  - **Purpose**: Generic backtesting cost calculations for strategy evaluation
  - **Fee Model**: Fixed percentage-based costs
  - **Divergence**: Does not account for Kalshi's minimum 2¢ per contract fee
  - **Usage**: Backtesting only - never for live trading
  - **Live Equivalent**: Use `merid/event_venues/kalshi/fees.py`

- `merid/strategies/production_strategy_15m.py`
  - **Purpose**: Backtest strategy for 15m crypto (historical data analysis)
  - **Fee Model**: May use simplified costs for backtesting speed
  - **Divergence**: Backtest environment may not perfectly match live execution
  - **Usage**: Research and backtesting only
  - **Live Equivalent**: Live agents use profile-driven configuration

- `merid/strategies/integrated_production_strategy.py`
  - **Purpose**: Integrated backtest strategy for BTC/ETH 15m
  - **Fee Model**: May use simplified costs for backtesting
  - **Divergence**: Backtest PnL may not match live PnL due to execution differences
  - **Usage**: Research and backtesting only
  - **Live Equivalent**: Live agents use profile-driven configuration

### Legacy Config Modules

These configuration files are for non-crypto, non-15m agents and are **not** used by 15m crypto agents.

- `config/trade_hold_config.yaml`
  - **Purpose**: Legacy configuration for non-crypto, non-15m agents
  - **Drawdown Model**: Hardcoded `max_daily_loss_usd` and drawdown limits
  - **Divergence**: Not profile-driven, may have different values
  - **Usage**: Legacy agents only - 15m crypto use `kalshi_crypto_15m.yaml`
  - **Live Equivalent**: Use `config/profiles/kalshi_crypto_15m.yaml` for 15m crypto

- `config/trading_constants.py`
  - **Purpose**: Legacy trading constants for non-crypto agents
  - **Risk Model**: Hardcoded risk limits and thresholds
  - **Divergence**: Not profile-driven, static values
  - **Usage**: Legacy agents only - 15m crypto use profile-driven values
  - **Live Equivalent**: Use profile-driven values via `crypto_15m_profile.py`

- `merid/prediction/trade_hold_config.py`
  - **Purpose**: Legacy configuration loader for non-crypto agents
  - **Risk Model**: Loads from `trade_hold_config.yaml`
  - **Divergence**: Different schema from 15m crypto profiles
  - **Usage**: Legacy agents only - 15m crypto use profile loader
  - **Live Equivalent**: Use `merid/risk/profiles/crypto_15m_profile.py`

- `merid/prediction/risk.py`
  - **Purpose**: Legacy risk configuration for non-crypto agents
  - **Risk Model**: Hardcoded risk limits and drawdown thresholds
  - **Divergence**: Not profile-gated, static implementation
  - **Usage**: Legacy agents only - 15m crypto use `_prediction_risk.py`
  - **Live Equivalent**: Use `merid/prediction/risk/_prediction_risk.py` with profile gating

### Legacy Trading Modules

- `merid/trading/kalshi_continuous_trader.py`
  - **Purpose**: Legacy continuous trader (research/parity checks only)
  - **Fee Model**: May use simplified fee calculations
  - **Divergence**: Not the primary execution path for 15m crypto
  - **Usage**: Research and parity checks only
  - **Live Equivalent**: Use KalshiTradingAgent via AgentGrid for live trading

### Regime Opinion Agents

These agents produce opinions for consensus but are separate from the main 15m crypto trading agents.

- `merid/agents/btc_15m_agent.py` - Regime opinion agent for TaCo consensus
- `merid/agents/eth_15m_agent.py` - Regime opinion agent for TaCo consensus
- `merid/agents/sol_15m_agent.py` - Regime opinion agent for TaCo consensus
- `merid/agents/xrp_15m_agent.py` - Regime opinion agent for TaCo consensus
- `merid/agents/doge_15m_agent.py` - Regime opinion agent for TaCo consensus

**Note**: These regime agents produce opinions for consensus but are separate from the main 15m crypto trading agents that use profile-driven risk parameters. They may use different risk models for opinion generation.

### Lane-Based Trading (Separate System)

- `merid/lanes/btc15m_lane.py` - Lane-based trading system (separate from main 15m crypto agents)
- `merid/risk/multi_tf_drawdown.py` - Multi-timeframe drawdown guard for lane-based trading

**Note**: The lane-based trading system uses its own drawdown monitoring (`MultiTFDrawdownGuard`) which is separate from the profile-driven drawdown enforcement in `_prediction_risk.py`. This is a separate system for a different trading paradigm.

---

## Legacy Module Usage Guidelines

### When to Use Legacy Modules

**Acceptable Use Cases:**
- Backtesting and historical analysis
- Strategy research and development
- Parity checks between systems
- Educational purposes (understanding different approaches)

**Unacceptable Use Cases:**
- Production risk decisions
- Live trading fee calculations
- User-facing PnL displays
- Drawdown enforcement for live agents
- Any production risk control logic

### How to Identify Legacy Modules

Legacy modules are marked with docstrings indicating their status:

```python
"""
LEGACY CONFIGURATION

This module is a legacy configuration for non-crypto, non-15m agents.
15m crypto agents should use kalshi_crypto_15m.yaml for risk and drawdown limits.

DO NOT USE THIS MODULE FOR:
- Production risk decisions
- PnL numbers displayed in user-facing dashboards
- Fee calculations for live trading
"""
```

### Migration Path

If you need to migrate a legacy module to use canonical primitives:

1. **For Backtest Modules**: Add a docstring clarifying it's backtest-only and reference the canonical modules
2. **For Config Modules**: Add a deprecation warning pointing to the profile system
3. **For Risk Modules**: Refactor to use `_prediction_risk.py` with profile gating
4. **For Trading Modules**: Refactor to use `fees.py` for fee calculations

See `docs/STRATEGY_ONBOARDING.md` for guidance on creating new agents that use canonical primitives.

---

## Enforcement & Validation

### Startup Validation
- `merid/startup_validations.py` includes validation to ensure profile restrictions are enforced
- `validate_15m_crypto_profile_restrictions()` ensures only 5 crypto agents are active for the profile

### CI Checks (Planned)
- Static/grep-based check to prevent new `kalshi_fee_*` functions outside `fees.py`
- Static check to prevent hardcoded drawdown thresholds in 15m crypto strategies
- Pattern matching for `0.07 * price * (1 - price)` outside canonical modules

### Invariant Tests (Planned)
- Backtest vs live fee calculation equivalence
- Drawdown monitoring alignment with risk enforcement

---

## Migration Path for Non-15m Agents

For agents that are not currently profile-driven (non-crypto, non-15m):

1. **Option A: Keep Legacy Path**
   - Continue using `trade_hold_config.yaml` and `trading_constants.py`
   - Add explicit comments indicating "legacy path, not 15m crypto"
   - No changes to risk enforcement logic

2. **Option B: Migrate to Profile-Driven**
   - Add profile config YAML for the agent class
   - Update `crypto_15m_profile.py` or create new profile loader
   - Add profile gating in relevant risk modules
   - Remove legacy config dependencies

**Recommendation:** Keep legacy path for non-15m agents to minimize risk. Only migrate if there's a clear business need.

---

## Quick Reference

| Primitive | Canonical Source | 15m Crypto Path | Legacy Path |
|-----------|-----------------|-----------------|-------------|
| Kalshi Fees | `merid/event_venues/kalshi/fees.py` | `fees.py` → `_prediction_risk.py` | N/A (use canonical) |
| Drawdown Limits | `merid/prediction/risk/_prediction_risk.py` | Profile YAML → Profile Loader → `_prediction_risk.py` | `trade_hold_config.yaml` / `risk.py` |
| Edge Thresholds | `config/crypto_threshold_matrix.yaml` | Profile YAML → `agent_grid_config.py` | `trade_hold_config.yaml` |
| Entry Windows | `merid/prediction/agent_grid_config.py` | Profile YAML → `agent_grid_config.py` | `EntryWindowConfig` defaults |
| Risk Limits (Notional) | `merid/risk/profiles/crypto_15m_profile.py` | Profile YAML → Profile Loader | `trade_hold_config.yaml` |

---

## Change Log

- 2026-05-14: Initial document created, established canonical sources of truth
- 2026-05-14: Fee consolidation completed - all duplicate implementations delegated to `fees.py`
- 2026-05-14: Drawdown consolidation completed - profile gating added to `_prediction_risk.py`
- 2026-05-15: Added pre-trade risk control architecture diagram
- 2026-05-15: Added Kalshi fee schedule change procedure

---

## Kalshi Fee Schedule Change Procedure

When Kalshi adjusts their fee schedule or introduces new contract types with non-standard fees, follow this procedure to update the canonical primitives with minimal code edits.

### Step 1: Detect Fee Schedule Change

**Detection Methods:**
- Monitor Kalshi's fee schedule page: https://kalshi.com/fee-schedule
- Subscribe to Kalshi announcements for fee changes
- Monitor fee drift alerts from `docs/alert_rules.md`
- Check surveillance reconciliation reports for fee anomalies

### Step 2: Update fees.py

**Location:** `merid/event_venues/kalshi/fees.py`

**Changes Required:**
- Update tier rates if changed (e.g., 7% → 8%)
- Update tier boundaries if changed (e.g., 1-99 → 1-149)
- Add new tiers if introduced
- Update minimum fee if changed
- Add special handling for new contract types if needed

**Example: Updating Tier Rates**
```python
# Before:
rate = 0.07 if contracts < 100 else (0.05 if contracts < 1000 else 0.03)

# After (if Kalshi changes rates):
rate = 0.08 if contracts < 100 else (0.06 if contracts < 1000 else 0.04)
```

**Example: Adding New Tier**
```python
# Before:
rate = 0.07 if contracts < 100 else (0.05 if contracts < 1000 else 0.03)

# After (if Kalshi adds new tier):
rate = 0.07 if contracts < 100 else (0.05 if contracts < 500 else (0.04 if contracts < 1000 else 0.03))
```

### Step 3: Update Documentation

**Location:** `docs/risk_primitives.md`

**Changes Required:**
- Update fee schedule section with new rates
- Add version note: "As of YYYY-MM-DD, Kalshi updated fee schedule to X"
- Update reference link if needed

**Example:**
```markdown
**Fee Schedule (Tiered, Parabolic Formula) - Updated 2026-06-01:**
```
fee = ceil(rate × contracts × price × (1 - price))
where:
  - rate = 8% for 1-99 contracts (changed from 7%)
  - rate = 6% for 100-999 contracts (changed from 5%)
  - rate = 4% for 1000+ contracts (changed from 3%)
  - price = price_cents / 100
  - minimum fee = 2¢ per contract
```

**Reference:** [Kalshi Fee Schedule](https://kalshi.com/fee-schedule)
```

### Step 4: Run Replay Harness for Impact Analysis

**Purpose:** Verify how PnL and DD behavior would have differed under new fees

**Steps:**
```bash
# Export recent fills (last 30 days)
python scripts/export_fills.py --days 30 --output recent_fills.json

# Run replay harness with current fees
python scripts/replay_harness.py \
  --fills recent_fills.json \
  --profile kalshi_crypto_15m_v2 \
  --output replay_old_fees.json

# Update fees.py with new schedule
# (Edit merid/event_venues/kalshi/fees.py)

# Run replay harness with new fees
python scripts/replay_harness.py \
  --fills recent_fills.json \
  --profile kalshi_crypto_15m_v2 \
  --output replay_new_fees.json

# Compare results
python scripts/compare_replays.py \
  --baseline replay_old_fees.json \
  --test replay_new_fees.json \
  --output fee_change_impact.json
```

**Analysis:**
- Compare total fees under old vs new schedule
- Compare PnL impact
- Identify which agents/tiers are most affected
- Determine if strategy parameters need adjustment

### Step 5: Update Alert Thresholds (if needed)

**Location:** `docs/alert_rules.md`

**Changes Required:**
- Update fee drift threshold if typical fee rate changes significantly
- Update tier distribution baseline if tier boundaries change
- Update dashboard requirements if needed

**Example:**
```markdown
**Alert 1.2: Fee Drift from Expected Rate**
**Threshold:** > 1% (0.01) for > 10 fills → Updated to > 2% (0.02) due to new fee schedule
```

### Step 6: Update Dashboard Requirements (if needed)

**Location:** `docs/dashboard_requirements.md`

**Changes Required:**
- Update expected fee rate reference lines if rates changed
- Update tier distribution baseline if tiers changed
- Add new tier to dashboard if new tier introduced

### Step 7: Deploy with Monitoring

**Steps:**
1. Deploy updated `fees.py` to demo environment first
2. Run surveillance reconciliation for demo
3. Compare demo fees with venue data
4. Deploy to production
5. Monitor fee dashboard closely for first 24 hours
6. Run surveillance reconciliation daily for first week

### Step 8: Document Change

**Location:** `docs/risk_primitives.md` (Change Log section)

**Add Entry:**
```markdown
- YYYY-MM-DD: Kalshi fee schedule updated - tier rates changed from X to Y
```

### Rollback Procedure

If new fee schedule causes issues:

1. **Revert fees.py**
   ```bash
   git checkout HEAD~1 merid/event_venues/kalshi/fees.py
   ```

2. **Deploy Rollback**
   ```bash
   # Deploy rollback
   ```

3. **Post-Mortem**
   - Document why new fees caused issues
   - Analyze if replay harness predicted the issue
   - Update impact analysis methodology

### Special Contract Types

If Kalshi introduces new contract types with non-standard fees:

1. **Add Special Handling in fees.py**
   ```python
   def calculate_kalshi_fee_cents(contracts: int, price_cents: int, contract_type: str = "standard") -> int:
       if contract_type == "special":
           # Apply special fee logic
           return calculate_special_fee(contracts, price_cents)
       else:
           # Apply standard parabolic formula
           return calculate_standard_fee(contracts, price_cents)
   ```

2. **Update Public API Documentation**
   ```markdown
   **Primary Function:**
   ```python
   def calculate_kalshi_fee_cents(contracts: int, price_cents: int, contract_type: str = "standard") -> int:
       """
       Calculate total Kalshi fee in cents for a trade.
       
       Args:
           contracts: Number of contracts (positive integer)
           price_cents: Price per contract in cents (1-99)
           contract_type: Contract type (standard, special, etc.)
       ```
   ```

3. **Update Call Sites**
   - Update all call sites to pass `contract_type` parameter if needed
   - Update `kalshi_risk.py` to pass contract type from market data
   - Update `order_router.py` to pass contract type

### Testing Checklist

Before deploying fee schedule changes:

- [ ] fees.py updated with new rates/tiers
- [ ] Documentation updated with version notes
- [ ] Replay harness run on recent fills
- [ ] Impact analysis completed
- [ ] Alert thresholds updated if needed
- [ ] Dashboard requirements updated if needed
- [ ] Demo deployment tested
- [ ] Surveillance reconciliation run on demo
- [ ] Production deployment approved
- [ ] Monitoring plan in place
- [ ] Rollback procedure documented

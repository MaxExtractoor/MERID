# Strategy Onboarding Playbook

**Last Updated:** 2026-05-14  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This playbook provides step-by-step instructions for adding a new 15m-crypto strategy or agent to the MERID system. It ensures that new work follows the canonical fee and drawdown primitives and maintains consistency with existing patterns.

---

## Prerequisites

Before adding a new 15m-crypto strategy, ensure you have:

1. Read `docs/risk_primitives.md` - Understand canonical fee and drawdown sources
2. Reviewed `config/profiles/kalshi_crypto_15m_template.yaml` - Profile template
3. Reviewed existing 15m agent specs (e.g., `config/kalshi_btc_15m_agent_spec.py`)
4. Access to Kalshi API credentials for the target environment
5. Approval from risk team for new strategy parameters

---

## Step 1: Create or Select Profile

### Option A: Use Existing Profile

If the new strategy can use existing risk parameters (e.g., same drawdown limits, sizing), use the existing `kalshi_crypto_15m.yaml` profile.

**When to use:**
- Strategy is a variant of existing strategy (e.g., different signal source)
- Risk parameters are identical to existing 15m crypto agents

**Steps:**
1. Confirm with risk team that existing profile is appropriate
2. No profile changes needed - proceed to Step 2

### Option B: Create New Profile

If the new strategy requires different risk parameters (e.g., more aggressive drawdown limits), create a new profile.

**When to use:**
- Strategy has different risk appetite
- Different asset class or timeframe (not covered by existing profile)
- Experimental strategy with tighter limits

**Steps:**
1. Copy `config/profiles/kalshi_crypto_15m_template.yaml` to new file (e.g., `kalshi_crypto_15m_aggressive.yaml`)
2. Update profile metadata:
   ```yaml
   profile_name: "kalshi_crypto_15m_aggressive"
   profile_version: "1.0.0"
   description: "Aggressive 15m-crypto profile for experimental strategies"
   ```
3. Adjust risk parameters according to risk team approval:
   - `guardrails.drawdown_halt_pct` (e.g., 0.15 for 15% halt)
   - `guardrails.drawdown_unwind_pct` (e.g., 0.20 for 20% unwind)
   - `guardrails.max_daily_loss_usd` (e.g., 500.0 for $500 daily cap)
   - `agent_defaults.max_notional_usd` (e.g., 2000.0 for $2000 notional)
4. Ensure `enable_sentiment_execution: false` for 15m crypto
5. Run profile validation:
   ```bash
   python -c "from merid.startup_validations import validate_15m_crypto_profile_fields; validate_15m_crypto_profile_fields()"
   ```
6. Get risk team approval for profile values

---

## Step 2: Create Agent Spec

Create the agent specification file that defines strategy parameters and signal generation logic.

**Location:** `config/{asset}_15m_agent_spec.py` (e.g., `config/ada_15m_agent_spec.py` for Cardano)

**Template:**
```python
"""
ADA 15m Agent Specification

This module defines the strategy parameters, signal generation, and risk rules
for the ADA_15M agent on Kalshi 15-minute crypto prediction markets.

Canonical Risk Primitives:
- Fees: merid/event_venues/kalshi/fees.py (calculate_kalshi_fee_cents)
- Drawdown: merid/prediction/risk/_prediction_risk.py (profile-driven)
- Profile: config/profiles/kalshi_crypto_15m.yaml (or custom profile)
"""

from dataclasses import dataclass
from typing import Optional, List
from decimal import Decimal

@dataclass
class Ada15mInputs:
    """Input data for ADA 15m signal generation."""
    # Market data
    spot_price: float
    order_book_imbalance: float
    recent_trades_volume: float
    # Sentiment
    social_sentiment: float
    news_sentiment: float
    # Technical indicators
    rsi: float
    macd: float
    bollinger_position: float

@dataclass
class Ada15mParams:
    """Strategy parameters for ADA 15m agent."""
    # Edge thresholds (from profile or override)
    min_edge_early: float = 0.05
    min_edge_mid: float = 0.04
    min_edge_late: float = 0.03
    min_edge_terminal: float = 0.02
    
    # Position sizing (from profile or override)
    max_position_size_pct: float = 0.02  # 2% of capital
    max_crypto_exposure_pct: float = 0.10  # 10% of capital
    
    # Risk parameters (from profile - DO NOT hardcode)
    # These are loaded from profile via to_agent_overrides()
    # drawdown_halt_pct: 0.10
    # drawdown_unwind_pct: 0.15
    # max_daily_loss_usd: 200.0

@dataclass
class Ada15mAgentSpec:
    """Complete agent specification for ADA_15M."""
    inputs: Ada15mInputs
    params: Ada15mParams
    
    def generate_signal(self) -> float:
        """Generate trading signal (-1 to 1)."""
        # Implement your signal generation logic here
        # This is a placeholder - replace with actual strategy
        signal = (self.inputs.social_sentiment + self.inputs.news_sentiment) / 2
        return signal
    
    def should_trade_ada_15m(self, inputs: Ada15mInputs, params: Ada15mParams) -> bool:
        """Determine if conditions are met to trade."""
        # Implement your entry conditions here
        edge = self.generate_signal()
        return abs(edge) >= params.min_edge_mid

# Risk rules class (delegates to canonical _prediction_risk.py)
class Ada15mRiskRules:
    """Risk rules for ADA_15M agent."""
    
    def __init__(self, profile_name: str = "kalshi_crypto_15m_v2"):
        self.profile_name = profile_name
    
    def check_drawdown(self, current_pnl: float, peak_equity: float) -> bool:
        """Check if trading allowed under drawdown limits.
        
        This delegates to the canonical _prediction_risk.py with profile gating.
        DO NOT implement custom drawdown logic here.
        """
        from merid.prediction.risk._prediction_risk import PredictionRiskConfig
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        # Load profile-driven limits
        adapter = get_active_profile()
        if not adapter:
            raise RuntimeError("Profile not available for risk check")
        
        profile = adapter.profile
        risk_config = PredictionRiskConfig(
            drawdown_halt_pct=profile.guardrails_drawdown_halt_pct,
            drawdown_unwind_pct=profile.guardrails_drawdown_unwind_pct,
            max_daily_loss_usd=profile.guardrails_max_daily_loss_usd,
        )
        
        # Use canonical check
        allowed, _ = risk_config.check_drawdown(current_pnl, peak_equity)
        return allowed
    
    def compute_fee(self, contracts: int, price_cents: int) -> int:
        """Compute fee for a trade.
        
        This delegates to the canonical fees.py.
        DO NOT implement custom fee logic here.
        """
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        return calculate_kalshi_fee_cents(contracts, price_cents)
```

**Key Requirements:**
- **DO NOT** hardcode drawdown limits - load from profile
- **DO NOT** implement custom fee calculation - use `calculate_kalshi_fee_cents()`
- **DO NOT** implement custom drawdown logic - use `_prediction_risk.py`
- Add docstring referencing canonical primitives
- Include comment that risk parameters come from profile

---

## Step 3: Create Agent Class

Create the agent class that implements the trading logic using the spec.

**Location:** `merid/agents/{asset}_15m_agent.py` (e.g., `merid/agents/ada_15m_agent.py`)

**Template:**
```python
"""
ADA 15m Trading Agent

This agent trades Kalshi 15-minute ADA prediction markets using the
strategy defined in config/ada_15m_agent_spec.py.

Canonical Risk Primitives:
- Fees: merid/event_venues/kalshi/fees.py
- Drawdown: merid/prediction/risk/_prediction_risk.py
- Profile: config/profiles/kalshi_crypto_15m.yaml
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from merid.agents.base_kalshi_agent import BaseKalshiAgent

@dataclass
class Ada15mAgentState:
    """Runtime state for ADA_15M agent."""
    last_signal: float = 0.0
    last_trade_time: Optional[float] = None
    consecutive_losses: int = 0

class Ada15mAgent(BaseKalshiAgent):
    """ADA 15m trading agent for Kalshi."""
    
    agent_id = "ada_15m_regime"
    product = "ada_15m"
    
    def __init__(
        self,
        market_registry,
        crypto_rti_monitor,
        portfolio_risk_agent,
    ):
        super().__init__(
            market_registry=market_registry,
            crypto_rti_monitor=crypto_rti_monitor,
            portfolio_risk_agent=portfolio_risk_agent,
        )
        
        # Load agent spec
        from config.ada_15m_agent_spec import Ada15mAgentSpec, Ada15mParams, Ada15mInputs
        from config.ada_15m_agent_spec import Ada15mRiskRules
        
        self.spec = Ada15mAgentSpec(
            inputs=Ada15mInputs(
                spot_price=0.0,
                order_book_imbalance=0.0,
                recent_trades_volume=0.0,
                social_sentiment=0.0,
                news_sentiment=0.0,
                rsi=50.0,
                macd=0.0,
                bollinger_position=0.0,
            ),
            params=Ada15mParams(),
        )
        
        self.risk_rules = Ada15mRiskRules()
        self.state = Ada15mAgentState()
    
    def generate_opinion(self, market_data: Dict[str, Any]) -> float:
        """Generate trading opinion for a market."""
        # Update inputs with market data
        self.spec.inputs.spot_price = market_data.get('spot_price', 0.0)
        self.spec.inputs.order_book_imbalance = market_data.get('order_book_imbalance', 0.0)
        # ... update other inputs
        
        # Generate signal
        signal = self.spec.generate_signal()
        self.state.last_signal = signal
        
        return signal
    
    def check_risk(self, current_pnl: float, peak_equity: float) -> bool:
        """Check if trading allowed under risk limits."""
        # Delegate to canonical risk rules
        return self.risk_rules.check_drawdown(current_pnl, peak_equity)
    
    def compute_trade_fee(self, contracts: int, price_cents: int) -> int:
        """Compute fee for a trade."""
        # Delegate to canonical fee calculation
        return self.risk_rules.compute_fee(contracts, price_cents)
```

**Key Requirements:**
- Inherit from `BaseKalshiAgent` for consistency
- Load profile-driven parameters via `to_agent_overrides()` if needed
- Delegate all risk checks to canonical primitives
- Delegate all fee calculations to `fees.py`

---

## Step 4: Add Agent to Grid

Add the new agent to the agent grid configuration.

**Location:** `config/kalshi_agent_grid.yaml`

**Add entry:**
```yaml
agents:
- name: ADA_15M
  enabled: true
  series_tickers:
  - KXADA15M  # Use 15M series ticker
  assets:
  - ADA
  timeframes:
  - 15m
  market_filter:
    category: crypto
    frequency: fifteen_min
  risk_limits:
    max_yes_position: 3  # From profile or override
    max_no_position: 3
    max_notional_usd: 0  # From profile
```

**Key Requirements:**
- Use 15M series ticker (e.g., KXADA15M, not KXADA)
- Set `risk_limits` to empty or 0 if using profile
- Profile will override these values via `to_agent_overrides()`

---

## Step 5: Add Profile Asset Config (if new profile)

If you created a new profile in Step 1B, add the asset configuration.

**Location:** `config/profiles/{profile_name}.yaml`

**Add to asset_configs:**
```yaml
asset_configs:
  ADA:
    max_notional_usd: 500.0
    min_edge_early: 0.05
    min_edge_mid: 0.04
    min_edge_late: 0.03
    min_edge_terminal: 0.02
```

---

## Step 6: Write Tests

Add tests to verify the strategy uses canonical primitives correctly.

**Location:** `tests/test_{asset}_15m_agent.py` (e.g., `tests/test_ada_15m_agent.py`)

**Template:**
```python
"""
Tests for ADA 15m agent.

Verifies:
1. Fee calculation uses canonical fees.py
2. Drawdown checks use canonical _prediction_risk.py
3. Profile overrides are applied correctly
"""

import pytest
from config.ada_15m_agent_spec import Ada15mAgentSpec, Ada15mRiskRules

def test_fee_calculation_uses_canonical():
    """Verify fee calculation delegates to fees.py."""
    risk_rules = Ada15mRiskRules()
    
    # Test various contract counts and prices
    test_cases = [
        (10, 50),   # Small trade
        (100, 50),  # Medium trade
        (1000, 50), # Large trade
    ]
    
    for contracts, price_cents in test_cases:
        fee = risk_rules.compute_fee(contracts, price_cents)
        
        # Verify fee is non-zero
        assert fee > 0, f"Fee should be non-zero for {contracts} contracts at {price_cents}¢"
        
        # Verify minimum 2¢ per contract
        assert fee >= 2 * contracts, f"Fee should be at least 2¢ per contract"

def test_drawdown_check_uses_canonical():
    """Verify drawdown check delegates to _prediction_risk.py."""
    risk_rules = Ada15mRiskRules()
    
    # Test various PnL scenarios
    test_cases = [
        (1000, 1000, True),   # No drawdown
        (950, 1000, True),    # 5% drawdown (below halt)
        (850, 1000, False),   # 15% drawdown (above halt)
    ]
    
    for pnl, peak, expected in test_cases:
        allowed = risk_rules.check_drawdown(pnl, peak)
        assert allowed == expected, f"Drawdown check failed for pnl={pnl}, peak={peak}"

def test_profile_overrides_applied():
    """Verify profile overrides are applied to agent config."""
    from merid.risk.profiles.crypto_15m_profile import get_active_profile
    
    adapter = get_active_profile()
    if not adapter:
        pytest.skip("Profile not available")
    
    overrides = adapter.to_agent_overrides(agent_name="ADA_15M")
    
    # Verify overrides contain expected keys
    assert 'max_notional_usd' in overrides
    assert 'max_orders_per_window' in overrides
    assert 'max_yes_position' in overrides
    
    # Verify values are non-zero
    assert overrides['max_notional_usd'] > 0
    assert overrides['max_orders_per_window'] > 0

def test_no_hardcoded_risk_parameters():
    """Verify agent spec does not hardcode risk parameters."""
    import re
    
    with open('config/ada_15m_agent_spec.py', 'r') as f:
        content = f.read()
    
    # Check for hardcoded drawdown values (e.g., 0.10, 0.15)
    # These should come from profile, not be hardcoded
    hardcoded_drawdown = re.search(r'drawdown.*=\s*0\.\d+', content)
    assert hardcoded_drawdown is None, "Drawdown should not be hardcoded"
    
    # Check for hardcoded fee rates (e.g., 0.07)
    hardcoded_fee = re.search(r'fee.*=\s*0\.0\d', content)
    assert hardcoded_fee is None, "Fee rate should not be hardcoded"
```

**Key Requirements:**
- Test fee calculation uses `fees.py`
- Test drawdown check uses `_prediction_risk.py`
- Test profile overrides are applied
- Test no hardcoded risk parameters

---

## Step 7: Run Validations

Run all startup validations to ensure the new agent is correctly configured.

```bash
# Run profile field validation
python -c "from merid.startup_validations import validate_15m_crypto_profile_fields; validate_15m_crypto_profile_fields()"

# Run profile restrictions validation
python -c "from merid.startup_validations import validate_15m_crypto_profile_restrictions; validate_15m_crypto_profile_restrictions()"

# Run CI check for canonical primitives
python scripts/check_risk_canonical_sources.py

# Run tests
pytest tests/test_ada_15m_agent.py
```

**Expected Output:**
- All validations pass
- No errors or warnings
- Tests pass

---

## Step 8: Deploy to Demo

Deploy the new agent to demo environment first for testing.

**Steps:**
1. Set environment variables:
   ```bash
   export MERID_PROFILE=kalshi_crypto_15m_v2  # or your custom profile
   export KALSHI_ENV=demo
   ```
2. Deploy code changes
3. Verify agent starts successfully
4. Monitor dashboard for:
   - Fee calculations (should match expected)
   - Drawdown behavior (should halt at correct threshold)
   - No alerts firing

**Validation:**
- Agent generates signals
- Orders are placed (if conditions met)
- Fees are recorded correctly
- Drawdown checks work as expected

---

## Step 9: Deploy to Production

After successful demo testing, deploy to production.

**Steps:**
1. Get final approval from risk team
2. Generate risk snapshot:
   ```bash
   python scripts/generate_risk_snapshot.py --output risk_snapshot_pre_deploy.json
   ```
3. Deploy code changes
4. Set production environment:
   ```bash
   export KALSHI_ENV=production
   ```
5. Verify startup logs show:
   - Profile loaded correctly
   - Risk parameters logged
   - No validation errors
6. Generate post-deploy snapshot:
   ```bash
   python scripts/generate_risk_snapshot.py --output risk_snapshot_post_deploy.json
   ```
7. Diff snapshots to ensure no unintended changes

**Validation:**
- Compare pre/post deploy snapshots
- Verify no parameter drift
- Monitor alerts for first 24 hours

---

## Step 10: Ongoing Monitoring

After deployment, monitor the agent using the dashboards defined in `docs/dashboard_requirements.md`.

**Key Metrics to Watch:**
- Fee spend vs notional (should match expected rate)
- Drawdown trajectory (should respect profile limits)
- Alert frequency (should be low for healthy agent)

**Review Cadence:**
- Daily: Check dashboards for anomalies
- Weekly: Review alert metrics and tune thresholds
- Monthly: Review profile parameters and adjust if needed

---

## Common Pitfalls

### Pitfall 1: Hardcoding Risk Parameters

**Problem:** Agent spec hardcodes drawdown limits or fee rates.

**Solution:** Load from profile via `to_agent_overrides()` or `_prediction_risk.py`.

**Detection:** CI check `scripts/check_risk_canonical_sources.py` will catch this.

### Pitfall 2: Using Wrong Series Ticker

**Problem:** Agent uses base series ticker (KXADA) instead of 15M ticker (KXADA15M).

**Solution:** Always use 15M series tickers for 15m agents.

**Detection:** Startup validation will check series availability.

### Pitfall 3: Implementing Custom Fee Logic

**Problem:** Agent implements its own fee calculation instead of using `fees.py`.

**Solution:** Always use `calculate_kalshi_fee_cents()` from `fees.py`.

**Detection:** CI check will catch duplicate fee implementations.

### Pitfall 4: Bypassing Profile Gating

**Problem:** Agent bypasses profile gating and uses hardcoded defaults.

**Solution:** Ensure profile is active and `to_agent_overrides()` is called.

**Detection:** Startup validation will check profile is loaded.

---

## Step 11: Pre-Trade Controls Checklist

Before enabling a new 15m-crypto agent in production, complete this pre-trade controls checklist to ensure all risk controls are in place and properly configured.

### Pre-Trade Controls Checklist

- [ ] **Profile-Driven Drawdown Limits**
  - [ ] Profile selected or created with required drawdown fields
  - [ ] `drawdown_halt_pct` configured (e.g., 10%)
  - [ ] `drawdown_unwind_pct` configured (e.g., 15%)
  - [ ] `max_daily_loss_usd` configured (e.g., $200)
  - [ ] Profile validation passes (`validate_15m_crypto_profile_fields()`)
  - [ ] Profile loaded correctly at startup (check logs)

- [ ] **Per-Order Notional Bounds**
  - [ ] `max_notional_usd` set in profile (e.g., $1000)
  - [ ] `max_yes_position` configured (e.g., 3 contracts)
  - [ ] `max_no_position` configured (e.g., 3 contracts)
  - [ ] Notional bounds enforced by `_prediction_risk.py` check_order()
  - [ ] Test: Attempt to place order above notional limit → should be rejected

- [ ] **Per-Timeframe Order/Volume Throttles**
  - [ ] `max_orders_per_window` configured (e.g., 10 orders)
  - [ ] `minutes_before_expiry` configured (e.g., 5 minutes)
  - [ ] `cutoff_minutes_before_expiry` configured (e.g., 2 minutes)
  - [ ] Throttling enforced by order router or risk layer
  - [ ] Test: Attempt to place orders faster than throttle → should be rate-limited

- [ ] **Fee Calculation Verification**
  - [ ] Agent uses `calculate_kalshi_fee_cents()` from `fees.py`
  - [ ] No custom fee implementation in agent code
  - [ ] CI check passes (`scripts/check_risk_canonical_sources.py`)
  - [ ] Test: Verify fee calculation for sample orders matches expected

- [ ] **Fat-Finger Limits**
  - [ ] Maximum single order size enforced (e.g., 1% of bankroll)
  - [ ] Maximum daily exposure enforced (e.g., 5% of capital)
  - [ ] Minimum order size enforced (e.g., 1 contract)
  - [ ] Test: Attempt to place order > max single order size → should be rejected

- [ ] **Kill-Switch Configuration**
  - [ ] Kill-switch mechanism tested for agent
  - [ ] Kill-switch can be triggered via API or environment variable
  - [ ] Test: Trigger kill-switch → agent stops trading immediately
  - [ ] Test: Verify agent respects kill-switch state

- [ ] **Market Filter Validation**
  - [ ] Agent configured with correct market filter (category: crypto, frequency: fifteen_min)
  - [ ] Series ticker correct (e.g., KXADA15M for 15m)
  - [ ] Test: Verify agent only trades in intended markets
  - [ ] Test: Verify agent rejects non-crypto or non-15m markets

- [ ] **Sentiment Isolation**
  - [ ] `enable_sentiment_execution: false` in profile
  - [ ] `sentiment_mode: "disabled"` in profile
  - [ ] Startup validation passes sentiment isolation check
  - [ ] Test: Verify agent does not use sentiment signals

- [ ] **Risk Snapshot Baseline**
  - [ ] Pre-deploy risk snapshot generated (`scripts/generate_risk_snapshot.py`)
  - [ ] Snapshot includes profile parameters and agent configuration
  - [ ] Snapshot stored for post-deploy comparison
  - [ ] Test: Verify snapshot contains expected data

- [ ] **Dashboard Configuration**
  - [ ] Agent added to fee dashboard monitoring
  - [ ] Agent added to drawdown dashboard monitoring
  - [ ] Alert rules configured for agent
  - [ ] Test: Verify dashboard shows agent data

### Pre-Trade Risk Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRE-TRADE RISK CONTROLS                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: Market Filter (First Line)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Category filter (crypto only)                         │   │
│  │ • Frequency filter (fifteen_min only)                   │   │
│  │ • Series ticker validation (KXADA15M, etc.)             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│  Layer 2: Fat-Finger Limits                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • Max single order size (1% of bankroll)               │   │
│  │ • Min order size (1 contract)                          │   │
│  │ • Max daily exposure (5% of capital)                  │   │
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
│  Layer 4: Fee Calculation (Canonical)                        │
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
│  Layer 6: Drawdown Enforcement (Profile-Driven)             │
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

### Approval Sign-Off

Before enabling the agent in production, obtain sign-off from:

- [ ] **Strategy Owner**: Confirms strategy logic and parameters
- [ ] **Risk Team**: Confirms risk controls are adequate
- [ ] **Operations Team**: Confirms monitoring and alerting configured
- [ ] **Engineering Team**: Confirms technical implementation correct

**Sign-Off Date:** _______________
**Approved By:** _______________

---

## Checklist

Use this checklist to ensure all steps are completed:

- [ ] Profile created or selected (Step 1)
- [ ] Agent spec created with canonical primitives (Step 2)
- [ ] Agent class created inheriting from BaseKalshiAgent (Step 3)
- [ ] Agent added to grid with correct series ticker (Step 4)
- [ ] Profile asset config added (if new profile) (Step 5)
- [ ] Tests written for fee/drawdown canonical usage (Step 6)
- [ ] Startup validations pass (Step 7)
- [ ] Demo deployment successful (Step 8)
- [ ] Production deployment approved (Step 9)
- [ ] Risk snapshots generated and compared (Step 9)
- [ ] Monitoring dashboards configured (Step 10)
- [ ] Ongoing monitoring plan in place (Step 10)
- [ ] Pre-trade controls checklist completed (Step 11)
- [ ] Pre-trade risk layer diagram reviewed (Step 11)
- [ ] Approval sign-off obtained (Step 11)

---

## References

- `docs/risk_primitives.md` - Canonical primitives documentation
- `config/profiles/kalshi_crypto_15m_template.yaml` - Profile template
- `scripts/check_risk_canonical_sources.py` - CI check for canonical primitives
- `scripts/generate_risk_snapshot.py` - Risk snapshot generator
- `docs/dashboard_requirements.md` - Dashboard requirements
- `docs/alert_rules.md` - Alert rules

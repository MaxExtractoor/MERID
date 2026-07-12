# Risk Parameter Untangling Solution

**Date:** 2026-06-28  
**Based on:** Web research and audit findings

---

## Research Summary

### Key Best Practices Identified

1. **Single Source of Truth Pattern**
   - Risk management as platform-level service independent of strategy logic
   - YAML-based configuration for rules (separates strategy from risk logic)
   - Guardian Class pattern: deterministic gatekeeper between AI and broker
   - Two-phase execution: Suggest (probabilistic) → Approve (deterministic)

2. **Pre-Trade Risk Engine Architecture**
   - Single chokepoint: no bypass path to exchange
   - Inline risk checks (not separate microservice)
   - Cheap checks first (constant bounds before state-dependent)
   - Fail-closed behavior: reject if state is stale
   - Multi-scope kill switches (per-strategy, per-desk, firm-wide)

3. **Deterministic Configuration**
   - No implicit defaults
   - All configuration must be explicit
   - Configuration must be validated during INIT
   - No configuration changes at runtime
   - Paper mode and live mode strictly separated

---

## Solution Design

### Current State Analysis

The MERID codebase has:
- **Profile YAML** (kalshi_crypto_15m_v2.yaml): Claims to be single source of truth
- **core.settings.py**: Has different defaults with environment variable overrides
- **Deprecated guards**: GlobalRiskGuard, GlobalExecutionGuard with conflicting values
- **UnifiedRiskManager**: Has different defaults, loads from separate config file
- **RiskGuard**: Core service with defaults set to 0

### Root Cause

The system lacks a clear configuration hierarchy. Multiple components can load risk parameters from different sources, and it's unclear which values are actually used at runtime.

### Recommended Solution

#### Phase 1: Establish Clear Hierarchy (Do This First)

**Decision:** Profile YAML is the single source of truth for 15m Kalshi production.

**Rationale:**
- Profile YAML is already the most comprehensive configuration
- It's specifically designed for the 15m Kalshi system
- It has detailed per-asset configuration
- It's already being used by Crypto15mProfileAdapter

**Implementation:**

1. **Make core.settings.py defer to profile YAML for 15m Kalshi**
   - Remove hardcoded defaults for risk parameters when MERID_PROFILE=kalshi_crypto_15m_v2
   - Add logic to read from profile YAML when profile is active
   - Keep environment variable overrides only for non-15m profiles

2. **Add startup validation**
   - Call unified_risk_enforcement.enforce_at_startup() in main_15m_lean.py
   - Detect mismatches between profile YAML and core.settings
   - Fail fast if critical discrepancies are detected

#### Phase 2: Remove Deprecated Components

**Decision:** Remove or clearly deprecate unused risk guard components.

**Implementation:**

1. **GlobalRiskGuard**
   - Add clear deprecation warning at module level
   - Log warning if instantiated
   - Document that it should not be used in production

2. **GlobalExecutionGuard**
   - Add clear deprecation warning at module level
   - Log warning if instantiated
   - Document that it should not be used in production

3. **TradingGuard**
   - Add clear comment that it's not used by Kalshi 15m
   - Document its intended use case (legacy unified trading suite)

4. **RiskGuard**
   - Add clear comment about its status
   - Determine if it's used by 15m stack
   - If not used, deprecate

#### Phase 3: Align Parameter Values

**Decision:** Align all components to use profile YAML values.

**Critical Parameters to Align:**

1. **max_cycle_risk_pct**
   - Profile YAML: 0.5% (0.005)
   - core.settings: 3% (0.03) → **CHANGE to read from profile**
   - UnifiedRiskManager: 25% (0.25) → **CHANGE default to 0.5%**
   - unified_risk_enforcement: 2% (0.02) → **CHANGE to 0.5%**

2. **drawdown_halt_pct**
   - Profile YAML: 20% (0.20)
   - core.settings: 10% (0.10) → **CHANGE to read from profile**
   - RiskGuard: 10% (0.10) → **CHANGE default to 20%**
   - UnifiedRiskManager: 10% (0.10) → **CHANGE default to 20%**

3. **per_trade_risk_pct**
   - Profile YAML: 2% (0.02)
   - unified_risk_enforcement: 1% (0.01) → **CHANGE to 2%**
   - UnifiedRiskManager: 5% (0.05) → **CHANGE default to 2%**

4. **max_daily_loss_pct**
   - Profile YAML: 5% (0.05)
   - core.settings: 5% (0.05) → **ALREADY ALIGNED**
   - UnifiedRiskManager: 3% (0.03) → **CHANGE default to 5%**

#### Phase 4: Resolve Internal Profile Inconsistencies

**Decision:** Unify conflicting values within the same profile YAML.

**Inconsistencies to Resolve:**

1. **Spread limits**
   - universe.max_spread_cents: 10
   - guardrails.max_spread_cents: 50
   - momentum_fvg.spread_gate_cents: 50
   - **Solution:** Use 50c everywhere (aligns with guardrails and momentum_fvg)

2. **Depth thresholds**
   - Per-asset min_depth_yes: 1
   - guardrails.min_depth_contracts: 2
   - guardrails tiered: Tier 1: 2, Tier 2: 1
   - **Solution:** Use per-asset values (1 contract) - this is the most specific

3. **Contract limits**
   - Per-asset max_contracts: 2
   - contract_caps.max_single_order_contracts: 10
   - failsafe.max_contracts_per_order: 1
   - **Solution:** Use per-asset values (2 contracts) for normal, failsafe (1) for emergency

#### Phase 5: Improve Determinism

**Decision:** Remove or clearly document non-deterministic features.

**Non-Deterministic Features:**

1. **Bankroll-tiered dynamic sizing**
   - **Action:** Keep but document clearly as intentional feature
   - Add logging when tier changes

2. **Adaptive risk bands**
   - **Action:** Keep but document clearly as intentional feature
   - Add logging when band changes

3. **Operation mode switching**
   - **Action:** Keep but validate at startup
   - Fail if operation_mode is not valid

4. **Environment variable overrides**
   - **Action:** Remove for critical risk parameters when profile is active
   - Keep only for non-15m profiles

---

## Implementation Plan

### Step 1: Update core.settings.py

```python
# Read from profile YAML when MERID_PROFILE=kalshi_crypto_15m_v2
if os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2":
    # Load from profile YAML instead of using defaults
    from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
    adapter = Crypto15mProfileAdapter()
    profile = adapter.load_profile()
    
    MAX_CYCLE_RISK_PCT = profile.max_cycle_risk_pct
    MAX_TOTAL_RISK_PCT = profile.max_total_risk_pct
    DAILY_LOSS_CAP_PCT = profile.guardrails_max_daily_loss_usd / profile.capital_usd if profile.capital_usd > 0 else 0.05
    DRAWDOWN_HALT_PCT = profile.guardrails_drawdown_halt_pct
    DRAWDOWN_UNWIND_PCT = profile.guardrails_drawdown_unwind_pct
else:
    # Use environment variable defaults for other profiles
    MAX_CYCLE_RISK_PCT = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.03"))
    MAX_TOTAL_RISK_PCT = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.06"))
    DAILY_LOSS_CAP_PCT = float(os.getenv("DAILY_LOSS_CAP_PCT", "0.05"))
    DRAWDOWN_HALT_PCT = float(os.getenv("DRAWDOWN_HALT_PCT", "0.10"))
    DRAWDOWN_UNWIND_PCT = float(os.getenv("DRAWDOWN_UNWIND_PCT", "0.15"))
```

### Step 2: Add Startup Validation in main_15m_lean.py

```python
from merid.config.unified_risk_enforcement import enforce_at_startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    
    # Enforce unified risk model
    enforce_at_startup()
    
    # ... rest of startup ...
```

### Step 3: Update unified_risk_enforcement.py

```python
# Change absolute caps to match profile YAML values
ABSOLUTE_MAX_CYCLE_RISK_PCT = 0.005  # 0.5% (aligned with profile)
ABSOLUTE_MAX_EDGES_PER_CYCLE = 3
ABSOLUTE_MAX_RISK_PER_TRADE_PCT = 0.02  # 2% (aligned with profile)
```

### Step 4: Update UnifiedRiskManager defaults

```python
@dataclass
class RiskLimits:
    """Risk limits loaded from config/risk_limits.yaml."""
    
    # Bankroll-based limits (aligned with profile YAML)
    max_cycle_risk_pct: float = 0.005  # 0.5% (was 0.25)
    max_total_risk_pct: float = 0.15  # 15% (was 0.30)
    daily_loss_pct: float = 0.05  # 5% (was 0.03)
    cluster_stop_pct: float = 0.025  # 2.5%
    
    # Drawdown limits (aligned with profile YAML)
    drawdown_halt_pct: float = 0.20  # 20% (was 0.10)
    drawdown_unwind_pct: float = 0.25  # 25% (was 0.15)
    
    # Per-trade limits (aligned with profile YAML)
    per_trade_max_notional_pct: float = 0.02  # 2% (was 0.05)
```

### Step 5: Add Deprecation Warnings

```python
# merid/guards/global_risk_guard.py
import warnings

warnings.warn(
    "GlobalRiskGuard is DEPRECATED. Use UnifiedRiskManager instead.",
    DeprecationWarning,
    stacklevel=2
)

# merid/guards/global_execution_guard.py
import warnings

warnings.warn(
    "GlobalExecutionGuard is DEPRECATED. Use UnifiedRiskManager instead.",
    DeprecationWarning,
    stacklevel=2
)
```

### Step 6: Resolve Profile YAML Inconsistencies

```yaml
# config/profiles/kalshi_crypto_15m_v2.yaml

# Unify spread limits
universe:
  max_spread_cents: 50  # Changed from 10 to align with guardrails

# Unify depth thresholds (remove guardrails min_depth_contracts)
guardrails:
  # min_depth_contracts: 2  # REMOVED - use per-asset values instead

# Clarify contract limits
contract_caps:
  max_single_order_contracts: 2  # Changed from 10 to align with per-asset
```

### Step 7: Add Tests

```python
# tests/test_risk_parameter_alignment.py

def test_core_settings_reads_from_profile():
    """Test that core.settings reads from profile YAML for 15m Kalshi."""
    os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
    import importlib
    import core.settings
    importlib.reload(core.settings)
    
    assert core.settings.MAX_CYCLE_RISK_PCT == 0.005
    assert core.settings.DRAWDOWN_HALT_PCT == 0.20

def test_unified_risk_manager_defaults_aligned():
    """Test that UnifiedRiskManager defaults align with profile."""
    from merid.risk.unified_risk_manager import RiskLimits
    limits = RiskLimits()
    
    assert limits.max_cycle_risk_pct == 0.005
    assert limits.drawdown_halt_pct == 0.20
    assert limits.per_trade_max_notional_pct == 0.02

def test_profile_yaml_internal_consistency():
    """Test that profile YAML has no internal inconsistencies."""
    from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
    adapter = Crypto15mProfileAdapter()
    profile = adapter.load_profile()
    
    # Check spread limits are consistent
    # Check depth thresholds are consistent
    # Check contract limits are consistent
```

---

## Risk Assessment

### Low Risk Changes
- Adding deprecation warnings
- Adding startup validation
- Updating comments and documentation

### Medium Risk Changes
- Changing UnifiedRiskManager defaults
- Changing unified_risk_enforcement absolute caps
- Resolving profile YAML internal inconsistencies

### High Risk Changes
- Changing core.settings.py to read from profile YAML
- This affects the entire system and needs thorough testing

### Mitigation Strategy
1. Implement changes incrementally
2. Add comprehensive tests before each change
3. Run tests in development environment first
4. Monitor logs closely after deployment
5. Have rollback plan ready

---

## Rollback Plan

If issues arise after deployment:

1. **Immediate rollback:** Revert core.settings.py changes
2. **Partial rollback:** Revert specific parameter changes
3. **Full rollback:** Revert all changes and restore previous state

Rollback commands:
```bash
git revert <commit-hash>
# Or restore from backup
```

---

## Success Criteria

1. All risk parameters have a single source of truth
2. No discrepancies between different components
3. Startup validation detects mismatches
4. Tests pass for all changes
5. Server starts without errors
6. Logs show correct risk parameters being used

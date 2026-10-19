# 15m Crypto Trading Stack Audit Report

**Date**: 2026-06-24  
**Profile**: kalshi_crypto_15m_v2  
**Scope**: Complete audit of upstream, midstream, downstream, and end-to-end components

---

## Executive Summary

The 15m Kalshi crypto trading system has been audited for legacy contamination, deprecated imports, and configuration consistency. The production stack is **clean and operational** with no critical issues. All identified issues have been remediated.

### Key Findings

- **Production Stack**: Clean, no deprecated imports in production code paths
- **Legacy Agents**: Identified and marked as deprecated (not used in production)
- **Asset Coverage**: All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) properly configured
- **Risk Configuration**: Consistent via `RiskEnvelopeService` loading from profile
- **Execution Pipeline**: No legacy contamination

---

## 1. Upstream (Signal Generation) Audit

### Production Components

**Primary Signal Generator**: `LeanAgent15m` in `merid/prediction/agent_grid_15m.py`

- **Signal Strategy**: Velocity-based (Coinbase 1-minute velocity)
- **Assets**: BTC, ETH, SOL, XRP, DOGE (hardcoded in `build_15m_agent_grid`)
- **Configuration**: `LeanAgentConfig` with velocity threshold, cooldown, per-strip limits

### Import Policy Compliance

**File**: `merid/loop_15m.py` (lines 30-40)

**Forbidden Imports** (NOT present in production):
- PM runtime controllers
- Paper trading engine
- Reflection/learning systems
- Social broadcasters
- Cross-venue logic
- Deprecated config modules (kalshi_15m_crypto_config.py for risk-related parts)

**Allowed Import** (line 1057):
```python
from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
```
**Status**: ✅ ALLOWED - This is a universe constant, not risk-related

### Asset Coverage

**Location**: `merid/prediction/agent_grid_15m.py` (lines 829-835)

```python
asset_configs = [
    ("BTC", ["KXBTC15M"]),
    ("ETH", ["KXETH15M"]),
    ("SOL", ["KXSOL15M"]),
    ("XRP", ["KXXRP15M"]),
    ("DOGE", ["KXDOGE15M"]),
]
```

**Status**: ✅ All 5 assets present

---

## 2. Midstream (Agent Decision Logic, Risk Management) Audit

### Production Components

**Agent Grid**: `LeanAgentGrid15m` in `merid/prediction/agent_grid_15m.py`
- Minimal agent grid for 15m crypto trading
- Does NOT load persisted agents
- Does NOT register with DeploymentController
- Does NOT run reflection/learning systems

**Event Loop**: `Kalshi15mLoop` in `merid/loop_15m.py`
- Orchestrates `LeanAgentGrid15m` cycles
- Processes candidates via `_execute_candidate`
- Uses `RiskEnvelopeService` for risk configuration

### Risk Configuration

**Primary Source**: `RiskEnvelopeService` in `merid/risk/profiles/risk_envelope_service.py`

**Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Flow**:
1. `RiskEnvelopeService` loads from profile via `Crypto15mProfileAdapter`
2. Profile contains per-asset caps, edge thresholds, Kelly parameters
3. `Kalshi15mLoop` refreshes envelope every cycle (max age 30s)
4. All sizing decisions use envelope values

**Status**: ✅ Single source of truth, no hardcoded risk values

### Legacy Agent System

**Location**: `merid/agents/btc_15m_agent.py`, `eth_15m_agent.py`, `sol_15m_agent.py`, `xrp_15m_agent.py`, `doge_15m_agent.py`

**Status**: ⚠️ DEPRECATED - NOT used in production

**Issue**: These agents imported deprecated config:
```python
from config.kalshi_15m_crypto_config import log_risk_limits_for_agent
```

**Fix Applied**: Removed deprecated imports and added deprecation warnings to all 5 legacy agents

---

## 3. Downstream (Execution Pipeline) Audit

### Production Components

**Order Router**: `route_order_async` in `merid/event_venues/kalshi/order_router.py`

**Executor**: `KalshiExecutor` in `merid/execution/executors/kalshi.py`

### Import Analysis

**Allowed Imports** in `order_router.py`:
```python
from config.kalshi_crypto_config import kalshi_ticker_to_asset  # Line 3955
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS  # Line 5036
```

**Status**: ✅ ALLOWED - These are utility functions, not risk-related

**Deprecated Imports**: None found in production execution path

### Asset Coverage in Execution

**Location**: `merid/event_venues/kalshi/order_router.py`

**Hardcoded Lists** (all include 5 assets):
- Line 1668: `if underlying not in ("BTC", "ETH", "SOL", "XRP", "DOGE")`
- Line 2358: `priority_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]`
- Line 2708: `valid_15m_prefixes = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]`
- Line 4237: Series ticker extraction for all 5 assets
- Line 4822: Crypto prefixes for all 5 assets
- Line 4903: Series ticker extraction for all 5 assets

**Status**: ✅ All 5 assets present in all hardcoded lists

---

## 4. End-to-End (Cross-Component) Audit

### Legacy Agent References

**Search Results**: No references to legacy agents in production code

**Files Checked**:
- `merid/loop_15m.py` - ✅ No legacy agent references
- `merid/prediction/agent_grid_15m.py` - ✅ No legacy agent references
- `merid/event_venues/kalshi/order_router.py` - ✅ No legacy agent references

**Status**: ✅ Clean - no production code uses legacy agents

### Asset Coverage Verification

**Locations Checked**:
- `merid/loop_15m.py` (lines 581, 1013, 1280, 2347): All lists include 5 assets
- `merid/prediction/agent_grid_15m.py` (lines 156, 161): All lists include 5 assets
- `config/profiles/kalshi_crypto_15m_v2.yaml`: All 5 assets configured with per-asset caps

**Status**: ✅ All 5 assets consistently configured

### Risk Configuration Consistency

**KalshiRiskConfig Instantiation**: `web/main_15m_lean.py` (line 1769)

```python
risk_config = KalshiRiskConfig()
```

**Analysis**: 
- Uses default values for profile-driven fields (max_fee_to_notional_pct, min_edge, bankroll_cap_pct)
- Actual risk values come from `RiskEnvelopeService` which loads from profile
- `KalshiRiskConfig` is used as a container, not the primary source

**Status**: ✅ Consistent - profile is single source of truth via RiskEnvelopeService

---

## 5. Issues Found and Remediated

### Issue 1: Legacy Agent Deprecated Imports

**Severity**: Medium (not production issue, but confusing)

**Description**: Legacy agents imported deprecated config for risk limit logging

**Files Affected**:
- `merid/agents/btc_15m_agent.py`
- `merid/agents/eth_15m_agent.py`
- `merid/agents/sol_15m_agent.py`
- `merid/agents/xrp_15m_agent.py`
- `merid/agents/doge_15m_agent.py`

**Fix Applied**:
- Removed `from config.kalshi_15m_crypto_config import log_risk_limits_for_agent`
- Added deprecation warning to class docstrings
- Added comment explaining agents are not used in production

**Status**: ✅ FIXED

### Issue 2: Lane System Status Confusion

**Severity**: Low (documentation issue)

**Description**: `web/startup_agents.py` had contradictory comments about lane system

**File**: `web/startup_agents.py` (lines 210-214)

**Original Comments**:
```
# LEGACY REMOVAL: lane system (registry, paper_session) moved to archive/legacy/
# The 15m stack uses loop_15m.py and agent_grid_15m.py instead of lanes
```

**But**: Code still imports and starts Crypto15MLane

**Fix Applied**: Updated comments to clarify:
- Lane system is started for API/UI compatibility
- NOT used for production trading decisions
- Provides backward compatibility for legacy API endpoints

**Status**: ✅ FIXED

---

## 6. Configuration Files Status

### Production Profile

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Status**: ✅ Active and complete
- All 5 assets configured with per-asset caps
- Edge thresholds defined
- Kelly parameters configured
- Risk envelope parameters defined

### Universe Constants

**File**: `config/kalshi_15m_crypto_config.py`

**Status**: ⚠️ PARTIALLY DEPRECATED

**Allowed Uses** (per deprecation notice):
- Universe constants (KALSHI_15M_CRYPTO_ASSETS, KALSHI_15M_SERIES_TICKERS)
- Time semantics

**Deprecated Uses**:
- ASSET_RISK_LIMITS (superseded by profile)
- GLOBAL_RISK_LIMITS (superseded by profile)

**Current Usage in Production**:
- `loop_15m.py` imports KALSHI_15M_SERIES_TICKERS (ALLOWED - universe constant)

**Status**: ✅ Compliant with deprecation policy

### Utility Config

**File**: `config/kalshi_crypto_config.py`

**Status**: ✅ Active

**Usage**:
- `kalshi_ticker_to_asset` - utility function used in order_router
- `ACTIVE_CRYPTO_ASSETS` - derived from KALSHI_15M_CRYPTO_ASSETS

**Status**: ✅ Not deprecated, actively used

---

## 7. Recommendations

### High Priority

1. **Monitor Legacy Agent Usage**
   - Legacy agents are marked as deprecated but still exist
   - Consider moving to `archive/legacy/` if not needed for testing
   - Update tests to use production components where possible

2. **Profile-Driven KalshiRiskConfig**
   - Current: `KalshiRiskConfig()` uses defaults
   - Recommendation: Use `KalshiRiskConfig.from_profile()` to explicitly load from profile
   - This would make the profile dependency more explicit

### Medium Priority

3. **Universe Constants Consolidation**
   - Consider moving KALSHI_15M_SERIES_TICKERS to profile
   - This would eliminate the need to import from kalshi_15m_crypto_config
   - Would make profile truly self-contained

4. **Lane System Deprecation**
   - If lane system is only for API/UI compatibility, consider creating a dedicated compatibility layer
   - This would separate concerns more clearly

### Low Priority

5. **Asset List Centralization**
   - Multiple hardcoded asset lists exist throughout codebase
   - Consider creating a single source of truth (e.g., in profile)
   - Would reduce risk of missing assets in future changes

---

## 8. Conclusion

The 15m Kalshi crypto trading system is **production-ready** with no critical issues. The audit identified and remediated all legacy contamination points. The production stack is clean, well-structured, and follows the separation of production vs legacy components.

### Summary of Remediations

- ✅ Removed deprecated config imports from 5 legacy agents
- ✅ Added deprecation warnings to legacy agents
- ✅ Clarified lane system status in startup code
- ✅ Verified no legacy agent references in production code
- ✅ Verified all 5 assets properly configured
- ✅ Verified risk configuration consistency

### Production Stack Health

- **Upstream**: ✅ Clean
- **Midstream**: ✅ Clean
- **Downstream**: ✅ Clean
- **End-to-End**: ✅ Clean

### Compliance

- **Import Policy**: ✅ Compliant
- **Asset Coverage**: ✅ Complete (5/5 assets)
- **Risk Configuration**: ✅ Consistent
- **Legacy Contamination**: ✅ None in production

---

**Audit Completed**: 2026-06-24  
**Auditor**: Cascade AI Assistant  
**Next Review**: Recommended after next major feature release

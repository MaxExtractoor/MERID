# 15M Crypto Setup Inconsistency Audit Report

**Date**: 2026-07-04  
**Profile**: kalshi_crypto_15m_v2  
**Purpose**: Identify and fix inconsistencies between setup documentation and actual code implementation

---

## Executive Summary

This audit identifies hardcoded values, legacy imports, and configuration bypasses that conflict with the single source of truth (kalshi_crypto_15m_v2 profile). All inconsistencies must be fixed to ensure the production 15m stack uses the documented configuration.

---

## Critical Inconsistencies Found

### 1. Legacy Config Imports (HIGH PRIORITY)

**Issue**: `kalshi_15m_crypto_config.py` is marked as deprecated but still imported in production code

**Files with problematic imports**:
- `merid/loop_15m.py:1761` - `from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS`
- `merid/startup_validations.py:367,546,1593` - Multiple imports of KALSHI_15M_SERIES_TICKERS
- `merid/event_venues/kalshi/market_catalog.py:1270,2892` - Imports of KALSHI_15M_SERIES_TICKERS
- `merid/event_venues/kalshi/health_snapshot.py:321` - Import of KALSHI_15M_SERIES_TICKERS
- `merid/config/signature.py:51,61` - Imports from kalshi_15m_crypto_config

**Impact**: Risk of using deprecated risk limits and configuration values instead of profile

**Fix Required**: Replace with profile-based configuration or create a clean series ticker source

---

### 2. Hardcoded Edge Thresholds (HIGH PRIORITY)

#### 2.1 merid/risk/risk_profile.py

**Issue**: Hardcoded min_edge_bps=75 (0.75%) conflicts with profile edge bands (4-7%)

**Location**: `merid/risk/risk_profile.py:87-95`

**Current Code**:
```python
min_edge_bps: int = 75  # 0.75%
min_edge_by_phase: Dict[str, int] = field(default_factory=lambda: {
    "early": 120,      # > 24h to expiry
    "mid": 75,         # 4-24h
    "late": 60,        # 1-4h
    "terminal": 100,   # < 1h
})
```

**Profile Edge Bands** (from kalshi_crypto_15m_v2.yaml):
- Watch band: 4-5% edge
- Small band: 5-7% edge
- Standard band: >=7% edge

**Conflict**: 0.75% is far below the 4% minimum documented in profile

**Fix Required**: Profile-gate this module for kalshi_crypto_15m_v2, or align with profile thresholds

---

#### 2.2 merid/swarm/orchestrator.py

**Issue**: Hardcoded MIN_EDGE_BPS=10.0 (0.10%) conflicts with profile thresholds

**Location**: `merid/swarm/orchestrator.py:12`

**Current Code**:
```python
MIN_EDGE_BPS = 10.0  # 0.10%
```

**Profile Edge Bands**: 4-7% minimum

**Conflict**: 0.10% is far below the 4% minimum documented in profile

**Fix Required**: Profile-gate this constant for kalshi_crypto_15m_v2

---

#### 2.3 merid/trading/top3_edge_allocator.py

**Issue**: Hardcoded min_edge1_pct=0.01 (1%) conflicts with profile edge bands

**Location**: `merid/trading/top3_edge_allocator.py:327`

**Current Code**:
```python
min_edge1_pct = 0.01  # 1% minimum for Edge #1
```

**Profile Edge Bands**: 4-7% minimum

**Conflict**: 1% is below the 4% minimum documented in profile

**Fix Required**: Profile-gate this threshold for kalshi_crypto_15m_v2

---

### 3. Risk Limit Conflicts (HIGH PRIORITY)

#### 3.1 merid/settings.py - Portfolio Notional Cap

**Issue**: KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT=0.50 (50%) conflicts with profile 25% total notional cap

**Location**: `merid/settings.py:754`

**Current Code**:
```python
KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT: float = Field(
    default=0.50, 
    description="DEPRECATED - use MAX_TOTAL_RISK_PCT from core.settings"
)
```

**Profile Value**: 25% total notional cap (5% per asset × 5 assets)

**Conflict**: 50% is double the documented 25% cap

**Status**: Marked as DEPRECATED but still may be used by legacy code paths

**Fix Required**: Ensure all code paths use profile value, not this deprecated setting

---

#### 3.2 merid/settings.py - Contract Caps

**Issue**: MAX_CONTRACTS_PER_TF_CRYPTO_15M marked as deprecated but still exists

**Location**: `merid/settings.py:787-790`

**Current Code**:
```python
MAX_CONTRACTS_PER_TF_CRYPTO_15M: int = Field(
    default=0,
    description="Max contracts per 15m timeframe (0 = derive from bankroll: 1 per $50)"
)
```

**Profile Values**:
- BTC: 2 contracts
- ETH: 2 contracts
- SOL: 2 contracts
- XRP: 2 contracts
- DOGE: 1 contract

**Status**: Marked as DEPRECATED for kalshi_crypto_15m_v2 profile

**Fix Required**: Ensure profile per-asset max_contracts are used instead

---

### 4. Hardcoded Contract Limits (MEDIUM PRIORITY)

#### 4.1 merid/risk/unified_risk_manager.py

**Issue**: Hardcoded per_trade_max_contracts=2 may conflict with per-asset profile values

**Location**: `merid/risk/unified_risk_manager.py:82`

**Current Code**:
```python
per_trade_max_contracts: int = 2  # CRITICAL FIX: Aligned with profile per-asset max_contracts (was 10)
```

**Profile Values**:
- BTC: 2 contracts ✓ (aligned)
- ETH: 2 contracts ✓ (aligned)
- SOL: 2 contracts ✓ (aligned)
- XRP: 2 contracts ✓ (aligned)
- DOGE: 1 contract ✗ (conflict - DOGE should be 1)

**Conflict**: DOGE max_contracts=1 in profile, but hardcoded limit is 2

**Fix Required**: Make this value profile-aware or align with most restrictive value (1)

---

## Additional Concerns

### 5. Environment Variable Overrides

**Issue**: Multiple environment variables can override profile settings

**Variables Found**:
- `MERID_PROFILE` - Controls which profile is active
- `MERID_KALSHI_15M_STALE_MS` - Can override staleness thresholds
- `MERID_KALSHI_15M_MISSING_MS` - Can override missing data thresholds
- `KALSHI_ENV` - Controls live/demo mode
- `KALSHI_USE_DEMO` - Controls demo mode
- `MERID_EXEC_GATE_REQUIRE_KALSHI_WS` - Controls WS requirement gate

**Risk**: Environment variables can silently override documented profile values

**Fix Required**: Document all environment variable overrides and ensure they respect profile gating

---

## Fix Priority Matrix

| Priority | Issue | Impact | Complexity |
|----------|-------|--------|------------|
| P0 | Legacy config imports (kalshi_15m_crypto_config) | HIGH - Risk of using wrong config | MEDIUM |
| P0 | Edge threshold conflicts (0.75%, 0.10%, 1% vs 4-7%) | HIGH - Wrong signal generation | LOW |
| P1 | Portfolio notional cap conflict (50% vs 25%) | HIGH - Risk overexposure | LOW |
| P1 | Contract cap conflicts (DOGE: 2 vs 1) | MEDIUM - DOGE overexposure | LOW |
| P2 | Environment variable overrides | MEDIUM - Silent overrides | MEDIUM |

---

## Recommended Fix Strategy

### Phase 1: Critical Fixes (Immediate)

1. **Profile-gate edge threshold modules**:
   - Add MERID_PROFILE check in merid/risk/risk_profile.py
   - Add MERID_PROFILE check in merid/swarm/orchestrator.py
   - Add MERID_PROFILE check in merid/trading/top3_edge_allocator.py
   - When MERID_PROFILE=kalshi_crypto_15m_v2, use profile edge bands (4-7%)

2. **Replace legacy config imports**:
   - Create clean series ticker source in profile
   - Replace all kalshi_15m_crypto_config imports with profile-based source
   - Update merid/loop_15m.py, startup_validations.py, market_catalog.py, health_snapshot.py, signature.py

3. **Fix DOGE contract limit**:
   - Update merid/risk/unified_risk_manager.py per_trade_max_contracts to 1 for DOGE
   - Or make it profile-aware to respect per-asset differences

### Phase 2: Risk Limit Alignment (Short-term)

4. **Deprecate settings.py legacy values**:
   - Add runtime warnings when KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT is used
   - Add runtime warnings when MAX_CONTRACTS_PER_TF_CRYPTO_15M is used
   - Ensure profile values take precedence

5. **Document environment variable overrides**:
   - Create comprehensive env var documentation
   - Add validation to ensure env vars respect profile gating

### Phase 3: Change Log System (Ongoing)

6. **Create change log system**:
   - Document all deviations from 15M_CRYPTO_SETUP_DOCUMENTATION.md
   - Track which configurations work best in production
   - Maintain audit trail of all configuration changes

---

## Change Log Template

For each fix applied, document:

```markdown
## [Date] - [Component] Fix

**Issue**: [Description of inconsistency]

**File**: [File path]

**Change**: [Specific change made]

**Rationale**: [Why this change was needed]

**Profile Alignment**: [How this aligns with kalshi_crypto_15m_v2 profile]

**Testing**: [How this was tested]
```

---

## Next Steps

1. Implement Phase 1 fixes immediately
2. Test each fix with kalshi_crypto_15m_v2 profile
3. Document all changes in change log
4. Verify no regressions in other profiles
5. Update 15M_CRYPTO_SETUP_DOCUMENTATION.md if needed

---

## Audit Status

**Started**: 2026-07-04  
**Status**: IN PROGRESS  
**Next Review**: After Phase 1 fixes complete

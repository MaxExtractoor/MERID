# Paper vs Live Separation + Production Consolidation Audit

**Date:** 2026-05-13  
**Scope:** MERID ↔ Kalshi 15m crypto integration for BTC/ETH/SOL/XRP/DOGE  
**Profile:** `kalshi_crypto_15m_v2`  
**Focus:** Paper/live blending risks and production-only legacy consolidation

---

## 1. Environment Flags Table

| Flag | Values | Where Used | Effect | Classification |
|------|--------|------------|--------|----------------|
| `MERID_TRADE_MODE` | `live`, `paper`, `mock`, `sim`, `backtest` | `trading/trade_mode.py:_resolve_initial_mode()` | Legacy trade mode (fallback when PM mode not set) | Live/paper switch |
| `MERID_PM_TRADING_MODE` | `live`, `paper`, `mock`, `sim` | `trading/trade_mode.py:_resolve_initial_mode()` | Canonical prediction market trading mode | Live/paper switch |
| `MERID_ALLOW_LIVE_TRADES` | `true`, `false`, `1`, `0` | `trading/trade_mode.py`, `risk/kill_switches.py` | Safety gate: must be true for live mode | Safety gate |
| `MERID_PM_LIVE_ENABLED` | `true`, `false`, `1`, `0` | `trading/trade_mode.py:_resolve_initial_mode()` | PM-specific live enable flag | Safety gate |
| `KALSHI_ENV` | `demo`, `live`, `elections`, `unknown` | `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` | Kalshi environment selector (demo vs prod host) | Host selector |
| `KALSHI_USE_DEMO` | `true`, `false` | `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` | Legacy demo mode flag (overrides KALSHI_ENV) | Host selector |
| `KALSHI_API_BASE_URL` | Any URL string | `merid/strategies/kalshi_market_data.py`, various | Override Kalshi REST API base URL | Host selector |
| `KALSHI_API_HOST` | Any URL string | `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` | Override Kalshi API host (demo vs prod) | Host selector |
| `KALSHI_LIVE_API_KEY_ID` | API key string | `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` | Live-specific API key (when KALSHI_ENV=live) | Auth selector |
| `KALSHI_DEMO_API_KEY_ID` | API key string | `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` | Demo-specific API key (when KALSHI_ENV=demo) | Auth selector |

**Key Finding:** Two separate mode systems exist:
- `MERID_TRADE_MODE` / `MERID_PM_TRADING_MODE` + `MERID_ALLOW_LIVE_TRADES` → Application-level mode
- `KALSHI_ENV` / `KALSHI_USE_DEMO` → Kalshi-specific host selection

These are **NOT** centrally coordinated. This is a blending risk (see Section 2).

---

## 2. Paper–Live Blending Risks

### P0-1: Dual Mode Systems Not Centrally Coordinated

**Location:** 
- `trading/trade_mode.py` (application mode)
- `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` (Kalshi host selection)

**Description:**
Two independent mode systems determine paper vs live:
1. Application mode: `MERID_TRADE_MODE` or `MERID_PM_TRADING_MODE` (with `MERID_ALLOW_LIVE_TRADES` gate)
2. Kalshi host selection: `KALSHI_ENV` or `KALSHI_USE_DEMO`

**How it can blend:**
- `MERID_TRADE_MODE=live` + `KALSHI_USE_DEMO=true` → App thinks live, but Kalshi client hits demo host
- `MERID_TRADE_MODE=paper` + `KALSHI_ENV=live` → App thinks paper, but Kalshi client has live keys loaded

**What happens:**
- Orders could be sent to wrong environment (paper orders to live, live orders to demo)
- Risk limits calculated incorrectly (paper risk limits applied to live trading)
- PnL tracking corrupted (paper fills mixed with live fills)

**Current Mitigation:**
- `KalshiConfig.__post_init__()` has KALSHI_ENV-aware key selection (lines 180-210)
- Some consistency checks in tests (`tests/merid/test_startup_validations.py`)
- No production enforcement: no hard assertion that mode systems agree

**Severity:** P0  
**Fix:** Add hard assertion in `KalshiConfig.__post_init__()`:
```python
# After line 210 (end of KALSHI_ENV handling)
from trading.trade_mode import get_trade_mode
trade_mode = get_trade_mode()
if trade_mode == TradeMode.LIVE and self.use_demo:
    raise RuntimeError(
        "MODE_MISMATCH: TradeMode=LIVE but KalshiConfig.use_demo=True. "
        "Set KALSHI_USE_DEMO=false or KALSHI_ENV=live for live trading."
    )
if trade_mode == TradeMode.PAPER and not self.use_demo:
    raise RuntimeError(
        "MODE_MISMATCH: TradeMode=PAPER but KalshiConfig.use_demo=False (live host). "
        "Set KALSHI_USE_DEMO=true or KALSHI_ENV=demo for paper trading."
    )
```

---

### P0-2: KalshiClient Singleton Can Be Created in Wrong Mode

**Location:** `merid/event_venues/kalshi/client.py:get_kalshi_client()`

**Description:**
`get_kalshi_client()` is a singleton that creates `KalshiVenueClient` with the first `KalshiConfig` it receives. If called early in startup before mode is resolved, it may create a client with wrong host.

**How it can blend:**
- Client created with `use_demo=True` before `KALSHI_ENV` is read
- Singleton is reused for entire process lifetime
- All subsequent calls use wrong host

**Current Mitigation:**
- None explicitly in client creation
- Relies on correct environment setup before startup

**Severity:** P0  
**Fix:** Add mode validation in `get_kalshi_client()`:
```python
def get_kalshi_client(config: Optional[KalshiConfig] = None) -> KalshiVenueClient:
    global _client, _client_shutting_down
    if _client_shutting_down:
        raise RuntimeError("Cannot create KalshiVenueClient: shutdown in progress")
    if _client is None:
        with _client_lock:
            if _client_shutting_down:
                raise RuntimeError("Cannot create KalshiVenueClient: shutdown in progress")
            if _client is None:
                from trading.trade_mode import get_trade_mode
                trade_mode = get_trade_mode()
                
                # Validate config mode matches trade mode
                if config and config.use_demo and trade_mode == TradeMode.LIVE:
                    raise RuntimeError(
                        "MODE_MISMATCH: KalshiConfig.use_demo=True but TradeMode=LIVE. "
                        "Cannot create KalshiVenueClient with demo host in live mode."
                    )
                if config and not config.use_demo and trade_mode == TradeMode.PAPER:
                    raise RuntimeError(
                        "MODE_MISMATCH: KalshiConfig.use_demo=False (live host) but TradeMode=PAPER. "
                        "Cannot create KalshiVenueClient with live host in paper mode."
                    )
                
                import os as _os
                _rate_tier = _os.getenv("KALSHI_RATE_TIER", "basic")
                _client = KalshiVenueClient(config, rate_tier=_rate_tier)
                _client._is_singleton = True
    return _client
```

---

### P1-1: route_order() Rejects Live Mode But No Guardrail Prevents Call

**Location:** `merid/event_venues/kalshi/order_router.py:route_order()` (lines 2681-2936)

**Description:**
`route_order()` is a sync function that rejects live mode with "live_requires_async_route_order" error. However, there's no guardrail preventing it from being called in live mode.

**How it can blend:**
- Legacy code paths may still call `route_order()` in live mode
- Error is logged but order is rejected after risk checks run
- Risk checks consume resources for orders that will be rejected

**Current Mitigation:**
- Lines 2919-2934 reject with error message
- Comment says "Fail-loud: sync route_order() must never be called in live mode"

**Severity:** P1  
**Fix:** Add hard assertion at top of `route_order()`:
```python
def route_order(intent: OrderIntent) -> OrderResult:
    """Sync order routing (MOCK/PAPER only)."""
    from trading.trade_mode import get_trade_mode, assert_not_live
    assert_not_live("route_order() is sync-only; use route_order_async() for LIVE mode")
    
    # ... rest of function
```

---

### P1-2: simulate_paper_fill Has No Mode Check

**Location:** `merid/event_venues/kalshi/order_router.py:simulate_paper_fill()` (line 709)

**Description:**
`simulate_paper_fill()` generates simulated fills for paper trading. It has no explicit check that it's only called in paper/mock mode.

**How it can blend:**
- If accidentally called in live mode, would generate fake fills
- Fake fills could be ingested by fills_ledger
- Real PnL corrupted with simulated data

**Current Mitigation:**
- None explicitly
- Relies on caller to only call in paper mode

**Severity:** P1  
**Fix:** Add mode check:
```python
def simulate_paper_fill(intent: OrderIntent, _rng: Optional[random.Random] = None) -> dict:
    """Simulate a paper fill for MOCK/PAPER modes only."""
    from trading.trade_mode import get_trade_mode, assert_not_live
    assert_not_live("simulate_paper_fill() is for paper trading only")
    
    # ... rest of function
```

---

### P2-1: Legacy Bankroll Service Still Exported

**Location:** `merid/event_venues/kalshi/bankroll_service.py:KalshiBankrollService`

**Description:**
`KalshiBankrollService` (legacy) is still exported from `merid.event_venues.kalshi.__init__`. `BankrollServiceV2` is the canonical service.

**How it can blend:**
- If legacy service is accidentally imported and used, could return different bankroll values
- Risk limits calculated incorrectly
- Two different bankroll sources could diverge

**Current Mitigation:**
- Comment in `bankroll_service.py` line 102 says "Use BankrollServiceV2 instead"
- No enforcement

**Severity:** P2 (low risk, but confusing)  
**Fix:** Remove from `__init__.py` exports, add deprecation warning on import:
```python
# In merid/event_venues/kalshi/bankroll_service.py
import warnings
warnings.warn(
    "KalshiBankrollService is deprecated. Use BankrollServiceV2 instead.",
    DeprecationWarning,
    stacklevel=2
)
```

---

### P2-2: Legacy Reconciler Still Exported

**Location:** `merid/reconciliation/kalshi_reconciler.py:KalshiReconciler`

**Description:**
`KalshiReconciler` (legacy) is still exported from `merid.reconciliation.__init__`. `PortfolioReconciler` (event-sourced) is canonical.

**How it can blend:**
- If legacy reconciler runs, could produce different reconciliation results
- Confusion about which reconciler is source of truth

**Current Mitigation:**
- None explicitly

**Severity:** P2 (low risk, but confusing)  
**Fix:** Remove from `__init__.py` exports, add deprecation warning.

---

## 3. Production Legacy & Consolidation List

### Production-Reachable Modules (from main.py + kalshi_crypto_15m_v2 profile)

Starting from `main.py` and the `kalshi_crypto_15m_v2` profile, the production path uses:

**Canonical (Keep):**
- `trading/trade_mode.py` - TradeMode enum, get_trade_mode()
- `merid/event_venues/kalshi/models.py` - KalshiConfig (with KALSHI_ENV handling)
- `merid/event_venues/kalshi/client.py` - KalshiVenueClient, get_kalshi_client()
- `merid/event_venues/kalshi/order_router.py` - route_order_async(), simulate_paper_fill()
- `merid/event_venues/kalshi/bankroll_service_v2.py` - BankrollServiceV2 (canonical)
- `merid/event_venues/kalshi/portfolio_reconciliation.py` - PortfolioReconciler (canonical)
- `merid/event_venues/kalshi/position_cache.py` - KalshiPositionCache
- `merid/prediction/trading_agent.py` - KalshiTradingAgent (AgentGrid PM)
- `merid/prediction/agent_grid.py` - AgentGrid orchestrator

**Legacy (Remove or Migrate):**

| Module | Current Use | Action | Scope |
|--------|-------------|--------|-------|
| `merid/event_venues/kalshi/bankroll_service.py` | Exported but not used in production path | Remove from exports, add deprecation warning | Small (1 file) |
| `merid/reconciliation/kalshi_reconciler.py` | Exported but not used in production path | Remove from exports, add deprecation warning | Small (1 file) |
| `merid/trading/kalshi_continuous_trader.py` | Gated by `pm_ct_policy.ct_legacy_must_not_trade()` | Add hard assertion that it cannot run with `kalshi_crypto_15m_v2` profile | Large (6000+ lines) |
| `merid/trading/ct_profit_taking_integration.py` | CT-specific TP integration | Remove (CT should use canonical TakeProfitManager) | Small (1 file) |
| `merid/trading/ct_pnl_reconciler.py` | CT-specific PnL reconciliation | Remove (CT should use canonical PortfolioReconciler) | Small (1 file) |
| `merid/event_venues/kalshi/order_manager_enhanced.py` | Not used in production | Remove (dead code) | Small (1 file) |
| `merid/event_venues/kalshi/order_group_manager_enhanced.py` | Not used in production | Remove (dead code) | Small (1 file) |
| `merid/event_venues/kalshi/venue_adapter_enhanced.py` | Not used in production | Remove (dead code) | Small (1 file) |
| `merid/event_venues/kalshi/trading_enhanced.py` | Not used in production | Remove (dead code) | Small (1 file) |

**Note:** `KalshiContinuousTrader` is a special case. It's a complete trading engine (6000+ lines) that is currently gated by `pm_ct_policy.ct_legacy_must_not_trade()`. While suppressed, it represents a shadow execution path. The recommended action is to add a hard assertion in its `__init__` that raises if `MERID_PROFILE=kalshi_crypto_15m_v2` is set, preventing any accidental activation.

---

## 4. Guardrail Plan

### 4.1 Centralize Mode Handling

**Current State:** Mode logic is scattered across:
- `trading/trade_mode.py` (canonical TradeMode)
- `merid/event_venues/kalshi/models.py:KalshiConfig.__post_init__()` (KALSHI_ENV handling)
- Various ad-hoc checks throughout codebase

**Proposed Central Service:** Create `merid/mode_resolver.py`:

```python
from enum import Enum
from trading.trade_mode import TradeMode, get_trade_mode

class KalshiEnvironment(str, Enum):
    DEMO = "demo"
    LIVE = "live"
    ELECTIONS = "elections"

class ModeResolver:
    """Single source of truth for mode + environment resolution."""
    
    @staticmethod
    def is_live_trading() -> bool:
        return get_trade_mode() == TradeMode.LIVE
    
    @staticmethod
    def is_paper_trading() -> bool:
        return get_trade_mode() in (TradeMode.PAPER, TradeMode.MOCK)
    
    @staticmethod
    def get_kalshi_environment() -> KalshiEnvironment:
        import os
        kalshi_env = os.getenv("KALSHI_ENV", "").lower()
        if kalshi_env == "live":
            return KalshiEnvironment.LIVE
        elif kalshi_env == "demo":
            return KalshiEnvironment.DEMO
        elif kalshi_env == "elections":
            return KalshiEnvironment.ELECTIONS
        # Fallback to use_demo flag
        use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"
        return KalshiEnvironment.DEMO if use_demo else KalshiEnvironment.LIVE
    
    @staticmethod
    def assert_mode_consistency() -> None:
        """Hard assertion that TradeMode and Kalshi environment agree."""
        trade_mode = get_trade_mode()
        kalshi_env = ModeResolver.get_kalshi_environment()
        
        if trade_mode == TradeMode.LIVE and kalshi_env != KalshiEnvironment.LIVE:
            raise RuntimeError(
                f"MODE_MISMATCH: TradeMode=LIVE but Kalshi environment={kalshi_env.value}. "
                f"Set KALSHI_ENV=live for live trading."
            )
        if trade_mode == TradeMode.PAPER and kalshi_env == KalshiEnvironment.LIVE:
            raise RuntimeError(
                f"MODE_MISMATCH: TradeMode=PAPER but Kalshi environment={kalshi_env.value} (live host). "
                f"Set KALSHI_ENV=demo or KALSHI_USE_DEMO=true for paper trading."
            )
```

**Integration Points:**
- Call `ModeResolver.assert_mode_consistency()` in `main.py` startup
- Replace ad-hoc mode checks with `ModeResolver.is_live_trading()` / `is_paper_trading()`
- Add to startup validation checklist

---

### 4.2 Hard Assertions in Critical Paths

**Locations to add assertions:**

1. **KalshiConfig.__post_init__()** (after line 210):
```python
from merid.mode_resolver import ModeResolver
ModeResolver.assert_mode_consistency()
```

2. **get_kalshi_client()** (after line 1437):
```python
from merid.mode_resolver import ModeResolver
ModeResolver.assert_mode_consistency()
```

3. **route_order()** (at top of function):
```python
from merid.mode_resolver import ModeResolver
if ModeResolver.is_live_trading():
    raise RuntimeError("route_order() is sync-only; use route_order_async() for LIVE mode")
```

4. **simulate_paper_fill()** (at top of function):
```python
from merid.mode_resolver import ModeResolver
if ModeResolver.is_live_trading():
    raise RuntimeError("simulate_paper_fill() is for paper trading only")
```

5. **KalshiContinuousTrader.__init__()** (at top of function):
```python
if os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2":
    raise RuntimeError(
        "KalshiContinuousTrader is incompatible with kalshi_crypto_15m_v2 profile. "
        "Use KalshiTradingAgent (AgentGrid PM) instead."
    )
```

---

### 4.3 Must-Pass Tests

Add to `tests/test_mode_enforcement.py`:

**Test 1: Live mode cannot use demo host**
```python
def test_live_mode_rejects_demo_host():
    """Live mode must reject KalshiConfig with use_demo=True."""
    with patch.dict(os.environ, {
        "MERID_TRADE_MODE": "live",
        "MERID_ALLOW_LIVE_TRADES": "true",
        "KALSHI_USE_DEMO": "true"
    }, clear=True):
        with pytest.raises(RuntimeError, match="MODE_MISMATCH"):
            from merid.event_venues.kalshi.models import KalshiConfig
            KalshiConfig()
```

**Test 2: Paper mode cannot use live host**
```python
def test_paper_mode_rejects_live_host():
    """Paper mode must reject KalshiConfig with use_demo=False (live host)."""
    with patch.dict(os.environ, {
        "MERID_TRADE_MODE": "paper",
        "KALSHI_ENV": "live"
    }, clear=True):
        with pytest.raises(RuntimeError, match="MODE_MISMATCH"):
            from merid.event_venues.kalshi.models import KalshiConfig
            KalshiConfig()
```

**Test 3: Mode resolver consistency check**
```python
def test_mode_resolver_asserts_consistency():
    """ModeResolver.assert_mode_consistency() raises on mismatch."""
    with patch.dict(os.environ, {
        "MERID_TRADE_MODE": "live",
        "MERID_ALLOW_LIVE_TRADES": "true",
        "KALSHI_ENV": "demo"
    }, clear=True):
        with pytest.raises(RuntimeError, match="MODE_MISMATCH"):
            from merid.mode_resolver import ModeResolver
            ModeResolver.assert_mode_consistency()
```

**Test 4: CT blocked with kalshi_crypto_15m_v2 profile**
```python
def test_ct_blocked_with_crypto_15m_profile():
    """KalshiContinuousTrader must raise with kalshi_crypto_15m_v2 profile."""
    with patch.dict(os.environ, {"MERID_PROFILE": "kalshi_crypto_15m_v2"}, clear=True):
        with pytest.raises(RuntimeError, match="incompatible with kalshi_crypto_15m_v2"):
            from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
            KalshiContinuousTrader()
```

**Test 5: Paper-only functions reject live mode**
```python
def test_simulate_paper_fill_rejects_live_mode():
    """simulate_paper_fill() must reject live mode."""
    with patch.dict(os.environ, {
        "MERID_TRADE_MODE": "live",
        "MERID_ALLOW_LIVE_TRADES": "true"
    }, clear=True):
        with pytest.raises(RuntimeError, match="paper trading only"):
            from merid.event_venues.kalshi.order_router import simulate_paper_fill, OrderIntent
            simulate_paper_fill(OrderIntent(...))
```

---

## 5. Final Deliverables Summary

### Paper–Live Blending Risks

| Risk | Location | Severity | Fix |
|------|----------|----------|-----|
| Dual mode systems not coordinated | `trade_mode.py` + `KalshiConfig.__post_init__()` | P0 | Add hard assertion in `KalshiConfig.__post_init__()` |
| KalshiClient singleton can be created in wrong mode | `client.py:get_kalshi_client()` | P0 | Add mode validation in `get_kalshi_client()` |
| route_order() has no guardrail preventing live call | `order_router.py:route_order()` | P1 | Add `assert_not_live()` at top |
| simulate_paper_fill has no mode check | `order_router.py:simulate_paper_fill()` | P1 | Add `assert_not_live()` at top |
| Legacy bankroll service still exported | `bankroll_service.py` | P2 | Remove from exports, add deprecation warning |
| Legacy reconciler still exported | `kalshi_reconciler.py` | P2 | Remove from exports, add deprecation warning |

### Production Legacy & Consolidation List

| Module | Action | Scope |
|--------|--------|-------|
| `bankroll_service.py` | Remove from exports, add deprecation warning | Small |
| `kalshi_reconciler.py` | Remove from exports, add deprecation warning | Small |
| `kalshi_continuous_trader.py` | Add hard assertion for profile incompatibility | Large (gated) |
| `ct_profit_taking_integration.py` | Remove (use canonical TakeProfitManager) | Small |
| `ct_pnl_reconciler.py` | Remove (use canonical PortfolioReconciler) | Small |
| `order_manager_enhanced.py` | Remove (dead code) | Small |
| `order_group_manager_enhanced.py` | Remove (dead code) | Small |
| `venue_adapter_enhanced.py` | Remove (dead code) | Small |
| `trading_enhanced.py` | Remove (dead code) | Small |

### Guardrail Plan

**Immediate (Week 1):**
1. Create `merid/mode_resolver.py` with centralized mode resolution
2. Add `ModeResolver.assert_mode_consistency()` to `main.py` startup
3. Add hard assertions in `KalshiConfig.__post_init__()` and `get_kalshi_client()`
4. Add 5 must-pass tests to `tests/test_mode_enforcement.py`

**Short-term (Weeks 2-3):**
1. Replace ad-hoc mode checks with `ModeResolver.is_live_trading()` / `is_paper_trading()`
2. Add assertions to `route_order()`, `simulate_paper_fill()`, `KalshiContinuousTrader.__init__()`
3. Remove legacy exports and add deprecation warnings

**Long-term (Weeks 4-6):**
1. Remove dead code (enhanced modules)
2. Consolidate CT-specific code to use canonical services
3. Add mode consistency to CI pre-flight checklist

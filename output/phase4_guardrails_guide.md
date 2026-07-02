# Phase 4: Legacy Path Detection and Guardrails

This guide shows how to implement guardrails to prevent legacy code from being used in the kalshi_crypto_15m_v2 production profile.

---

## Step 1: Add Profile Guards to Legacy Modules

### Pattern 1: Hard Fail on Import

**For modules that should NEVER be imported in kalshi_crypto_15m_v2**:

Add this at the top of the file (immediately after imports):

```python
# PROFILE GUARD: This module is legacy and should not be used in kalshi_crypto_15m_v2
from merid.profile_resolver import is_kalshi_crypto_15m_v2

if is_kalshi_crypto_15m_v2():
    raise RuntimeError(
        "LEGACY module imported in kalshi_crypto_15m_v2 profile. "
        "This module is deprecated and should not be used in production. "
        f"Module: {__name__}"
    )
```

**Apply to these files**:
- `merid/prediction/agent_grid.py` (legacy agent grid)
- `merid/event_venues/kalshi/bankroll_service.py` (deprecated bankroll)
- `merid/loop.py` (legacy loop)
- `archive/legacy/agent_grid.py`
- `archive/legacy/trading_agent.py`
- `archive/legacy/crypto_15m_strategy.py`
- `archive/legacy/kalshi_continuous_trader.py`

### Pattern 2: Soft Fail with Warning

**For modules that should warn but not fail**:

```python
# PROFILE GUARD: This module is legacy and should not be used in kalshi_crypto_15m_v2
from merid.profile_resolver import is_kalshi_crypto_15m_v2
import logging

logger = logging.getLogger(__name__)

if is_kalshi_crypto_15m_v2():
    logger.warning(
        f"LEGACY module imported in kalshi_crypto_15m_v2 profile: {__name__}. "
        "This may cause unexpected behavior."
    )
```

---

## Step 2: Add Profile Guards to Legacy Classes

**For classes that should not be instantiated in kalshi_crypto_15m_v2**:

Add this in the `__init__` method:

```python
class KalshiBankrollService:
    """DEPRECATED: Use BankrollServiceV2 instead."""
    
    def __init__(self, *args, **kwargs):
        from merid.profile_resolver import is_kalshi_crypto_15m_v2
        
        if is_kalshi_crypto_15m_v2():
            raise RuntimeError(
                "KalshiBankrollService is deprecated and should not be used in "
                "kalshi_crypto_15m_v2 profile. Use BankrollServiceV2 instead."
            )
        
        # Existing initialization...
```

**Apply to**:
- `KalshiBankrollService.__init__` in `merid/event_venues/kalshi/bankroll_service.py`
- `KalshiVenueClient.__init__` in `merid/event_venues/kalshi/client.py` (if it should not be used)
- Any other deprecated class constructors

---

## Step 3: Add Profile Guards to Legacy Functions

**For functions that should not be called in kalshi_crypto_15m_v2**:

```python
def get_bankroll_service() -> KalshiBankrollService:
    """
    DEPRECATED: Use get_bankroll_service_v2() instead.
    
    This function is deprecated and will raise an error in kalshi_crypto_15m_v2 profile.
    """
    from merid.profile_resolver import is_kalshi_crypto_15m_v2
    
    if is_kalshi_crypto_15m_v2():
        raise RuntimeError(
            "get_bankroll_service() is deprecated in kalshi_crypto_15m_v2 profile. "
            "Use get_bankroll_service_v2() instead."
        )
    
    # Existing implementation...
```

**Apply to**:
- `get_bankroll_service()` in `merid/event_venues/kalshi/bankroll_service.py`
- Any other deprecated singleton getters

---

## Step 4: Create Centralized Legacy Module Registry

**File**: `merid/legacy_module_guard.py` (enhance existing if it exists)

```python
"""
Centralized legacy module guard for kalshi_crypto_15m_v2 profile.

This module maintains a registry of legacy modules and provides
utilities to detect and prevent their usage in production.
"""

import sys
import logging
from typing import Set, Dict, List
from merid.profile_resolver import is_kalshi_crypto_15m_v2

logger = logging.getLogger("legacy_module_guard")


# Registry of legacy modules that should not be imported in kalshi_crypto_15m_v2
LEGACY_MODULES: Set[str] = {
    "merid.prediction.agent_grid",  # Use agent_grid_15m instead
    "merid.loop",  # Use loop_15m instead
    "merid.event_venues.kalshi.bankroll_service",  # Use bankroll_service_v2 instead
    "merid.event_venues.kalshi.client",  # Use client_v2 instead (or verify this)
    "archive.legacy.agent_grid",
    "archive.legacy.trading_agent",
    "archive.legacy.crypto_15m_strategy",
    "archive.legacy.kalshi_continuous_trader",
    "archive.legacy.crypto_top_edge",
    "archive.legacy.strategies.sentiment_swarm_execution",
    "archive.legacy.strategies.kalshi_rate_limited_client",
    "archive.legacy.strategies.kalshi_ws",
    "legacy.lanes.btc15m_lane",
}

# Registry of deprecated classes
DEPRECATED_CLASSES: Dict[str, str] = {
    "KalshiBankrollService": "Use BankrollServiceV2 instead",
    "KalshiVenueClient": "Use KalshiClientV2 instead (verify this is correct)",
}

# Registry of deprecated functions
DEPRECATED_FUNCTIONS: Dict[str, str] = {
    "get_bankroll_service": "Use get_bankroll_service_v2 instead",
}


def check_legacy_modules_imported() -> Dict[str, List[str]]:
    """
    Check which legacy modules are currently imported.
    
    Returns:
        Dict with 'legacy_modules_loaded' list and 'legacy_count' int
    """
    if not is_kalshi_crypto_15m_v2():
        # Only check in production profile
        return {"legacy_modules_loaded": [], "legacy_count": 0}
    
    loaded_legacy = []
    
    for module_name in LEGACY_MODULES:
        if module_name in sys.modules:
            loaded_legacy.append(module_name)
            logger.warning(f"[LEGACY-GUARD] Legacy module imported: {module_name}")
    
    return {
        "legacy_modules_loaded": loaded_legacy,
        "legacy_count": len(loaded_legacy),
    }


def assert_no_legacy_modules(context: str = "") -> None:
    """
    Assert that no legacy modules are imported.
    
    Args:
        context: Additional context for error message
    
    Raises:
        RuntimeError: If any legacy modules are imported
    """
    if not is_kalshi_crypto_15m_v2():
        return
    
    result = check_legacy_modules_imported()
    
    if result["legacy_count"] > 0:
        error_msg = (
            f"Legacy modules detected in kalshi_crypto_15m_v2 profile: "
            f"{result['legacy_modules_loaded']}"
        )
        if context:
            error_msg += f" (context: {context})"
        
        logger.error(f"[LEGACY-GUARD] {error_msg}")
        raise RuntimeError(error_msg)


def get_legacy_module_report() -> Dict:
    """
    Get a report of legacy module usage.
    
    Returns:
        Dict with legacy module information
    """
    result = check_legacy_modules_imported()
    result["is_clean"] = result["legacy_count"] == 0
    result["profile"] = "kalshi_crypto_15m_v2" if is_kalshi_crypto_15m_v2() else "other"
    
    return result


def register_legacy_module(module_name: str, reason: str = "") -> None:
    """
    Register a module as legacy.
    
    Args:
        module_name: The module name to register
        reason: Reason why it's legacy
    """
    LEGACY_MODULES.add(module_name)
    logger.info(f"[LEGACY-GUARD] Registered legacy module: {module_name} ({reason})")


def is_legacy_module(module_name: str) -> bool:
    """
    Check if a module is registered as legacy.
    
    Args:
        module_name: The module name to check
    
    Returns:
        True if module is legacy, False otherwise
    """
    return module_name in LEGACY_MODULES
```

---

## Step 5: Integrate Legacy Guard into Startup

**File**: `web/main_15m_lean.py`

**Location**: In `_run_full_startup_in_lifespan()`, after profile validation

**Add this code** (enhance existing legacy check):

```python
# Phase 4: Legacy module guard
from merid.legacy_module_guard import assert_no_legacy_modules, get_legacy_module_report

try:
    assert_no_legacy_modules(context="startup")
    logger.info("[STARTUP] Legacy module check passed - no legacy modules loaded")
    
    health_log_path = get_health_log_path()
    with open(health_log_path, "a") as f:
        f.write(f"[{datetime.now(timezone.utc)}] LEGACY-GUARD: PASSED\n")
        f.flush()
        
except RuntimeError as e:
    logger.error(f"[STARTUP] Legacy module check failed: {e}")
    
    health_log_path = get_health_log_path()
    with open(health_log_path, "a") as f:
        f.write(f"[{datetime.now(timezone.utc)}] LEGACY-GUARD: FAILED - {e}\n")
        f.flush()
    
    # For now, log but continue (can be made to fail startup later)
    logger.warning("[STARTUP] Continuing despite legacy modules (will be hardened later)")
```

---

## Step 6: Add Import-Time Guard for Legacy Imports

**File**: `merid/__init__.py` (or create new `merid/import_guard.py`)

```python
"""
Import-time guard to prevent legacy module imports in kalshi_crypto_15m_v2 profile.

This module uses sys.meta_path to intercept imports and block legacy modules.
"""

import sys
import logging
from importlib.abc import MetaPathFinder, Loader
from importlib.util import spec_from_loader
from merid.profile_resolver import is_kalshi_crypto_15m_v2
from merid.legacy_module_guard import LEGACY_MODULES

logger = logging.getLogger("import_guard")


class LegacyModuleBlocker(MetaPathFinder):
    """
    Meta path finder that blocks imports of legacy modules in production profile.
    """
    
    def find_spec(self, fullname, path, target=None):
        """
        Intercept import and block if it's a legacy module in production profile.
        """
        if not is_kalshi_crypto_15m_v2():
            # Only block in production profile
            return None
        
        # Check if this is a legacy module
        for legacy_module in LEGACY_MODULES:
            if fullname == legacy_module or fullname.startswith(legacy_module + "."):
                logger.error(f"[IMPORT-GUARD] Blocked import of legacy module: {fullname}")
                raise ImportError(
                    f"Import of legacy module '{fullname}' is blocked in "
                    f"kalshi_crypto_15m_v2 profile. "
                    f"This module is deprecated and should not be used in production."
                )
        
        return None


def install_import_guard():
    """
    Install the legacy module blocker into sys.meta_path.
    
    This should be called early in the application startup.
    """
    if is_kalshi_crypto_15m_v2():
        blocker = LegacyModuleBlocker()
        sys.meta_path.insert(0, blocker)
        logger.info("[IMPORT-GUARD] Legacy module blocker installed")
    else:
        logger.debug("[IMPORT-GUARD] Skipped (not in kalshi_crypto_15m_v2 profile)")


# Auto-install on module import (optional - can be called explicitly instead)
# install_import_guard()
```

**Then in `web/main_15m_lean.py` startup**:

```python
# Install import guard early
from merid.import_guard import install_import_guard
install_import_guard()
```

---

## Step 7: Add Runtime Guard for Function Calls

**For critical functions that should only be called from authorized modules**:

```python
from merid.profile_resolver import is_kalshi_crypto_15m_v2
import inspect

def _check_authorized_caller(authorized_modules: list) -> None:
    """
    Check if the caller is from an authorized module.
    
    Args:
        authorized_modules: List of module names that are allowed to call this function
    
    Raises:
        RuntimeError: If caller is not from an authorized module
    """
    if not is_kalshi_crypto_15m_v2():
        return
    
    # Get caller's frame
    frame = inspect.currentframe()
    try:
        # Go up 2 frames to get the actual caller (skip this function and its wrapper)
        caller_frame = frame.f_back.f_back
        caller_module = inspect.getmodule(caller_frame)
        
        if caller_module:
            caller_name = caller_module.__name__
            
            # Check if caller is authorized
            is_authorized = any(
                caller_name.startswith(auth) for auth in authorized_modules
            )
            
            if not is_authorized:
                raise RuntimeError(
                    f"Unauthorized call from module '{caller_name}'. "
                    f"Authorized modules: {authorized_modules}"
                )
    finally:
        del frame


# Example usage in a critical function
def route_order_async(intent: OrderIntent) -> OrderResult:
    """Route an order (critical function)."""
    _check_authorized_caller([
        "merid.loop_15m",
        "merid.prediction.agent_grid_15m",
        "web.api",
    ])
    
    # Existing implementation...
```

---

## Step 8: Add Profile Guards to API Endpoints

**For API endpoints that should not be available in kalshi_crypto_15m_v2**:

```python
from fastapi import HTTPException
from merid.profile_resolver import is_kalshi_crypto_15m_v2

@router.get("/api/legacy-endpoint")
async def legacy_endpoint():
    """Legacy endpoint that should not be used in kalshi_crypto_15m_v2."""
    if is_kalshi_crypto_15m_v2():
        raise HTTPException(
            status_code=403,
            detail="This endpoint is not available in kalshi_crypto_15m_v2 profile"
        )
    
    # Existing implementation...
```

---

## Priority List for Guardrail Implementation

### High Priority (Block Immediately)
1. **Legacy agent grid import**: `merid.prediction.agent_grid`
   - This is the most likely cause of your run_cycle issue
   - Add hard fail on import

2. **Deprecated bankroll service**: `KalshiBankrollService`
   - Add hard fail in `__init__` and `get_bankroll_service()`

3. **Legacy loop**: `merid.loop`
   - Add hard fail on import

### Medium Priority (Block with Warning)
4. **Legacy Kalshi client**: `KalshiVenueClient`
   - Verify if this should be blocked or if it's still needed
   - Add warning or hard fail depending on investigation

5. **Archive modules**: All `archive.legacy.*` modules
   - Add hard fail on import

### Low Priority (Monitor)
6. **Test files**: No guards needed (tests can import legacy modules)
7. **Scripts**: Some scripts may need legacy modules for debugging
   - Add conditional guards based on context

---

## Testing the Guardrails

After implementing guardrails, test with:

```powershell
# Test 1: Try to import legacy module (should fail)
py -c "from merid.profile_resolver import is_kalshi_crypto_15m_v2; import os; os.environ['MERID_PROFILE']='kalshi_crypto_15m_v2'; from merid.prediction import agent_grid"

# Test 2: Start system and check logs for legacy module warnings
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2

# Check logs
Get-Content C:\Dev\MERID\web\health_diagnostic_*.txt -Tail 20 | Select-String "LEGACY"
```

---

## Expected Behavior

**Without guardrails** (current state):
- Legacy modules can be imported silently
- Multiple versions of classes can coexist
- Hard to detect which implementation is actually used

**With guardrails** (desired state):
- Importing legacy module in kalshi_crypto_15m_v2 raises ImportError
- Instantiating deprecated class raises RuntimeError
- Logs clearly show when legacy code is attempted
- Startup fails if legacy modules are detected (configurable)

---

## Gradual Rollout Strategy

1. **Phase 1**: Add logging-only guards (warnings, no failures)
2. **Phase 2**: Add soft failures (warnings + continue)
3. **Phase 3**: Add hard failures for critical modules (agent_grid, bankroll)
4. **Phase 4**: Add hard failures for all legacy modules
5. **Phase 5**: Enable import-time blocking

This allows you to incrementally tighten the guards without breaking the system immediately.

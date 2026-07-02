# Phase 3: Profile & Environment Verification - Implementation Guide

This guide shows how to add environment logging to the application startup to detect configuration issues at runtime.

---

## Step 1: Add Environment Logging to Startup

**File**: `web/main_15m_lean.py`

**Location**: In `_run_full_startup_in_lifespan()`, immediately after the profile validation (around line 1691)

**Add this code**:

```python
# Phase 3: Environment verification - log at startup
import sys
import os
from pathlib import Path

# Log environment variables
env_vars = {
    "MERID_PROFILE": os.environ.get("MERID_PROFILE", "<not set>"),
    "MERID_ALLOW_LIVE_TRADES": os.environ.get("MERID_ALLOW_LIVE_TRADES", "<not set>"),
    "KALSHI_ENV": os.environ.get("KALSHI_ENV", "<not set>"),
    "PYTHONPATH": os.environ.get("PYTHONPATH", "<not set>"),
}

logger.info("[ENV-VERIFICATION] Environment variables:")
for var, value in env_vars.items():
    logger.info(f"[ENV-VERIFICATION]   {var}={value}")

# Log sys.path
logger.info("[ENV-VERIFICATION] sys.path (first 10 entries):")
for i, path in enumerate(sys.path[:10]):
    logger.info(f"[ENV-VERIFICATION]   [{i}] {path}")

# Log working directory
logger.info(f"[ENV-VERIFICATION] Working directory: {os.getcwd()}")

# Log merid module source
try:
    import merid
    merid_file = getattr(merid, "__file__", "<no __file__>")
    logger.info(f"[ENV-VERIFICATION] merid module: {merid_file}")
    
    # Check for site-packages shadowing
    if "site-packages" in merid_file.lower() or "dist-packages" in merid_file.lower():
        logger.error(f"[ENV-VERIFICATION] ⚠️  CRITICAL: merid loaded from site-packages: {merid_file}")
        logger.error("[ENV-VERIFICATION] This may shadow local source changes!")
except ImportError as e:
    logger.error(f"[ENV-VERIFICATION] Failed to import merid: {e}")

# Log critical module sources
critical_modules = [
    "merid.prediction.agent_grid_15m",
    "merid.loop_15m",
    "merid.event_venues.kalshi.market_catalog",
    "merid.event_venues.kalshi.bankroll_service_v2",
    "merid.event_venues.kalshi.client_v2",
]

for module_name in critical_modules:
    try:
        mod = __import__(module_name, fromlist=[""])
        mod_file = getattr(mod, "__file__", "<no __file__>")
        
        if "site-packages" in mod_file.lower() or "dist-packages" in mod_file.lower():
            logger.error(f"[ENV-VERIFICATION] ⚠️  {module_name} loaded from site-packages: {mod_file}")
        else:
            logger.info(f"[ENV-VERIFICATION] ✓ {module_name}: {mod_file}")
    except ImportError as e:
        logger.warning(f"[ENV-VERIFICATION] Could not import {module_name}: {e}")

# Write to health diagnostic file
health_log_path = get_health_log_path()
with open(health_log_path, "a") as f:
    f.write(f"[{datetime.now(timezone.utc)}] ENV-VERIFICATION: Profile={env_vars['MERID_PROFILE']}\n")
    f.write(f"[{datetime.now(timezone.utc)}] ENV-VERIFICATION: Working directory={os.getcwd()}\n")
    f.write(f"[{datetime.now(timezone.utc)}] ENV-VERIFICATION: sys.path entries={len(sys.path)}\n")
    f.flush()
```

---

## Step 2: Add Profile Validation Check

**File**: `web/main_15m_lean.py`

**Location**: In the profile validation section (around line 1682-1684), enhance the existing check

**Replace/Enhance existing code**:

```python
# Enhanced profile validation
profile = settings.MERID_PROFILE
logger.info(f"[STARTUP] Checking profile: {profile}")

if profile != "kalshi_crypto_15m_v2":
    logger.error(f"[STARTUP] Invalid profile '{profile}'. Expected 'kalshi_crypto_15m_v2'")
    raise RuntimeError(f"Invalid profile: {profile}. Expected: kalshi_crypto_15m_v2")

logger.info("[STARTUP] Profile verified: kalshi_crypto_15m_v2")

# Additional profile-specific checks
if profile == "kalshi_crypto_15m_v2":
    # Verify live trading flags are consistent
    allow_live = os.environ.get("MERID_ALLOW_LIVE_TRADES", "").lower()
    kalshi_env = os.environ.get("KALSHI_ENV", "").lower()
    
    logger.info(f"[STARTUP] Profile-specific checks: allow_live={allow_live}, kalshi_env={kalshi_env}")
    
    if kalshi_env == "live" and allow_live != "true":
        logger.warning("[STARTUP] ⚠️  KALSHI_ENV=live but MERID_ALLOW_LIVE_TRADES is not 'true'")
```

---

## Step 3: Add Module Shadowing Detection

**File**: Create new file `merid/environment_guard.py`

```python
"""
Environment guard to detect module shadowing and configuration issues.
"""

import sys
import os
import logging
from typing import List, Tuple

logger = logging.getLogger("environment_guard")


def detect_module_shadowing() -> List[Tuple[str, str]]:
    """
    Detect if critical modules are being shadowed by site-packages.
    
    Returns:
        List of (module_name, file_path) tuples for shadowed modules
    """
    shadowed = []
    
    critical_modules = [
        "merid",
        "merid.prediction.agent_grid_15m",
        "merid.loop_15m",
        "merid.event_venues.kalshi.market_catalog",
        "merid.event_venues.kalshi.bankroll_service_v2",
        "merid.event_venues.kalshi.client_v2",
    ]
    
    for module_name in critical_modules:
        try:
            mod = __import__(module_name, fromlist=[""])
            mod_file = getattr(mod, "__file__", None)
            
            if mod_file and ("site-packages" in mod_file.lower() or "dist-packages" in mod_file.lower()):
                shadowed.append((module_name, mod_file))
                logger.error(f"[SHADOWING] {module_name} is shadowed by site-packages: {mod_file}")
        except ImportError:
            logger.warning(f"[SHADOWING] Could not import {module_name}")
    
    return shadowed


def detect_duplicate_merid_paths() -> List[str]:
    """
    Detect if there are multiple merid paths in sys.path.
    
    Returns:
        List of duplicate merid paths
    """
    merid_paths = [p for p in sys.path if "merid" in p.lower()]
    
    if len(merid_paths) > 1:
        logger.warning(f"[SHADOWING] Multiple merid paths in sys.path: {merid_paths}")
    
    return merid_paths


def validate_environment_for_profile(profile: str) -> Tuple[bool, List[str]]:
    """
    Validate that the environment is correctly configured for the given profile.
    
    Args:
        profile: The profile name (e.g., "kalshi_crypto_15m_v2")
    
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    # Check profile
    if profile != "kalshi_crypto_15m_v2":
        issues.append(f"Profile is '{profile}' instead of 'kalshi_crypto_15m_v2'")
    
    # Check for module shadowing
    shadowed = detect_module_shadowing()
    if shadowed:
        for module, path in shadowed:
            issues.append(f"Module {module} is shadowed by site-packages: {path}")
    
    # Check for duplicate paths
    duplicate_paths = detect_duplicate_merid_paths()
    if len(duplicate_paths) > 1:
        issues.append(f"Multiple merid paths in sys.path: {duplicate_paths}")
    
    # Check environment variables
    if profile == "kalshi_crypto_15m_v2":
        kalshi_env = os.environ.get("KALSHI_ENV", "")
        if not kalshi_env:
            issues.append("KALSHI_ENV is not set")
        
        allow_live = os.environ.get("MERID_ALLOW_LIVE_TRADES", "")
        if not allow_live:
            issues.append("MERID_ALLOW_LIVE_TRADES is not set")
    
    is_valid = len(issues) == 0
    
    if is_valid:
        logger.info(f"[ENV-GUARD] Environment is valid for profile '{profile}'")
    else:
        logger.error(f"[ENV-GUARD] Environment validation failed for profile '{profile}':")
        for issue in issues:
            logger.error(f"[ENV-GUARD]   - {issue}")
    
    return is_valid, issues


def log_environment_snapshot() -> None:
    """Log a complete snapshot of the environment for debugging."""
    logger.info("[ENV-SNAPSHOT] Environment variables:")
    for key in sorted(os.environ.keys()):
        if "MERID" in key or "KALSHI" in key or "PYTHON" in key:
            logger.info(f"[ENV-SNAPSHOT]   {key}={os.environ[key]}")
    
    logger.info("[ENV-SNAPSHOT] sys.path:")
    for i, path in enumerate(sys.path):
        logger.info(f"[ENV-SNAPSHOT]   [{i}] {path}")
    
    logger.info(f"[ENV-SNAPSHOT] Working directory: {os.getcwd()}")
    logger.info(f"[ENV-SNAPSHOT] Python executable: {sys.executable}")
```

---

## Step 4: Integrate Environment Guard into Startup

**File**: `web/main_15m_lean.py`

**Location**: In `_run_full_startup_in_lifespan()`, after profile validation

**Add this code**:

```python
# Phase 3: Environment guard validation
from merid.environment_guard import validate_environment_for_profile, log_environment_snapshot

is_valid, issues = validate_environment_for_profile(profile)

if not is_valid:
    logger.error("[STARTUP] Environment validation failed:")
    for issue in issues:
        logger.error(f"[STARTUP]   - {issue}")
    
    # Log to health diagnostic
    health_log_path = get_health_log_path()
    with open(health_log_path, "a") as f:
        f.write(f"[{datetime.now(timezone.utc)}] ENV-GUARD: VALIDATION FAILED\n")
        for issue in issues:
            f.write(f"[{datetime.now(timezone.utc)}] ENV-GUARD:   - {issue}\n")
        f.flush()
    
    # Decide whether to fail startup or continue with warning
    # For now, log but continue (can be made stricter later)
    logger.warning("[STARTUP] Continuing despite environment validation issues (will be hardened later)")
else:
    logger.info("[STARTUP] Environment validation passed")
    
    health_log_path = get_health_log_path()
    with open(health_log_path, "a") as f:
        f.write(f"[{datetime.now(timezone.utc)}] ENV-GUARD: VALIDATION PASSED\n")
        f.flush()

# Log environment snapshot for debugging
log_environment_snapshot()
```

---

## Failure Patterns to Detect

### Pattern 1: Multiple merid in sys.path
**Symptom**:
```
[SHADOWING] Multiple merid paths in sys.path: ['C:\\Dev\\MERID', 'C:\\Python\\Lib\\site-packages\\merid']
```
**Cause**: merid installed in both local source and site-packages
**Fix**: Uninstall from site-packages, ensure only local source is used

### Pattern 2: Module loaded from site-packages
**Symptom**:
```
[SHADOWING] merid.prediction.agent_grid_15m is shadowed by site-packages: C:\\Python\\Lib\\site-packages\\merid\\prediction\\agent_grid_15m.py
```
**Cause**: Module imported from site-packages instead of local source
**Fix**: Remove site-packages installation, adjust PYTHONPATH

### Pattern 3: Wrong profile
**Symptom**:
```
[ENV-GUARD] Profile is 'kalshi_crypto_15m' instead of 'kalshi_crypto_15m_v2'
```
**Cause**: MERID_PROFILE environment variable set incorrectly
**Fix**: Set MERID_PROFILE=kalshi_crypto_15m_v2 in startup script

### Pattern 4: Missing environment variables
**Symptom**:
```
[ENV-GUARD] KALSHI_ENV is not set
[ENV-GUARD] MERID_ALLOW_LIVE_TRADES is not set
```
**Cause**: Required environment variables not set
**Fix**: Set these in startup script or environment

---

## Quick Verification Commands

After adding environment logging, verify with:

```powershell
# Check environment before starting
$env:MERID_PROFILE
$env:KALSHI_ENV
$env:MERID_ALLOW_LIVE_TRADES

# Start the system
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2

# Check logs for environment verification
Get-Content C:\Dev\MERID\web\health_diagnostic_*.txt -Tail 20 | Select-String "ENV-"
```

---

## Expected Output

**Successful validation**:
```
[STARTUP] Profile verified: kalshi_crypto_15m_v2
[ENV-GUARD] Environment is valid for profile 'kalshi_crypto_15m_v2'
[STARTUP] Environment validation passed
[ENV-SNAPSHOT] Environment variables:
[ENV-SNAPSHOT]   KALSHI_ENV=live
[ENV-SNAPSHOT]   MERID_ALLOW_LIVE_TRADES=true
[ENV-SNAPSHOT]   MERID_PROFILE=kalshi_crypto_15m_v2
```

**Failed validation**:
```
[STARTUP] Profile verified: kalshi_crypto_15m_v2
[SHADOWING] merid.prediction.agent_grid_15m is shadowed by site-packages: C:\Python\Lib\site-packages\merid\prediction\agent_grid_15m.py
[ENV-GUARD] Environment validation failed for profile 'kalshi_crypto_15m_v2':
[ENV-GUARD]   - Module merid.prediction.agent_grid_15m is shadowed by site-packages: ...
[STARTUP] Continuing despite environment validation issues
```

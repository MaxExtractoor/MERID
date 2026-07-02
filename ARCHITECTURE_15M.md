# Kalshi 15m Stack - Architectural Separation

## Overview

The Kalshi 15m stack is a completely separate system from the legacy MERID system. This document defines the architectural boundaries and operational safeguards to ensure clean separation.

## Canonical Entrypoint

**15m Stack:** `web.main_15m_lean:app`
- **Startup Script:** `start_15m.ps1`
- **Profile:** `kalshi_crypto_15m_v2`
- **Port:** 8011 (default)
- **Docs:** `http://localhost:8011/docs`

**Legacy System:** `web.main_legacy.py` (quarantined)
- **Purpose:** Historical reference only
- **Status:** DO NOT USE FOR PRODUCTION

## 15m Stack Boundaries

### Core Modules (15m Only)
```
web.main_15m_lean                    # Canonical entrypoint
web.api.performance_api             # Performance metrics
web.api.kalshi_api                  # Kalshi trading endpoints
web.api.kalshi_agent_grid_api       # Agent grid management
web.api.kalshi_grid_api             # Grid status and control
web.api.health_api                   # Health checks
web.api.loop_api                    # Loop status
web.api.spot_debug_api              # Spot price debugging
web.api.paper_session_api            # Paper trading
web.api.system_endpoints            # System diagnostics
web.api.agents                       # Agent management
```

### Prediction Modules (15m Only)
```
merid.prediction.agent_grid_15m     # 15m agent grid (NOT legacy agent_grid)
merid.prediction.kalshi_strike_selector  # Strike selection
merid.prediction.agent_grid_config  # Configuration
```

### Data and Venue Modules (15m Only)
```
data.unified_spot_service           # Spot price service
merid.event_venues.kalshi.*         # Kalshi venue modules
merid.loop_15m                       # 15m trading loop
```

## Forbidden Imports (Legacy System)

The following modules are **FORBIDDEN** in the 15m stack:

### Legacy Prediction
- `merid.prediction.agent_grid` ❌ (use `agent_grid_15m`)
- `merid.prediction.paper_session` ❌
- `merid.prediction.debate_store` ❌
- `merid.prediction.unified_orchestrator` ❌

### Legacy Web
- `web.main` ❌ (use `web.main_15m_lean`)
- `web.main_legacy.py` ❌ (quarantined)

### Legacy Loop
- `merid.loop` ❌ (use `merid.loop_15m`)
- `merid.loop_main` ❌

### Legacy Core
- `core.orchestrator` ❌
- `core.deployment_controller` ❌
- `core.learning` ❌
- `core.persistence` ❌

## Operational Safeguards

### 1. Startup Script
```powershell
# CORRECT: Uses 15m entrypoint
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2

# INCORRECT: Do NOT use legacy entrypoint
uvicorn web.main:app  # ❌ This will fail
```

### 2. Health Checks
```bash
# CORRECT: Target 15m endpoints
curl http://localhost:8011/api/v1/health
curl http://localhost:8011/api/v1/system/health

# EXPECTED: app=merid_15m_kalshi_crypto, profile=kalshi_crypto_15m_v2
```

### 3. API Documentation
- **15m Stack:** `http://localhost:8011/docs`
- **Legacy System:** No longer accessible

### 4. Static Tests
Run architectural separation tests:
```bash
python -m pytest tests/test_15m_architectural_separation.py -v
```

## Migration History

### Before Separation
- Mixed imports between legacy and 15m systems
- `main.py` used for both systems
- Import errors: `"No module named 'merid.prediction.agent_grid'"`

### After Separation
- Clean architectural boundaries
- `main_15m_lean.py` for 15m stack only
- `main_legacy.py` quarantined
- All imports correctly resolved

## Testing the Separation

### Static Tests
```bash
# Test architectural separation
python -m pytest tests/test_15m_architectural_separation.py -v

# Expected: All tests pass
```

### Runtime Tests
```bash
# Start 15m stack
.\start_15m.ps1

# Verify correct app/profile
curl http://localhost:8011/api/v1/health | jq '.app, .profile'

# Expected: "merid_15m_kalshi_crypto", "kalshi_crypto_15m_v2"
```

## Troubleshooting

### Import Errors
If you see `"No module named 'merid.prediction.agent_grid'"`:
1. Check that you're using `web.main_15m_lean:app`
2. Verify no 15m modules import legacy `agent_grid`
3. Run architectural separation tests

### Endpoint 404s
If endpoints return 404:
1. Verify startup script uses correct entrypoint
2. Check port conflicts
3. Confirm 15m profile is set

### Agent Grid Issues
If agent grid shows `agent_grid_missing`:
1. Check `startup_state.completed` is true
2. Verify `app.state.agent_grid_15m` is set
3. Check for import errors in logs

## Development Guidelines

### Adding New 15m Modules
1. Use `merid.prediction.agent_grid_15m` imports
2. Add module to `fifteen_m_modules` in test
3. Test architectural separation

### Modifying Existing Modules
1. Never import legacy modules
2. Use 15m-specific alternatives
3. Run separation tests after changes

### Debugging
1. Always use 15m entrypoint
2. Check 15m-specific logs
3. Verify 15m health endpoints

## Emergency Procedures

### If Legacy System is Accidentally Used
1. Stop all processes
2. Verify `start_15m.ps1` is used
3. Check no legacy imports exist
4. Run separation tests

### If Architectural Separation Tests Fail
1. Identify violating import
2. Replace with 15m equivalent
3. Update test if new 15m module added
4. Re-run tests

## Contact

For questions about the 15m stack architectural separation:
- Check this documentation first
- Run separation tests to diagnose issues
- Verify startup script and entrypoint usage

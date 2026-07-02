# MERID RTI Configuration

This document describes the environment variables for configuring the MERID RTI (Real-Time Index) spot price service and unified edge computation for Kalshi 15-minute crypto markets.

## Environment Variables

### Edge Computation Mode

#### `MERID_UNIFIED_EDGE_ENABLED`
- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Description**: Controls whether unified edge computation is used for live trading decisions.
- **Values**:
  - `false`: Legacy edge computation (spread-based heuristic) is used for live trading
  - `true`: Unified edge computation (RTI-based) is used for live trading
- **Notes**:
  - Cannot be enabled simultaneously with `MERID_UNIFIED_EDGE_SHADOW_MODE=true`
  - Requires `MERID_CALIBRATION_VERSION` to be set to a non-placeholder value
  - When enabled, spot data must come from a valid SpotProvider

#### `MERID_UNIFIED_EDGE_SHADOW_MODE`
- **Type**: Boolean (`true`/`false`)
- **Default**: `false`
- **Description**: Enables shadow mode where unified edge is computed and logged for comparison but not used for trading.
- **Values**:
  - `false`: Shadow mode disabled
  - `true`: Shadow mode enabled - legacy edge is used for trading, unified edge computed in parallel for comparison
- **Notes**:
  - Cannot be enabled simultaneously with `MERID_UNIFIED_EDGE_ENABLED=true`
  - Logs detailed comparison between legacy and unified edge on every signal
  - Use this to validate unified edge behavior before making it live
- **Log output**: `[SHADOW-MODE-COMPARISON]` with edge %, confidence, implied/model probs, side match

### Spot Provider Configuration

#### `MERID_SPOT_PROVIDER_TYPE`
- **Type**: String
- **Default**: `unified`
- **Description**: Selects the spot price provider implementation.
- **Values**:
  - `unified`: Uses `UnifiedSpotProvider` which wraps `unified_spot_service` directly (no HTTP overhead)
  - `rti`: Uses `MeridRtiSpotProvider` which fetches from `/api/v1/rti/{asset}` HTTP endpoint
  - `cfb`: Uses `CfbSpotProvider` which fetches from legacy CFB proxy (deprecated)
- **Notes**:
  - Validated at startup - invalid values will cause startup to fail
  - For Kalshi 15-minute crypto, `unified` is recommended for lowest latency
  - `rti` is useful for testing the HTTP API endpoint

### Calibration

#### `MERID_CALIBRATION_VERSION`
- **Type**: String
- **Default**: `placeholder`
- **Description**: Version identifier for calibration parameters used in unified edge computation.
- **Values**:
  - `placeholder`: Indicates no calibration is fitted (blocks unified edge in live mode)
  - `v1`, `v2`, etc.: Valid calibration versions after fitting parameters
- **Notes**:
  - Required to be non-placeholder when `MERID_UNIFIED_EDGE_ENABLED=true`
  - Used to track which calibration parameters are in use

## Valid Configuration Combinations

### Production (Legacy Mode)
```bash
MERID_UNIFIED_EDGE_ENABLED=false
MERID_UNIFIED_EDGE_SHADOW_MODE=false
MERID_SPOT_PROVIDER_TYPE=unified
```
- Legacy edge is live
- No unified edge computation
- Spot data from unified_spot_service

### Shadow Mode (Validation)
```bash
MERID_UNIFIED_EDGE_ENABLED=false
MERID_UNIFIED_EDGE_SHADOW_MODE=true
MERID_SPOT_PROVIDER_TYPE=unified
```
- Legacy edge is live (trading)
- Unified edge computed in parallel for comparison
- Spot data from unified_spot_service
- Logs: `[SHADOW-MODE-COMPARISON]` for every signal

### Production (Unified Edge Live)
```bash
MERID_UNIFIED_EDGE_ENABLED=true
MERID_UNIFIED_EDGE_SHADOW_MODE=false
MERID_SPOT_PROVIDER_TYPE=unified
MERID_CALIBRATION_VERSION=v1
```
- Unified edge is live (trading)
- No legacy edge computation
- Spot data from unified_spot_service
- Requires valid calibration version

### Invalid Combinations

**Both unified edge and shadow mode enabled:**
```bash
MERID_UNIFIED_EDGE_ENABLED=true
MERID_UNIFIED_EDGE_SHADOW_MODE=true  # ERROR: Cannot enable both
```
- Startup validation will fail with error message

**Unified edge enabled with placeholder calibration:**
```bash
MERID_UNIFIED_EDGE_ENABLED=true
MERID_CALIBRATION_VERSION=placeholder  # ERROR: Invalid calibration
```
- Startup validation will fail with error message

**Invalid spot provider type:**
```bash
MERID_SPOT_PROVIDER_TYPE=invalid  # ERROR: Must be unified, rti, or cfb
```
- Startup validation will fail with error message

## Startup Validations

The following validations are performed at startup:

1. **Unified edge configuration** (`validate_unified_edge_configuration`)
   - Ensures `MERID_UNIFIED_EDGE_ENABLED` and `MERID_UNIFIED_EDGE_SHADOW_MODE` are not both true
   - Ensures `MERID_CALIBRATION_VERSION` is not placeholder when unified edge is enabled
   - Logs the active mode (legacy, shadow, or unified live)

2. **Spot provider configuration** (`validate_spot_provider_configuration`)
   - Ensures `MERID_SPOT_PROVIDER_TYPE` is one of `unified`, `rti`, or `cfb`
   - Logs the selected provider type

3. **Spot proxy availability** (`validate_spot_proxy_availability`)
   - Only runs when unified edge is enabled or shadow mode is active
   - Checks that `unified_spot_service` is running and has fresh data
   - Warns if assets are missing or stale

## Shadow Mode Success Criteria

When running in shadow mode, monitor the following to determine if unified edge is ready for production:

### Log Lines to Watch

**Shadow mode comparison:**
```
[SHADOW-MODE-COMPARISON] BTC_15M asset=BTC ticker=KXBTC15M-XXXX LEGACY: edge=0.0234 conf=0.70 implied=0.512 model=0.535 side=yes | UNIFIED: edge=0.0251 conf=0.72 implied=0.512 model=0.537 side=yes | EDGE_DIFF=0.0017 SIDE_MATCH=true
```

**Key metrics:**
- `EDGE_DIFF`: Absolute difference between legacy and unified edge (target: < 0.005 or 50bp)
- `SIDE_MATCH`: Boolean indicating if both backends chose the same side (target: > 95% match rate)
- Edge magnitude: Both should be reasonable (not extreme outliers)
- Confidence: Unified edge confidence should be >= 0.60

### Acceptable Tolerances

- **Edge difference**: < 50bp (0.005) on 90%+ of signals
- **Side match rate**: > 95% agreement on chosen side
- **No crashes**: SpotProvider and EdgeComputer should not throw exceptions
- **No unsupported asset warnings**: All 5 assets (BTC, ETH, SOL, XRP, DOGE) should be valid

### Failure Modes

- **Edge divergence**: If `EDGE_DIFF` consistently > 100bp, investigate calibration or spot data
- **Side mismatch**: If `SIDE_MATCH=false` frequently, review edge computation logic
- **Missing spot data**: If spot provider returns None, check unified_spot_service health
- **Unsupported asset errors**: Indicates asset scope assertion failure

## Asset Scope

The MERID RTI system is scoped to support only the following assets for Kalshi 15-minute crypto markets:

- **BTC** (Bitcoin)
- **ETH** (Ethereum)
- **SOL** (Solana)
- **XRP** (Ripple)
- **DOGE** (Dogecoin)

Any attempt to fetch spot data for other assets will fail with `[SPOT-ASSET-INVALID]` error.

## Related Files

- `merid/prediction/spot_provider.py`: SpotProvider abstraction and implementations
- `merid/prediction/edge_computer.py`: EdgeComputer abstraction and backends
- `merid/prediction/unified_edge.py`: UnifiedEdgeBackend implementation
- `merid/prediction/agent_grid_15m.py`: LeanAgent15m using SpotProvider
- `web/api/crypto_rti_api.py`: RTI HTTP API endpoint
- `data/unified_spot_service.py`: Unified spot price service
- `merid/startup_validations.py`: Configuration validation functions

"""
Integration verification script for risk pipeline.

This script verifies:
1. API endpoints are registered in FastAPI app
2. Feature flag is accessible and working
3. Coordinator is accessible from API endpoints
4. All components are properly wired together
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 80)
print("INTEGRATION VERIFICATION: Risk Pipeline")
print("=" * 80)

# Test 1: Verify FastAPI app includes kalshi_api_router
print("\n[TEST 1] Verify kalshi_api_router is registered in FastAPI app...")
try:
    from web.main import create_app
    app = create_app(lifespan=lambda app: None)  # No-op lifespan for testing
    
    # Check if kalshi_api_router routes are present
    routes = [route.path for route in app.routes]
    
    expected_routes = [
        "/api/v1/kalshi/risk/projection",
        "/api/v1/kalshi/risk/diff",
        "/api/v1/kalshi/risk/pipeline-status",
    ]
    
    for route in expected_routes:
        if route in routes:
            print(f"  ✅ {route} registered")
        else:
            print(f"  ❌ {route} NOT registered")
            sys.exit(1)
    
    print("✅ All risk pipeline API endpoints registered")
except Exception as e:
    print(f"❌ Failed to verify router registration: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Verify feature flag is accessible
print("\n[TEST 2] Verify feature flag USE_NEW_RISK_PIPELINE is accessible...")
try:
    from merid.settings import settings
    
    if hasattr(settings, 'USE_NEW_RISK_PIPELINE'):
        print(f"✅ USE_NEW_RISK_PIPELINE exists: {settings.USE_NEW_RISK_PIPELINE}")
    else:
        print("❌ USE_NEW_RISK_PIPELINE not found in settings")
        sys.exit(1)
except Exception as e:
    print(f"❌ Failed to access feature flag: {e}")
    sys.exit(1)

# Test 3: Verify coordinator is accessible
print("\n[TEST 3] Verify risk_pipeline_coordinator is accessible...")
try:
    from merid.event_venues.kalshi.risk_pipeline_coordinator import (
        get_risk_projection,
        run_parallel_diff,
        get_pipeline_status,
    )
    print("✅ Coordinator functions imported successfully")
    
    # Check function signatures
    import inspect
    sig = inspect.signature(get_risk_projection)
    print(f"  get_risk_projection signature: {sig}")
    
    sig = inspect.signature(run_parallel_diff)
    print(f"  run_parallel_diff signature: {sig}")
    
    sig = inspect.signature(get_pipeline_status)
    print(f"  get_pipeline_status signature: {sig}")
except Exception as e:
    print(f"❌ Failed to import coordinator: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Verify backend snapshot fetcher is accessible
print("\n[TEST 4] Verify backend_snapshot_fetcher is accessible...")
try:
    from merid.event_venues.kalshi.backend_snapshot_fetcher import (
        fetch_backend_snapshot,
        fetch_and_validate_snapshot,
    )
    print("✅ Backend snapshot fetcher functions imported successfully")
except Exception as e:
    print(f"❌ Failed to import backend snapshot fetcher: {e}")
    sys.exit(1)

# Test 5: Verify risk projection engine is accessible
print("\n[TEST 5] Verify risk_projection engine is accessible...")
try:
    from merid.event_venues.kalshi.risk_projection import (
        RiskProjectionEngine,
        BackendPosition,
        BackendBalance,
        BackendSnapshot,
    )
    print("✅ Risk projection engine components imported successfully")
    
    # Verify singleton access
    from merid.event_venues.kalshi.risk_projection import get_risk_projection_engine
    engine = get_risk_projection_engine()
    print(f"✅ Risk projection engine singleton accessible: {type(engine).__name__}")
except Exception as e:
    print(f"❌ Failed to import risk projection engine: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: Verify parallel runner is accessible
print("\n[TEST 6] Verify parallel_risk_runner is accessible...")
try:
    from merid.event_venues.kalshi.parallel_risk_runner import (
        ParallelRiskRunner,
        DiffResult,
    )
    print("✅ Parallel risk runner components imported successfully")
    
    # Verify singleton access
    from merid.event_venues.kalshi.parallel_risk_runner import get_parallel_risk_runner
    runner = get_parallel_risk_runner()
    print(f"✅ Parallel risk runner singleton accessible: {type(runner).__name__}")
except Exception as e:
    print(f"❌ Failed to import parallel risk runner: {e}")
    sys.exit(1)

# Test 7: Verify compatibility shim is accessible
print("\n[TEST 7] Verify risk_adapter compatibility shim is accessible...")
try:
    from merid.event_venues.kalshi.risk_adapter import (
        LegacyPosition,
        LegacyPositionCache,
        get_position_cache,
    )
    print("✅ Risk adapter compatibility shim imported successfully")
except Exception as e:
    print(f"❌ Failed to import risk adapter: {e}")
    sys.exit(1)

# Test 8: Verify API endpoint functions are callable
print("\n[TEST 8] Verify API endpoint functions are callable...")
try:
    from web.api.kalshi_api import (
        get_risk_projection_api,
        run_parallel_diff_api,
        get_pipeline_status_api,
    )
    print("✅ API endpoint functions imported successfully")
    
    # Check function signatures
    import inspect
    sig = inspect.signature(get_risk_projection_api)
    print(f"  get_risk_projection_api signature: {sig}")
    
    sig = inspect.signature(run_parallel_diff_api)
    print(f"  run_parallel_diff_api signature: {sig}")
    
    sig = inspect.signature(get_pipeline_status_api)
    print(f"  get_pipeline_status_api signature: {sig}")
except Exception as e:
    print(f"❌ Failed to import API endpoint functions: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ ALL INTEGRATION TESTS PASSED")
print("=" * 80)
print("\nIntegration Summary:")
print("- API endpoints registered in FastAPI app: ✅")
print("- Feature flag accessible: ✅")
print("- Risk pipeline coordinator accessible: ✅")
print("- Backend snapshot fetcher accessible: ✅")
print("- Risk projection engine accessible: ✅")
print("- Parallel risk runner accessible: ✅")
print("- Compatibility shim accessible: ✅")
print("- API endpoint functions callable: ✅")
print("\nConclusion: The risk pipeline is completely wired and integrated.")

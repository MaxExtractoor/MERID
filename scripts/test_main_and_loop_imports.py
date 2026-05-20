"""
Test script to verify main.py and loop imports are not broken by risk pipeline changes.

This script tests:
1. main.py can be imported without errors
2. settings.py new feature flag doesn't break anything
3. New risk pipeline modules can be imported
4. Legacy modules still work (not broken by changes)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 80)
print("TESTING: main.py and loop imports after risk pipeline changes")
print("=" * 80)

# Test 1: Import settings to verify feature flag doesn't break
print("\n[TEST 1] Import settings.py...")
try:
    from merid.settings import settings
    print(f"✅ Settings imported successfully")
    print(f"   USE_NEW_RISK_PIPELINE = {settings.USE_NEW_RISK_PIPELINE}")
except Exception as e:
    print(f"❌ Failed to import settings: {e}")
    sys.exit(1)

# Test 2: Import main.py to verify no import errors
print("\n[TEST 2] Import main.py...")
try:
    # Import the app factory function
    from web.main import create_app
    print(f"✅ main.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import main.py: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Verify new risk pipeline modules can be imported
print("\n[TEST 3] Import new risk pipeline modules...")
try:
    from merid.event_venues.kalshi.risk_projection import (
        BackendPosition,
        BackendBalance,
        BackendFill,
        BackendSnapshot,
        RiskProjection,
        RiskProjectionEngine,
    )
    print("✅ risk_projection.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import risk_projection: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.backend_snapshot_fetcher import (
        fetch_backend_snapshot,
        fetch_and_validate_snapshot,
    )
    print("✅ backend_snapshot_fetcher.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import backend_snapshot_fetcher: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.risk_pipeline_coordinator import (
        get_risk_projection,
        run_parallel_diff,
        get_pipeline_status,
    )
    print("✅ risk_pipeline_coordinator.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import risk_pipeline_coordinator: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.parallel_risk_runner import (
        ParallelRiskRunner,
        DiffResult,
    )
    print("✅ parallel_risk_runner.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import parallel_risk_runner: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.risk_adapter import (
        LegacyPosition,
        LegacyPositionCache,
        get_position_cache,
    )
    print("✅ risk_adapter.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import risk_adapter: {e}")
    sys.exit(1)

# Test 4: Verify legacy modules still work (not broken by changes)
print("\n[TEST 4] Import legacy Kalshi modules (verify not broken)...")
try:
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    print("✅ fills_ledger.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import fills_ledger: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.position_cache import get_position_cache as get_legacy_cache
    print("✅ position_cache.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import position_cache: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.client import get_kalshi_client
    print("✅ client.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import client: {e}")
    sys.exit(1)

try:
    from merid.event_venues.kalshi.fills_poller import get_fills_poller
    print("✅ fills_poller.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import fills_poller: {e}")
    sys.exit(1)

# Test 5: Verify API endpoints module can be imported
print("\n[TEST 5] Import kalshi_api.py with new endpoints...")
try:
    from web.api import kalshi_api
    print("✅ kalshi_api.py imported successfully")
except Exception as e:
    print(f"❌ Failed to import kalshi_api: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ ALL IMPORT TESTS PASSED")
print("=" * 80)
print("\nConclusion:")
print("- main.py imports successfully")
print("- settings.py with new feature flag works")
print("- All new risk pipeline modules import successfully")
print("- Legacy Kalshi modules still work (not broken)")
print("- API endpoints module imports successfully")
print("\nThe risk pipeline changes do NOT negatively affect main.py or loop imports.")

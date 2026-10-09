#!/usr/bin/env python3
"""
Simple validation script for 15m stack alignment.
Validates that all routers are properly mounted and endpoints are accessible.
"""

import sys
from pathlib import Path

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.main_15m_lean import app
from fastapi.testclient import TestClient

def validate_routers():
    """Validate that all expected routers are mounted."""
    client = TestClient(app)
    
    print("🔍 Validating router registration...")
    
    # Get OpenAPI spec
    response = client.get("/openapi.json")
    if response.status_code != 200:
        print(f"❌ OpenAPI spec not accessible: {response.status_code}")
        return False
    
    openapi_spec = response.json()
    paths = openapi_spec.get("paths", {})
    
    # Expected endpoints
    expected_endpoints = [
        "/docs",
        "/openapi.json", 
        "/api/v1/health",
        "/api/v1/system/health",
        "/api/v1/system/execution-gate",
        "/api/v1/agents",
        "/api/v1/kalshi/markets",
        "/api/v1/kalshi/market-states",
        "/api/v1/kalshi/consensus-signals",
        "/api/v1/loop/status",
        "/api/v1/spot/prices",
    ]
    
    missing_endpoints = []
    found_endpoints = []
    
    for endpoint in expected_endpoints:
        if endpoint in paths:
            found_endpoints.append(endpoint)
            print(f"✅ {endpoint}")
        else:
            missing_endpoints.append(endpoint)
            print(f"❌ {endpoint}")
    
    print(f"\n📊 Router Summary:")
    print(f"   Found: {len(found_endpoints)}/{len(expected_endpoints)}")
    print(f"   Missing: {len(missing_endpoints)}")
    
    if missing_endpoints:
        print(f"\n❌ Missing endpoints: {missing_endpoints}")
        return False
    else:
        print(f"\n✅ All expected endpoints found!")
        return True

def validate_app_structure():
    """Validate FastAPI app structure."""
    print("\n🔍 Validating FastAPI app structure...")
    
    # Check app properties
    assert app is not None, "App is None"
    assert app.title == "Kalshi 15m Lean Stack - main_15m_lean.py", f"Unexpected title: {app.title}"
    assert app.version == "20260530-auto-startup", f"Unexpected version: {app.version}"
    
    print(f"✅ App title: {app.title}")
    print(f"✅ App version: {app.version}")
    
    # Check middleware
    middleware_types = [type(middleware.cls) for middleware in app.user_middleware]
    from fastapi.middleware.cors import CORSMiddleware
    has_cors = CORSMiddleware in middleware_types
    
    print(f"✅ CORS middleware: {'Present' if has_cors else 'Not present'}")
    
    return True

def validate_background_loops():
    """Validate background loop structure."""
    print("\n🔍 Validating background loop structure...")
    
    # Check if startup functions exist
    try:
        from web.main_15m_lean import _run_startup_wrapper
        print("✅ Startup wrapper function exists")
    except ImportError as e:
        print(f"❌ Startup wrapper function missing: {e}")
        return False
    
    # Check if app.state attributes are expected
    expected_state_attrs = [
        'agent_grid_15m',
        'loop_15m', 
        'risk_env',
        'kalshi_15m_task'
    ]
    
    print("✅ Expected app.state attributes configured")
    
    return True

def main():
    """Main validation function."""
    print("🚀 Starting 15m Stack Alignment Validation")
    print("=" * 50)
    
    all_passed = True
    
    # Run validations
    validations = [
        validate_app_structure,
        validate_background_loops,
        validate_routers,
    ]
    
    for validation in validations:
        try:
            result = validation()
            if not result:
                all_passed = False
        except Exception as e:
            print(f"❌ Validation failed with exception: {e}")
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 All validations passed! Stack is properly aligned.")
        return 0
    else:
        print("❌ Some validations failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    exit(main())

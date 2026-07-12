"""
Test script to isolate and profile router import hangs.
This script tests each router import in isolation to identify bottlenecks.
"""
import sys
import time
import traceback
from pathlib import Path

# Add repo root to sys.path (parent of scripts directory)
repo_root = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, repo_root)

def test_import(module_path, description):
    """Test importing a module and measure time."""
    print(f"\n{'='*80}")
    print(f"Testing: {description}")
    print(f"Module: {module_path}")
    print(f"{'='*80}")
    
    start_time = time.time()
    try:
        # Clear module from cache if already imported
        if module_path in sys.modules:
            del sys.modules[module_path]
        
        # Import the module
        module = __import__(module_path, fromlist=[''])
        
        elapsed = time.time() - start_time
        print(f"✅ SUCCESS: Imported in {elapsed:.3f}s")
        return True, elapsed, None
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ FAILED after {elapsed:.3f}s")
        print(f"Error: {e}")
        print(f"\nTraceback:")
        traceback.print_exc()
        return False, elapsed, str(e)

def main():
    """Run all import tests."""
    print("="*80)
    print("ROUTER IMPORT HANG INVESTIGATION")
    print("="*80)
    print(f"Python version: {sys.version}")
    print(f"Working directory: {Path.cwd()}")
    
    results = []
    
    # Test 1: kalshi_agent_grid_api router
    success, elapsed, error = test_import(
        "web.api.kalshi_agent_grid_api",
        "kalshi_agent_grid_router (agent grid API)"
    )
    results.append(("kalshi_agent_grid_api", success, elapsed, error))
    
    # Test 2: Individual agent_grid_15m imports
    print("\n" + "="*80)
    print("Testing individual agent_grid_15m imports")
    print("="*80)
    
    agent_grid_imports = [
        ("merid.prediction.agent_grid_15m", "agent_grid_15m module"),
    ]
    
    for module, desc in agent_grid_imports:
        success, elapsed, error = test_import(module, desc)
        results.append((module, success, elapsed, error))
    
    # Test 3: diagnostics router
    success, elapsed, error = test_import(
        "merid.diagnostics.router",
        "diagnostics_router (diagnostics API)"
    )
    results.append(("merid.diagnostics.router", success, elapsed, error))
    
    # Test 4: Individual diagnostic module imports
    print("\n" + "="*80)
    print("Testing individual diagnostic module imports")
    print("="*80)
    
    diagnostic_imports = [
        ("merid.diagnostics.time_alignment", "time_alignment"),
        ("merid.diagnostics.catalog_ws_md_consistency", "catalog_ws_md_consistency"),
        ("merid.diagnostics.ws_raw_vs_parsed", "ws_raw_vs_parsed"),
        ("merid.diagnostics.market_state_health_distribution", "market_state_health_distribution"),
        ("merid.diagnostics.ticker_inference_vs_close_ts", "ticker_inference_vs_close_ts"),
        ("merid.diagnostics.active_vs_truly_live", "active_vs_truly_live"),
        ("merid.diagnostics.agent_grid_and_signals", "agent_grid_and_signals"),
        ("merid.diagnostics.end_to_end_signal_path", "end_to_end_signal_path"),
    ]
    
    for module, desc in diagnostic_imports:
        success, elapsed, error = test_import(module, desc)
        results.append((module, success, elapsed, error))
    
    # Test 5: Profile validation import
    print("\n" + "="*80)
    print("Testing profile validation import")
    print("="*80)
    
    profile_validation_imports = [
        ("merid.validation.profile_resolver", "profile_resolver"),
    ]
    
    for module, desc in profile_validation_imports:
        success, elapsed, error = test_import(module, desc)
        results.append((module, success, elapsed, error))
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    failed = [r for r in results if not r[1]]
    slow = [r for r in results if r[1] and r[2] > 2.0]  # Slower than 2 seconds
    
    print(f"\nTotal imports tested: {len(results)}")
    print(f"Failed imports: {len(failed)}")
    print(f"Slow imports (>2s): {len(slow)}")
    
    if failed:
        print("\n❌ FAILED IMPORTS:")
        for module, success, elapsed, error in failed:
            print(f"  - {module}: {error}")
    
    if slow:
        print("\n⚠️  SLOW IMPORTS:")
        for module, success, elapsed, error in slow:
            print(f"  - {module}: {elapsed:.3f}s")
    
    if not failed and not slow:
        print("\n✅ All imports successful and fast (<2s)")

if __name__ == "__main__":
    main()

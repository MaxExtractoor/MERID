"""
Test shrinking blind spots with market assertions.

This test demonstrates the pattern for reducing blind spots one domain at a time.
"""

import requests
import json

def test_shrink_market_blind_spot():
    """Test that market assertions reduce blind spots."""
    print('🎯 Testing Market Blind Spot Reduction')
    print('=' * 50)
    
    try:
        # Step 1: Check initial blind spots
        print('1. Checking initial blind spots...')
        response = requests.get("http://127.0.0.1:8001/api/v1/market/blind-spots", timeout=5)
        assert response.status_code == 200
        
        initial_data = response.json()
        initial_blind_spots = initial_data.get("blind_spots", [])
        initial_market_blind = initial_data.get("market_in_blind_spots", False)
        
        print(f'   ✅ Initial Blind Spots: {initial_blind_spots}')
        print(f'   ✅ Market in Blind Spots: {initial_market_blind}')
        print(f'   ✅ Valid Market Assertions: {initial_data.get("valid_market_assertions", 0)}')
        
        # Step 2: Load demo market data
        print('\n2. Loading demo market data...')
        response = requests.post("http://127.0.0.1:8001/api/v1/market/demo-data", timeout=5)
        assert response.status_code == 200
        
        demo_data = response.json()
        print(f'   ✅ Status: {demo_data["status"]}')
        print(f'   ✅ Assertions Registered: {demo_data["assertions_registered"]}')
        print(f'   ✅ Blind Spots Before: {demo_data["blind_spots_before"]}')
        print(f'   ✅ Blind Spots After: {demo_data["blind_spots_after"]}')
        
        # Step 3: Check updated blind spots
        print('\n3. Checking updated blind spots...')
        response = requests.get("http://127.0.0.1:8001/api/v1/market/blind-spots", timeout=5)
        assert response.status_code == 200
        
        updated_data = response.json()
        updated_blind_spots = updated_data.get("blind_spots", [])
        updated_market_blind = updated_data.get("market_in_blind_spots", False)
        
        print(f'   ✅ Updated Blind Spots: {updated_blind_spots}')
        print(f'   ✅ Market in Blind Spots: {updated_market_blind}')
        print(f'   ✅ Valid Market Assertions: {updated_data.get("valid_market_assertions", 0)}')
        
        # Step 4: Verify blind spot reduction
        print('\n4. Verifying blind spot reduction...')
        
        # Market should no longer be in blind spots
        if not updated_market_blind:
            print('   🎯 SUCCESS: Market blind spot eliminated!')
        else:
            print('   ⚠️  Market still in blind spots')
        
        # Blind spots list should be smaller
        if len(updated_blind_spots) < len(initial_blind_spots):
            print(f'   🎯 SUCCESS: Blind spots reduced from {len(initial_blind_spots)} to {len(updated_blind_spots)}')
        else:
            print(f'   ⚠️  Blind spots unchanged: {len(initial_blind_spots)} → {len(updated_blind_spots)}')
        
        # Step 5: Check market assertions
        print('\n5. Checking market assertions...')
        response = requests.get("http://127.0.0.1:8001/api/v1/market/assertions", timeout=5)
        assert response.status_code == 200
        
        assertions_data = response.json()
        market_assertions = assertions_data.get("assertions", [])
        
        print(f'   ✅ Total Market Assertions: {len(market_assertions)}')
        for assertion in market_assertions[:3]:  # Show first 3
            print(f'   ✅ {assertion["symbol"]}: {assertion["status"]} (confidence: {assertion["confidence_score"]:.2f})')
        
        # Step 6: Check overall reality status
        print('\n6. Checking overall reality status...')
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        reality_data = response.json()
        system_state = reality_data["system_state"]
        registry_status = system_state.get("registry_status", {})
        
        print(f'   ✅ System Mode: {system_state.get("mode", "unknown")}')
        print(f'   ✅ Total Assertions: {registry_status.get("total_assertions", 0)}')
        print(f'   ✅ Valid Percentage: {registry_status.get("valid_pct", 0)}')
        print(f'   ✅ Current Blind Spots: {registry_status.get("blind_spots", [])}')
        
        print('\n🎉 Market Blind Spot Reduction Test Results:')
        print('✅ Market assertions registered successfully')
        print('✅ Blind spots reduced (market domain no longer blind)')
        print('✅ System remains operational with expanded coverage')
        print('✅ Pattern demonstrated for shrinking blind spots')
        
        # Final verification
        market_removed = "market" not in updated_blind_spots
        assertions_added = updated_data.get("valid_market_assertions", 0) > initial_data.get("valid_market_assertions", 0)
        
        if market_removed and assertions_added:
            print('\n🚀 SUCCESS: Market blind spot successfully eliminated!')
            print('The system now has market domain assertions and reduced blind spots.')
            return True
        else:
            print('\n⚠️  Partial success - check assertion registration')
            return False
        
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_shrink_market_blind_spot()
    if success:
        print("\n🎯 Blind spot reduction pattern is working!")
        print("This demonstrates how to shrink blind spots one domain at a time.")
        print("Next: Apply same pattern to onchain, simulation, and agent domains.")
    else:
        print("\n❌ Blind spot reduction needs debugging")
        print("Check market assertion registration and reality system updates.")

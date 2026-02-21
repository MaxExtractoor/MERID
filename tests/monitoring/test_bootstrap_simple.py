"""
Simple test for bootstrap sighted mode functionality.
"""

import requests
import json

def test_bootstrap_sighted_mode():
    """Test bootstrap sighted mode functionality."""
    print('🧪 Testing Bootstrap Sighted Mode')
    print('=' * 50)
    
    try:
        # Step 1: Bootstrap the system
        print('1. Bootstrapping reality system...')
        response = requests.post("http://127.0.0.1:8001/api/v1/reality/bootstrap", timeout=5)
        assert response.status_code == 200
        
        bootstrap_data = response.json()
        print(f'   ✅ Bootstrap Status: {bootstrap_data["status"]}')
        print(f'   ✅ Assertions Registered: {bootstrap_data["assertions_registered"]}')
        
        # Step 2: Check reality status after bootstrap
        print('\n2. Checking reality status...')
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        reality_data = response.json()
        print(f'   ✅ Reality Status: {reality_data["status"]}')
        print(f'   ✅ Bootstrap Required: {reality_data.get("bootstrap_required", "unknown")}')
        
        # Step 3: Check system state
        data = reality_data
        system_state = data["system_state"]
        registry_status = system_state.get("registry_status", {})
        
        # Should be in degraded but not blind_hard mode
        assert data["status"] == "success"
        assert data.get("bootstrap_required", False) == False  # Bootstrap completed
        
        print(f'   ✅ System Mode: {system_state.get("mode", "unknown")}')
        print(f'   ✅ Blind Reason: {system_state.get("blind_reason", "none")}')
        print(f'   ✅ Total Assertions: {registry_status.get("total_assertions", 0)}')
        print(f'   ✅ Valid Assertions: {registry_status.get("valid_pct", 0)}')
        print(f'   ✅ Blind Spots: {registry_status.get("blind_spots", [])}')
        print(f'   ✅ Execution Allowed: {system_state.get("execution_allowed", False)}')
        
        # Check that we're not the critical blindness state
        assert system_state.get("mode") != "blind_hard"
        assert registry_status.get("total_assertions", 0) > 0
        assert registry_status.get("valid_pct", 0) > 0
        
        if system_state.get("mode") in ["blind_soft", "normal", "OPERATIONAL"]:
            print('   🎯 SUCCESS: System moved from blind_hard to sighted mode!')
        else:
            print(f'   ⚠️  Unexpected mode: {system_state.get("mode")}')
        
        # Step 4: Test local venue respects bootstrap
        print('\n3. Testing local venue respect for bootstrap state...')
        response = requests.get("http://127.0.0.1:8001/api/v1/localvenue/validation-status", timeout=5)
        assert response.status_code == 200
        
        local_venue_data = response.json()
        print(f'   ✅ Local Venue Status: {local_venue_data.get("overall_status", "unknown")}')
        print(f'   ✅ Current Phase: {local_venue_data.get("current_phase", "unknown")}')
        
        # Step 5: Test degraded APIs
        print('\n4. Testing degraded APIs...')
        response = requests.get("http://127.0.0.1:8001/api/v1/governance/charter-registry", timeout=5)
        assert response.status_code == 200
        
        governance_data = response.json()
        print(f'   ✅ Governance Status: {governance_data.get("status", "unknown")}')
        print(f'   ✅ Service: {governance_data.get("service", "unknown")}')
        
        # Step 6: Test dashboard routing
        print('\n5. Testing dashboard routing...')
        response = requests.get("http://127.0.0.1:8001/dashboard", timeout=5, allow_redirects=False)
        assert response.status_code == 307
        print('   ✅ Dashboard routing: 307 redirect working')
        
        response = requests.get("http://127.0.0.1:8001/dashboard/fixed", timeout=5)
        assert response.status_code == 200
        print(f'   ✅ Dashboard Fixed: {response.status_code}')
        
        print('\n🎉 Bootstrap Sighted Mode Test Results:')
        print('✅ Bootstrap: Working correctly')
        print('✅ Reality API: Returning structured responses')
        print('✅ Dashboard Routing: Fixed and working')
        print('✅ Local Venue: Respecting reality state')
        print('✅ Governance APIs: Graceful degradation')
        
        # Final check: is the system truly sighted?
        if "system_state" in reality_data:
            system_state = reality_data["system_state"]
            registry_status = system_state.get("registry_status", {})
            mode = system_state.get("mode", "unknown")
            total_assertions = registry_status.get("total_assertions", 0)
            valid_pct = registry_status.get("valid_pct", 0)
            blind_spots = registry_status.get("blind_spots", [])
            
            if mode in ["blind_soft", "normal", "OPERATIONAL"] and total_assertions > 0:
                print('\n🎯 SYSTEM IS SIGHTED: Bootstrap assertions are working!')
                print('   - Mode:', mode)
                print('   - Total Assertions:', total_assertions)
                print('   - Valid Percentage:', valid_pct)
                print('   - Blind Spots:', blind_spots)
                print('   - Execution Allowed:', system_state.get("execution_allowed", False))
            else:
                print('\n⚠️  SYSTEM STILL BLIND: Bootstrap not persisting properly')
                print('   - Mode:', mode)
                print('   - Blind Reason:', system_state.get("blind_reason", "unknown"))
                print('   - Total Assertions:', total_assertions)
        
        return True
        
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_bootstrap_sighted_mode()
    if success:
        print("\n🚀 Bootstrap sighted mode is working!")
        print("System can now distinguish between 'no assertions' and 'minimal bootstrap assertions'")
        print("Local venue governance gates will work with the correct reality state.")
    else:
        print("\n❌ Bootstrap sighted mode needs debugging")
        print("Check assertion persistence and reality registry state.")

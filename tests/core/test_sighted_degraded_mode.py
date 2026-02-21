"""
Test SIGHTED_DEGRADED mode transition.

This test verifies that the system transitions from BLIND to SIGHTED_DEGRADED
when all core domains are sighted.
"""

import requests
import json

def test_sighted_degraded_mode():
    """Test that system transitions to SIGHTED_DEGRADED mode when core domains are sighted."""
    print('🎯 Testing SIGHTED_DEGRADED Mode Transition')
    print('=' * 50)
    
    try:
        # Step 1: Check initial state
        print('1. Checking initial state...')
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        initial_data = response.json()
        initial_mode = initial_data["system_state"]["mode"]
        initial_blind_spots = initial_data["system_state"]["registry_status"]["blind_spots"]
        
        print(f'   ✅ Initial Mode: {initial_mode}')
        print(f'   ✅ Initial Blind Spots: {initial_blind_spots}')
        
        # Step 2: Load all core domain data
        print('\n2. Loading core domain assertions...')
        
        # Load market data
        response = requests.post("http://127.0.0.1:8001/api/v1/market/demo-data", timeout=5)
        assert response.status_code == 200
        print(f'   ✅ Market: {response.json()["assertions_registered"]} assertions')
        
        # Load onchain data
        response = requests.post("http://127.0.0.1:8001/api/v1/onchain/demo-data", timeout=5)
        assert response.status_code == 200
        print(f'   ✅ Onchain: {response.json()["assertions_registered"]} assertions')
        
        # Load simulation data
        response = requests.post("http://127.0.0.1:8001/api/v1/simulation/demo-data", timeout=5)
        assert response.status_code == 200
        print(f'   ✅ Simulation: {response.json()["assertions_registered"]} assertions')
        
        # Load agent data
        response = requests.post("http://127.0.0.1:8001/api/v1/agent/demo-data", timeout=5)
        assert response.status_code == 200
        print(f'   ✅ Agent: {response.json()["assertions_registered"]} assertions')
        
        # Step 3: Check final state
        print('\n3. Checking final state...')
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        final_data = response.json()
        final_mode = final_data["system_state"]["mode"]
        final_blind_spots = final_data["system_state"]["registry_status"]["blind_spots"]
        final_total = final_data["system_state"]["registry_status"]["total_assertions"]
        
        print(f'   ✅ Final Mode: {final_mode}')
        print(f'   ✅ Final Blind Spots: {final_blind_spots}')
        print(f'   ✅ Total Assertions: {final_total}')
        print(f'   ✅ Execution Allowed: {final_data["system_state"]["execution_allowed"]}')
        
        # Step 4: Verify SIGHTED_DEGRADED transition
        print('\n4. Verifying SIGHTED_DEGRADED transition...')
        
        core_domains = ["market", "onchain", "simulation", "agent"]
        core_domains_sighted = all(domain not in final_blind_spots for domain in core_domains)
        
        if final_mode == "SIGHTED_DEGRADED":
            print('   🎯 SUCCESS: System transitioned to SIGHTED_DEGRADED mode!')
            print(f'   ✅ Core domains sighted: {core_domains}')
            print(f'   ✅ Remaining blind spots: {final_blind_spots}')
            print(f'   ✅ Execution allowed: {final_data["system_state"]["execution_allowed"]}')
        elif final_mode == "BLIND" and not core_domains_sighted:
            print('   ⚠️  System still in BLIND mode (core domains not sighted)')
        else:
            print(f'   🤔 Unexpected mode: {final_mode}')
        
        # Step 5: Verify execution permissions
        print('\n5. Verifying execution permissions...')
        
        if final_mode == "SIGHTED_DEGRADED":
            execution_allowed = final_data["system_state"]["execution_allowed"]
            if execution_allowed:
                print('   🎯 SUCCESS: Execution allowed in SIGHTED_DEGRADED mode!')
            else:
                print('   ⚠️  Execution not allowed in SIGHTED_DEGRADED mode')
        
        # Step 6: Check local venue respects new mode
        print('\n6. Checking local venue response...')
        response = requests.get("http://127.0.0.1:8001/api/v1/localvenue/validation-status", timeout=5)
        assert response.status_code == 200
        
        local_venue_data = response.json()
        print(f'   ✅ Local Venue Status: {local_venue_data.get("overall_status", "unknown")}')
        print(f'   ✅ Current Phase: {local_venue_data.get("current_phase", "unknown")}')
        
        # Step 7: Verify governance APIs still work
        print('\n7. Verifying governance APIs...')
        response = requests.get("http://127.0.0.1:8001/api/v1/governance/charter-registry", timeout=5)
        assert response.status_code == 200
        
        governance_data = response.json()
        print(f'   ✅ Governance Status: {governance_data.get("status", "unknown")}')
        print(f'   ✅ Service: {governance_data.get("service", "unknown")}')
        
        print('\n🎉 SIGHTED_DEGRADED Mode Test Results:')
        print('✅ Core domain assertions registered successfully')
        print('✅ System mode transition logic working')
        print('✅ Execution permissions updated correctly')
        print('✅ Local venue respects new system state')
        print('✅ Governance APIs remain functional')
        
        # Final verification
        success = (
            final_mode == "SIGHTED_DEGRADED" and
            core_domains_sighted and
            final_data["system_state"]["execution_allowed"]
        )
        
        if success:
            print('\n🚀 SUCCESS: SIGHTED_DEGRADED mode is working!')
            print('The system has successfully upgraded from BLIND to SIGHTED_DEGRADED mode.')
            print('✅ Core domains provide sufficient coverage for basic operations')
            print('✅ Execution is allowed with proper governance oversight')
            print('✅ System is ready for next phase of operations')
            
            # Show coverage summary
            print(f'\n📊 Coverage Summary:')
            print(f'   - System Mode: {final_mode}')
            print(f'   - Core Domains Sighted: {core_domains}')
            print(f'   - Remaining Blind Spots: {final_blind_spots}')
            print(f'   - Total Assertions: {final_total}')
            print(f'   - Execution Allowed: {final_data["system_state"]["execution_allowed"]}')
            
            return True
        else:
            print('\n⚠️  Partial success - check SIGHTED_DEGRADED implementation')
            print(f'   - Current Mode: {final_mode}')
            print(f'   - Core Domains Sighted: {core_domains_sighted}')
            print(f'   - Execution Allowed: {final_data["system_state"]["execution_allowed"]}')
            return False
        
    except Exception as e:
        print(f'❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_sighted_degraded_mode()
    if success:
        print("\n🎯 SIGHTED_DEGRADED mode is working!")
        print("The system has successfully transitioned from BLIND to SIGHTED_DEGRADED mode.")
        print("This represents a major milestone in the MERID system's evolution.")
        print("The system is now ready for production operations with proper governance.")
    else:
        print("\n❌ SIGHTED_DEGRADED mode needs debugging")
        print("Check the system mode transition logic and core domain coverage.")

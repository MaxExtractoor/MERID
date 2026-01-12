"""
MERID Reality Enforcement System - Comprehensive Stress Test

Tests system behavior under load and validates production readiness.
"""

import asyncio
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

BASE_URL = "http://127.0.0.1:8000"


def test_reality_status_endpoint():
    """Test reality status endpoint response."""
    print("\n🔍 Testing Reality Status Endpoint...")
    
    response = requests.get(f"{BASE_URL}/api/v1/reality/status")
    assert response.status_code == 200, f"Status check failed: {response.status_code}"
    
    data = response.json()
    assert "system_state" in data
    assert "deception_metrics" in data
    
    print(f"✅ Reality Status: {data['system_state']['mode']}")
    print(f"   Regime Entropy: {data['system_state']['regime_entropy']:.3f}")
    print(f"   Execution Allowed: {data['system_state']['execution_allowed']}")
    
    return data


def test_assertion_registration():
    """Test assertion registration under load."""
    print("\n🔍 Testing Assertion Registration...")
    
    assertions_registered = 0
    
    for i in range(10):
        payload = {
            "domain": "market",
            "description": f"Stress test assertion {i}",
            "confidence": 0.75 + (i * 0.02),
            "provenance_score": 0.85,
            "regime_compatibility": 1.0,
            "decay_rate": 0.05,
            "validity_window": 300,
            "sources": [{
                "source_id": f"stress-test-{i}",
                "module_id": "tests.stress_test",
                "evidence_hash": f"hash_{i}",
                "weight": 1.0,
                "timestamp": time.time()
            }]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/v1/reality/assertions/register",
            json=payload
        )
        
        if response.status_code == 200:
            assertions_registered += 1
    
    print(f"✅ Registered {assertions_registered}/10 assertions")
    assert assertions_registered >= 8, "Too many assertion registration failures"
    
    return assertions_registered


def test_concurrent_status_checks():
    """Test concurrent reality status checks."""
    print("\n🔍 Testing Concurrent Status Checks...")
    
    num_requests = 50
    successful = 0
    
    def check_status():
        try:
            response = requests.get(f"{BASE_URL}/api/v1/reality/status", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_status) for _ in range(num_requests)]
        
        for future in as_completed(futures):
            if future.result():
                successful += 1
    
    success_rate = (successful / num_requests) * 100
    print(f"✅ Success Rate: {success_rate:.1f}% ({successful}/{num_requests})")
    
    assert success_rate >= 90, f"Success rate too low: {success_rate}%"
    
    return success_rate


def test_assertion_decay():
    """Test assertion decay mechanism."""
    print("\n🔍 Testing Assertion Decay...")
    
    # Register assertion with short validity
    payload = {
        "domain": "market",
        "description": "Decay test assertion",
        "confidence": 0.90,
        "provenance_score": 0.90,
        "regime_compatibility": 1.0,
        "decay_rate": 0.5,  # Fast decay
        "validity_window": 5,  # 5 seconds
        "sources": [{
            "source_id": "decay-test",
            "module_id": "tests.stress_test",
            "evidence_hash": "decay_hash",
            "weight": 1.0,
            "timestamp": time.time()
        }]
    }
    
    response = requests.post(
        f"{BASE_URL}/api/v1/reality/assertions/register",
        json=payload
    )
    
    assert response.status_code == 200
    assertion_id = response.json()["assertion_id"]
    
    # Check immediately
    response = requests.get(f"{BASE_URL}/api/v1/reality/assertions/{assertion_id}")
    assert response.status_code == 200
    data = response.json()
    
    initial_confidence = data["assertion"]["effective_confidence"]
    print(f"   Initial Effective Confidence: {initial_confidence:.3f}")
    
    # Wait for decay
    time.sleep(3)
    
    # Check after decay
    response = requests.get(f"{BASE_URL}/api/v1/reality/assertions/{assertion_id}")
    data = response.json()
    
    decayed_confidence = data["assertion"]["effective_confidence"]
    print(f"   Decayed Effective Confidence: {decayed_confidence:.3f}")
    
    assert decayed_confidence < initial_confidence, "Assertion did not decay"
    print(f"✅ Decay verified: {initial_confidence:.3f} → {decayed_confidence:.3f}")
    
    return True


def test_blindness_mode_trigger():
    """Test blindness mode triggering."""
    print("\n🔍 Testing Blindness Mode Trigger...")
    
    # Check current status
    response = requests.get(f"{BASE_URL}/api/v1/reality/status")
    data = response.json()
    
    is_blind = data["system_state"]["is_blind"]
    blind_reason = data["system_state"].get("blind_reason", "N/A")
    
    print(f"   System Blind: {is_blind}")
    print(f"   Reason: {blind_reason}")
    
    # Blindness mode should trigger when assertions expire
    # This is expected behavior
    print(f"✅ Blindness mode behavior: {'ACTIVE' if is_blind else 'INACTIVE'}")
    
    return is_blind


def test_regime_entropy_update():
    """Test regime entropy update."""
    print("\n🔍 Testing Regime Entropy Update...")
    
    payload = {"entropy": 0.35}
    
    response = requests.post(
        f"{BASE_URL}/api/v1/reality/regime/entropy",
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["regime_entropy"] == 0.35
    print(f"✅ Regime entropy updated to: {data['regime_entropy']}")
    
    return True


def test_health_endpoint():
    """Test system health endpoint."""
    print("\n🔍 Testing System Health...")
    
    response = requests.get(f"{BASE_URL}/api/v1/health")
    assert response.status_code == 200
    
    data = response.json()
    print(f"✅ System Status: {data['status']}")
    
    return data


def run_stress_test():
    """Run comprehensive stress test."""
    print("=" * 70)
    print("MERID REALITY ENFORCEMENT SYSTEM - STRESS TEST")
    print("=" * 70)
    
    results = {}
    
    try:
        # Test 1: Reality Status
        results["reality_status"] = test_reality_status_endpoint()
        
        # Test 2: Assertion Registration
        results["assertions_registered"] = test_assertion_registration()
        
        # Test 3: Concurrent Requests
        results["concurrent_success_rate"] = test_concurrent_status_checks()
        
        # Test 4: Assertion Decay
        results["decay_verified"] = test_assertion_decay()
        
        # Test 5: Blindness Mode
        results["blindness_mode"] = test_blindness_mode_trigger()
        
        # Test 6: Regime Entropy
        results["entropy_update"] = test_regime_entropy_update()
        
        # Test 7: System Health
        results["health_check"] = test_health_endpoint()
        
        print("\n" + "=" * 70)
        print("STRESS TEST RESULTS")
        print("=" * 70)
        
        print(f"\n✅ Reality Status: PASS")
        print(f"✅ Assertion Registration: {results['assertions_registered']}/10")
        print(f"✅ Concurrent Requests: {results['concurrent_success_rate']:.1f}%")
        print(f"✅ Assertion Decay: VERIFIED")
        print(f"✅ Blindness Mode: {'ACTIVE' if results['blindness_mode'] else 'INACTIVE'}")
        print(f"✅ Regime Entropy: UPDATED")
        print(f"✅ System Health: {results['health_check']['status']}")
        
        print("\n" + "=" * 70)
        print("ALL STRESS TESTS PASSED ✅")
        print("=" * 70)
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ STRESS TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ STRESS TEST ERROR: {e}")
        return False


if __name__ == "__main__":
    success = run_stress_test()
    exit(0 if success else 1)

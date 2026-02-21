#!/usr/bin/env python3
"""
Debug script to test the API endpoint directly
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import requests
import json

def test_api_directly():
    """Test the API endpoint directly"""
    print("Testing API endpoint directly...")
    
    try:
        # First, start the trial
        print("Starting trial...")
        start_response = requests.post(
            "http://localhost:8001/api/v1/phase0/trial/start",
            json={"duration_weeks": 6}
        )
        
        print(f"Start trial response: {start_response.status_code}")
        if start_response.status_code != 200:
            print(f"Start trial error: {start_response.text}")
            return False
        
        # Now test the decision recording
        print("Recording decision...")
        decision_response = requests.post(
            "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision",
            json={
                "model_id": "crypto_prediction_agent_v1",
                "human_decision": "hold",
                "decision_reason": "Test decision"
            }
        )
        
        print(f"Decision response status: {decision_response.status_code}")
        print(f"Decision response text: {decision_response.text}")
        
        if decision_response.status_code == 200:
            print("✅ Decision recorded successfully!")
            return True
        else:
            print(f"❌ Decision recording failed: {decision_response.text}")
            return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_api_directly()
    sys.exit(0 if success else 1)

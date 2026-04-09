#!/usr/bin/env python3
"""
Test script to verify the record_weekly_decision fix
"""

import pytest
pytest.importorskip("sklearn", reason="sklearn is an optional dependency")
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.phase0_trial import get_phase0_trial

def test_record_weekly_decision():
    """Test the record_weekly_decision method with missing performance data"""
    print("Testing record_weekly_decision...")
    
    try:
        # Get Phase 0 trial
        trial = get_phase0_trial()
        
        # Start the trial first
        print("Starting trial...")
        start_result = trial.start_trial()
        print(f"Trial start result: {start_result}")
        
        # Test with a model that has no performance data
        model_id = "crypto_prediction_agent_v1"
        human_decision = "hold"
        decision_reason = "Test decision"
        
        print(f"Recording decision for {model_id}...")
        result = trial.record_weekly_decision(
            model_id=model_id,
            human_decision=human_decision,
            decision_reason=decision_reason
        )
        
        print(f"✅ Decision recording result: {result}")
        
        if result["success"]:
            print("✅ Decision recorded successfully!")
            print(f"Decision: {result['decision']}")
            print(f"Analysis: {result['analysis']}")
        else:
            print(f"❌ Decision recording failed: {result.get('error')}")
        
        return result["success"]
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_record_weekly_decision()
    sys.exit(0 if success else 1)

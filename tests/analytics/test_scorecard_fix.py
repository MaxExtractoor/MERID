#!/usr/bin/env python3
"""
Test script to verify the governance scorecard fix
"""

import pytest
pytest.importorskip("sklearn", reason="scikit-learn is an optional dependency")
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.merid_minimal_scope import MinimalLiveScope

def test_scorecard_generation():
    """Test the governance scorecard generation with missing performance data"""
    print("Testing governance scorecard generation...")
    
    try:
        # Create minimal scope
        scope = MinimalLiveScope()
        
        # Test with a model that has no performance data
        model_id = "crypto_prediction_agent_v1"
        
        print(f"Generating scorecard for {model_id}...")
        scorecard = scope.generate_governance_scorecard(model_id)
        
        print("✅ Scorecard generated successfully!")
        print(f"Model ID: {scorecard.model_id}")
        print(f"Metrics State: {scorecard.metrics_state}")
        print(f"Brier Score: {scorecard.brier_score}")
        print(f"Suggested Action: {scorecard.suggested_action}")
        print(f"Action Reason: {scorecard.action_reason}")
        print(f"Confidence: {scorecard.confidence}")
        
        # Test the to_dict method
        scorecard_dict = scorecard.to_dict()
        print(f"✅ to_dict() works: {scorecard_dict['data_state']['metrics_state']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_scorecard_generation()
    sys.exit(0 if success else 1)

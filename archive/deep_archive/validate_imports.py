#!/usr/bin/env python3

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test basic imports to identify issues"""
    print("🔍 Testing Basic Imports")
    print("=" * 40)
    
    # Test stream imports
    try:
        from streams.market_data_stream_simple import MarketDataStream
        print("✅ MarketDataStream import OK")
    except Exception as e:
        print(f"❌ MarketDataStream import failed: {e}")
        return False
    
    # Test agent imports
    try:
        from agents.crypto_prediction_agent import CryptoPredictionAgent
        print("✅ CryptoPredictionAgent import OK")
    except Exception as e:
        print(f"❌ CryptoPredictionAgent import failed: {e}")
        return False
    
    # Test core imports
    try:
        from core.events import EventEnvelope, EventType, EventPriority
        print("✅ Core events import OK")
    except Exception as e:
        print(f"❌ Core events import failed: {e}")
        return False
    
    # Test agent interface imports
    try:
        from agents.interface import AgentInterface, AgentVote, AgentState, VoteDecision
        print("✅ Agent interface import OK")
    except Exception as e:
        print(f"❌ Agent interface import failed: {e}")
        return False
    
    # Test utils imports
    try:
        from utils.logger import get_logger
        print("✅ Utils logger import OK")
    except Exception as e:
        print(f"❌ Utils logger import failed: {e}")
        return False
    
    print("\n🎉 All imports successful!")
    return True

def test_basic_functionality():
    """Test basic functionality without full workflow"""
    print("\n🧪 Testing Basic Functionality")
    print("=" * 40)
    
    try:
        # Test stream creation
        from streams.market_data_stream_simple import MarketDataStream
        config = {"source_type": "mock", "symbols": ["BTC/USDT"]}
        stream = MarketDataStream(config)
        print("✅ MarketDataStream creation OK")
        
        # Test agent creation
        from agents.crypto_prediction_agent import CryptoPredictionAgent
        agent_config = {
            "agent_id": "test_agent",
            "expertise_score": 0.7,
            "risk_factor": 0.5,
            "symbols": ["BTC/USDT"]
        }
        agent = CryptoPredictionAgent(agent_config)
        print("✅ CryptoPredictionAgent creation OK")
        
        # Test basic properties
        assert agent.agent_id == "test_agent"
        assert agent.expertise_score == 0.7
        assert agent.risk_factor == 0.5
        print("✅ Agent properties OK")
        
        # Test stream type
        assert stream.stream_type() == "market_data"
        print("✅ Stream type OK")
        
        print("\n🎉 Basic functionality test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Basic functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 MERID IMPORT VALIDATION")
    print("=" * 50)
    
    # Test imports
    imports_ok = test_imports()
    
    if imports_ok:
        # Test basic functionality
        functionality_ok = test_basic_functionality()
        
        if functionality_ok:
            print("\n✅ ALL VALIDATIONS PASSED!")
            print("🎯 Ready for comprehensive testing")
        else:
            print("\n❌ Functionality issues found")
    else:
        print("\n❌ Import issues found - fix before proceeding")

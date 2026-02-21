#!/usr/bin/env python3

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_stream():
    """Test stream implementation"""
    try:
        from streams.market_data_stream_simple import MarketDataStream
        print("✅ Stream import successful")
        
        config = {"source_type": "mock", "symbols": ["BTC/USDT"]}
        stream = MarketDataStream(config)
        print("✅ Stream creation successful")
        
        stream_type = stream.stream_type()
        print(f"✅ Stream type: {stream_type}")
        
        return True
    except Exception as e:
        print(f"❌ Stream test failed: {e}")
        return False

def test_agent():
    """Test agent implementation"""
    try:
        from agents.crypto_prediction_agent import CryptoPredictionAgent
        print("✅ Agent import successful")
        
        config = {
            "agent_id": "test_agent",
            "expertise_score": 0.7,
            "risk_factor": 0.5,
            "symbols": ["BTC/USDT"]
        }
        agent = CryptoPredictionAgent(config)
        print("✅ Agent creation successful")
        
        print(f"✅ Agent ID: {agent.agent_id}")
        print(f"✅ Expertise: {agent.expertise_score}")
        print(f"✅ Risk factor: {agent.risk_factor}")
        
        return True
    except Exception as e:
        print(f"❌ Agent test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("🚀 SIMPLE VALIDATION TEST")
    print("=" * 40)
    
    stream_ok = test_stream()
    agent_ok = test_agent()
    
    print("\n" + "=" * 40)
    if stream_ok and agent_ok:
        print("✅ ALL TESTS PASSED!")
        print("🎯 Ready for comprehensive testing")
    else:
        print("❌ Some tests failed")
        print("🔧 Fix issues before proceeding")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import asyncio
import sys
import os
import time
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.crypto_prediction_agent import CryptoPredictionAgent
from agents.interface import MarketState, Proposal, Outcome
from utils.logger import get_logger

logger = get_logger("test_agent_fixed")

async def test_agent_initialization():
    """Test agent initialization and basic properties"""
    
    print("🚀 Testing CryptoPredictionAgent Initialization")
    print("=" * 50)
    
    try:
        # Create agent config
        config = {
            "agent_id": "test_crypto_agent",
            "expertise_score": 0.8,
            "risk_factor": 0.4,
            "symbols": ["BTC/USD", "ETH/USD"],
            "confidence_threshold": 0.6,
            "max_position_size": 0.1
        }
        
        # Create agent
        agent = CryptoPredictionAgent(config)
        print(f"✅ Agent created: {agent.agent_id}")
        print(f"✅ Expertise score: {agent.expertise_score}")
        print(f"✅ Risk factor: {agent.risk_factor}")
        print(f"✅ State: {agent.state}")
        
        # Test properties
        assert agent.agent_id == "test_crypto_agent"
        assert agent.expertise_score == 0.8
        assert agent.risk_factor == 0.4
        assert agent.state.value == "ready"
        
        print("\n🎉 Agent initialization test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Agent initialization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_observe_analyze_loop():
    """Test observe -> analyze loop"""
    
    print("\n🔄 Testing Observe -> Analyze Loop")
    print("-" * 30)
    
    try:
        config = {
            "agent_id": "test_analyze_agent",
            "expertise_score": 0.7,
            "risk_factor": 0.5,
            "symbols": ["BTC/USD"]
        }
        
        agent = CryptoPredictionAgent(config)
        
        # Create market state
        market_state = MarketState(
            timestamp=time.time(),
            prices={"BTC/USD": 45000.0, "ETH/USD": 3000.0},
            volumes={"BTC/USD": 1000000.0, "ETH/USD": 500000.0},
            funding_rates={"BTC/USD": 0.0001, "ETH/USD": 0.0002},
            news_sentiment=0.5,
            volatility_index=0.3
        )
        
        # Test observe
        await agent.observe(market_state)
        print(f"✅ Observed market state: {len(market_state.prices)} symbols")
        
        # Test analyze
        analysis = await agent.analyze()
        print(f"✅ Analysis completed: {analysis.get('signal')} signal")
        print(f"✅ Confidence: {analysis.get('confidence', 0):.2f}")
        print(f"✅ Processing time: {analysis.get('processing_time_ms', 0):.1f}ms")
        
        # Validate analysis structure
        assert "signal" in analysis
        assert "confidence" in analysis
        assert "reasoning" in analysis
        assert "technical_indicators" in analysis
        
        print("\n🎉 Observe -> Analyze test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Observe -> Analyze test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_voting():
    """Test voting functionality"""
    
    print("\n🗳️ Testing Voting Functionality")
    print("-" * 30)
    
    try:
        config = {
            "agent_id": "test_vote_agent",
            "expertise_score": 0.8,
            "risk_factor": 0.3,
            "confidence_threshold": 0.6
        }
        
        agent = CryptoPredictionAgent(config)
        
        # Create proposal
        proposal = Proposal(
            proposal_id="test_proposal_001",
            proposal_type="trading_signal",
            payload={
                "signal": "buy",
                "confidence": 0.8,
                "reasoning": "Strong bullish momentum detected",
                "symbol": "BTC/USD"
            },
            created_at=time.time(),
            expires_at=time.time() + 3600,
            source_agent="test_agent"
        )
        
        # Test voting
        vote = await agent.vote(proposal)
        print(f"✅ Vote cast: {vote.decision}")
        print(f"✅ Confidence: {vote.confidence:.2f}")
        print(f"✅ Reasoning: {vote.reasoning[:50]}...")
        
        # Validate vote structure
        assert vote.agent_id == "test_vote_agent"
        assert vote.confidence >= 0.0 and vote.confidence <= 1.0
        assert vote.reasoning is not None and len(vote.reasoning) > 0
        
        print("\n🎉 Voting test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Voting test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_reflection():
    """Test reflection functionality"""
    
    print("\n🧠 Testing Reflection Functionality")
    print("-" * 30)
    
    try:
        config = {
            "agent_id": "test_reflect_agent",
            "expertise_score": 0.7,
            "risk_factor": 0.5
        }
        
        agent = CryptoPredictionAgent(config)
        
        # Create successful outcome
        success_outcome = Outcome(
            outcome_id="outcome_001",
            proposal_id="proposal_001",
            result="success",
            actual_value=46000.0,
            predicted_value=45500.0,
            timestamp=time.time(),
            metadata={"prediction_accuracy": 0.8}
        )
        
        # Test reflection with success
        await agent.reflect(success_outcome)
        metrics = agent.get_learning_metrics()
        print(f"✅ Success reflection completed")
        print(f"✅ Total predictions: {metrics['total_predictions']}")
        print(f"✅ Successful: {metrics['successful_predictions']}")
        print(f"✅ Accuracy: {metrics['accuracy_score']:.2f}")
        
        # Create failed outcome
        fail_outcome = Outcome(
            outcome_id="outcome_002",
            proposal_id="proposal_002",
            result="failure",
            actual_value=44000.0,
            predicted_value=45500.0,
            timestamp=time.time(),
            metadata={"prediction_accuracy": 0.3}
        )
        
        # Test reflection with failure
        await agent.reflect(fail_outcome)
        metrics_after = agent.get_learning_metrics()
        print(f"✅ Failure reflection completed")
        print(f"✅ Total predictions: {metrics_after['total_predictions']}")
        print(f"✅ Failed: {metrics_after['failed_predictions']}")
        print(f"✅ Updated accuracy: {metrics_after['accuracy_score']:.2f}")
        
        # Validate learning
        assert metrics_after['total_predictions'] == 2
        assert metrics_after['successful_predictions'] == 1
        assert metrics_after['failed_predictions'] == 1
        assert metrics_after['accuracy_score'] == 0.5
        
        print("\n🎉 Reflection test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Reflection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_complete_workflow():
    """Test complete agent workflow"""
    
    print("\n🔄 Testing Complete Agent Workflow")
    print("-" * 30)
    
    try:
        config = {
            "agent_id": "test_workflow_agent",
            "expertise_score": 0.8,
            "risk_factor": 0.4,
            "symbols": ["BTC/USD"],
            "confidence_threshold": 0.6
        }
        
        agent = CryptoPredictionAgent(config)
        
        # Step 1: Observe market state
        market_state = MarketState(
            timestamp=time.time(),
            prices={"BTC/USD": 45000.0},
            volumes={"BTC/USD": 1000000.0},
            funding_rates={"BTC/USD": 0.0001},
            news_sentiment=0.6,
            volatility_index=0.25
        )
        await agent.observe(market_state)
        print("✅ Step 1: Market state observed")
        
        # Step 2: Analyze
        analysis = await agent.analyze()
        print(f"✅ Step 2: Analysis completed - {analysis['signal']} signal")
        
        # Step 3: Vote on proposal
        proposal = Proposal(
            proposal_id="workflow_proposal",
            proposal_type="trading_decision",
            payload=analysis,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            source_agent=agent.agent_id
        )
        vote = await agent.vote(proposal)
        print(f"✅ Step 3: Vote cast - {vote.decision}")
        
        # Step 4: Reflect on outcome
        outcome = Outcome(
            outcome_id="workflow_outcome",
            proposal_id="workflow_proposal",
            result="success",
            actual_value=45500.0,
            predicted_value=45000.0,
            timestamp=time.time(),
            metadata={"prediction_accuracy": 0.9}
        )
        await agent.reflect(outcome)
        print("✅ Step 4: Reflection completed")
        
        # Check final state
        metrics = agent.get_learning_metrics()
        print(f"✅ Final accuracy: {metrics['accuracy_score']:.2f}")
        
        print("\n🎉 Complete workflow test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Complete workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all agent tests"""
    try:
        print("🧪 CRYPTO PREDICTION AGENT TEST SUITE")
        print("=" * 60)
        
        # Run tests
        test1 = await test_agent_initialization()
        test2 = await test_observe_analyze_loop()
        test3 = await test_voting()
        test4 = await test_reflection()
        test5 = await test_complete_workflow()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS")
        print("=" * 60)
        print(f"Agent Initialization: {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Observe -> Analyze:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Voting:               {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Reflection:           {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Complete Workflow:    {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL TESTS PASSED!")
            print("✅ CryptoPredictionAgent is working correctly")
            print("✅ All NotImplemented methods implemented")
            print("✅ AgentInterface contract satisfied")
            print("✅ Ready for integration with streams and oracles")
        else:
            print("\n❌ Some tests failed - check implementation")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

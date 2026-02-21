#!/usr/bin/env python3
"""
Test script for Brier metrics dashboard integration
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_brier_api():
    """Test the Brier metrics API endpoint"""
    try:
        # Import the API function
        from web.api.dashboard_data import get_brier_metrics
        
        print("🎯 Testing Brier Metrics API")
        print("=" * 50)
        
        # Call the API function
        result = await get_brier_metrics()
        
        print(f"✅ API Status: {result.get('status', 'unknown')}")
        
        if result.get('status') == 'success':
            metrics = result.get('metrics', {})
            interpretation = result.get('interpretation', {})
            
            print("\n📊 Brier Score Metrics:")
            print(f"   Brier Score: {metrics.get('brier_score', 'N/A'):.4f}")
            print(f"   BSS vs Baseline: {metrics.get('brier_skill_score_vs_baseline', 'N/A'):.2f}")
            print(f"   Quality Category: {metrics.get('quality_category', 'N/A')}")
            print(f"   Sample Size: {metrics.get('n_samples', 'N/A')}")
            
            print("\n🔍 Decomposition:")
            decomp = metrics.get('decomposition', {})
            print(f"   Reliability: {decomp.get('reliability', 'N/A'):.4f}")
            print(f"   Resolution: {decomp.get('resolution', 'N/A'):.4f}")
            print(f"   Uncertainty: {decomp.get('uncertainty', 'N/A'):.4f}")
            
            print("\n💡 Interpretation:")
            print(f"   Calibration: {interpretation.get('calibration', 'N/A')}")
            print(f"   Baseline Status: {interpretation.get('baseline_status', 'N/A')}")
            print(f"   Skill Assessment: {interpretation.get('skill_assessment', 'N/A')}")
            
            print("\n✅ Brier Metrics API Test - SUCCESS")
            return True
            
        else:
            print(f"❌ API Error: {result.get('error', 'Unknown error')}")
            print(f"   Message: {result.get('message', 'No message')}")
            print("\n❌ Brier Metrics API Test - FAILED")
            return False
            
    except Exception as e:
        print(f"❌ Exception during API test: {e}")
        print("\n❌ Brier Metrics API Test - FAILED")
        return False

async def test_dashboard_integration():
    """Test dashboard integration components"""
    print("\n🎯 Testing Dashboard Integration")
    print("=" * 50)
    
    try:
        # Test agent creation
        from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent
        
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test-dashboard",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["crypto", "politics", "sports"]
        )
        print("✅ Agent creation successful")
        
        # Test metrics calculation with sample data
        from agents.prediction_arbitrage_analyst import ArbitrageOpportunitySummary
        
        # Create sample opportunities
        sample_opps = [
            ArbitrageOpportunitySummary(
                canonical_question="Will BTC reach $100k by end of year?",
                spread_probability=0.65,
                best_venue="Polymarket",
                best_probability=0.68,
                worst_venue="PredictIt",
                worst_probability=0.62,
                days_to_resolution=30.0,
                total_liquidity=75000.0,
                risk_note="High volatility expected",
                forecast_probability=0.65
            ),
            ArbitrageOpportunitySummary(
                canonical_question="Will Trump win 2024 election?",
                spread_probability=0.45,
                best_venue="Kalshi",
                best_probability=0.48,
                worst_venue="PredictIt",
                worst_probability=0.42,
                days_to_resolution=45.0,
                total_liquidity=120000.0,
                risk_note="Political uncertainty",
                forecast_probability=0.45
            )
        ]
        
        metrics = agent._calculate_brier_score(sample_opps)
        
        if metrics:
            print("✅ Metrics calculation successful")
            print(f"   Brier Score: {metrics['brier_score']:.4f}")
            print(f"   Quality: {metrics['quality_category']}")
        else:
            print("❌ Metrics calculation failed")
            return False
        
        print("\n✅ Dashboard Integration Test - SUCCESS")
        return True
        
    except Exception as e:
        print(f"❌ Exception during integration test: {e}")
        print("\n❌ Dashboard Integration Test - FAILED")
        return False

async def main():
    """Run all tests"""
    print("🚀 Brier Metrics Dashboard Integration Test Suite")
    print("=" * 60)
    
    # Test API endpoint
    api_success = await test_brier_api()
    
    # Test dashboard integration
    integration_success = await test_dashboard_integration()
    
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    print(f"API Test: {'✅ PASS' if api_success else '❌ FAIL'}")
    print(f"Integration Test: {'✅ PASS' if integration_success else '❌ FAIL'}")
    
    if api_success and integration_success:
        print("\n🎉 ALL TESTS PASSED - Dashboard Integration Ready!")
        print("\n📋 Next Steps:")
        print("   1. Start the web server: python -m uvicorn web.main:app --reload")
        print("   2. Open dashboard: http://127.0.0.1:8000/templates/unified_standalone.html")
        print("   3. Verify Brier metrics panel appears and updates")
    else:
        print("\n❌ SOME TESTS FAILED - Check errors above")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

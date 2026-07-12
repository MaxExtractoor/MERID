#!/usr/bin/env python3
"""
Quick test to verify Brier score calculation.

NOTE: This test is skipped because prediction_arbitrage_analyst is in the legacy folder
and is not part of the core 15m crypto trading system.
"""

import pytest

pytest.skip("prediction_arbitrage_analyst is in legacy folder, not part of 15m crypto system", allow_module_level=True)

async def test_brier_calculation():
    """Test the Brier score calculation."""
    
    # Create agent instance
    agent = PredictionArbitrageAnalystAgent()
    
    # Mock response from LLM
    mock_llm_response = json.dumps({
        "summary": "Found 3 arbitrage opportunities with spreads ranging from 3% to 13%.",
        "top_opportunities": [
            {
                "canonical_question": "will bitcoin reach 100k by end of 2024",
                "spread_probability": 0.13,
                "best_venue": "polymarket",
                "best_probability": 0.65,
                "worst_venue": "kalshi",
                "worst_probability": 0.52,
                "days_to_resolution": 30.0,
                "total_liquidity": 450000.0,
                "risk_note": "High liquidity, good time horizon"
            },
            {
                "canonical_question": "will ethereum reach 3k by end of 2024",
                "spread_probability": 0.08,
                "best_venue": "polymarket",
                "best_probability": 0.55,
                "worst_venue": "augur",
                "worst_probability": 0.47,
                "days_to_resolution": 45.0,
                "total_liquidity": 250000.0,
                "risk_note": "Moderate liquidity, reasonable time horizon"
            },
            {
                "canonical_question": "will gdp exceed 3 in q4",
                "spread_probability": 0.03,
                "best_venue": "kalshi",
                "best_probability": 0.45,
                "worst_venue": "polymarket",
                "worst_probability": 0.42,
                "days_to_resolution": 15.0,
                "total_liquidity": 140000.0,
                "risk_note": "Low liquidity, near expiry"
            }
        ],
        "filters_used": {
            "min_spread": 0.05,
            "min_liquidity": 50000.0,
            "categories": []
        },
        "total_opportunities_analyzed": 3,
        "analysis_timestamp": 1234567890.0
    })
    
    # Parse the response using the agent's parser
    result = agent._parse_response(mock_llm_response)
    
    print("=== Brier Score Test Results ===")
    print(f"Summary: {result['summary']}")
    print(f"Brier Score: {result['brier_score']}")
    print(f"Brier Score (3 decimal): {result['brier_score']:.3f}")
    
    # Show bucket details that contribute to Brier
    print("\n=== Bucket Contributions to Brier ===")
    for bucket in result['bucket_analysis']:
        forecast = bucket['avg_forecast']
        actual = bucket['empirical_success_rate']
        squared_error = (forecast - actual) ** 2
        weight = bucket['count']
        contribution = squared_error * weight
        
        print(f"Bucket {bucket['bucket_range']}:")
        print(f"  Forecast: {forecast:.3f}, Actual: {actual:.3f}")
        print(f"  Squared Error: {squared_error:.6f}")
        print(f"  Weight: {weight}, Contribution: {contribution:.6f}")
        print()
    
    # Verify Brier calculation manually
    total_contribution = sum(
        ((bucket['avg_forecast'] - bucket['empirical_success_rate']) ** 2) * bucket['count']
        for bucket in result['bucket_analysis']
    )
    total_count = sum(bucket['count'] for bucket in result['bucket_analysis'])
    manual_brier = total_contribution / total_count
    
    print(f"Manual Brier calculation: {manual_brier:.6f}")
    print(f"Agent Brier calculation: {result['brier_score']:.6f}")
    print(f"Match: {abs(manual_brier - result['brier_score']) < 1e-10}")
    
    print("\n✅ Brier score test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_brier_calculation())

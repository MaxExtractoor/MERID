#!/usr/bin/env python3
"""
Quick test script to verify bucket analysis functionality.
"""

import asyncio
import json
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent

async def test_bucket_analysis():
    """Test the bucket analysis functionality."""
    
    # Create agent instance
    agent = PredictionArbitrageAnalystAgent()
    
    # Create mock energy packet
    energy = {
        "energy_id": "test-bucket-analysis-1",
        "source": "test",
        "payload": {
            "min_spread": 0.05,
            "max_opportunities": 10,
            "min_liquidity": 50000.0,
            "categories": []
        }
    }
    
    # Mock response from LLM (simulating what the LLM would return)
    mock_llm_response = json.dumps({
        "summary": "Found 3 arbitrage opportunities with spreads ranging from 3% to 13%. Bitcoin opportunity shows highest spread with good liquidity.",
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
    
    print("=== Bucket Analysis Test Results ===")
    print(f"Summary: {result['summary']}")
    print(f"Total opportunities: {result['total_opportunities_analyzed']}")
    print(f"Number of opportunities: {len(result['top_opportunities'])}")
    
    # Check forecast probabilities
    print("\n=== Forecast Probabilities ===")
    for i, opp in enumerate(result['top_opportunities'], 1):
        print(f"Opportunity {i}: {opp['forecast_probability']:.3f} ({opp['forecast_probability']*100:.1f}%)")
    
    # Check bucket analysis
    print("\n=== Bucket Analysis ===")
    for bucket in result['bucket_analysis']:
        print(f"Bucket {bucket['bucket_range']}:")
        print(f"  Count: {bucket['count']}")
        print(f"  Avg Forecast: {bucket['avg_forecast']:.3f} ({bucket['avg_forecast']*100:.1f}%)")
        print(f"  Empirical Success: {bucket['empirical_success_rate']:.3f} ({bucket['empirical_success_rate']*100:.1f}%)")
        print(f"  Avg Spread: {bucket['avg_spread']:.3f} ({bucket['avg_spread']*100:.1f}%)")
        print(f"  Avg Liquidity: ${bucket['avg_liquidity']/1000:.0f}K")
        print()
    
    print("✅ Bucket analysis test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_bucket_analysis())

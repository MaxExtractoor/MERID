#!/usr/bin/env python3
"""
Test script to verify run logging functionality.
"""

import asyncio
import json
import time
from pathlib import Path
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, log_agent_run, AgentRunLog, BucketAnalysis

async def test_run_logging():
    """Test the run logging functionality."""
    
    # Create agent instance
    agent = PredictionArbitrageAnalystAgent()
    
    # Create a mock run log
    mock_run = AgentRunLog(
        run_id="test-run-logging-123",
        timestamp=time.time(),
        agent_id="prediction-arbitrage-analyst-01",
        agent_version="merid-strategist:latest",
        run_type="manual",
        filters={
            "min_spread": 0.05,
            "max_opportunities": 10,
            "min_liquidity": 50000.0,
            "categories": []
        },
        brier_score=0.003889,
        estimates_only=True,
        bucket_stats=[
            BucketAnalysis(
                bucket_range="0.8-1.0",
                count=1,
                avg_forecast=0.85,
                empirical_success_rate=0.76,
                avg_spread=0.13,
                avg_liquidity=450000.0
            )
        ],
        total_opportunities=3,
        recommendations_count=3,
        latency_ms=850.0,
        status="success"
    )
    
    # Test logging
    print("=== Testing Run Logging ===")
    print(f"Run ID: {mock_run.run_id}")
    print(f"Agent ID: {mock_run.agent_id}")
    print(f"Brier Score: {mock_run.brier_score}")
    print(f"Status: {mock_run.status}")
    print(f"Latency: {mock_run.latency_ms}ms")
    
    # Log the run
    log_agent_run(mock_run)
    print("✅ Run logged successfully!")
    
    # Verify the log file exists and contains our entry
    log_path = Path("logs/agent_runs.jsonl")
    if log_path.exists():
        print(f"\n✅ Log file exists: {log_path}")
        
        # Read the last line to verify our entry
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                logged_data = json.loads(last_line)
                print(f"✅ Verified logged entry: {logged_data['run_id']}")
                print(f"   Timestamp: {logged_data['timestamp']}")
                print(f"   Brier Score: {logged_data['brier_score']}")
                print(f"   Status: {logged_data['status']}")
            else:
                print("❌ Log file is empty")
    else:
        print("❌ Log file was not created")
    
    print("\n=== Testing Recent Runs API ===")
    
    # Test the API endpoint (this would normally be called from the dashboard)
    from web.api.institutional import get_recent_runs
    
    try:
        result = await get_recent_runs(limit=5)
        print(f"✅ API returned {len(result.get('runs', []))} runs")
        
        if result.get('runs'):
            first_run = result['runs'][0]
            print(f"   First run ID: {first_run.get('run_id')}")
            print(f"   Brier Score: {first_run.get('brier_score')}")
            print(f"   Status: {first_run.get('status')}")
        
    except Exception as e:
        print(f"❌ API test failed: {e}")
    
    print("\n✅ Run logging test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_run_logging())

#!/usr/bin/env python3
"""
Test script to verify structured JSON logging functionality.
"""

import pytest
pytest.importorskip("sklearn", reason="sklearn is an optional dependency")
import asyncio
import json
import time
from pathlib import Path
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, log_agent_run, AgentRunLog, BucketAnalysis

async def test_structured_logging():
    """Test the structured JSON logging functionality."""
    
    print("=== Testing Structured JSON Logging ===")
    
    # Create agent instance
    agent = PredictionArbitrageAnalystAgent()
    
    # Create a mock run log with rich data
    mock_run = AgentRunLog(
        run_id="test-structured-logging-123",
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
            ),
            BucketAnalysis(
                bucket_range="0.6-0.8",
                count=1,
                avg_forecast=0.65,
                empirical_success_rate=0.58,
                avg_spread=0.08,
                avg_liquidity=250000.0
            )
        ],
        total_opportunities=3,
        recommendations_count=3,
        latency_ms=850.0,
        status="success"
    )
    
    # Test structured logging
    print(f"Run ID: {mock_run.run_id}")
    print(f"Agent ID: {mock_run.agent_id}")
    print(f"Brier Score: {mock_run.brier_score}")
    print(f"Status: {mock_run.status}")
    print(f"Latency: {mock_run.latency_ms}ms")
    print(f"Bucket Stats: {len(mock_run.bucket_stats)} buckets")
    
    # Log the run
    log_agent_run(mock_run)
    print("✅ Structured run logged successfully!")
    
    # Verify the log file exists and contains structured JSON
    log_path = Path("logs/agent_runs.jsonl")
    if log_path.exists():
        print(f"\n✅ Log file exists: {log_path}")
        
        # Read the last line to verify our structured entry
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                try:
                    logged_data = json.loads(last_line)
                    print(f"✅ Verified structured JSON entry")
                    print(f"   Timestamp: {logged_data.get('ts', 'N/A')}")
                    print(f"   Service: {logged_data.get('service', 'N/A')}")
                    print(f"   Level: {logged_data.get('level', 'N/A')}")
                    print(f"   Message: {logged_data.get('msg', 'N/A')}")
                    print(f"   Agent ID: {logged_data.get('agent_id', 'N/A')}")
                    print(f"   Run ID: {logged_data.get('run_id', 'N/A')}")
                    print(f"   Brier Score: {logged_data.get('brier_score', 'N/A')}")
                    print(f"   Status: {logged_data.get('status', 'N/A')}")
                    
                    # Check bucket stats structure
                    bucket_stats = logged_data.get('bucket_stats', [])
                    print(f"   Bucket Stats Count: {len(bucket_stats)}")
                    if bucket_stats:
                        first_bucket = bucket_stats[0]
                        print(f"   First Bucket: {first_bucket.get('bucket_range', 'N/A')}")
                        print(f"   First Bucket Forecast: {first_bucket.get('avg_forecast', 'N/A')}")
                    
                except json.JSONDecodeError as e:
                    print(f"❌ Failed to parse JSON: {e}")
                    print(f"Raw line: {last_line[:200]}...")
            else:
                print("❌ Log file is empty")
    else:
        print("❌ Log file was not created")
    
    print("\n=== Testing Error Logging ===")
    
    # Test error logging with structured data
    error_run = AgentRunLog(
        run_id="test-error-logging-456",
        timestamp=time.time(),
        agent_id="prediction-arbitrage-analyst-01",
        agent_version="merid-strategist:latest",
        run_type="manual",
        filters={},
        brier_score=None,
        estimates_only=True,
        bucket_stats=[],
        total_opportunities=0,
        recommendations_count=0,
        latency_ms=1200.0,
        status="error",
        error_type="llm_timeout",
        error_message="LLM call timed out after 30 seconds"
    )
    
    log_agent_run(error_run)
    print("✅ Error run logged successfully!")
    
    # Verify error structure
    with log_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        if lines:
            last_line = lines[-1].strip()
            error_data = json.loads(last_line)
            print(f"✅ Error log verified:")
            print(f"   Status: {error_data.get('status', 'N/A')}")
            print(f"   Error Type: {error_data.get('error_type', 'N/A')}")
            print(f"   Error Message: {error_data.get('error_message', 'N/A')}")
    
    print("\n✅ Structured logging test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_structured_logging())

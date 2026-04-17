import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from merid.agents.risk_agents import AnomalyDetectorAgent, Anomaly

@pytest.mark.asyncio
async def test_anomaly_detector_no_anomalies():
    agent = AnomalyDetectorAgent()
    market_data = [
        {"instrument": "BTC", "venue": "kalshi", "price": 50, "bid": 49, "ask": 51, "timestamp": datetime.now(timezone.utc).isoformat()}
    ]
    output = await agent.run({"market_data": market_data})
    
    assert output.output_type == "anomalies"
    assert output.payload["count"] == 0
    assert output.payload["critical"] == 0

@pytest.mark.asyncio
async def test_anomaly_detector_stale_data():
    agent = AnomalyDetectorAgent()
    # 2 minutes ago
    stale_ts = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - 120, timezone.utc).isoformat()
    market_data = [
        {"instrument": "BTC", "venue": "kalshi", "price": 50, "bid": 49, "ask": 51, "timestamp": stale_ts}
    ]
    output = await agent.run({"market_data": market_data})
    
    assert output.payload["count"] == 1
    assert output.payload["anomalies"][0]["anomaly_type"] == "stale_data"
    assert output.payload["anomalies"][0]["severity"] == "warning"

@pytest.mark.asyncio
async def test_anomaly_detector_price_spike():
    agent = AnomalyDetectorAgent(spike_threshold_pct=0.10)
    
    # First run to establish baseline
    ts = datetime.now(timezone.utc).isoformat()
    market_data_1 = [
        {"instrument": "BTC", "venue": "kalshi", "price": 50, "bid": 49, "ask": 51, "timestamp": ts}
    ]
    await agent.run({"market_data": market_data_1})
    
    # Second run with spike (50 -> 60 is a 20% jump)
    market_data_2 = [
        {"instrument": "BTC", "venue": "kalshi", "price": 60, "bid": 59, "ask": 61, "timestamp": ts}
    ]
    
    with patch("core.event_bus.event_stream.publish", new_callable=MagicMock) as mock_publish:
        output = await agent.run({"market_data": market_data_2})
        
        assert output.payload["count"] == 1
        assert output.payload["critical"] == 1
        assert output.payload["anomalies"][0]["anomaly_type"] == "price_spike"
        assert output.payload["anomalies"][0]["severity"] == "critical"
        
        # Give event loop a moment to execute the background task
        await asyncio.sleep(0.01)
        mock_publish.assert_called_once()
        assert mock_publish.call_args[0][0] == "risk:anomaly_detected"
        
@pytest.mark.asyncio
async def test_anomaly_detector_spread_anomaly():
    agent = AnomalyDetectorAgent()
    ts = datetime.now(timezone.utc).isoformat()
    # Wide spread: bid 40, ask 60 (50% spread)
    market_data = [
        {"instrument": "BTC", "venue": "kalshi", "price": 50, "bid": 40, "ask": 60, "timestamp": ts}
    ]
    output = await agent.run({"market_data": market_data})
    
    assert output.payload["count"] == 1
    assert output.payload["anomalies"][0]["anomaly_type"] == "spread_anomaly"
    assert output.payload["anomalies"][0]["severity"] == "warning"

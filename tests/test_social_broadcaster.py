import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from merid.prediction.social_broadcaster import KalshiSocialBroadcaster

@pytest.fixture
def mock_twitter_agent():
    with patch("agents.twitter_agent.get_twitter_agent") as mock_get:
        mock_agent = MagicMock()
        mock_agent.enabled = True
        mock_agent.post_tweet.return_value = MagicMock(tweet_id="12345")
        mock_get.return_value = mock_agent
        yield mock_agent

@pytest.fixture
def mock_telegram():
    with patch("merid.prediction.social_broadcaster.KalshiSocialBroadcaster._post_to_telegram", new_callable=AsyncMock) as mock_tg:
        yield mock_tg

@pytest.mark.asyncio
async def test_publish_fill(mock_twitter_agent, mock_telegram):
    broadcaster = KalshiSocialBroadcaster()
    
    payload = {
        "agent": "test-agent",
        "side": "yes",
        "action": "buy",
        "market_id": "KXBTCD-25JUN-T100000",
        "price_cents": 55,
        "contracts": 10,
        "simulated": False,
        "ref_bid": 54,
        "ref_ask": 56,
        "question": "Will BTC be above 100k?",
        "edge_pct": 0.05,
        "confidence": 0.8,
        "phase": "MID",
        "archetype": "trend"
    }
    
    await broadcaster._publish_fill(payload)
    
    # Verify Telegram
    mock_telegram.assert_called_once()
    tg_args = mock_telegram.call_args[0][0]
    assert "<b>Kalshi Fill</b> [LIVE]" in tg_args
    assert "<b>BUY</b> 10× YES" in tg_args
    assert "Ref bid: <b>54¢</b> | Ref ask: <b>56¢</b>" in tg_args
    assert "Edge: <b>+5.00%</b> | Conf: 80%" in tg_args
    
    # Verify Twitter
    mock_twitter_agent.post_tweet.assert_called_once()
    tw_args = mock_twitter_agent.post_tweet.call_args[0][0]
    assert "[LIVE] Kalshi BUY 10× YES" in tw_args
    assert "Will BTC be above 100k?" in tw_args
    assert "Bid 54¢/Ask 56¢ | Edge +5.0%" in tw_args

@pytest.mark.asyncio
async def test_publish_consensus_decision(mock_twitter_agent, mock_telegram):
    broadcaster = KalshiSocialBroadcaster()
    
    payload = {
        "ticker": "KXBTCD-25JUN-T100000",
        "asset": "BTC",
        "timeframe": "15m",
        "direction": "YES",
        "consensus_prob": 0.85,
        "ev": 0.05,
        "confidence": 0.9,
        "n_agents": 5,
        "n_yes": 4,
        "n_no": 1,
        "n_neutral": 0,
        "size_band": "large",
        "mode": "live",
        "confidence_factors": ["Strong trend", "High volume"]
    }
    
    await broadcaster._publish_consensus_decision(payload)
    
    # Verify Telegram
    mock_telegram.assert_called_once()
    
    # Verify Twitter
    mock_twitter_agent.post_tweet.assert_called_once()
    tw_args = mock_twitter_agent.post_tweet.call_args[0][0]
    assert "Kalshi swarm: YES @ 85.0%" in tw_args
    assert "(conf 90%, 5 agents)" in tw_args

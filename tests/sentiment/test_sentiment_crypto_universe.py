"""Sentiment stack alignment with canonical Kalshi crypto universe."""

from __future__ import annotations

from config.kalshi_crypto_config import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    active_crypto_asset_mood_timeframe_grid,
)
from merid.event_venues.kalshi.crypto_catalog import KalshiCryptoCatalog, KalshiMarketInfo
from merid.sentiment.hashtag_agent import HashtagAgent, HashtagSentiment
from merid.sentiment.sentiment_signal import SentimentSignal, utcnow
from merid.swarm.consensus_aggregator import (
    SwarmConsensusAggregator,
    neutral_consensus_view,
)


def test_mood_grid_covers_all_assets_and_ws_timeframes() -> None:
    from config.kalshi_crypto_config import WS_TIMEFRAME_TO_MOOD_LABEL

    grid = active_crypto_asset_mood_timeframe_grid()
    assets = {a for a, _ in grid}
    tfs = {t for _, t in grid}
    assert assets == set(ACTIVE_CRYPTO_ASSETS)
    assert tfs == {WS_TIMEFRAME_TO_MOOD_LABEL[w] for w in ACTIVE_CRYPTO_WS_TIMEFRAMES}
    assert len(grid) == len(ACTIVE_CRYPTO_ASSETS) * len(ACTIVE_CRYPTO_WS_TIMEFRAMES)


def test_neutral_consensus_not_usable() -> None:
    v = neutral_consensus_view("ETH", "1h", reason="test")
    assert v.usable is False
    assert v.consensus_confidence == 0.0
    assert v.size_band == "halted"
    upd = v.to_sentiment_context_update()
    assert upd.get("swarm_usable") is False


def test_get_consensus_or_neutral_returns_neutral_when_empty() -> None:
    agg = SwarmConsensusAggregator()
    v = agg.get_consensus_or_neutral("SOL", "15m")
    assert v.usable is False
    assert v.consensus_confidence == 0.0


def test_hashtag_generate_signals_uses_per_asset_fg() -> None:
    agent = HashtagAgent()
    ts = utcnow()
    sentiments = [
        HashtagSentiment(
            tag="#BTC",
            score=0.5,
            volume=100,
            category="crypto",
            asset="BTC",
            event_id=None,
            provider="twitter",
            timestamp=ts,
        ),
        HashtagSentiment(
            tag="#ETH",
            score=0.5,
            volume=100,
            category="crypto",
            asset="ETH",
            event_id=None,
            provider="twitter",
            timestamp=ts,
        ),
    ]
    sigs = agent.generate_signals(
        sentiments,
        fg_by_asset={"BTC": 15, "ETH": 85},
        score_threshold=0.1,
    )
    by_asset = {s.asset_or_event: s for s in sigs}
    assert "BTC" in by_asset and "ETH" in by_asset


def test_sentiment_signal_model() -> None:
    s = SentimentSignal(
        asset="DOGE",
        timeframe="15m",
        score=0.2,
        intensity=50.0,
        source="lane",
        generated_at=utcnow(),
    )
    assert s.to_dict()["asset"] == "DOGE"


def test_iter_tickers_filters_by_timeframe() -> None:
    infos = [
        KalshiMarketInfo(
            ticker="KXDOGE15M-TEST1",
            asset="DOGE",
            frequency="15M",
        ),
        KalshiMarketInfo(
            ticker="KXDOGE-TEST2",
            asset="DOGE",
            frequency="1H",
        ),
    ]
    cat = KalshiCryptoCatalog(infos)
    assert cat.iter_tickers("DOGE", "15m") == ["KXDOGE15M-TEST1"]
    assert cat.iter_tickers("DOGE", "1h") == ["KXDOGE-TEST2"]

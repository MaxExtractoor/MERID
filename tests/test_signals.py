"""Comprehensive tests for merid.signals — Events, Ingestion, Processing, Agents, Alerts.

Covers:
§1 Domain objects: InfoEvent, SentimentFeature, SentimentSpike, OperatorCommand
§2 Ingestion: XWorker, TelegramWorker, NewsWorker, EventBuffer, ticker extraction
§3 Processing: SentimentProcessor, sentiment analysis, spike detection, windowing
§4 Agents: SentimentAgent, NewsThesisAgent, TelegramOpsAgent
§5 Alerts: AlertRouter, channel routing, formatting, convenience methods
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from merid.signals.events import (
    InfoEvent,
    InfoSource,
    EventType,
    SentimentFeature,
    SentimentSpike,
    SentimentWindow,
    OperatorCommand,
)
from merid.signals.ingestion import (
    EventBuffer,
    XWorker,
    TelegramWorker,
    NewsWorker,
    extract_tickers,
)
from merid.signals.processing import (
    SentimentProcessor,
    _simple_sentiment,
)
from merid.signals.agents import (
    SentimentAgent,
    NewsThesisAgent,
    TelegramOpsAgent,
)
from merid.signals.alerts import (
    Alert,
    AlertChannel,
    AlertRouter,
    AlertSeverity,
)


# ======================================================================
# §1 Domain Object Tests
# ======================================================================

class TestInfoEvent:

    def test_creation(self):
        e = InfoEvent(source=InfoSource.X, raw_text="BTC is pumping!")
        assert e.source == InfoSource.X
        assert e.raw_text_hash != ""

    def test_hash_computed(self):
        e = InfoEvent(raw_text="test text")
        assert len(e.raw_text_hash) == 16

    def test_to_dict(self):
        e = InfoEvent(source=InfoSource.NEWS, raw_text="headline", tickers=["BTC"])
        d = e.to_dict()
        assert d["source"] == "news"
        assert d["tickers"] == ["BTC"]

    def test_to_dict_truncates_long_text(self):
        e = InfoEvent(raw_text="x" * 300)
        d = e.to_dict()
        assert d["raw_text"].endswith("...")

    def test_empty_text_no_hash(self):
        e = InfoEvent(raw_text="")
        assert e.raw_text_hash == ""


class TestSentimentFeature:

    def test_creation(self):
        f = SentimentFeature(ticker="BTC", polarity=0.8, magnitude=0.6)
        assert f.polarity == 0.8

    def test_to_dict(self):
        f = SentimentFeature(ticker="ETH", polarity=-0.5, relevance=0.9)
        d = f.to_dict()
        assert d["ticker"] == "ETH"
        assert d["polarity"] == -0.5


class TestSentimentSpike:

    def test_creation(self):
        s = SentimentSpike(ticker="SOL", delta=0.8, direction="bullish")
        assert s.direction == "bullish"

    def test_to_dict(self):
        s = SentimentSpike(ticker="BTC", short_window_avg=0.9, long_window_avg=0.1, delta=0.8)
        d = s.to_dict()
        assert d["delta"] == 0.8


class TestSentimentWindow:

    def test_to_dict(self):
        w = SentimentWindow(ticker="BTC", avg_polarity=0.5, sample_count=10)
        d = w.to_dict()
        assert d["ticker"] == "BTC"
        assert d["sample_count"] == 10


class TestOperatorCommand:

    def test_creation(self):
        c = OperatorCommand(command="pause", domain="crypto", reason="news")
        assert c.command == "pause"

    def test_to_dict(self):
        c = OperatorCommand(command="status")
        d = c.to_dict()
        assert d["command"] == "status"
        assert d["source"] == "telegram"


# ======================================================================
# §2 Ingestion Tests
# ======================================================================

class TestExtractTickers:

    def test_cashtag(self):
        tickers = extract_tickers("$BTC is going up, $ETH too")
        assert "BTC" in tickers
        assert "ETH" in tickers

    def test_known_tickers(self):
        tickers = extract_tickers("BTC and SOL are pumping")
        assert "BTC" in tickers
        assert "SOL" in tickers

    def test_no_tickers(self):
        tickers = extract_tickers("the weather is nice today")
        assert tickers == []

    def test_mixed(self):
        tickers = extract_tickers("$AAPL earnings beat, TSLA down")
        assert "AAPL" in tickers
        assert "TSLA" in tickers


class TestEventBuffer:

    def test_push_and_size(self):
        buf = EventBuffer()
        e = InfoEvent(raw_text="test")
        assert buf.push(e) is True
        assert buf.size == 1

    def test_dedup(self):
        buf = EventBuffer()
        e1 = InfoEvent(raw_text="same text")
        e2 = InfoEvent(raw_text="same text")
        buf.push(e1)
        assert buf.push(e2) is False
        assert buf.size == 1

    def test_pop_batch(self):
        buf = EventBuffer()
        for i in range(5):
            buf.push(InfoEvent(raw_text=f"event {i}"))
        batch = buf.pop_batch(3)
        assert len(batch) == 3
        assert buf.size == 2

    def test_peek(self):
        buf = EventBuffer()
        buf.push(InfoEvent(raw_text="a"))
        buf.push(InfoEvent(raw_text="b"))
        peeked = buf.peek(1)
        assert len(peeked) == 1
        assert buf.size == 2  # Not removed

    def test_max_size_eviction(self):
        buf = EventBuffer(max_size=3)
        for i in range(5):
            buf.push(InfoEvent(raw_text=f"event {i}"))
        assert buf.size == 3

    def test_clear(self):
        buf = EventBuffer()
        buf.push(InfoEvent(raw_text="test"))
        buf.clear()
        assert buf.size == 0


class TestXWorker:

    def test_ingest_tweet(self):
        worker = XWorker()
        event = worker.ingest_tweet({"text": "$BTC moon!", "author": "trader1"})
        assert event is not None
        assert event.source == InfoSource.X
        assert "BTC" in event.tickers

    def test_dedup(self):
        worker = XWorker()
        worker.ingest_tweet({"text": "same tweet"})
        event2 = worker.ingest_tweet({"text": "same tweet"})
        assert event2 is None

    def test_ingest_batch(self):
        worker = XWorker()
        tweets = [{"text": f"tweet {i}"} for i in range(5)]
        count = worker.ingest_batch(tweets)
        assert count == 5

    def test_empty_text(self):
        worker = XWorker()
        assert worker.ingest_tweet({"text": ""}) is None

    def test_watch_account(self):
        worker = XWorker()
        worker.watch_account("@elonmusk")
        assert "@elonmusk" in worker._watchlist

    def test_summary(self):
        worker = XWorker()
        s = worker.summary()
        assert s["worker"] == "x"


class TestTelegramWorker:

    def test_ingest_message(self):
        worker = TelegramWorker()
        event = worker.ingest_message({"text": "BTC looking good", "from": "user1"})
        assert event is not None
        assert event.source == InfoSource.TELEGRAM

    def test_operator_command(self):
        worker = TelegramWorker()
        event = worker.ingest_message({"text": "/pause domain=crypto reason='news'", "from": "admin"})
        assert event is not None
        assert event.event_type == EventType.OPERATOR_COMMAND
        cmds = worker.get_pending_commands()
        assert len(cmds) == 1
        assert cmds[0].command == "pause"
        assert cmds[0].domain == "crypto"

    def test_unknown_command_is_message(self):
        worker = TelegramWorker()
        event = worker.ingest_message({"text": "/unknown_cmd", "from": "user"})
        assert event is not None
        assert event.event_type == EventType.TELEGRAM_MSG

    def test_status_command(self):
        worker = TelegramWorker()
        worker.ingest_message({"text": "/status", "from": "admin"})
        cmds = worker.get_pending_commands()
        assert len(cmds) == 1
        assert cmds[0].command == "status"

    def test_summary(self):
        worker = TelegramWorker()
        s = worker.summary()
        assert s["worker"] == "telegram"


class TestNewsWorker:

    def test_ingest_article(self):
        worker = NewsWorker()
        event = worker.ingest_article({
            "headline": "BTC hits new high",
            "tickers": ["BTC"],
            "source": "reuters",
            "sentiment_score": 0.8,
        })
        assert event is not None
        assert event.source == InfoSource.NEWS
        assert "BTC" in event.tickers

    def test_ingest_batch(self):
        worker = NewsWorker()
        articles = [
            {"headline": f"Article {i}", "tickers": ["ETH"]}
            for i in range(3)
        ]
        count = worker.ingest_batch(articles)
        assert count == 3

    def test_empty_article(self):
        worker = NewsWorker()
        assert worker.ingest_article({}) is None

    def test_ticker_extraction_from_text(self):
        worker = NewsWorker()
        event = worker.ingest_article({"headline": "$SOL partnership announced"})
        assert event is not None
        assert "SOL" in event.tickers

    def test_summary(self):
        worker = NewsWorker()
        s = worker.summary()
        assert s["worker"] == "news"


# ======================================================================
# §3 Processing Tests
# ======================================================================

class TestSimpleSentiment:

    def test_bullish(self):
        pol, mag, rel, act = _simple_sentiment("BTC is bullish, rally incoming, buy now!")
        assert pol > 0

    def test_bearish(self):
        pol, mag, rel, act = _simple_sentiment("crash incoming, dump everything, sell sell sell")
        assert pol < 0

    def test_neutral(self):
        pol, mag, rel, act = _simple_sentiment("the weather is nice today")
        assert pol == 0.0
        assert mag == 0.0

    def test_high_relevance(self):
        pol, mag, rel, act = _simple_sentiment("BREAKING: SEC confirms new crypto rules")
        assert rel > 0


class TestSentimentProcessor:

    def _make_event(self, text, tickers=None, source=InfoSource.X, **kwargs):
        return InfoEvent(
            source=source, raw_text=text,
            tickers=tickers or extract_tickers(text),
            **kwargs,
        )

    def test_process_event(self):
        proc = SentimentProcessor()
        event = self._make_event("$BTC is bullish!")
        features = proc.process_event(event)
        assert len(features) >= 1
        assert features[0].ticker == "BTC"
        assert features[0].polarity > 0

    def test_process_batch(self):
        proc = SentimentProcessor()
        events = [
            self._make_event("$BTC moon"),
            self._make_event("$ETH crash"),
        ]
        features = proc.process_batch(events)
        assert len(features) >= 2

    def test_get_window(self):
        proc = SentimentProcessor()
        proc.process_event(self._make_event("$BTC bullish rally"))
        proc.process_event(self._make_event("$BTC buy now pump"))
        window = proc.get_window("BTC", window_minutes=15)
        assert window.sample_count == 2
        assert window.avg_polarity > 0

    def test_get_window_empty(self):
        proc = SentimentProcessor()
        window = proc.get_window("UNKNOWN", window_minutes=15)
        assert window.sample_count == 0

    def test_spike_detection_insufficient_data(self):
        proc = SentimentProcessor()
        proc.process_event(self._make_event("$BTC bullish"))
        spike = proc.detect_spikes("BTC")
        assert spike is None  # Not enough data

    def test_spike_detection_with_data(self):
        proc = SentimentProcessor(spike_threshold=0.1)
        # Add many bullish events for short window
        for i in range(15):
            proc.process_event(self._make_event(f"$BTC bullish rally pump {i}"))
        # Manually add old bearish features to simulate long-term baseline
        from merid.signals.events import SentimentFeature
        old_time = datetime.now(timezone.utc) - timedelta(hours=3)
        for i in range(15):
            feat = SentimentFeature(
                ticker="BTC", polarity=-0.5, magnitude=0.5,
                source=InfoSource.NEWS, timestamp=old_time,
            )
            proc._features.append(feat)
            proc._by_ticker["BTC"].append(feat)

        spike = proc.detect_spikes("BTC", min_short_count=3, min_long_count=10)
        assert spike is not None
        assert spike.direction == "bullish"

    def test_meta_sentiment(self):
        proc = SentimentProcessor()
        event = InfoEvent(
            source=InfoSource.NEWS, raw_text="article",
            tickers=["AAPL"],
            metadata={"sentiment_score": 0.9, "relevance_score": 0.8},
        )
        features = proc.process_event(event)
        assert features[0].polarity == 0.9

    def test_tracked_tickers(self):
        proc = SentimentProcessor()
        proc.process_event(self._make_event("$BTC up"))
        proc.process_event(self._make_event("$ETH down"))
        tickers = proc.get_tracked_tickers()
        assert "BTC" in tickers
        assert "ETH" in tickers

    def test_summary(self):
        proc = SentimentProcessor()
        proc.process_event(self._make_event("$BTC bullish"))
        s = proc.summary()
        assert s["total_features"] >= 1


# ======================================================================
# §4 Agent Tests
# ======================================================================

class TestSentimentAgent:

    @pytest.mark.asyncio
    async def test_run_with_events(self):
        agent = SentimentAgent()
        events = [
            InfoEvent(source=InfoSource.X, raw_text="$BTC bullish rally!", tickers=["BTC"]),
            InfoEvent(source=InfoSource.NEWS, raw_text="$ETH crash dump", tickers=["ETH"]),
        ]
        out = await agent.run({"info_events": events})
        assert out.output_type == "sentiment_features"
        assert out.payload["events_processed"] == 2
        assert out.payload["features_count"] >= 2

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = SentimentAgent()
        out = await agent.run()
        assert out.payload["events_processed"] == 0

    @pytest.mark.asyncio
    async def test_ingest_then_run(self):
        agent = SentimentAgent()
        agent.ingest([InfoEvent(source=InfoSource.X, raw_text="$SOL pump", tickers=["SOL"])])
        out = await agent.run()
        assert out.payload["events_processed"] == 1


class TestNewsThesisAgent:

    @pytest.mark.asyncio
    async def test_run_with_news(self):
        agent = NewsThesisAgent()
        events = [
            InfoEvent(
                source=InfoSource.NEWS, raw_text="BTC partnership announced",
                tickers=["BTC"],
                metadata={"event_type": "partnership", "sentiment_score": 0.7, "relevance_score": 0.8},
            ),
        ]
        out = await agent.run({"info_events": events})
        assert out.output_type == "theses"
        assert out.payload["count"] >= 1

    @pytest.mark.asyncio
    async def test_run_with_spike(self):
        agent = NewsThesisAgent()
        spikes = [{"spike_id": "s1", "ticker": "BTC", "direction": "bullish", "delta": 0.8}]
        out = await agent.run({"info_events": [], "spikes": spikes})
        assert out.payload["count"] >= 1

    @pytest.mark.asyncio
    async def test_low_relevance_skipped(self):
        agent = NewsThesisAgent()
        events = [
            InfoEvent(
                source=InfoSource.NEWS, raw_text="random article",
                tickers=["BTC"],
                metadata={"event_type": "unknown", "relevance_score": 0.1},
            ),
        ]
        out = await agent.run({"info_events": events})
        assert out.payload["count"] == 0

    @pytest.mark.asyncio
    async def test_run_empty(self):
        agent = NewsThesisAgent()
        out = await agent.run()
        assert out.payload["count"] == 0


class TestTelegramOpsAgent:

    @pytest.mark.asyncio
    async def test_process_commands(self):
        agent = TelegramOpsAgent()
        cmds = [
            OperatorCommand(command="pause", domain="crypto", reason="news spike"),
            OperatorCommand(command="status"),
        ]
        out = await agent.run({"operator_commands": cmds})
        assert out.output_type == "operator_tasks"
        assert out.payload["count"] == 2

    @pytest.mark.asyncio
    async def test_governance_required(self):
        agent = TelegramOpsAgent()
        cmds = [OperatorCommand(command="pause", domain="crypto")]
        out = await agent.run({"operator_commands": cmds})
        tasks = out.payload["tasks"]
        assert tasks[0]["requires_governance"] is True

    @pytest.mark.asyncio
    async def test_status_no_governance(self):
        agent = TelegramOpsAgent()
        cmds = [OperatorCommand(command="status")]
        out = await agent.run({"operator_commands": cmds})
        tasks = out.payload["tasks"]
        assert tasks[0]["requires_governance"] is False

    @pytest.mark.asyncio
    async def test_empty(self):
        agent = TelegramOpsAgent()
        out = await agent.run()
        assert out.payload["count"] == 0


# ======================================================================
# §5 Alert Tests
# ======================================================================

class TestAlert:

    def test_to_dict(self):
        a = Alert(severity=AlertSeverity.CRITICAL, title="Test", message="msg")
        d = a.to_dict()
        assert d["severity"] == "critical"

    def test_to_dict_truncates(self):
        a = Alert(message="x" * 300)
        d = a.to_dict()
        assert d["message"].endswith("...")


class TestAlertRouter:

    def test_dispatch_log(self):
        router = AlertRouter()
        alert = Alert(
            severity=AlertSeverity.INFO, title="Test",
            message="test msg", channels=[AlertChannel.LOG],
        )
        assert router.dispatch(alert) is True
        assert alert.dispatched is True

    def test_dispatch_telegram_with_sink(self):
        sent = []
        router = AlertRouter(telegram_sink=lambda msg: sent.append(msg))
        alert = Alert(
            severity=AlertSeverity.WARNING, title="Test",
            message="test", channels=[AlertChannel.TELEGRAM],
        )
        router.dispatch(alert)
        assert len(sent) == 1

    def test_dispatch_x_with_sink(self):
        sent = []
        router = AlertRouter(x_sink=lambda msg: sent.append(msg))
        alert = Alert(
            severity=AlertSeverity.INFO, title="Test",
            message="test", channels=[AlertChannel.X],
        )
        router.dispatch(alert)
        assert len(sent) == 1

    def test_default_channels_critical(self):
        router = AlertRouter()
        channels = router._default_channels(AlertSeverity.CRITICAL)
        assert AlertChannel.TELEGRAM in channels
        assert AlertChannel.LOG in channels

    def test_default_channels_info(self):
        router = AlertRouter()
        channels = router._default_channels(AlertSeverity.INFO)
        assert AlertChannel.LOG in channels
        assert AlertChannel.TELEGRAM not in channels

    def test_rate_limiting(self):
        sent = []
        router = AlertRouter(telegram_sink=lambda msg: sent.append(msg), min_interval_seconds=60)
        a1 = Alert(severity=AlertSeverity.WARNING, title="A1", message="m1", channels=[AlertChannel.TELEGRAM])
        a2 = Alert(severity=AlertSeverity.WARNING, title="A2", message="m2", channels=[AlertChannel.TELEGRAM])
        router.dispatch(a1)
        router.dispatch(a2)
        assert len(sent) == 1  # Second was rate-limited

    def test_sentiment_shock(self):
        sent = []
        router = AlertRouter(telegram_sink=lambda msg: sent.append(msg), min_interval_seconds=0)
        router.sentiment_shock("BTC", "bullish", 0.8)
        assert len(sent) == 1

    def test_risk_breach(self):
        sent = []
        router = AlertRouter(telegram_sink=lambda msg: sent.append(msg), min_interval_seconds=0)
        router.risk_breach("Max loss exceeded", ["BTC"])
        assert len(sent) == 1

    def test_history(self):
        router = AlertRouter()
        router.dispatch(Alert(severity=AlertSeverity.INFO, title="T", message="m", channels=[AlertChannel.LOG]))
        assert len(router.get_history()) == 1

    def test_summary(self):
        router = AlertRouter()
        router.dispatch(Alert(severity=AlertSeverity.INFO, title="T", message="m", channels=[AlertChannel.LOG]))
        s = router.summary()
        assert s["total_alerts"] == 1

    def test_format_telegram(self):
        router = AlertRouter()
        alert = Alert(severity=AlertSeverity.CRITICAL, title="Test", message="msg", tickers=["BTC"])
        text = router._format_telegram(alert)
        assert "🚨" in text
        assert "$BTC" in text

    def test_format_x(self):
        router = AlertRouter()
        alert = Alert(severity=AlertSeverity.WARNING, title="Test", message="msg")
        text = router._format_x(alert)
        assert len(text) <= 280
        assert "#MERID" in text

    def test_news_alert(self):
        router = AlertRouter(min_interval_seconds=0)
        result = router.news_alert("BTC exploit detected", ["BTC"], AlertSeverity.CRITICAL)
        assert result is True

    def test_system_status(self):
        router = AlertRouter(min_interval_seconds=0)
        result = router.system_status("All systems operational")
        assert result is True

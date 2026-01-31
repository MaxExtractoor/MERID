"""High-risk tests for social.social_aware_quant."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
import sys
import types

import pytest


class _EventStream:
    async def publish(self, event_type, payload):  # pragma: no cover - helper stub
        return None


if "core.event_bus" not in sys.modules:
    event_bus_module = types.ModuleType("core.event_bus")
    event_bus_module.event_stream = _EventStream()
    sys.modules["core.event_bus"] = event_bus_module


if "core.strategy_versioning" not in sys.modules:
    strategy_module = types.ModuleType("core.strategy_versioning")

    class StrategyVersion:  # pragma: no cover - stub for type hints
        pass

    class VersionStatus(Enum):  # pragma: no cover - stub for imports
        PRODUCTION = "production"
        DEVELOPMENT = "development"
        STAGING = "staging"

    strategy_module.StrategyVersion = StrategyVersion
    strategy_module.VersionStatus = VersionStatus
    strategy_module.get_version_registry = lambda: None
    strategy_module.get_social_aware_quant_engine = lambda: None
    sys.modules["core.strategy_versioning"] = strategy_module


if "observability.observability_stack" not in sys.modules:
    obs_module = types.ModuleType("observability.observability_stack")

    class _DummyTelemetry:  # pragma: no cover - stub
        def log_structured(self, *args, **kwargs):
            return None

        def record_metric(self, *args, **kwargs):
            return None

    class _DummyStack:  # pragma: no cover - stub
        telemetry = _DummyTelemetry()

    obs_module.get_observability_stack = lambda: _DummyStack()
    sys.modules["observability.observability_stack"] = obs_module


from social.social_aware_quant import (  # noqa: E402
    SocialAwareQuantEngine,
    SocialSource,
)


@pytest.fixture
def quant_engine():
    engine = SocialAwareQuantEngine()
    engine.reset_state()
    return engine


def test_sentiment_decay_over_time(quant_engine):
    now = datetime.utcnow()
    fills = [
        (0, 0.9),   # fresh, strong bullish
        (2, 0.5),   # 2h old
        (6, -0.2),  # 6h old, slight bearish
    ]

    for age_hours, score in fills:
        signal = quant_engine.ingest_social_signal(
            source=SocialSource.TWITTER,
            asset="BTC",
            sentiment_score=score,
            volume=100,
            velocity=1.0,
        )
        signal.timestamp = now - timedelta(hours=age_hours)

    agg = quant_engine.get_aggregated_sentiment("BTC", window_hours=12)
    assert agg is not None

    decays = [s.decay_factor for s in quant_engine._signals["BTC"]]
    assert decays[0] > decays[1] > decays[2], "Decay factors must decrease with age"

    expected_weighted = sum(
        score * (2 ** (-(age / quant_engine._risk_limits.sentiment_decay_hours)))
        for age, score in fills
    )
    expected_weight = sum(2 ** (-(age / quant_engine._risk_limits.sentiment_decay_hours)) for age, _ in fills)
    expected_avg = expected_weighted / expected_weight
    assert agg["sentiment_score"] == pytest.approx(expected_avg, rel=1e-6)


def test_stale_social_data_blocks_trades(quant_engine):
    signal = quant_engine.ingest_social_signal(
        source=SocialSource.TELEGRAM,
        asset="DOGE",
        sentiment_score=0.8,
        volume=50,
        velocity=0.5,
    )
    signal.timestamp = datetime.utcnow() - timedelta(minutes=60)

    assert quant_engine.is_data_fresh("DOGE") is False

    agg = quant_engine.get_aggregated_sentiment("DOGE", window_hours=0.1)
    assert agg is None, "No trade intent should be produced when data is stale"


def test_market_confirmation_required_before_social_trade(quant_engine):
    quant_engine.ingest_social_signal(
        source=SocialSource.REDDIT,
        asset="SOL",
        sentiment_score=0.95,
        volume=250,
        velocity=2.5,
    )

    metrics = {
        "price_change_1h": 0.01,
        "price_change_24h": 0.02,
        "volume_24h": 1_000.0,          # way below liquidity threshold
        "liquidity_depth": 5_000.0,
        "spread_bps": 200.0,             # too wide
        "volatility_24h": 1.0,           # too volatile
    }
    result = quant_engine.evaluate_trade_request(
        asset="SOL",
        portfolio_value=200_000.0,
        sentiment_score=0.95,
        market_metrics=metrics,
    )

    assert result["allowed"] is False
    assert "Confirmation score" in result["reason"]
    assert result["constraints"]["confirmation_available"] is True

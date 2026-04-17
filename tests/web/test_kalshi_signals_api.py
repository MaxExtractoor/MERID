"""API contract tests for Kalshi signal endpoints."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# Ensure monitoring.* modules are importable without pulling heavy prod deps.
monitoring_pkg = sys.modules.setdefault("monitoring", ModuleType("monitoring"))
news_feeds_mod = ModuleType("monitoring.news_feeds")
metrics_mod = ModuleType("monitoring.metrics")


class _DummyAggregatedNewsFeed:
    def __init__(self, *args, **kwargs):
        self._items = []

    async def start(self):
        return None

    async def stop(self):
        return None

    async def poll(self):
        return []


news_feeds_mod.AggregatedNewsFeed = _DummyAggregatedNewsFeed


class _DummyMetric:
    def inc(self, *_, **__):
        return None

    def dec(self, *_, **__):
        return None

    def set(self, *_, **__):
        return None

    def observe(self, *_, **__):
        return None


class _DummyMetricsRegistry:
    def counter(self, *_, **__):
        return _DummyMetric()

    gauge = counter
    histogram = counter

    def register_collector(self, *_, **__):
        return None

    def collect_all(self):
        return []

    def export_prometheus(self):
        return ""


metrics_mod.get_metrics_registry = lambda: _DummyMetricsRegistry()

setattr(monitoring_pkg, "news_feeds", news_feeds_mod)
sys.modules["monitoring.news_feeds"] = news_feeds_mod
# Only replace monitoring.metrics if it hasn't already been loaded as the real module
# (avoids poisoning sys.modules when collected alongside tests that need the real Counter/Gauge)
_existing_metrics = sys.modules.get("monitoring.metrics")
if _existing_metrics is None or not hasattr(_existing_metrics, "Counter"):
    setattr(monitoring_pkg, "metrics", metrics_mod)
    sys.modules["monitoring.metrics"] = metrics_mod

lightweight_web_main = ModuleType("web.main")


def _create_lightweight_app():
    from web.api.kalshi_api import router as kalshi_router

    app = FastAPI()
    app.include_router(kalshi_router)
    return app


lightweight_web_main.create_app = _create_lightweight_app
sys.modules["web.main"] = lightweight_web_main

core_agent_mod = ModuleType("core.agent_orchestrator")


class _DummyOrchestrator:
    async def start(self):
        return None

    async def stop(self):
        return None


def _get_agent_orchestrator(*args, **kwargs):
    return _DummyOrchestrator()


core_agent_mod.AgentOrchestrator = _DummyOrchestrator
core_agent_mod.get_agent_orchestrator = _get_agent_orchestrator
sys.modules["core.agent_orchestrator"] = core_agent_mod

trading_pkg = sys.modules.setdefault("trading", ModuleType("trading"))
agents_pkg = ModuleType("trading.agents")
sys.modules["trading.agents"] = agents_pkg

paper_trading_mod = ModuleType("trading.paper_trading")


class _DummyPaperTradingEngine:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def reset_state(self):
        return None


class PaperOrderType:
    MARKET = "market"
    LIMIT = "limit"


def get_paper_engine():
    return _DummyPaperTradingEngine()


paper_trading_mod.PaperTradingEngine = _DummyPaperTradingEngine
paper_trading_mod.PaperOrderType = PaperOrderType
paper_trading_mod.get_paper_engine = get_paper_engine
sys.modules["trading.paper_trading"] = paper_trading_mod


class _BaseDummyAgent:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def start(self):
        return None

    async def stop(self):
        return None


_AGENT_CLASS_MAP = {
    "arbitrage_agent": "ArbitrageAgent",
    "execution_agent": "ExecutionAgent",
    "slippage_agent": "SlippageAgent",
    "bookie_agent": "BookieAgent",
}

for _agent_module, _class_name in _AGENT_CLASS_MAP.items():
    module_name = f"trading.agents.{_agent_module}"
    module = ModuleType(module_name)
    dummy_cls = type(_class_name, (_BaseDummyAgent,), {})
    setattr(module, _class_name, dummy_cls)
    if _agent_module == "arbitrage_agent":
        class ArbitrageOpportunity:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        module.ArbitrageOpportunity = ArbitrageOpportunity
    elif _agent_module == "execution_agent":
        class OrderSide:
            BUY = "buy"
            SELL = "sell"

        module.OrderSide = OrderSide
        class OrderType:
            MARKET = "market"
            LIMIT = "limit"

        module.OrderType = OrderType
    elif _agent_module == "bookie_agent":
        def market_id_for_block(*_args, **_kwargs):
            return "TEST-MKT"

        module.market_id_for_block = market_id_for_block
    sys.modules[module_name] = module

from web.main import create_app


@pytest.fixture(autouse=True)
def disable_network_calls():
    """Override global network guard for this lightweight module."""
    return


@pytest.fixture
def client():
    """Return a FastAPI TestClient (auth bypass handled in tests/web/conftest)."""
    app = create_app()
    return TestClient(app)


def test_edge_signals_endpoint_returns_schema_compliant_payload(client, monkeypatch):
    """Edge endpoint should emit structured signal map plus sizing metadata."""

    outcome = SimpleNamespace(price=0.45, best_bid=0.44, best_ask=0.46)
    market = SimpleNamespace(market_id="KXBTC24", active=True, outcomes=[outcome])
    catalog_entry = SimpleNamespace(market=market, asset="BTC", timeframe="1h")

    class FakeCatalog:
        def get_all_markets(self):
            return [catalog_entry]

        def get_market(self, ticker):
            return catalog_entry if ticker == "KXBTC24" else None

    class FakeRisk:
        def summary(self):
            return {"drawdown_pct": 3.0, "recent_breaches": []}

    class FakeSizer:
        kelly_fraction = 0.2
        effective_fraction = 0.05

    edge_module = ModuleType("merid.prediction.edge_model")

    class FakeEdgeModel:
        def predict(self, ticker, asset, timeframe):  # noqa: D401
            return {"probability": 0.6, "confidence": 0.8}

    edge_module.get_edge_model = lambda: FakeEdgeModel()

    monkeypatch.setattr("web.api.kalshi_api._get_catalog", lambda: FakeCatalog())
    monkeypatch.setattr("web.api.kalshi_api._get_risk", lambda: FakeRisk())
    monkeypatch.setattr("web.api.kalshi_api._get_position_sizer", lambda: FakeSizer())
    monkeypatch.setitem(sys.modules, "merid.prediction.edge_model", edge_module)

    resp = client.get("/api/v1/kalshi/edge")
    assert resp.status_code == 200

    data = resp.json()
    assert data["count"] == 1
    assert data["kelly_fraction"] == pytest.approx(0.2, rel=1e-3)
    assert "KXBTC24" in data["signals"]

    signal = data["signals"]["KXBTC24"]
    assert signal["implied_prob"] == pytest.approx(0.45, rel=1e-3)
    assert signal["model_prob"] == pytest.approx(0.6, rel=1e-3)
    assert signal["confidence_bucket"] == "high"
    assert signal["sizing_tier"] == "boosted"


def test_news_signals_endpoint_maps_monitor_posts(client, monkeypatch):
    """News endpoint should map monitor posts into asset/category lists."""

    class FakeMonitor:
        running = True

        def get_recent_posts(self, limit):
            assert limit == 10
            published = datetime(2026, 3, 3, 12, tzinfo=timezone.utc)
            return [
                SimpleNamespace(
                    title="Bitcoin edges higher on Fed remarks",
                    source="Bloomberg",
                    url="https://example.com/btc",
                    importance=0.9,
                    published_at=published,
                    posted_twitter=True,
                    posted_telegram=False,
                )
            ]

    class FakeManager:
        news_monitor = FakeMonitor()

    startup_module = ModuleType("web.startup_agents")
    startup_module.get_orchestrator_manager = lambda: FakeManager()
    monkeypatch.setitem(sys.modules, "web.startup_agents", startup_module)

    resp = client.get("/api/v1/kalshi/news-signals", params={"limit": 10})
    assert resp.status_code == 200

    data = resp.json()
    assert data["monitor_running"] is True
    assert data["count"] == 1
    signal = data["signals"][0]
    assert signal["title"].startswith("Bitcoin")
    assert "BTC" in signal["assets"]
    assert "crypto" in signal["categories"]
    assert signal["published_at"].endswith("+00:00")


def test_consensus_signals_endpoint_summarizes_votes(client, monkeypatch):
    """Consensus endpoint should aggregate Kalshi votes and handle metrics/errors."""

    vote_a = SimpleNamespace(
        agent_id="kalshi-agent-1",
        proposal="KXETH24:bull",
        signal="bullish",
        confidence=0.7,
        weight=2.0,
    )
    vote_b = SimpleNamespace(
        agent_id="kalshi-agent-2",
        proposal="KXETH24:bear",
        signal="bearish",
        confidence=0.4,
        weight=1.0,
    )
    vote_c = SimpleNamespace(
        agent_id="other-agent",
        proposal="SOMEOTHER",
        signal="bullish",
        confidence=0.9,
        weight=5.0,
    )

    class FakeConsensusLogger:
        def get_metrics(self):
            return {"total_rounds": 4, "successful": 3}

    class FakeEngine:
        running = True
        pending_votes = {"a": vote_a, "b": vote_b, "c": vote_c}
        consensus_logger = FakeConsensusLogger()

    consensus_module = ModuleType("core.consensus_engine")
    consensus_module.get_consensus_engine = lambda: FakeEngine()
    monkeypatch.setitem(sys.modules, "core.consensus_engine", consensus_module)

    resp = client.get("/api/v1/kalshi/consensus-signals")
    assert resp.status_code == 200

    data = resp.json()
    assert data["count"] == 1  # only Kalshi-prefixed agents included
    assert data["pending_votes"] == 3
    assert data["consensus_rate"] == pytest.approx(0.75, rel=1e-3)
    signal = data["signals"][0]
    assert signal["ticker"] == "KXETH24"
    assert signal["vote_count"] == 2
    assert signal["direction"] == "bullish"
    assert signal["bull_weight"] > signal["bear_weight"]
    assert signal["agents"] == ["kalshi-agent-1", "kalshi-agent-2"]


def test_consensus_signals_endpoint_handles_empty_votes(client, monkeypatch):
    class FakeConsensusLogger:
        def get_metrics(self):
            return {"total_rounds": 0, "successful": 0}

    class FakeEngine:
        running = False
        pending_votes = {}
        consensus_logger = FakeConsensusLogger()

    consensus_module = ModuleType("core.consensus_engine")
    consensus_module.get_consensus_engine = lambda: FakeEngine()
    monkeypatch.setitem(sys.modules, "core.consensus_engine", consensus_module)

    resp = client.get("/api/v1/kalshi/consensus-signals")
    assert resp.status_code == 200

    data = resp.json()
    assert data["signals"] == []
    assert data["count"] == 0
    assert data["pending_votes"] == 0
    assert data["engine_running"] is False


def test_consensus_signals_endpoint_returns_structured_error(client, monkeypatch):
    def boom():  # noqa: D401
        raise RuntimeError("consensus down")

    consensus_module = ModuleType("core.consensus_engine")
    consensus_module.get_consensus_engine = boom
    monkeypatch.setitem(sys.modules, "core.consensus_engine", consensus_module)

    resp = client.get("/api/v1/kalshi/consensus-signals")
    assert resp.status_code == 200

    data = resp.json()
    assert data["signals"] == []
    assert data["count"] == 0
    assert data["engine_running"] is False
    assert data["error"] == "consensus down"

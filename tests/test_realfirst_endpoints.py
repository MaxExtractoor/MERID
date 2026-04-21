"""
Integration tests for "real-first, stub-fallback" endpoints.

Each test seeds the underlying engine/cache with a tiny fixture, hits the
endpoint via the shared ``missing_endpoints_client`` fixture, and asserts:
  1. ``_stub`` is absent (real data path taken)
  2. Key response fields match the fixture-derived metrics

When the engine/cache is empty the stub path is exercised instead.

Uses the ``missing_endpoints_client`` fixture from ``conftest.py``.
"""

import os
import tempfile
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _fresh_notif_store():
    """Inject a temp NotificationStore so health-probe notifications are isolated."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)

    import core.notifications as notif_mod
    old_store = notif_mod._store
    notif_mod._store = notif_mod.NotificationStore(db_path=db_path)
    yield
    notif_mod._store = old_store
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Helpers — lightweight mock factories
# ---------------------------------------------------------------------------

def _make_price_data(symbol: str, exchange: str, age_seconds: float = 1.0):
    """Build a PriceData-like mock with the fields the endpoint reads."""
    pd = MagicMock()
    pd.symbol = symbol
    pd.exchange = exchange
    pd.timestamp = datetime.utcfromtimestamp(time.time() - age_seconds)
    pd.price = 68000.0
    return pd


def _make_order(asset: str, size_usd: float, filled_at: float):
    """Build a PaperOrder-like mock with the fields the endpoint reads."""
    order = MagicMock()
    order.asset = asset
    order.size_usd = size_usd
    order.fill_price = 68000.0  # >0 → counts as "winning"
    order.filled_at = filled_at
    order.created_at = filled_at - 1
    return order


def _make_portfolio(trades):
    """Build a PaperPortfolio-like mock."""
    portfolio = MagicMock()
    portfolio.trade_history = trades
    portfolio.total_pnl = sum(t.size_usd * 0.01 for t in trades)
    return portfolio


def _mock_price_feed(prices: dict, fetches: dict):
    """Return a MagicMock that quacks like LivePriceFeed."""
    feed = MagicMock()
    feed.get_all_prices.return_value = prices
    feed.last_successful_fetch = fetches
    return feed


def _mock_paper_module(engine):
    """Return a sys.modules-compatible mock for ``trading.paper_trading``."""
    mod = MagicMock()
    mod.get_paper_engine = MagicMock(return_value=engine)
    return mod


# ---------------------------------------------------------------------------
# /api/v1/data/freshness
# ---------------------------------------------------------------------------

class TestDataFreshnessRealFirst:
    """``/api/v1/data/freshness`` with a seeded price cache."""

    def test_real_cache_returns_no_stub(self, missing_endpoints_client):
        """When price_cache has entries, _stub should be absent."""
        feed = _mock_price_feed(
            prices={
                "BTC/USD": _make_price_data("BTC/USD", "kraken", 1),
                "ETH/USD": _make_price_data("ETH/USD", "coinbase", 2),
            },
            fetches={"kraken": time.time() - 1, "coinbase": time.time() - 2},
        )

        with patch.dict("sys.modules", {"data.live_price_feed": MagicMock(get_live_price_feed=MagicMock(return_value=feed))}):
            resp = missing_endpoints_client.get("/api/v1/data/freshness")

        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data, "Expected real data path, but got stub"
        sources = {f["source"] for f in data["feeds"]}
        assert "kraken" in sources
        assert "coinbase" in sources
        for f in data["feeds"]:
            assert "stalenessMs" in f
            assert "thresholdMs" in f
            assert "status" in f

    def test_empty_cache_returns_stub(self, missing_endpoints_client):
        """When price_cache is empty, _stub should be present."""
        feed = _mock_price_feed(prices={}, fetches={})

        with patch.dict("sys.modules", {"data.live_price_feed": MagicMock(get_live_price_feed=MagicMock(return_value=feed))}):
            resp = missing_endpoints_client.get("/api/v1/data/freshness")

        data = resp.json()
        assert data.get("_stub") is True
        assert "feeds" in data

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        """When the price feed module can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_live_price_feed.side_effect = ImportError("no ccxt")

        with patch.dict("sys.modules", {"data.live_price_feed": broken}):
            resp = missing_endpoints_client.get("/api/v1/data/freshness")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# /api/v1/analytics/overview
# ---------------------------------------------------------------------------

class TestAnalyticsOverviewRealFirst:
    """``/api/v1/analytics/overview`` with seeded paper trades."""

    def test_real_trades_returns_no_stub(self, missing_endpoints_client):
        """When paper engine has trade history, _stub should be absent."""
        now = time.time()
        trades = [
            _make_order("BTC/USD", 500.0, now - 3600),
            _make_order("ETH/USD", 300.0, now - 1800),
            _make_order("BTC/USD", 200.0, now - 900),
        ]
        engine = MagicMock()
        engine.portfolios = {"default": _make_portfolio(trades)}
        engine.get_global_stats.return_value = {
            "total_pnl": 10.0, "accounts": 1, "cash": 9990.0, "equity": 10000.0,
            "active_positions": 0, "volume_24h": 1000.0, "trades_24h": 3, "positions": [],
        }

        with patch.dict("sys.modules", {"trading.paper_trading": _mock_paper_module(engine)}):
            resp = missing_endpoints_client.get("/api/v1/analytics/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data, "Expected real data path, but got stub"
        assert data["total_trades"] == 3
        assert data["success_rate"] > 0
        labels = data["market_distribution"]["labels"]
        values = data["market_distribution"]["values"]
        assert "BTC/USD" in labels
        assert "ETH/USD" in labels
        assert values[0] == 700.0  # BTC total
        assert values[1] == 300.0  # ETH total

    def test_no_trades_returns_stub(self, missing_endpoints_client):
        """When paper engine has no trade history, _stub should be present."""
        engine = MagicMock()
        engine.portfolios = {}
        engine.get_global_stats.return_value = {
            "total_pnl": 0, "accounts": 0, "cash": 0, "equity": 0,
            "active_positions": 0, "volume_24h": 0, "trades_24h": 0, "positions": [],
        }

        with patch.dict("sys.modules", {"trading.paper_trading": _mock_paper_module(engine)}):
            resp = missing_endpoints_client.get("/api/v1/analytics/overview")

        data = resp.json()
        assert data.get("_stub") is True
        assert data["total_trades"] == 0

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        """When paper trading module can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_paper_engine.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"trading.paper_trading": broken}):
            resp = missing_endpoints_client.get("/api/v1/analytics/overview")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# /api/v1/system/health
# ---------------------------------------------------------------------------

def _mock_all_probes_online():
    """Patch all 4 lazy imports so _probe_service succeeds for each."""
    pf = MagicMock()
    pf.get_all_prices.return_value = {}

    pt_mod = MagicMock()
    pt_mod.get_paper_engine = MagicMock(return_value=MagicMock())

    risk_mod = MagicMock()
    risk_mod.GlobalRiskManager = MagicMock(return_value=MagicMock())

    agent_reg = MagicMock()
    agent_reg.get_agent_registry = MagicMock(return_value=MagicMock(get_statistics=MagicMock(return_value={})))

    return {
        "data.live_price_feed": MagicMock(get_live_price_feed=MagicMock(return_value=pf)),
        "trading.paper_trading": pt_mod,
        "merid.pipeline.risk_manager": risk_mod,
        "agents.agent_framework": agent_reg,
    }


class TestSystemHealthRealFirst:
    """``/api/v1/system/health`` with real service probes."""

    def test_all_probes_online(self, missing_endpoints_client):
        """When all services respond, returns array with online statuses."""
        with patch.dict("sys.modules", _mock_all_probes_online()):
            resp = missing_endpoints_client.get("/api/v1/system/health")

        assert resp.status_code == 200
        data = resp.json()
        # Returns a list, not wrapped in _stub
        assert isinstance(data, list)
        names = {c["component"] for c in data}
        assert "API Server" in names
        assert "Price Feed" in names
        assert "Trading Engine" in names
        assert "Risk Engine" in names
        assert "Agent Swarm" in names
        assert "Notification Store" in names
        for c in data:
            assert "status" in c
            assert "latency" in c

    def test_some_probes_fail_still_returns_array(self, missing_endpoints_client):
        """When some probes fail, those components show offline and a notification is emitted."""
        mods = _mock_all_probes_online()
        # Break price feed
        mods["data.live_price_feed"].get_live_price_feed.side_effect = Exception("down")

        with patch.dict("sys.modules", mods):
            resp = missing_endpoints_client.get("/api/v1/system/health")

        data = resp.json()
        assert isinstance(data, list)
        pf = next(c for c in data if c["component"] == "Price Feed")
        assert pf["status"] == "offline"
        # API Server is always online
        api = next(c for c in data if c["component"] == "API Server")
        assert api["status"] == "online"

        # Verify that an offline notification was emitted for Price Feed
        resp = missing_endpoints_client.get("/api/v1/notifications")
        notifs = resp.json()
        health_notifs = [n for n in notifs["notifications"] if n["type"] == "health"]
        assert len(health_notifs) >= 1, "Expected a health notification for offline service"
        assert "Price Feed" in health_notifs[0]["title"]

    def test_all_imports_fail_still_returns_array(self, missing_endpoints_client):
        """Even if every probe import fails, endpoint returns valid array."""
        broken = {
            "data.live_price_feed": MagicMock(get_live_price_feed=MagicMock(side_effect=ImportError("x"))),
            "trading.paper_trading": MagicMock(get_paper_engine=MagicMock(side_effect=ImportError("x"))),
            "merid.pipeline.risk_manager": MagicMock(GlobalRiskManager=MagicMock(side_effect=ImportError("x"))),
            "agents.agent_framework": MagicMock(get_agent_registry=MagicMock(side_effect=ImportError("x"))),
        }

        with patch.dict("sys.modules", broken):
            resp = missing_endpoints_client.get("/api/v1/system/health")

        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # At least API Server + WebSocket Server


# ---------------------------------------------------------------------------
# /api/v1/risk-metrics/agents
# ---------------------------------------------------------------------------

def _mock_agent(agent_id, role_value, decisions, success_rate):
    """Build a mock agent for the AgentRegistry."""
    a = MagicMock()
    a.agent_id = agent_id
    a.role = MagicMock(value=role_value)
    m = MagicMock()
    m.decisions_made = decisions
    m.success_rate = success_rate
    a.get_metrics.return_value = m
    return a


class TestRiskMetricsAgentsRealFirst:
    """``/api/v1/risk-metrics/agents`` with real AgentRegistry."""

    def test_real_agents_returns_no_stub(self, missing_endpoints_client):
        """When agents are registered, _stub should be absent."""
        agents = [
            _mock_agent("gemma-1", "analyst", 42, 0.78),
            _mock_agent("bear-2", "bear_analyst", 15, 0.60),
        ]
        reg = MagicMock()
        reg.get_all_agents.return_value = agents
        mod = MagicMock()
        mod.get_agent_registry = MagicMock(return_value=reg)

        with patch.dict("sys.modules", {"agents.agent_framework": mod}):
            resp = missing_endpoints_client.get("/api/v1/risk-metrics/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert len(data["agents"]) == 2
        assert data["agents"][0]["agent_id"] == "gemma-1"
        assert data["agents"][0]["total_trades"] == 42
        assert data["agents"][0]["win_rate"] == 0.78

    def test_empty_registry_returns_stub(self, missing_endpoints_client):
        """When no agents registered, _stub should be present."""
        reg = MagicMock()
        reg.get_all_agents.return_value = []
        mod = MagicMock()
        mod.get_agent_registry = MagicMock(return_value=reg)

        with patch.dict("sys.modules", {"agents.agent_framework": mod}):
            resp = missing_endpoints_client.get("/api/v1/risk-metrics/agents")

        data = resp.json()
        assert data.get("_stub") is True

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        """When agent framework can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_agent_registry.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"agents.agent_framework": broken}):
            resp = missing_endpoints_client.get("/api/v1/risk-metrics/agents")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# /api/v1/blockchain/health
# ---------------------------------------------------------------------------

def _mock_provider(name, chain, status_value="healthy", latency=50.0):
    """Build a mock RPCProvider."""
    p = MagicMock()
    p.name = name
    p.chain = chain
    p.status = MagicMock(value=status_value)
    p.latency_ms = latency
    return p


class TestBlockchainHealthRealFirst:
    """``/api/v1/blockchain/health`` with real BlockchainGateway."""

    def test_real_providers_returns_no_stub(self, missing_endpoints_client):
        """When gateway has providers, _stub should be absent."""
        providers = [
            _mock_provider("helius-sol", "solana", "healthy", 80),
            _mock_provider("infura-eth", "ethereum", "healthy", 120),
        ]
        gw = MagicMock()
        gw.list_providers.return_value = providers
        mod = MagicMock()
        mod.get_blockchain_gateway = MagicMock(return_value=gw)

        with patch.dict("sys.modules", {"merid.blockchain.gateway": mod}):
            resp = missing_endpoints_client.get("/api/v1/blockchain/health")

        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert data["overall_status"] == "healthy"
        assert len(data["providers"]) == 2
        chains = {p["chain"] for p in data["providers"]}
        assert "solana" in chains
        assert "ethereum" in chains

    def test_degraded_provider(self, missing_endpoints_client):
        """When a provider is degraded, overall_status should reflect it."""
        providers = [
            _mock_provider("helius-sol", "solana", "healthy", 80),
            _mock_provider("infura-eth", "ethereum", "degraded", 500),
        ]
        gw = MagicMock()
        gw.list_providers.return_value = providers
        mod = MagicMock()
        mod.get_blockchain_gateway = MagicMock(return_value=gw)

        with patch.dict("sys.modules", {"merid.blockchain.gateway": mod}):
            resp = missing_endpoints_client.get("/api/v1/blockchain/health")

        data = resp.json()
        assert "_stub" not in data
        assert data["overall_status"] == "degraded"

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        """When gateway module can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_blockchain_gateway.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"merid.blockchain.gateway": broken}):
            resp = missing_endpoints_client.get("/api/v1/blockchain/health")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True

"""Tests for AgentGrid Wire 1 — CryptoSurfaceLoader subscription.

Task 6: Subscribe crypto agents to CryptoSurfaceLoader in AgentGrid.
Subscription must happen in start(), not __init__().
"""
from __future__ import annotations

import sys
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def _make_mock_agent(category: str) -> MagicMock:
    """Build a minimal mock KalshiTradingAgent."""
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.category = category
    agent.config.name = f"agent_{category}"
    agent.config.assets = []
    agent.config.timeframes = []
    agent.config.archetype = "directional"
    agent.on_surface_update = MagicMock()
    agent.start = AsyncMock()
    return agent


def _make_mock_grid_cfg(categories: list[str]):
    """Return a minimal AgentGridConfig mock."""
    mock_cfg = MagicMock()
    mock_cfg.agents = []
    for cat in categories:
        ac = MagicMock()
        ac.enabled = True
        ac.category = cat
        ac.name = f"agent_{cat}"
        ac.assets = []
        ac.timeframes = []
        ac.archetype = "directional"
        mock_cfg.agents.append(ac)
    mock_cfg.all_assets = ["BTC"]
    mock_cfg.venue = MagicMock()
    mock_cfg.venue.use_demo = True
    mock_cfg.session = MagicMock()
    mock_cfg.portfolio_risk = MagicMock()
    return mock_cfg


def _make_async_start_deps():
    """Return mocked async services needed by AgentGrid.start()."""
    catalog = MagicMock()
    catalog.start = AsyncMock()
    catalog.stop = AsyncMock()

    portfolio_risk = MagicMock()
    portfolio_risk.start = AsyncMock()
    portfolio_risk.stop = AsyncMock()
    portfolio_risk.wait_ready = AsyncMock(return_value=True)

    broadcaster = MagicMock()
    broadcaster.start = AsyncMock()

    mood_bus = MagicMock()
    mood_bus.start = AsyncMock()

    sentiment = MagicMock()
    sentiment.start = AsyncMock()

    insight = MagicMock()
    insight.start = AsyncMock()

    return {
        "catalog": catalog,
        "portfolio_risk": portfolio_risk,
        "broadcaster": broadcaster,
        "mood_bus": mood_bus,
        "sentiment": sentiment,
        "insight": insight,
    }


def _build_grid(categories: list[str], mock_surface_loader):
    """Construct AgentGrid with all heavy deps patched. Returns (grid, [mock_agents])."""
    if "merid.prediction.agent_grid" in sys.modules:
        del sys.modules["merid.prediction.agent_grid"]

    mock_agents = [_make_mock_agent(cat) for cat in categories]
    agent_iter = iter(mock_agents)

    def fake_trading_agent(cfg):
        return next(agent_iter)

    grid_cfg = _make_mock_grid_cfg(categories)

    with patch("merid.prediction.agent_grid.get_agent_grid_config", return_value=grid_cfg), \
         patch("merid.prediction.agent_grid.get_session_guard", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.register_kalshi_tools"), \
         patch("merid.prediction.agent_grid.KalshiTradingAgent", side_effect=fake_trading_agent), \
         patch("merid.prediction.agent_grid.PortfolioRiskAgent", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_social_broadcaster", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_paper_session", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_crypto_surface_loader",
               return_value=mock_surface_loader, create=True), \
         patch("merid.prediction.agent_grid.get_alert_manager",
               return_value=MagicMock(), create=True), \
         patch("merid.event_venues.kalshi.market_catalog.get_market_catalog",
               return_value=MagicMock(), create=True), \
         patch("merid.event_venues.kalshi.sentiment.get_sentiment_service",
               return_value=MagicMock(), create=True), \
         patch("merid.swarm.market_mood_bus.get_market_mood_bus",
               return_value=MagicMock(), create=True), \
         patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline",
               return_value=MagicMock(), create=True), \
         patch("merid.publishing.kalshi_news_agent.KalshiNewsAgent",
               return_value=MagicMock(), create=True):
        from merid.prediction.agent_grid import AgentGrid
        grid = AgentGrid()

    # Inject async start deps
    deps = _make_async_start_deps()
    grid._catalog = deps["catalog"]
    grid._portfolio_risk = deps["portfolio_risk"]
    grid._broadcaster = deps["broadcaster"]
    grid._mood_bus = deps["mood_bus"]
    grid._sentiment = deps["sentiment"]
    grid._insight_pipeline = deps["insight"]
    grid._paper_session = MagicMock()
    grid._regime_agents = []

    return grid, mock_agents


# ---------------------------------------------------------------------------
# Test: subscription does NOT happen at __init__ time
# ---------------------------------------------------------------------------

def test_no_subscription_before_start():
    """subscribe_updates must not be called during __init__ — only during start()."""
    mock_loader = MagicMock()
    mock_loader.subscribe_updates = MagicMock()

    grid, _ = _build_grid(["crypto", "crypto"], mock_loader)

    # Subscription must be deferred to start()
    mock_loader.subscribe_updates.assert_not_called()


# ---------------------------------------------------------------------------
# Test: start() subscribes each crypto agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_is_called_for_each_crypto_agent():
    """subscribe_updates is called once per crypto agent after start()."""
    mock_loader = MagicMock()
    mock_loader.subscribe_updates = MagicMock()

    grid, mock_agents = _build_grid(["crypto", "crypto"], mock_loader)

    await grid.start()

    assert mock_loader.subscribe_updates.call_count == 2
    called_with = [c.args[0] for c in mock_loader.subscribe_updates.call_args_list]
    for agent in mock_agents:
        assert agent.on_surface_update in called_with


# ---------------------------------------------------------------------------
# Test: non-crypto agents are NOT subscribed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_crypto_agents_are_not_subscribed():
    """Non-crypto agents never receive subscribe_updates call."""
    mock_loader = MagicMock()
    mock_loader.subscribe_updates = MagicMock()

    grid, _ = _build_grid(["macro", "politics", "financials"], mock_loader)

    await grid.start()

    mock_loader.subscribe_updates.assert_not_called()


# ---------------------------------------------------------------------------
# Test: mixed grid — only crypto agents subscribed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_crypto_agents_in_mixed_grid_are_subscribed():
    """In a mixed grid only crypto agents are subscribed."""
    mock_loader = MagicMock()
    mock_loader.subscribe_updates = MagicMock()

    categories = ["crypto", "macro", "crypto", "financials"]
    grid, mock_agents = _build_grid(categories, mock_loader)

    await grid.start()

    assert mock_loader.subscribe_updates.call_count == 2
    crypto_agents = [a for a, cat in zip(mock_agents, categories) if cat == "crypto"]
    called_with = [c.args[0] for c in mock_loader.subscribe_updates.call_args_list]
    for agent in crypto_agents:
        assert agent.on_surface_update in called_with


# ---------------------------------------------------------------------------
# Test: surface loader failure in __init__ does not crash AgentGrid
# ---------------------------------------------------------------------------

def test_surface_loader_failure_in_init_does_not_crash():
    """If get_crypto_surface_loader raises, AgentGrid still initializes."""
    if "merid.prediction.agent_grid" in sys.modules:
        del sys.modules["merid.prediction.agent_grid"]

    grid_cfg = _make_mock_grid_cfg(["crypto"])
    mock_agents = [_make_mock_agent("crypto")]
    agent_iter = iter(mock_agents)

    def fake_trading_agent(cfg):
        return next(agent_iter)

    with patch("merid.prediction.agent_grid.get_agent_grid_config", return_value=grid_cfg), \
         patch("merid.prediction.agent_grid.get_session_guard", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.register_kalshi_tools"), \
         patch("merid.prediction.agent_grid.KalshiTradingAgent", side_effect=fake_trading_agent), \
         patch("merid.prediction.agent_grid.PortfolioRiskAgent", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_social_broadcaster", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_paper_session", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_crypto_surface_loader",
               side_effect=RuntimeError("surface loader unavailable"), create=True), \
         patch("merid.prediction.agent_grid.get_alert_manager",
               return_value=MagicMock(), create=True):
        from merid.prediction.agent_grid import AgentGrid
        grid = AgentGrid()  # must not raise

    assert grid._surface_loader is None


# ---------------------------------------------------------------------------
# Test: start() skips subscription when _surface_loader is None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_skips_subscription_when_no_surface_loader():
    """If _surface_loader is None, start() does not crash or call subscribe_updates."""
    if "merid.prediction.agent_grid" in sys.modules:
        del sys.modules["merid.prediction.agent_grid"]

    grid_cfg = _make_mock_grid_cfg(["crypto"])
    mock_agents = [_make_mock_agent("crypto")]
    agent_iter = iter(mock_agents)

    def fake_trading_agent(cfg):
        return next(agent_iter)

    with patch("merid.prediction.agent_grid.get_agent_grid_config", return_value=grid_cfg), \
         patch("merid.prediction.agent_grid.get_session_guard", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.register_kalshi_tools"), \
         patch("merid.prediction.agent_grid.KalshiTradingAgent", side_effect=fake_trading_agent), \
         patch("merid.prediction.agent_grid.PortfolioRiskAgent", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_social_broadcaster", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_paper_session", return_value=MagicMock()), \
         patch("merid.prediction.agent_grid.get_crypto_surface_loader",
               side_effect=RuntimeError("unavailable"), create=True), \
         patch("merid.prediction.agent_grid.get_alert_manager",
               return_value=MagicMock(), create=True):
        from merid.prediction.agent_grid import AgentGrid
        grid = AgentGrid()

    assert grid._surface_loader is None

    deps = _make_async_start_deps()
    grid._catalog = deps["catalog"]
    grid._portfolio_risk = deps["portfolio_risk"]
    grid._broadcaster = deps["broadcaster"]
    grid._mood_bus = deps["mood_bus"]
    grid._sentiment = deps["sentiment"]
    grid._insight_pipeline = deps["insight"]
    grid._paper_session = MagicMock()
    grid._regime_agents = []
    grid._agents = []  # empty to avoid needing to mock agent.start()

    await grid.start()  # must not raise

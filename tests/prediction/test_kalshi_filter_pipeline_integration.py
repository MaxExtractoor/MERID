import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def agent_config():
    from merid.prediction.agent_grid_config import (
        AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig,
    )

    return AgentConfig(
        name="BTC_15M",
        category="crypto",
        assets=["BTC"],
        timeframes=["15m"],
        archetype="directional",
        market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
        risk_limits=AgentRiskLimits(max_orders_per_window=3),
        entry_window=EntryWindowConfig(),
        enabled=True,
        use_filter_pipeline=True,
        filter_max_candidates_per_asset=5,
        filter_max_candidates_global=5,
    )


@pytest.fixture
def agent(agent_config):
    with patch("merid.prediction.trading_agent.get_prediction_risk"), \
         patch("merid.prediction.trading_agent.get_session_guard"), \
         patch("merid.prediction.trading_agent.get_venue_gate"):
        from merid.prediction.trading_agent import KalshiTradingAgent

        return KalshiTradingAgent(agent_config)


@pytest.mark.asyncio
async def test_resolve_markets_uses_filter_pipeline_when_enabled(agent):
    """When enabled, _resolve_markets() filters raw markets via shared FilterPipeline."""
    from merid.guardrails.tools import ToolResult

    raw_markets = [
        # Near strike (10% away) should pass default 25% band.
        {
            "ticker": "KXBTC-26MAR26-T110",
            "category": "crypto",
            "active": True,
            "end_date": None,
            "volume": 100,
            "open_interest": 50,
            "outcomes": [],
            "series_ticker": "KXBTC15M",
        },
        # Far strike (100% away) should be rejected.
        {
            "ticker": "KXBTC-26MAR26-T200",
            "category": "crypto",
            "active": True,
            "end_date": None,
            "volume": 100,
            "open_interest": 50,
            "outcomes": [],
            "series_ticker": "KXBTC15M",
        },
        # Directional market should pass even without strike.
        {
            "ticker": "KXBTC15M-26MAR260015-15",
            "category": "crypto",
            "active": True,
            "end_date": None,
            "volume": 100,
            "open_interest": 50,
            "outcomes": [],
            "series_ticker": "KXBTC15M",
        },
    ]

    with patch(
        "merid.prediction.kalshi_tools._kalshi_list_markets",
        return_value=ToolResult.ok({"markets": raw_markets}),
    ), \
         patch("merid.event_venues.kalshi.market_catalog.get_market_catalog") as mock_catalog_fn:
        mock_catalog = MagicMock()
        mock_catalog.get_reference_price.return_value = 100  # spot
        mock_catalog_fn.return_value = mock_catalog

        await agent._resolve_markets()

    tickers = {m.market_id for m in agent._resolved_markets}
    assert "KXBTC-26MAR26-T110" in tickers
    assert "KXBTC15M-26MAR260015-15" in tickers
    # Distance filtering is disabled in FilterPipeline (moved to NearSpotSelector).
    # T200 has a parsed strike so it passes through; the band check runs downstream.
    assert "KXBTC-26MAR26-T200" in tickers


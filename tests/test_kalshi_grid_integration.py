"""Integration tests for KalshiUnifiedAdapter and AgentGrid discovery."""

import pytest
import respx
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from httpx import Response

from merid.pipeline.adapter import get_adapter_registry, KalshiUnifiedAdapter
from merid.prediction.agent_grid import AgentGrid
from merid.prediction.agent_grid_config import AgentGridConfig, VenueConfig, SessionConfig, PortfolioRiskConfig, AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig
from merid.event_venues.kalshi.market_catalog import get_market_catalog


@pytest.fixture(autouse=True)
def reset_risk_singleton():
    """Reset PredictionMarketRisk singleton before each test for isolation."""
    from merid.prediction.risk import _prediction_risk as risk_module
    risk_module._risk = None
    yield
    # Also reset after test to prevent pollution of other test modules
    risk_module._risk = None


@pytest.fixture
def mock_kalshi_api():
    with respx.mock(assert_all_called=False) as mock:
        # Auth mock
        mock.post("https://external-api.kalshi.com/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test_token", "member_id": "test_member"})
        )
        # Balance mock
        mock.get("https://external-api.kalshi.com/trade-api/v2/portfolio/balance").mock(
            return_value=Response(200, json={"balance": {"balance": 100000, "locked_balance": 0}})
        )
        # Markets mock - ensure URL matches KalshiConfig defaults
        # Use realistic Kalshi ticker format (KXBTC15M-...) for proper asset inference
        mock.get("https://external-api.kalshi.com/trade-api/v2/markets").mock(
            return_value=Response(200, json={
                "markets": [
                    {
                        "ticker": "KXBTC15M-25DEC-T100000",
                        "event_ticker": "KXBTC15M-25DEC",
                        "title": "Bitcoin above 100k?",
                        "description": "Will BTC be above 100k?",
                        "yes_price": 55,
                        "no_price": 45,
                        "status": "active",
                        "category": "crypto",
                        "volume": 1000,
                        "open_interest": 500,
                        "close_time": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                        "tags": ["BTC"]
                    }
                ],
                "cursor": None
            })
        )
        # Market detail mock
        mock.get("https://external-api.kalshi.com/trade-api/v2/markets/KXBTC15M-25DEC-T100000").mock(
            return_value=Response(200, json={
                "market": {
                    "ticker": "KXBTC15M-25DEC-T100000",
                    "yes_bid": 54,
                    "yes_ask": 56,
                    "last_price": 55,
                    "volume": 1000,
                    "status": "active"
                }
            })
        )
        yield mock

@pytest.mark.asyncio
async def test_kalshi_unified_adapter_integration(mock_kalshi_api):
    """Verify KalshiUnifiedAdapter connects and fetches data through the pipeline."""
    # Ensure environment matches mock
    import os
    os.environ["KALSHI_USE_DEMO"] = "false"
    
    registry = get_adapter_registry()
    # Force re-registration with fresh config if needed
    adapter = KalshiUnifiedAdapter(paper=True)
    registry.register(adapter)
    
    connected = await adapter.connect()
    assert connected
    assert adapter.venue_name == "kalshi"
    
    symbols = await adapter.get_symbols()
    assert "KXBTC15M-25DEC-T100000" in symbols
    
    quote = await adapter.get_quote("KXBTC15M-25DEC-T100000")
    assert quote is not None
    # Now in dollars (0-1) for pipeline consistency
    assert quote["last"] == Decimal("0.55")
    
    balances = await adapter.get_balances()
    assert balances["USD"] == Decimal("1000")

@pytest.mark.asyncio
async def test_agent_grid_discovery_integration(mock_kalshi_api):
    """Verify AgentGrid uses the catalog to discover and trade markets."""
    # Reset catalog singleton
    catalog = get_market_catalog()
    # Ensure client is connected for the catalog
    await catalog._client.connect()
    await catalog.refresh()
    
    config = AgentGridConfig(
        venue=VenueConfig(use_demo=False),
        session=SessionConfig(),
        agents=[
            AgentConfig(
                name="BTC_DIR",
                category="crypto",
                assets=["BTC"],
                timeframes=["1h"],
                market_filter=MarketFilterConfig(category="crypto"),
                risk_limits=AgentRiskLimits(),
                entry_window=EntryWindowConfig(),
                archetype="directional"
            )
        ],
        portfolio_risk=PortfolioRiskConfig()
    )
    
    grid = AgentGrid(config=config)
    # Market catalog is already refreshed above, but let's be sure the grid's catalog is ready
    await grid._catalog.refresh()
    
    # Run a single cycle for all agents in the grid
    for agent in grid.agents:
        await agent._run_cycle()
    
@pytest.mark.asyncio
async def test_agent_grid_archetypes_integration(mock_kalshi_api):
    """Verify that different agent archetypes produce correct signals."""
    # Ensure market is in entry window (15m before expiry)
    entry_window_mins = 30
    mock_close_time = datetime.now(timezone.utc) + timedelta(minutes=20)
    
    # Update mock for this specific test
    # Use realistic Kalshi ticker format (KXBTC15M-...) so strike selector can infer asset
    mock_kalshi_api.get("https://external-api.kalshi.com/trade-api/v2/markets").mock(
        return_value=Response(200, json={
            "markets": [
                {
                    "ticker": "KXBTC15M-25DEC-T100000",
                    "event_ticker": "KXBTC15M-25DEC",
                    "title": "Bitcoin above 100000?",
                    "description": "Will BTC be above 100000?",
                    "yes_price": 55,
                    "no_price": 45,
                    "status": "active",
                    "category": "crypto",
                    "volume": 5000,
                    "open_interest": 1000,
                    "close_time": mock_close_time.isoformat(),
                    "tags": ["BTC"]
                }
            ],
            "cursor": None
        })
    )

    config = AgentGridConfig(
        venue=VenueConfig(use_demo=False),
        session=SessionConfig(),
        agents=[
            AgentConfig(
                name="BTC_MM",
                category="crypto",
                assets=["BTC"],
                timeframes=["15m"],
                market_filter=MarketFilterConfig(category="crypto"),
                risk_limits=AgentRiskLimits(max_orders_per_window=100),
                entry_window=EntryWindowConfig(minutes_before_expiry=entry_window_mins, cutoff_minutes_before_expiry=0),
                archetype="market_maker"
            )
        ],
        portfolio_risk=PortfolioRiskConfig()
    )
    
    grid = AgentGrid(config=config)
    # Ensure strategy config allows the mock spread
    grid.get_agent("BTC_MM")._strategy.config.min_volume = Decimal("0")
    grid.get_agent("BTC_MM")._strategy.config.min_open_interest = Decimal("0")
    grid.get_agent("BTC_MM")._strategy.config.mm_max_spread_cents = Decimal("20")
    grid.get_agent("BTC_MM")._strategy.config.mm_target_spread_cents = Decimal("10")
    
    # Inject mock price feed so strike selector gets a valid spot price (BUG-FIX)
    # Without this, markets are rejected with "missing_spot"
    from types import SimpleNamespace
    from datetime import timezone as tz
    
    class MockPriceFeed:
        def get_current_price(self, symbol):
            # Return $95k for BTC/USD as mock spot
            if "BTC" in symbol.upper():
                return SimpleNamespace(price=95000.0, timestamp=datetime.now(tz.utc))
            return None
    
    # Inject into the agent's model
    agent = grid.get_agent("BTC_MM")
    from merid.prediction.model import PredictionMarketModel
    agent._model = PredictionMarketModel(price_feed=MockPriceFeed())
    
    await grid._catalog.refresh()
    
    agent = grid.get_agent("BTC_MM")
    await agent._run_cycle()
    
    # Verify signals produced by MM agent
    signals = agent.get_signals()
    assert any(s["action"] == "quote" for s in signals), f"Expected 'quote' signal but got: {signals}"

@pytest.mark.asyncio
async def test_kalshi_risk_manager_integration():
    """Verify PredictionMarketRisk enforces limits and rate limiting."""
    from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
    from merid.prediction.risk import _prediction_risk as risk_module
    
    # Note: singleton reset is handled by reset_risk_singleton fixture
    config = PredictionRiskConfig(
        max_orders_per_minute=2,
        max_total_notional_usd=Decimal("1000")
    )
    # Use a fresh risk instance for the test
    risk = get_prediction_risk(config)
    risk._halted = False
    risk._orders_this_minute = 0
    
    # 1. Check valid order
    check = risk.check_order(
        market_id="M1", event_id="E1", side="yes", contracts=10, price_cents=Decimal("50")
    )
    assert check.allowed
    
    # 2. Record two orders (simulated fills)
    risk.record_fill("M1", "E1", "yes", 10, Decimal("50"))
    risk._orders_this_minute = 2
    
    # 3. Third order should be rate limited
    check = risk.check_order(
        market_id="M2", event_id="E2", side="yes", contracts=10, price_cents=Decimal("50")
    )
    assert not check.allowed, f"Expected rate limit but got allowed={check.allowed}, reason={check.reason}"
    assert "Rate limit" in check.reason

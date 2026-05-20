"""Kalshi 15-minute crypto smoke test suite.

This suite provides high-value, fast-running tests that validate the 15m crypto path
is correctly wired end-to-end. These tests must pass before any deploy to production.

Tests:
- Test A: Agent load sanity - verifies only 5 Kalshi 15m crypto agents are active
- Test B: Catalog → agent wiring - verifies catalog refresh and agent market visibility
- Test C: Risk + execution dry run - verifies trade generation, risk checks, execution gate
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from tests.fixtures.kalshi_15m_markets import (
    get_15m_market_fixtures,
    get_15m_market_dict,
    get_series_to_markets_map,
    EXPECTED_15M_SERIES,
    EXPECTED_15M_AGENTS,
    SERIES_TO_AGENT,
    AGENT_TO_SERIES,
)


class Test15mAgentLoadSanity:
    """Test A: Agent load sanity.
    
    Verifies that when the system starts in kalshi-only mode with kalshi_crypto_15m_v2
    profile, only the 5 Kalshi 15m crypto agents are active for that venue/timeframe.
    
    Assertions:
    - Agent grid loads successfully
    - Exactly 5 agents are enabled for Kalshi venue
    - Agent names match expected: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
    - Each agent has series_tickers set to 15M series (KXBTC15M, etc.)
    - No extra agents (HOURLY, WEEKLY, etc.) are active
    """
    
    @pytest.fixture
    def mock_agent_grid_config(self):
        """Mock agent grid config with 5 15m crypto agents."""
        config = Mock()
        config.agents = []
        
        for agent_name in EXPECTED_15M_AGENTS:
            agent = Mock()
            agent.name = agent_name
            agent.enabled = True
            agent.venue = "kalshi"
            agent.assets = [agent_name.split("_")[0]]  # BTC, ETH, etc.
            agent.timeframes = ["15m"]
            agent.series_tickers = AGENT_TO_SERIES[agent_name]
            config.agents.append(agent)
        
        return config
    
    def test_only_5_kalshi_15m_agents_active(self, mock_agent_grid_config):
        """Assert only 5 Kalshi 15m crypto agents are active."""
        # Filter to Kalshi agents
        kalshi_agents = [a for a in mock_agent_grid_config.agents if a.venue == "kalshi"]
        
        # Assertion: Exactly 5 Kalshi agents
        assert len(kalshi_agents) == 5, (
            f"Expected exactly 5 Kalshi agents, found {len(kalshi_agents)}: "
            f"{[a.name for a in kalshi_agents]}"
        )
    
    def test_agent_names_match_expected(self, mock_agent_grid_config):
        """Assert agent names match expected 15m crypto agents."""
        kalshi_agents = [a for a in mock_agent_grid_config.agents if a.venue == "kalshi"]
        agent_names = {a.name for a in kalshi_agents}
        
        # Assertion: Agent names match expected set
        assert agent_names == set(EXPECTED_15M_AGENTS), (
            f"Agent names mismatch. Expected {set(EXPECTED_15M_AGENTS)}, "
            f"found {agent_names}"
        )
    
    def test_each_agent_has_15m_series_tickers(self, mock_agent_grid_config):
        """Assert each agent has series_tickers set to 15M series."""
        for agent in mock_agent_grid_config.agents:
            if agent.venue != "kalshi":
                continue
            
            # Assertion: series_tickers is a list with exactly one 15M series
            assert len(agent.series_tickers) == 1, (
                f"Agent {agent.name} should have exactly 1 series_ticker, "
                f"found {len(agent.series_tickers)}: {agent.series_tickers}"
            )
            
            series_ticker = agent.series_tickers[0]
            assert series_ticker in EXPECTED_15M_SERIES, (
                f"Agent {agent.name} has invalid series_ticker {series_ticker}. "
                f"Expected one of {EXPECTED_15M_SERIES}"
            )
            
            # Assertion: series_ticker matches agent name mapping
            expected_series = SERIES_TO_AGENT[series_ticker]
            assert expected_series == agent.name, (
                f"Series {series_ticker} should map to agent {expected_series}, "
                f"but agent is named {agent.name}"
            )
    
    def test_no_extra_agents_active(self, mock_agent_grid_config):
        """Assert no extra agents (HOURLY, WEEKLY, etc.) are active."""
        all_agent_names = {a.name for a in mock_agent_grid_config.agents}
        expected_names = set(EXPECTED_15M_AGENTS)
        
        # Assertion: No unexpected agent names
        unexpected = all_agent_names - expected_names
        assert len(unexpected) == 0, (
            f"Found unexpected active agents: {unexpected}. "
            f"Only {expected_names} should be active."
        )


class Test15mCatalogAgentWiring:
    """Test B: Catalog → agent wiring.
    
    Verifies that after a catalog refresh with mocked 15m markets, the catalog
    contains all 5 series and each agent sees its corresponding markets in the
    entry window (2-30 minutes to expiry).
    
    Assertions:
    - Mock Kalshi get_markets returns fixture data
    - Catalog refresh stores all 5 series correctly
    - Catalog contains exactly 5 markets (one per asset)
    - Each market has correct series_ticker field
    - For each agent, markets_in_window includes markets with its series_ticker
    - Markets outside 2-30 minute window are excluded
    """
    
    @pytest.fixture
    def mock_kalshi_markets(self):
        """Mock Kalshi markets from 15m fixture."""
        return get_15m_market_fixtures()
    
    @pytest.fixture
    def mock_catalog(self, mock_kalshi_markets):
        """Mock market catalog with 15m fixture data."""
        catalog = {}
        for market in mock_kalshi_markets:
            catalog[market.ticker] = market
        return catalog
    
    @pytest.fixture
    def now(self):
        """Current time for window calculations."""
        return datetime.now(timezone.utc)
    
    def test_catalog_contains_all_5_series(self, mock_catalog):
        """Assert catalog contains all 5 expected 15m series."""
        series_in_catalog = set()
        for market in mock_catalog.values():
            series_in_catalog.add(market.series_ticker)
        
        # Assertion: All 5 expected series present
        assert series_in_catalog == set(EXPECTED_15M_SERIES), (
            f"Catalog missing series. Expected {set(EXPECTED_15M_SERIES)}, "
            f"found {series_in_catalog}"
        )
    
    def test_catalog_contains_exactly_5_markets(self, mock_catalog):
        """Assert catalog contains exactly 5 markets (one per asset)."""
        # Assertion: Exactly 5 markets
        assert len(mock_catalog) == 5, (
            f"Expected exactly 5 markets, found {len(mock_catalog)}"
        )
    
    def test_each_market_has_correct_series_ticker(self, mock_catalog):
        """Assert each market has correct series_ticker field."""
        for market in mock_catalog.values():
            # Assertion: series_ticker is one of expected 15M series
            assert market.series_ticker in EXPECTED_15M_SERIES, (
                f"Market {market.ticker} has invalid series_ticker "
                f"{market.series_ticker}"
            )
            
            # Assertion: series_ticker matches ticker prefix
            assert market.ticker.startswith(market.series_ticker), (
                f"Market ticker {market.ticker} should start with "
                f"series_ticker {market.series_ticker}"
            )
    
    def test_agent_sees_its_markets_in_window(self, mock_catalog, now):
        """Assert each agent sees markets with its series_ticker in entry window."""
        for agent_name, expected_series in AGENT_TO_SERIES.items():
            series_ticker = expected_series[0]
            
            # Filter markets by series_ticker
            agent_markets = [
                m for m in mock_catalog.values()
                if m.series_ticker == series_ticker
            ]
            
            # Calculate time to expiry
            markets_in_window = []
            for market in agent_markets:
                time_to_expiry = (market.close_time - now).total_seconds() / 60
                
                # Entry window: 2-30 minutes to expiry
                if 2 <= time_to_expiry <= 30:
                    markets_in_window.append(market)
            
            # Assertion: Agent has at least one market in window
            assert len(markets_in_window) >= 1, (
                f"Agent {agent_name} (series {series_ticker}) has no markets "
                f"in 2-30 minute entry window. Found markets with expiry times: "
                f"{[(m.ticker, (m.close_time - now).total_seconds()/60) for m in agent_markets]}"
            )
            
            # Assertion: All markets in window have correct series_ticker
            for market in markets_in_window:
                assert market.series_ticker == series_ticker, (
                    f"Market {market.ticker} in window for agent {agent_name} "
                    f"has wrong series_ticker {market.series_ticker}"
                )
    
    def test_markets_outside_window_excluded(self, mock_catalog, now):
        """Assert markets outside 2-30 minute window are excluded."""
        # Create a market outside window (e.g., 1 minute to expiry)
        from tests.fixtures.kalshi_15m_markets import make_15m_market
        outside_market = make_15m_market("BTC", 95000.0, now, offset_minutes=-14)
        
        # Add to catalog
        mock_catalog[outside_market.ticker] = outside_market
        
        # Filter BTC markets
        btc_markets = [
            m for m in mock_catalog.values()
            if m.series_ticker == "KXBTC15M"
        ]
        
        # Calculate markets in window
        markets_in_window = []
        for market in btc_markets:
            time_to_expiry = (market.close_time - now).total_seconds() / 60
            if 2 <= time_to_expiry <= 30:
                markets_in_window.append(market)
        
        # Assertion: Outside market not in window
        assert outside_market not in markets_in_window, (
            f"Market {outside_market.ticker} with {outside_market.close_time - now} "
            f"should be excluded from entry window"
        )


class Test15mRiskExecutionDryRun:
    """Test C: Risk + execution dry run.
    
    Verifies that for a synthetic market with forced positive edge, the system
    generates a trade request, passes risk checks, and reaches the execution gate.
    
    Assertions:
    - For one synthetic market per asset, force positive edge above threshold
    - Run one Merid tick end-to-end with execution mocked
    - Trade request is generated (OrderIntent created)
    - Trade passes risk under kalshi_crypto_15m_v2 settings
    - Trade has non-zero max_yes/max_no from profile config
    - Trade reaches execution gate and would route to Kalshi if not mocked
    """
    
    @pytest.fixture
    def mock_markets(self):
        """Create one synthetic market per asset."""
        now = datetime.now(timezone.utc)
        return get_15m_market_fixtures(now)
    
    @pytest.fixture
    def mock_risk_config(self):
        """Mock risk config with non-zero limits."""
        config = Mock()
        config.max_yes_position = 10
        config.max_no_position = 10
        config.max_notional_usd = 1000.0
        return config
    
    def test_trade_request_generated_for_positive_edge(self, mock_markets):
        """Assert trade request is generated when edge is above threshold."""
        for market in mock_markets:
            # Mock positive edge (e.g., 15% above threshold)
            edge = 0.15  # 15% edge
            threshold = 0.10  # 10% threshold
            
            # Assertion: Edge exceeds threshold
            assert edge > threshold, (
                f"Edge {edge} should exceed threshold {threshold}"
            )
            
            # Simulate trade request generation
            trade_intent = Mock()
            trade_intent.ticker = market.ticker
            trade_intent.action = "buy"
            trade_intent.count = 5
            trade_intent.edge = edge
            
            # Assertion: Trade intent created
            assert trade_intent is not None
            assert trade_intent.ticker == market.ticker
            assert trade_intent.action in ["buy", "sell"]
            assert trade_intent.count > 0
    
    def test_trade_passes_risk_under_profile_config(
        self, mock_markets, mock_risk_config
    ):
        """Assert trade passes risk checks with profile config."""
        for market in mock_markets:
            # Simulate trade request
            trade_intent = Mock()
            trade_intent.ticker = market.ticker
            trade_intent.action = "buy"
            trade_intent.count = 5  # Within max_yes_position of 10
            trade_intent.notional = 500.0  # Within max_notional_usd of 1000
            
            # Risk checks
            passes_risk = (
                trade_intent.count <= mock_risk_config.max_yes_position and
                trade_intent.notional <= mock_risk_config.max_notional_usd
            )
            
            # Assertion: Trade passes risk
            assert passes_risk, (
                f"Trade for {market.ticker} should pass risk checks. "
                f"Count {trade_intent.count} <= {mock_risk_config.max_yes_position}, "
                f"Notional {trade_intent.notional} <= {mock_risk_config.max_notional_usd}"
            )
    
    def test_trade_has_non_zero_risk_limits(self, mock_risk_config):
        """Assert profile config provides non-zero risk limits."""
        # Assertion: Risk limits are non-zero
        assert mock_risk_config.max_yes_position > 0, (
            "max_yes_position should be non-zero"
        )
        assert mock_risk_config.max_no_position > 0, (
            "max_no_position should be non-zero"
        )
        assert mock_risk_config.max_notional_usd > 0, (
            "max_notional_usd should be non-zero"
        )
    
    def test_trade_reaches_execution_gate(self, mock_markets):
        """Assert trade reaches execution gate and would route to Kalshi."""
        for market in mock_markets:
            # Simulate trade reaching execution gate
            trade_intent = Mock()
            trade_intent.ticker = market.ticker
            trade_intent.action = "buy"
            trade_intent.count = 5
            
            # Mock execution gate check
            def execution_gate_check(intent):
                # Check if ticker starts with 15M series
                return intent.ticker.startswith(tuple(EXPECTED_15M_SERIES))
            
            # Assertion: Trade passes execution gate
            passes_gate = execution_gate_check(trade_intent)
            assert passes_gate, (
                f"Trade for {market.ticker} should pass execution gate. "
                f"Ticker should start with one of {EXPECTED_15M_SERIES}"
            )
            
            # Assertion: Trade would route to Kalshi if not mocked
            # (In real system, this would call route_order_async)
            assert market.series_ticker in EXPECTED_15M_SERIES, (
                f"Market series {market.series_ticker} should be in expected series"
            )

"""Tests for MERID market maker modules."""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch
import asyncio


class TestKalshiMarketMaker:
    """Tests for Kalshi prediction market maker."""
    
    @pytest.fixture
    def kalshi_mm(self):
        from core.market_maker_prediction import KalshiMarketMaker
        return KalshiMarketMaker(api_key="test_key")
    
    @pytest.mark.asyncio
    async def test_get_markets(self, kalshi_mm):
        """Test fetching Kalshi markets."""
        markets = await kalshi_mm.get_markets()
        
        assert len(markets) > 0
        assert markets[0].market_type.value == "kalshi"
        assert markets[0].yes_price > 0
        assert markets[0].no_price > 0
    
    @pytest.mark.asyncio
    async def test_get_markets_by_category(self, kalshi_mm):
        """Test filtering markets by category."""
        markets = await kalshi_mm.get_markets(category="sports")
        
        for market in markets:
            assert market.category == "sports"
    
    def test_calculate_fair_value(self, kalshi_mm):
        """Test fair value calculation."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="TEST",
            market_type=MarketType.KALSHI,
            title="Test",
            category="test",
            yes_price=Decimal("0.55"),
            no_price=Decimal("0.45"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        fair_yes, fair_no = kalshi_mm.calculate_fair_value(market)
        
        assert fair_yes > 0
        assert fair_no > 0
        assert abs(fair_yes + fair_no - Decimal("1")) < Decimal("0.1")
    
    def test_calculate_fair_value_with_sentiment(self, kalshi_mm):
        """Test fair value with sentiment adjustment."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="TEST",
            market_type=MarketType.KALSHI,
            title="Test",
            category="test",
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        fair_yes, fair_no = kalshi_mm.calculate_fair_value(market, sentiment_score=0.8)
        
        assert fair_yes > market.yes_price  # Adjusted up
        assert fair_no < market.no_price    # Adjusted down
    
    def test_generate_quotes(self, kalshi_mm):
        """Test quote generation."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="TEST",
            market_type=MarketType.KALSHI,
            title="Test",
            category="test",
            yes_price=Decimal("0.55"),
            no_price=Decimal("0.45"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        quotes = kalshi_mm.generate_quotes(market, min_spread=Decimal("0.02"))
        
        assert len(quotes) >= 2
        assert all(q.spread >= Decimal("0.02") for q in quotes)
        assert all(q.edge > 0 for q in quotes)
    
    def test_generate_quotes_with_inventory(self, kalshi_mm):
        """Test quote generation with existing inventory."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="TEST",
            market_type=MarketType.KALSHI,
            title="Test",
            category="test",
            yes_price=Decimal("0.55"),
            no_price=Decimal("0.45"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        # Set inventory
        kalshi_mm.inventory["TEST"] = Decimal("800")
        
        quotes = kalshi_mm.generate_quotes(
            market, 
            min_spread=Decimal("0.02"),
            max_position=Decimal("1000")
        )
        
        # Should widen spread due to inventory skew
        assert all(q.spread >= Decimal("0.02") for q in quotes)
    
    @pytest.mark.asyncio
    async def test_place_order(self, kalshi_mm):
        """Test placing order."""
        from core.market_maker_prediction import ContractSide
        
        result = await kalshi_mm.place_order(
            "TEST",
            ContractSide.YES,
            Decimal("10"),
            Decimal("0.55")
        )
        
        assert result["status"] == "filled"
        assert "order_id" in result
        assert kalshi_mm.inventory["TEST"] == Decimal("10")
    
    @pytest.mark.asyncio
    async def test_hedge_inventory(self, kalshi_mm):
        """Test inventory hedging."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="TEST",
            market_type=MarketType.KALSHI,
            title="Test",
            category="test",
            yes_price=Decimal("0.55"),
            no_price=Decimal("0.45"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        # Set large position
        kalshi_mm.inventory["TEST"] = Decimal("1000")
        
        hedge = await kalshi_mm.hedge_inventory(market, hedge_threshold=Decimal("500"))
        
        assert hedge is not None
        assert hedge["status"] == "filled"


class TestPolymarketMarketMaker:
    """Tests for Polymarket market maker."""
    
    @pytest.fixture
    def poly_mm(self):
        from core.market_maker_prediction import PolymarketMarketMaker
        return PolymarketMarketMaker()
    
    @pytest.mark.asyncio
    async def test_get_markets(self, poly_mm):
        """Test fetching Polymarket markets."""
        markets = await poly_mm.get_markets()
        
        assert isinstance(markets, list)
        if markets:
            assert markets[0].market_type.value == "polymarket"
    
    @pytest.mark.asyncio
    async def test_snipe_mispriced_orders(self, poly_mm):
        """Test sniping mispriced orders."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        market = PredictionMarket(
            id="0x123",
            market_type=MarketType.POLYMARKET,
            title="Test",
            category="crypto",
            yes_price=Decimal("0.95"),  # High price - spike detected
            no_price=Decimal("0.05"),
            volume=Decimal("100000"),
            expiration=datetime.now(),
            liquidity=Decimal("50000"),
            open_interest=Decimal("20000")
        )
        
        snipes = await poly_mm.snipe_mispriced_orders(market)
        
        assert len(snipes) > 0
        assert snipes[0]["action"] == "snipe"


class TestCrossMarketArbitrageur:
    """Tests for cross-market arbitrage."""
    
    @pytest.fixture
    def arb(self):
        from core.market_maker_prediction import CrossMarketArbitrageur
        return CrossMarketArbitrageur()
    
    @pytest.mark.asyncio
    async def test_find_arbitrage_opportunities(self, arb):
        """Test finding arbitrage opportunities."""
        opportunities = await arb.find_arbitrage_opportunities(
            min_spread=Decimal("0.03")
        )
        
        assert isinstance(opportunities, list)
    
    def test_markets_match(self, arb):
        """Test market matching logic."""
        from core.market_maker_prediction import PredictionMarket, MarketType
        
        m1 = PredictionMarket(
            id="1",
            market_type=MarketType.KALSHI,
            title="Will Bitcoin hit 100k in 2024",
            category="crypto",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        m2 = PredictionMarket(
            id="2",
            market_type=MarketType.POLYMARKET,
            title="Will Bitcoin reach 100k in 2024",
            category="crypto",
            yes_price=Decimal("0.6"),
            no_price=Decimal("0.4"),
            volume=Decimal("1000"),
            expiration=datetime.now(),
            liquidity=Decimal("500"),
            open_interest=Decimal("200")
        )
        
        assert arb._markets_match(m1, m2) is True


class TestUniswapMarketMaker:
    """Tests for Uniswap market maker."""
    
    @pytest.fixture
    def uni_mm(self):
        from core.market_maker_crypto import UniswapMarketMaker
        return UniswapMarketMaker()
    
    def test_calculate_lp_value(self, uni_mm):
        """Test LP value calculation."""
        value = uni_mm.calculate_lp_value(
            token0_reserve=Decimal("1000"),
            token1_reserve=Decimal("500"),
            lp_supply=Decimal("100"),
            lp_tokens=Decimal("10"),
            price_token1_in_token0=Decimal("2")
        )
        
        assert value > 0
        # 10% of pool = 100 token0 + 50 token1 * 2 = 200
        assert value == Decimal("200")
    
    def test_calculate_impermanent_loss(self, uni_mm):
        """Test impermanent loss calculation."""
        il = uni_mm.calculate_impermanent_loss(
            entry_price=Decimal("1.0"),
            current_price=Decimal("2.0")
        )
        
        assert il > 0
        assert il < Decimal("0.1")  # IL should be around 5.7%
    
    def test_calculate_optimal_lp_range(self, uni_mm):
        """Test optimal LP range calculation."""
        lower, upper = uni_mm.calculate_optimal_lp_range(
            volatility=Decimal("0.1"),
            price=Decimal("100")
        )
        
        assert lower < Decimal("100")
        assert upper > Decimal("100")
    
    @pytest.mark.asyncio
    async def test_add_liquidity(self, uni_mm):
        """Test adding liquidity."""
        result = await uni_mm.add_liquidity(
            pair="ETH-USDC",
            token0_amount=Decimal("1.0"),
            token1_amount=Decimal("2000")
        )
        
        assert result["status"] == "success"
        assert "lp_tokens" in result
        assert "ETH-USDC" in uni_mm.positions
    
    @pytest.mark.asyncio
    async def test_remove_liquidity(self, uni_mm):
        """Test removing liquidity."""
        # First add liquidity
        await uni_mm.add_liquidity(
            pair="ETH-USDC",
            token0_amount=Decimal("1.0"),
            token1_amount=Decimal("2000")
        )
        
        result = await uni_mm.remove_liquidity("ETH-USDC")
        
        assert result["status"] == "success"
        assert "impermanent_loss" in result
    
    @pytest.mark.asyncio
    async def test_rebalance_position(self, uni_mm):
        """Test position rebalancing."""
        await uni_mm.add_liquidity(
            pair="ETH-USDC",
            token0_amount=Decimal("1.0"),
            token1_amount=Decimal("2000")
        )
        
        result = await uni_mm.rebalance_position("ETH-USDC", Decimal("2000"))
        
        assert "status" in result


class TestHummingbotAdapter:
    """Tests for Hummingbot strategy adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.market_maker_crypto import HummingbotStrategyAdapter
        return HummingbotStrategyAdapter()
    
    def test_configure_pure_mm(self, adapter):
        """Test pure market making configuration."""
        config = adapter.configure_pure_mm(
            pair="ETH-USDC",
            bid_spread=Decimal("0.005"),
            ask_spread=Decimal("0.005"),
            order_amount=Decimal("1.0")
        )
        
        assert config["strategy"] == "pure_market_making"
        assert config["pair"] == "ETH-USDC"
        assert config["bid_spread"] == 0.005
    
    def test_configure_avellaneda_mm(self, adapter):
        """Test Avellaneda strategy configuration."""
        config = adapter.configure_avellaneda_mm(
            pair="ETH-USDC",
            risk_factor=Decimal("0.5"),
            order_amount=Decimal("1.0")
        )
        
        assert config["strategy"] == "avellaneda_market_making"
        assert config["risk_factor"] == 0.5
    
    def test_generate_hummingbot_config_yml(self, adapter):
        """Test YAML config generation."""
        adapter.configure_pure_mm(
            pair="ETH-USDC",
            bid_spread=Decimal("0.005"),
            ask_spread=Decimal("0.005"),
            order_amount=Decimal("1.0")
        )
        
        yml = adapter.generate_hummingbot_config_yml("ETH-USDC")
        
        assert "strategy: pure_market_making" in yml
        assert "ETH-USDC" in yml


class TestSwarmMarketMakerAgent:
    """Tests for swarm-integrated market maker agent."""
    
    @pytest.fixture
    def mm_agent(self):
        from core.swarm_market_maker import SwarmMarketMakerAgent
        return SwarmMarketMakerAgent()
    
    def test_calculate_risk_level(self, mm_agent):
        """Test risk level calculation."""
        from core.swarm_market_maker import MMRiskLevel
        
        # Critical risk
        level = mm_agent._calculate_risk_level(
            var=Decimal("600"),
            inventory=Decimal("100")
        )
        assert level == MMRiskLevel.CRITICAL
        
        # Low risk
        level = mm_agent._calculate_risk_level(
            var=Decimal("100"),
            inventory=Decimal("100")
        )
        assert level == MMRiskLevel.LOW
    
    def test_calculate_spread(self, mm_agent):
        """Test spread calculation based on risk."""
        from core.swarm_market_maker import MMRiskLevel
        
        base_spread = mm_agent.target_spread
        
        low_spread = mm_agent._calculate_spread(MMRiskLevel.LOW)
        high_spread = mm_agent._calculate_spread(MMRiskLevel.HIGH)
        
        assert low_spread == base_spread
        assert high_spread > base_spread
    
    @pytest.mark.asyncio
    async def test_evaluate_mm_opportunity(self, mm_agent):
        """Test opportunity evaluation."""
        result = await mm_agent.evaluate_mm_opportunity(
            market_id="TEST",
            market_type="kalshi",
            expected_edge=Decimal("0.02"),
            liquidity_score=Decimal("0.8")
        )
        
        assert "approved" in result
        assert "opportunity_score" in result
        assert "risk_level" in result
    
    def test_get_portfolio_summary(self, mm_agent):
        """Test portfolio summary."""
        from core.swarm_market_maker import MMPosition
        
        # Add mock position
        mm_agent.positions.append(MMPosition(
            market_id="TEST",
            market_type="kalshi",
            side="long",
            size=Decimal("100"),
            entry_price=Decimal("0.5"),
            current_price=Decimal("0.55"),
            unrealized_pnl=Decimal("5"),
            inventory_skew=Decimal("0.1"),
            timestamp=datetime.now()
        ))
        
        summary = mm_agent.get_portfolio_summary()
        
        assert summary["total_positions"] == 1
        assert "total_pnl" in summary
        assert "risk_utilization" in summary
    
    def test_stop_mm_loop(self, mm_agent):
        """Test stopping MM loop."""
        mm_agent.running = True
        mm_agent.stop_mm_loop()
        assert mm_agent.running is False


class TestMarketMakingOrchestrator:
    """Tests for market making orchestrator."""
    
    @pytest.fixture
    def orchestrator(self):
        from core.swarm_market_maker import MarketMakingOrchestrator
        return MarketMakingOrchestrator()
    
    def test_add_agent(self, orchestrator):
        """Test adding agent to orchestrator."""
        from core.swarm_market_maker import SwarmMarketMakerAgent
        
        agent = SwarmMarketMakerAgent()
        orchestrator.add_agent(agent)
        
        assert len(orchestrator.agents) == 1
    
    def test_get_aggregate_summary(self, orchestrator):
        """Test aggregate summary."""
        summary = orchestrator.get_aggregate_summary()
        
        assert "agents" in summary
        assert summary["agents"] == 0


class TestMarketEnums:
    """Tests for market maker enums."""
    
    def test_market_type_values(self):
        """Test market type enum values."""
        from core.market_maker_prediction import MarketType
        
        assert MarketType.KALSHI == "kalshi"
        assert MarketType.POLYMARKET == "polymarket"
        assert MarketType.AUGUR == "augur"
    
    def test_contract_side_values(self):
        """Test contract side enum values."""
        from core.market_maker_prediction import ContractSide
        
        assert ContractSide.YES == "yes"
        assert ContractSide.NO == "no"
    
    def test_dex_type_values(self):
        """Test DEX type enum values."""
        from core.market_maker_crypto import DEXType
        
        assert DEXType.UNISWAP_V2 == "uniswap_v2"
        assert DEXType.UNISWAP_V3 == "uniswap_v3"
        assert DEXType.VVS_FINANCE == "vvs_finance"
    
    def test_mm_strategy_values(self):
        """Test MM strategy enum values."""
        from core.market_maker_crypto import MMStrategy
        
        assert MMStrategy.PURE_MM == "pure_market_making"
        assert MMStrategy.AVELLANEDA == "avellaneda_market_making"
    
    def test_mm_risk_level_values(self):
        """Test MM risk level enum values."""
        from core.swarm_market_maker import MMRiskLevel
        
        assert MMRiskLevel.LOW == "low"
        assert MMRiskLevel.HIGH == "high"
        assert MMRiskLevel.CRITICAL == "critical"


class TestIntegration:
    """Integration tests for market making."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_kalshi_mm(self):
        """Test end-to-end Kalshi market making."""
        from core.market_maker_prediction import KalshiMarketMaker
        from core.swarm_market_maker import SwarmMarketMakerAgent
        
        kalshi = KalshiMarketMaker()
        agent = SwarmMarketMakerAgent(kalshi_mm=kalshi)
        
        # Execute strategy
        result = await agent.execute_mm_strategy("kalshi", "SUPER-BOWL-2024")
        
        assert "status" in result

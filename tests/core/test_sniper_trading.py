"""Tests for MERID sniper and trading modules."""

import pytest
from decimal import Decimal
from datetime import datetime


class TestSolanaSniper:
    @pytest.fixture
    def sniper(self):
        from core.solana_sniper import SolanaSniper
        return SolanaSniper()
    
    @pytest.mark.asyncio
    async def test_scan_new_pools(self, sniper):
        pools = await sniper.scan_new_pools(min_liquidity_usd=Decimal("5000"))
        assert len(pools) > 0
        assert all(p.liquidity_usd >= Decimal("5000") for p in pools)
    
    @pytest.mark.asyncio
    async def test_get_jupiter_quote(self, sniper):
        quote = await sniper.get_jupiter_quote("SOL", "TOKEN", Decimal("1.0"))
        assert quote is not None
        assert quote.in_amount == Decimal("1.0")
        assert quote.out_amount > 0
    
    @pytest.mark.asyncio
    async def test_execute_swap(self, sniper):
        from core.solana_sniper import SwapQuote
        quote = SwapQuote("SOL", "TOKEN", Decimal("1"), Decimal("0.95"), Decimal("0.05"), Decimal("0.01"), ["SOL", "TOKEN"], Decimal("0.003"))
        result = await sniper.execute_swap(quote)
        assert result["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_snipe_new_pool(self, sniper):
        from core.solana_sniper import TokenPool, DEXPlatform
        pool = TokenPool("pool1", DEXPlatform.RAYDIUM, "TOKEN", "MEME", Decimal("50"), Decimal("1000000"), Decimal("0.00005"), Decimal("15000"), Decimal("50000"), datetime.now(), 150, 200)
        result = await sniper.snipe_new_pool(pool, Decimal("1.0"))
        assert "status" in result


class TestMemecoinSafety:
    @pytest.fixture
    def scanner(self):
        from core.memecoin_safety import MemecoinSafetyScanner
        return MemecoinSafetyScanner()
    
    @pytest.mark.asyncio
    async def test_analyze_token(self, scanner):
        safety = await scanner.analyze_token("TOKEN123")
        assert safety.overall >= 0
        assert safety.overall <= 100
    
    def test_is_safe_to_trade(self, scanner):
        from core.memecoin_safety import SafetyScore, RiskLevel
        safety = SafetyScore(75.0, 80.0, 70.0, 75.0, 70.0, 80.0, RiskLevel.LOW, [])
        assert scanner.is_safe_to_trade(safety) is True
    
    def test_calculate_risk_level(self, scanner):
        from core.memecoin_safety import RiskLevel
        assert scanner._calculate_risk_level(85.0, []) == RiskLevel.SAFE
        assert scanner._calculate_risk_level(10.0, ["warning"]) == RiskLevel.CRITICAL


class TestSpotPerpTrading:
    @pytest.fixture
    def trader(self):
        from core.spot_perp_trading import CCXTTrader
        return CCXTTrader(exchange_id="binance")
    
    @pytest.mark.asyncio
    async def test_get_ticker(self, trader):
        ticker = await trader.get_ticker("BTC/USDT")
        assert ticker is not None
        assert ticker.bid > 0
    
    @pytest.mark.asyncio
    async def test_place_order(self, trader):
        from core.spot_perp_trading import OrderSide, OrderType, MarketType
        result = await trader.place_order("BTC/USDT", OrderSide.BUY, OrderType.MARKET, Decimal("0.1"))
        assert result["status"] == "filled"
    
    @pytest.mark.asyncio
    async def test_get_positions(self, trader):
        positions = await trader.get_positions()
        assert isinstance(positions, list)


class TestCopyTrading:
    @pytest.fixture
    def engine(self):
        from core.copy_trading import CopyTradingEngine
        return CopyTradingEngine()
    
    @pytest.mark.asyncio
    async def test_mirror_trade(self, engine):
        result = await engine.mirror_trade("whale123", "SOL", "buy", Decimal("1000"), Decimal("100"))
        assert result["status"] == "executed"
        assert Decimal(result["size"]) < Decimal(result["whale_original"])


class TestSwarmSniper:
    @pytest.fixture
    def agent(self):
        from core.swarm_sniper import SwarmSniperAgent
        return SwarmSniperAgent()
    
    @pytest.mark.asyncio
    async def test_snipe_with_safety(self, agent):
        result = await agent.snipe_with_safety("TOKEN", "POOL", Decimal("1.0"))
        assert "status" in result

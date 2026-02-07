"""Tests for MERID US-Compliant Universal Router."""

import pytest
from decimal import Decimal


class TestUSComplianceConfig:
    """Tests for US compliance configuration."""
    
    def test_is_venue_allowed(self):
        from core.us_compliance_config import is_venue_allowed
        
        assert is_venue_allowed("alpaca") is True
        assert is_venue_allowed("binanceus") is True
        assert is_venue_allowed("merid_sim") is True
        assert is_venue_allowed("bybit") is False
        assert is_venue_allowed("binance") is False
    
    def test_is_venue_blocked(self):
        from core.us_compliance_config import is_venue_blocked
        
        assert is_venue_blocked("bybit") is True
        assert is_venue_blocked("binance") is True
        assert is_venue_blocked("alpaca") is False
    
    def test_get_venues_for_asset_class(self):
        from core.us_compliance_config import get_venues_for_asset_class
        
        equities = get_venues_for_asset_class("equities")
        assert "alpaca" in equities
        assert "ibkr" in equities
        
        crypto = get_venues_for_asset_class("crypto_spot")
        assert "binanceus" in crypto
        assert "alpaca" in crypto
        
        prediction = get_venues_for_asset_class("prediction")
        assert "kalshi" in prediction
    
    def test_validate_venue_selection(self):
        from core.us_compliance_config import validate_venue_selection
        
        assert validate_venue_selection("alpaca", "equities") is True
        assert validate_venue_selection("binanceus", "crypto_spot") is True
        assert validate_venue_selection("bybit", "crypto_spot") is False


class TestVenueAdapter:
    """Tests for base venue adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.merid_sim_adapter import MERIDSimulatorAdapter
        return MERIDSimulatorAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.is_connected() is True
    
    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        await adapter.connect()
        result = await adapter.disconnect()
        assert result is True
        assert adapter.is_connected() is False


class TestAlpacaAdapter:
    """Tests for Alpaca adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.alpaca_adapter import AlpacaAdapter
        return AlpacaAdapter(paper=True)
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.venue_id == "alpaca"
    
    @pytest.mark.asyncio
    async def test_place_order(self, adapter):
        from core.venue_adapter import OrderSide, OrderType
        
        await adapter.connect()
        result = await adapter.place_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("100")
        )
        
        assert result["status"] == "filled"
        assert result["venue"] == "alpaca"
    
    @pytest.mark.asyncio
    async def test_get_market_data(self, adapter):
        await adapter.connect()
        data = await adapter.get_market_data("AAPL")
        
        assert data is not None
        assert data.symbol == "AAPL"
        assert data.bid > 0


class TestIBKRAdapter:
    """Tests for IBKR adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.ibkr_adapter import IBKRAdapter
        return IBKRAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.venue_id == "ibkr"
    
    @pytest.mark.asyncio
    async def test_get_positions(self, adapter):
        await adapter.connect()
        positions = await adapter.get_positions()
        
        assert isinstance(positions, list)


class TestBinanceUSAdapter:
    """Tests for Binance.US adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.binanceus_adapter import BinanceUSAdapter
        return BinanceUSAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.endpoint == "https://api.binance.us"
    
    @pytest.mark.asyncio
    async def test_place_order(self, adapter):
        from core.venue_adapter import OrderSide, OrderType
        
        await adapter.connect()
        result = await adapter.place_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1")
        )
        
        assert result["status"] == "filled"
        assert result["venue"] == "binanceus"


class TestKalshiAdapter:
    """Tests for Kalshi adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.kalshi_adapter import KalshiAdapter
        return KalshiAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.endpoint == "https://trading-api.kalshi.com"
    
    @pytest.mark.asyncio
    async def test_get_markets(self, adapter):
        await adapter.connect()
        markets = await adapter.get_markets()
        
        assert len(markets) > 0
        assert "id" in markets[0]


class TestCoinbaseAdvancedAdapter:
    """Tests for Coinbase Advanced Trade adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.coinbase_advanced_adapter import CoinbaseAdvancedAdapter
        return CoinbaseAdvancedAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.endpoint == "https://api.coinbase.com"
        assert adapter.venue_id == "coinbase_advanced"
    
    @pytest.mark.asyncio
    async def test_place_order(self, adapter):
        from core.venue_adapter import OrderSide, OrderType
        
        await adapter.connect()
        result = await adapter.place_order(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1")
        )
        
        assert result["status"] == "filled"
        assert result["venue"] == "coinbase_advanced"
    
    @pytest.mark.asyncio
    async def test_get_market_data(self, adapter):
        await adapter.connect()
        data = await adapter.get_market_data("BTC/USD")
        
        assert data is not None
        assert data.symbol == "BTC/USD"
        assert data.bid > 0
        assert data.venue == "coinbase_advanced"
    
    @pytest.mark.asyncio
    async def test_get_balance(self, adapter):
        await adapter.connect()
        balance = await adapter.get_balance()
        
        assert "USD" in balance
        assert "BTC" in balance


class TestKrakenAdapter:
    """Tests for Kraken adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.kraken_adapter import KrakenAdapter
        return KrakenAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert adapter.endpoint == "https://api.kraken.com"
        assert adapter.venue_id == "kraken"
    
    @pytest.mark.asyncio
    async def test_place_order(self, adapter):
        from core.venue_adapter import OrderSide, OrderType
        
        await adapter.connect()
        result = await adapter.place_order(
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            amount=Decimal("0.05")
        )
        
        assert result["status"] == "filled"
        assert result["venue"] == "kraken"
    
    @pytest.mark.asyncio
    async def test_get_market_data(self, adapter):
        await adapter.connect()
        data = await adapter.get_market_data("ETH/USD")
        
        assert data is not None
        assert data.symbol == "ETH/USD"
        assert data.venue == "kraken"
    
    @pytest.mark.asyncio
    async def test_get_balance(self, adapter):
        await adapter.connect()
        balance = await adapter.get_balance()
        
        assert "USD" in balance
        assert "EUR" in balance  # Kraken supports EUR


class TestGeminiAdapter:
    """Tests for Gemini adapter."""
    
    @pytest.fixture
    def adapter(self):
        from core.venues.gemini_adapter import GeminiAdapter
        return GeminiAdapter()
    
    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        result = await adapter.connect()
        assert result is True
        assert "gemini.com" in adapter.endpoint
        assert adapter.venue_id == "gemini"
    
    @pytest.mark.asyncio
    async def test_connect_sandbox(self):
        from core.venues.gemini_adapter import GeminiAdapter
        sandbox_adapter = GeminiAdapter(sandbox=True)
        result = await sandbox_adapter.connect()
        assert result is True
        assert "sandbox" in sandbox_adapter.endpoint
    
    @pytest.mark.asyncio
    async def test_place_order(self, adapter):
        from core.venue_adapter import OrderSide, OrderType
        
        await adapter.connect()
        result = await adapter.place_order(
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1")
        )
        
        assert result["status"] == "filled"
        assert result["venue"] == "gemini"
    
    @pytest.mark.asyncio
    async def test_get_market_data(self, adapter):
        await adapter.connect()
        data = await adapter.get_market_data("BTC/USD")
        
        assert data is not None
        assert data.symbol == "BTC/USD"
        assert data.venue == "gemini"
    
    @pytest.mark.asyncio
    async def test_get_balance(self, adapter):
        await adapter.connect()
        balance = await adapter.get_balance()
        
        assert "USD" in balance
        assert "BTC" in balance


class TestUniversalRouter:
    """Tests for universal router."""
    
    @pytest.fixture
    def router(self):
        from core.universal_router import UniversalRouter
        return UniversalRouter()
    
    def test_validate_venue_allowed(self, router):
        assert router.validate_venue("alpaca") is True
        assert router.validate_venue("merid_sim") is True
    
    def test_validate_venue_blocked(self, router):
        from core.universal_router import UniversalRouter
        
        router = UniversalRouter()
        
        with pytest.raises(ValueError, match="blocked"):
            router.validate_venue("bybit")
        
        with pytest.raises(ValueError, match="blocked"):
            router.validate_venue("binance")
    
    def test_route_by_asset_class(self, router):
        from core.universal_router import AssetClass
        
        venue = router.route_by_asset_class(AssetClass.EQUITIES, paper=True)
        assert venue in ["alpaca", "ibkr", "merid_sim"]
        
        crypto_venue = router.route_by_asset_class(AssetClass.CRYPTO_SPOT, paper=False)
        assert crypto_venue in ["alpaca", "binanceus", "coinbase"]
        
        prediction_venue = router.route_by_asset_class(AssetClass.PREDICTION)
        assert prediction_venue == "kalshi"
    
    @pytest.mark.asyncio
    async def test_execute_trade(self, router):
        from core.universal_router import UniversalTrade, AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        trade = UniversalTrade(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("100"),
            price=None,
            venue="merid_sim",
            asset_class=AssetClass.EQUITIES,
            paper=True
        )
        
        result = await router.execute(trade)
        
        assert result["status"] == "filled"
        assert result["routed_through"] == "merid_sim"
    
    @pytest.mark.asyncio
    async def test_execute_auto(self, router):
        from core.universal_router import AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        result = await router.execute_auto(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1"),
            asset_class=AssetClass.CRYPTO_SPOT,
            paper=True
        )
        
        assert result["status"] == "filled"
        assert "routed_through" in result
    
    @pytest.mark.asyncio
    async def test_get_best_price(self, router):
        from core.universal_router import AssetClass
        from core.venue_adapter import OrderSide
        
        result = await router.get_best_price(
            symbol="BTC",
            asset_class=AssetClass.CRYPTO_SPOT,
            side=OrderSide.BUY
        )
        
        assert "best_venue" in result
        assert "best_price" in result
    
    def test_list_allowed_venues(self, router):
        venues = router.list_allowed_venues()
        
        assert "alpaca" in venues
        assert "binanceus" in venues
        assert "kalshi" in venues
        assert "merid_sim" in venues
        assert "bybit" not in venues
    
    def test_list_blocked_venues(self, router):
        venues = router.list_blocked_venues()
        
        assert "bybit" in venues
        assert "binance" in venues
        assert "alpaca" not in venues


class TestUSComplianceIntegration:
    """Integration tests for US compliance."""
    
    @pytest.mark.asyncio
    async def test_full_trade_flow_equities(self):
        from core.universal_router import universal_router, AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        result = await universal_router.execute_auto(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("100"),
            asset_class=AssetClass.EQUITIES,
            paper=True
        )
        
        assert result["status"] == "filled"
        assert result["paper"] is True
    
    @pytest.mark.asyncio
    async def test_full_trade_flow_crypto(self):
        from core.universal_router import universal_router, AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        result = await universal_router.execute_auto(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1"),
            asset_class=AssetClass.CRYPTO_SPOT,
            paper=True
        )
        
        assert result["status"] == "filled"
        # Should route to binanceus or alpaca for crypto
        assert result["routed_through"] in ["binanceus", "alpaca", "merid_sim"]
    
    @pytest.mark.asyncio
    async def test_full_trade_flow_prediction(self):
        from core.universal_router import universal_router, AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        result = await universal_router.execute_auto(
            symbol="KXBT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            amount=Decimal("10"),
            price=Decimal("0.55"),
            asset_class=AssetClass.PREDICTION,
            paper=True
        )
        
        assert result["status"] == "filled"
        assert result["routed_through"] == "kalshi"
    
    def test_blocked_venue_raises_error(self):
        from core.universal_router import UniversalRouter, UniversalTrade, AssetClass
        from core.venue_adapter import OrderSide, OrderType
        
        router = UniversalRouter()
        
        with pytest.raises(ValueError, match="blocked"):
            trade = UniversalTrade(
                symbol="BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                amount=Decimal("1"),
                price=None,
                venue="bybit",
                asset_class=AssetClass.CRYPTO_SPOT
            )
            # This should raise when trying to validate
            router.validate_venue("bybit")

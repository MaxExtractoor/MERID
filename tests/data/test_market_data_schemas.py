"""Tests for data/market_data_schemas.py."""
import pytest
from datetime import datetime
from decimal import Decimal
from data.market_data_schemas import (
    DataType, Side, LiquidityFlag, TradeCondition, BarResolution,
    TickTradeData, BarOHLCVData, OrderBookLevel, OrderBookData,
    PredictionMarketData, DeFiStateData, RWAStateData, UnifiedMarketData,
    MarketDataSchemaValidator, get_schema_validator
)


class TestDataTypeEnum:
    """Test DataType enum."""

    def test_data_type_values(self):
        """Test data type enum values."""
        assert DataType.TICK.value == "tick"
        assert DataType.TRADE.value == "trade"
        assert DataType.BAR.value == "bar"
        assert DataType.OHLCV.value == "ohlcv"
        assert DataType.ORDER_BOOK_SNAPSHOT.value == "order_book_snapshot"
        assert DataType.PREDICTION_MARKET.value == "prediction_market"


class TestSideEnum:
    """Test Side enum."""

    def test_side_values(self):
        """Test side enum values."""
        assert Side.BUY.value == "buy"
        assert Side.SELL.value == "sell"
        assert Side.UNKNOWN.value == "unknown"


class TestLiquidityFlagEnum:
    """Test LiquidityFlag enum."""

    def test_liquidity_flag_values(self):
        """Test liquidity flag enum values."""
        assert LiquidityFlag.TAKER.value == "taker"
        assert LiquidityFlag.MAKER.value == "maker"
        assert LiquidityFlag.UNKNOWN.value == "unknown"


class TestTradeConditionEnum:
    """Test TradeCondition enum."""

    def test_trade_condition_values(self):
        """Test trade condition enum values."""
        assert TradeCondition.REGULAR.value == "regular"
        assert TradeCondition.AUCTION.value == "auction"
        assert TradeCondition.DARK.value == "dark"


class TestBarResolutionEnum:
    """Test BarResolution enum."""

    def test_bar_resolution_values(self):
        """Test bar resolution enum values."""
        assert BarResolution.TICK.value == "tick"
        assert BarResolution.MINUTE_1.value == "1m"
        assert BarResolution.HOUR_1.value == "1h"
        assert BarResolution.DAY_1.value == "1d"


class TestTickTradeData:
    """Test TickTradeData dataclass."""

    def test_default_creation(self):
        """Test TickTradeData with default values."""
        tick = TickTradeData()
        assert tick.instrument_id == ""
        assert tick.symbol == ""
        assert tick.side == Side.UNKNOWN
        assert tick.liquidity_flag == LiquidityFlag.UNKNOWN
        assert tick.data_version == "1.0"

    def test_custom_creation(self):
        """Test TickTradeData with custom values."""
        now = datetime.utcnow()
        tick = TickTradeData(
            instrument_id="BTC-USD",
            symbol="BTC/USD",
            price=Decimal("50000.00"),
            size=Decimal("1.5"),
            side=Side.BUY,
            exchange_timestamp=now
        )
        assert tick.instrument_id == "BTC-USD"
        assert tick.symbol == "BTC/USD"
        assert tick.price == Decimal("50000.00")
        assert tick.side == Side.BUY


class TestBarOHLCVData:
    """Test BarOHLCVData dataclass."""

    def test_default_creation(self):
        """Test BarOHLCVData with default values."""
        bar = BarOHLCVData()
        assert bar.instrument_id == ""
        assert bar.bar_resolution == BarResolution.MINUTE_1
        assert bar.data_version == "1.0"

    def test_custom_creation(self):
        """Test BarOHLCVData with custom values."""
        bar = BarOHLCVData(
            symbol="ETH/USD",
            open=Decimal("3000.00"),
            high=Decimal("3100.00"),
            low=Decimal("2950.00"),
            close=Decimal("3050.00"),
            volume=Decimal("10000.00"),
            bar_resolution=BarResolution.HOUR_1
        )
        assert bar.symbol == "ETH/USD"
        assert bar.high == Decimal("3100.00")
        assert bar.bar_resolution == BarResolution.HOUR_1


class TestOrderBookLevel:
    """Test OrderBookLevel dataclass."""

    def test_creation(self):
        """Test OrderBookLevel creation."""
        level = OrderBookLevel(
            side=Side.BUY,
            price=Decimal("50000.00"),
            size=Decimal("1.5"),
            level_index=0
        )
        assert level.side == Side.BUY
        assert level.price == Decimal("50000.00")
        assert level.level_index == 0


class TestOrderBookData:
    """Test OrderBookData dataclass."""

    def test_default_creation(self):
        """Test OrderBookData with default values."""
        now = datetime.utcnow()
        ob = OrderBookData(
            instrument_id="BTC-USD",
            symbol="BTC/USD",
            venue_symbol="BTCUSD",
            asset_class="crypto",
            venue_id="kraken",
            timestamp=now
        )
        assert ob.instrument_id == "BTC-USD"
        assert ob.bids == []
        assert ob.asks == []
        assert ob.is_snapshot is True

    def test_with_levels(self):
        """Test OrderBookData with price levels."""
        now = datetime.utcnow()
        bids = [
            OrderBookLevel(Side.BUY, Decimal("50000.00"), Decimal("1.0"), 0),
            OrderBookLevel(Side.BUY, Decimal("49990.00"), Decimal("2.0"), 1),
        ]
        asks = [
            OrderBookLevel(Side.SELL, Decimal("50010.00"), Decimal("1.5"), 0),
        ]
        ob = OrderBookData(
            instrument_id="BTC-USD",
            symbol="BTC/USD",
            venue_symbol="BTCUSD",
            asset_class="crypto",
            venue_id="kraken",
            timestamp=now,
            bids=bids,
            asks=asks
        )
        assert len(ob.bids) == 2
        assert len(ob.asks) == 1


class TestPredictionMarketData:
    """Test PredictionMarketData dataclass."""

    def test_default_creation(self):
        """Test PredictionMarketData with default values."""
        pm = PredictionMarketData()
        assert pm.market_id == ""
        assert pm.outcomes == []
        assert pm.status == ""
        assert pm.data_version == "1.0"

    def test_custom_creation(self):
        """Test PredictionMarketData with custom values."""
        pm = PredictionMarketData(
            market_id="market_123",
            platform_id="polymarket",
            question="Will BTC hit 100k?",
            outcomes=["Yes", "No"],
            status="open"
        )
        assert pm.market_id == "market_123"
        assert pm.platform_id == "polymarket"
        assert pm.outcomes == ["Yes", "No"]


class TestDeFiStateData:
    """Test DeFiStateData dataclass."""

    def test_default_creation(self):
        """Test DeFiStateData with default values."""
        defi = DeFiStateData()
        assert defi.protocol_id == ""
        assert defi.chain_id == 0
        assert defi.block_number == 0

    def test_amm_state(self):
        """Test DeFiStateData with AMM state."""
        defi = DeFiStateData(
            protocol_id="uniswap_v3",
            protocol_name="Uniswap V3",
            protocol_type="AMM",
            chain_id=1,
            pool_price=Decimal("3000.00"),
            pool_liquidity=Decimal("1000000.00")
        )
        assert defi.protocol_type == "AMM"
        assert defi.pool_price == Decimal("3000.00")


class TestRWAStateData:
    """Test RWAStateData dataclass."""

    def test_default_creation(self):
        """Test RWAStateData with default values."""
        rwa = RWAStateData()
        assert rwa.asset_id == ""
        assert rwa.kyc_required is True
        assert rwa.accredited_only is False

    def test_treasury_creation(self):
        """Test RWAStateData for treasury asset."""
        rwa = RWAStateData(
            asset_id="t_bill_001",
            asset_name="US Treasury Bill",
            asset_type="treasury",
            underlying_asset="US Treasury",
            nav_per_token=Decimal("100.00")
        )
        assert rwa.asset_type == "treasury"
        assert rwa.nav_per_token == Decimal("100.00")


class TestUnifiedMarketData:
    """Test UnifiedMarketData dataclass."""

    def test_default_creation(self):
        """Test UnifiedMarketData with default values."""
        data = UnifiedMarketData()
        assert data.data_type == DataType.TICK
        assert data.environment == "live"
        assert data.tick_data is None

    def test_with_tick_data(self):
        """Test UnifiedMarketData with tick data."""
        tick = TickTradeData(symbol="BTC/USD")
        data = UnifiedMarketData(
            data_type=DataType.TICK,
            tick_data=tick
        )
        assert data.data_type == DataType.TICK
        assert data.tick_data.symbol == "BTC/USD"


class TestMarketDataSchemaValidator:
    """Test MarketDataSchemaValidator class."""

    def test_validate_tick_trade_valid(self):
        """Test valid tick trade validation."""
        now = datetime.utcnow()
        data = {
            "instrument_id": "BTC-USD",
            "symbol": "BTC/USD",
            "venue_symbol": "BTCUSD",
            "asset_class": "crypto",
            "venue_id": "kraken",
            "exchange_timestamp": now,
            "receive_timestamp": now,
            "processing_timestamp": now,
            "price": Decimal("50000.00"),
            "size": Decimal("1.5"),
            "side": Side.BUY,
            "trade_id": "trade_123",
        }
        
        valid, errors = MarketDataSchemaValidator.validate_tick_trade(data)
        assert valid is True
        assert errors == []

    def test_validate_tick_trade_missing_fields(self):
        """Test tick trade validation with missing fields."""
        data = {"symbol": "BTC/USD"}  # Missing most fields
        
        valid, errors = MarketDataSchemaValidator.validate_tick_trade(data)
        assert valid is False
        assert len(errors) > 0
        assert any("Missing" in e for e in errors)

    def test_validate_bar_ohlcv_valid(self):
        """Test valid bar OHLCV validation."""
        now = datetime.utcnow()
        data = {
            "instrument_id": "BTC-USD",
            "symbol": "BTC/USD",
            "venue_symbol": "BTCUSD",
            "asset_class": "crypto",
            "venue_id": "kraken",
            "bar_start_time": now,
            "bar_end_time": now,
            "bar_resolution": BarResolution.MINUTE_1,
            "open": Decimal("50000.00"),
            "high": Decimal("51000.00"),
            "low": Decimal("49000.00"),
            "close": Decimal("50500.00"),
            "volume": Decimal("100.00"),
        }
        
        valid, errors = MarketDataSchemaValidator.validate_bar_ohlcv(data)
        assert valid is True

    def test_validate_bar_ohlcv_inconsistent_ohlc(self):
        """Test bar validation with inconsistent OHLC values."""
        data = {
            "instrument_id": "BTC-USD",
            "symbol": "BTC/USD",
            "venue_symbol": "BTCUSD",
            "asset_class": "crypto",
            "venue_id": "kraken",
            "bar_start_time": datetime.utcnow(),
            "bar_end_time": datetime.utcnow(),
            "bar_resolution": BarResolution.MINUTE_1,
            "open": Decimal("50000.00"),
            "high": Decimal("48000.00"),  # High < Open - inconsistent
            "low": Decimal("49000.00"),
            "close": Decimal("50500.00"),
            "volume": Decimal("100.00"),
        }
        
        valid, errors = MarketDataSchemaValidator.validate_bar_ohlcv(data)
        assert valid is False
        assert any("inconsistent" in e.lower() for e in errors)

    def test_validate_order_book_valid(self):
        """Test valid order book validation."""
        now = datetime.utcnow()
        data = {
            "instrument_id": "BTC-USD",
            "symbol": "BTC/USD",
            "venue_symbol": "BTCUSD",
            "asset_class": "crypto",
            "venue_id": "kraken",
            "timestamp": now,
            "is_snapshot": True,
            "bids": [{"price": Decimal("50000.00"), "size": Decimal("1.0")}],
            "asks": [{"price": Decimal("50010.00"), "size": Decimal("1.5")}],
        }
        
        valid, errors = MarketDataSchemaValidator.validate_order_book(data)
        assert valid is True

    def test_validate_prediction_market_valid(self):
        """Test valid prediction market validation."""
        now = datetime.utcnow()
        data = {
            "market_id": "market_123",
            "platform_id": "polymarket",
            "question": "Will BTC hit 100k?",
            "outcomes": ["Yes", "No"],
            "resolution_criteria": "By end of 2024",
            "market_type": "binary",
            "created_at": now,
            "status": "open",
            "outcome_prices": {"Yes": Decimal("0.6"), "No": Decimal("0.4")},
        }
        
        valid, errors = MarketDataSchemaValidator.validate_prediction_market(data)
        assert valid is True

    def test_validate_prediction_market_invalid_probabilities(self):
        """Test prediction market validation with invalid probabilities."""
        data = {
            "market_id": "market_123",
            "platform_id": "polymarket",
            "question": "Will BTC hit 100k?",
            "outcomes": ["Yes", "No"],
            "resolution_criteria": "By end of 2024",
            "market_type": "binary",
            "created_at": datetime.utcnow(),
            "status": "open",
            "outcome_prices": {"Yes": Decimal("0.6"), "No": Decimal("0.5")},
            "implied_probabilities": {"Yes": Decimal("0.7"), "No": Decimal("0.4")},  # Sum = 1.1
        }
        
        valid, errors = MarketDataSchemaValidator.validate_prediction_market(data)
        assert valid is False
        assert any("sum" in e.lower() for e in errors)


class TestGetSchemaValidator:
    """Test get_schema_validator function."""

    def test_returns_validator(self):
        """Test get_schema_validator returns validator instance."""
        validator = get_schema_validator()
        assert isinstance(validator, MarketDataSchemaValidator)

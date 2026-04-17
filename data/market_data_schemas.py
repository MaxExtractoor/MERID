"""
Essential market data schemas for all asset classes.

Defines mandatory fields for reliable backtesting across crypto, memecoins,
xStocks, futures, perps, forex, DeFi, TradFi, RWAs, and prediction markets.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class DataType(Enum):
    """Type of market data."""
    TICK = "tick"
    TRADE = "trade"
    BAR = "bar"
    OHLCV = "ohlcv"
    ORDER_BOOK_SNAPSHOT = "order_book_snapshot"
    ORDER_BOOK_DELTA = "order_book_delta"
    QUOTE = "quote"
    PREDICTION_MARKET = "prediction_market"
    DEFI_STATE = "defi_state"
    RWA_STATE = "rwa_state"
    LOCAL_SIM_TICK = "local_sim_tick"
    LOCAL_SIM_TRADE = "local_sim_trade"
    LOCAL_SIM_ORDER_BOOK = "local_sim_order_book"
    MULTICAST_ITCH = "multicast_itch"
    MULTICAST_SOUPBIN = "multicast_soupbin"
    FIX_SNAPSHOT = "fix_snapshot"
    FIX_INCREMENTAL = "fix_incremental"


class Side(Enum):
    """Trade side."""
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class LiquidityFlag(Enum):
    """Liquidity flag."""
    TAKER = "taker"
    MAKER = "maker"
    UNKNOWN = "unknown"


class TradeCondition(Enum):
    """Trade condition for equities/futures."""
    REGULAR = "regular"
    AUCTION = "auction"
    DARK = "dark"
    OFF_BOOK = "off_book"
    CROSS = "cross"
    UNKNOWN = "unknown"


class BarResolution(Enum):
    """Bar resolution."""
    TICK = "tick"
    SECOND_1 = "1s"
    SECOND_5 = "5s"
    SECOND_15 = "15s"
    SECOND_30 = "30s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"


@dataclass
class TickTradeData:
    """
    Core tick/trade data fields (all assets).
    
    Essential for reliable backtesting across all asset classes.
    """
    # Identification
    instrument_id: str = field(default="")
    symbol: str = field(default="")
    venue_symbol: str = field(default="")
    asset_class: str = field(default="")
    venue_id: str = field(default="")
    
    # Timestamps (all in UTC)
    exchange_timestamp: Optional[datetime] = None
    receive_timestamp: Optional[datetime] = None
    processing_timestamp: Optional[datetime] = None
    timezone: str = "UTC"
    
    # Trade data
    price: Optional[Decimal] = None
    size: Optional[Decimal] = None
    side: Side = Side.UNKNOWN
    trade_id: str = field(default="")
    liquidity_flag: LiquidityFlag = LiquidityFlag.UNKNOWN
    
    # Sequencing
    sequence_number: Optional[int] = None
    
    # Metadata
    source_feed_type: str = "websocket"  # REST/WebSocket/FIX/ITCH
    environment: str = "live"  # live/sim/backtest
    
    # Optional for equities/futures
    trade_condition: Optional[TradeCondition] = None
    
    # Data quality
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class BarOHLCVData:
    """
    Bar/OHLCV data fields (all assets).
    
    Essential for bar-based backtesting and analysis.
    """
    # Identification
    instrument_id: str = field(default="")
    symbol: str = field(default="")
    venue_symbol: str = field(default="")
    asset_class: str = field(default="")
    venue_id: str = field(default="")
    
    # Bar timing
    bar_start_time: Optional[datetime] = None
    bar_end_time: Optional[datetime] = None
    bar_resolution: BarResolution = BarResolution.MINUTE_1
    timezone: str = "UTC"
    
    # OHLCV
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    
    # Derived
    vwap: Optional[Decimal] = None
    trade_count: Optional[int] = None
    
    # Corporate actions (equities/ETFs)
    split_factor: Optional[Decimal] = None
    dividend_amount: Optional[Decimal] = None
    corporate_action_flags: List[str] = field(default_factory=list)
    
    # Metadata
    source_feed_type: str = "REST"
    environment: str = "live"
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class OrderBookLevel:
    """Single order book level."""
    side: Side  # bid/ask
    price: Decimal
    size: Decimal
    level_index: int  # 0 = best bid/ask


@dataclass
class OrderBookData:
    """
    Order book snapshot/delta data.
    
    Essential for microstructure analysis and HFT strategies.
    """
    # Identification
    instrument_id: str
    symbol: str
    venue_symbol: str
    asset_class: str
    venue_id: str
    
    # Timing
    timestamp: datetime
    exchange_timestamp: Optional[datetime] = None
    timezone: str = "UTC"
    
    # Sequencing
    sequence_number: Optional[int] = None
    
    # Snapshot or delta
    is_snapshot: bool = True
    
    # Levels
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    
    # Derived (computed from levels)
    spread: Optional[Decimal] = None
    mid_price: Optional[Decimal] = None
    imbalance: Optional[Decimal] = None
    depth_bids: Optional[Decimal] = None
    depth_asks: Optional[Decimal] = None
    
    # Metadata
    source_feed_type: str = "websocket"
    environment: str = "live"
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class PredictionMarketData:
    """
    Prediction market data.
    
    Essential for prediction market trading and analysis.
    """
    # Market identification
    market_id: str = field(default="")
    platform_id: str = field(default="")
    
    # Market definition
    question: str = field(default="")
    outcomes: List[str] = field(default_factory=list)
    resolution_criteria: str = field(default="")
    market_type: str = field(default="")  # binary, categorical, scalar
    
    # Timing
    created_at: Optional[datetime] = None
    close_time: Optional[datetime] = None
    resolution_time: Optional[datetime] = None
    
    # Market state
    status: str = field(default="")  # open, closed, resolved, disputed
    resolved_outcome: Optional[str] = None
    
    # Pricing per outcome
    outcome_prices: Dict[str, Decimal] = field(default_factory=dict)
    implied_probabilities: Dict[str, Decimal] = field(default_factory=dict)
    
    # Liquidity per outcome
    outcome_liquidity: Dict[str, Decimal] = field(default_factory=dict)
    
    # Order book per outcome (if available)
    outcome_order_books: Dict[str, OrderBookData] = field(default_factory=dict)
    
    # Fees
    maker_fee: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0")
    
    # Volume
    total_volume: Decimal = Decimal("0")
    volume_by_outcome: Dict[str, Decimal] = field(default_factory=dict)
    
    # Metadata
    timestamp: Optional[datetime] = None
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class DeFiStateData:
    """
    DeFi protocol state data.
    
    Essential for DeFi strategy backtesting and analysis.
    """
    # Protocol identification
    protocol_id: str = field(default="")
    protocol_name: str = field(default="")
    protocol_type: str = field(default="")  # AMM, lending, perp, derivative
    
    # Chain
    chain_id: int = 0
    chain_name: str = field(default="")
    
    # Block context
    block_number: int = 0
    block_timestamp: Optional[datetime] = None
    transaction_hash: Optional[str] = None
    
    # AMM state (if applicable)
    pool_address: Optional[str] = None
    token0_address: Optional[str] = None
    token1_address: Optional[str] = None
    token0_reserve: Optional[Decimal] = None
    token1_reserve: Optional[Decimal] = None
    pool_price: Optional[Decimal] = None
    pool_liquidity: Optional[Decimal] = None
    pool_fee: Optional[Decimal] = None
    
    # Lending state (if applicable)
    asset_address: Optional[str] = None
    total_supply: Optional[Decimal] = None
    total_borrow: Optional[Decimal] = None
    supply_rate: Optional[Decimal] = None
    borrow_rate: Optional[Decimal] = None
    utilization_rate: Optional[Decimal] = None
    ltv: Optional[Decimal] = None
    liquidation_threshold: Optional[Decimal] = None
    
    # Perp state (if applicable)
    perp_market: Optional[str] = None
    index_price: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    funding_rate: Optional[Decimal] = None
    open_interest: Optional[Decimal] = None
    
    # TVL
    tvl_usd: Optional[Decimal] = None
    
    # Oracle data
    oracle_price: Optional[Decimal] = None
    oracle_timestamp: Optional[datetime] = None
    
    # Metadata
    parser_version: str = "1.0"
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class RWAStateData:
    """
    Real-world asset (RWA) state data.
    
    Essential for RWA strategy backtesting and analysis.
    """
    # Asset identification
    asset_id: str = field(default="")
    asset_name: str = field(default="")
    asset_type: str = field(default="")  # treasury, credit, real_estate
    
    # Token
    token_address: str = field(default="")
    chain_id: int = 0
    chain_name: str = field(default="")
    
    # Block context
    block_number: int = 0
    block_timestamp: Optional[datetime] = None
    
    # Asset backing
    underlying_asset: str = field(default="")  # e.g., "US Treasury", "Corporate Bond"
    backing_value_usd: Decimal = Decimal("0")
    token_supply: Decimal = Decimal("0")
    nav_per_token: Decimal = Decimal("0")
    
    # Yield/returns
    apy: Optional[Decimal] = None
    yield_accrued: Optional[Decimal] = None
    last_distribution: Optional[datetime] = None
    
    # Treasury-specific
    treasury_maturity: Optional[datetime] = None
    treasury_coupon: Optional[Decimal] = None
    
    # Credit-specific
    credit_rating: Optional[str] = None
    default_probability: Optional[Decimal] = None
    
    # Real estate-specific
    property_address: Optional[str] = None
    property_value: Optional[Decimal] = None
    rental_yield: Optional[Decimal] = None
    
    # Compliance
    kyc_required: bool = True
    accredited_only: bool = False
    jurisdiction_restrictions: List[str] = field(default_factory=list)
    
    # Metadata
    data_source: str = "on_chain"
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class UnifiedMarketData:
    """
    Unified market data container for multi-asset backtests.
    
    Long format with consistent schema across all asset classes.
    """
    # Universal fields
    timestamp: Optional[datetime] = None
    instrument_id: str = field(default="")
    symbol: str = field(default="")
    asset_class: str = field(default="")
    venue_id: str = field(default="")
    data_type: DataType = DataType.TICK
    
    # Type-specific data (only one populated)
    tick_data: Optional[TickTradeData] = None
    bar_data: Optional[BarOHLCVData] = None
    order_book_data: Optional[OrderBookData] = None
    prediction_market_data: Optional[PredictionMarketData] = None
    defi_state_data: Optional[DeFiStateData] = None
    rwa_state_data: Optional[RWAStateData] = None
    
    # Metadata
    environment: str = "live"
    data_version: str = "1.0"
    quality_flags: List[str] = field(default_factory=list)


class MarketDataSchemaValidator:
    """
    Validates market data against essential schemas.
    
    Ensures all mandatory fields are present for reliable backtesting.
    """
    
    @staticmethod
    def validate_tick_trade(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate tick/trade data."""
        required_fields = [
            "instrument_id", "symbol", "venue_symbol", "asset_class", "venue_id",
            "exchange_timestamp", "receive_timestamp", "processing_timestamp",
            "price", "size", "side", "trade_id",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        return True, []
    
    @staticmethod
    def validate_bar_ohlcv(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate bar/OHLCV data."""
        required_fields = [
            "instrument_id", "symbol", "venue_symbol", "asset_class", "venue_id",
            "bar_start_time", "bar_end_time", "bar_resolution",
            "open", "high", "low", "close", "volume",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        # Validate OHLC consistency
        errors = []
        if "open" in data and "high" in data and "low" in data and "close" in data:
            o, h, l, c = data["open"], data["high"], data["low"], data["close"]
            if h < max(o, c) or l > min(o, c):
                errors.append("OHLC values inconsistent (high < max(O,C) or low > min(O,C))")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_order_book(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate order book data."""
        required_fields = [
            "instrument_id", "symbol", "venue_symbol", "asset_class", "venue_id",
            "timestamp", "is_snapshot", "bids", "asks",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        # Validate bid/ask ordering
        errors = []
        if "bids" in data and len(data["bids"]) > 1:
            for i in range(len(data["bids"]) - 1):
                if data["bids"][i]["price"] <= data["bids"][i + 1]["price"]:
                    errors.append("Bids not in descending price order")
                    break
        
        if "asks" in data and len(data["asks"]) > 1:
            for i in range(len(data["asks"]) - 1):
                if data["asks"][i]["price"] >= data["asks"][i + 1]["price"]:
                    errors.append("Asks not in ascending price order")
                    break
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_prediction_market(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate prediction market data."""
        required_fields = [
            "market_id", "platform_id", "question", "outcomes",
            "resolution_criteria", "market_type", "created_at",
            "status", "outcome_prices",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        # Validate probabilities sum to ~1
        errors = []
        if "implied_probabilities" in data and data["implied_probabilities"]:
            total_prob = sum(data["implied_probabilities"].values())
            if abs(total_prob - 1.0) > 0.01:
                errors.append(f"Implied probabilities sum to {total_prob}, not 1.0")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_defi_state(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate DeFi state data."""
        required_fields = [
            "protocol_id", "protocol_name", "protocol_type",
            "chain_id", "chain_name", "block_number", "block_timestamp",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        return True, []
    
    @staticmethod
    def validate_rwa_state(data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate RWA state data."""
        required_fields = [
            "asset_id", "asset_name", "asset_type", "token_address",
            "chain_id", "chain_name", "block_number", "block_timestamp",
            "underlying_asset", "backing_value_usd", "token_supply", "nav_per_token",
        ]
        
        missing = [f for f in required_fields if f not in data or data[f] is None]
        
        if missing:
            return False, [f"Missing required field: {f}" for f in missing]
        
        return True, []


def get_schema_validator() -> MarketDataSchemaValidator:
    """Get schema validator instance."""
    return MarketDataSchemaValidator()

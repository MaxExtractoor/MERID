"""
Geo-aware venue selection system with jurisdiction constraints.

Handles venue selection across all asset classes (crypto, memecoins, xStocks,
futures, perps, forex, DeFi, TradFi, RWAs, prediction markets) with respect
to geographic and regulatory restrictions.
"""

import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AssetClass(Enum):
    """Asset class types."""
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    CRYPTO_FUTURE = "crypto_future"
    MEMECOIN = "memecoin"
    XSTOCK = "xstock"  # Tokenized equities
    EQUITY_SPOT = "equity_spot"
    ETF = "etf"
    FUTURE = "future"
    OPTION = "option"
    FOREX = "forex"
    DEFI_AMM = "defi_amm"
    DEFI_LENDING = "defi_lending"
    DEFI_PERP = "defi_perp"
    DEFI_DERIVATIVE = "defi_derivative"
    RWA_TREASURY = "rwa_treasury"
    RWA_CREDIT = "rwa_credit"
    RWA_REAL_ESTATE = "rwa_real_estate"
    PREDICTION_MARKET = "prediction_market"


class VenueType(Enum):
    """Venue type."""
    CEX = "cex"  # Centralized exchange
    DEX = "dex"  # Decentralized exchange
    BROKER = "broker"
    DATA_VENDOR = "data_vendor"
    DEFI_PROTOCOL = "defi_protocol"
    PREDICTION_PLATFORM = "prediction_platform"
    LOCAL_SIM = "local_sim"  # Local simulation venue


class Jurisdiction(Enum):
    """Jurisdiction codes."""
    US = "US"
    EU = "EU"
    UK = "UK"
    JAPAN = "JP"
    SINGAPORE = "SG"
    HONG_KONG = "HK"
    GLOBAL = "GLOBAL"


@dataclass
class VenueDefinition:
    """Venue definition with geo restrictions."""
    venue_id: str
    name: str
    venue_type: VenueType
    asset_classes: Set[AssetClass]
    
    # Geographic restrictions
    allowed_jurisdictions: Set[Jurisdiction]
    blocked_jurisdictions: Set[Jurisdiction]
    
    # Capabilities
    supports_rest_api: bool
    supports_websocket: bool
    supports_fix: bool
    supports_historical: bool
    
    # Data quality
    has_tick_data: bool
    has_order_book: bool
    has_ohlcv: bool
    
    # Cost
    is_free: bool
    requires_kyc: bool
    
    # Metadata
    website: str
    api_docs: str
    notes: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class VenueRestriction:
    """Specific venue restriction."""
    restriction_id: str
    venue_id: str
    jurisdiction: Jurisdiction
    asset_class: Optional[AssetClass]
    
    restriction_type: str  # blocked, limited, requires_license
    reason: str
    effective_date: datetime
    
    reference_url: Optional[str] = None


class GeoAwareVenueSystem:
    """
    Geo-aware venue selection system.
    
    Manages venue selection across all asset classes with respect to
    geographic and regulatory restrictions. Ensures compliance with
    jurisdiction-specific rules (e.g., no Binance.com for US users).
    """
    
    def __init__(self):
        self._venues: Dict[str, VenueDefinition] = {}
        self._restrictions: List[VenueRestriction] = []
        
        self._initialize_venues()
        self._initialize_restrictions()
    
    def _initialize_venues(self) -> None:
        """Initialize venue definitions."""
        
        # === CRYPTO CEXs (US-COMPLIANT) ===
        
        self.register_venue(
            venue_id="kraken",
            name="Kraken",
            venue_type=VenueType.CEX,
            asset_classes={
                AssetClass.CRYPTO_SPOT,
                AssetClass.CRYPTO_PERP,
                AssetClass.CRYPTO_FUTURE,
            },
            allowed_jurisdictions={Jurisdiction.US, Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.kraken.com",
            api_docs="https://docs.kraken.com/rest/",
            notes="US-compliant, excellent free data access",
        )
        
        self.register_venue(
            venue_id="coinbase",
            name="Coinbase",
            venue_type=VenueType.CEX,
            asset_classes={AssetClass.CRYPTO_SPOT},
            allowed_jurisdictions={Jurisdiction.US, Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=True,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.coinbase.com",
            api_docs="https://docs.cloud.coinbase.com/",
            notes="US-compliant, institutional-grade",
        )
        
        self.register_venue(
            venue_id="gemini",
            name="Gemini",
            venue_type=VenueType.CEX,
            asset_classes={AssetClass.CRYPTO_SPOT},
            allowed_jurisdictions={Jurisdiction.US, Jurisdiction.UK, Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=True,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.gemini.com",
            api_docs="https://docs.gemini.com/",
            notes="US-compliant, regulated",
        )
        
        # === CRYPTO CEXs (NON-US) ===
        
        self.register_venue(
            venue_id="binance_global",
            name="Binance (Global)",
            venue_type=VenueType.CEX,
            asset_classes={
                AssetClass.CRYPTO_SPOT,
                AssetClass.CRYPTO_PERP,
                AssetClass.CRYPTO_FUTURE,
                AssetClass.MEMECOIN,
            },
            allowed_jurisdictions={Jurisdiction.EU, Jurisdiction.GLOBAL},
            blocked_jurisdictions={Jurisdiction.US},
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.binance.com",
            api_docs="https://binance-docs.github.io/apidocs/",
            notes="BLOCKED FOR US USERS - use Binance.US instead",
        )
        
        self.register_venue(
            venue_id="binance_us",
            name="Binance.US",
            venue_type=VenueType.CEX,
            asset_classes={AssetClass.CRYPTO_SPOT},
            allowed_jurisdictions={Jurisdiction.US},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.binance.us",
            api_docs="https://docs.binance.us/",
            notes="US-compliant version of Binance",
        )
        
        # === DEXs ===
        
        self.register_venue(
            venue_id="uniswap_v3",
            name="Uniswap V3",
            venue_type=VenueType.DEX,
            asset_classes={AssetClass.CRYPTO_SPOT, AssetClass.MEMECOIN},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=False,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=False,
            website="https://uniswap.org",
            api_docs="https://docs.uniswap.org/",
            notes="On-chain data via The Graph subgraph",
        )
        
        self.register_venue(
            venue_id="curve",
            name="Curve Finance",
            venue_type=VenueType.DEX,
            asset_classes={AssetClass.CRYPTO_SPOT, AssetClass.DEFI_AMM},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=False,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=False,
            website="https://curve.fi",
            api_docs="https://curve.readthedocs.io/",
            notes="Stablecoin-focused AMM",
        )
        
        # === EQUITIES / ETFs (US-COMPLIANT) ===
        
        self.register_venue(
            venue_id="alpaca",
            name="Alpaca Markets",
            venue_type=VenueType.BROKER,
            asset_classes={AssetClass.EQUITY_SPOT, AssetClass.ETF},
            allowed_jurisdictions={Jurisdiction.US},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=False,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://alpaca.markets",
            api_docs="https://alpaca.markets/docs/",
            notes="Commission-free trading, free historical bars",
        )
        
        self.register_venue(
            venue_id="polygon_io",
            name="Polygon.io",
            venue_type=VenueType.DATA_VENDOR,
            asset_classes={AssetClass.EQUITY_SPOT, AssetClass.ETF, AssetClass.OPTION, AssetClass.FOREX},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=True,
            is_free=False,
            requires_kyc=False,
            website="https://polygon.io",
            api_docs="https://polygon.io/docs/",
            notes="Free tier available, paid for full tick data",
        )
        
        # === FUTURES ===
        
        self.register_venue(
            venue_id="cme_datamine",
            name="CME DataMine",
            venue_type=VenueType.DATA_VENDOR,
            asset_classes={AssetClass.FUTURE, AssetClass.OPTION},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=True,
            is_free=False,
            requires_kyc=True,
            website="https://www.cmegroup.com/market-data/datamine.html",
            api_docs="https://www.cmegroup.com/market-data/datamine-api.html",
            notes="Official CME historical data, paid",
        )
        
        # === FOREX ===
        
        self.register_venue(
            venue_id="oanda",
            name="OANDA",
            venue_type=VenueType.BROKER,
            asset_classes={AssetClass.FOREX},
            allowed_jurisdictions={Jurisdiction.US, Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=False,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=True,
            website="https://www.oanda.com",
            api_docs="https://developer.oanda.com/",
            notes="Free historical FX data with account",
        )
        
        # === DeFi PROTOCOLS ===
        
        self.register_venue(
            venue_id="aave",
            name="Aave",
            venue_type=VenueType.DEFI_PROTOCOL,
            asset_classes={AssetClass.DEFI_LENDING},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=False,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=False,
            is_free=True,
            requires_kyc=False,
            website="https://aave.com",
            api_docs="https://docs.aave.com/",
            notes="On-chain lending data via subgraph",
        )
        
        self.register_venue(
            venue_id="gmx",
            name="GMX",
            venue_type=VenueType.DEFI_PROTOCOL,
            asset_classes={AssetClass.DEFI_PERP},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=False,
            website="https://gmx.io",
            api_docs="https://docs.gmx.io/",
            notes="Decentralized perpetuals",
        )
        
        # === RWAs ===
        
        self.register_venue(
            venue_id="ondo_finance",
            name="Ondo Finance",
            venue_type=VenueType.DEFI_PROTOCOL,
            asset_classes={AssetClass.RWA_TREASURY, AssetClass.RWA_CREDIT},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=False,
            has_order_book=False,
            has_ohlcv=False,
            is_free=True,
            requires_kyc=True,
            website="https://ondo.finance",
            api_docs="https://docs.ondo.finance/",
            notes="Tokenized treasuries and credit",
        )
        
        # === PREDICTION MARKETS ===
        
        self.register_venue(
            venue_id="polymarket",
            name="Polymarket",
            venue_type=VenueType.PREDICTION_PLATFORM,
            asset_classes={AssetClass.PREDICTION_MARKET},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions={Jurisdiction.US},
            supports_rest_api=True,
            supports_websocket=True,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=False,
            is_free=True,
            requires_kyc=False,
            website="https://polymarket.com",
            api_docs="https://docs.polymarket.com/",
            notes="BLOCKED FOR US USERS - on-chain prediction markets",
        )
        
        self.register_venue(
            venue_id="augur",
            name="Augur",
            venue_type=VenueType.PREDICTION_PLATFORM,
            asset_classes={AssetClass.PREDICTION_MARKET},
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=False,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=True,
            has_ohlcv=False,
            is_free=True,
            requires_kyc=False,
            website="https://augur.net",
            api_docs="https://docs.augur.net/",
            notes="Decentralized prediction market protocol",
        )
        
        # === DATA AGGREGATORS ===
        
        self.register_venue(
            venue_id="quantconnect",
            name="QuantConnect",
            venue_type=VenueType.DATA_VENDOR,
            asset_classes={
                AssetClass.CRYPTO_SPOT,
                AssetClass.EQUITY_SPOT,
                AssetClass.ETF,
                AssetClass.FUTURE,
                AssetClass.OPTION,
                AssetClass.FOREX,
            },
            allowed_jurisdictions={Jurisdiction.GLOBAL},
            blocked_jurisdictions=set(),
            supports_rest_api=True,
            supports_websocket=False,
            supports_fix=False,
            supports_historical=True,
            has_tick_data=True,
            has_order_book=False,
            has_ohlcv=True,
            is_free=True,
            requires_kyc=False,
            website="https://www.quantconnect.com",
            api_docs="https://www.quantconnect.com/docs/",
            notes="Free research datasets, paid for full access",
        )
        
        logger.info(f"Initialized {len(self._venues)} venues")
    
    def _initialize_restrictions(self) -> None:
        """Initialize venue restrictions."""
        
        # Binance.com blocked for US
        self.register_restriction(
            restriction_id="binance_us_block",
            venue_id="binance_global",
            jurisdiction=Jurisdiction.US,
            asset_class=None,
            restriction_type="blocked",
            reason="Binance.com not licensed to operate in US",
            effective_date=datetime(2019, 9, 12),
            reference_url="https://www.binance.com/en/support/announcement/",
        )
        
        # Polymarket blocked for US
        self.register_restriction(
            restriction_id="polymarket_us_block",
            venue_id="polymarket",
            jurisdiction=Jurisdiction.US,
            asset_class=None,
            restriction_type="blocked",
            reason="Polymarket geo-blocks US users",
            effective_date=datetime(2022, 1, 1),
            reference_url="https://polymarket.com/terms",
        )
        
        logger.info(f"Initialized {len(self._restrictions)} restrictions")
    
    def register_venue(
        self,
        venue_id: str,
        name: str,
        venue_type: VenueType,
        asset_classes: Set[AssetClass],
        allowed_jurisdictions: Set[Jurisdiction],
        blocked_jurisdictions: Set[Jurisdiction],
        supports_rest_api: bool,
        supports_websocket: bool,
        supports_fix: bool,
        supports_historical: bool,
        has_tick_data: bool,
        has_order_book: bool,
        has_ohlcv: bool,
        is_free: bool,
        requires_kyc: bool,
        website: str,
        api_docs: str,
        notes: str = "",
    ) -> VenueDefinition:
        """Register venue definition."""
        venue = VenueDefinition(
            venue_id=venue_id,
            name=name,
            venue_type=venue_type,
            asset_classes=asset_classes,
            allowed_jurisdictions=allowed_jurisdictions,
            blocked_jurisdictions=blocked_jurisdictions,
            supports_rest_api=supports_rest_api,
            supports_websocket=supports_websocket,
            supports_fix=supports_fix,
            supports_historical=supports_historical,
            has_tick_data=has_tick_data,
            has_order_book=has_order_book,
            has_ohlcv=has_ohlcv,
            is_free=is_free,
            requires_kyc=requires_kyc,
            website=website,
            api_docs=api_docs,
            notes=notes,
        )
        
        self._venues[venue_id] = venue
        
        return venue
    
    def register_restriction(
        self,
        restriction_id: str,
        venue_id: str,
        jurisdiction: Jurisdiction,
        asset_class: Optional[AssetClass],
        restriction_type: str,
        reason: str,
        effective_date: datetime,
        reference_url: Optional[str] = None,
    ) -> VenueRestriction:
        """Register venue restriction."""
        restriction = VenueRestriction(
            restriction_id=restriction_id,
            venue_id=venue_id,
            jurisdiction=jurisdiction,
            asset_class=asset_class,
            restriction_type=restriction_type,
            reason=reason,
            effective_date=effective_date,
            reference_url=reference_url,
        )
        
        self._restrictions.append(restriction)
        
        return restriction
    
    def get_allowed_venues(
        self,
        jurisdiction: Jurisdiction,
        asset_class: AssetClass,
        require_free: bool = False,
        require_tick_data: bool = False,
        require_order_book: bool = False,
    ) -> List[VenueDefinition]:
        """
        Get allowed venues for jurisdiction and asset class.
        
        Respects geo restrictions and filters by capabilities.
        """
        allowed_venues = []
        
        for venue_id, venue in self._venues.items():
            # Check asset class support
            if asset_class not in venue.asset_classes:
                continue
            
            # Check jurisdiction allowed
            if jurisdiction not in venue.allowed_jurisdictions and Jurisdiction.GLOBAL not in venue.allowed_jurisdictions:
                continue
            
            # Check jurisdiction not blocked
            if jurisdiction in venue.blocked_jurisdictions:
                continue
            
            # Check restrictions
            has_restriction = any(
                r.venue_id == venue_id and
                r.jurisdiction == jurisdiction and
                (r.asset_class is None or r.asset_class == asset_class) and
                r.restriction_type == "blocked"
                for r in self._restrictions
            )
            
            if has_restriction:
                continue
            
            # Check optional filters
            if require_free and not venue.is_free:
                continue
            
            if require_tick_data and not venue.has_tick_data:
                continue
            
            if require_order_book and not venue.has_order_book:
                continue
            
            allowed_venues.append(venue)
        
        return allowed_venues
    
    def is_venue_allowed(
        self,
        venue_id: str,
        jurisdiction: Jurisdiction,
        asset_class: Optional[AssetClass] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if venue is allowed for jurisdiction.
        
        Returns (allowed, reason_if_blocked).
        """
        venue = self._venues.get(venue_id)
        if not venue:
            return False, f"Venue '{venue_id}' not found"
        
        # Check asset class if specified
        if asset_class and asset_class not in venue.asset_classes:
            return False, f"Venue does not support {asset_class.value}"
        
        # Check jurisdiction allowed
        if jurisdiction not in venue.allowed_jurisdictions and Jurisdiction.GLOBAL not in venue.allowed_jurisdictions:
            return False, f"Venue not available in {jurisdiction.value}"
        
        # Check jurisdiction not blocked
        if jurisdiction in venue.blocked_jurisdictions:
            return False, f"Venue blocked in {jurisdiction.value}"
        
        # Check restrictions
        for restriction in self._restrictions:
            if (restriction.venue_id == venue_id and
                restriction.jurisdiction == jurisdiction and
                (restriction.asset_class is None or restriction.asset_class == asset_class) and
                restriction.restriction_type == "blocked"):
                return False, restriction.reason
        
        return True, None
    
    def get_venue_recommendations(
        self,
        jurisdiction: Jurisdiction,
        asset_class: AssetClass,
    ) -> Dict[str, Any]:
        """Get venue recommendations for jurisdiction and asset class."""
        allowed = self.get_allowed_venues(jurisdiction, asset_class)
        free_venues = [v for v in allowed if v.is_free]
        tick_venues = [v for v in allowed if v.has_tick_data]
        
        return {
            "jurisdiction": jurisdiction.value,
            "asset_class": asset_class.value,
            "total_venues": len(allowed),
            "free_venues": len(free_venues),
            "tick_data_venues": len(tick_venues),
            "recommended_venues": [
                {
                    "venue_id": v.venue_id,
                    "name": v.name,
                    "venue_type": v.venue_type.value,
                    "is_free": v.is_free,
                    "has_tick_data": v.has_tick_data,
                    "has_order_book": v.has_order_book,
                    "notes": v.notes,
                }
                for v in free_venues[:5]
            ],
        }
    
    def get_all_venues(self) -> List[VenueDefinition]:
        """Get all registered venues."""
        return list(self._venues.values())
    
    def get_venue(self, venue_id: str) -> Optional[VenueDefinition]:
        """Get venue by ID."""
        return self._venues.get(venue_id)


_geo_aware_venue_system: Optional[GeoAwareVenueSystem] = None


def get_geo_aware_venue_system() -> GeoAwareVenueSystem:
    """Get global GeoAwareVenueSystem instance."""
    global _geo_aware_venue_system
    if _geo_aware_venue_system is None:
        _geo_aware_venue_system = GeoAwareVenueSystem()
    return _geo_aware_venue_system

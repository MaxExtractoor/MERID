"""
Monetization layers for MERID projects and protocols.

Implements protocol fees, white-label services, token models, data/API monetization,
and affiliate revenue streams, all optimized by AI swarms.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class RevenueStream(Enum):
    """Revenue stream type."""
    MANAGEMENT_FEE = "management_fee"
    PERFORMANCE_FEE = "performance_fee"
    PROTOCOL_FEE = "protocol_fee"
    WHITE_LABEL = "white_label"
    API_SUBSCRIPTION = "api_subscription"
    DATA_LICENSING = "data_licensing"
    AFFILIATE = "affiliate"
    TOKEN_REVENUE_SHARE = "token_revenue_share"


class FeeType(Enum):
    """Fee type."""
    FLAT = "flat"
    PERCENTAGE = "percentage"
    TIERED = "tiered"
    DYNAMIC = "dynamic"


@dataclass
class ProtocolFee:
    """Protocol fee configuration."""
    fee_id: str
    protocol_name: str
    
    # Management fee
    management_fee_annual: Decimal = Decimal("1.0")  # 1% annual
    management_fee_type: FeeType = FeeType.PERCENTAGE
    
    # Performance fee
    performance_fee: Decimal = Decimal("10.0")  # 10% of profits
    high_water_mark: bool = True
    
    # Protocol fees
    swap_fee: Decimal = Decimal("0.3")  # 0.3% per swap
    deposit_fee: Decimal = Decimal("0")
    withdrawal_fee: Decimal = Decimal("0.1")  # 0.1% withdrawal
    
    # Revenue collected
    total_management_fees_usd: Decimal = Decimal("0")
    total_performance_fees_usd: Decimal = Decimal("0")
    total_protocol_fees_usd: Decimal = Decimal("0")
    
    # Distribution
    treasury_allocation: Decimal = Decimal("40.0")  # 40% to treasury
    token_holder_allocation: Decimal = Decimal("30.0")  # 30% to token holders
    team_allocation: Decimal = Decimal("20.0")  # 20% to team
    buyback_allocation: Decimal = Decimal("10.0")  # 10% for buyback/burn
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WhiteLabelClient:
    """White-label client."""
    client_id: str
    client_name: str
    
    # Services
    services: List[str] = field(default_factory=list)  # ["dex", "risk", "ai_swarms", "dashboards"]
    
    # Pricing
    setup_fee_usd: Decimal = Decimal("50000")
    monthly_fee_usd: Decimal = Decimal("5000")
    usage_fee_percentage: Decimal = Decimal("0.5")  # 0.5% of volume
    
    # Usage
    monthly_volume_usd: Decimal = Decimal("0")
    total_revenue_usd: Decimal = Decimal("0")
    
    # Contract
    contract_start: datetime = field(default_factory=datetime.utcnow)
    contract_end: Optional[datetime] = None
    
    active: bool = True


@dataclass
class APISubscription:
    """API subscription tier."""
    tier_id: str
    tier_name: str
    
    # Pricing
    monthly_price_usd: Decimal
    
    # Limits
    requests_per_month: int
    rate_limit_per_second: int
    
    # Features
    features: List[str] = field(default_factory=list)
    
    # Usage
    active_subscribers: int = 0
    monthly_revenue_usd: Decimal = Decimal("0")


@dataclass
class DataProduct:
    """Data product for licensing."""
    product_id: str
    name: str
    description: str
    
    # Data type
    data_type: str  # "market_data", "backtest_results", "ai_signals", "risk_metrics"
    
    # Pricing
    pricing_model: str  # "subscription", "pay_per_use", "enterprise"
    base_price_usd: Decimal
    
    # Access
    update_frequency: str  # "realtime", "hourly", "daily"
    historical_depth_days: int
    
    # Revenue
    active_licenses: int = 0
    monthly_revenue_usd: Decimal = Decimal("0")


@dataclass
class AffiliatePartner:
    """Affiliate partner."""
    partner_id: str
    partner_name: str
    partner_type: str  # "bridge", "rwa", "perp", "oracle"
    
    # Revenue share
    revenue_share_percentage: Decimal  # % of fees from routed volume
    
    # Volume
    monthly_volume_usd: Decimal = Decimal("0")
    total_volume_usd: Decimal = Decimal("0")
    
    # Revenue
    monthly_revenue_usd: Decimal = Decimal("0")
    total_revenue_usd: Decimal = Decimal("0")
    
    # Status
    active: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TokenRevenueShare:
    """Token revenue sharing model."""
    token_id: str
    token_symbol: str
    
    # Revenue share
    revenue_share_percentage: Decimal  # % of protocol fees to token holders
    
    # Distribution
    distribution_frequency: str  # "daily", "weekly", "monthly"
    min_holding_requirement: Decimal = Decimal("0")
    
    # Staking boost
    staking_boost_enabled: bool = True
    staking_boost_multiplier: Decimal = Decimal("1.5")  # 1.5x for stakers
    
    # Metrics
    total_distributed_usd: Decimal = Decimal("0")
    holders_count: int = 0
    stakers_count: int = 0
    
    # Compliance
    regulatory_compliant: bool = True
    jurisdiction_restrictions: List[str] = field(default_factory=list)


@dataclass
class RevenueReport:
    """Revenue report."""
    report_id: str
    period_start: datetime
    period_end: datetime
    
    # Revenue by stream
    management_fees: Decimal = Decimal("0")
    performance_fees: Decimal = Decimal("0")
    protocol_fees: Decimal = Decimal("0")
    white_label_revenue: Decimal = Decimal("0")
    api_revenue: Decimal = Decimal("0")
    data_licensing_revenue: Decimal = Decimal("0")
    affiliate_revenue: Decimal = Decimal("0")
    
    # Total
    total_revenue: Decimal = Decimal("0")
    
    # Growth
    mom_growth_percentage: Optional[Decimal] = None
    yoy_growth_percentage: Optional[Decimal] = None


class Monetization:
    """
    Monetization layers for MERID projects and protocols.
    
    Implements:
    - Protocol and vault fees (management, performance)
    - White-label and infrastructure services
    - Token revenue-sharing models
    - Data, analytics, and API monetization
    - Affiliate and partner revenue
    - AI-optimized fee structures
    """
    
    def __init__(self):
        self._protocol_fees: Dict[str, ProtocolFee] = {}
        self._white_label_clients: Dict[str, WhiteLabelClient] = {}
        self._api_tiers: Dict[str, APISubscription] = {}
        self._data_products: Dict[str, DataProduct] = {}
        self._affiliate_partners: Dict[str, AffiliatePartner] = {}
        self._token_models: Dict[str, TokenRevenueShare] = {}
        self._revenue_reports: List[RevenueReport] = []
        
        self._initialize_default_config()
    
    def _initialize_default_config(self) -> None:
        """Initialize default monetization configuration."""
        
        # Default protocol fees
        self.configure_protocol_fees(
            fee_id="merid_default",
            protocol_name="MERID",
            management_fee_annual=Decimal("1.0"),
            performance_fee=Decimal("10.0"),
            swap_fee=Decimal("0.3"),
            withdrawal_fee=Decimal("0.1"),
        )
        
        # API tiers
        self.add_api_tier(
            tier_id="free",
            tier_name="Free Tier",
            monthly_price_usd=Decimal("0"),
            requests_per_month=10000,
            rate_limit_per_second=1,
            features=["basic_market_data", "public_endpoints"],
        )
        
        self.add_api_tier(
            tier_id="pro",
            tier_name="Pro Tier",
            monthly_price_usd=Decimal("99"),
            requests_per_month=1000000,
            rate_limit_per_second=10,
            features=["market_data", "backtest_api", "ai_signals", "webhooks"],
        )
        
        self.add_api_tier(
            tier_id="enterprise",
            tier_name="Enterprise Tier",
            monthly_price_usd=Decimal("999"),
            requests_per_month=10000000,
            rate_limit_per_second=100,
            features=["all_features", "dedicated_support", "custom_integrations", "sla"],
        )
        
        # Data products
        self.add_data_product(
            product_id="market_data_feed",
            name="Real-Time Market Data Feed",
            description="Real-time market data across all supported venues",
            data_type="market_data",
            pricing_model="subscription",
            base_price_usd=Decimal("499"),
            update_frequency="realtime",
            historical_depth_days=365,
        )
        
        self.add_data_product(
            product_id="ai_signals",
            name="AI Trading Signals",
            description="AI-generated trading signals and predictions",
            data_type="ai_signals",
            pricing_model="subscription",
            base_price_usd=Decimal("1999"),
            update_frequency="realtime",
            historical_depth_days=90,
        )
        
        # Token revenue share
        self.configure_token_revenue_share(
            token_id="merid_token",
            token_symbol="MERID",
            revenue_share_percentage=Decimal("30.0"),
            distribution_frequency="weekly",
            staking_boost_enabled=True,
            staking_boost_multiplier=Decimal("1.5"),
        )
        
        logger.info("Initialized default monetization configuration")
    
    def configure_protocol_fees(
        self,
        fee_id: str,
        protocol_name: str,
        management_fee_annual: Decimal = Decimal("1.0"),
        performance_fee: Decimal = Decimal("10.0"),
        swap_fee: Decimal = Decimal("0.3"),
        withdrawal_fee: Decimal = Decimal("0.1"),
    ) -> ProtocolFee:
        """Configure protocol fees."""
        fees = ProtocolFee(
            fee_id=fee_id,
            protocol_name=protocol_name,
            management_fee_annual=management_fee_annual,
            performance_fee=performance_fee,
            swap_fee=swap_fee,
            withdrawal_fee=withdrawal_fee,
        )
        
        self._protocol_fees[fee_id] = fees
        
        logger.info(
            f"Configured protocol fees for '{protocol_name}': "
            f"mgmt {management_fee_annual}%, perf {performance_fee}%"
        )
        
        return fees
    
    def add_white_label_client(
        self,
        client_id: str,
        client_name: str,
        services: List[str],
        setup_fee_usd: Decimal = Decimal("50000"),
        monthly_fee_usd: Decimal = Decimal("5000"),
        usage_fee_percentage: Decimal = Decimal("0.5"),
    ) -> WhiteLabelClient:
        """Add white-label client."""
        client = WhiteLabelClient(
            client_id=client_id,
            client_name=client_name,
            services=services,
            setup_fee_usd=setup_fee_usd,
            monthly_fee_usd=monthly_fee_usd,
            usage_fee_percentage=usage_fee_percentage,
        )
        
        self._white_label_clients[client_id] = client
        
        logger.info(
            f"Added white-label client '{client_name}': "
            f"${setup_fee_usd} setup + ${monthly_fee_usd}/mo"
        )
        
        return client
    
    def add_api_tier(
        self,
        tier_id: str,
        tier_name: str,
        monthly_price_usd: Decimal,
        requests_per_month: int,
        rate_limit_per_second: int,
        features: List[str],
    ) -> APISubscription:
        """Add API subscription tier."""
        tier = APISubscription(
            tier_id=tier_id,
            tier_name=tier_name,
            monthly_price_usd=monthly_price_usd,
            requests_per_month=requests_per_month,
            rate_limit_per_second=rate_limit_per_second,
            features=features,
        )
        
        self._api_tiers[tier_id] = tier
        
        logger.info(
            f"Added API tier '{tier_name}': ${monthly_price_usd}/mo "
            f"({requests_per_month:,} requests)"
        )
        
        return tier
    
    def add_data_product(
        self,
        product_id: str,
        name: str,
        description: str,
        data_type: str,
        pricing_model: str,
        base_price_usd: Decimal,
        update_frequency: str,
        historical_depth_days: int,
    ) -> DataProduct:
        """Add data product."""
        product = DataProduct(
            product_id=product_id,
            name=name,
            description=description,
            data_type=data_type,
            pricing_model=pricing_model,
            base_price_usd=base_price_usd,
            update_frequency=update_frequency,
            historical_depth_days=historical_depth_days,
        )
        
        self._data_products[product_id] = product
        
        logger.info(
            f"Added data product '{name}': ${base_price_usd}/mo ({update_frequency})"
        )
        
        return product
    
    def add_affiliate_partner(
        self,
        partner_id: str,
        partner_name: str,
        partner_type: str,
        revenue_share_percentage: Decimal,
    ) -> AffiliatePartner:
        """Add affiliate partner."""
        partner = AffiliatePartner(
            partner_id=partner_id,
            partner_name=partner_name,
            partner_type=partner_type,
            revenue_share_percentage=revenue_share_percentage,
        )
        
        self._affiliate_partners[partner_id] = partner
        
        logger.info(
            f"Added affiliate partner '{partner_name}': "
            f"{revenue_share_percentage}% revenue share"
        )
        
        return partner
    
    def configure_token_revenue_share(
        self,
        token_id: str,
        token_symbol: str,
        revenue_share_percentage: Decimal,
        distribution_frequency: str,
        staking_boost_enabled: bool = True,
        staking_boost_multiplier: Decimal = Decimal("1.5"),
    ) -> TokenRevenueShare:
        """Configure token revenue sharing."""
        model = TokenRevenueShare(
            token_id=token_id,
            token_symbol=token_symbol,
            revenue_share_percentage=revenue_share_percentage,
            distribution_frequency=distribution_frequency,
            staking_boost_enabled=staking_boost_enabled,
            staking_boost_multiplier=staking_boost_multiplier,
        )
        
        self._token_models[token_id] = model
        
        logger.info(
            f"Configured token revenue share for '{token_symbol}': "
            f"{revenue_share_percentage}% ({distribution_frequency})"
        )
        
        return model
    
    def record_revenue(
        self,
        stream: RevenueStream,
        amount_usd: Decimal,
        source_id: Optional[str] = None,
    ) -> None:
        """Record revenue."""
        if stream == RevenueStream.MANAGEMENT_FEE:
            fee_config = self._protocol_fees.get(source_id or "merid_default")
            if fee_config:
                fee_config.total_management_fees_usd += amount_usd
        
        elif stream == RevenueStream.PERFORMANCE_FEE:
            fee_config = self._protocol_fees.get(source_id or "merid_default")
            if fee_config:
                fee_config.total_performance_fees_usd += amount_usd
        
        elif stream == RevenueStream.PROTOCOL_FEE:
            fee_config = self._protocol_fees.get(source_id or "merid_default")
            if fee_config:
                fee_config.total_protocol_fees_usd += amount_usd
        
        elif stream == RevenueStream.WHITE_LABEL:
            client = self._white_label_clients.get(source_id) if source_id else None
            if client:
                client.total_revenue_usd += amount_usd
        
        elif stream == RevenueStream.API_SUBSCRIPTION:
            tier = self._api_tiers.get(source_id) if source_id else None
            if tier:
                tier.monthly_revenue_usd += amount_usd
        
        elif stream == RevenueStream.AFFILIATE:
            partner = self._affiliate_partners.get(source_id) if source_id else None
            if partner:
                partner.total_revenue_usd += amount_usd
        
        logger.info(f"Recorded revenue: {stream.value} ${amount_usd}")
    
    def generate_revenue_report(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> RevenueReport:
        """Generate revenue report."""
        report_id = f"report_{int(period_start.timestamp())}_{int(period_end.timestamp())}"
        
        report = RevenueReport(
            report_id=report_id,
            period_start=period_start,
            period_end=period_end,
        )
        
        # Aggregate revenue by stream
        for fees in self._protocol_fees.values():
            report.management_fees += fees.total_management_fees_usd
            report.performance_fees += fees.total_performance_fees_usd
            report.protocol_fees += fees.total_protocol_fees_usd
        
        for client in self._white_label_clients.values():
            report.white_label_revenue += client.total_revenue_usd
        
        for tier in self._api_tiers.values():
            report.api_revenue += tier.monthly_revenue_usd
        
        for product in self._data_products.values():
            report.data_licensing_revenue += product.monthly_revenue_usd
        
        for partner in self._affiliate_partners.values():
            report.affiliate_revenue += partner.total_revenue_usd
        
        # Calculate total
        report.total_revenue = (
            report.management_fees +
            report.performance_fees +
            report.protocol_fees +
            report.white_label_revenue +
            report.api_revenue +
            report.data_licensing_revenue +
            report.affiliate_revenue
        )
        
        self._revenue_reports.append(report)
        
        logger.info(
            f"Generated revenue report: ${report.total_revenue} "
            f"({period_start.date()} to {period_end.date()})"
        )
        
        return report
    
    def get_protocol_fees(self, fee_id: str) -> Optional[ProtocolFee]:
        """Get protocol fees configuration."""
        return self._protocol_fees.get(fee_id)
    
    def get_white_label_clients(self) -> List[WhiteLabelClient]:
        """Get all white-label clients."""
        return list(self._white_label_clients.values())
    
    def get_api_tiers(self) -> List[APISubscription]:
        """Get all API tiers."""
        return list(self._api_tiers.values())
    
    def get_data_products(self) -> List[DataProduct]:
        """Get all data products."""
        return list(self._data_products.values())
    
    def get_affiliate_partners(self) -> List[AffiliatePartner]:
        """Get all affiliate partners."""
        return list(self._affiliate_partners.values())
    
    def get_revenue_reports(self) -> List[RevenueReport]:
        """Get all revenue reports."""
        return self._revenue_reports


_monetization: Optional[Monetization] = None


def get_monetization() -> Monetization:
    """Get global Monetization instance."""
    global _monetization
    if _monetization is None:
        _monetization = Monetization()
    return _monetization

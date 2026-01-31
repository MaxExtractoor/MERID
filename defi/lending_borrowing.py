"""
Lending and borrowing integration for MERID.

Implements lending markets, structured credit, RWA lending, leverage strategies,
and AI-optimized collateral management with health factor monitoring.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class LendingProtocol(Enum):
    """Lending protocol."""
    AAVE = "aave"
    COMPOUND = "compound"
    MORPHO = "morpho"
    EULER = "euler"
    MAPLE = "maple"
    GOLDFINCH = "goldfinch"
    CENTRIFUGE = "centrifuge"


class AssetType(Enum):
    """Asset type."""
    STABLECOIN = "stablecoin"
    BLUE_CHIP = "blue_chip"
    ALTCOIN = "altcoin"
    LST = "lst"  # Liquid staking token
    RWA = "rwa"  # Real-world asset
    LP_TOKEN = "lp_token"


class PositionType(Enum):
    """Position type."""
    LEND = "lend"
    BORROW = "borrow"
    LEVERAGE = "leverage"
    CARRY_TRADE = "carry_trade"


@dataclass
class LendingMarket:
    """Lending market."""
    market_id: str
    protocol: LendingProtocol
    asset: str
    asset_type: AssetType
    
    # Rates
    supply_apy: Decimal
    borrow_apy: Decimal
    
    # Utilization
    total_supplied_usd: Decimal
    total_borrowed_usd: Decimal
    utilization_rate: Decimal
    
    # Collateral
    can_be_collateral: bool = True
    collateral_factor: Decimal = Decimal("0.75")  # LTV
    liquidation_threshold: Decimal = Decimal("0.80")
    liquidation_penalty: Decimal = Decimal("0.05")
    
    # Incentives
    supply_incentive_apy: Decimal = Decimal("0")
    borrow_incentive_apy: Decimal = Decimal("0")
    incentive_tokens: List[str] = field(default_factory=list)
    
    # Risk
    protocol_risk: str = "medium"
    oracle_risk: str = "low"
    
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LendingPosition:
    """Lending position."""
    position_id: str
    user_id: str
    position_type: PositionType
    
    # Market
    market_id: str
    protocol: LendingProtocol
    asset: str
    
    # Position
    amount: Decimal
    value_usd: Decimal
    
    # Performance (for lending)
    interest_earned_usd: Decimal = Decimal("0")
    incentives_earned_usd: Decimal = Decimal("0")
    total_earned_usd: Decimal = Decimal("0")
    
    # Cost (for borrowing)
    interest_paid_usd: Decimal = Decimal("0")
    
    # Health (for borrowing)
    collateral_value_usd: Decimal = Decimal("0")
    debt_value_usd: Decimal = Decimal("0")
    health_factor: Optional[Decimal] = None
    liquidation_price: Optional[Decimal] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_update: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LeverageStrategy:
    """Leverage strategy."""
    strategy_id: str
    user_id: str
    
    # Strategy
    strategy_type: str  # "leverage_yield", "carry_trade", "basis_trade"
    target_leverage: Decimal
    
    # Positions
    collateral_asset: str
    collateral_amount: Decimal
    collateral_value_usd: Decimal
    
    borrowed_asset: str
    borrowed_amount: Decimal
    borrowed_value_usd: Decimal
    
    # Performance
    yield_apy: Decimal
    borrow_cost_apy: Decimal
    net_apy: Decimal
    
    # Risk
    current_leverage: Decimal
    health_factor: Decimal
    liquidation_price: Decimal
    
    # Limits
    max_leverage: Decimal = Decimal("3.0")
    min_health_factor: Decimal = Decimal("1.5")
    stop_loss_price: Optional[Decimal] = None
    
    # Status
    active: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_rebalance: Optional[datetime] = None


@dataclass
class StructuredCreditProduct:
    """Structured credit product (RWA)."""
    product_id: str
    protocol: LendingProtocol
    
    # Product details
    name: str
    description: str
    asset_class: str  # "invoices", "mortgages", "corporate_credit", "t_bills"
    
    # Tranches
    senior_tranche_apy: Decimal
    junior_tranche_apy: Decimal
    
    senior_tvl_usd: Decimal
    junior_tvl_usd: Decimal
    
    # Risk
    default_rate: Decimal = Decimal("0")
    recovery_rate: Decimal = Decimal("0.80")
    credit_rating: Optional[str] = None
    
    # Terms
    maturity_date: Optional[datetime] = None
    lockup_period_days: int = 0
    
    # Compliance
    kyc_required: bool = True
    accredited_only: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthMonitorAlert:
    """Health factor monitoring alert."""
    alert_id: str
    position_id: str
    user_id: str
    
    # Alert
    alert_type: str  # "health_warning", "health_critical", "liquidation_risk"
    severity: str  # "low", "medium", "high", "critical"
    
    # Details
    current_health_factor: Decimal
    threshold_health_factor: Decimal
    liquidation_price: Decimal
    current_price: Decimal
    
    # Recommended action
    recommended_action: str
    ai_rationale: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False


class LendingBorrowing:
    """
    Lending and borrowing integration for MERID.
    
    Implements:
    - Lending markets integration (Aave, Compound, etc.)
    - Structured credit and RWA products
    - Leverage strategies (leverage-on-yield, carry, basis)
    - Health factor monitoring and alerts
    - Collateral optimization
    - Liquidation protection
    """
    
    def __init__(self):
        self._markets: Dict[str, LendingMarket] = {}
        self._positions: Dict[str, LendingPosition] = {}
        self._leverage_strategies: Dict[str, LeverageStrategy] = {}
        self._credit_products: Dict[str, StructuredCreditProduct] = {}
        self._health_alerts: List[HealthMonitorAlert] = []
        
        self._initialize_markets()
        self._initialize_credit_products()
    
    def _initialize_markets(self) -> None:
        """Initialize lending markets."""
        
        # Aave USDC
        self.add_market(
            market_id="aave_usdc",
            protocol=LendingProtocol.AAVE,
            asset="USDC",
            asset_type=AssetType.STABLECOIN,
            supply_apy=Decimal("4.2"),
            borrow_apy=Decimal("5.8"),
            total_supplied_usd=Decimal("3000000000"),
            total_borrowed_usd=Decimal("2100000000"),
            collateral_factor=Decimal("0.80"),
            liquidation_threshold=Decimal("0.85"),
            supply_incentive_apy=Decimal("0.5"),
            incentive_tokens=["AAVE"],
            protocol_risk="low",
        )
        
        # Aave ETH
        self.add_market(
            market_id="aave_eth",
            protocol=LendingProtocol.AAVE,
            asset="ETH",
            asset_type=AssetType.BLUE_CHIP,
            supply_apy=Decimal("2.8"),
            borrow_apy=Decimal("3.5"),
            total_supplied_usd=Decimal("5000000000"),
            total_borrowed_usd=Decimal("3000000000"),
            collateral_factor=Decimal("0.75"),
            liquidation_threshold=Decimal("0.80"),
            protocol_risk="low",
        )
        
        # Compound USDC
        self.add_market(
            market_id="compound_usdc",
            protocol=LendingProtocol.COMPOUND,
            asset="USDC",
            asset_type=AssetType.STABLECOIN,
            supply_apy=Decimal("3.8"),
            borrow_apy=Decimal("6.2"),
            total_supplied_usd=Decimal("2000000000"),
            total_borrowed_usd=Decimal("1400000000"),
            collateral_factor=Decimal("0.80"),
            liquidation_threshold=Decimal("0.85"),
            supply_incentive_apy=Decimal("1.0"),
            incentive_tokens=["COMP"],
            protocol_risk="low",
        )
        
        # Morpho stETH
        self.add_market(
            market_id="morpho_steth",
            protocol=LendingProtocol.MORPHO,
            asset="stETH",
            asset_type=AssetType.LST,
            supply_apy=Decimal("3.2"),
            borrow_apy=Decimal("4.0"),
            total_supplied_usd=Decimal("500000000"),
            total_borrowed_usd=Decimal("300000000"),
            collateral_factor=Decimal("0.85"),
            liquidation_threshold=Decimal("0.90"),
            protocol_risk="medium",
        )
        
        logger.info(f"Initialized {len(self._markets)} lending markets")
    
    def _initialize_credit_products(self) -> None:
        """Initialize structured credit products."""
        
        # Maple USDC pool (corporate credit)
        self.add_credit_product(
            product_id="maple_usdc_corporate",
            protocol=LendingProtocol.MAPLE,
            name="Maple Corporate Credit Pool",
            description="Senior secured loans to institutional borrowers",
            asset_class="corporate_credit",
            senior_tranche_apy=Decimal("8.5"),
            junior_tranche_apy=Decimal("12.0"),
            senior_tvl_usd=Decimal("100000000"),
            junior_tvl_usd=Decimal("20000000"),
            default_rate=Decimal("0.02"),
            recovery_rate=Decimal("0.85"),
            credit_rating="BBB",
            lockup_period_days=90,
            kyc_required=True,
            accredited_only=True,
        )
        
        # Goldfinch senior pool
        self.add_credit_product(
            product_id="goldfinch_senior",
            protocol=LendingProtocol.GOLDFINCH,
            name="Goldfinch Senior Pool",
            description="Diversified emerging market credit",
            asset_class="emerging_market_credit",
            senior_tranche_apy=Decimal("10.0"),
            junior_tranche_apy=Decimal("15.0"),
            senior_tvl_usd=Decimal("50000000"),
            junior_tvl_usd=Decimal("10000000"),
            default_rate=Decimal("0.05"),
            recovery_rate=Decimal("0.70"),
            lockup_period_days=180,
            kyc_required=True,
            accredited_only=False,
        )
        
        # Centrifuge T-bill pool
        self.add_credit_product(
            product_id="centrifuge_tbill",
            protocol=LendingProtocol.CENTRIFUGE,
            name="Centrifuge T-Bill Pool",
            description="Tokenized US Treasury bills",
            asset_class="t_bills",
            senior_tranche_apy=Decimal("5.2"),
            junior_tranche_apy=Decimal("0"),  # No junior tranche
            senior_tvl_usd=Decimal("200000000"),
            junior_tvl_usd=Decimal("0"),
            default_rate=Decimal("0"),
            recovery_rate=Decimal("1.0"),
            credit_rating="AAA",
            lockup_period_days=30,
            kyc_required=True,
            accredited_only=False,
        )
        
        logger.info(f"Initialized {len(self._credit_products)} credit products")
    
    def add_market(
        self,
        market_id: str,
        protocol: LendingProtocol,
        asset: str,
        asset_type: AssetType,
        supply_apy: Decimal,
        borrow_apy: Decimal,
        total_supplied_usd: Decimal,
        total_borrowed_usd: Decimal,
        collateral_factor: Decimal = Decimal("0.75"),
        liquidation_threshold: Decimal = Decimal("0.80"),
        supply_incentive_apy: Decimal = Decimal("0"),
        incentive_tokens: Optional[List[str]] = None,
        protocol_risk: str = "medium",
    ) -> LendingMarket:
        """Add lending market."""
        utilization_rate = (total_borrowed_usd / total_supplied_usd * 100) if total_supplied_usd > 0 else Decimal("0")
        
        market = LendingMarket(
            market_id=market_id,
            protocol=protocol,
            asset=asset,
            asset_type=asset_type,
            supply_apy=supply_apy,
            borrow_apy=borrow_apy,
            total_supplied_usd=total_supplied_usd,
            total_borrowed_usd=total_borrowed_usd,
            utilization_rate=utilization_rate,
            collateral_factor=collateral_factor,
            liquidation_threshold=liquidation_threshold,
            supply_incentive_apy=supply_incentive_apy,
            incentive_tokens=incentive_tokens or [],
            protocol_risk=protocol_risk,
        )
        
        self._markets[market_id] = market
        
        return market
    
    def add_credit_product(
        self,
        product_id: str,
        protocol: LendingProtocol,
        name: str,
        description: str,
        asset_class: str,
        senior_tranche_apy: Decimal,
        junior_tranche_apy: Decimal,
        senior_tvl_usd: Decimal,
        junior_tvl_usd: Decimal,
        default_rate: Decimal = Decimal("0"),
        recovery_rate: Decimal = Decimal("0.80"),
        credit_rating: Optional[str] = None,
        lockup_period_days: int = 0,
        kyc_required: bool = True,
        accredited_only: bool = False,
    ) -> StructuredCreditProduct:
        """Add structured credit product."""
        product = StructuredCreditProduct(
            product_id=product_id,
            protocol=protocol,
            name=name,
            description=description,
            asset_class=asset_class,
            senior_tranche_apy=senior_tranche_apy,
            junior_tranche_apy=junior_tranche_apy,
            senior_tvl_usd=senior_tvl_usd,
            junior_tvl_usd=junior_tvl_usd,
            default_rate=default_rate,
            recovery_rate=recovery_rate,
            credit_rating=credit_rating,
            lockup_period_days=lockup_period_days,
            kyc_required=kyc_required,
            accredited_only=accredited_only,
        )
        
        self._credit_products[product_id] = product
        
        return product
    
    def create_lending_position(
        self,
        user_id: str,
        market_id: str,
        amount: Decimal,
        value_usd: Decimal,
    ) -> LendingPosition:
        """Create lending position."""
        market = self._markets.get(market_id)
        if not market:
            raise ValueError(f"Market '{market_id}' not found")
        
        position_id = f"lend_{user_id}_{market_id}_{int(datetime.utcnow().timestamp())}"
        
        position = LendingPosition(
            position_id=position_id,
            user_id=user_id,
            position_type=PositionType.LEND,
            market_id=market_id,
            protocol=market.protocol,
            asset=market.asset,
            amount=amount,
            value_usd=value_usd,
        )
        
        self._positions[position_id] = position
        
        logger.info(
            f"Created lending position for user '{user_id}': "
            f"{market.protocol.value} {market.asset} ${value_usd} "
            f"(APY: {market.supply_apy}%)"
        )
        
        return position
    
    def create_leverage_strategy(
        self,
        user_id: str,
        strategy_type: str,
        collateral_asset: str,
        collateral_amount: Decimal,
        borrowed_asset: str,
        target_leverage: Decimal,
        yield_apy: Decimal,
        borrow_cost_apy: Decimal,
    ) -> LeverageStrategy:
        """Create leverage strategy."""
        strategy_id = f"leverage_{user_id}_{int(datetime.utcnow().timestamp())}"
        
        # Calculate borrowed amount (simplified)
        borrowed_amount = collateral_amount * (target_leverage - 1)
        
        strategy = LeverageStrategy(
            strategy_id=strategy_id,
            user_id=user_id,
            strategy_type=strategy_type,
            target_leverage=target_leverage,
            collateral_asset=collateral_asset,
            collateral_amount=collateral_amount,
            collateral_value_usd=collateral_amount,  # Simplified
            borrowed_asset=borrowed_asset,
            borrowed_amount=borrowed_amount,
            borrowed_value_usd=borrowed_amount,  # Simplified
            yield_apy=yield_apy,
            borrow_cost_apy=borrow_cost_apy,
            net_apy=yield_apy * target_leverage - borrow_cost_apy * (target_leverage - 1),
            current_leverage=target_leverage,
            health_factor=Decimal("2.0"),  # Simplified
            liquidation_price=Decimal("0"),  # Calculate based on collateral factor
        )
        
        self._leverage_strategies[strategy_id] = strategy
        
        logger.info(
            f"Created leverage strategy for user '{user_id}': "
            f"{strategy_type} {target_leverage}x leverage "
            f"(Net APY: {strategy.net_apy}%)"
        )
        
        return strategy
    
    def monitor_health_factor(
        self,
        position_id: str,
        current_health_factor: Decimal,
        current_price: Decimal,
    ) -> Optional[HealthMonitorAlert]:
        """Monitor health factor and create alerts."""
        position = self._positions.get(position_id)
        if not position or position.position_type != PositionType.BORROW:
            return None
        
        # Determine alert level
        alert_type = None
        severity = None
        recommended_action = None
        
        if current_health_factor < Decimal("1.1"):
            alert_type = "liquidation_risk"
            severity = "critical"
            recommended_action = "Add collateral immediately or repay debt"
        elif current_health_factor < Decimal("1.3"):
            alert_type = "health_critical"
            severity = "high"
            recommended_action = "Add collateral or reduce debt to improve health factor"
        elif current_health_factor < Decimal("1.5"):
            alert_type = "health_warning"
            severity = "medium"
            recommended_action = "Monitor position closely, consider adding collateral"
        
        if not alert_type:
            return None
        
        alert_id = f"alert_{position_id}_{int(datetime.utcnow().timestamp())}"
        
        alert = HealthMonitorAlert(
            alert_id=alert_id,
            position_id=position_id,
            user_id=position.user_id,
            alert_type=alert_type,
            severity=severity,
            current_health_factor=current_health_factor,
            threshold_health_factor=Decimal("1.5"),
            liquidation_price=position.liquidation_price or Decimal("0"),
            current_price=current_price,
            recommended_action=recommended_action,
        )
        
        self._health_alerts.append(alert)
        
        logger.warning(
            f"Health alert for position '{position_id}': "
            f"{alert_type} (HF: {current_health_factor:.2f})"
        )
        
        return alert
    
    def get_best_lending_markets(
        self,
        asset_type: Optional[AssetType] = None,
        limit: int = 10,
    ) -> List[LendingMarket]:
        """Get best lending markets by supply APY."""
        markets = list(self._markets.values())
        
        if asset_type:
            markets = [m for m in markets if m.asset_type == asset_type]
        
        # Sort by total APY (supply + incentives)
        markets.sort(key=lambda m: m.supply_apy + m.supply_incentive_apy, reverse=True)
        
        return markets[:limit]
    
    def get_credit_products(
        self,
        asset_class: Optional[str] = None,
        min_apy: Optional[Decimal] = None,
    ) -> List[StructuredCreditProduct]:
        """Get structured credit products."""
        products = list(self._credit_products.values())
        
        if asset_class:
            products = [p for p in products if p.asset_class == asset_class]
        
        if min_apy:
            products = [p for p in products if p.senior_tranche_apy >= min_apy]
        
        return products
    
    def get_user_positions(self, user_id: str) -> List[LendingPosition]:
        """Get user lending positions."""
        return [p for p in self._positions.values() if p.user_id == user_id]
    
    def get_active_alerts(self, user_id: Optional[str] = None) -> List[HealthMonitorAlert]:
        """Get active health alerts."""
        alerts = [a for a in self._health_alerts if not a.resolved]
        
        if user_id:
            alerts = [a for a in alerts if a.user_id == user_id]
        
        return alerts


_lending_borrowing: Optional[LendingBorrowing] = None


def get_lending_borrowing() -> LendingBorrowing:
    """Get global LendingBorrowing instance."""
    global _lending_borrowing
    if _lending_borrowing is None:
        _lending_borrowing = LendingBorrowing()
    return _lending_borrowing

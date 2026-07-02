"""
Layered Risk Caps per Asset and Cross-Asset

Implements tiered risk limits:
1. Per-asset caps: Maximum exposure per individual asset
2. Cross-asset cluster caps: Maximum exposure across correlated assets
3. System-wide caps: Maximum total exposure across all assets

Risk layers:
- Normal: Standard trading allowed
- Warning: Approaching limits, reduce size
- Critical: Near limits, halt new entries
- Breach: Limits exceeded, forced reduction
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
from decimal import Decimal

from utils.logger import get_logger

logger = get_logger("merid.risk.layered_risk_caps")


class RiskLayer(Enum):
    """Risk layer classification."""
    NORMAL = "normal"  # Within limits
    WARNING = "warning"  # Approaching limits (>70%)
    CRITICAL = "critical"  # Near limits (>90%)
    BREACH = "breach"  # Limits exceeded (>100%)


@dataclass
class AssetRiskCap:
    """Risk cap for a single asset."""
    asset: str
    max_position_usd: Decimal  # Maximum position size in USD
    max_daily_loss_usd: Decimal  # Maximum daily loss in USD
    current_position_usd: Decimal = Decimal("0")
    current_daily_loss_usd: Decimal = Decimal("0")
    
    @property
    def position_utilization(self) -> float:
        """Position utilization as percentage (0.0 to 1.0+)."""
        if self.max_position_usd == 0:
            return 0.0
        return float(self.current_position_usd / self.max_position_usd)
    
    @property
    def loss_utilization(self) -> float:
        """Loss utilization as percentage (0.0 to 1.0+)."""
        if self.max_daily_loss_usd == 0:
            return 0.0
        return float(self.current_daily_loss_usd / self.max_daily_loss_usd)
    
    @property
    def risk_layer(self) -> RiskLayer:
        """Current risk layer based on utilization."""
        max_util = max(self.position_utilization, self.loss_utilization)
        
        if max_util >= 1.0:
            return RiskLayer.BREACH
        elif max_util >= 0.9:
            return RiskLayer.CRITICAL
        elif max_util >= 0.7:
            return RiskLayer.WARNING
        else:
            return RiskLayer.NORMAL


@dataclass
class AssetCluster:
    """Cluster of correlated assets for cross-asset risk caps."""
    cluster_name: str
    assets: List[str]
    max_cluster_position_usd: Decimal  # Max position across cluster
    max_cluster_daily_loss_usd: Decimal  # Max daily loss across cluster
    current_cluster_position_usd: Decimal = Decimal("0")
    current_cluster_daily_loss_usd: Decimal = Decimal("0")
    
    @property
    def position_utilization(self) -> float:
        """Cluster position utilization as percentage."""
        if self.max_cluster_position_usd == 0:
            return 0.0
        return float(self.current_cluster_position_usd / self.max_cluster_position_usd)
    
    @property
    def loss_utilization(self) -> float:
        """Cluster loss utilization as percentage."""
        if self.max_cluster_daily_loss_usd == 0:
            return 0.0
        return float(self.current_cluster_daily_loss_usd / self.max_cluster_daily_loss_usd)
    
    @property
    def risk_layer(self) -> RiskLayer:
        """Current risk layer based on cluster utilization."""
        max_util = max(self.position_utilization, self.loss_utilization)
        
        if max_util >= 1.0:
            return RiskLayer.BREACH
        elif max_util >= 0.9:
            return RiskLayer.CRITICAL
        elif max_util >= 0.7:
            return RiskLayer.WARNING
        else:
            return RiskLayer.NORMAL


# Define asset clusters (correlated assets)
ASSET_CLUSTERS: Dict[str, AssetCluster] = {
    "BTC_ETH": AssetCluster(
        cluster_name="BTC_ETH",
        assets=["BTC", "ETH"],
        max_cluster_position_usd=Decimal("5000"),  # $5,000 max for BTC+ETH
        max_cluster_daily_loss_usd=Decimal("500"),  # $500 max daily loss
    ),
    "ALT_BASKET": AssetCluster(
        cluster_name="ALT_BASKET",
        assets=["SOL", "XRP", "DOGE"],
        max_cluster_position_usd=Decimal("3000"),  # $3,000 max for SOL+XRP+DOGE
        max_cluster_daily_loss_usd=Decimal("300"),  # $300 max daily loss
    ),
}


# Per-asset risk caps
ASSET_RISK_CAPS: Dict[str, AssetRiskCap] = {
    "BTC": AssetRiskCap(
        asset="BTC",
        max_position_usd=Decimal("3000"),  # $3,000 max
        max_daily_loss_usd=Decimal("300"),  # $300 max daily loss
    ),
    "ETH": AssetRiskCap(
        asset="ETH",
        max_position_usd=Decimal("2500"),  # $2,500 max
        max_daily_loss_usd=Decimal("250"),  # $250 max daily loss
    ),
    "SOL": AssetRiskCap(
        asset="SOL",
        max_position_usd=Decimal("1500"),  # $1,500 max
        max_daily_loss_usd=Decimal("150"),  # $150 max daily loss
    ),
    "XRP": AssetRiskCap(
        asset="XRP",
        max_position_usd=Decimal("1000"),  # $1,000 max
        max_daily_loss_usd=Decimal("100"),  # $100 max daily loss
    ),
    "DOGE": AssetRiskCap(
        asset="DOGE",
        max_position_usd=Decimal("1000"),  # $1,000 max
        max_daily_loss_usd=Decimal("100"),  # $100 max daily loss
    ),
}


@dataclass
class RiskCapCheckResult:
    """Result of a risk cap check."""
    allowed: bool
    asset: str
    position_usd: Decimal
    cap_usd: Decimal
    utilization: float
    layer: RiskLayer
    reason: str


class LayeredRiskCapManager:
    """Manager for layered risk caps."""
    
    def __init__(self):
        self.asset_caps = ASSET_RISK_CAPS
        self.asset_clusters = ASSET_CLUSTERS
        self.system_max_position_usd = Decimal("10000")  # $10,000 system-wide
        self.system_max_daily_loss_usd = Decimal("1000")  # $1,000 system-wide
        self.current_system_position_usd = Decimal("0")
        self.current_system_daily_loss_usd = Decimal("0")
    
    def check_asset_position_cap(
        self,
        asset: str,
        additional_position_usd: Decimal,
    ) -> RiskCapCheckResult:
        """Check if adding position is within per-asset cap.
        
        Args:
            asset: Asset symbol
            additional_position_usd: Additional position size in USD
        
        Returns:
            RiskCapCheckResult with decision
        """
        cap = self.asset_caps.get(asset.upper())
        if not cap:
            return RiskCapCheckResult(
                allowed=False,
                asset=asset,
                position_usd=additional_position_usd,
                cap_usd=Decimal("0"),
                utilization=0.0,
                layer=RiskLayer.BREACH,
                reason=f"No risk cap defined for asset {asset}",
            )
        
        new_position = cap.current_position_usd + additional_position_usd
        new_utilization = float(new_position / cap.max_position_usd)
        
        # Determine risk layer
        if new_utilization >= 1.0:
            layer = RiskLayer.BREACH
            allowed = False
        elif new_utilization >= 0.9:
            layer = RiskLayer.CRITICAL
            allowed = False  # Block at critical
        elif new_utilization >= 0.7:
            layer = RiskLayer.WARNING
            allowed = True  # Allow but warn
        else:
            layer = RiskLayer.NORMAL
            allowed = True
        
        return RiskCapCheckResult(
            allowed=allowed,
            asset=asset,
            position_usd=new_position,
            cap_usd=cap.max_position_usd,
            utilization=new_utilization,
            layer=layer,
            reason=f"Asset position cap: {new_utilization:.1%} of {cap.max_position_usd}",
        )
    
    def check_cluster_position_cap(
        self,
        asset: str,
        additional_position_usd: Decimal,
    ) -> RiskCapCheckResult:
        """Check if adding position is within cluster cap.
        
        Args:
            asset: Asset symbol
            additional_position_usd: Additional position size in USD
        
        Returns:
            RiskCapCheckResult with decision
        """
        # Find which cluster this asset belongs to
        cluster = None
        for cl in self.asset_clusters.values():
            if asset.upper() in cl.assets:
                cluster = cl
                break
        
        if not cluster:
            return RiskCapCheckResult(
                allowed=True,
                asset=asset,
                position_usd=additional_position_usd,
                cap_usd=Decimal("0"),
                utilization=0.0,
                layer=RiskLayer.NORMAL,
                reason=f"Asset {asset} not in any cluster",
            )
        
        new_cluster_position = cluster.current_cluster_position_usd + additional_position_usd
        new_utilization = float(new_cluster_position / cluster.max_cluster_position_usd)
        
        # Determine risk layer
        if new_utilization >= 1.0:
            layer = RiskLayer.BREACH
            allowed = False
        elif new_utilization >= 0.9:
            layer = RiskLayer.CRITICAL
            allowed = False
        elif new_utilization >= 0.7:
            layer = RiskLayer.WARNING
            allowed = True
        else:
            layer = RiskLayer.NORMAL
            allowed = True
        
        return RiskCapCheckResult(
            allowed=allowed,
            asset=asset,
            position_usd=new_cluster_position,
            cap_usd=cluster.max_cluster_position_usd,
            utilization=new_utilization,
            layer=layer,
            reason=f"Cluster {cluster.cluster_name} position cap: {new_utilization:.1%} of {cluster.max_cluster_position_usd}",
        )
    
    def check_system_position_cap(
        self,
        additional_position_usd: Decimal,
    ) -> RiskCapCheckResult:
        """Check if adding position is within system-wide cap.
        
        Args:
            additional_position_usd: Additional position size in USD
        
        Returns:
            RiskCapCheckResult with decision
        """
        new_system_position = self.current_system_position_usd + additional_position_usd
        new_utilization = float(new_system_position / self.system_max_position_usd)
        
        # Determine risk layer
        if new_utilization >= 1.0:
            layer = RiskLayer.BREACH
            allowed = False
        elif new_utilization >= 0.9:
            layer = RiskLayer.CRITICAL
            allowed = False
        elif new_utilization >= 0.7:
            layer = RiskLayer.WARNING
            allowed = True
        else:
            layer = RiskLayer.NORMAL
            allowed = True
        
        return RiskCapCheckResult(
            allowed=allowed,
            asset="SYSTEM",
            position_usd=new_system_position,
            cap_usd=self.system_max_position_usd,
            utilization=new_utilization,
            layer=layer,
            reason=f"System position cap: {new_utilization:.1%} of {self.system_max_position_usd}",
        )
    
    def check_all_caps(
        self,
        asset: str,
        additional_position_usd: Decimal,
    ) -> List[RiskCapCheckResult]:
        """Check all risk caps (asset, cluster, system).
        
        Args:
            asset: Asset symbol
            additional_position_usd: Additional position size in USD
        
        Returns:
            List of RiskCapCheckResult for each cap check
        """
        results = []
        results.append(self.check_asset_position_cap(asset, additional_position_usd))
        results.append(self.check_cluster_position_cap(asset, additional_position_usd))
        results.append(self.check_system_position_cap(additional_position_usd))
        return results
    
    def update_asset_position(self, asset: str, position_usd: Decimal) -> None:
        """Update current position for an asset.
        
        Args:
            asset: Asset symbol
            position_usd: Current position size in USD
        """
        cap = self.asset_caps.get(asset.upper())
        if cap:
            cap.current_position_usd = position_usd
            logger.debug(f"Updated {asset} position to ${position_usd}")
    
    def update_cluster_positions(self) -> None:
        """Recalculate cluster positions from asset positions."""
        for cluster in self.asset_clusters.values():
            total = Decimal("0")
            for asset in cluster.assets:
                cap = self.asset_caps.get(asset)
                if cap:
                    total += cap.current_position_usd
            cluster.current_cluster_position_usd = total
            logger.debug(f"Updated cluster {cluster.cluster_name} position to ${total}")
    
    def update_system_position(self) -> None:
        """Recalculate system position from all asset positions."""
        total = sum(cap.current_position_usd for cap in self.asset_caps.values())
        self.current_system_position_usd = total
        logger.debug(f"Updated system position to ${total}")


def get_risk_cap_manager() -> LayeredRiskCapManager:
    """Get the layered risk cap manager singleton."""
    global _manager
    if _manager is None:
        _manager = LayeredRiskCapManager()
    return _manager


_manager: Optional[LayeredRiskCapManager] = None

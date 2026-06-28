"""Tests for layered risk caps per asset and cross-asset."""
import pytest
from decimal import Decimal

from merid.risk.layered_risk_caps import (
    RiskLayer,
    AssetRiskCap,
    AssetCluster,
    ASSET_CLUSTERS,
    ASSET_RISK_CAPS,
    RiskCapCheckResult,
    LayeredRiskCapManager,
    get_risk_cap_manager,
)


class TestAssetRiskCap:
    """Test asset risk cap."""
    
    def test_btc_cap_defined(self):
        """Test BTC risk cap is defined."""
        assert "BTC" in ASSET_RISK_CAPS
        cap = ASSET_RISK_CAPS["BTC"]
        assert cap.asset == "BTC"
        assert cap.max_position_usd == Decimal("3000")
    
    def test_position_utilization(self):
        """Test position utilization calculation."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_position_usd=Decimal("500"),
        )
        assert cap.position_utilization == 0.5
    
    def test_loss_utilization(self):
        """Test loss utilization calculation."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_daily_loss_usd=Decimal("50"),
        )
        assert cap.loss_utilization == 0.5
    
    def test_risk_layer_normal(self):
        """Test risk layer classification for normal."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_position_usd=Decimal("500"),
        )
        assert cap.risk_layer == RiskLayer.NORMAL
    
    def test_risk_layer_warning(self):
        """Test risk layer classification for warning."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_position_usd=Decimal("750"),
        )
        assert cap.risk_layer == RiskLayer.WARNING
    
    def test_risk_layer_critical(self):
        """Test risk layer classification for critical."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_position_usd=Decimal("950"),
        )
        assert cap.risk_layer == RiskLayer.CRITICAL
    
    def test_risk_layer_breach(self):
        """Test risk layer classification for breach."""
        cap = AssetRiskCap(
            asset="BTC",
            max_position_usd=Decimal("1000"),
            max_daily_loss_usd=Decimal("100"),
            current_position_usd=Decimal("1100"),
        )
        assert cap.risk_layer == RiskLayer.BREACH


class TestAssetCluster:
    """Test asset cluster."""
    
    def test_btc_eth_cluster_defined(self):
        """Test BTC_ETH cluster is defined."""
        assert "BTC_ETH" in ASSET_CLUSTERS
        cluster = ASSET_CLUSTERS["BTC_ETH"]
        assert cluster.cluster_name == "BTC_ETH"
        assert "BTC" in cluster.assets
        assert "ETH" in cluster.assets
    
    def test_alt_basket_cluster_defined(self):
        """Test ALT_BASKET cluster is defined."""
        assert "ALT_BASKET" in ASSET_CLUSTERS
        cluster = ASSET_CLUSTERS["ALT_BASKET"]
        assert cluster.cluster_name == "ALT_BASKET"
        assert "SOL" in cluster.assets
        assert "XRP" in cluster.assets
        assert "DOGE" in cluster.assets
    
    def test_cluster_position_utilization(self):
        """Test cluster position utilization."""
        cluster = AssetCluster(
            cluster_name="TEST",
            assets=["BTC", "ETH"],
            max_cluster_position_usd=Decimal("5000"),
            max_cluster_daily_loss_usd=Decimal("500"),
            current_cluster_position_usd=Decimal("2500"),
        )
        assert cluster.position_utilization == 0.5


class TestLayeredRiskCapManager:
    """Test layered risk cap manager."""
    
    def test_check_asset_position_cap_normal(self):
        """Test asset position cap check in normal regime."""
        manager = LayeredRiskCapManager()
        result = manager.check_asset_position_cap("BTC", Decimal("1000"))
        assert result.allowed == True
        assert result.layer == RiskLayer.NORMAL
    
    def test_check_asset_position_cap_warning(self):
        """Test asset position cap check in warning regime."""
        manager = LayeredRiskCapManager()
        # BTC max is 3000, 2500 should be warning
        result = manager.check_asset_position_cap("BTC", Decimal("2500"))
        assert result.allowed == True
        assert result.layer == RiskLayer.WARNING
    
    def test_check_asset_position_cap_critical(self):
        """Test asset position cap check in critical regime."""
        manager = LayeredRiskCapManager()
        # BTC max is 3000, 2900 should be critical and blocked
        result = manager.check_asset_position_cap("BTC", Decimal("2900"))
        assert result.allowed == False
        assert result.layer == RiskLayer.CRITICAL
    
    def test_check_asset_position_cap_breach(self):
        """Test asset position cap check in breach regime."""
        manager = LayeredRiskCapManager()
        # BTC max is 3000, 3500 should be breach and blocked
        result = manager.check_asset_position_cap("BTC", Decimal("3500"))
        assert result.allowed == False
        assert result.layer == RiskLayer.BREACH
    
    def test_check_asset_position_cap_unknown_asset(self):
        """Test asset position cap check for unknown asset."""
        manager = LayeredRiskCapManager()
        result = manager.check_asset_position_cap("UNKNOWN", Decimal("100"))
        assert result.allowed == False
        assert result.layer == RiskLayer.BREACH
    
    def test_check_cluster_position_cap_normal(self):
        """Test cluster position cap check in normal regime."""
        manager = LayeredRiskCapManager()
        result = manager.check_cluster_position_cap("BTC", Decimal("1000"))
        assert result.allowed == True
        assert result.layer == RiskLayer.NORMAL
    
    def test_check_cluster_position_cap_critical(self):
        """Test cluster position cap check in critical regime."""
        manager = LayeredRiskCapManager()
        # BTC_ETH cluster max is 5000, 4800 should be critical
        result = manager.check_cluster_position_cap("BTC", Decimal("4800"))
        assert result.allowed == False
        assert result.layer == RiskLayer.CRITICAL
    
    def test_check_cluster_position_cap_no_cluster(self):
        """Test cluster position cap check for asset not in cluster."""
        manager = LayeredRiskCapManager()
        result = manager.check_cluster_position_cap("UNKNOWN", Decimal("100"))
        assert result.allowed == True  # No cluster = no restriction
        assert result.layer == RiskLayer.NORMAL
    
    def test_check_system_position_cap_normal(self):
        """Test system position cap check in normal regime."""
        manager = LayeredRiskCapManager()
        result = manager.check_system_position_cap(Decimal("1000"))
        assert result.allowed == True
        assert result.layer == RiskLayer.NORMAL
    
    def test_check_system_position_cap_critical(self):
        """Test system position cap check in critical regime."""
        manager = LayeredRiskCapManager()
        # System max is 10000, 9500 should be critical
        result = manager.check_system_position_cap(Decimal("9500"))
        assert result.allowed == False
        assert result.layer == RiskLayer.CRITICAL
    
    def test_check_all_caps(self):
        """Test checking all caps at once."""
        manager = LayeredRiskCapManager()
        results = manager.check_all_caps("BTC", Decimal("1000"))
        assert len(results) == 3  # asset, cluster, system
        assert all(r.asset in ["BTC", "BTC_ETH", "SYSTEM"] for r in results)
    
    def test_update_asset_position(self):
        """Test updating asset position."""
        manager = LayeredRiskCapManager()
        manager.update_asset_position("BTC", Decimal("1500"))
        cap = manager.asset_caps["BTC"]
        assert cap.current_position_usd == Decimal("1500")
    
    def test_update_cluster_positions(self):
        """Test updating cluster positions."""
        manager = LayeredRiskCapManager()
        manager.update_asset_position("BTC", Decimal("1000"))
        manager.update_asset_position("ETH", Decimal("500"))
        manager.update_cluster_positions()
        cluster = manager.asset_clusters["BTC_ETH"]
        assert cluster.current_cluster_position_usd == Decimal("1500")
    
    def test_update_system_position(self):
        """Test updating system position."""
        manager = LayeredRiskCapManager()
        manager.update_asset_position("BTC", Decimal("1000"))
        manager.update_asset_position("ETH", Decimal("500"))
        manager.update_system_position()
        assert manager.current_system_position_usd == Decimal("1500")


class TestRiskCapManagerSingleton:
    """Test risk cap manager singleton."""
    
    def test_get_risk_cap_manager(self):
        """Test singleton pattern."""
        manager1 = get_risk_cap_manager()
        manager2 = get_risk_cap_manager()
        
        assert manager1 is manager2

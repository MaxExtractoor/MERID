"""Tests for per-asset microstructure invariants."""
import pytest

from merid.event_venues.kalshi.microstructure_invariants import (
    AssetClass,
    MicrostructureThresholds,
    ASSET_THRESHOLDS,
    InvariantViolation,
    MicrostructureInvariantChecker,
    get_microstructure_checker,
)


class TestAssetThresholds:
    """Test asset-specific threshold definitions."""
    
    def test_btc_thresholds_defined(self):
        """Test BTC thresholds are defined."""
        assert "BTC" in ASSET_THRESHOLDS
        thresholds = ASSET_THRESHOLDS["BTC"]
        assert thresholds.asset == "BTC"
        assert thresholds.asset_class == AssetClass.HIGH_LIQUIDITY
        assert thresholds.max_spread_normal == 5
        assert thresholds.min_depth_yes == 100
    
    def test_eth_thresholds_defined(self):
        """Test ETH thresholds are defined."""
        assert "ETH" in ASSET_THRESHOLDS
        thresholds = ASSET_THRESHOLDS["ETH"]
        assert thresholds.asset == "ETH"
        assert thresholds.asset_class == AssetClass.HIGH_LIQUIDITY
    
    def test_sol_thresholds_defined(self):
        """Test SOL thresholds are defined."""
        assert "SOL" in ASSET_THRESHOLDS
        thresholds = ASSET_THRESHOLDS["SOL"]
        assert thresholds.asset == "SOL"
        assert thresholds.asset_class == AssetClass.MEDIUM_LIQUIDITY
        assert thresholds.max_spread_normal == 8  # Wider than BTC/ETH
    
    def test_xrp_thresholds_defined(self):
        """Test XRP thresholds are defined."""
        assert "XRP" in ASSET_THRESHOLDS
        thresholds = ASSET_THRESHOLDS["XRP"]
        assert thresholds.asset == "XRP"
        assert thresholds.asset_class == AssetClass.LOW_LIQUIDITY
        assert thresholds.max_spread_normal == 10  # Widest
    
    def test_doge_thresholds_defined(self):
        """Test DOGE thresholds are defined."""
        assert "DOGE" in ASSET_THRESHOLDS
        thresholds = ASSET_THRESHOLDS["DOGE"]
        assert thresholds.asset == "DOGE"
        assert thresholds.asset_class == AssetClass.LOW_LIQUIDITY
    
    def test_all_crypto_assets_covered(self):
        """Test all 5 crypto assets have thresholds."""
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in expected_assets:
            assert asset in ASSET_THRESHOLDS, f"Missing thresholds for {asset}"


class TestMicrostructureInvariantChecker:
    """Test microstructure invariant checker."""
    
    def test_get_thresholds(self):
        """Test getting thresholds for an asset."""
        checker = MicrostructureInvariantChecker()
        thresholds = checker.get_thresholds("BTC")
        assert thresholds is not None
        assert thresholds.asset == "BTC"
    
    def test_get_thresholds_unknown_asset(self):
        """Test getting thresholds for unknown asset."""
        checker = MicrostructureInvariantChecker()
        thresholds = checker.get_thresholds("UNKNOWN")
        assert thresholds is None
    
    def test_check_spread_invariant_pass(self):
        """Test spread invariant check when within threshold."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_spread_invariant("BTC", spread_cents=3, regime="normal")
        assert violation.violated == False
        assert "within" in violation.message.lower()
    
    def test_check_spread_invariant_fail(self):
        """Test spread invariant check when exceeding threshold."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_spread_invariant("BTC", spread_cents=10, regime="normal")
        assert violation.violated == True
        assert "exceeds" in violation.message.lower()
        assert violation.severity == "error"
    
    def test_check_spread_invariant_tight_regime(self):
        """Test spread invariant with tight regime."""
        checker = MicrostructureInvariantChecker()
        # BTC tight regime max is 2 cents
        violation = checker.check_spread_invariant("BTC", spread_cents=3, regime="tight")
        assert violation.violated == True
    
    def test_check_spread_invariant_wide_regime(self):
        """Test spread invariant with wide regime."""
        checker = MicrostructureInvariantChecker()
        # BTC wide regime max is 10 cents
        violation = checker.check_spread_invariant("BTC", spread_cents=8, regime="wide")
        assert violation.violated == False
    
    def test_check_depth_invariant_pass(self):
        """Test depth invariant check when within threshold."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_depth_invariant("BTC", depth_yes=150, depth_no=75)
        assert violation.violated == False
        assert "meets" in violation.message.lower()
    
    def test_check_depth_invariant_fail_yes(self):
        """Test depth invariant check when YES depth too low."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_depth_invariant("BTC", depth_yes=50, depth_no=75)
        assert violation.violated == True
        assert "below" in violation.message.lower()
    
    def test_check_depth_invariant_fail_no(self):
        """Test depth invariant check when NO depth too low."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_depth_invariant("BTC", depth_yes=150, depth_no=25)
        assert violation.violated == True
    
    def test_check_volatility_invariant_pass(self):
        """Test volatility invariant check when within threshold."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_volatility_invariant("BTC", realized_vol_15m=0.05, price_range_15m=0.03)
        assert violation.violated == False
    
    def test_check_volatility_invariant_fail_vol(self):
        """Test volatility invariant check when vol too high."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_volatility_invariant("BTC", realized_vol_15m=0.10, price_range_15m=0.03)
        assert violation.violated == True
        assert "realized_vol" in violation.message
    
    def test_check_volatility_invariant_fail_range(self):
        """Test volatility invariant check when price range too high."""
        checker = MicrostructureInvariantChecker()
        violation = checker.check_volatility_invariant("BTC", realized_vol_15m=0.05, price_range_15m=0.08)
        assert violation.violated == True
        assert "price_range" in violation.message
    
    def test_check_all_invariants_pass(self):
        """Test checking all invariants when all pass."""
        checker = MicrostructureInvariantChecker()
        violations = checker.check_all_invariants(
            asset="BTC",
            spread_cents=3,
            depth_yes=150,
            depth_no=75,
            realized_vol_15m=0.05,
            price_range_15m=0.03,
            regime="normal",
        )
        assert len(violations) == 3  # spread, depth, volatility
        assert all(not v.violated for v in violations)
    
    def test_check_all_invariants_fail(self):
        """Test checking all invariants when some fail."""
        checker = MicrostructureInvariantChecker()
        violations = checker.check_all_invariants(
            asset="BTC",
            spread_cents=15,  # Too wide
            depth_yes=50,  # Too shallow
            depth_no=75,
            realized_vol_15m=0.10,  # Too high
            price_range_15m=0.03,
            regime="normal",
        )
        assert len(violations) == 3
        # At least spread and depth should fail
        assert violations[0].violated == True  # spread
        assert violations[1].violated == True  # depth
    
    def test_asset_specific_thresholds(self):
        """Test that different assets have different thresholds."""
        checker = MicrostructureInvariantChecker()
        
        # BTC (high liquidity) should allow tighter spread than XRP (low liquidity)
        btc_violation = checker.check_spread_invariant("BTC", spread_cents=6, regime="normal")
        xrp_violation = checker.check_spread_invariant("XRP", spread_cents=6, regime="normal")
        
        # 6 cents should violate for BTC (max 5) but not for XRP (max 10)
        assert btc_violation.violated == True
        assert xrp_violation.violated == False


class TestMicrostructureCheckerSingleton:
    """Test microstructure checker singleton."""
    
    def test_get_microstructure_checker(self):
        """Test singleton pattern."""
        checker1 = get_microstructure_checker()
        checker2 = get_microstructure_checker()
        
        assert checker1 is checker2

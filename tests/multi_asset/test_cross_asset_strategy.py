"""Tests for multi_asset/cross_asset_strategy.py - Cross-Asset Strategy."""
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from multi_asset.cross_asset_strategy import (
    StrategyType,
    SignalStrength,
    CrossAssetSignal,
    AssetRotationSignal,
    PairsTradingSignal,
    CrossAssetStrategyEngine,
)


class TestStrategyType:
    """Test StrategyType enum."""

    def test_asset_rotation(self):
        """Test asset rotation strategy type."""
        assert StrategyType.ASSET_ROTATION.value == "asset_rotation"

    def test_statistical_arbitrage(self):
        """Test statistical arbitrage strategy type."""
        assert StrategyType.STATISTICAL_ARBITRAGE.value == "statistical_arbitrage"

    def test_pairs_trading(self):
        """Test pairs trading strategy type."""
        assert StrategyType.PAIRS_TRADING.value == "pairs_trading"

    def test_momentum_rotation(self):
        """Test momentum rotation strategy type."""
        assert StrategyType.MOMENTUM_ROTATION.value == "momentum_rotation"

    def test_risk_parity(self):
        """Test risk parity strategy type."""
        assert StrategyType.RISK_PARITY.value == "risk_parity"


class TestSignalStrength:
    """Test SignalStrength enum."""

    def test_very_strong_signal(self):
        """Test very strong signal."""
        assert SignalStrength.VERY_STRONG.value == 5

    def test_strong_signal(self):
        """Test strong signal."""
        assert SignalStrength.STRONG.value == 4

    def test_moderate_signal(self):
        """Test moderate signal."""
        assert SignalStrength.MODERATE.value == 3

    def test_weak_signal(self):
        """Test weak signal."""
        assert SignalStrength.WEAK.value == 2

    def test_signal_ordering(self):
        """Test signal strength ordering."""
        assert SignalStrength.VERY_STRONG.value > SignalStrength.STRONG.value
        assert SignalStrength.STRONG.value > SignalStrength.MODERATE.value


class TestCrossAssetSignal:
    """Test CrossAssetSignal dataclass."""

    def test_long_signal(self):
        """Test long cross-asset signal."""
        signal = CrossAssetSignal(
            signal_id="sig_001",
            strategy_type=StrategyType.MOMENTUM_ROTATION,
            symbols=["BTC/USD", "ETH/USD"],
            signal_type="long",
            strength=SignalStrength.STRONG,
            confidence=0.85,
            expected_return=0.15,
            risk_score=0.3,
            holding_period=7,
            entry_price={"BTC/USD": 50000, "ETH/USD": 3000},
            stop_loss={"BTC/USD": 47500, "ETH/USD": 2850},
            take_profit={"BTC/USD": 55000, "ETH/USD": 3300},
            position_sizes={"BTC/USD": 0.6, "ETH/USD": 0.4},
            correlation_risk=0.75,
            timestamp=1000.0,
        )
        assert signal.signal_type == "long"
        assert signal.confidence == 0.85

    def test_short_signal(self):
        """Test short cross-asset signal."""
        signal = CrossAssetSignal(
            signal_id="sig_002",
            strategy_type=StrategyType.MEAN_REVERSION,
            symbols=["AAPL", "MSFT"],
            signal_type="short",
            strength=SignalStrength.MODERATE,
            confidence=0.70,
            expected_return=0.08,
            risk_score=0.5,
            holding_period=3,
            entry_price={"AAPL": 175, "MSFT": 380},
            stop_loss={"AAPL": 182, "MSFT": 395},
            take_profit={"AAPL": 165, "MSFT": 360},
            position_sizes={"AAPL": 0.5, "MSFT": 0.5},
            correlation_risk=0.85,
            timestamp=1000.0,
        )
        assert signal.signal_type == "short"
        assert len(signal.symbols) == 2


class TestAssetRotationSignal:
    """Test AssetRotationSignal dataclass."""

    def test_rotation_to_equities(self):
        """Test rotation signal to equities."""
        signal = AssetRotationSignal(
            signal_id="rot_001",
            asset_classes=["equity", "fixed_income", "commodity"],
            recommended_allocation={"equity": 0.60, "fixed_income": 0.30, "commodity": 0.10},
            current_allocation={"equity": 0.40, "fixed_income": 0.40, "commodity": 0.20},
            rotation_reason="Strong equity momentum",
            momentum_score=0.75,
            risk_adjusted_score=1.2,
            expected_return=0.12,
            risk_score=0.35,
            rebalance_urgency="high",
            timestamp=1000.0,
        )
        assert signal.recommended_allocation["equity"] > signal.current_allocation["equity"]
        assert signal.rebalance_urgency == "high"

    def test_defensive_rotation(self):
        """Test defensive rotation signal."""
        signal = AssetRotationSignal(
            signal_id="rot_002",
            asset_classes=["equity", "fixed_income", "cash"],
            recommended_allocation={"equity": 0.20, "fixed_income": 0.50, "cash": 0.30},
            current_allocation={"equity": 0.60, "fixed_income": 0.30, "cash": 0.10},
            rotation_reason="Market downturn expected",
            momentum_score=-0.5,
            risk_adjusted_score=0.3,
            expected_return=0.03,
            risk_score=0.15,
            rebalance_urgency="urgent",
            timestamp=1000.0,
        )
        assert signal.recommended_allocation["equity"] < signal.current_allocation["equity"]
        assert signal.recommended_allocation["cash"] > signal.current_allocation["cash"]


class TestPairsTradingSignal:
    """Test PairsTradingSignal dataclass."""

    def test_long_short_pair(self):
        """Test long-short pairs trading signal."""
        signal = PairsTradingSignal(
            signal_id="pair_001",
            pair=("AAPL", "MSFT"),
            spread=5.5,
            z_score=2.1,
            signal_type="long_short",
            entry_ratio=0.46,
            stop_loss_ratio=0.50,
            take_profit_ratio=0.40,
            half_life=5.0,
            correlation=0.92,
            confidence=0.80,
            expected_return=0.05,
            holding_period=10,
            timestamp=1000.0,
        )
        assert signal.signal_type == "long_short"
        assert signal.z_score > 2.0

    def test_short_long_pair(self):
        """Test short-long pairs trading signal."""
        signal = PairsTradingSignal(
            signal_id="pair_002",
            pair=("BTC/USD", "ETH/USD"),
            spread=-3.2,
            z_score=-2.3,
            signal_type="short_long",
            entry_ratio=16.5,
            stop_loss_ratio=18.0,
            take_profit_ratio=15.0,
            half_life=3.0,
            correlation=0.85,
            confidence=0.75,
            expected_return=0.08,
            holding_period=5,
            timestamp=1000.0,
        )
        assert signal.signal_type == "short_long"
        assert signal.z_score < -2.0


class TestCrossAssetStrategyEngine:
    """Test CrossAssetStrategyEngine class."""

    @pytest.fixture
    def engine_config(self):
        """Create engine config."""
        return {
            "max_signals": 100,
            "min_confidence": 0.6,
            "risk_limit": 0.5,
        }

    @pytest.fixture
    def strategy_engine(self, engine_config):
        """Create strategy engine instance."""
        return CrossAssetStrategyEngine(engine_config)

    def test_engine_creation(self, strategy_engine):
        """Test creating engine."""
        assert strategy_engine is not None
        assert strategy_engine.strategies == {}

    def test_register_strategy(self, strategy_engine):
        """Test registering a strategy."""
        strategy = {
            "name": "momentum_rotation",
            "type": StrategyType.MOMENTUM_ROTATION,
            "params": {"lookback": 20, "threshold": 0.05},
        }
        strategy_engine.strategies["momentum_rotation"] = strategy
        
        assert "momentum_rotation" in strategy_engine.strategies

    def test_signal_history(self, strategy_engine):
        """Test signal history storage."""
        assert hasattr(strategy_engine, 'signal_history')
        assert strategy_engine.signal_history.maxlen == 1000

    def test_active_signals(self, strategy_engine):
        """Test active signals tracking."""
        signal = CrossAssetSignal(
            signal_id="test_sig",
            strategy_type=StrategyType.PAIRS_TRADING,
            symbols=["A", "B"],
            signal_type="long",
            strength=SignalStrength.STRONG,
            confidence=0.8,
            expected_return=0.1,
            risk_score=0.3,
            holding_period=5,
            entry_price={"A": 100, "B": 50},
            stop_loss={"A": 95, "B": 47},
            take_profit={"A": 110, "B": 55},
            position_sizes={"A": 0.5, "B": 0.5},
            correlation_risk=0.7,
            timestamp=1000.0,
        )
        strategy_engine.active_signals["test_sig"] = signal
        
        assert "test_sig" in strategy_engine.active_signals


class TestPairsTradingLogic:
    """Test pairs trading logic."""

    def test_spread_calculation(self):
        """Test spread calculation."""
        price_a = 100.0
        price_b = 50.0
        hedge_ratio = 2.0
        
        spread = price_a - hedge_ratio * price_b
        
        assert spread == 0.0

    def test_z_score_calculation(self):
        """Test Z-score calculation."""
        spreads = np.array([1.0, 2.0, 1.5, 3.0, 2.5, 4.0, 3.5, 5.0])
        
        mean_spread = np.mean(spreads)
        std_spread = np.std(spreads)
        current_spread = 5.5
        
        z_score = (current_spread - mean_spread) / std_spread
        
        assert z_score > 1.0  # Above mean

    def test_cointegration_check(self):
        """Test cointegration-like check (simplified)."""
        np.random.seed(42)
        n = 100
        
        # Generate cointegrated series
        x = np.cumsum(np.random.randn(n))
        y = x + np.random.randn(n) * 0.5
        
        # Check correlation as proxy
        correlation = np.corrcoef(x, y)[0, 1]
        
        assert correlation > 0.9

    def test_half_life_estimation(self):
        """Test half-life estimation."""
        # Simplified half-life calculation
        mean_reversion_speed = 0.1  # 10% per period
        
        half_life = np.log(2) / mean_reversion_speed
        
        assert half_life == pytest.approx(6.93, rel=0.01)


class TestAssetRotationLogic:
    """Test asset rotation logic."""

    def test_momentum_score_calculation(self):
        """Test momentum score calculation."""
        returns = {
            "equity": 0.15,
            "fixed_income": 0.03,
            "commodity": 0.08,
        }
        
        # Rank-based momentum score
        sorted_assets = sorted(returns.items(), key=lambda x: x[1], reverse=True)
        ranks = {asset: i+1 for i, (asset, _) in enumerate(sorted_assets)}
        
        assert ranks["equity"] == 1
        assert ranks["fixed_income"] == 3

    def test_risk_adjusted_allocation(self):
        """Test risk-adjusted allocation."""
        returns = {"equity": 0.12, "fixed_income": 0.04, "commodity": 0.08}
        volatilities = {"equity": 0.20, "fixed_income": 0.05, "commodity": 0.15}
        
        # Sharpe-like ratio
        sharpe = {k: returns[k] / volatilities[k] for k in returns}
        
        # Risk parity allocation (simplified)
        inv_vol = {k: 1 / volatilities[k] for k in volatilities}
        total_inv_vol = sum(inv_vol.values())
        allocation = {k: v / total_inv_vol for k, v in inv_vol.items()}
        
        # Fixed income should have highest weight (lowest vol)
        assert allocation["fixed_income"] > allocation["equity"]

    def test_rebalance_threshold(self):
        """Test rebalance threshold check."""
        target = {"equity": 0.60, "fixed_income": 0.30, "commodity": 0.10}
        current = {"equity": 0.65, "fixed_income": 0.25, "commodity": 0.10}
        threshold = 0.05
        
        needs_rebalance = any(
            abs(target[k] - current[k]) > threshold 
            for k in target
        )
        
        assert needs_rebalance is True


class TestRiskParityStrategy:
    """Test risk parity strategy logic."""

    def test_equal_risk_contribution(self):
        """Test equal risk contribution calculation."""
        weights = np.array([0.5, 0.3, 0.2])
        volatilities = np.array([0.20, 0.15, 0.25])
        
        # Risk contribution (simplified)
        weighted_vol = weights * volatilities
        total_risk = np.sum(weighted_vol)
        risk_contrib = weighted_vol / total_risk
        
        # In risk parity, we want equal contributions
        target_contrib = 1 / len(weights)
        
        # Check deviation from equal
        max_deviation = max(abs(rc - target_contrib) for rc in risk_contrib)
        assert max_deviation > 0  # Current allocation is not risk parity

    def test_inverse_volatility_weights(self):
        """Test inverse volatility weighting."""
        volatilities = {"A": 0.20, "B": 0.10, "C": 0.40}
        
        inv_vol = {k: 1 / v for k, v in volatilities.items()}
        total = sum(inv_vol.values())
        weights = {k: v / total for k, v in inv_vol.items()}
        
        # B (lowest vol) should have highest weight
        assert weights["B"] > weights["A"] > weights["C"]
        assert sum(weights.values()) == pytest.approx(1.0)

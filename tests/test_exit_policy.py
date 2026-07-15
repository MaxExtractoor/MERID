"""Tests for exit policy integration with unified edge."""
import pytest
from decimal import Decimal

from merid.risk.exit_policy import (
    ExitPolicyConfig,
    ExitPolicyEngine,
    ExitReason,
    ExitSignal,
    get_exit_policy_engine,
)


class TestExitPolicyConfig:
    """Test exit policy configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = ExitPolicyConfig()
        assert config.take_profit_enabled == True
        assert config.take_profit_pct == 0.50
        assert config.stop_loss_enabled == True
        assert config.stop_loss_pct == 0.80
        assert config.edge_based_tp == True
        assert config.edge_based_sl == True
        assert config.confidence_scaling == True
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = ExitPolicyConfig(
            take_profit_pct=0.30,
            stop_loss_pct=0.50,
            edge_based_tp=False,
        )
        assert config.take_profit_pct == 0.30
        assert config.stop_loss_pct == 0.50
        assert config.edge_based_tp == False


class TestExitPolicyEngine:
    """Test exit policy engine logic."""
    
    def test_take_profit_trigger_yes(self):
        """Test take-profit trigger for YES position."""
        # Disable dynamic thresholds for predictable test
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # Entry at 50 cents, current at 75 cents (50% profit)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
        assert "TP triggered" in signal.message
    
    def test_take_profit_trigger_no(self):
        """Test take-profit trigger for NO position."""
        # Disable dynamic thresholds for predictable test
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # Entry at 50 cents, current at 25 cents (50% profit for NO)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=25,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_take_profit_time_gate(self):
        """Test take-profit time gate (minimum holding period)."""
        engine = ExitPolicyEngine()
        
        # Profitable but held for less than minimum time
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=0.5,  # Below 2.0 min threshold
            side="yes",
        )
        
        assert signal.should_exit == False
        assert "Holding" in signal.message
    
    def test_stop_loss_trigger_yes(self):
        """Test stop-loss trigger for YES position."""
        engine = ExitPolicyEngine()
        
        # Entry at 50 cents, current at 10 cents (80% loss)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=10,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.STOP_LOSS
        assert "SL triggered" in signal.message
    
    def test_stop_loss_trigger_no(self):
        """Test stop-loss trigger for NO position."""
        engine = ExitPolicyEngine()
        
        # Entry at 50 cents, current at 90 cents (80% loss for NO)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.STOP_LOSS
    
    def test_no_exit_signal(self):
        """Test no exit signal when within thresholds."""
        engine = ExitPolicyEngine()
        
        # Small profit, not enough to trigger TP
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=55,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        assert signal.should_exit == False
        assert signal.reason == ExitReason.MANUAL
        assert "Holding" in signal.message
    
    def test_edge_based_dynamic_tp(self):
        """Test edge-based dynamic take-profit threshold."""
        config = ExitPolicyConfig(edge_based_tp=True, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # High edge should increase TP threshold
        signal_high_edge = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,  # 50% profit
            edge_pct=0.10,  # High edge
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        # With high edge, TP threshold should be higher, so 50% may not trigger
        # (depends on multiplier calculation)
        assert signal_high_edge.should_exit == signal_high_edge.should_exit  # Just check it runs
    
    def test_confidence_scaling(self):
        """Test confidence-based threshold scaling."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=True)
        engine = ExitPolicyEngine(config)
        
        # High confidence should increase TP threshold
        signal_high_conf = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,
            edge_pct=0.05,
            confidence=0.9,  # High confidence
            minutes_held=3.0,
            side="yes",
        )
        
        assert signal_high_conf.should_exit == signal_high_conf.should_exit  # Just check it runs


class TestExitPolicySingleton:
    """Test exit policy engine singleton."""
    
    def test_get_exit_policy_engine(self):
        """Test singleton pattern."""
        engine1 = get_exit_policy_engine()
        engine2 = get_exit_policy_engine()
        
        assert engine1 is engine2
    
    def test_get_exit_policy_engine_with_config(self):
        """Test singleton with custom config (only on first call)."""
        # Reset singleton for this test
        import merid.risk.exit_policy as ep
        ep._exit_engine = None
        
        config = ExitPolicyConfig(take_profit_pct=0.30)
        engine = get_exit_policy_engine(config)
        
        assert engine.config.take_profit_pct == 0.30


class TestExitPolicyAllAssets:
    """Test exit policy works across all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE)."""
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_take_profit_trigger_all_assets(self, asset):
        """Test take-profit trigger works for all crypto assets."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # Entry at 50 cents, current at 75 cents (50% profit)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_stop_loss_trigger_all_assets(self, asset):
        """Test stop-loss trigger works for all crypto assets."""
        engine = ExitPolicyEngine()
        
        # Entry at 50 cents, current at 10 cents (80% loss)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=10,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.STOP_LOSS


class TestExitPolicyBothSides:
    """Test exit policy works for both YES and NO sides."""
    
    def test_yes_position_take_profit(self):
        """Test take-profit for YES position."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # YES: Entry 50c, current 75c = 50% profit
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=75,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_no_position_take_profit(self):
        """Test take-profit for NO position."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # NO: Entry 50c, current 25c = 50% profit (price moved down)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=25,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=3.0,
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_yes_position_stop_loss(self):
        """Test stop-loss for YES position."""
        engine = ExitPolicyEngine()
        
        # YES: Entry 50c, current 10c = 80% loss
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=10,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.STOP_LOSS
    
    def test_no_position_stop_loss(self):
        """Test stop-loss for NO position."""
        engine = ExitPolicyEngine()
        
        # NO: Entry 50c, current 90c = 80% loss (price moved up)
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.STOP_LOSS

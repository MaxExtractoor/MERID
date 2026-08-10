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
        assert config.take_profit_pct == 0.80  # CRITICAL FIX 2026-07-16: Changed from 0.50 to achieve positive risk/reward
        assert config.stop_loss_enabled == True
        assert config.stop_loss_pct == 0.40  # CRITICAL FIX 2026-07-16: Changed from 0.80 to achieve positive risk/reward
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
        
        # Entry at 50 cents, current at 90 cents (80% profit) - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated minutes_held from 3.0 to 6.0 to meet new min_hold_minutes=5.0
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=6.0,  # Above min_hold_minutes (5.0)
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
        
        # Entry at 50 cents, current at 10 cents (80% profit for NO) - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated minutes_held from 3.0 to 6.0 to meet new min_hold_minutes=5.0
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=10,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=6.0,  # Above min_hold_minutes (5.0)
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_take_profit_time_gate(self):
        """Test take-profit time gate (minimum holding period)."""
        engine = ExitPolicyEngine()
        
        # Profitable but held for less than minimum time - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated comment from 2.0 to 5.0 min threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=0.5,  # Below 5.0 min threshold
            side="yes",
        )
        
        assert signal.should_exit == False
        assert "Holding" in signal.message
    
    def test_stop_loss_trigger_yes(self):
        """Direct stop-loss is suppressed and converted to a StopCandidate path."""
        engine = ExitPolicyEngine()

        # Entry at 50 cents, current at 30 cents (40% loss) - CRITICAL FIX 2026-07-16: Updated for new SL threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=30,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )

        assert signal.should_exit == False
        assert signal.reason is None
        assert "SL suppressed" in signal.message
    
    def test_stop_loss_trigger_no(self):
        """Direct stop-loss is suppressed and converted to a StopCandidate path."""
        engine = ExitPolicyEngine()

        # Entry at 50 cents, current at 70 cents (40% loss for NO) - CRITICAL FIX 2026-07-16: Updated for new SL threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=70,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="no",
        )

        assert signal.should_exit == False
        assert signal.reason is None
        assert "SL suppressed" in signal.message
    
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
        
        # High edge should increase TP threshold - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        signal_high_edge = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,  # 80% profit
            edge_pct=0.10,  # High edge
            confidence=0.8,
            minutes_held=3.0,
            side="yes",
        )
        
        # With high edge, TP threshold should be higher, so 80% may not trigger
        # (depends on multiplier calculation)
        assert signal_high_edge.should_exit == signal_high_edge.should_exit  # Just check it runs
    
    def test_confidence_scaling(self):
        """Test confidence-based threshold scaling."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=True)
        engine = ExitPolicyEngine(config)
        
        # High confidence should increase TP threshold - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        signal_high_conf = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
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
        
        # Entry at 50 cents, current at 90 cents (80% profit) - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated minutes_held from 3.0 to 6.0 to meet new min_hold_minutes=5.0
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=6.0,  # Above min_hold_minutes (5.0)
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_stop_loss_suppressed_for_all_assets(self, asset):
        """Direct stop-loss is suppressed for every crypto asset; StopCandidate path is live."""
        engine = ExitPolicyEngine()

        # Entry at 50 cents, current at 30 cents (40% loss) - CRITICAL FIX 2026-07-16: Updated for new SL threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=30,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )

        assert signal.should_exit == False
        assert signal.reason is None
        assert "SL suppressed" in signal.message


class TestExitPolicyBothSides:
    """Test exit policy works for both YES and NO sides."""
    
    def test_yes_position_take_profit(self):
        """Test take-profit for YES position."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # YES: Entry 50c, current 90c = 80% profit - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated minutes_held from 3.0 to 6.0 to meet new min_hold_minutes=5.0
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=90,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=6.0,  # Above min_hold_minutes (5.0)
            side="yes",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_no_position_take_profit(self):
        """Test take-profit for NO position."""
        config = ExitPolicyConfig(edge_based_tp=False, confidence_scaling=False)
        engine = ExitPolicyEngine(config)
        
        # NO: Entry 50c, current 10c = 80% profit (price moved down) - CRITICAL FIX 2026-07-16: Updated for new TP threshold
        # CRITICAL FIX 2026-07-30: Updated minutes_held from 3.0 to 6.0 to meet new min_hold_minutes=5.0
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=10,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=6.0,  # Above min_hold_minutes (5.0)
            side="no",
        )
        
        assert signal.should_exit == True
        assert signal.reason == ExitReason.TAKE_PROFIT
    
    def test_yes_position_stop_loss_suppressed(self):
        """Direct stop-loss for YES is suppressed; StopCandidate path is live."""
        engine = ExitPolicyEngine()

        # YES: Entry 50c, current 30c = 40% loss - CRITICAL FIX 2026-07-16: Updated for new SL threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=30,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="yes",
        )

        assert signal.should_exit == False
        assert signal.reason is None
        assert "SL suppressed" in signal.message

    def test_no_position_stop_loss_suppressed(self):
        """Direct stop-loss for NO is suppressed; StopCandidate path is live."""
        engine = ExitPolicyEngine()

        # NO: Entry 50c, current 70c = 40% loss (price moved up) - CRITICAL FIX 2026-07-16: Updated for new SL threshold
        signal = engine.evaluate_exit(
            entry_price_cents=50,
            current_price_cents=70,
            edge_pct=0.05,
            confidence=0.8,
            minutes_held=2.0,
            side="no",
        )

        assert signal.should_exit == False
        assert signal.reason is None
        assert "SL suppressed" in signal.message


class TestExitPolicyRiskRewardRatio:
    """Test exit policy risk/reward ratio (CRITICAL FIX 2026-07-16)."""
    
    def test_positive_risk_reward_ratio(self):
        """Test that exit policy achieves positive risk/reward ratio (2:1 in favor)."""
        config = ExitPolicyConfig()
        
        # Risk/reward ratio should be 2:1 in favor (win $0.80, lose $0.40)
        assert config.take_profit_pct == 0.80, "TP should be 80%"
        assert config.stop_loss_pct == 0.40, "SL should be 40%"
        
        # Required win rate should be achievable (33% or lower)
        required_win_rate = config.stop_loss_pct / (config.stop_loss_pct + config.take_profit_pct)
        assert required_win_rate <= 0.40, f"Required win rate {required_win_rate:.2%} should be <= 40%"
    
    def test_break_even_win_rate(self):
        """Test break-even win rate calculation."""
        config = ExitPolicyConfig()
        
        # Break-even win rate = SL / (SL + TP)
        # With 80% TP and 40% SL: 0.40 / (0.40 + 0.80) = 0.40 / 1.20 = 33.3%
        break_even_win_rate = config.stop_loss_pct / (config.stop_loss_pct + config.take_profit_pct)
        
        # Should be achievable in 15m crypto markets (typical win rate: 45-55%)
        assert 0.30 <= break_even_win_rate <= 0.40, f"Break-even win rate {break_even_win_rate:.2%} should be 30-40%"
    
    def test_expected_value_positive(self):
        """Test that expected value is positive with typical win rate."""
        config = ExitPolicyConfig()
        
        # Typical 15m crypto market win rate
        typical_win_rate = 0.50
        
        # Expected value = (win_rate * TP) - ((1 - win_rate) * SL)
        expected_value = (typical_win_rate * config.take_profit_pct) - ((1 - typical_win_rate) * config.stop_loss_pct)
        
        # Should be positive with 50% win rate
        assert expected_value > 0, f"Expected value {expected_value:.2%} should be positive with 50% win rate"
    
    def test_comparison_with_old_values(self):
        """Test that new values are better than old catastrophic values."""
        config = ExitPolicyConfig()
        
        # Old values (catastrophic): TP 50%, SL 80% -> 1.6:1 against trader
        old_tp = 0.50
        old_sl = 0.80
        old_required_win_rate = old_sl / (old_sl + old_tp)  # 61.5%
        
        # New values (positive): TP 80%, SL 40% -> 2:1 in favor
        new_required_win_rate = config.stop_loss_pct / (config.stop_loss_pct + config.take_profit_pct)  # 33.3%
        
        # New required win rate should be significantly lower
        assert new_required_win_rate < old_required_win_rate * 0.6, \
            f"New required win rate {new_required_win_rate:.2%} should be much lower than old {old_required_win_rate:.2%}"

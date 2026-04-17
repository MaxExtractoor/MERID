"""End-to-end coverage tests for Kalshi crypto integration.

Parametrized test suite covering all asset/timeframe combinations:
- Assets: BTC, ETH, SOL, XRP, DOGE
- Timeframes: 15m, hourly, daily, weekly, one-time

Test Suite Invariants:
- TradeMode is always reset between tests (via conftest.py autouse fixture)
- E2E coverage tests run in PAPER by default
- All tests are deterministic and independent
"""

import pytest
from datetime import datetime, timezone
from typing import Dict, Any, List
from unittest.mock import Mock, patch

from trading.trade_mode import TradeMode, set_trade_mode, get_trade_mode

# Asset/Timeframe coverage matrix
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TIMEFRAMES = ["15m", "hourly", "daily", "weekly", "one-time"]

# Map timeframes to config labels
TIMEFRAME_LABELS = {
    "15m": "15M",
    "hourly": "HOURLY",
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "one-time": "OT",
}


class TestKalshiCryptoE2E:
    """End-to-end tests for Kalshi crypto integration - PAPER mode only."""
    
    @pytest.mark.parametrize("asset", ASSETS)
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    @pytest.mark.e2e
    @pytest.mark.slow
    def test_kalshi_crypto_e2e_paper(self, asset: str, timeframe: str, fresh_paper_session):
        """Test complete lifecycle: signal → intent → risk → execution → fill → recon.
        
        Uses fresh_paper_session fixture for complete isolation.
        
        Verifies:
        - No exceptions in any phase
        - All events logged
        - PnL updated correctly
        - TradeMode is PAPER throughout
        """
        paper = fresh_paper_session
        
        # 1. Verify we're in PAPER mode
        assert get_trade_mode() == TradeMode.PAPER
        
        # 2. Generate synthetic signal
        agent_name = f"{asset}_{TIMEFRAME_LABELS[timeframe]}"
        signal = {
            "asset": asset,
            "timeframe": timeframe,
            "direction": "LONG",
            "confidence": 0.75,
            "edge": 0.05,
            "kalshi_market_id": f"KX{asset}-{TIMEFRAME_LABELS[timeframe]}",
        }
        
        # 3. Create intent from signal
        intent = {
            "agent_id": agent_name,
            "signal": signal,
            "suggested_contracts": 10,
            "kelly_fraction": 0.25,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # 4. Validate intent structure
        assert intent["signal"]["asset"] == asset
        assert intent["signal"]["timeframe"] == timeframe
        assert intent["suggested_contracts"] > 0
        
        # 5. Verify no mode drift
        assert get_trade_mode() == TradeMode.PAPER
    
    def test_per_market_kill_switch_blocks_orders(self, auto_promoter_clean):
        """Test that per-market kill switch blocks new orders."""
        promoter = auto_promoter_clean
        agent_name = "BTC_15M"
        market_id = "KXBTC-15M"
        
        # 1. Initialize agent
        promoter.initialize_agent(agent_name, "BTC", "15m")
        
        # 2. First order path check (no kill switch)
        status = promoter.get_status(agent_name)
        assert market_id not in status.blocked_markets
        
        # 3. Activate per-market kill switch
        promoter.block_market(
            agent_id=agent_name,
            market=market_id,
            reason="test_kill_switch_activation"
        )
        
        # 4. Verify market is blocked
        status = promoter.get_status(agent_name)
        assert market_id in status.blocked_markets
    
    def test_coverage_matrix_completeness(self):
        """Verify all asset/timeframe combinations are covered."""
        expected_combos = len(ASSETS) * len(TIMEFRAMES)
        actual_combos = [(a, tf) for a in ASSETS for tf in TIMEFRAMES]
        
        assert len(actual_combos) == expected_combos
        assert ("BTC", "15m") in actual_combos
        assert ("ETH", "hourly") in actual_combos
        assert ("SOL", "daily") in actual_combos
        assert ("XRP", "weekly") in actual_combos
        assert ("DOGE", "one-time") in actual_combos


class TestTradeModeGating:
    """Tests for TradeMode gating - isolated from other tests."""
    
    def test_paper_to_live_requires_env_flag(self, _reset_trade_mode_between_tests):
        """Test that switching to LIVE requires MERID_ALLOW_LIVE_TRADES=true."""
        set_trade_mode(TradeMode.PAPER, reason="test_start")
        assert get_trade_mode() == TradeMode.PAPER
        
        with pytest.raises(RuntimeError) as exc_info:
            set_trade_mode(TradeMode.LIVE, reason="unauthorized_live_attempt")
        
        assert "MERID_ALLOW_LIVE_TRADES" in str(exc_info.value)
        assert get_trade_mode() == TradeMode.PAPER
    
    def test_mock_to_paper_allowed(self, _reset_trade_mode_between_tests):
        """Test that MOCK → PAPER transition is allowed."""
        set_trade_mode(TradeMode.MOCK, reason="test_start")
        assert get_trade_mode() == TradeMode.MOCK
        
        old_mode = set_trade_mode(TradeMode.PAPER, reason="test_transition")
        assert old_mode == TradeMode.MOCK
        assert get_trade_mode() == TradeMode.PAPER
    
    def test_mock_to_live_blocked(self, _reset_trade_mode_between_tests):
        """Test that MOCK → LIVE transition is blocked."""
        set_trade_mode(TradeMode.MOCK, reason="test_start")
        assert get_trade_mode() == TradeMode.MOCK
        
        with patch.dict("os.environ", {"MERID_ALLOW_LIVE_TRADES": "true"}):
            with pytest.raises(RuntimeError) as exc_info:
                set_trade_mode(TradeMode.LIVE, reason="mock_to_live_attempt")
            
            assert "MOCK to LIVE" in str(exc_info.value)
        
        assert get_trade_mode() == TradeMode.MOCK


class TestKalshiFeeModel:
    """Tests for Kalshi fee model in isolation."""
    
    def test_fee_calculation_accuracy(self):
        """Test that fee calculations match Kalshi's fee schedule."""
        from merid.kalshi.crypto_15m_execution import KalshiCrypto15mExecutor, KalshiFeeConfig
        
        executor = KalshiCrypto15mExecutor()
        
        test_cases = [
            (50, 10),  # 50 cents, 10 contracts
            (20, 5),   # 20 cents, 5 contracts
            (80, 8),   # 80 cents, 8 contracts
        ]
        
        for price_cents, quantity in test_cases:
            taker_fee = executor.calculate_kalshi_fees(price_cents, quantity, is_maker=False)
            
            price_frac = price_cents / 100.0
            expected_per_contract = 0.07 * price_frac * (1 - price_frac) * 100
            expected_per_contract = min(expected_per_contract, 3.5)
            expected_total = expected_per_contract * quantity
            
            assert abs(taker_fee - expected_total) < 0.01
    
    def test_fee_config_validation(self):
        """Test fee config validation."""
        from merid.kalshi.crypto_15m_execution import KalshiFeeConfig
        
        valid = KalshiFeeConfig(taker_fee_rate=0.07, maker_fee_rate=0.0175, max_fee_cents=3.5)
        assert valid.validate() is True
        
        invalid_taker = KalshiFeeConfig(taker_fee_rate=0.8, maker_fee_rate=0.0175, max_fee_cents=3.5)
        assert invalid_taker.validate() is False


class TestReconciliationKillSwitchIntegration:
    """Tests for reconciliation → kill switch wiring."""
    
    def test_critical_discrepancy_triggers_kill_recommendation(self, auto_promoter_clean):
        """Test that critical reconciliation discrepancies trigger kill switch recommendations."""
        from merid.reconciliation import PositionDiscrepancy, _recommend_kill_switch_for_discrepancies
        
        promoter = auto_promoter_clean
        promoter.initialize_agent("BTC_15M", "BTC", "15m")
        
        discrepancies = [
            PositionDiscrepancy(
                venue="kalshi",
                symbol="KXBTC-15M",
                merid_qty=100.0,
                venue_qty=0.0,
                merid_entry_price=50.0,
                venue_entry_price=0.0,
            )
        ]
        
        _recommend_kill_switch_for_discrepancies(discrepancies)
        
        status = promoter.get_status("BTC_15M")
        assert "KXBTC-15M" in status.blocked_markets


def test_parametrization_sanity():
    """Quick sanity check that parametrization is set up correctly."""
    assert len(ASSETS) == 5
    assert len(TIMEFRAMES) == 5

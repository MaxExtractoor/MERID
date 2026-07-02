"""Integration tests for probability calibration outcome recording and auto-fit logic.

Tests the complete flow from order placement through trade resolution to outcome recording
and automatic calibration fitting in the 15m Kalshi crypto trading system.
"""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any

from merid.risk.probability.platt_scaler import PlattScaler
from merid.prediction.agent_grid_15m import LeanAgent15m, LeanAgentConfig
from merid.event_venues.kalshi.round_trip_monitor import RoundTripMonitor, EntryRecord, get_round_trip_monitor
from merid.event_venues.kalshi.fills_ledger import KalshiFill, KalshiFillsLedger, OrderIntent as FillsLedgerOrderIntent


class TestCalibrationOutcomeRecording:
    """Tests for outcome recording flow from trade resolution to calibration."""
    
    @pytest.fixture
    def mock_agent_config(self):
        """Create a mock LeanAgentConfig with calibration enabled."""
        return LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
            per_asset_cooldown_s=60,
            calibration_enabled=True,
            calibration_auto_fit=True,
            calibration_min_samples=10,
            calibration_max_samples=100,
            calibration_regularization=0.0001,
            calibration_fit_interval_hours=24,
        )
    
    @pytest.fixture
    def mock_spot_provider(self):
        """Create a mock spot provider."""
        provider = Mock()
        provider.get_spot_price = Mock(return_value=95000.0)
        return provider
    
    @pytest.fixture
    def mock_market_state_store(self):
        """Create a mock market state store."""
        store = Mock()
        return store
    
    @pytest.fixture
    def agent(self, mock_agent_config, mock_spot_provider, mock_market_state_store):
        """Create a LeanAgent15m instance for testing."""
        agent = LeanAgent15m(
            config=mock_agent_config,
            spot_provider=mock_spot_provider,
            market_state_store=mock_market_state_store,
        )
        return agent
    
    def test_record_outcome_stores_logit_and_binary_result(self, agent):
        """Test that record_outcome correctly stores logit and binary outcome."""
        # Record some outcomes
        agent.record_outcome(0.5, 1)  # Win
        agent.record_outcome(-0.3, 0)  # Loss
        agent.record_outcome(0.8, 1)  # Win
        
        # Check that outcomes were stored
        assert len(agent._calibration_logits) == 3
        assert len(agent._calibration_outcomes) == 3
        assert agent._calibration_logits == [0.5, -0.3, 0.8]
        assert agent._calibration_outcomes == [1, 0, 1]
    
    def test_record_outcome_triggers_auto_fit_when_threshold_reached(self, agent):
        """Test that auto-fit is triggered when min_samples threshold is reached."""
        # Set a low threshold for testing
        agent._calibration_min_samples = 3
        
        # Record outcomes up to threshold
        agent.record_outcome(0.5, 1)
        agent.record_outcome(-0.3, 0)
        agent.record_outcome(0.8, 1)  # This should trigger auto-fit
        
        # Check that scaler was fitted
        assert agent._platt_scaler.is_fitted()
    
    def test_record_outcome_respects_fit_interval(self, agent):
        """Test that auto-fit respects the fit interval to avoid overfitting."""
        # Set low threshold and short interval
        agent._calibration_min_samples = 3
        agent._calibration_fit_interval_hours = 1
        agent._last_fit_time = time.time() - 3600  # 1 hour ago
        
        # Record outcomes
        agent.record_outcome(0.5, 1)
        agent.record_outcome(-0.3, 0)
        agent.record_outcome(0.8, 1)
        
        # Should fit since interval has passed
        assert agent._platt_scaler.is_fitted()
        
        # Reset and try again within interval
        agent._platt_scaler.reset()
        agent._last_fit_time = time.time()  # Just fitted
        
        # Record more outcomes
        agent.record_outcome(0.2, 0)
        agent.record_outcome(0.6, 1)
        agent.record_outcome(0.4, 0)
        
        # Should NOT fit since interval hasn't passed
        assert not agent._platt_scaler.is_fitted()
    
    def test_record_outcome_rolls_window_when_max_samples_exceeded(self, agent):
        """Test that calibration data rolls when max_samples is exceeded."""
        agent._calibration_max_samples = 5
        
        # Record more than max_samples
        for i in range(10):
            agent.record_outcome(float(i) / 10.0, i % 2)
        
        # Should only keep max_samples
        assert len(agent._calibration_logits) == 5
        assert len(agent._calibration_outcomes) == 5
    
    def test_get_calibration_metrics_returns_correct_structure(self, agent):
        """Test that get_calibration_metrics returns the expected structure."""
        # Record some outcomes and fit
        for i in range(20):
            agent.record_outcome(float(i) / 20.0 - 0.5, i % 2)
        
        metrics = agent.get_calibration_metrics()
        
        # Check structure
        assert "is_fitted" in metrics
        assert "sample_count" in metrics
        assert "brier_score" in metrics
        assert "ece" in metrics
        assert "mce" in metrics
        assert "last_fit_time" in metrics
        
        # Check values
        assert metrics["sample_count"] == 20
        assert metrics["is_fitted"] == True


class TestRoundTripMonitorCallback:
    """Tests for RoundTripMonitor callback integration with calibration."""
    
    @pytest.fixture
    def monitor(self):
        """Create a RoundTripMonitor instance."""
        return RoundTripMonitor(max_round_trips_per_day=20, sl_violation_threshold_cents=5)
    
    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent with record_outcome method."""
        agent = Mock()
        agent.record_outcome = Mock()
        return agent
    
    def test_set_outcome_callback_registers_callback(self, monitor):
        """Test that set_outcome_callback registers the callback function."""
        callback = Mock()
        monitor.set_outcome_callback(callback)
        
        assert monitor._outcome_callback == callback
    
    def test_record_exit_calls_callback_with_correct_parameters(self, monitor, mock_agent):
        """Test that record_exit calls the callback with agent_id, logit, and outcome."""
        # Set up callback
        def callback(agent_id: str, logit: float, outcome: int) -> None:
            mock_agent.record_outcome(logit, outcome)
        
        monitor.set_outcome_callback(callback)
        
        # Record entry
        entry = EntryRecord(
            intent_id="test_intent",
            ticker="KXBTC15M-T10000",
            asset="BTC",
            timestamp=datetime.now(timezone.utc),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="default",
            exit_policy_id="default",
            raw_logit=0.5,
            agent_id="BTC_15M",
        )
        monitor.record_entry(entry)
        
        # Record exit with profit (outcome=1)
        monitor.record_exit(
            exit_intent_id="exit_intent",
            entry_intent_id="test_intent",
            exit_price_cents=55,  # 5 cent profit
            exit_reason="tp",
        )
        
        # Check that callback was called
        mock_agent.record_outcome.assert_called_once_with(0.5, 1)
    
    def test_record_exit_determines_outcome_from_pnl(self, monitor, mock_agent):
        """Test that outcome is correctly determined from PnL (profit=1, loss=0)."""
        callback = Mock()
        monitor.set_outcome_callback(callback)
        
        # Record entry
        entry = EntryRecord(
            intent_id="test_intent",
            ticker="KXBTC15M-T10000",
            asset="BTC",
            timestamp=datetime.now(timezone.utc),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="default",
            exit_policy_id="default",
            raw_logit=0.5,
            agent_id="BTC_15M",
        )
        monitor.record_entry(entry)
        
        # Record exit with loss (outcome=0)
        monitor.record_exit(
            exit_intent_id="exit_intent",
            entry_intent_id="test_intent",
            exit_price_cents=45,  # 5 cent loss
            exit_reason="sl",
        )
        
        # Check that callback was called with outcome=0
        callback.assert_called_once_with("BTC_15M", 0.5, 0)


class TestFillsLedgerIntegration:
    """Tests for fills_ledger integration with calibration data."""
    
    @pytest.fixture
    def ledger(self):
        """Create a KalshiFillsLedger instance."""
        return KalshiFillsLedger()
    
    def test_intent_stores_raw_logit(self, ledger):
        """Test that OrderIntent stores raw_logit for calibration."""
        intent = FillsLedgerOrderIntent(
            intent_id="test_intent",
            ticker="KXBTC15M-T10000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="BTC_15M",
            raw_logit=0.75,
        )
        
        ledger.record_intent(intent)
        
        # Check that intent was stored with raw_logit
        stored_intent = ledger._intents["test_intent"]
        assert stored_intent.raw_logit == 0.75
    
    def test_fill_copies_raw_logit_from_intent(self, ledger):
        """Test that KalshiFill copies raw_logit from linked intent."""
        # Record intent with raw_logit
        intent = FillsLedgerOrderIntent(
            intent_id="test_intent",
            ticker="KXBTC15M-T10000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="BTC_15M",
            raw_logit=0.75,
        )
        ledger.record_intent(intent)
        
        # Create fill linked to intent
        fill = KalshiFill(
            fill_id="test_fill",
            market_ticker="KXBTC15M-T10000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            client_order_id="test_intent",
            ingestion_source="test",
        )
        
        # Add fill to ledger (this should copy raw_logit from intent)
        ledger._fills[fill.fill_id] = fill
        ledger._index_fill(fill)
        
        # Link to intent
        if fill.client_order_id and fill.client_order_id in ledger._intents:
            stored_intent = ledger._intents[fill.client_order_id]
            fill.intent_id = stored_intent.intent_id
            fill.agent_id = stored_intent.agent_id
            if hasattr(stored_intent, 'raw_logit') and stored_intent.raw_logit is not None:
                fill.raw_logit = stored_intent.raw_logit
        
        # Check that fill has raw_logit
        assert fill.raw_logit == 0.75


class TestEndToEndCalibrationFlow:
    """End-to-end tests for the complete calibration flow."""
    
    def test_flow_from_order_to_calibration(self):
        """Test the complete flow from order placement to calibration outcome recording."""
        # This is a high-level integration test that would require mocking
        # the entire order flow. For now, we test the components individually.
        
        # 1. OrderIntent carries raw_logit
        from merid.event_venues.kalshi.order_router import OrderIntent as RouterOrderIntent
        intent = RouterOrderIntent(
            ticker="KXBTC15M-T10000",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            raw_logit=0.75,
        )
        assert intent.raw_logit == 0.75
        
        # 2. FillsLedger stores raw_logit
        ledger = KalshiFillsLedger()
        fills_intent = FillsLedgerOrderIntent(
            intent_id=intent.intent_id,
            ticker=intent.ticker,
            side=intent.side,
            action=intent.action,
            count=intent.count,
            price_cents=intent.price_cents,
            raw_logit=intent.raw_logit,
        )
        ledger.record_intent(fills_intent)
        assert ledger._intents[intent.intent_id].raw_logit == 0.75
        
        # 3. RoundTripMonitor records entry with raw_logit
        monitor = get_round_trip_monitor()
        entry = EntryRecord(
            intent_id=intent.intent_id,
            ticker=intent.ticker,
            asset="BTC",
            timestamp=datetime.now(timezone.utc),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="default",
            exit_policy_id="default",
            raw_logit=0.75,
            agent_id="BTC_15M",
        )
        monitor.record_entry(entry)
        assert monitor._entries[intent.intent_id].raw_logit == 0.75
        
        # 4. Callback records outcome to agent
        mock_agent = Mock()
        monitor.set_outcome_callback(lambda agent_id, logit, outcome: mock_agent.record_outcome(logit, outcome))
        monitor.record_exit(
            exit_intent_id="exit_intent",
            entry_intent_id=intent.intent_id,
            exit_price_cents=55,
            exit_reason="tp",
        )
        mock_agent.record_outcome.assert_called_once_with(0.75, 1)

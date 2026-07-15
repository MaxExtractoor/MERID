"""Tests for entropy-based kill switch module."""

import pytest
import time
from datetime import datetime, timezone

from merid.event_venues.kalshi.entropy_kill_switch import (
    EntropyKillSwitch,
    KillSwitchState,
    get_entropy_kill_switch,
    reset_entropy_kill_switch,
)


class TestEntropyKillSwitch:
    """Test entropy-based kill switch functionality."""
    
    def test_kill_switch_initialization(self):
        """Test kill switch initialization with default thresholds."""
        kill_switch = EntropyKillSwitch()
        
        assert kill_switch.entropy_threshold == 2.5
        assert kill_switch.signal_energy_threshold == 1000.0
        assert kill_switch.cooldown_duration_sec == 300
        assert kill_switch.auto_reset is True
    
    def test_kill_switch_custom_thresholds(self):
        """Test kill switch initialization with custom thresholds."""
        kill_switch = EntropyKillSwitch(
            entropy_threshold=3.0,
            signal_energy_threshold=2000.0,
            cooldown_duration_sec=600,
            auto_reset=False,
        )
        
        assert kill_switch.entropy_threshold == 3.0
        assert kill_switch.signal_energy_threshold == 2000.0
        assert kill_switch.cooldown_duration_sec == 600
        assert kill_switch.auto_reset is False
    
    def test_check_kill_switch_normal(self):
        """Test kill switch check with normal conditions."""
        kill_switch = EntropyKillSwitch()
        
        state = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=1.0,  # Below threshold
            signal_energy=500.0,  # Below threshold
        )
        
        assert state.is_active is False
        assert state.trigger_count == 0
    
    def test_check_kill_switch_entropy_trigger(self):
        """Test kill switch trigger on high entropy."""
        kill_switch = EntropyKillSwitch(entropy_threshold=2.0)
        
        state = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,  # Above threshold
            signal_energy=500.0,
        )
        
        assert state.is_active is True
        assert state.trigger_count == 1
        assert state.entropy_at_trigger == 2.5
        assert "entropy" in state.trigger_reason.lower()
    
    def test_check_kill_switch_signal_energy_trigger(self):
        """Test kill switch trigger on high signal energy."""
        kill_switch = EntropyKillSwitch(signal_energy_threshold=500.0)
        
        state = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=1.0,
            signal_energy=1000.0,  # Above threshold
        )
        
        assert state.is_active is True
        assert state.trigger_count == 1
        assert state.signal_energy_at_trigger == 1000.0
        assert "signal energy" in state.trigger_reason.lower()
    
    def test_kill_switch_cooldown(self):
        """Test kill switch cooldown period."""
        kill_switch = EntropyKillSwitch(
            entropy_threshold=2.0,
            cooldown_duration_sec=1,  # 1 second for testing
        )
        
        # Trigger kill switch
        state1 = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        assert state1.is_active is True
        assert state1.cooldown_until is not None
        
        # Check during cooldown (should still be active)
        state2 = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=1.0,  # Normal now
            signal_energy=500.0,
        )
        
        assert state2.is_active is True  # Still in cooldown
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        
        # Check after cooldown (should auto-reset)
        state3 = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=1.0,
            signal_energy=500.0,
        )
        
        if kill_switch.auto_reset:
            assert state3.is_active is False
        else:
            assert state3.is_active is True
    
    def test_kill_switch_no_auto_reset(self):
        """Test kill switch without auto-reset."""
        kill_switch = EntropyKillSwitch(
            entropy_threshold=2.0,
            cooldown_duration_sec=1,
            auto_reset=False,
        )
        
        # Trigger kill switch
        state1 = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        assert state1.is_active is True
        
        # Wait for cooldown
        time.sleep(1.1)
        
        # Check after cooldown (should NOT auto-reset)
        state2 = kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=1.0,
            signal_energy=500.0,
        )
        
        assert state2.is_active is True  # Still active (no auto-reset)
    
    def test_trigger_global_kill_switch(self):
        """Test manual global kill switch trigger."""
        kill_switch = EntropyKillSwitch()
        
        kill_switch.trigger_global_kill_switch(
            reason="Manual test trigger",
            entropy=2.5,
            signal_energy=1000.0,
        )
        
        state = kill_switch.get_state()
        
        assert state.is_active is True
        assert "manual" in state.trigger_reason.lower()
        assert state.entropy_at_trigger == 2.5
        assert state.signal_energy_at_trigger == 1000.0
    
    def test_reset_kill_switch_market(self):
        """Test manual reset of market kill switch."""
        kill_switch = EntropyKillSwitch(entropy_threshold=2.0)
        
        # Trigger kill switch
        kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        assert kill_switch.get_state("KXBTCD-25JUN-T100000").is_active is True
        
        # Reset
        kill_switch.reset_kill_switch(ticker="KXBTCD-25JUN-T100000")
        
        assert kill_switch.get_state("KXBTCD-25JUN-T100000").is_active is False
        assert kill_switch.get_state("KXBTCD-25JUN-T100000").last_reset_at is not None
    
    def test_reset_kill_switch_global(self):
        """Test manual reset of global kill switch."""
        kill_switch = EntropyKillSwitch()
        
        # Trigger global kill switch
        kill_switch.trigger_global_kill_switch(reason="Test")
        
        assert kill_switch.get_state().is_active is True
        
        # Reset
        kill_switch.reset_kill_switch()
        
        assert kill_switch.get_state().is_active is False
        assert kill_switch.get_state().last_reset_at is not None
    
    def test_is_trading_allowed_normal(self):
        """Test trading allowed in normal conditions."""
        kill_switch = EntropyKillSwitch()
        
        is_allowed, reason = kill_switch.is_trading_allowed("KXBTCD-25JUN-T100000")
        
        assert is_allowed is True
        assert reason == "Trading allowed"
    
    def test_is_trading_allowed_market_blocked(self):
        """Test trading blocked by market kill switch."""
        kill_switch = EntropyKillSwitch(entropy_threshold=2.0)
        
        # Trigger kill switch
        kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        is_allowed, reason = kill_switch.is_trading_allowed("KXBTCD-25JUN-T100000")
        
        assert is_allowed is False
        assert "kill switch" in reason.lower()
    
    def test_is_trading_allowed_global_blocked(self):
        """Test trading blocked by global kill switch."""
        kill_switch = EntropyKillSwitch()
        
        # Trigger global kill switch
        kill_switch.trigger_global_kill_switch(reason="Test")
        
        is_allowed, reason = kill_switch.is_trading_allowed("KXBTCD-25JUN-T100000")
        
        assert is_allowed is False
        assert "global" in reason.lower()
    
    def test_is_trading_allowed_different_market(self):
        """Test trading allowed for different market when one is blocked."""
        kill_switch = EntropyKillSwitch(entropy_threshold=2.0)
        
        # Trigger kill switch for BTC
        kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        # ETH should still be allowed
        is_allowed, reason = kill_switch.is_trading_allowed("KXETHD-25JUN-T100000")
        
        assert is_allowed is True
    
    def test_get_state_market(self):
        """Test getting market-specific state."""
        kill_switch = EntropyKillSwitch()
        
        state = kill_switch.get_state("KXBTCD-25JUN-T100000")
        
        assert state.is_active is False
        assert state.trigger_count == 0
    
    def test_get_state_global(self):
        """Test getting global state."""
        kill_switch = EntropyKillSwitch()
        
        state = kill_switch.get_state()
        
        assert state.is_active is False
        assert state.trigger_count == 0
    
    def test_get_all_states(self):
        """Test getting all states."""
        kill_switch = EntropyKillSwitch(entropy_threshold=2.0)
        
        # Trigger for BTC
        kill_switch.check_kill_switch(
            ticker="KXBTCD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        # Trigger for ETH
        kill_switch.check_kill_switch(
            ticker="KXETHD-25JUN-T100000",
            entropy=2.5,
            signal_energy=500.0,
        )
        
        all_states = kill_switch.get_all_states()
        
        assert "global" in all_states
        assert "KXBTCD-25JUN-T100000" in all_states
        assert "KXETHD-25JUN-T100000" in all_states
        assert all_states["KXBTCD-25JUN-T100000"].is_active is True
        assert all_states["KXETHD-25JUN-T100000"].is_active is True


class TestKillSwitchState:
    """Test KillSwitchState dataclass."""
    
    def test_state_initialization(self):
        """Test state initialization."""
        state = KillSwitchState()
        
        assert state.is_active is False
        assert state.triggered_at is None
        assert state.trigger_reason == ""
        assert state.entropy_at_trigger == 0.0
        assert state.signal_energy_at_trigger == 0.0
        assert state.cooldown_until is None
        assert state.trigger_count == 0
    
    def test_state_to_dict(self):
        """Test state serialization to dict."""
        state = KillSwitchState(
            is_active=True,
            triggered_at=1234567890.0,
            trigger_reason="Test trigger",
            entropy_at_trigger=2.5,
            signal_energy_at_trigger=1000.0,
            trigger_count=5,
        )
        
        d = state.to_dict()
        
        assert d["is_active"] is True
        assert d["triggered_at"] == 1234567890.0
        assert d["trigger_reason"] == "Test trigger"
        assert d["entropy_at_trigger"] == 2.5
        assert d["signal_energy_at_trigger"] == 1000.0
        assert d["trigger_count"] == 5


class TestEntropyKillSwitchSingleton:
    """Test global kill switch singleton management."""
    
    def test_get_entropy_kill_switch(self):
        """Test getting global kill switch instance."""
        reset_entropy_kill_switch()
        
        ks1 = get_entropy_kill_switch()
        ks2 = get_entropy_kill_switch()
        
        # Should return same instance
        assert ks1 is ks2
    
    def test_get_entropy_kill_switch_custom(self):
        """Test getting global kill switch with custom config."""
        reset_entropy_kill_switch()
        
        ks1 = get_entropy_kill_switch(entropy_threshold=3.0)
        ks2 = get_entropy_kill_switch()
        
        # Should return same instance (first call wins)
        assert ks1 is ks2
        assert ks1.entropy_threshold == 3.0
    
    def test_reset_entropy_kill_switch(self):
        """Test resetting global kill switch."""
        reset_entropy_kill_switch()
        
        ks1 = get_entropy_kill_switch()
        ks1.trigger_global_kill_switch(reason="Test")
        
        reset_entropy_kill_switch()
        
        ks2 = get_entropy_kill_switch()
        
        # Should be new instance
        assert ks1 is not ks2
        assert ks2.get_state().is_active is False

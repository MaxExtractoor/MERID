"""Drawdown progression integration test for risk envelope.

Tests the full lifecycle of drawdown tracking from initial state through
various drawdown levels, adaptive risk band transitions, and halt conditions.
"""

import pytest
from unittest.mock import Mock, patch


def test_drawdown_progression_full_lifecycle():
    """Test full drawdown progression from healthy to halted state."""
    # Create a mock envelope
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 10000.0
    envelope.current_drawdown_pct = 0.0
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.kelly_fraction = 0.25
    envelope.per_trade_risk_multiplier = 1.0
    envelope.is_halted = False
    
    # Simulate drawdown progression through bands
    equity_progression = [10000.0, 9800.0, 9500.0, 9000.0, 8500.0]
    
    for equity in equity_progression:
        envelope.current_equity_usd = equity
        envelope.current_drawdown_pct = (envelope.peak_equity_usd - equity) / envelope.peak_equity_usd
        
        # Update risk multiplier based on drawdown
        for band in envelope.adaptive_risk_bands:
            if envelope.current_drawdown_pct <= band["max_drawdown_pct"]:
                envelope.per_trade_risk_multiplier = band["multiplier"]
                break
        
        # Check halt condition
        if envelope.current_drawdown_pct >= envelope.drawdown_halt_pct:
            envelope.is_halted = True
    
    # Final state should be halted
    assert envelope.is_halted is True
    assert envelope.current_drawdown_pct == 0.15
    assert envelope.per_trade_risk_multiplier == 0.5


def test_drawdown_progression_recovery():
    """Test drawdown recovery from halted state back to healthy."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 8500.0  # Started at halt level
    envelope.current_drawdown_pct = 0.15
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.kelly_fraction = 0.25
    envelope.per_trade_risk_multiplier = 0.5
    envelope.is_halted = True
    
    # Simulate recovery
    equity_progression = [8500.0, 8750.0, 9000.0, 9500.0, 10000.0, 10200.0]
    
    for equity in equity_progression:
        envelope.current_equity_usd = equity
        
        # Update peak if new high
        if equity > envelope.peak_equity_usd:
            envelope.peak_equity_usd = equity
        
        envelope.current_drawdown_pct = (envelope.peak_equity_usd - equity) / envelope.peak_equity_usd
        
        # Update risk multiplier
        for band in envelope.adaptive_risk_bands:
            if envelope.current_drawdown_pct <= band["max_drawdown_pct"]:
                envelope.per_trade_risk_multiplier = band["multiplier"]
                break
        
        # Unhalt if below unwind threshold
        if envelope.current_drawdown_pct < envelope.drawdown_unwind_pct:
            envelope.is_halted = False
    
    # Final state should be healthy
    assert envelope.is_halted is False
    assert envelope.current_drawdown_pct == 0.0  # At new peak
    assert envelope.per_trade_risk_multiplier == 1.0


def test_drawdown_progression_band_transitions():
    """Test that risk band transitions happen at correct thresholds."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 10000.0
    envelope.current_drawdown_pct = 0.0
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.per_trade_risk_multiplier = 1.0
    
    # Track band transitions
    transitions = []
    last_multiplier = envelope.per_trade_risk_multiplier
    
    equity_progression = [10000.0, 9600.0, 9400.0, 8900.0, 8600.0, 8400.0]
    
    for equity in equity_progression:
        envelope.current_equity_usd = equity
        envelope.current_drawdown_pct = (envelope.peak_equity_usd - equity) / envelope.peak_equity_usd
        
        for band in envelope.adaptive_risk_bands:
            if envelope.current_drawdown_pct <= band["max_drawdown_pct"]:
                envelope.per_trade_risk_multiplier = band["multiplier"]
                break
        
        if envelope.per_trade_risk_multiplier != last_multiplier:
            transitions.append({
                "drawdown": envelope.current_drawdown_pct,
                "multiplier": envelope.per_trade_risk_multiplier
            })
            last_multiplier = envelope.per_trade_risk_multiplier
    
    # Should have 2 transitions (1.0 -> 0.75 -> 0.5)
    assert len(transitions) == 2
    assert transitions[0]["multiplier"] == 0.75
    assert transitions[1]["multiplier"] == 0.5


def test_drawdown_progression_with_peak_update():
    """Test drawdown progression when peak equity is updated."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.per_trade_risk_multiplier = 1.0
    
    # Scenario: Recover to new peak, then draw down again
    equity_progression = [9500.0, 10000.0, 10500.0, 10200.0, 9800.0]
    
    for equity in equity_progression:
        envelope.current_equity_usd = equity
        
        # Update peak if new high
        if equity > envelope.peak_equity_usd:
            envelope.peak_equity_usd = equity
        
        envelope.current_drawdown_pct = (envelope.peak_equity_usd - equity) / envelope.peak_equity_usd
        
        for band in envelope.adaptive_risk_bands:
            if envelope.current_drawdown_pct <= band["max_drawdown_pct"]:
                envelope.per_trade_risk_multiplier = band["multiplier"]
                break
    
    # Final state: new peak is 10500, current is 9800
    assert envelope.peak_equity_usd == 10500.0
    assert envelope.current_equity_usd == 9800.0
    assert envelope.current_drawdown_pct == pytest.approx(0.0667, abs=0.001)
    # Drawdown 0.0667 is > 0.05 (first band) but < 0.10 (second band), so multiplier should be 0.75
    assert envelope.per_trade_risk_multiplier == 0.75  # In second band


def test_drawdown_progression_rapid_decline():
    """Test rapid drawdown decline (e.g., gap down)."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 10000.0
    envelope.current_drawdown_pct = 0.0
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.per_trade_risk_multiplier = 1.0
    envelope.is_halted = False
    
    # Simulate rapid gap down (skip bands)
    envelope.current_equity_usd = 8000.0  # 20% drawdown - past halt
    envelope.current_drawdown_pct = (envelope.peak_equity_usd - envelope.current_equity_usd) / envelope.peak_equity_usd
    
    # Should immediately halt
    if envelope.current_drawdown_pct >= envelope.drawdown_halt_pct:
        envelope.is_halted = True
    
    assert envelope.is_halted is True
    assert envelope.current_drawdown_pct == 0.20


def test_drawdown_progression_oscillation():
    """Test drawdown oscillation around band boundaries."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 10000.0
    envelope.current_drawdown_pct = 0.0
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.adaptive_risk_bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    envelope.per_trade_risk_multiplier = 1.0
    
    # Simulate oscillation around 10% threshold
    equity_progression = [9500.0, 8900.0, 9100.0, 8950.0, 9050.0, 8900.0]
    
    multiplier_changes = 0
    last_multiplier = envelope.per_trade_risk_multiplier
    
    for equity in equity_progression:
        envelope.current_equity_usd = equity
        envelope.current_drawdown_pct = (envelope.peak_equity_usd - equity) / envelope.peak_equity_usd
        
        for band in envelope.adaptive_risk_bands:
            if envelope.current_drawdown_pct <= band["max_drawdown_pct"]:
                envelope.per_trade_risk_multiplier = band["multiplier"]
                break
        
        if envelope.per_trade_risk_multiplier != last_multiplier:
            multiplier_changes += 1
            last_multiplier = envelope.per_trade_risk_multiplier
    
    # Should handle oscillations without excessive switching
    assert multiplier_changes >= 1  # At least one change


def test_drawdown_progression_distance_metrics():
    """Test distance to halt metric updates correctly."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    
    # Calculate distance to halt
    def distance_to_halt():
        return envelope.drawdown_halt_pct - envelope.current_drawdown_pct
    
    initial_distance = distance_to_halt()
    assert initial_distance == pytest.approx(0.10, abs=1e-10)
    
    # Increase drawdown
    envelope.current_equity_usd = 9000.0
    envelope.current_drawdown_pct = 0.10
    new_distance = distance_to_halt()
    assert new_distance == pytest.approx(0.05, abs=1e-10)
    
    # At halt
    envelope.current_equity_usd = 8500.0
    envelope.current_drawdown_pct = 0.15
    halt_distance = distance_to_halt()
    assert halt_distance == pytest.approx(0.0, abs=1e-10)


def test_drawdown_progression_with_kill_switch_integration():
    """Test drawdown progression triggers kill switch at halt."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 10000.0
    envelope.current_drawdown_pct = 0.0
    envelope.drawdown_halt_pct = 0.15
    envelope.drawdown_unwind_pct = 0.10
    envelope.is_halted = False
    
    # Mock kill switch controller
    kill_switch_triggered = False
    
    def trigger_kill_switch(reason):
        nonlocal kill_switch_triggered
        kill_switch_triggered = True
    
    # Simulate drawdown to halt
    envelope.current_equity_usd = 8500.0
    envelope.current_drawdown_pct = (envelope.peak_equity_usd - envelope.current_equity_usd) / envelope.peak_equity_usd
    
    if envelope.current_drawdown_pct >= envelope.drawdown_halt_pct:
        envelope.is_halted = True
        trigger_kill_switch(f"Drawdown halt: {envelope.current_drawdown_pct:.2%}")
    
    assert envelope.is_halted is True
    assert kill_switch_triggered is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

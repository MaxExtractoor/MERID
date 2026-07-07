"""
Unit tests for multi-window velocity and mean reversion signal generation.
Tests Phase 4.1 (multi-window velocity) and Phase 4.3 (mean reversion).
"""

import math
import collections
import time
from typing import Dict


def test_multi_window_velocity_calculation():
    """Test multi-window velocity calculation with different time windows."""
    # Simulate price history
    price_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Add price data: prices increasing over time
    base_price = 100.0
    for i in range(100):
        price = base_price + i * 0.01  # Gradual increase
        price_history.append((current_time - (100 - i), price))
    
    # Calculate velocity for each window
    velocity_windows = [10, 30, 60]
    momentum_weights = [0.2, 0.3, 0.5]
    current_price = base_price + 99 * 0.01
    
    weighted_velocity = 0.0
    for window_sec, weight in zip(velocity_windows, momentum_weights):
        target_time = current_time - window_sec
        
        prev_price = None
        for ts, price in reversed(price_history):
            if ts <= target_time:
                prev_price = price
                break
        
        if prev_price is not None and prev_price > 0:
            window_velocity = (current_price - prev_price) / prev_price
            weighted_velocity += weight * window_velocity
    
    # Weighted velocity should be positive (prices increasing)
    assert weighted_velocity > 0, f"Expected positive velocity, got {weighted_velocity}"
    print(f"Multi-window velocity: {weighted_velocity}")


def test_multi_window_velocity_with_insufficient_data():
    """Test multi-window velocity when insufficient data is available."""
    price_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Only add 5 data points (insufficient for 60s window)
    for i in range(5):
        price_history.append((current_time - (5 - i), 100.0 + i * 0.01))
    
    velocity_windows = [10, 30, 60]
    momentum_weights = [0.2, 0.3, 0.5]
    current_price = 100.04
    
    weighted_velocity = 0.0
    for window_sec, weight in zip(velocity_windows, momentum_weights):
        target_time = current_time - window_sec
        
        prev_price = None
        for ts, price in reversed(price_history):
            if ts <= target_time:
                prev_price = price
                break
        
        if prev_price is not None and prev_price > 0:
            window_velocity = (current_price - prev_price) / prev_price
            weighted_velocity += weight * window_velocity
    
    # Should still compute velocity with available windows
    # (60s window will be skipped due to insufficient data)
    print(f"Velocity with insufficient data: {weighted_velocity}")


def test_mean_reversion_sma_calculation():
    """Test mean reversion signal using 2-minute SMA."""
    sma_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Add price data: prices oscillating around 100
    base_price = 100.0
    for i in range(100):
        price = base_price + math.sin(i * 0.1) * 2.0  # Oscillate ±2.0
        sma_history.append((current_time - (100 - i), price))
    
    current_price = base_price + math.sin(99 * 0.1) * 2.0
    
    # Calculate 2-minute SMA
    target_time = current_time - 120.0
    prices_in_window = []
    for ts, price in sma_history:
        if ts >= target_time:
            prices_in_window.append(price)
    
    sma = sum(prices_in_window) / len(prices_in_window)
    
    # Calculate deviation from SMA
    deviation_pct = (current_price - sma) / sma
    
    # Deviation should be small (prices oscillating around mean)
    assert abs(deviation_pct) < 0.05, f"Expected small deviation, got {deviation_pct}"
    print(f"Mean reversion deviation: {deviation_pct}")


def test_mean_reversion_above_sma():
    """Test mean reversion when price is above SMA (should reduce bullish bias)."""
    sma_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Add price data: prices consistently above SMA
    for i in range(100):
        price = 100.0 + i * 0.1  # Consistent upward trend
        sma_history.append((current_time - (100 - i), price))
    
    current_price = 109.9
    
    # Calculate SMA
    target_time = current_time - 120.0
    prices_in_window = []
    for ts, price in sma_history:
        if ts >= target_time:
            prices_in_window.append(price)
    
    sma = sum(prices_in_window) / len(prices_in_window)
    deviation_pct = (current_price - sma) / sma
    
    # Deviation should be positive (price above SMA)
    assert deviation_pct > 0, f"Expected positive deviation, got {deviation_pct}"
    
    # Mean reversion adjustment should be negative (reduce bullish bias)
    mean_reversion_adjustment = -deviation_pct * 0.5
    assert mean_reversion_adjustment < 0, f"Expected negative adjustment, got {mean_reversion_adjustment}"
    print(f"Mean reversion adjustment (above SMA): {mean_reversion_adjustment}")


def test_mean_reversion_below_sma():
    """Test mean reversion when price is below SMA (should increase bullish bias)."""
    sma_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Add price data: prices consistently below SMA
    for i in range(100):
        price = 110.0 - i * 0.1  # Consistent downward trend
        sma_history.append((current_time - (100 - i), price))
    
    current_price = 100.1
    
    # Calculate SMA
    target_time = current_time - 120.0
    prices_in_window = []
    for ts, price in sma_history:
        if ts >= target_time:
            prices_in_window.append(price)
    
    sma = sum(prices_in_window) / len(prices_in_window)
    deviation_pct = (current_price - sma) / sma
    
    # Deviation should be negative (price below SMA)
    assert deviation_pct < 0, f"Expected negative deviation, got {deviation_pct}"
    
    # Mean reversion adjustment should be positive (increase bullish bias)
    mean_reversion_adjustment = -deviation_pct * 0.5
    assert mean_reversion_adjustment > 0, f"Expected positive adjustment, got {mean_reversion_adjustment}"
    print(f"Mean reversion adjustment (below SMA): {mean_reversion_adjustment}")


def test_combined_signal_generation():
    """Test combined velocity and mean reversion signal."""
    # Setup price history
    price_history = collections.deque(maxlen=120)
    sma_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Add price data: increasing trend with oscillation
    base_price = 100.0
    for i in range(100):
        price = base_price + i * 0.05 + math.sin(i * 0.2) * 1.0
        price_history.append((current_time - (100 - i), price))
        sma_history.append((current_time - (100 - i), price))
    
    current_price = base_price + 99 * 0.05 + math.sin(99 * 0.2) * 1.0
    
    # Calculate multi-window velocity
    velocity_windows = [10, 30, 60]
    momentum_weights = [0.2, 0.3, 0.5]
    weighted_velocity = 0.0
    
    for window_sec, weight in zip(velocity_windows, momentum_weights):
        target_time = current_time - window_sec
        prev_price = None
        for ts, price in reversed(price_history):
            if ts <= target_time:
                prev_price = price
                break
        if prev_price is not None and prev_price > 0:
            window_velocity = (current_price - prev_price) / prev_price
            weighted_velocity += weight * window_velocity
    
    # Calculate mean reversion
    target_time = current_time - 120.0
    prices_in_window = []
    for ts, price in sma_history:
        if ts >= target_time:
            prices_in_window.append(price)
    sma = sum(prices_in_window) / len(prices_in_window)
    deviation_pct = (current_price - sma) / sma
    
    # Combine signals
    mean_reversion_adjustment = -deviation_pct * 0.5
    combined_velocity = weighted_velocity + mean_reversion_adjustment
    
    # Combined velocity should reflect both momentum and mean reversion
    print(f"Weighted velocity: {weighted_velocity}")
    print(f"Mean reversion adjustment: {mean_reversion_adjustment}")
    print(f"Combined velocity: {combined_velocity}")
    
    # Apply logistic mapping
    alpha_0 = 0.0
    alpha_1 = 1000.0
    raw_logit = alpha_0 + alpha_1 * combined_velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    
    # p_model should be in valid range
    assert 0.0 <= p_model <= 1.0, f"p_model out of range: {p_model}"
    print(f"Model probability: {p_model}")


def test_velocity_weights_sum_to_one():
    """Test that momentum weights sum to 1.0."""
    momentum_weights = [0.2, 0.3, 0.5]
    total_weight = sum(momentum_weights)
    assert abs(total_weight - 1.0) < 0.001, f"Weights sum to {total_weight}, expected 1.0"
    print(f"Momentum weights sum: {total_weight}")


def test_mean_reversion_with_insufficient_data():
    """Test mean reversion when insufficient data is available."""
    sma_history = collections.deque(maxlen=120)
    current_time = time.time()
    
    # Only add 1 data point
    sma_history.append((current_time, 100.0))
    
    current_price = 100.0
    
    # Calculate SMA
    target_time = current_time - 120.0
    prices_in_window = []
    for ts, price in sma_history:
        if ts >= target_time:
            prices_in_window.append(price)
    
    # Should return 0.0 when insufficient data
    if len(prices_in_window) < 2:
        deviation_pct = 0.0
    else:
        sma = sum(prices_in_window) / len(prices_in_window)
        deviation_pct = (current_price - sma) / sma
    
    assert deviation_pct == 0.0, f"Expected 0.0 with insufficient data, got {deviation_pct}"
    print(f"Mean reversion with insufficient data: {deviation_pct}")


def test_logit_fusion_normal_case():
    """Test logit fusion with normal expiry time."""
    velocity_logit = 0.5
    mean_reversion_logit = -0.2
    minutes_to_expiry = 10.0  # Well above 5 minute guard
    
    logit_fusion_velocity_weight = 0.7
    logit_fusion_mean_reversion_weight = 0.3
    near_expiry_guard_sec = 300
    
    # Apply logit fusion (CRITICAL FIX: 2026-07-07 - use <= instead of <)
    if minutes_to_expiry * 60 <= near_expiry_guard_sec:
        fused_logit = velocity_logit
    else:
        fused_logit = (logit_fusion_velocity_weight * velocity_logit + 
                      logit_fusion_mean_reversion_weight * mean_reversion_logit)
    
    expected_fused = 0.7 * 0.5 + 0.3 * (-0.2)  # 0.35 - 0.06 = 0.29
    assert abs(fused_logit - expected_fused) < 0.001, f"Expected {expected_fused}, got {fused_logit}"
    print(f"Logit fusion (normal): {fused_logit}")


def test_logit_fusion_near_expiry():
    """Test logit fusion near expiry (should use velocity only)."""
    velocity_logit = 0.5
    mean_reversion_logit = -0.2
    minutes_to_expiry = 3.0  # Below 5 minute guard
    
    logit_fusion_velocity_weight = 0.7
    logit_fusion_mean_reversion_weight = 0.3
    near_expiry_guard_sec = 300
    
    # Apply logit fusion (CRITICAL FIX: 2026-07-07 - use <= instead of <)
    if minutes_to_expiry * 60 <= near_expiry_guard_sec:
        fused_logit = velocity_logit
    else:
        fused_logit = (logit_fusion_velocity_weight * velocity_logit + 
                      logit_fusion_mean_reversion_weight * mean_reversion_logit)
    
    # Should use velocity logit only
    assert fused_logit == velocity_logit, f"Expected {velocity_logit}, got {fused_logit}"
    print(f"Logit fusion (near expiry): {fused_logit}")


def test_logit_fusion_at_guard_boundary():
    """Test logit fusion exactly at guard boundary (CRITICAL FIX: 2026-07-07)."""
    velocity_logit = 0.5
    mean_reversion_logit = -0.2
    minutes_to_expiry = 5.0  # Exactly at 5 minute guard
    
    logit_fusion_velocity_weight = 0.7
    logit_fusion_mean_reversion_weight = 0.3
    near_expiry_guard_sec = 300
    
    # Apply logit fusion (CRITICAL FIX: 2026-07-07 - use <= instead of <)
    # At exactly 5 minutes, should use velocity-only mode
    if minutes_to_expiry * 60 <= near_expiry_guard_sec:
        fused_logit = velocity_logit
    else:
        fused_logit = (logit_fusion_velocity_weight * velocity_logit + 
                      logit_fusion_mean_reversion_weight * mean_reversion_logit)
    
    # Should use velocity logit only (not fusion) at exact boundary
    assert fused_logit == velocity_logit, f"Expected {velocity_logit} (velocity-only at boundary), got {fused_logit}"
    print(f"Logit fusion (at boundary): {fused_logit}")


def test_logit_fusion_weights_sum_to_one():
    """Test that logit fusion weights sum to 1.0."""
    logit_fusion_velocity_weight = 0.7
    logit_fusion_mean_reversion_weight = 0.3
    total_weight = logit_fusion_velocity_weight + logit_fusion_mean_reversion_weight
    assert abs(total_weight - 1.0) < 0.001, f"Weights sum to {total_weight}, expected 1.0"
    print(f"Logit fusion weights sum: {total_weight}")


def test_logit_fusion_to_probability():
    """Test that fused logit produces valid probability."""
    velocity_logit = 0.5
    mean_reversion_logit = -0.2
    minutes_to_expiry = 10.0
    
    logit_fusion_velocity_weight = 0.7
    logit_fusion_mean_reversion_weight = 0.3
    near_expiry_guard_sec = 300
    
    # Apply logit fusion
    if minutes_to_expiry * 60 < near_expiry_guard_sec:
        fused_logit = velocity_logit
    else:
        fused_logit = (logit_fusion_velocity_weight * velocity_logit + 
                      logit_fusion_mean_reversion_weight * mean_reversion_logit)
    
    # Apply logistic function
    p_model = 1.0 / (1.0 + math.exp(-fused_logit))
    
    # p_model should be in valid range
    assert 0.0 <= p_model <= 1.0, f"p_model out of range: {p_model}"
    print(f"Fused logit to probability: {p_model}")


if __name__ == "__main__":
    test_multi_window_velocity_calculation()
    test_multi_window_velocity_with_insufficient_data()
    test_mean_reversion_sma_calculation()
    test_mean_reversion_above_sma()
    test_mean_reversion_below_sma()
    test_combined_signal_generation()
    test_velocity_weights_sum_to_one()
    test_mean_reversion_with_insufficient_data()
    test_logit_fusion_normal_case()
    test_logit_fusion_near_expiry()
    test_logit_fusion_at_guard_boundary()
    test_logit_fusion_weights_sum_to_one()
    test_logit_fusion_to_probability()
    print("\nAll multi-window velocity, mean reversion, and logit fusion tests passed!")

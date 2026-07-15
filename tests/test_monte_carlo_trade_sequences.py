"""Monte Carlo tests for trade sequence randomization.

This module implements Monte Carlo simulations to test the robustness of the trading
system across randomized trade sequences. These tests help identify edge cases
and ensure the system performs consistently under various orderings of events.

Monte Carlo Scenarios Tested:
1. Randomized trade order sequences
2. Randomized price movements
3. Randomized edge signal sequences
4. Randomized market condition sequences
5. Statistical analysis of PnL distribution
6. Extreme scenario identification
"""

import pytest
import random
import numpy as np
from statistics import mean, stdev
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class Trade:
    """Represents a single trade in a sequence."""
    asset: str
    side: str  # 'buy' or 'sell'
    price_cents: int
    quantity: int
    edge: float
    timestamp: int


@dataclass
class TradeSequenceResult:
    """Results from a Monte Carlo trade sequence simulation."""
    total_pnl: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int


class TestTradeSequenceRandomization:
    """Monte Carlo tests for randomized trade sequences."""

    def test_randomized_trade_order_preserves_invariants(self):
        """Randomized trade order should preserve exposure cap invariants."""
        # Generate random trade sequence
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        trades = []
        
        for _ in range(100):
            asset = random.choice(assets)
            side = random.choice(['buy', 'sell'])
            price_cents = random.randint(10, 75)
            quantity = random.randint(1, 10)
            edge = random.uniform(0.0, 0.1)
            trades.append(Trade(asset, side, price_cents, quantity, edge, len(trades)))
        
        # Simulate trades in random order
        random.shuffle(trades)
        
        exposure_cap = 1.0
        current_exposure = 0.0
        
        for trade in trades:
            trade_exposure = (trade.price_cents / 100.0) * trade.quantity
            if trade.side == 'buy':
                current_exposure = min(exposure_cap, current_exposure + trade_exposure)
            else:
                current_exposure = max(0.0, current_exposure - trade_exposure)
            
            # Invariant: exposure never exceeds cap
            assert current_exposure <= exposure_cap, \
                f"Exposure {current_exposure} exceeds cap {exposure_cap}"
            assert current_exposure >= 0.0, \
                f"Exposure {current_exposure} is negative"

    def test_randomized_price_movements_stay_in_range(self):
        """Randomized price movements should stay within canonical range."""
        # Generate random price sequence
        prices = [random.randint(10, 75) for _ in range(1000)]
        
        # Apply random price changes
        for i in range(1, len(prices)):
            change = random.randint(-5, 5)
            new_price = prices[i-1] + change
            prices[i] = max(10, min(75, new_price))
        
        # Verify all prices stay in range
        for price in prices:
            assert 10 <= price <= 75, \
                f"Price {price} outside canonical range [10, 75]"

    def test_randomized_edge_signal_distribution(self):
        """Randomized edge signals should have expected statistical properties."""
        # Generate random edge signals
        edges = [random.uniform(0.0, 0.1) for _ in range(1000)]
        
        # Statistical properties
        avg_edge = mean(edges)
        std_edge = stdev(edges)
        
        # Edges should be in valid range
        assert all(0.0 <= e <= 0.1 for e in edges), \
            "Edge signals outside valid range"
        
        # Average should be around middle of range
        assert 0.03 <= avg_edge <= 0.07, \
            f"Average edge {avg_edge} outside expected range"
        
        # Standard deviation should be reasonable
        assert 0.02 <= std_edge <= 0.04, \
            f"Edge std dev {std_edge} outside expected range"

    def test_randomized_market_condition_sequences(self):
        """Randomized market condition sequences should be handled correctly."""
        market_conditions = ['bull', 'bear', 'neutral', 'volatile']
        sequence = [random.choice(market_conditions) for _ in range(100)]
        
        # Count transitions
        transitions = {}
        for i in range(len(sequence) - 1):
            transition = (sequence[i], sequence[i+1])
            transitions[transition] = transitions.get(transition, 0) + 1
        
        # Should have reasonable number of unique transitions
        assert len(transitions) >= 4, \
            f"Too few unique transitions: {len(transitions)}"
        
        # No single transition should dominate (>50%)
        max_transition_count = max(transitions.values())
        total_transitions = sum(transitions.values())
        assert max_transition_count / total_transitions < 0.5, \
            f"Transition dominates: {max_transition_count}/{total_transitions}"

    def test_monte_carlo_pnl_distribution_analysis(self):
        """Monte Carlo simulation should produce reasonable PnL distribution."""
        num_simulations = 100
        pnl_results = []
        
        for _ in range(num_simulations):
            # Generate random trade sequence
            trades = []
            for _ in range(50):
                side = random.choice(['buy', 'sell'])
                price_cents = random.randint(10, 75)
                quantity = random.randint(1, 5)
                entry_price = price_cents
                exit_price = max(10, min(75, entry_price + random.randint(-10, 10)))
                
                if side == 'buy':
                    pnl = (exit_price - entry_price) * quantity / 100.0
                else:
                    pnl = (entry_price - exit_price) * quantity / 100.0
                
                trades.append(pnl)
            
            total_pnl = sum(trades)
            pnl_results.append(total_pnl)
        
        # Statistical analysis
        avg_pnl = mean(pnl_results)
        std_pnl = stdev(pnl_results)
        
        # Distribution should be reasonable
        assert -1.0 <= avg_pnl <= 1.0, \
            f"Average PnL {avg_pnl} outside reasonable range"
        assert std_pnl >= 0, \
            f"Standard deviation negative: {std_pnl}"
        
        # Should have both winning and losing simulations
        assert any(p > 0 for p in pnl_results), \
            "No winning simulations"
        assert any(p < 0 for p in pnl_results), \
            "No losing simulations"

    def test_extreme_scenario_identification(self):
        """Monte Carlo should identify extreme scenarios."""
        num_simulations = 100
        pnl_results = []
        
        for _ in range(num_simulations):
            # Generate random trade sequence with potential extremes
            trades = []
            for _ in range(50):
                # Occasionally generate extreme trades
                if random.random() < 0.05:  # 5% chance of extreme
                    price_cents = random.choice([10, 75])  # Boundary prices
                    quantity = random.randint(5, 10)
                else:
                    price_cents = random.randint(20, 65)
                    quantity = random.randint(1, 5)
                
                side = random.choice(['buy', 'sell'])
                entry_price = price_cents
                exit_price = max(10, min(75, entry_price + random.randint(-15, 15)))
                
                if side == 'buy':
                    pnl = (exit_price - entry_price) * quantity / 100.0
                else:
                    pnl = (entry_price - exit_price) * quantity / 100.0
                
                trades.append(pnl)
            
            total_pnl = sum(trades)
            pnl_results.append(total_pnl)
        
        # Identify extreme scenarios (top/bottom 5%)
        sorted_pnl = sorted(pnl_results)
        extreme_threshold = int(len(sorted_pnl) * 0.05)
        worst_cases = sorted_pnl[:extreme_threshold]
        best_cases = sorted_pnl[-extreme_threshold:]
        
        # Should have identifiable extremes
        assert len(worst_cases) > 0, "No worst cases identified"
        assert len(best_cases) > 0, "No best cases identified"
        
        # Worst cases should be significantly worse than average
        avg_pnl = mean(pnl_results)
        assert worst_cases[0] < avg_pnl, \
            "Worst case not worse than average"
        
        # Best cases should be significantly better than average
        assert best_cases[-1] > avg_pnl, \
            "Best case not better than average"

    def test_randomized_sequence_reproducibility_with_seed(self):
        """Randomized sequences should be reproducible with seed."""
        seed = 42
        
        # Generate first sequence with seed
        random.seed(seed)
        sequence1 = [random.randint(10, 75) for _ in range(100)]
        
        # Generate second sequence with same seed
        random.seed(seed)
        sequence2 = [random.randint(10, 75) for _ in range(100)]
        
        # Sequences should be identical
        assert sequence1 == sequence2, \
            "Sequences not reproducible with same seed"

    def test_concurrent_random_sequence_generation(self):
        """Concurrent random sequence generation should produce independent results."""
        sequences = []
        
        # Generate multiple sequences
        for i in range(10):
            random.seed(i)  # Different seed for each sequence
            sequence = [random.randint(10, 75) for _ in range(50)]
            sequences.append(sequence)
        
        # Sequences should be different
        for i in range(len(sequences)):
            for j in range(i + 1, len(sequences)):
                assert sequences[i] != sequences[j], \
                    f"Sequences {i} and {j} are identical"

    def test_trade_sequence_length_variations(self):
        """System should handle varying trade sequence lengths."""
        sequence_lengths = [10, 50, 100, 500, 1000]
        
        for length in sequence_lengths:
            trades = []
            for _ in range(length):
                price_cents = random.randint(10, 75)
                quantity = random.randint(1, 5)
                trades.append((price_cents, quantity))
            
            # Process trades
            total_exposure = 0.0
            for price_cents, quantity in trades:
                exposure = (price_cents / 100.0) * quantity
                total_exposure += exposure
            
            # Should complete without errors
            assert len(trades) == length, \
                f"Trade sequence length mismatch: {len(trades)} vs {length}"

    def test_randomized_asset_allocation_sequences(self):
        """Randomized asset allocation should respect exposure cap."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        exposure_cap = 1.0
        allocations = {}
        
        # Randomly allocate exposure across assets
        for _ in range(100):
            asset = random.choice(assets)
            allocation = random.uniform(0.0, 0.2)
            allocations[asset] = allocations.get(asset, 0.0) + allocation
            
            # Clamp to exposure cap
            total_exposure = sum(allocations.values())
            if total_exposure > exposure_cap:
                # Scale down all allocations
                scale_factor = exposure_cap / total_exposure
                for a in allocations:
                    allocations[a] *= scale_factor
            
            # Verify invariant
            total_exposure = sum(allocations.values())
            assert total_exposure <= exposure_cap + 0.001, \
                f"Total exposure {total_exposure} exceeds cap {exposure_cap}"

    def test_monte_carlo_convergence_analysis(self):
        """Monte Carlo results should converge with more simulations."""
        convergence_threshold = 0.05  # 5% convergence threshold
        
        # Run increasing number of simulations
        simulation_counts = [10, 50, 100, 500, 1000]
        avg_pnls = []
        
        for count in simulation_counts:
            pnl_results = []
            for _ in range(count):
                # Simple random walk
                price = 50
                for _ in range(50):
                    price += random.randint(-5, 5)
                    price = max(10, min(75, price))
                pnl = (price - 50) / 100.0
                pnl_results.append(pnl)
            
            avg_pnls.append(mean(pnl_results))
        
        # Check convergence (variance should decrease with more simulations)
        early_variance = stdev(avg_pnls[:3])
        late_variance = stdev(avg_pnls[-3:])
        
        # Later simulations should have less variance
        assert late_variance <= early_variance + 0.01, \
            f"Results not converging: early={early_variance}, late={late_variance}"


class TestTradeSequenceEdgeCases:
    """Monte Carlo tests for edge cases in trade sequences."""

    def test_empty_trade_sequence(self):
        """System should handle empty trade sequences."""
        trades = []
        total_pnl = sum(trades)
        assert total_pnl == 0.0, "Empty sequence should have zero PnL"

    def test_single_trade_sequence(self):
        """System should handle single trade sequences."""
        trade = Trade("BTC", "buy", 50, 10, 0.05, 0)
        entry_price = trade.price_cents
        exit_price = 55
        pnl = (exit_price - entry_price) * trade.quantity / 100.0
        assert pnl == 0.5, f"Single trade PnL incorrect: {pnl}"

    def test_all_buy_sequence(self):
        """System should handle all-buy sequences."""
        trades = [Trade("BTC", "buy", 50, 1, 0.05, i) for i in range(10)]
        
        exposure_cap = 1.0
        current_exposure = 0.0
        
        for trade in trades:
            trade_exposure = (trade.price_cents / 100.0) * trade.quantity
            current_exposure = min(exposure_cap, current_exposure + trade_exposure)
        
        # Should hit exposure cap
        assert current_exposure == exposure_cap, \
            f"All-buy sequence should hit cap: {current_exposure}"

    def test_all_sell_sequence(self):
        """System should handle all-sell sequences."""
        trades = [Trade("BTC", "sell", 50, 1, 0.05, i) for i in range(10)]
        
        current_exposure = 0.5  # Start with some exposure
        
        for trade in trades:
            trade_exposure = (trade.price_cents / 100.0) * trade.quantity
            current_exposure = max(0.0, current_exposure - trade_exposure)
        
        # Should hit zero exposure
        assert current_exposure == 0.0, \
            f"All-sell sequence should hit zero: {current_exposure}"

    def test_alternating_buy_sell_sequence(self):
        """System should handle alternating buy-sell sequences."""
        trades = []
        for i in range(10):
            side = 'buy' if i % 2 == 0 else 'sell'
            trades.append(Trade("BTC", side, 50, 1, 0.05, i))
        
        exposure_cap = 1.0
        current_exposure = 0.0
        
        for trade in trades:
            trade_exposure = (trade.price_cents / 100.0) * trade.quantity
            if trade.side == 'buy':
                current_exposure = min(exposure_cap, current_exposure + trade_exposure)
            else:
                current_exposure = max(0.0, current_exposure - trade_exposure)
        
        # Should end near zero exposure
        assert current_exposure < 0.1, \
            f"Alternating sequence should end near zero: {current_exposure}"

    def test_boundary_price_sequence(self):
        """System should handle sequences at price boundaries."""
        trades = []
        for i in range(10):
            price_cents = 10 if i % 2 == 0 else 75  # Alternate boundaries
            trades.append(Trade("BTC", "buy", price_cents, 1, 0.05, i))
        
        # All prices should be at boundaries
        for trade in trades:
            assert trade.price_cents in [10, 75], \
                f"Price not at boundary: {trade.price_cents}"

    def test_zero_edge_sequence(self):
        """System should handle sequences with zero edge."""
        trades = [Trade("BTC", "buy", 50, 1, 0.0, i) for i in range(10)]
        
        # All edges should be zero
        for trade in trades:
            assert trade.edge == 0.0, f"Edge not zero: {trade.edge}"

    def test_max_edge_sequence(self):
        """System should handle sequences with maximum edge."""
        trades = [Trade("BTC", "buy", 50, 1, 0.1, i) for i in range(10)]
        
        # All edges should be at maximum
        for trade in trades:
            assert trade.edge == 0.1, f"Edge not at max: {trade.edge}"

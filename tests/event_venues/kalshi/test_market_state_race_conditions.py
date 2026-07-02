"""Tests for race condition fixes in KalshiMarketStateStore."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore


class TestMarketStateRaceConditions:
    """Test race condition fixes in market state store."""

    def setup_method(self):
        """Set up a fresh store for each test."""
        self.store = KalshiMarketStateStore()

    def test_concurrent_get_or_create_same_ticker(self):
        """Test that concurrent calls to _get_or_create for the same ticker don't create duplicate states.
        
        This tests the race condition fix where multiple threads could simultaneously
        create state objects for the same ticker, leading to duplicate states.
        """
        ticker = "KXBTC15M-TEST"
        num_threads = 10
        states = []
        lock = threading.Lock()

        def create_state():
            state = self.store._get_or_create(ticker)
            with lock:
                states.append(state)

        # Create multiple threads that all try to get/create the same ticker
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(create_state) for _ in range(num_threads)]
            for future in futures:
                future.result()

        # All threads should have received the same state object
        assert len(states) == num_threads
        first_state = states[0]
        for state in states[1:]:
            assert state is first_state, "All threads should receive the same state object"

        # Verify only one state was created in the store
        assert ticker in self.store._states
        assert len([k for k in self.store._states.keys() if k == ticker]) == 1

    def test_concurrent_get_or_create_different_tickers(self):
        """Test that concurrent calls to _get_or_create for different tickers work correctly."""
        tickers = [f"KXBTC15M-T{i}" for i in range(10)]
        states = []
        lock = threading.Lock()

        def create_state(ticker):
            state = self.store._get_or_create(ticker)
            with lock:
                states.append((ticker, state))

        # Create multiple threads that each create a different ticker
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_state, ticker) for ticker in tickers]
            for future in futures:
                future.result()

        # All tickers should have been created
        assert len(states) == len(tickers)
        for ticker, state in states:
            assert state.ticker == ticker
            assert ticker in self.store._states

        # Verify no duplicate states
        assert len(self.store._states) == len(tickers)

    def test_global_lock_prevents_duplicate_creation(self):
        """Test that the global lock in _get_or_create prevents duplicate state creation."""
        ticker = "KXETH15M-TEST"
        creation_count = 0
        original_states_dict = self.store._states
        lock = threading.Lock()

        def tracked_get_or_create():
            nonlocal creation_count
            # Call the actual _get_or_create method
            state = self.store._get_or_create(ticker)
            with lock:
                creation_count += 1
            return state

        # Simulate concurrent access
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(tracked_get_or_create) for _ in range(5)]
            results = [future.result() for future in futures]

        # All calls should return the same state
        assert all(r is results[0] for r in results)
        
        # Only one state should exist in the store
        assert len([k for k in self.store._states.keys() if k == ticker]) == 1

    def test_get_or_create_idempotent(self):
        """Test that calling _get_or_create multiple times for the same ticker returns the same state."""
        ticker = "KXSOL15M-TEST"
        
        state1 = self.store._get_or_create(ticker)
        state2 = self.store._get_or_create(ticker)
        state3 = self.store._get_or_create(ticker)

        assert state1 is state2
        assert state2 is state3
        assert state1.ticker == ticker

        # Verify only one entry in the states dict
        assert len([k for k in self.store._states.keys() if k == ticker]) == 1

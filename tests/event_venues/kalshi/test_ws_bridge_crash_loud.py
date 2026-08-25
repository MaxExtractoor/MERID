"""Tests for WS bridge crash-loud separation and hard wiring.

Tests the canonical bridge (merid.event_venues.kalshi.ws_bridge) crash-loud
features including:
- _spawn crash-loud wrapper
- Health monitor hardening
- Singleton pattern
- Event counter and logging

NOTE: LEGACY: Tests deprecated merid.event_venues.kalshi.ws_bridge - 15m lean stack uses merid_core.kalshi.ws_bridge
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from merid.event_venues.kalshi.ws_bridge import (
    KalshiWebSocketBridge,
    _spawn,
    get_ws_bridge,
)


pytestmark = pytest.mark.skip(reason="P3-LEGACY: TRACKER-030: Deprecated `merid.event_venues.kalshi.ws_bridge`")


class TestSpawnCrashLoudWrapper:
    """Test the _spawn crash-loud wrapper for background tasks."""

    @pytest.mark.asyncio
    async def test_spawn_logs_start(self, caplog):
        """_spawn should log START when task begins."""
        async def dummy_coro():
            await asyncio.sleep(0.01)
        
        with caplog.at_level("INFO"):
            task = _spawn("TEST-TASK", dummy_coro())
            await task
        
        assert any("TEST-TASK" in record.message and "START" in record.message 
                  for record in caplog.records)

    @pytest.mark.asyncio
    async def test_spawn_logs_crash(self, caplog):
        """_spawn should log crash when task fails."""
        async def failing_coro():
            raise ValueError("Test crash")
        
        with caplog.at_level("ERROR"):
            task = _spawn("FAILING-TASK", failing_coro())
            with pytest.raises(ValueError, match="Test crash"):
                await task
        
        assert any("FAILING-TASK" in record.message and "crashed" in record.message 
                  for record in caplog.records)

    @pytest.mark.asyncio
    async def test_spawn_bubbles_exception(self):
        """_spawn should re-raise exceptions, not swallow them."""
        async def failing_coro():
            raise RuntimeError("Test error")
        
        task = _spawn("TEST", failing_coro())
        with pytest.raises(RuntimeError, match="Test error"):
            await task


class TestHealthMonitorHardening:
    """Test health monitor defensive implementation."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        yield
        # Reset after test
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False

    @pytest.fixture
    def bridge(self):
        """Create a bridge instance for testing."""
        ws = MagicMock()
        ws.config = MagicMock()
        ws.config.api_key_id = "test_key"
        ws.config.private_key_path = "test_path"
        ws.config.ws_base_url = "wss://test.com"
        ws.config.use_demo = True
        
        bridge = KalshiWebSocketBridge(ws=ws)
        # Initialize shutdown event in __init__ (as per our changes)
        bridge._shutdown = asyncio.Event()
        bridge._queue = asyncio.Queue(maxsize=32768)
        bridge._events_seen = 0
        bridge._events_forwarded = 0
        bridge._events_dropped = 0
        return bridge

    @pytest.mark.asyncio
    async def test_health_monitor_uses_shutdown_event(self, bridge, caplog):
        """Health monitor should use self._shutdown directly, not lazy init."""
        with caplog.at_level("INFO"):
            # Start health monitor
            task = asyncio.create_task(bridge._health_monitor())
            
            # Give it time to log startup
            await asyncio.sleep(0.1)
            
            # Cancel the task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Should log "Starting health monitor"
        assert any("WS-HEALTH-MONITOR" in record.message and "Starting" in record.message 
                  for record in caplog.records)

    @pytest.mark.asyncio
    async def test_health_monitor_logs_metrics(self, bridge, caplog):
        """Health monitor should log events_seen and queue_size."""
        with caplog.at_level("INFO"):
            # Set some metrics
            bridge._events_seen = 100
            bridge._events_forwarded = 95
            bridge._events_dropped = 5
            
            # Start health monitor
            task = asyncio.create_task(bridge._health_monitor())
            
            # Wait for at least one health log
            await asyncio.sleep(0.35)  # Wait for first health check (30s interval reduced for test)
            
            # Cancel the task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Should log health metrics
        assert any("WS-HEALTH" in record.message and "events_seen" in record.message 
                  for record in caplog.records)


class TestSingletonPattern:
    """Test singleton pattern for canonical bridge."""

    def test_singleton_returns_same_instance(self):
        """get_ws_bridge should return the same instance on subsequent calls."""
        # Reset singleton
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        
        # Get first instance
        bridge1 = get_ws_bridge()
        
        # Get second instance
        bridge2 = get_ws_bridge()
        
        # Should be the same instance
        assert bridge1 is bridge2

    def test_singleton_prevents_double_instantiation(self):
        """Direct instantiation should raise RuntimeError if instance already exists."""
        # Reset singleton
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        
        # Create first instance via singleton
        get_ws_bridge()
        
        # Attempt direct instantiation should fail
        with pytest.raises(RuntimeError, match="instantiated twice in one process"):
            KalshiWebSocketBridge()

    def test_singleton_allows_reinstantiation_after_reset(self):
        """After resetting singleton, new instance should be allowed."""
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        
        # Create first instance
        bridge1 = get_ws_bridge()
        
        # Reset singleton
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        
        # New instance should be allowed
        bridge2 = KalshiWebSocketBridge()
        
        # Should be different instances
        assert bridge1 is not bridge2


class TestEventCounterAndLogging:
    """Test event counter and logging in _enqueue_event."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        yield
        # Reset after test
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False

    @pytest.fixture
    def bridge(self):
        """Create a bridge instance for testing."""
        ws = MagicMock()
        ws.config = MagicMock()
        ws.config.api_key_id = "test_key"
        ws.config.private_key_path = "test_path"
        ws.config.ws_base_url = "wss://test.com"
        ws.config.use_demo = True
        
        bridge = KalshiWebSocketBridge(ws=ws)
        bridge._shutdown = asyncio.Event()
        bridge._queue = asyncio.Queue(maxsize=32768)
        bridge._events_seen = 0
        bridge._events_forwarded = 0
        bridge._events_dropped = 0
        # Use defaultdict to avoid KeyError
        from collections import defaultdict
        bridge._interval_type_counts = defaultdict(int)
        bridge._type_counts = defaultdict(int)
        return bridge

    def test_enqueue_event_increments_counter(self, bridge):
        """_enqueue_event should increment events_seen counter."""
        initial_count = bridge._events_seen
        
        # Enqueue an event
        bridge._enqueue_event({"type": "orderbook", "ticker": "KXBTC15M-24JUN26"})
        
        # Counter should be incremented
        assert bridge._events_seen == initial_count + 1

    def test_enqueue_event_logs_periodically(self, bridge, caplog):
        """_enqueue_event should log every 1000 events."""
        with caplog.at_level("INFO"):
            # Enqueue 1001 events
            for i in range(1001):
                bridge._enqueue_event({"type": "orderbook", "ticker": "KXBTC15M-24JUN26"})
        
        # Should have logged at least once (at event 1 and 1001)
        assert any("WS-ENQUEUE" in record.message and "first_or_kth event" in record.message 
                  for record in caplog.records)


class TestCanonicalBridgeImports:
    """Test that production code uses canonical bridge imports."""

    def test_no_legacy_bridge_imports_in_codebase(self):
        """No code should import from the removed legacy bridge."""
        import os
        import re
        
        # Search only key directories (not entire codebase) for performance
        search_dirs = [
            "c:\\Dev\\MERID\\merid",
            "c:\\Dev\\MERID\\web",
            "c:\\Dev\\MERID\\scripts",
        ]
        
        # Search for legacy bridge imports in Python files
        legacy_imports = []
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                # Skip test files and __pycache__
                dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git", "venv", "env", "tests"]]
                
                for file in files:
                    if file.endswith(".py"):
                        filepath = os.path.join(root, file)
                        # Skip the find_kalshi_ws_imports.py script itself
                        if "find_kalshi_ws_imports.py" in filepath:
                            continue
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                lines = f.readlines()
                            
                            # Check for actual legacy bridge imports (not comments)
                            for line in lines:
                                line = line.strip()
                                # Skip comments and empty lines
                                if line.startswith("#") or not line:
                                    continue
                                # Check for actual import statement
                                if "merid_core.kalshi.ws_bridge" in line and ("import" in line or "from" in line):
                                    legacy_imports.append((filepath, line))
                        except Exception:
                            pass
        
        # Should have no legacy bridge imports
        assert len(legacy_imports) == 0, f"Found legacy bridge imports in: {legacy_imports}"

    def test_ws_bridge_file_exists(self):
        """The canonical ws_bridge file should exist."""
        import os
        canonical_path = "c:\\Dev\\MERID\\merid\\event_venues\\kalshi\\ws_bridge.py"
        assert os.path.exists(canonical_path), "Canonical ws_bridge should exist"

    def test_legacy_bridge_file_removed(self):
        """The legacy ws_bridge file should not exist."""
        import os
        legacy_path = "c:\\Dev\\MERID\\merid_core\\kalshi\\ws_bridge.py"
        assert not os.path.exists(legacy_path), "Legacy ws_bridge should be removed"


class TestSimplifiedCoalescing:
    """Test simplified coalescing logic for queue pressure management."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        yield
        # Reset after test
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False

    @pytest.fixture
    def bridge(self):
        """Create a bridge instance for testing."""
        ws = MagicMock()
        ws.config = MagicMock()
        ws.config.api_key_id = "test_key"
        ws.config.private_key_path = "test_path"
        ws.config.ws_base_url = "wss://test.com"
        ws.config.use_demo = True
        
        bridge = KalshiWebSocketBridge(ws=ws)
        bridge._shutdown = asyncio.Event()
        # Use queue.Queue for thread-safe operations
        import queue
        bridge._queue = queue.Queue(maxsize=10000)
        bridge._events_seen = 0
        bridge._events_forwarded = 0
        bridge._events_dropped = 0
        bridge._events_coalesced = 0
        return bridge

    def test_coalescing_keeps_latest_per_ticker(self, bridge):
        """Coalescing should keep only the latest event per (ticker, kind)."""
        # Add multiple orderbook deltas for same ticker
        for i in range(5):
            bridge._enqueue_event({
                "type": "orderbook_delta",
                "ticker": "KXBTC15M-24JUN26",
                "sequence": i
            })
        
        # Coalesce
        bridge._coalesce_queue()
        
        # Should have only 1 event (the latest)
        remaining = []
        while not bridge._queue.empty():
            remaining.append(bridge._queue.get_nowait())
        
        assert len(remaining) == 1
        assert remaining[0]["sequence"] == 4  # Last one

    def test_coalescing_preserves_critical_events(self, bridge):
        """Critical events (fills, portfolio) should never be coalesced."""
        # Add multiple fills for same ticker
        for i in range(5):
            bridge._enqueue_event({
                "type": "fill",
                "ticker": "KXBTC15M-24JUN26",
                "fill_id": i
            })
        
        # Coalesce
        bridge._coalesce_queue()
        
        # Should have all 5 fills preserved
        remaining = []
        while not bridge._queue.empty():
            remaining.append(bridge._queue.get_nowait())
        
        assert len(remaining) == 5
        fill_ids = [evt["fill_id"] for evt in remaining]
        assert fill_ids == [0, 1, 2, 3, 4]

    def test_coalescing_handles_mixed_event_types(self, bridge):
        """Coalescing should handle mix of critical and coalescable events."""
        # Add orderbook deltas (coalescable)
        for i in range(3):
            bridge._enqueue_event({
                "type": "orderbook_delta",
                "ticker": "KXBTC15M-24JUN26",
                "sequence": i
            })
        
        # Add fills (critical)
        for i in range(2):
            bridge._enqueue_event({
                "type": "fill",
                "ticker": "KXBTC15M-24JUN26",
                "fill_id": i
            })
        
        # Add more orderbook deltas
        for i in range(3, 6):
            bridge._enqueue_event({
                "type": "orderbook_delta",
                "ticker": "KXBTC15M-24JUN26",
                "sequence": i
            })
        
        # Coalesce
        bridge._coalesce_queue()
        
        # Should have 1 orderbook delta (latest) + 2 fills (all preserved)
        remaining = []
        while not bridge._queue.empty():
            remaining.append(bridge._queue.get_nowait())
        
        assert len(remaining) == 3
        orderbook_events = [evt for evt in remaining if evt["type"] == "orderbook_delta"]
        fill_events = [evt for evt in remaining if evt["type"] == "fill"]
        
        assert len(orderbook_events) == 1
        assert orderbook_events[0]["sequence"] == 5  # Latest
        assert len(fill_events) == 2

    def test_coalescing_handles_multiple_tickers(self, bridge):
        """Coalescing should keep latest per ticker separately."""
        # Add events for multiple tickers
        tickers = ["KXBTC15M-24JUN26", "KXETH15M-24JUN26", "KXSOL15M-24JUN26"]
        
        for ticker in tickers:
            for i in range(3):
                bridge._enqueue_event({
                    "type": "orderbook_delta",
                    "ticker": ticker,
                    "sequence": i
                })
        
        # Coalesce
        bridge._coalesce_queue()
        
        # Should have 3 events (1 per ticker, the latest)
        remaining = []
        while not bridge._queue.empty():
            remaining.append(bridge._queue.get_nowait())
        
        assert len(remaining) == 3
        remaining_tickers = {evt["ticker"] for evt in remaining}
        assert remaining_tickers == set(tickers)
        
        # All should be sequence 2 (latest)
        for evt in remaining:
            assert evt["sequence"] == 2


class TestCallbackWiringLogging:
    """Test callback wiring logging in start() method."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        from merid.event_venues.kalshi import ws_bridge
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False
        yield
        # Reset after test
        ws_bridge._bridge = None
        ws_bridge.KalshiWebSocketBridge._instance_created = False

    @pytest.fixture
    def bridge(self):
        """Create a bridge instance for testing."""
        ws = MagicMock()
        ws.config = MagicMock()
        ws.config.api_key_id = "test_key"
        ws.config.private_key_path = "test_path"
        ws.config.ws_base_url = "wss://test.com"
        ws.config.use_demo = True
        ws.listen = AsyncMock()
        
        bridge = KalshiWebSocketBridge(ws=ws)
        bridge._shutdown = asyncio.Event()
        bridge._queue = asyncio.Queue(maxsize=32768)
        bridge._events_seen = 0
        bridge._events_forwarded = 0
        bridge._events_dropped = 0
        bridge._circuit_breaker_tripped = False
        bridge._rest_fallback_mode = False
        return bridge

    def test_start_logs_callback_wiring(self):
        """start() method should have callback wiring log statement."""
        # Read the source file to verify the log statement exists
        import merid.event_venues.kalshi.ws_bridge as ws_bridge_module
        source_file = ws_bridge_module.__file__
        
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should have callback wiring log
        assert "Starting WS listener with callback" in content

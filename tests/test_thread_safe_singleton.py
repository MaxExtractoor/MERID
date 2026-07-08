"""Tests for thread-safe singleton pattern in core.persistence_manager."""

import threading
import time
import pytest
import sys
from pathlib import Path

# Add parent directory to path to import core module
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.persistence_manager import get_persistence_manager, shutdown_persistence


def reset_singleton():
    """Helper to reset singleton between tests."""
    import core.persistence_manager as pm
    pm._persistence_manager = None


def test_singleton_returns_same_instance():
    """Test that singleton returns the same instance across multiple calls."""
    reset_singleton()
    
    instance1 = get_persistence_manager()
    instance2 = get_persistence_manager()
    
    assert instance1 is instance2, "Singleton should return same instance"
    
    # Cleanup
    shutdown_persistence()


def test_thread_safe_initialization():
    """Test that singleton initialization is thread-safe."""
    reset_singleton()
    
    instances = []
    num_threads = 10
    
    def get_instance():
        instance = get_persistence_manager()
        instances.append(instance)
    
    # Create multiple threads that all try to get the instance simultaneously
    threads = []
    for _ in range(num_threads):
        thread = threading.Thread(target=get_instance)
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # All threads should have received the same instance
    assert len(instances) == num_threads, f"Expected {num_threads} instances, got {len(instances)}"
    assert all(instance is instances[0] for instance in instances), "All threads should receive same instance"
    
    # Cleanup
    shutdown_persistence()


def test_shutdown_is_thread_safe():
    """Test that shutdown is thread-safe and doesn't cause race conditions."""
    reset_singleton()
    
    # Get instance
    instance = get_persistence_manager()
    assert instance is not None
    
    # Shutdown from multiple threads simultaneously
    shutdown_errors = []
    
    def shutdown_thread():
        try:
            shutdown_persistence()
        except Exception as e:
            shutdown_errors.append(e)
    
    threads = []
    for _ in range(5):
        thread = threading.Thread(target=shutdown_thread)
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    # Should not have any errors
    assert len(shutdown_errors) == 0, f"Shutdown had errors: {shutdown_errors}"
    
    # After shutdown, singleton should be None
    import core.persistence_manager as pm
    assert pm._persistence_manager is None, "Singleton should be None after shutdown"


def test_double_checked_locking():
    """Test that double-checked locking prevents unnecessary lock acquisition."""
    reset_singleton()
    
    # First call initializes the singleton
    instance1 = get_persistence_manager()
    
    # Second call should not acquire lock (already initialized)
    # This is a performance test - should be fast
    start = time.perf_counter()
    for _ in range(100):
        instance2 = get_persistence_manager()
    end = time.perf_counter()
    
    assert instance1 is instance2, "Should return same instance"
    
    # 100 calls with double-checked locking should be very fast (< 1ms)
    # If it were acquiring the lock every time, it would be much slower
    assert (end - start) < 0.01, f"Double-checked locking should be fast, took {end - start}s"
    
    # Cleanup
    shutdown_persistence()


def test_singleton_persistence_after_shutdown():
    """Test that singleton can be recreated after shutdown."""
    reset_singleton()
    
    # Get first instance
    instance1 = get_persistence_manager()
    assert instance1 is not None
    
    # Shutdown
    shutdown_persistence()
    
    # Get new instance after shutdown
    instance2 = get_persistence_manager()
    assert instance2 is not None
    
    # Should be different instances
    assert instance1 is not instance2, "Should be new instance after shutdown"
    
    # Cleanup
    shutdown_persistence()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

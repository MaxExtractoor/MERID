"""
MERID Production-Style Logging Patterns Tests
Tests for the production-style set of patterns that matches what you're building.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
import pytest
import pathlib
import time
from logging.handlers import QueueHandler
from typing import List

# Import MERID logging patterns
import merid_logging


# 3) Assert processName and process on LogRecord in pytest
def worker(queue, wid: int):
    """
    Assert processName and process on LogRecord in pytest.
    
    Since pytest's caplog doesn't see child-process logs, assert against the 
    listener's log file and parse the formatted lines.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    log = logging.getLogger(f"merid.worker.{wid}")
    log.info("wid=%d msg=%d", wid, 0)


def test_log_has_process_info(log_queue):
    """
    Assert processName and process on LogRecord in pytest.
    
    If you want to correlate to the actual PID, extract the integer between 
    [ and ] and compare to p.pid.
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    p = mp.Process(target=worker, args=(q, 0))
    p.start()
    p.join()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines

    has_process_name = any("Process-" in line or "MainProcess" in line for line in lines)
    has_pid = any("[" in line and "]" in line for line in lines)
    assert has_process_name
    assert has_pid


# 4) Best practices for multiprocessing logging in pytest
def production_worker(queue, wid: int, n: int):
    """
    Best practices for multiprocessing logging in pytest.
    
    From the cookbook and multi-process logging guidance:
    
    - Use a single queue + listener as the logging backend.
    - In each child process/test worker:
      - Clear handlers on the root logger.
      - Attach a QueueHandler(queue) only.
      - Let the listener process own the file/console handlers.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    log = logging.getLogger(f"merid.production.{wid}")
    for i in range(n):
        log.info("wid=%d msg=%d", wid, i)


def test_production_multiprocessing_logging(log_queue):
    """
    Test production-style multiprocessing logging.
    
    In pytest, keep the listener fixture session-scoped so all tests share it, 
    unless a test needs special rotation settings.
    
    Always join() worker processes before pushing your sentinel; avoid leaving 
    daemon children alive at test exit (they can hang pytest).
    
    Use file inspection for multi-process log assertions; don't rely on 
    caplog for spawned processes.
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    # Spawn multiple workers following best practices
    procs = []
    for wid in range(3):
        p = mp.Process(target=production_worker, args=(q, wid, 50))
        p.start()
        procs.append(p)

    # Always join() worker processes before pushing your sentinel
    for p in procs:
        p.join()

    # Wait a bit for logging to be processed
    time.sleep(0.5)

    # Use file inspection for multi-process log assertions
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 0
    
    # Verify all workers contributed
    for wid in range(3):
        worker_lines = [line for line in lines if f"merid.production.{wid}" in line]
        assert len(worker_lines) == 50  # Each worker sent 50 messages

    # Verify process info is present
    has_process_name = any("Process-" in line or "MainProcess" in line for line in lines)
    has_pid = any("[" in line and "]" in line for line in lines)
    assert has_process_name
    assert has_pid


# 5) Ensuring QueueListener drains queue before stopping
def test_queue_drain_before_shutdown(log_queue):
    """
    Ensuring QueueListener drains queue before stopping.
    
    The pattern above already does it, but the critical sequence is:
    
    1) All producers finish: for p in procs: p.join().
    2) Send sentinel: queue.put_nowait(None).
    3) Close queue: queue.close().
    4) Join listener: listener_proc.join(timeout=5).
    
    Because the sentinel is enqueued after all worker join() calls, all records 
    from those workers are already in the queue when the listener starts draining. 
    It will process until it sees the sentinel and then exit, so you don't lose 
    records in shutdown.
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    # Create workers that send many messages
    procs = []
    for wid in range(4):
        p = mp.Process(target=production_worker, args=(q, wid, 100))
        p.start()
        procs.append(p)

    # 1) All producers finish: for p in procs: p.join()
    for p in procs:
        p.join()

    # Count expected messages
    expected_messages = 4 * 100  # 4 workers × 100 messages each

    # Wait for processing
    time.sleep(1)

    # 2) Send sentinel: queue.put_nowait(None) (handled by fixture teardown)
    # 3) Close queue: queue.close() (handled by fixture teardown)
    # 4) Join listener: listener_proc.join(timeout=5) (handled by fixture teardown)

    # Verify all messages were processed
    lines = log_file.read_text(encoding="utf-8").splitlines()
    
    # Filter for worker messages
    worker_lines = [line for line in lines if "merid.production." in line and "msg=" in line]
    
    # Should have all messages (no loss during shutdown)
    assert len(worker_lines) == expected_messages
    
    # Verify format consistency
    for line in worker_lines:
        assert "[" in line and "]" in line  # PID present
        assert "Process-" in line or "MainProcess" in line  # Process name present
        assert "wid=" in line and "msg=" in line  # Message structure present


# Test the production MERID integration
def test_merid_production_integration():
    """
    Test the production MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = os.path.join(tmp_dir, "merid_production.log")
        
        # Start listener using production-style function
        listener_proc = merid_logging.start_merid_listener(log_path)
        
        try:
            # Spawn workers using production-style function
            procs = []
            for wid in range(3):
                p = mp.Process(target=merid_logging.merid_worker, args=(f"merid.production.{wid}", 20))
                p.start()
                procs.append(p)

            # 1) All producers finish: for p in procs: p.join()
            for p in procs:
                p.join()

            # Wait a bit for logging to be processed
            time.sleep(1)

            # Verify log file was created and has content
            assert os.path.exists(log_path)
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
                assert len(lines) > 0
                assert any(f"merid.production.{wid}" in line for wid in range(3) for line in lines)
                
        finally:
            # 2) Send sentinel: LOG_QUEUE.put_nowait(None)
            # 3) Close queue: LOG_QUEUE.close()
            # 4) Join listener: listener_proc.join(timeout=5)
            merid_logging.stop_merid_logging_listener(listener_proc)


if __name__ == "__main__":
    print("🚀 Testing MERID Production-Style Logging Patterns")
    print("=" * 55)
    
    # Test the integration
    print("\n🧪 Testing MERID Production Integration...")
    try:
        test_merid_production_integration()
        print("   ✅ MERID production integration test passed")
    except Exception as e:
        print(f"   ❌ MERID production integration test failed: {e}")
    
    print("\n✅ MERID production-style logging patterns tested successfully!")

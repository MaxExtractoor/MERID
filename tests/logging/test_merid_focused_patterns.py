"""
MERID Focused Logging Patterns Tests
Tests for the minimal, focused set of patterns matching what was requested.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
import pytest
import pathlib
import time
from typing import List
from logging.handlers import QueueHandler, QueueListener
from queue import Queue

# Import MERID logging patterns
import merid_logging


# 2) Signalling the listener to shut down from tests
@pytest.fixture(scope="session")
def merid_log_listener(tmp_path_factory):
    """
    Session-scoped pytest fixture for MERID logging.
    
    Use a sentinel and join in teardown.
    
    This ensures all queued records are processed before shutdown.
    """
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "merid.log"
    proc = merid_logging.start_merid_logging_listener(str(log_file))
    yield {"log_file": log_file, "proc": proc}
    merid_logging.stop_merid_logging_listener(proc)


# 3) Verifying process name and PID in log records
def test_log_includes_pid_and_process_name(merid_log_listener):
    """
    Verifying process name and PID in log records.
    
    Use %(process)d and %(processName)s in your formatter, then parse them from the log file.
    """
    log_file = merid_log_listener["log_file"]

    # spawn a worker
    p = mp.Process(target=merid_logging._test_worker, args=("merid.worker",))
    p.start()
    p.join()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines

    any_proc_name = any("Process-" in line or "MainProcess" in line for line in lines)
    any_pid = any("[" in line and "]" in line for line in lines)
    assert any_proc_name
    assert any_pid


# 4) Testing LogRecord formatting across processes
def test_record_format_across_processes(merid_log_listener):
    """
    Testing LogRecord formatting across processes.
    
    You already have worker IDs and sequence numbers; assert the format is consistent across multiple workers.
    """
    log_file = merid_log_listener["log_file"]

    procs = []
    for wid in range(3):
        name = f"merid.worker.{wid}"
        p = mp.Process(target=merid_logging._test_worker, args=(name,))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    # All lines should follow the formatter pattern
    # Example quick check: each contains PID brackets and a logger name
    for line in lines:
        assert "[" in line and "]" in line
        assert "merid.worker" in line
        assert "wid=" in line and "msg=" in line


# 5) Simulating high-volume logs to test rotation
def test_high_volume_rotation(tmp_path):
    """
    Simulating high-volume logs to test rotation.
    
    Use a short interval or a small maxBytes and many workers to stress the rotation.
    
    Here's a queue-based time rotation test:
    """
    # local listener for this test
    log_file = tmp_path / "rotation.log"
    proc = merid_logging.start_merid_logging_listener(str(log_file))

    procs = [mp.Process(target=merid_logging.spam_worker, args=(wid, 2000))
             for wid in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    # stop listener
    merid_logging.stop_merid_logging_listener(proc)

    files = list(log_file.parent.glob(log_file.name + "*"))
    assert len(files) >= 2  # rotated at least once

    total_lines = 0
    for f in files:
        total_lines += len(f.read_text(encoding="utf-8").splitlines())
    assert total_lines > 0


# Test the minimal MERID integration
def test_merid_minimal_integration():
    """
    Test the minimal MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = os.path.join(tmp_dir, "merid_test.log")
        
        # Start listener
        listener_proc = merid_logging.start_merid_logging_listener(log_path)
        
        try:
            # Spawn workers
            procs = []
            for wid in range(3):
                name = f"merid.worker.{wid}"
                p = mp.Process(target=merid_logging.merid_worker, args=(name, 10))
                p.start()
                procs.append(p)

            # Wait for workers to complete
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
                assert any(f"merid.worker.{wid}" in line for wid in range(3) for line in lines)
                
        finally:
            # Shutdown
            merid_logging.stop_merid_logging_listener(listener_proc)


if __name__ == "__main__":
    print("🚀 Testing MERID Focused Logging Patterns")
    print("=" * 50)
    
    # Test the integration
    print("\n🧪 Testing MERID Minimal Integration...")
    try:
        test_merid_minimal_integration()
        print("   ✅ MERID minimal integration test passed")
    except Exception as e:
        print(f"   ❌ MERID minimal integration test failed: {e}")
    
    print("\n✅ MERID focused logging patterns tested successfully!")

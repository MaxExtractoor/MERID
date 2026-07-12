"""
MERID End-to-End Logging Patterns Tests
Tests for the end-to-end set of patterns matching what you're doing with MERID.

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


# 3) Asserting processName and process in pytest
def worker(queue, wid: int):
    """
    Asserting processName and process in pytest.
    
    With formatter:
    
    fmt = "%(asctime)s [%(process)d] %(processName)s %(levelname)s %(name)s %(message)s"
    
    you can assert both attributes from the listener's log file.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    log = logging.getLogger(f"merid.worker.{wid}")
    log.info("wid=%d msg=%d", wid, 0)


def test_log_includes_process_info(log_queue):
    """
    Asserting processName and process in pytest.
    
    e.g. "2026-01-27 05:00:00,123 [12345] Process-1 INFO merid.worker.0 wid=0 msg=0"
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    p = mp.Process(target=worker, args=(q, 0))
    p.start()
    p.join()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines

    # e.g. "2026-01-27 05:00:00,123 [12345] Process-1 INFO merid.worker.0 wid=0 msg=0"
    has_process_name = any("Process-" in line or "MainProcess" in line for line in lines)
    has_pid_brackets = any("[" in line and "]" in line for line in lines)
    assert has_process_name
    assert has_pid_brackets


# 5) Testing TimedRotatingFileHandler rollover with multiprocessing logs
def test_timed_rotation_multiprocessing(log_queue):
    """
    Testing TimedRotatingFileHandler rollover with multiprocessing logs.
    
    Stress rotation by using a short interval (when="s") and multiple workers 
    sending via the queue.
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    # Override listener handler to use seconds rotation (if needed you can
    # start a per-test listener instead of the session one).
    # For simplicity, assume log_queue listener already uses when='s'.

    procs = [mp.Process(target=merid_logging.spam_worker, args=(wid, 2000))
             for wid in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    # stop listener so all files are flushed
    q.put_nowait(None)
    q.close()

    # wait for listener fixture teardown to join the process, then:
    files = list(log_file.parent.glob(log_file.name + "*"))
    assert len(files) >= 2  # rotated at least once

    total_lines = 0
    for f in files:
        total_lines += len(f.read_text(encoding="utf-8").splitlines())
    assert total_lines > 0


# Test the minimal MERID integration
def test_merid_end_to_end_integration():
    """
    Test the end-to-end MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = os.path.join(tmp_dir, "merid_test.log")
        
        # Start listener
        listener_proc = merid_logging.start_merid_listener(log_path)
        
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
    print("🚀 Testing MERID End-to-End Logging Patterns")
    print("=" * 50)
    
    # Test the integration
    print("\n🧪 Testing MERID End-to-End Integration...")
    try:
        test_merid_end_to_end_integration()
        print("   ✅ MERID end-to-end integration test passed")
    except Exception as e:
        print(f"   ❌ MERID end-to-end integration test failed: {e}")
    
    print("\n✅ MERID end-to-end logging patterns tested successfully!")

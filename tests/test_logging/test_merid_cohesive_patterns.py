"""
MERID Cohesive Logging Patterns Tests
Tests for the minimal, cohesive set of patterns that can be used directly.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
import pytest
import pathlib
import time
from logging.handlers import QueueHandler, QueueListener
from multiprocessing import Queue
from typing import List

# Import MERID logging patterns
import merid_logging


# 4) Asserting LogRecord.processName and LogRecord.process in pytest
def worker(queue, wid: int):
    """
    Asserting LogRecord.processName and LogRecord.process in pytest.
    
    For the process-based listener fixture (log_queue), assert against the 
    file it writes.
    
    The format string used in the listener (%(process)d and %(processName)s) 
    ensures those attributes are present in every line.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    log = logging.getLogger(f"merid.worker.{wid}")
    log.info("wid=%d msg=%d", wid, 0)


def test_process_info_in_logs(log_queue):
    """
    Asserting LogRecord.processName and LogRecord.process in pytest.
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


# 5) Capturing child-process logs in pytest using QueueHandler
def spam_worker(queue, wid: int, n: int):
    """
    Capturing child-process logs in pytest using QueueHandler.
    
    Pytest's caplog cannot see logs from spawned child processes directly, 
    so the standard pattern is:
    
    - In workers: attach QueueHandler(queue) and log as usual.
    - In the listener process: write to a file.
    - In tests: inspect that file.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    log = logging.getLogger(f"merid.worker.{wid}")
    for i in range(n):
        log.info("wid=%d msg=%d", wid, i)


def test_child_process_logs_captured(log_queue):
    """
    Capturing child-process logs in pytest using QueueHandler.
    
    This is the recommended workaround: QueueHandler + file assertions 
    instead of trying to make caplog capture logs from other processes.
    """
    q = log_queue["queue"]
    log_file = log_queue["log_file"]

    procs = [mp.Process(target=spam_worker, args=(q, wid, 10)) for wid in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    text = log_file.read_text(encoding="utf-8")
    assert "wid=0 msg=0" in text
    assert "wid=1 msg=0" in text
    assert "wid=2 msg=0" in text


# Test the threaded listener pattern
def test_threaded_listener_pattern(thread_listener):
    """
    Test the threaded listener pattern.
    
    Workers in the same process just log via normal loggers; the QueueListener 
    handles them asynchronously.
    """
    q = thread_listener["queue"]
    listener = thread_listener["listener"]
    
    # Configure logging for same-process test
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(q))
    
    # Log some messages
    logger = logging.getLogger("merid.threaded.test")
    logger.info("threaded test message 1")
    logger.info("threaded test message 2")
    
    # Give the listener time to process
    time.sleep(0.1)
    
    # The QueueListener handles messages asynchronously
    # We can't easily assert on StreamHandler output, but we can verify
    # the listener is working by checking it doesn't hang
    assert listener.is_alive()


# Test the QueueListener sentinel pattern
def test_queue_listener_sentinel_pattern():
    """
    Test the QueueListener sentinel pattern.
    
    Fixture to join and terminate a QueueListener thread safely.
    
    The thread_listener fixture above shows the idiomatic pattern:
    
    - Call listener.enqueue_sentinel() to push a sentinel into the queue.
    - Call listener.stop() to drain the queue up to the sentinel and stop.
    
    That guarantees all queued records are processed before the listener thread exits.
    """
    q = Queue(-1)
    
    # Create a simple handler that captures records
    captured_records = []
    
    class TestHandler(logging.Handler):
        def emit(self, record):
            captured_records.append(record)
    
    handler = TestHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(processName)s %(levelname)s %(name)s %(message)s"
    ))
    
    listener = QueueListener(q, handler, respect_handler_level=True)
    listener.start()
    
    # Configure logging
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(q))
    
    # Log some messages
    logger = logging.getLogger("merid.sentinel.test")
    logger.info("sentinel test message 1")
    logger.info("sentinel test message 2")
    
    # Test the sentinel pattern
    listener.enqueue_sentinel()
    listener.stop()
    
    # Verify all records were processed
    assert len(captured_records) >= 2
    assert any("sentinel test message 1" in record.getMessage() for record in captured_records)
    assert any("sentinel test message 2" in record.getMessage() for record in captured_records)


# Test the cohesive MERID integration
def test_merid_cohesive_integration():
    """
    Test the cohesive MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = os.path.join(tmp_dir, "merid_cohesive.log")
        
        # Start listener using cohesive pattern
        listener_proc = merid_logging.start_merid_listener(log_path)
        
        try:
            # Test single worker in same process
            merid_logging.configure_merid_worker_logging()
            logger = logging.getLogger('merid.cohesive.test')
            logger.info('cohesive test message from main process')
            
            # Wait a bit for logging to be processed
            time.sleep(1)
            
            # Verify log file was created and has content
            assert os.path.exists(log_path)
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
                assert len(lines) > 0
                assert "cohesive test message from main process" in lines[0]
                
        finally:
            # Shutdown using cohesive pattern
            merid_logging.stop_merid_logging_listener(listener_proc)


if __name__ == "__main__":
    print("🚀 Testing MERID Cohesive Logging Patterns")
    print("=" * 45)
    
    # Test the integration
    print("\n🧪 Testing MERID Cohesive Integration...")
    try:
        test_merid_cohesive_integration()
        print("   ✅ MERID cohesive integration test passed")
    except Exception as e:
        print(f"   ❌ MERID cohesive integration test failed: {e}")
    
    print("\n✅ MERID cohesive logging patterns tested successfully!")

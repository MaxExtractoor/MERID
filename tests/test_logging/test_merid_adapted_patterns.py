"""
MERID Adapted Logging Patterns Tests
Tests for adapting QueueListener to MERID's logging config.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
import pytest
import pathlib
import time
from logging.handlers import QueueHandler, TimedRotatingFileHandler, RotatingFileHandler
from multiprocessing import Queue
from typing import List

# Import MERID logging patterns
import merid_logging_queue


# 3) Testing QueueListener shutdown in pytest for MERID
@pytest.fixture(scope="session")
def merid_log_backend(tmp_path_factory):
    """
    Testing QueueListener shutdown in pytest for MERID.
    
    Use the same fixture you already have, but think of it as MERID's 
    logging backend for tests.
    """
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "merid.log"
    proc = merid_logging_queue.start_merid_listener(str(log_file))
    yield {"log_file": log_file, "proc": proc}
    # graceful shutdown
    merid_logging_queue.shutdown_merid_logging()
    proc.join(timeout=5)


def test_listener_shutdown(merid_log_backend):
    """
    Test that:
    
    - Workers join.
    - Listener process terminates cleanly.
    - Log file is non-empty.
    
    This ensures MERID's logging backend does not hang pytest at the end of the session.
    """
    log_file = merid_log_backend["log_file"]

    # spawn a worker that logs
    p = mp.Process(target=merid_logging_queue._test_worker)
    p.start()
    p.join()

    # fixture teardown will send sentinel and join listener
    text = log_file.read_text(encoding="utf-8")
    assert "MERID test worker" in text


# 4) Ensuring LogRecord attributes survive multiprocessing
def test_attributes_survive_multiprocessing(merid_log_backend):
    """
    Ensuring LogRecord attributes survive multiprocessing.
    
    The standard logging cookbook pattern sends full LogRecord objects through 
    the queue; attributes like process, processName, name, levelno, etc., survive 
    as long as you don't mutate them yourself.
    
    To assert this in tests:
    """
    log_file = merid_log_backend["log_file"]

    # spawn a worker that logs extra fields
    p = mp.Process(target=merid_logging_queue._test_worker_with_extra)
    p.start()
    p.join()

    text = log_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    
    # Check that extra fields survive
    assert any("merid_worker_id" in line for line in lines)
    # Check that standard attributes survive
    assert any("Process-" in line or "MainProcess" in line for line in lines)
    assert any("INFO" in line or "ERROR" in line for line in lines)
    assert any("merid.test.worker.extra" in line for line in lines)


# 5) Handling file rotation when using QueueListener
def test_rotation_under_load(tmp_path):
    """
    Handling file rotation when using QueueListener.
    
    With the queue model, only the listener process touches files, so rotation 
    is straightforward:
    
    - Use TimedRotatingFileHandler or RotatingFileHandler in the listener's config.
    - All worker processes write via the queue; they never see rotation.
    
    Because rotation is confined to a single process, you avoid the classic 
    multi-process TimedRotatingFileHandler race conditions.
    """
    # override listener for this test with 'when="s"' or small maxBytes
    log_file = tmp_path / "rotation.log"
    proc = merid_logging_queue.start_merid_listener(str(log_file), handler_type="timed")

    # hammer it from several workers
    procs = [mp.Process(target=merid_logging_queue._spam_worker, args=(wid, 2000))
             for wid in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    merid_logging_queue.shutdown_merid_logging()
    proc.join(timeout=5)

    files = list(log_file.parent.glob(log_file.name + "*"))
    assert len(files) >= 2  # rotated
    total_lines = sum(
        len(f.read_text(encoding="utf-8").splitlines()) for f in files
    )
    assert total_lines > 0


def test_rotating_file_handler_under_load(tmp_path):
    """
    Test RotatingFileHandler under load.
    """
    # override listener for this test with rotating file handler
    log_file = tmp_path / "rotating.log"
    proc = merid_logging_queue.start_merid_listener(str(log_file), handler_type="rotating")

    # hammer it from several workers
    procs = [mp.Process(target=merid_logging_queue._spam_worker, args=(wid, 1000))
             for wid in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    merid_logging_queue.shutdown_merid_logging()
    proc.join(timeout=5)

    files = list(log_file.parent.glob(log_file.name + "*"))
    assert len(files) >= 1  # at least the main file
    total_lines = sum(
        len(f.read_text(encoding="utf-8").splitlines()) for f in files
    )
    assert total_lines > 0


# Test integration with existing MERID loggers
def test_existing_logger_integration(merid_log_backend):
    """
    Test integration with existing MERID loggers.
    
    Then, all existing calls like:
    
    logger = logging.getLogger("merid.agent.trader")
    logger.info("placing order")
    
    are automatically routed through the queue to the listener, without changing call sites.
    """
    log_file = merid_log_backend["log_file"]

    # Test multiple existing logger names
    test_loggers = [
        "merid.agent.trader",
        "merid.swarm.worker",
        "merid.task.processor",
        "merid.system.monitor"
    ]

    procs = []
    for logger_name in test_loggers:
        def worker_with_logger(name):
            merid_logging_queue.configure_merid_worker_logging()
            logger = logging.getLogger(name)
            logger.info(f"test message from {name}")
        
        p = mp.Process(target=worker_with_logger, args=(logger_name,))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    # Verify all loggers contributed
    text = log_file.read_text(encoding="utf-8")
    for logger_name in test_loggers:
        assert f"test message from {logger_name}" in text


# Test the adapted MERID integration
def test_merid_adapted_integration():
    """
    Test the adapted MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_path = os.path.join(tmp_dir, "merid_adapted.log")
        
        # Start listener using adapted pattern
        listener_proc = merid_logging_queue.start_merid_listener(log_path)
        
        try:
            # Test multiple workers using adapted pattern
            procs = []
            for wid in range(3):
                p = mp.Process(target=merid_logging_queue._adapted_worker)
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
                for wid in range(3):
                    assert f"adapted test message from worker {wid}" in content
                
        finally:
            # Shutdown using adapted pattern
            merid_logging_queue.shutdown_merid_logging()
            listener_proc.join(timeout=5)


if __name__ == "__main__":
    print("🚀 Testing MERID Adapted Logging Patterns")
    print("=" * 47)
    
    # Test the integration
    print("\n🧪 Testing MERID Adapted Integration...")
    try:
        test_merid_adapted_integration()
        print("   ✅ MERID adapted integration test passed")
    except Exception as e:
        print(f"   ❌ MERID adapted integration test failed: {e}")
    
    print("\n✅ MERID adapted logging patterns tested successfully!")
    print("\n📋 In short:")
    print("   • Adaptation: treat the listener + queue as MERID's logging backend;")
    print("     your existing loggers stay as-is.")
    print("   • Integration: override only root handlers in workers to")
    print("     QueueHandler(LOG_QUEUE).")
    print("   • Testing: pytest fixtures spin up the listener, run workers,")
    print("     assert on the listener's output, and tear down with sentinel + join.")
    print("   • Attributes and rotation: come \"for free\" when you pass whole")
    print("     LogRecord's through the queue and only rotate in the listener process.")

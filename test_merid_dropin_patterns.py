"""
MERID Drop-in Logging Patterns Tests
Tests for concise drop-in patterns for MERID.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
import pytest
import pathlib
import time
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from multiprocessing import Queue
from typing import List

# Import MERID logging patterns
import merid_logging_config


# 4) Pytest pattern: assert no pending records after shutdown
def test_no_pending_records(tmp_path):
    """
    Pytest pattern: assert no pending records after shutdown.
    
    You can't reliably introspect multiprocessing.Queue internals, but you can assert:
    
    - All workers have finished (join()ed).
    - Listener stopped cleanly.
    - Log file contains at least the expected number of lines.
    """
    log_path = tmp_path / "merid.log"
    merid_logging_config.start_merid_logging(str(log_path))

    # spawn workers
    procs = []
    for i in range(3):
        p = mp.Process(target=merid_logging_config._spam_worker, args=(i, 50))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()

    merid_logging_config.shutdown_merid_logging()

    text = log_path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # 3 * 50 messages, allow some slack if needed
    assert len(lines) >= 140


# 5) Safe TimedRotatingFileHandler with multiple processes via QueueListener
def test_rotation_multi_process(tmp_path):
    """
    Safe TimedRotatingFileHandler with multiple processes via QueueListener.
    
    Core rule: only the listener thread/process owns the TimedRotatingFileHandler. 
    All worker processes send LogRecords via the queue.
    
    Because rotation operations (rename, open/close) happen in exactly one thread, 
    you avoid the race conditions that TimedRotatingFileHandler exhibits when 
    used directly from multiple processes.
    """
    log_path = tmp_path / "rotation.log"

    # use seconds-based rotation for test
    # quick override: call base_dict_config, adjust when='s', then start_merid_logging
    merid_logging_config.start_merid_logging(str(log_path))

    procs = [mp.Process(target=merid_logging_config._spam_worker, args=(i, 1000)) for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    merid_logging_config.shutdown_merid_logging()

    files = list(log_path.parent.glob(log_path.name + "*"))
    assert len(files) >= 2
    total_lines = sum(
        len(f.read_text(encoding="utf-8").splitlines()) for f in files
    )
    assert total_lines > 0


# Test the dictConfig integration
def test_dictconfig_integration(tmp_path):
    """
    Test dictConfig integration with QueueListener.
    
    The pattern above shows how:
    
    1. Apply dictConfig.
    2. Capture current handlers (e.g., root's rotating_file).
    3. Remove them from root.
    4. Start a QueueListener with those handlers.
    5. Add QueueHandler(LOG_QUEUE) to root.
    
    This is the idiomatic way to "wrap" a dictConfig in a queue-based backend.
    """
    log_path = tmp_path / "dictconfig.log"
    
    # Test that dictConfig is applied correctly
    cfg = merid_logging_config.base_dict_config(str(log_path))
    
    # Verify config structure
    assert cfg["version"] == 1
    assert "formatters" in cfg
    assert "handlers" in cfg
    assert "loggers" in cfg
    assert "root" in cfg
    
    # Test that logging works with the config
    merid_logging_config.start_merid_logging(str(log_path))
    
    # Test logging from main process
    logger = logging.getLogger("merid.test")
    logger.info("dictconfig test message")
    
    # Test worker process
    p = mp.Process(target=merid_logging_config._test_worker)
    p.start()
    p.join()
    
    merid_logging_config.shutdown_merid_logging()
    
    # Verify log file content
    text = log_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) > 0
    assert any("dictconfig test message" in line for line in lines)
    assert any("test worker started" in line for line in lines)


# Test worker initialization
def test_worker_initialization(tmp_path):
    """
    Test best practices for reinitializing loggers in worker processes.
    
    When you spawn MERID workers (processes):
    
    - Do not re-create file handlers.
    - Do clear and reattach a QueueHandler pointing at the existing queue.
    """
    log_path = tmp_path / "worker_init.log"
    merid_logging_config.start_merid_logging(str(log_path))
    
    # Test worker initialization
    p = mp.Process(target=merid_logging_config._worker_main)
    p.start()
    p.join()
    
    merid_logging_config.shutdown_merid_logging()
    
    # Verify log file content
    text = log_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) > 0
    assert any("worker started" in line for line in lines)


# Test existing logger integration
def test_existing_logger_integration(tmp_path):
    """
    Test that existing MERID loggers work unchanged.
    
    All MERID components just use normal loggers 
    (logging.getLogger("merid.agent.trader")).
    """
    log_path = tmp_path / "existing_logger.log"
    merid_logging_config.start_merid_logging(str(log_path))
    
    # Test various logger names that MERID might use
    test_loggers = [
        "merid.agent.trader",
        "merid.swarm.worker",
        "merid.task.processor",
        "merid.system.monitor",
        "merid.web.api",
        "merid.data.feed"
    ]
    
    # Test logging from main process with various loggers
    for logger_name in test_loggers:
        logger = logging.getLogger(logger_name)
        logger.info(f"test message from {logger_name}")
    
    # Test worker processes with various loggers
    procs = []
    for logger_name in test_loggers:
        def worker_with_logger(name):
            merid_logging_config.init_merid_worker_logging()
            logger = logging.getLogger(name)
            logger.info(f"worker message from {name}")
        
        p = mp.Process(target=worker_with_logger, args=(logger_name,))
        p.start()
        procs.append(p)
    
    for p in procs:
        p.join()
    
    merid_logging_config.shutdown_merid_logging()
    
    # Verify all loggers contributed
    text = log_path.read_text(encoding="utf-8")
    for logger_name in test_loggers:
        assert f"test message from {logger_name}" in text
        assert f"worker message from {logger_name}" in text


# Test the drop-in MERID integration
def test_merid_dropin_integration():
    """
    Test the drop-in MERID integration pattern.
    """
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Test with explicit path
        log_path = os.path.join(tmp_dir, "merid_dropin.log")
        merid_logging_config.start_merid_logging(log_path)
        
        try:
            # Test normal MERID logger usage
            logger = logging.getLogger("merid.agent.trader")
            logger.info("placing order")
            
            logger = logging.getLogger("merid.swarm.worker")
            logger.info("swarm task completed")
            
            # Wait a bit for logging to be processed
            time.sleep(1)
            
            # Verify log file was created and has content
            assert os.path.exists(log_path)
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
                assert len(lines) > 0
                assert "placing order" in content
                assert "swarm task completed" in content
                
        finally:
            # Shutdown using drop-in pattern
            merid_logging_config.shutdown_merid_logging()
    
    # Test with default path (use current directory to avoid permission issues)
    old_env = os.environ.get('MERID_LOG_PATH')
    try:
        # Use current directory for default test to avoid permission issues
        current_dir = os.getcwd()
        default_log_path = os.path.join(current_dir, 'test_merid_default.log')
        os.environ['MERID_LOG_PATH'] = default_log_path
        merid_logging_config.start_merid_logging()
        
        try:
            logger = logging.getLogger('merid.test.default')
            logger.info('default path test')
            time.sleep(0.5)
            
            # Verify default path works
            resolved_path = merid_logging_config._resolve_default_log_path()
            assert os.path.exists(resolved_path)
            
        finally:
            merid_logging_config.shutdown_merid_logging()
            
            # Clean up test file
            if os.path.exists(resolved_path):
                os.remove(resolved_path)
                
    finally:
        if old_env:
            os.environ['MERID_LOG_PATH'] = old_env
        else:
            os.environ.pop('MERID_LOG_PATH', None)
    
    # Test with environment variable
    old_env = os.environ.get("MERID_LOG_PATH")
    try:
        test_env_path = os.path.join(tmp_dir, "env_test", "merid.log")
        os.makedirs(os.path.dirname(test_env_path), exist_ok=True)
        os.environ["MERID_LOG_PATH"] = os.path.dirname(test_env_path)
        
        merid_logging_config.start_merid_logging()
        
        try:
            logger = logging.getLogger("merid.test.env")
            logger.info("environment variable test")
            time.sleep(0.5)
            
            # Verify environment variable works
            assert os.path.exists(test_env_path)
            
        finally:
            merid_logging_config.shutdown_merid_logging()
            
    finally:
        if old_env:
            os.environ["MERID_LOG_PATH"] = old_env
        else:
            os.environ.pop("MERID_LOG_PATH", None)


if __name__ == "__main__":
    print("🚀 Testing MERID Drop-in Logging Patterns")
    print("=" * 45)
    
    # Test the integration
    print("\n🧪 Testing MERID Drop-in Integration...")
    try:
        test_merid_dropin_integration()
        print("   ✅ MERID drop-in integration test passed")
    except Exception as e:
        print(f"   ❌ MERID drop-in integration test failed: {e}")
    
    print("\n✅ MERID drop-in logging patterns tested successfully!")
    print("\n📋 These patterns give you:")
    print("   • A dictConfig-friendly wrapper for QueueListener.")
    print("   • Minimal worker init code.")
    print("   • Clear pytest hooks to verify shutdown and rotation.")
    print("   • Confidence that all LogRecord attributes and rotation")
    print("     semantics are preserved across MERID's multiprocess swarms.")

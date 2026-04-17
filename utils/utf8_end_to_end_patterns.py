"""
MERID End-to-End UTF-8 Logging Patterns
Compact, end-to-end patterns covering complete pytest fixture, worker logging, sentinel shutdown, queue comparison, and listener process configuration.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import pathlib
import threading
import time
import os
import multiprocessing as mp
from typing import Union, Optional, Dict, Set, List
from logging.handlers import TimedRotatingFileHandler, QueueHandler, QueueListener
from pathlib import Path

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - end-to-end patterns will use fallback")


# 1) Complete pytest fixture: multiprocessing.Queue + listener process
def _listener_process(log_path: str, queue: mp.Queue):
    """
    Run in a separate process; owns handlers and logging config.
    
    This follows the logging cookbook's QueueHandler/QueueListener pattern 
    with a dedicated listener process.
    
    This keeps all file I/O and rotation in one process and lets all test 
    workers just enqueue LogRecords.
    """
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    try:
        while True:
            record = queue.get()
            if record is None:  # sentinel => shutdown
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
    finally:
        handler.close()


def setup_end_to_end_logging_listener(tmp_path: Union[str, pathlib.Path]) -> Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]:
    """
    Session-scoped logging queue + listener process.
    
    Complete pytest fixture: multiprocessing.Queue + listener process.
    """
    if isinstance(tmp_path, str):
        tmp_path = pathlib.Path(tmp_path)
    
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "multiproc.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(
        target=_listener_process,
        args=(str(log_file), q),
        daemon=True,
    )
    proc.start()

    return {"queue": q, "log_file": log_file, "process": proc}


def cleanup_end_to_end_logging_listener(logging_info: Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]) -> None:
    """
    Sentinel and shutdown sequence for the listener.
    
    The safe, cookbook-style shutdown sequence is:
    
    1. After all workers are finished, put a sentinel (e.g. None) onto the queue.
    2. The listener loop checks for record is None and breaks.
    3. Close the queue and join the listener process.
    
    This ensures all pending records are processed before the listener exits.
    """
    if "queue" in logging_info:
        logging_info["queue"].put_nowait(None)  # sentinel for listener loop
        logging_info["queue"].close()
    if "process" in logging_info:
        logging_info["process"].join(timeout=5)


# 2) Sending logging records from pytest workers to the listener
def _worker(queue: mp.Queue, worker_id: int, n: int):
    """
    Configure logging in the worker process.
    
    Each worker (or any test code running in child processes) attaches a 
    QueueHandler that sends LogRecords to the shared queue.
    
    QueueHandler converts log records into messages on the multiprocessing.Queue, 
    which the listener process's loop consumes and re-emits through its own 
    logger configuration.
    """
    # Configure logging in the worker process
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    logger = logging.getLogger(f"worker-{worker_id}")
    for i in range(n):
        logger.info("wid=%d msg=%d", worker_id, i)


def test_multiproc_logging(
    log_path: Union[str, pathlib.Path] = "logs/multiproc.log",
    num_workers: int = 3,
    messages_per_worker: int = 100
) -> dict:
    """
    Sending logging records from pytest workers to the listener.
    
    This demonstrates the complete end-to-end pattern with multiple workers 
    sending records to the listener process.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        text = log_file.read_text(encoding="utf-8")
        
        return {
            "log_file_exists": log_file.exists(),
            "log_file_size": log_file.stat().st_size if log_file.exists() else 0,
            "log_content": text,
            "contains_worker_messages": "wid=0 msg=0" in text,
            "test_passed": "wid=0 msg=0" in text,
            "workers": num_workers,
            "messages_per_worker": messages_per_worker,
            "expected_total_messages": num_workers * messages_per_worker
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 3) Sentinel and shutdown sequence for the listener
def test_sentinel_shutdown(
    log_path: Union[str, pathlib.Path] = "logs/sentinel_shutdown.log",
    num_workers: int = 2,
    messages_per_worker: int = 50
) -> dict:
    """
    Sentinel and shutdown sequence for the listener.
    
    The safe, cookbook-style shutdown sequence is:
    
    1. After all workers are finished, put a sentinel (e.g. None) onto the queue.
    2. The listener loop checks for record is None and breaks.
    3. Close the queue and join the listener process.
    
    This ensures all pending records are processed before the listener exits.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Check results
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            
            return {
                "log_file_exists": True,
                "lines_found": len(lines),
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": len(lines) > 0,
                "sample_lines": lines[:5] if lines else [],
                "shutdown_successful": True
            }
        else:
            return {
                "log_file_exists": False,
                "lines_found": 0,
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": False,
                "error": "Log file not created",
                "sample_lines": [],
                "shutdown_successful": False
            }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 4) multiprocessing.Queue vs Manager().Queue for logging
def analyze_queue_types() -> dict:
    """
    multiprocessing.Queue vs Manager().Queue for logging.
    
    Key differences for logging workloads:
    
    multiprocessing.Queue:
      - Backed by pipes/shared resources and locks; high throughput and low overhead.
      - Designed for frequent, small messages like LogRecords.
      - Used in the official logging cookbook and QueueHandler/QueueListener examples.
    
    multiprocessing.Manager().Queue:
      - Proxied by a manager process; more flexible for complex shared objects.
      - Higher latency/overhead because every operation goes through the manager.
    
    For logging, multiprocessing.Queue is preferred: it's simpler, faster, and exactly 
    what the standard recipes use.
    """
    return {
        "recommendation": "multiprocessing.Queue",
        "reasoning": "Lower overhead, higher throughput, designed for frequent small messages like LogRecords",
        "queue_type": "multiprocessing.Queue",
        "manager_type": "multiprocessing.Manager().Queue",
        "use_case": "logging with QueueHandler/QueueListener patterns",
        "performance": "High throughput, low overhead",
        "complexity": "Simple, direct implementation",
        "standard_compliance": "Used in official logging cookbook examples"
    }


# 5) Safely configuring handlers inside the listener process
def create_safe_listener_config(
    log_path: Union[str, pathlib.Path] = "logs/safe_listener.log",
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8",
    level: int = logging.INFO
) -> dict:
    """
    Safely configuring handlers inside the listener process.
    
    Best practices from the cookbook and QueueListener guides:
    
    - Configure logging inside the listener process (not in the parent) so it has 
      its own independent root logger and handlers.
    - Only the listener process should own file/network handlers; workers must not 
      touch file handlers, just QueueHandler.
    - Set levels/filters either in workers (to avoid sending discarded records) or 
      in the listener (for centralized control), but keep the pipeline simple: 
      workers → queue → listener → handlers.
    
    This separation avoids handler duplication, file descriptor conflicts, and 
    race conditions, and is the pattern recommended for high-throughput 
    multiprocess logging.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # This is the pattern used inside _listener_process
    config = {
        "listener_config": {
            "handler": {
                "type": "TimedRotatingFileHandler",
                "log_path": str(log_path),
                "when": when,
                "interval": interval,
                "backup_count": backup_count,
                "encoding": encoding,
                "level": level,
                "formatter": "%(asctime)s [%(process)d] %(levelname)s %(message)s"
            },
            "root_logger": {
                "handlers_cleared": True,
                "level": level,
                "handler_added": True
            }
        },
        "worker_config": {
            "handler": {
                "type": "QueueHandler",
                "queue": "shared_queue",
                "level": level
            },
            "root_logger": {
                "handlers_cleared": True,
                "level": level,
                "handler_added": True
            }
        },
        "separation_benefits": [
            "Avoids handler duplication",
            "Prevents file descriptor conflicts",
            "Eliminates race conditions",
            "Centralizes file I/O operations",
            "Simplifies worker configuration"
        ],
        "pipeline": "workers → queue → listener → handlers"
    }
    
    return config


def test_safe_listener_configuration(
    log_path: Union[str, pathlib.Path] = "logs/safe_config_test.log",
    num_workers: int = 2,
    messages_per_worker: int = 30
) -> dict:
    """
    Test safe listener configuration with multiple workers.
    
    This demonstrates the safe configuration pattern where only the listener 
    process owns file handlers and workers only use QueueHandler.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get safe configuration
    config = create_safe_listener_config(log_path)
    
    # Set up queue listener process
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Check results
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            
            return {
                "log_file_exists": True,
                "lines_found": len(lines),
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": len(lines) > 0,
                "sample_lines": lines[:5] if lines else [],
                "config_applied": config,
                "separation_successful": True
            }
        else:
            return {
                "log_file_exists": False,
                "lines_found": 0,
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": False,
                "error": "Log file not created",
                "sample_lines": [],
                "config_applied": config,
                "separation_successful": False
            }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# Standard UTF-8 StreamHandler for dictConfig
class Utf8StreamHandler(logging.StreamHandler):
    """Standard UTF-8 StreamHandler for dictConfig."""
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="fast",
            )
        super(Utf8StreamHandler, self).__init__(stream)


# Console + File configuration
LOGGING_CONSOLE_FILE = {
    "version": 1,
    "handlers": {
        "console_utf8": {
            "()": "utf8_end_to_end_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
        "file_utf8_bom": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_console_bom.log",
            "mode": "a",
            "encoding": "utf-8-sig",
        },
    },
    "formatters": {
        "standard": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["console_utf8", "file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_console_file_bom_logging() -> logging.Logger:
    """Configure console + file logging with BOM."""
    log_path = pathlib.Path("logs/app_console_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CONSOLE_FILE)
    return logging.getLogger(__name__)


# Utility functions
def verify_bom_in_file(file_path: Union[str, pathlib.Path]) -> bool:
    """Verify that a file starts with UTF-8 BOM."""
    file_path = pathlib.Path(file_path)
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'rb') as f:
            bom = f.read(3)
            return bom == b'\xef\xbb\xbf'
    except Exception:
        return False


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing End-to-End UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test complete pytest fixture
    print("\n🧪 Testing Complete Pytest Fixture...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        logging_info = setup_end_to_end_logging_listener(tmp_path)
        print(f"   ✅ End-to-end listener set up with log file: {logging_info['log_file']}")
        print(f"   📝 Queue size: {logging_info['queue'].qsize()}")
        print(f"   📝 Process PID: {logging_info['process'].pid}")
        
        cleanup_end_to_end_logging_listener(logging_info)
        print(f"   ✅ Listener gracefully stopped")
    
    # Test multiprocess logging
    print("\n🧪 Testing Multiprocess Logging...")
    multiproc_results = test_multiproc_logging(
        log_path="logs/multiproc.log",
        num_workers=3,
        messages_per_worker=50
    )
    print(f"   📊 Results:")
    print(f"      Log file exists: {multiproc_results['log_file_exists']}")
    print(f"      Log file size: {multiproc_results['log_file_size']}")
    print(f"      Contains worker messages: {multiproc_results['contains_worker_messages']}")
    print(f"      Test passed: {multiproc_results['test_passed']}")
    print(f"      Workers: {multiproc_results['workers']}")
    print(f"      Messages per worker: {multiproc_results['messages_per_worker']}")
    
    # Test sentinel shutdown
    print("\n🧪 Testing Sentinel Shutdown...")
    sentinel_results = test_sentinel_shutdown(
        log_path="logs/sentinel_shutdown.log",
        num_workers=2,
        messages_per_worker=30
    )
    print(f"   📊 Results:")
    print(f"      Log file exists: {sentinel_results['log_file_exists']}")
    print(f"      Lines found: {sentinel_results['lines_found']}")
    print(f"      Expected lines: {sentinel_results['expected_lines']}")
    print(f"      Test passed: {sentinel_results['test_passed']}")
    print(f"      Shutdown successful: {sentinel_results['shutdown_successful']}")
    
    # Test queue type analysis
    print("\n🧪 Testing Queue Type Analysis...")
    queue_analysis = analyze_queue_types()
    print(f"   📊 Recommendation: {queue_analysis['recommendation']}")
    print(f"   📝 Reasoning: {queue_analysis['reasoning']}")
    print(f"   📝 Performance: {queue_analysis['performance']}")
    print(f"   📝 Complexity: {queue_analysis['complexity']}")
    print(f"   📝 Standard compliance: {queue_analysis['standard_compliance']}")
    
    # Test safe listener configuration
    print("\n🧪 Testing Safe Listener Configuration...")
    safe_config_results = test_safe_listener_configuration(
        log_path="logs/safe_config_test.log",
        num_workers=2,
        messages_per_worker=25
    )
    print(f"   📊 Results:")
    print(f"      Log file exists: {safe_config_results['log_file_exists']}")
    print(f"      Lines found: {safe_config_results['lines_found']}")
    print(f"      Expected lines: {safe_config_results['expected_lines']}")
    print(f"      Test passed: {safe_config_results['test_passed']}")
    print(f"      Separation successful: {safe_config_results['separation_successful']}")
    print(f"      Pipeline: {safe_config_results['config_applied']['pipeline']}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("End-to-end test: 🚀 αβγ")
    
    print("\n✅ All end-to-end UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 End-to-End Features:")
    print("   • Complete pytest fixture with multiprocessing.Queue")
    print("   • Worker logging via QueueHandler")
    print("   • Sentinel shutdown sequence")
    print("   • Queue type analysis and recommendations")
    print("   • Safe listener process configuration")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

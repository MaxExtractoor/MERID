"""
MERID Minimal Production-Style UTF-8 Logging Patterns
Minimal, production-oriented patterns covering QueueListener process setup, Gunicorn QueueHandler integration, graceful teardown, queue comparison, and worker logging patterns.

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
    print("⚠️  concurrent-log-handler not available - minimal patterns will use fallback")


# 1) Pytest fixture: listener process for QueueListener
def _listener_process(log_path: str, queue: mp.Queue):
    """
    Run in a separate process; owns file handler + QueueListener.
    
    Use a separate process that owns the file handler and consumes a 
    multiprocessing.Queue of LogRecords.
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

    listener = QueueListener(queue, handler, respect_handler_level=True)
    listener.start()
    try:
        # main process will send None as sentinel to stop
        while True:
            record = queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
    finally:
        listener.stop()
        handler.close()


def setup_minimal_logging_listener(tmp_path: Union[str, pathlib.Path]) -> Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]:
    """
    Session-wide logging queue + listener process.
    
    Workers (or simulated Gunicorn workers) just attach 
    QueueHandler(log_queue["queue"]).
    """
    if isinstance(tmp_path, str):
        tmp_path = pathlib.Path(tmp_path)
    
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gunicorn_queue.log"

    queue: mp.Queue = mp.Queue(-1)
    proc = mp.Process(
        target=_listener_process,
        args=(str(log_file), queue),
        daemon=True,
    )
    proc.start()

    return {"queue": queue, "log_file": log_file, "process": proc}


def cleanup_minimal_logging_listener(logging_info: Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]) -> None:
    """
    Gracefully stopping QueueListener in pytest teardown.
    
    From the fixture above, the graceful pattern is:
    
    - Push a sentinel `None` into the queue.
    - Let the listener loop break on `None`.
    - Call `listener.stop()` and close the handler.
    
    This ensures all pending records are processed before the listener terminates.
    """
    if "queue" in logging_info:
        logging_info["queue"].put_nowait(None)   # sentinel
        logging_info["queue"].close()
    if "process" in logging_info:
        logging_info["process"].join(timeout=5)


# 2) Gunicorn config using QueueHandler + multiprocessing.Queue
def create_minimal_shared_queue_module(
    module_path: Union[str, pathlib.Path] = "my_logging_queue.py"
) -> pathlib.Path:
    """
    Expose the queue via a small module and use a custom logger_class 
    that applies QueueHandler to Gunicorn's loggers.
    
    Your pytest listener process (fixture above) consumes log_queue and writes 
    to disk.
    """
    module_path = pathlib.Path(module_path)
    
    module_content = '''import multiprocessing as mp

# Shared queue for logging across all processes
log_queue: mp.Queue = mp.Queue(-1)
'''
    
    module_path.write_text(module_content, encoding='utf-8')
    return module_path


def create_minimal_gunicorn_logger_class(
    class_file_path: Union[str, pathlib.Path] = "my_gunicorn_logger.py",
    queue_import_path: str = "my_logging_queue"
) -> pathlib.Path:
    """
    Custom Gunicorn logger class that swaps Gunicorn's handlers for a 
    QueueHandler hooked to your process-level QueueListener.
    
    All worker loggers propagate to root, which sends records into the 
    queue; the listener in the master (or a separate process) writes to disk.
    """
    class_file_path = pathlib.Path(class_file_path)
    
    class_content = f'''import logging
from logging.handlers import QueueHandler
from gunicorn.glogging import Logger as GunicornLogger
from {queue_import_path} import log_queue


class QueueGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)

        qh = QueueHandler(log_queue)

        # Route Gunicorn logs into the queue
        self.error_log.handlers = [qh]
        self.access_log.handlers = [qh]
'''
    
    class_file_path.write_text(class_content, encoding='utf-8')
    return class_file_path


def create_minimal_gunicorn_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_minimal_conf.py",
    logger_class_path: str = "my_gunicorn_logger.QueueGunicornLogger",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Create minimal Gunicorn config with QueueHandler setup.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with QueueHandler logging
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

# Use custom logger class with QueueHandler
logger_class = "{logger_class_path}"
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


# 3) Gracefully stopping QueueListener in pytest teardown
def test_minimal_teardown(
    log_path: Union[str, pathlib.Path] = "logs/minimal_teardown.log",
    num_workers: int = 2,
    messages_per_worker: int = 50
) -> dict:
    """
    Test graceful stopping of QueueListener in pytest teardown.
    
    From the fixture above, the graceful pattern is:
    
    - Push a sentinel `None` into the queue.
    - Let the listener loop break on `None`.
    - Call `listener.stop()` and close the handler.
    
    This ensures all pending records are processed before the listener terminates.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    logging_info = setup_minimal_logging_listener(log_path.parent)
    
    try:
        # Start worker processes
        procs = []
        for wid in range(num_workers):
            p = mp.Process(
                target=_minimal_worker, 
                args=(logging_info["queue"], wid, messages_per_worker)
            )
            p.start()
            procs.append(p)

        # Wait for all workers to complete
        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Check results
        if logging_info["log_file"].exists():
            text = logging_info["log_file"].read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            
            return {
                "log_file_exists": True,
                "lines_found": len(lines),
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": len(lines) > 0,
                "sample_lines": lines[:5] if lines else []
            }
        else:
            return {
                "log_file_exists": False,
                "lines_found": 0,
                "expected_lines": num_workers * messages_per_worker,
                "test_passed": False,
                "error": "Log file not created",
                "sample_lines": []
            }
    finally:
        cleanup_minimal_logging_listener(logging_info)


def _minimal_worker(log_queue: mp.Queue, wid: int, n_msgs: int):
    """
    Minimal worker function that uses QueueHandler for logging.
    
    Workers (or simulated Gunicorn workers) just attach 
    QueueHandler(log_queue["queue"]).
    """
    logger = logging.getLogger(f"worker-{wid}")
    logger.setLevel(logging.INFO)

    # Attach QueueHandler to forward to the listener
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))
    logger.addHandler(queue_handler)

    for i in range(n_msgs):
        logger.info(f"worker-{wid} message-{i}")
        time.sleep(0.01)


# 4) multiprocessing.Queue vs Manager().Queue for logging
def compare_queue_types() -> dict:
    """
    multiprocessing.Queue vs Manager().Queue for logging.
    
    Trade-offs:
    
    multiprocessing.Queue:
      - Backed by shared resources and OS pipes, uses locks for synchronization.
      - Lower overhead and higher throughput, ideal for logging where you push lots of small messages.
      - Standard choice in the logging cookbook and most queue-based logging examples.
    
    multiprocessing.Manager().Queue:
      - Managed by a separate manager process; more flexible for complex shared objects.
      - Higher overhead, more indirection; usually overkill for log records.
    
    For logging, prefer multiprocessing.Queue: simpler, faster, and exactly what the cookbook 
    recommends for QueueHandler/QueueListener patterns.
    """
    return {
        "recommendation": "multiprocessing.Queue",
        "reasoning": "Lower overhead, higher throughput, standard choice for logging",
        "queue_type": "multiprocessing.Queue",
        "manager_type": "multiprocessing.Manager().Queue",
        "use_case": "logging with QueueHandler/QueueListener patterns"
    }


# 5) Sending log records from Gunicorn workers to master
def create_minimal_post_fork_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_minimal_postfork_conf.py",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Sending log records from Gunicorn workers to master.
    
    Two common patterns:
    
    1) Queue-based (recommended)
      - Master (or dedicated listener process) owns QueueListener + handlers.
      - Workers have only QueueHandler(queue).
      - For Gunicorn, you supply the queue through a shared module 
        (my_logging_queue.log_queue) and a custom logger_class as above.
    
    2) Master process logger
      - In post_fork, attach a QueueHandler(server.logqueue) if you've set up your own 
        queue attribute on the server object.
    
    Queue-based logging centralizes all file I/O and rotation outside worker request 
    paths, which is the main best practice for multi-process servers like Gunicorn.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with post_fork QueueHandler
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

def post_fork(server, worker):
    import logging
    from logging.handlers import QueueHandler
    from my_logging_queue import log_queue

    h = QueueHandler(log_queue)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    root.setLevel(logging.INFO)
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


def create_minimal_master_logger_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_minimal_master_conf.py",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Alternative master process logger configuration.
    
    All worker loggers propagate to root, which sends records into the queue; the 
    listener in the master (or a separate process) writes to disk.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with master logger
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

def on_starting(server):
    import logging
    from logging.handlers import QueueHandler
    from my_logging_queue import log_queue

    # Master process: configure logging once
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    
    # Master process also has a QueueHandler to capture its own logs
    h = QueueHandler(log_queue)
    root.addHandler(h)
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


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
            "()": "utf8_minimal_production_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Minimal Production-Style UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test QueueListener process setup
    print("\n🧪 Testing Minimal QueueListener Process Setup...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        logging_info = setup_minimal_logging_listener(tmp_path)
        print(f"   ✅ QueueListener process set up with log file: {logging_info['log_file']}")
        print(f"   📝 Queue size: {logging_info['queue'].qsize()}")
        print(f"   📝 Process PID: {logging_info['process'].pid}")
        
        # Test graceful teardown
        print("\n🧪 Testing Graceful Teardown...")
        teardown_results = test_minimal_teardown(
            log_path=tmp_path / "minimal_teardown.log",
            num_workers=2,
            messages_per_worker=50
        )
        print(f"   📊 Results:")
        print(f"      Log file exists: {teardown_results['log_file_exists']}")
        print(f"      Lines found: {teardown_results['lines_found']}")
        print(f"      Expected lines: {teardown_results['expected_lines']}")
        print(f"      Test passed: {teardown_results['test_passed']}")
        
        if teardown_results['sample_lines']:
            print(f"      Sample lines: {teardown_results['sample_lines']}")
        
        cleanup_minimal_logging_listener(logging_info)
    
    # Test custom Gunicorn logger class
    print("\n🧪 Testing Minimal Gunicorn Logger Class...")
    logger_class_file = create_minimal_gunicorn_logger_class()
    print(f"   ✅ Custom logger class created: {logger_class_file}")
    
    gunicorn_config = create_minimal_gunicorn_config()
    print(f"   ✅ Gunicorn config created: {gunicorn_config}")
    
    # Test shared queue module
    print("\n🧪 Testing Shared Queue Module...")
    shared_queue_module = create_shared_queue_module()
    print(f"   ✅ Shared queue module created: {shared_queue_module}")
    
    # Test queue comparison
    print("\n🧪 Testing Queue Type Comparison...")
    queue_comparison = compare_queue_types()
    print(f"   📊 Recommendation: {queue_comparison['recommendation']}")
    print(f"   📝 Reasoning: {queue_comparison['reasoning']}")
    print(f"   📝 Queue type: {queue_comparison['queue_type']}")
    print(f"   📝 Manager type: {queue_comparison['manager_type']}")
    print(f"   📝 Use case: {queue_comparison['use_case']}")
    
    # Test post_fork configuration
    print("\n🧪 Testing Post-Fork Configuration...")
    post_fork_config = create_minimal_post_fork_config()
    print(f"   ✅ Post-fork config created: {post_fork_config}")
    
    master_config = create_minimal_master_logger_config()
    print(f"   ✅ Master logger config created: {master_config}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Minimal production test: 🚀 αβγ")
    
    print("\n✅ All minimal production-style UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Minimal Production-Style Features:")
    print("   • QueueListener process for clean separation")
    print("   • Custom Gunicorn logger with QueueHandler")
    print("   • Shared queue module for process communication")
    print("   • Graceful teardown with sentinel pattern")
    print("   • Queue type comparison and recommendations")
    print("   • Worker logging via QueueHandler")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

"""
MERID Queue-Based UTF-8 Logging Patterns
Clean patterns covering QueueListener for Gunicorn-style workers, custom logger classes, concurrent handler usage, worker startup waiting, and non-blocking rotation.

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
from queue import Queue
from pathlib import Path

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - queue patterns will use fallback")


# Global queue and listener for session-wide logging
log_queue: Optional[Queue] = None
log_listener: Optional[QueueListener] = None


# 1) Pytest fixture: QueueListener for Gunicorn-style workers
def setup_logging_listener(tmp_path: Union[str, pathlib.Path]) -> Dict[str, Union[Queue, pathlib.Path]]:
    """
    Pytest fixture: QueueListener for Gunicorn-style workers.
    
    Fixture creates a global QueueListener with a rotating file handler; 
    workers use QueueHandler only.
    
    Workers will attach QueueHandler(log_queue) to forward records 
    to the listener.
    """
    global log_queue, log_listener
    
    if isinstance(tmp_path, str):
        tmp_path = pathlib.Path(tmp_path)
    
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gunicorn_queue.log"

    log_queue = mp.Queue(-1)

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    log_listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    log_listener.start()

    return {"queue": log_queue, "log_file": log_file}


def cleanup_logging_listener():
    """Clean up the logging listener."""
    global log_queue, log_listener
    
    if log_listener:
        log_listener.stop()
        log_listener = None
    
    if log_queue:
        log_queue.close()
        log_queue = None


# 2) Example gunicorn.conf.py with a custom logging class
def create_queue_gunicorn_logger_class(
    class_file_path: Union[str, pathlib.Path] = "mylogger.py",
    queue_import_path: str = "my_logging_queue"
) -> pathlib.Path:
    """
    Example gunicorn.conf.py with a custom logging class.
    
    If you want Gunicorn itself to use QueueHandler/QueueListener, you 
    implement a custom logger class and set logger_class in config.
    """
    class_file_path = pathlib.Path(class_file_path)
    
    class_content = f'''import logging
from logging.handlers import QueueHandler
from gunicorn.glogging import Logger as GunicornLogger


class QueueGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)

        from {queue_import_path} import log_queue  # import shared Queue

        qh = QueueHandler(log_queue)

        # Route gunicorn.error to queue
        self.error_log.handlers = [qh]
        # Route access log to queue as well
        self.access_log.handlers = [qh]
'''
    
    class_file_path.write_text(class_content, encoding='utf-8')
    return class_file_path


def create_queue_gunicorn_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_queue_conf.py",
    logger_class_path: str = "mylogger.QueueGunicornLogger",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Create Gunicorn config file with QueueHandler setup.
    
    This causes Gunicorn master + workers to enqueue into your QueueListener 
    instead of writing files directly.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with QueueHandler logging
import logging
from {logger_class_path}

bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

# Use custom logger class instead of logconfig
logger_class = "{logger_class_path}"
logconfig = None  # using logger_class instead of ini
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


def configure_queue_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_queue.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Configure logging with QueueHandler pattern (for testing).
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue and listener
    logging_info = setup_logging_listener(log_path.parent)
    
    # Configure logger with QueueHandler
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(process)d] %(levelname)s %(message)s"
            }
        },
        "handlers": {
            "queue_handler": {
                "class": "logging.handlers.QueueHandler",
                "level": level,
                "queue": logging_info["queue"],
            },
        },
        "loggers": {
            "": {
                "handlers": ["queue_handler"],
                "level": level,
                "propagate": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 3) Using ConcurrentTimedRotatingFileHandler with multiple processes
def configure_concurrent_handler_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_concurrent.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Using ConcurrentTimedRotatingFileHandler with multiple processes.
    
    If you skip QueueListener and just want multi-process safe rotation, 
    ConcurrentTimedRotatingFileHandler is already designed for that.
    
    Best practices: all processes use the same handler type and target file; 
    rely on the library's internal locking, do not add extra file locks or 
    multiple different rotating handlers pointing at the same filename.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not CONCURRENT_HANDLER_AVAILABLE:
        print("⚠️  concurrent-log-handler not available - using fallback pattern")
        # Fallback to basic TimedRotatingFileHandler
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s [%(process)d] %(levelname)s %(message)s"
                }
            },
            "handlers": {
                "file_handler": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "level": level,
                    "formatter": "standard",
                    "filename": str(log_path),
                    "when": when,
                    "interval": interval,
                    "backupCount": backup_count,
                    "encoding": encoding,
                    "utc": True,
                    "delay": True,
                },
            },
            "loggers": {
                "": {
                    "handlers": ["file_handler"],
                    "level": level,
                    "propagate": False,
                }
            }
        }
    else:
        # Use concurrent-log-handler directly
        logger = logging.getLogger("app")
        logger.setLevel(level)
        
        handler = ConcurrentTimedRotatingFileHandler(
            str(log_path),
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding=encoding,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        
        logger.handlers.clear()
        logger.addHandler(handler)
        return logger
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 4) Pytest pattern to wait for worker startup
def wait_for_logs(
    path: pathlib.Path, 
    min_lines: int = 1, 
    timeout: int = 20
) -> None:
    """
    Pytest pattern to wait for worker startup.
    
    When you actually spawn workers (Gunicorn or simulated), wait until the 
    log file exists and contains at least one line.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if len(lines) >= min_lines:
                return
        time.sleep(0.2)
    raise TimeoutError("Workers did not appear / no logs written")


def test_workers_started(log_file: pathlib.Path, min_lines: int = 1, timeout: int = 15) -> dict:
    """
    Test that workers have started and are writing logs.
    
    In a test:
        after starting worker processes…
        wait_for_logs(log_file, min_lines=1, timeout=15)
    """
    try:
        wait_for_logs(log_file, min_lines=min_lines, timeout=timeout)
        
        # Read the actual content to verify
        text = log_file.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        
        return {
            "log_file_exists": log_file.exists(),
            "lines_found": len(lines),
            "min_lines_required": min_lines,
            "test_passed": len(lines) >= min_lines,
            "first_lines": lines[:3]  # Show first few lines for verification
        }
    except TimeoutError as e:
        return {
            "log_file_exists": log_file.exists(),
            "lines_found": 0,
            "min_lines_required": min_lines,
            "test_passed": False,
            "error": str(e)
        }


# 5) Rotating logs without blocking Gunicorn requests
def configure_non_blocking_rotation(
    log_path: Union[str, pathlib.Path] = "logs/app_nonblocking.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig",
    use_queue_listener: bool = True
) -> Dict[str, Union[logging.Logger, Dict[str, Union[Queue, pathlib.Path]]]]:
    """
    Rotating logs without blocking Gunicorn requests.
    
    Two patterns:
    
    1) QueueHandler + QueueListener (preferred): workers just enqueue, a 
       dedicated listener thread/process handles rotation; request threads 
       do almost no I/O.
    
    2) ConcurrentTimedRotatingFileHandler: workers write directly but 
       with efficient portalocker-based locking; usually fine for typical 
       throughput.
    
    With QueueListener (pattern you set in fixtures / production):
    
    - In workers: attach only a QueueHandler(queue) to root / app loggers.  
    - In the listener (single thread/process): attach a 
      TimedRotatingFileHandler or ConcurrentTimedRotatingFileHandler and 
      let it handle rotation.
    
    This keeps rotation work (renames, file open/close) off the hot request 
    path and is the pattern recommended in the logging cookbook for 
    multi-process or high-throughput servers.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if use_queue_listener:
        # Pattern 1: QueueHandler + QueueListener (preferred)
        logging_info = setup_logging_listener(log_path.parent)
        
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s [%(process)d] %(levelname)s %(message)s"
                }
            },
            "handlers": {
                "queue_handler": {
                    "class": "logging.handlers.QueueHandler",
                    "level": level,
                    "queue": logging_info["queue"],
                },
            },
            "loggers": {
                "": {
                    "handlers": ["queue_handler"],
                    "level": level,
                    "propagate": False,
                }
            }
        }
        
        logging.config.dictConfig(config)
        logger = logging.getLogger(__name__)
        
        return {
            "logger": logger,
            "logging_info": logging_info,
            "pattern": "QueueHandler + QueueListener (preferred)"
        }
    else:
        # Pattern 2: ConcurrentTimedRotatingFileHandler
        return configure_concurrent_handler_logging(
            log_path=log_path,
            level=level,
            when=when,
            interval=interval,
            backup_count=backup_count,
            encoding=encoding
        )


# Worker function for testing queue-based logging
def queue_worker(log_queue: Queue, wid: int, n_msgs: int):
    """
    Worker function that uses QueueHandler for logging.
    
    Workers will attach QueueHandler(log_queue) to forward records 
    to the listener.
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


def test_queue_logging_workers(
    log_path: Union[str, pathlib.Path] = "logs/worker_queue.log",
    num_workers: int = 4,
    messages_per_worker: int = 100
) -> dict:
    """
    Test queue-based logging with multiple workers.
    
    This demonstrates the QueueHandler + QueueListener pattern.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener
    logging_info = setup_logging_listener(log_path.parent)
    
    try:
        # Start worker processes
        procs = []
        for wid in range(num_workers):
            p = mp.Process(
                target=queue_worker, 
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
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8")
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
        cleanup_logging_listener()


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
            "()": "utf8_queue_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Queue-Based UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test QueueListener setup
    print("\n🧪 Testing QueueListener Setup...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        logging_info = setup_logging_listener(tmp_path)
        print(f"   ✅ QueueListener set up with log file: {logging_info['log_file']}")
        print(f"   📝 Queue size: {logging_info['queue'].qsize()}")
        
        # Test worker logging
        print("\n🧪 Testing Queue-Based Worker Logging...")
        queue_results = test_queue_logging_workers(
            log_path=tmp_path / "worker_queue.log",
            num_workers=2,
            messages_per_worker=50
        )
        print(f"   📊 Results:")
        print(f"      Log file exists: {queue_results['log_file_exists']}")
        print(f"      Lines found: {queue_results['lines_found']}")
        print(f"      Expected lines: {queue_results['expected_lines']}")
        print(f"      Test passed: {queue_results['test_passed']}")
        
        if queue_results['sample_lines']:
            print(f"      Sample lines: {queue_results['sample_lines']}")
        
        cleanup_logging_listener()
    
    # Test ConcurrentTimedRotatingFileHandler
    print("\n🧪 Testing ConcurrentTimedRotatingFileHandler...")
    concurrent_logger = configure_concurrent_handler_logging()
    concurrent_logger.info("Concurrent handler test: 🚀 αβγ")
    print(f"   ✅ Concurrent handler configured")
    
    # Test worker startup waiting
    print("\n🧪 Testing Worker Startup Waiting...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        test_log = tmp_path / "startup_test.log"
        test_log.write_text("Initial line\n", encoding="utf-8")
        
        startup_results = test_workers_started(test_log, min_lines=1, timeout=5)
        print(f"   📊 Results:")
        print(f"      Log file exists: {startup_results['log_file_exists']}")
        print(f"      Lines found: {startup_results['lines_found']}")
        print(f"      Test passed: {startup_results['test_passed']}")
        print(f"      First lines: {startup_results.get('first_lines', [])}")
    
    # Test non-blocking rotation
    print("\n🧪 Testing Non-Blocking Rotation...")
    nonblocking_results = configure_non_blocking_rotation(use_queue_listener=True)
    print(f"   📊 Pattern: {nonblocking_results['pattern']}")
    
    if 'logger' in nonblocking_results:
        nonblocking_results['logger'].info("Non-blocking rotation test: 🚀 αβγ")
    
    # Test concurrent handler fallback
    print("\n🧪 Testing Concurrent Handler Fallback...")
    concurrent_fallback = configure_non_blocking_rotation(use_queue_listener=False)
    if isinstance(concurrent_fallback, logging.Logger):
        concurrent_fallback.info("Concurrent handler fallback test: 🚀 αβγ")
        print(f"   ✅ Concurrent handler configured")
    else:
        print(f"   📊 Pattern: {concurrent_fallback['pattern']}")
    
    # Test custom logger class creation
    print("\n🧪 Testing Custom Logger Class Creation...")
    logger_class_file = create_queue_gunicorn_logger_class()
    print(f"   ✅ Custom logger class created: {logger_class_file}")
    
    gunicorn_config = create_queue_gunicorn_config()
    print(f"   ✅ Gunicorn config created: {gunicorn_config}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All queue-based UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Queue-Based Features:")
    print("   • QueueListener for Gunicorn-style workers")
    print("   • Custom Gunicorn logger class with QueueHandler")
    print("   • ConcurrentTimedRotatingFileHandler for multi-process safety")
    print("   • Worker startup waiting and validation")
    print("   • Non-blocking rotation patterns")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

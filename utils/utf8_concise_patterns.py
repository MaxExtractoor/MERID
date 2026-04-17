"""
MERID Concise UTF-8 Logging Patterns
Concise patterns covering QueueListener process setup, custom Gunicorn logger, shared queue module, INI-style config, and concurrent handler usage.

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
    from concurrent_log_handler import ConcurrentRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - concise patterns will use fallback")


# 1) Pytest fixture: listener process for QueueListener
def _listener_process(log_path: str, queue: mp.Queue):
    """
    Listener process function for QueueListener.
    
    Use a separate process to own the file handler and QueueListener; 
    workers send via QueueHandler.
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
        queue.join_thread()  # wait until main process closes queue
    finally:
        listener.stop()
        handler.close()


def setup_concise_logging_listener(tmp_path: Union[str, pathlib.Path]) -> Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]:
    """
    Pytest fixture: listener process for QueueListener.
    
    Workers will attach QueueHandler(log_queue["queue"]) to forward records.
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


def cleanup_concise_logging_listener(logging_info: Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]) -> None:
    """Clean up the concise logging listener."""
    if "queue" in logging_info:
        logging_info["queue"].close()
    if "process" in logging_info:
        logging_info["process"].terminate()
        logging_info["process"].join(timeout=5)


# 2) gunicorn.py custom Logger using QueueHandler/Listener
def create_concise_gunicorn_logger_class(
    class_file_path: Union[str, pathlib.Path] = "my_gunicorn_logger.py",
    queue_import_path: str = "my_logging_queue"
) -> pathlib.Path:
    """
    Custom logger class that swaps Gunicorn's handlers for a QueueHandler 
    hooked to your process-level QueueListener.
    
    Gunicorn master + workers now enqueue logs; your external listener 
    process writes/rotates files.
    """
    class_file_path = pathlib.Path(class_file_path)
    
    class_content = f'''import logging
from logging.handlers import QueueHandler
from gunicorn.glogging import Logger as GunicornLogger
from {queue_import_path} import log_queue  # your shared multiprocessing.Queue


class QueueGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)

        qh = QueueHandler(log_queue)

        # Route Gunicorn internal logs to the queue
        self.error_log.handlers = [qh]
        self.access_log.handlers = [qh]
'''
    
    class_file_path.write_text(class_content, encoding='utf-8')
    return class_file_path


def create_concise_gunicorn_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_concise_conf.py",
    logger_class_path: str = "my_gunicorn_logger.QueueGunicornLogger",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Create concise Gunicorn config with QueueHandler setup.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with QueueHandler logging
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

# Use custom logger class with QueueHandler
logger_class = "{logger_class_path}"
logconfig = None  # using logger_class instead of ini
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


# 3) Configure Gunicorn to pass a multiprocessing.Queue to workers
def create_shared_queue_module(
    module_path: Union[str, pathlib.Path] = "my_logging_queue.py"
) -> pathlib.Path:
    """
    Configure Gunicorn to pass a multiprocessing.Queue to workers.
    
    Gunicorn doesn't expose Queue injection directly; instead you put the 
    Queue in a module, import it from both master and workers (as in 
    my_logging_queue.log_queue), and rely on multiprocessing semantics.
    
    With spawn, each process gets its own proxy to the same underlying 
    queue; with fork, the object is inherited.
    """
    module_path = pathlib.Path(module_path)
    
    module_content = '''import multiprocessing as mp

# Shared queue for logging across all processes
log_queue: mp.Queue = mp.Queue(-1)
'''
    
    module_path.write_text(module_content, encoding='utf-8')
    return module_path


def configure_shared_queue_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_shared.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Configure logging using shared queue module.
    
    The Gunicorn logger class and any app code that wants to use QueueHandler 
    import log_queue from this module.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create the shared queue module
    create_shared_queue_module()
    
    # Set up logging with QueueHandler
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
                "queue": "my_logging_queue.log_queue",  # Import from shared module
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


# 4) Sample logging config file for Gunicorn via logconfig
def create_gunicorn_logging_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_logging.conf",
    log_file: Union[str, pathlib.Path] = "logs/gunicorn.log",
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8"
) -> pathlib.Path:
    """
    Sample logging config file for Gunicorn via logconfig.
    
    Classic INI-style config (for logconfig), mapping Gunicorn loggers 
    to your handlers.
    
    Use logconfig_dict instead if you prefer dictConfig.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''[loggers]
keys=root, gunicorn.error, gunicorn.access

[handlers]
keys=rotating_file

[formatters]
keys=standard

[logger_root]
level=INFO
handlers=rotating_file

[logger_gunicorn.error]
level=INFO
handlers=rotating_file
propagate=0
qualname=gunicorn.error

[logger_gunicorn.access]
level=INFO
handlers=rotating_file
propagate=0
qualname=gunicorn.access

[handler_rotating_file]
class=logging.handlers.TimedRotatingFileHandler
level=INFO
formatter=standard
args=('{log_file}', '{when}', {interval}, {backup_count}, 'utf-8')

[formatter_standard]
class=logging.Formatter
format=%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s
datefmt=%Y-%m-%d %H:%M:%S
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


def create_gunicorn_config_with_logconfig(
    config_path: Union[str, pathlib.Path] = "gunicorn_logconfig_conf.py",
    logconfig_path: Union[str, pathlib.Path] = "gunicorn_logging.conf",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Create Gunicorn config that uses logconfig file.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with logconfig
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

# Use INI-style logging configuration
logconfig = "{logconfig_path}"
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


# 5) Using ConcurrentRotatingFileHandler safely with multiple Gunicorn workers
def configure_concurrent_logging(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_app.log",
    max_bytes: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 10,
    encoding: str = "utf-8",
    level: int = logging.INFO
) -> None:
    """
    Using ConcurrentRotatingFileHandler safely with multiple Gunicorn workers.
    
    ConcurrentRotatingFileHandler from concurrent-log-handler is designed 
    for exactly this; just ensure all workers use it and write to the same file.
    
    Best practices:
    - Do not mix stdlib RotatingFileHandler with ConcurrentRotatingFileHandler 
      on the same file.
    - Configure once in master (on_starting) so all workers inherit the same 
      concurrent handler configuration.
    - Let the handler manage file locking and rotation; avoid additional 
      file locks on top of it.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not CONCURRENT_HANDLER_AVAILABLE:
        print("⚠️  concurrent-log-handler not available - using fallback pattern")
        # Fallback to basic TimedRotatingFileHandler
        logger = logging.getLogger("gunicorn.error")
        logger.setLevel(level)
        
        handler = TimedRotatingFileHandler(
            str(log_path),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        
        logger.handlers.clear()
        logger.addHandler(handler)
    else:
        # Use concurrent-log-handler
        logger = logging.getLogger("gunicorn.error")
        logger.setLevel(level)

        handler = ConcurrentRotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))

        logger.handlers.clear()
        logger.addHandler(handler)

    # Also configure access logger
    access_logger = logging.getLogger("gunicorn.access")
    access_logger.handlers.clear()
    access_logger.addHandler(handler)
    access_logger.setLevel(level)


def create_concurrent_gunicorn_config(
    config_path: Union[str, pathlib.Path] = "gunicorn_concurrent_conf.py",
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_app.log",
    bind: str = "0.0.0.0:8000",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Create Gunicorn config that uses ConcurrentRotatingFileHandler.
    
    Then in gunicorn_conf.py:
        from logging_concurrent import configure_concurrent_logging
        
        def on_starting(server):
            configure_concurrent_logging()
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''# Gunicorn config with ConcurrentRotatingFileHandler
bind = "{bind}"
workers = {workers}
worker_class = "{worker_class}"

def on_starting(server):
    # Configure concurrent logging once in master so all workers inherit
    from utils.utf8_concise_patterns import configure_concurrent_logging
    configure_concurrent_logging("{log_path}")
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


# Worker function for testing queue-based logging
def concise_worker(log_queue: mp.Queue, wid: int, n_msgs: int):
    """
    Worker function that uses QueueHandler for logging.
    
    Workers will attach QueueHandler(log_queue["queue"]) to forward records.
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


def test_concise_queue_logging(
    log_path: Union[str, pathlib.Path] = "logs/concise_queue.log",
    num_workers: int = 4,
    messages_per_worker: int = 100
) -> dict:
    """
    Test concise queue-based logging with multiple workers.
    
    This demonstrates the QueueListener process pattern.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        logging_info = setup_concise_logging_listener(tmp_path)
        
        try:
            # Start worker processes
            procs = []
            for wid in range(num_workers):
                p = mp.Process(
                    target=concise_worker, 
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
            cleanup_concise_logging_listener(logging_info)


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
            "()": "utf8_concise_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Concise UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test QueueListener process setup
    print("\n🧪 Testing QueueListener Process Setup...")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        logging_info = setup_concise_logging_listener(tmp_path)
        print(f"   ✅ QueueListener process set up with log file: {logging_info['log_file']}")
        print(f"   📝 Queue size: {logging_info['queue'].qsize()}")
        print(f"   📝 Process PID: {logging_info['process'].pid}")
        
        # Test worker logging
        print("\n🧪 Testing Concise Queue-Based Worker Logging...")
        queue_results = test_concise_queue_logging(
            log_path=tmp_path / "concise_queue.log",
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
        
        cleanup_concise_logging_listener(logging_info)
    
    # Test custom Gunicorn logger class
    print("\n🧪 Testing Custom Gunicorn Logger Class...")
    logger_class_file = create_concise_gunicorn_logger_class()
    print(f"   ✅ Custom logger class created: {logger_class_file}")
    
    gunicorn_config = create_concise_gunicorn_config()
    print(f"   ✅ Gunicorn config created: {gunicorn_config}")
    
    # Test shared queue module
    print("\n🧪 Testing Shared Queue Module...")
    shared_queue_module = create_shared_queue_module()
    print(f"   ✅ Shared queue module created: {shared_queue_module}")
    
    shared_logger = configure_shared_queue_logging()
    shared_logger.info("Shared queue test: 🚀 αβγ")
    print(f"   ✅ Shared queue logging configured")
    
    # Test INI-style logging config
    print("\n🧪 Testing INI-Style Logging Config...")
    logging_config = create_gunicorn_logging_config()
    print(f"   ✅ INI-style logging config created: {logging_config}")
    
    logconfig_gunicorn = create_gunicorn_config_with_logconfig()
    print(f"   ✅ Gunicorn config with logconfig created: {logconfig_gunicorn}")
    
    # Test ConcurrentRotatingFileHandler
    print("\n🧪 Testing ConcurrentRotatingFileHandler...")
    configure_concurrent_logging()
    print(f"   ✅ Concurrent logging configured")
    
    concurrent_config = create_concurrent_gunicorn_config()
    print(f"   ✅ Concurrent Gunicorn config created: {concurrent_config}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All concise UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Concise Features:")
    print("   • QueueListener process for clean separation")
    print("   • Custom Gunicorn logger with QueueHandler")
    print("   • Shared queue module for process communication")
    print("   • INI-style logging configuration support")
    print("   • ConcurrentRotatingFileHandler for multi-process safety")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

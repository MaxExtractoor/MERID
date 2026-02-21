"""
MERID Logging Configuration with QueueListener + File Rotation
Concise drop-in patterns for MERID.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import multiprocessing as mp
import os
from pathlib import Path
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from typing import Optional

LOG_QUEUE: Optional[mp.Queue] = None
LOG_LISTENER: Optional[QueueListener] = None
LOG_LISTENER_HANDLERS: list[logging.Handler] = []


def _resolve_default_log_path() -> str:
    """
    Resolve default log path at call time.
    
    env wins, otherwise relative logs/merid.log
    """
    return str(Path(os.getenv("MERID_LOG_PATH", "logs/merid.log")))


# Expose a constant for introspection (computed at import time)
DEFAULT_LOG_PATH = Path(_resolve_default_log_path())


def get_default_log_path() -> str:
    """
    Get default log path from environment or fallback.
    
    Environment-driven path so MERID services can adopt this without 
    hard-coding paths per deployment.
    """
    # Check for environment variable first
    log_path = os.environ.get("MERID_LOG_PATH")
    if log_path:
        return log_path
    
    # Check for common log directories
    common_paths = [
        "logs",
        "var/log/merid",
        "/var/log/merid",
        os.path.expanduser("~/logs/merid"),
    ]
    
    for path in common_paths:
        # Create directory if it doesn't exist
        expanded_path = os.path.expanduser(path)
        if not os.path.exists(expanded_path):
            try:
                os.makedirs(expanded_path, exist_ok=True)
            except (OSError, PermissionError):
                continue
        
        # Check if directory is writable
        if os.access(expanded_path, os.W_OK):
            return os.path.join(expanded_path, "merid.log")
    
    # Fallback to current directory
    return "merid.log"


def base_dict_config(log_path: str) -> dict:
    """
    Base dictConfig for MERID logging.
    
    Pattern: dictConfig for format/handlers, plus a small bootstrap that 
    wires QueueHandler/QueueListener around it.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(process)d] %(processName)s "
                          "%(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "rotating_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": log_path,
                "when": "midnight",
                "interval": 1,
                "backupCount": 7,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "merid": {
                "handlers": ["rotating_file"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["rotating_file"],
            "level": "INFO",
        },
    }


def start_merid_logging(log_path: Optional[str] = None):
    """
    Start QueueListener + QueueHandler setup:
    
    - listener thread owns TimedRotatingFileHandler
    - all loggers send records via QueueHandler
    
    Startup: call start_merid_logging() or start_merid_logging("logs/merid.log") 
    in the main/orchestrator.
    
    Environment variable: MERID_LOG_PATH can be set to override the default path.
    
    Services can either:
    - rely on MERID_LOG_PATH from env, or
    - call start_merid_logging() with no arguments for a sensible default.
    """
    global LOG_QUEUE, LOG_LISTENER, LOG_LISTENER_HANDLERS

    # resolve default each time, so env override is honored
    path = log_path or _resolve_default_log_path()

    # Ensure the directory exists for the log file
    log_dir = os.path.dirname(path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except (OSError, PermissionError) as e:
            # Surface the actual dictConfig error for debugging
            raise RuntimeError(f"Cannot create log directory {log_dir}: {e}")

    cfg = base_dict_config(path)
    logging.config.dictConfig(cfg)

    LOG_QUEUE = mp.Queue(-1)

    # Grab existing handlers to attach to QueueListener
    root = logging.getLogger()
    existing_handlers = root.handlers[:]

    # remember handlers so we can close them later
    LOG_LISTENER_HANDLERS = existing_handlers

    # Remove direct handlers; replace with QueueHandler
    for h in existing_handlers:
        root.removeHandler(h)

    LOG_LISTENER = QueueListener(LOG_QUEUE, *existing_handlers, respect_handler_level=True)
    LOG_LISTENER.start()

    # Root now only sends to queue
    root.addHandler(QueueHandler(LOG_QUEUE))


def shutdown_merid_logging():
    """
    Shutdown MERID logging gracefully.
    
    Shutdown: call shutdown_merid_logging() at process exit.
    """
    global LOG_QUEUE, LOG_LISTENER, LOG_LISTENER_HANDLERS

    # Stop listener and drain queue
    if LOG_LISTENER is not None:
        LOG_LISTENER.enqueue_sentinel()
        LOG_LISTENER.stop()

    # Close handlers so files are released (important on Windows)
    for h in LOG_LISTENER_HANDLERS:
        try:
            h.close()
        except Exception:
            pass
    LOG_LISTENER_HANDLERS = []

    if LOG_QUEUE is not None:
        LOG_QUEUE.close()
        LOG_QUEUE = None
    LOG_LISTENER = None


# Worker initialization function
def init_merid_worker_logging():
    """
    Best practices for reinitializing loggers in worker processes.
    
    When you spawn MERID workers (processes):
    
    - Do not re-create file handlers.
    - Do clear and reattach a QueueHandler pointing at the existing queue.
    """
    global LOG_QUEUE
    if LOG_QUEUE is None:
        raise RuntimeError("MERID logging queue not initialized. Call start_merid_logging() first.")
    
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(LOG_QUEUE))


# Test worker functions
def _spam_worker(idx: int, n: int):
    """
    Spam worker for testing rotation under load.
    
    Core rule: only the listener thread/process owns the TimedRotatingFileHandler. 
    All worker processes send LogRecords via the queue.
    """
    init_merid_worker_logging()
    log = logging.getLogger(f"merid.spam.{idx}")
    for i in range(n):
        log.info("wid=%d msg=%d", idx, i)


def _test_worker():
    """Test worker for basic functionality."""
    init_merid_worker_logging()
    log = logging.getLogger("merid.worker.test")
    log.info("test worker started")


def _worker_main():
    """
    Example worker entrypoint.
    
    In each worker entrypoint:
    
    def worker_main():
        from merid_worker_init import init_merid_worker_logging
        init_merid_worker_logging()
        log = logging.getLogger("merid.worker")
        log.info("worker started")
    """
    init_merid_worker_logging()
    log = logging.getLogger("merid.worker")
    log.info("worker started")

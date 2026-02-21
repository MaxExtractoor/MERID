"""
MERID Minimal Integration with QueueHandler
Central idea: MERID workers just push to a shared queue; a listener process (or thread) does all file I/O.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
from logging.handlers import QueueHandler, TimedRotatingFileHandler
from typing import Optional

# Global queue for MERID logging
LOG_QUEUE: Optional[mp.Queue] = None


def _listener(path: str, queue: mp.Queue):
    """Listener process function - module level for pickling support."""
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(processName)s %(levelname)s %(name)s %(message)s"
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


def start_merid_listener(log_path: str) -> mp.Process:
    """
    Start background logging listener for MERID.
    
    Minimal MERID integration with QueueHandler.
    
    A small helper module for MERID to centralize wiring.
    """
    global LOG_QUEUE
    LOG_QUEUE = mp.Queue(-1)

    proc = mp.Process(target=_listener, args=(log_path, LOG_QUEUE), daemon=True)
    proc.start()
    return proc


def configure_merid_worker_logging():
    """
    Call once in each MERID worker process.
    
    MERID orchestrator:
    
    listener_proc = start_merid_listener("logs/merid.log")
    # spawn workers, each calls configure_merid_worker_logging()
    
    shutdown:
    
    LOG_QUEUE.put_nowait(None)
    LOG_QUEUE.close()
    listener_proc.join(timeout=5)
    
    This matches the cookbook and avoids multiple processes touching file handlers.
    """
    global LOG_QUEUE
    if LOG_QUEUE is None:
        raise RuntimeError("MERID logging queue not initialized. Call start_merid_listener() first.")
    
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(LOG_QUEUE))


def stop_merid_logging_listener(listener_proc: mp.Process):
    """
    Signal the listener to shut down from tests.
    
    Use a sentinel and join in teardown.
    """
    global LOG_QUEUE
    if LOG_QUEUE is not None:
        try:
            LOG_QUEUE.put_nowait(None)  # sentinel for listener loop
        except ValueError:
            pass  # Queue already closed
        try:
            LOG_QUEUE.close()
        except ValueError:
            pass  # Queue already closed
        LOG_QUEUE = None
    
    listener_proc.join(timeout=5)


def shutdown_merid_logging():
    """
    Shutdown MERID logging gracefully.
    
    LOG_QUEUE.put_nowait(None)
    LOG_QUEUE.close()
    """
    global LOG_QUEUE
    if LOG_QUEUE is not None:
        try:
            LOG_QUEUE.put_nowait(None)
        except ValueError:
            pass  # Queue already closed
        try:
            LOG_QUEUE.close()
        except ValueError:
            pass  # Queue already closed
        LOG_QUEUE = None


def spam_worker(wid: int, n: int):
    """
    Spam worker for high-volume rotation testing.
    
    Testing TimedRotatingFileHandler rollover with multiprocessing logs.
    
    Stress rotation by using a short interval (when="s") and multiple workers 
    sending via the queue.
    """
    configure_merid_worker_logging()
    log = logging.getLogger(f"merid.spam.{wid}")
    for i in range(n):
        log.info("wid=%d msg=%d", wid, i)


# Worker function for testing
def merid_worker(logger_name: str, n: int):
    """
    Sample MERID worker function for testing.
    
    Call once in each MERID worker process.
    """
    configure_merid_worker_logging()
    log = logging.getLogger(logger_name)
    for i in range(n):
        log.info("wid=%s msg=%d", logger_name, i)


# Test worker functions for the patterns
def _test_worker(logger_name: str):
    """Test worker for pattern validation."""
    configure_merid_worker_logging()
    log = logging.getLogger(logger_name)
    for i in range(10):
        log.info("wid=%s msg=%d", logger_name, i)


# Listener process function for testing
def _listener_process(log_path: str, queue: mp.Queue):
    """
    Listener process function for testing.
    
    This matches the pattern used in start_merid_logging_listener().
    """
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s"
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    try:
        while True:
            record = queue.get()
            if record is None:
                break
            logging.getLogger(record.name).handle(record)
    finally:
        handler.close()


# Best-practice formatting for multiprocessing records
MERID_FORMAT = "%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s"
"""
Recommended format: include timestamp, PID, level, logger name, and message.

Optional extras:
- %(processName)s for human-friendly names.
- A structured wid=/msg= pair in the message, as you're already doing, 
  to assert origin per MERID worker in tests.
- Use handler levels (handler.setLevel(logging.INFO)) in the listener 
  to filter, and leave worker roots at DEBUG or INFO.
"""

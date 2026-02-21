"""
MERID Queue-Based Logging Configuration
Adapting QueueListener to MERID's logging config.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
from logging.handlers import QueueHandler, TimedRotatingFileHandler, RotatingFileHandler
from typing import Optional

LOG_QUEUE: Optional[mp.Queue] = None


def _listener_proc(path: str, queue: mp.Queue, h_type: str):
    """Listener process function - module level for pickling support."""
    configure_merid_listener(path, h_type)
    try:
        while True:
            record = queue.get()
            if record is None:
                break
            logging.getLogger(record.name).handle(record)
    finally:
        for h in logging.getLogger().handlers:
            h.close()


def configure_merid_listener(log_path: str, handler_type: str = "timed"):
    """
    Configure logging in the listener (single process).
    
    Adaptation: treat the queue-based path as a "backend" and keep your existing loggers.
    """
    if handler_type == "timed":
        handler = TimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
    elif handler_type == "rotating":
        handler = RotatingFileHandler(
            log_path,
            maxBytes=50*1024*1024,  # 50MB
            backupCount=10,
            encoding="utf-8",
        )
    else:
        handler = TimedRotatingFileHandler(
            log_path,
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


def start_merid_listener(log_path: str, handler_type: str = "timed") -> mp.Process:
    """
    Start background listener process; MERID workers send to LOG_QUEUE.
    
    Integrate with existing config by calling configure_merid_listener instead 
    of your file handlers in the master.
    """
    global LOG_QUEUE
    LOG_QUEUE = mp.Queue(-1)

    proc = mp.Process(target=_listener_proc, args=(log_path, LOG_QUEUE, handler_type), daemon=True)
    proc.start()
    return proc


def configure_merid_worker_logging():
    """
    Call once in each MERID worker process.
    
    In workers, you keep using your normal loggers (logging.getLogger("merid.swarm.worker") 
    etc.); only the root handler changes to a QueueHandler.
    """
    global LOG_QUEUE
    if LOG_QUEUE is None:
        raise RuntimeError("MERID logging queue not initialized. Call start_merid_listener() first.")
    
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(LOG_QUEUE))


def merid_worker_init():
    """
    Minimal override in each worker process.
    
    If MERID already configures named loggers via dictConfig, the minimal 
    override in each worker is:
    """
    configure_merid_worker_logging()


def shutdown_merid_logging():
    """
    Shutdown MERID logging gracefully.
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


def _test_worker():
    """Test worker for shutdown testing."""
    configure_merid_worker_logging()
    logger = logging.getLogger("merid.test.worker")
    logger.info("MERID test worker")


def _spam_worker(queue, wid: int, n: int):
    """Spam worker for rotation testing."""
    configure_merid_worker_logging()
    logger = logging.getLogger(f"merid.spam.{wid}")
    for i in range(n):
        logger.info("wid=%d msg=%d", wid, i)


def _test_worker_with_extra():
    """Test worker with extra fields for attribute testing."""
    configure_merid_worker_logging()
    logger = logging.getLogger("merid.test.worker.extra")
    logger.info("event", extra={"merid_worker_id": 42})


def _adapted_worker():
    """Adapted worker for integration testing."""
    configure_merid_worker_logging()
    logger = logging.getLogger("merid.adapted.worker")
    logger.info("adapted test message from worker")

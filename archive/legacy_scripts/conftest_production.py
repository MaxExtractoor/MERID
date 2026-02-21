"""
MERID Production-Style Pytest Configuration
Production-style patterns for multiprocessing logging with QueueListener.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import multiprocessing as mp
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import pytest


def _listener_process(log_path: str, queue: mp.Queue):
    """
    Pytest fixture that stops a QueueListener after tests.
    
    For a separate listener process using a multiprocessing.Queue, 
    stop it in fixture teardown with a sentinel and join.
    """
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

    try:
        while True:
            record = queue.get()
            if record is None:  # sentinel => shutdown
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
    finally:
        handler.close()


@pytest.fixture(scope="session")
def log_queue(tmp_path_factory):
    """
    Session-wide multiprocessing logging queue + listener process.
    
    This is the same sentinel pattern used in cookbook QueueHandler/QueueListener 
    multi-process examples.
    """
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "multiproc.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(target=_listener_process, args=(str(log_file), q), daemon=True)
    proc.start()

    yield {"queue": q, "log_file": log_file}

    # graceful shutdown: send sentinel, close queue, join listener
    q.put_nowait(None)
    q.close()
    proc.join(timeout=5)

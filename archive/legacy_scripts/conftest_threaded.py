"""
MERID Threaded Listener Pytest Configuration
Using multiprocessing.Queue with QueueListener in tests.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
from logging.handlers import QueueHandler, QueueListener
from multiprocessing import Queue
import pytest


@pytest.fixture
def thread_listener():
    """
    Using multiprocessing.Queue with QueueListener in tests.
    
    If you prefer a threaded listener instead of a separate process, 
    use QueueListener with multiprocessing.Queue (or queue.Queue) in the same process.
    
    Workers in the same process just log via normal loggers; the QueueListener 
    handles them asynchronously.
    """
    q = Queue(-1)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(processName)s %(levelname)s %(name)s %(message)s"
    ))

    listener = QueueListener(q, handler, respect_handler_level=True)
    listener.start()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(q))

    yield {"queue": q, "listener": listener}

    # Fixture to join and terminate a QueueListener thread safely
    listener.enqueue_sentinel()
    listener.stop()

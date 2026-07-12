import logging
import multiprocessing as mp
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import pytest


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "kalshi_crypto_15m_v2: Tests for the kalshi_crypto_15m_v2 profile (BTC/ETH/SOL/XRP/DOGE 15m sentiment-free trading)"
    )
    config.addinivalue_line(
        "markers", "sentiment_research: Research-only sentiment tests excluded from live 15m Kalshi runs"
    )


def pytest_sessionstart(session):
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Already set (e.g., on Linux when running under fork)
        pass
    
    # Clear SCALPER15M environment variables to ensure consistent test behavior
    import os
    os.environ.pop("SCALPER15M_MIN_CUTOFF_MINUTES", None)


def _listener_process(log_path: str, queue: mp.Queue):
    """
    Gracefully stopping a QueueListener from a pytest fixture.
    
    For a separate listener process, use a sentinel and join in fixture teardown.
    This is exactly the pattern in the logging cookbook example.
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
    Shared multiprocessing.Queue + listener process for all tests.
    
    This guarantees the listener drains all records before exiting.
    """
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "merid.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(target=_listener_process, args=(str(log_file), q), daemon=True)
    proc.start()

    yield {"queue": q, "log_file": log_file}

    # graceful shutdown after all tests/children are done
    q.put_nowait(None)  # sentinel
    q.close()
    proc.join(timeout=5)

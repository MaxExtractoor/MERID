import logging
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

bind = "0.0.0.0:8000"
workers = 4
worker_class = "sync"  # or uvicorn.workers.UvicornWorker, etc.


def _configure_logging():
    logger = logging.getLogger("gunicorn.error")
    logger.setLevel(logging.INFO)

    handler = ConcurrentTimedRotatingFileHandler(
        "logs/gunicorn_app.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))

    logger.handlers.clear()
    logger.addHandler(handler)

    access_logger = logging.getLogger("gunicorn.access")
    access_logger.handlers.clear()
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)


def on_starting(server):
    _configure_logging()


def pre_fork(server, worker):
    # Runs in master, just before forking a worker
    pass


def post_fork(server, worker):
    # Runs in worker right after fork; logging handlers from master are inherited
    # You can tweak per-worker context here if needed.
    pass


def post_worker_init(worker):
    # Called after worker app initialization.
    # Avoid reconfiguring logging here; it should already be set up in master.
    pass

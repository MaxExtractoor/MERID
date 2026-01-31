import logging
from logging.handlers import QueueHandler
from gunicorn.glogging import Logger as GunicornLogger
from my_logging_queue import log_queue


class QueueGunicornLogger(GunicornLogger):
    def setup(self, cfg):
        super().setup(cfg)

        qh = QueueHandler(log_queue)

        # Route Gunicorn logs into the queue
        self.error_log.handlers = [qh]
        self.access_log.handlers = [qh]

"""
MERID Structured Logging Configuration
Environment-based logging with JSON for tests, human-readable for dev
"""

import logging
import os
import sys
import structlog
from structlog import contextvars


def configure_logging():
    """Configure structlog based on environment"""
    is_test = os.getenv("APP_ENV") == "test" or "PYTEST_CURRENT_TEST" in os.environ
    
    # Shared processors for all environments
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]
    
    if is_test:
        # JSON logs for tests
        processors = shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Human-readable logs for development
        processors = shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    
    # Configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def bind_correlation_context(correlation_id: str = None, test_id: str = None, **kwargs):
    """Bind correlation context variables"""
    contextvars.clear_contextvars()
    
    context_vars = {}
    if correlation_id:
        context_vars["correlation_id"] = correlation_id
    if test_id:
        context_vars["test_id"] = test_id
    
    context_vars.update(kwargs)
    
    if context_vars:
        contextvars.bind_contextvars(**context_vars)


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger"""
    return structlog.get_logger(name)

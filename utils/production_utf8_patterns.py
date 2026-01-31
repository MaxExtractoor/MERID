"""
MERID Production UTF-8 Logging Patterns
Concise, production-oriented UTF-8 logging patterns for MERID systems.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import sys
import io
import logging.config
from pathlib import Path
from typing import Union
from logging.handlers import RotatingFileHandler


def configure_console_utf8(level: int = logging.INFO) -> logging.Logger:
    """
    Console StreamHandler with UTF-8 on Windows.
    
    This wraps the underlying binary stdout in a UTF-8 text wrapper and gives 
    logging a StreamHandler that bypasses the cp1252 console encoding while 
    still being safe on Windows.
    
    Args:
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )

    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(console)

    return logger


# dictConfig with UTF-8 RotatingFileHandler
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        },
        "detailed": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(module)s:%(lineno)d - %(message)s"
        }
    },
    "handlers": {
        "rotating_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app.log",
            "mode": "a",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "standard",
            "stream": "ext://sys.stdout"
        }
    },
    "loggers": {
        "": {  # root logger
            "handlers": ["rotating_file"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["rotating_file"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["rotating_file"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_logging_from_dict(config: dict = None) -> logging.Logger:
    """
    Configure logging from dictConfig with UTF-8 RotatingFileHandler.
    
    Here, `encoding: "utf-8"` on the `RotatingFileHandler` is the key to 
    making rotated logs Unicode-safe.
    
    Args:
        config: Logging configuration dictionary (default: LOGGING_CONFIG)
    
    Returns:
        Configured logger instance
    """
    if config is None:
        config = LOGGING_CONFIG
    
    # Ensure log directory exists
    if "handlers" in config:
        for handler_name, handler_config in config["handlers"].items():
            if "filename" in handler_config:
                log_path = Path(handler_config["filename"])
                log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(config)
    return logging.getLogger()


def configure_utf8_logging_py27(
    log_path: Union[str, Path] = "logs/app.log", 
    level: int = logging.INFO
) -> logging.Logger:
    """
    Python 2.7-compatible UTF-8 file logging.
    
    Python 2.7 logging doesn't have the `encoding` kwarg on basicConfig, so 
    use a `FileHandler` with an explicit codec-wrapped stream.
    
    This pattern (wrapping a file with `codecs.open` and using it as the stream) 
    is the standard workaround for UTF-8 logs on 2.7.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    import codecs
    
    logger = logging.getLogger()
    logger.setLevel(level)

    # Ensure log directory exists
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Open file with UTF-8 encoding and wrap as a stream
    stream = codecs.open(str(log_path), mode="a", encoding="utf-8")

    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    logger.handlers = []
    logger.addHandler(handler)

    return logger


def configure_thread_safe_utf8_logging(
    log_path: Union[str, Path] = "logs/app.log",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Thread-safe UTF-8 logging with rotating handler.
    
    The logging module uses internal locks on loggers and handlers so that 
    writes to a given handler are serialized across threads. This means multiple 
    threads can safely use the same logger and handler instances without 
    corrupting the log file; only one thread writes at a time.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
        max_bytes: Maximum bytes before rotation (default: 5MB)
        backup_count: Number of backup files to keep (default: 5)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Single rotating file handler for thread safety
    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(threadName)s - %(message)s"
    ))

    logger.handlers.clear()
    logger.addHandler(file_handler)

    return logger


def demo_exception_logging():
    """
    Demonstrate exception logging with traceback and UTF-8.
    
    With the UTF-8 handlers above in place, exception logging "just works":
    
    - `logger.exception(...)` logs at ERROR level and appends the full traceback 
      to the message using the handler's stream and encoding.
    - Because the console/file handlers are UTF-8, both the exception message 
      and any non-ASCII characters are preserved in the traceback output without 
      `UnicodeEncodeError`.
    """
    logger = configure_console_utf8()

    try:
        raise ValueError(u"Bad data 🚀 αβγ")
    except Exception:
        logger.exception("Unhandled error while processing request")


# MERID-specific production configurations
def get_merid_production_logger(
    name: str = "merid",
    log_path: Union[str, Path] = "logs/merid.log",
    level: int = logging.INFO
) -> logging.Logger:
    """
    Get MERID production logger with UTF-8 console and rotating file handlers.
    
    Args:
        name: Logger name (default: "merid")
        log_path: Path to log file (default: "logs/merid.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 console handler
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )
    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    ))

    # UTF-8 rotating file handler
    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(module)s:%(lineno)d - %(message)s"
    ))

    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


def get_merid_governance_logger() -> logging.Logger:
    """Get MERID governance logger with UTF-8 support."""
    return get_merid_production_logger(
        name="merid.governance",
        log_path="governance/governance.log"
    )


def get_merid_analytics_logger() -> logging.Logger:
    """Get MERID analytics logger with UTF-8 support."""
    return get_merid_production_logger(
        name="merid.analytics",
        log_path="analytics/analytics.log"
    )


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Production UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test console UTF-8 logging
    print("\n🧪 Testing Console UTF-8 Logging...")
    console_logger = configure_console_utf8()
    console_logger.info("Console test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test dictConfig logging
    print("\n🧪 Testing dictConfig UTF-8 Logging...")
    dict_logger = configure_logging_from_dict()
    dict_logger.info("dictConfig test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test thread-safe logging
    print("\n🧪 Testing Thread-Safe UTF-8 Logging...")
    thread_logger = configure_thread_safe_utf8_logging()
    thread_logger.info("Thread-safe test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test MERID production logger
    print("\n🧪 Testing MERID Production Logger...")
    merid_logger = get_merid_production_logger()
    merid_logger.info("MERID production test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test exception logging
    print("\n🧪 Testing Exception Logging with UTF-8...")
    demo_exception_logging()
    
    print("\n✅ All production UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

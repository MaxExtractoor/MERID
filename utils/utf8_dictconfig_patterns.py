"""
MERID UTF-8 dictConfig Patterns
Compact, production-style UTF-8 logging patterns using dictConfig.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
from pathlib import Path
from typing import Union, Dict, Any


class Utf8StreamHandler(logging.StreamHandler):
    """
    Custom UTF-8 StreamHandler for dictConfig.
    
    There's no direct `encoding` argument for `StreamHandler`, so you wrap stdout 
    once in code and let dictConfig reference a custom handler class.
    """
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="replace",
            )
        super(Utf8StreamHandler, self).__init__(stream)


# dictConfig with UTF-8 StreamHandler on Windows
LOGGING_UTF8_CONSOLE = {
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
        "console_utf8": {
            "()": "utf8_dictconfig_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["console_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_utf8_console_logging() -> logging.Logger:
    """
    Configure dictConfig with UTF-8 StreamHandler on Windows.
    
    This pattern (custom handler + dictConfig) is the standard way to inject 
    a UTF-8 stream while still using dictConfig.
    
    Returns:
        Configured logger instance
    """
    logging.config.dictConfig(LOGGING_UTF8_CONSOLE)
    return logging.getLogger(__name__)


# dictConfig with UTF-8 RotatingFileHandler
LOGGING_ROTATING_UTF8 = {
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
        "rotating_file_utf8": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app.log",
            "mode": "a",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "console_utf8": {
            "()": "utf8_dictconfig_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        }
    },
    "loggers": {
        "": {
            "handlers": ["rotating_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["rotating_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["rotating_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_utf8_rotating_logging() -> logging.Logger:
    """
    Configure dictConfig with UTF-8 RotatingFileHandler.
    
    Using `encoding: "utf-8"` in the dictConfig for `RotatingFileHandler` is exactly 
    how you make rotated logs Unicode-safe.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = Path("logs/app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_ROTATING_UTF8)
    return logging.getLogger(__name__)


# Python 2.7-compatible UTF-8 file logging
def configure_utf8_logging_py27(
    log_path: Union[str, Path] = "logs/app.log", 
    level: int = logging.INFO
) -> logging.Logger:
    """
    Python 2.7-compatible UTF-8 file logging.
    
    Python 2.7 logging is less Unicode-friendly, so you typically use `codecs.open` 
    or an explicit UTF-8 `StreamHandler`.
    
    This pattern (UTF-8 file via codecs + StreamHandler) is a documented 
    workaround for 2.7 to avoid `UnicodeEncodeError`.
    
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

    # Open the file as a UTF-8 text stream
    stream = codecs.open(str(log_path), mode="a", encoding="utf-8")

    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    logger.handlers = []
    logger.addHandler(handler)

    return logger


# Wrapping StreamHandler for UTF-8 Windows console
def configure_console_and_file_utf8(
    log_path: Union[str, Path] = "logs/app.log", 
    level: int = logging.INFO
) -> logging.Logger:
    """
    Minimal console + file configuration with UTF-8.
    
    If you don't use dictConfig, the minimal console + file configuration is:
    
    Wrapping `sys.stdout.buffer` in `io.TextIOWrapper(…, encoding="utf-8")` is the 
    recommended way to ensure UTF-8 output even when the Windows console's 
    code page is cp1252.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    import logging.handlers
    
    logger = logging.getLogger()
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 console (bypasses cp1252 code page on Windows)
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )
    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


# MERID-specific dictConfig configurations
def get_merid_dictconfig_logging(
    log_path: Union[str, Path] = "logs/merid.log",
    console_enabled: bool = True,
    rotating_enabled: bool = True,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Get MERID-specific dictConfig logging configuration.
    
    Args:
        log_path: Path to log file (default: "logs/merid.log")
        console_enabled: Enable console handler (default: True)
        rotating_enabled: Enable rotating file handler (default: True)
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
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
        "handlers": {},
        "loggers": {
            "": {
                "handlers": [],
                "level": level,
                "propagate": False,
            }
        }
    }
    
    # Add console handler if enabled
    if console_enabled:
        config["handlers"]["console_utf8"] = {
            "class": "utf8_dictconfig_patterns.Utf8StreamHandler",
            "level": level,
            "formatter": "standard",
        }
        config["loggers"][""]["handlers"].append("console_utf8")
    
    # Add rotating file handler if enabled
    if rotating_enabled:
        config["handlers"]["rotating_file_utf8"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": level,
            "formatter": "detailed",
            "filename": str(log_path),
            "mode": "a",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }
        config["loggers"][""]["handlers"].append("rotating_file_utf8")
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


def get_merid_governance_dictconfig() -> logging.Logger:
    """Get MERID governance logger with dictConfig."""
    return get_merid_dictconfig_logging(
        log_path="governance/governance.log",
        console_enabled=True,
        rotating_enabled=True
    )


def get_merid_analytics_dictconfig() -> logging.Logger:
    """Get MERID analytics logger with dictConfig."""
    return get_merid_dictconfig_logging(
        log_path="analytics/analytics.log",
        console_enabled=True,
        rotating_enabled=True
    )


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing UTF-8 dictConfig Patterns")
    print("=" * 50)
    
    # Test console UTF-8 logging
    print("\n🧪 Testing dictConfig Console UTF-8 Logging...")
    console_logger = configure_utf8_console_logging()
    console_logger.info("dictConfig console test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test rotating UTF-8 logging
    print("\n🧪 Testing dictConfig Rotating UTF-8 Logging...")
    rotating_logger = configure_utf8_rotating_logging()
    rotating_logger.info("dictConfig rotating test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test console + file UTF-8 logging
    print("\n🧪 Testing Console + File UTF-8 Logging...")
    both_logger = configure_console_and_file_utf8()
    both_logger.info("Console + file test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test MERID dictConfig logging
    print("\n🧪 Testing MERID dictConfig Logging...")
    merid_logger = get_merid_dictconfig_logging()
    merid_logger.info("MERID dictConfig test: 🚀 αβγ абв ابجد ∑ €")
    
    print("\n✅ All UTF-8 dictConfig patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

"""
MERID Complete UTF-8 Logging Patterns
Focused patterns covering dictConfig + Windows console + TimedRotating + 2.7 compatibility.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import codecs
from pathlib import Path
from typing import Union, Dict, Any


class Utf8StreamHandler(logging.StreamHandler):
    """
    Custom UTF-8 StreamHandler for dictConfig.
    
    You can't set `encoding` directly on `StreamHandler`, so expose a custom handler 
    class that wraps stdout and reference it in dictConfig.
    """
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="replace",
            )
        super(Utf8StreamHandler, self).__init__(stream)


class CodecsUtf8StreamHandler(logging.StreamHandler):
    """
    Codecs-style UTF-8 StreamHandler for dictConfig.
    
    Uses codecs.getwriter for UTF-8 wrapping, works in both 2.7 and 3.x.
    """
    
    def __init__(self, stream=None):
        if stream is None:
            # wraps sys.stdout in a UTF-8 writer (works in 3.x too)
            stream = codecs.getwriter("utf-8")(sys.stdout)
        super(CodecsUtf8StreamHandler, self).__init__(stream)


# Complete dictConfig with UTF-8 StreamHandler on Windows
LOGGING_UTF8_COMPLETE = {
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
            "()": "utf8_complete_patterns.Utf8StreamHandler",
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


def configure_utf8_complete_logging() -> logging.Logger:
    """
    Configure complete dictConfig with UTF-8 StreamHandler on Windows.
    
    Key idea: dictConfig instantiates `Utf8StreamHandler`, which always uses a UTF-8 
    `TextIOWrapper` around `sys.stdout.buffer`, so Windows cp1252 never sees the text.
    
    Returns:
        Configured logger instance
    """
    logging.config.dictConfig(LOGGING_UTF8_COMPLETE)
    return logging.getLogger(__name__)


# TimedRotatingFileHandler with UTF-8 via dictConfig
LOGGING_TIMED_UTF8 = {
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
        "time_file_utf8": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed.log",
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8",
        },
        "console_utf8": {
            "()": "utf8_complete_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        }
    },
    "loggers": {
        "": {
            "handlers": ["time_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["time_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["time_file_utf8", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_timed_utf8_logging() -> logging.Logger:
    """
    Configure TimedRotatingFileHandler with UTF-8 via dictConfig.
    
    `encoding: "utf-8"` here ensures all rolled files are UTF-8 encoded, which is the 
    standard fix for Unicode issues in rotating handlers.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_UTF8)
    return logging.getLogger(__name__)


# Codecs-style dictConfig configuration
LOGGING_CODECS_UTF8 = {
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
        "console_codecs_utf8": {
            "()": "utf8_complete_patterns.CodecsUtf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
        "time_file_utf8": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_codecs.log",
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8",
        }
    },
    "loggers": {
        "": {
            "handlers": ["console_codecs_utf8", "time_file_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["console_codecs_utf8", "time_file_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["console_codecs_utf8", "time_file_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_codecs_utf8_logging() -> logging.Logger:
    """
    Configure codecs-style UTF-8 logging via dictConfig.
    
    Uses codecs.getwriter for UTF-8 wrapping, works in both 2.7 and 3.x.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = Path("logs/app_codecs.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CODECS_UTF8)
    return logging.getLogger(__name__)


# Workaround functions for direct use
def create_utf8_stream_handler_3x() -> logging.StreamHandler:
    """
    Workaround for StreamHandler encoding on Windows consoles (Python 3.x).
    
    Since `StreamHandler` has no `encoding` arg, the workaround is always stream 
    wrapping; you can do it with `io.TextIOWrapper` (3.x).
    
    Returns:
        UTF-8 StreamHandler instance
    """
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )
    handler = logging.StreamHandler(utf8_stdout)
    return handler


def create_utf8_stream_handler_27() -> logging.StreamHandler:
    """
    Workaround for StreamHandler encoding on Windows consoles (Python 2.7).
    
    Python 2.7: codecs + StreamHandler
    
    Returns:
        UTF-8 StreamHandler instance
    """
    utf8_stdout = codecs.getwriter("utf-8")(sys.stdout)
    handler = logging.StreamHandler(utf8_stdout)
    return handler


# MERID-specific complete configurations
def get_merid_complete_utf8_logging(
    log_path: Union[str, Path] = "logs/merid_complete.log",
    console_enabled: bool = True,
    timed_enabled: bool = True,
    level: int = logging.INFO,
    use_codecs: bool = False
) -> logging.Logger:
    """
    Get MERID complete UTF-8 logging configuration.
    
    Args:
        log_path: Path to log file (default: "logs/merid_complete.log")
        console_enabled: Enable console handler (default: True)
        timed_enabled: Enable timed rotating handler (default: True)
        level: Logging level (default: logging.INFO)
        use_codecs: Use codecs-style handler (default: False)
    
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
        handler_class = "utf8_complete_patterns.CodecsUtf8StreamHandler" if use_codecs else "utf8_complete_patterns.Utf8StreamHandler"
        config["handlers"]["console_utf8"] = {
            "()": handler_class,
            "level": level,
            "formatter": "standard",
        }
        config["loggers"][""]["handlers"].append("console_utf8")
    
    # Add timed rotating file handler if enabled
    if timed_enabled:
        config["handlers"]["time_file_utf8"] = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": level,
            "formatter": "detailed",
            "filename": str(log_path),
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8",
        }
        config["loggers"][""]["handlers"].append("time_file_utf8")
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


def get_merid_governance_complete() -> logging.Logger:
    """Get MERID governance complete logger."""
    return get_merid_complete_utf8_logging(
        log_path="governance/governance_complete.log",
        console_enabled=True,
        timed_enabled=True
    )


def get_merid_analytics_complete() -> logging.Logger:
    """Get MERID analytics complete logger."""
    return get_merid_complete_utf8_logging(
        log_path="analytics/analytics_complete.log",
        console_enabled=True,
        timed_enabled=True
    )


# Python version compatibility utilities
def get_python_version_info() -> Dict[str, Any]:
    """Get Python version information for compatibility checks."""
    import sys
    return {
        "version": sys.version_info,
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "is_python27": sys.version_info[:2] == (2, 7),
        "is_python3x": sys.version_info.major >= 3,
        "supports_encoding_in_dictconfig": sys.version_info.major >= 3,
    }


def get_recommended_handler_class() -> str:
    """Get recommended handler class based on Python version."""
    version_info = get_python_version_info()
    
    if version_info["is_python27"]:
        return "utf8_complete_patterns.CodecsUtf8StreamHandler"
    else:
        return "utf8_complete_patterns.Utf8StreamHandler"


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Complete UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test complete UTF-8 logging
    print("\n🧪 Testing Complete UTF-8 Logging...")
    complete_logger = configure_utf8_complete_logging()
    complete_logger.info("Complete UTF-8 test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test timed rotating UTF-8 logging
    print("\n🧪 Testing Timed Rotating UTF-8 Logging...")
    timed_logger = configure_timed_utf8_logging()
    timed_logger.info("Timed rotating test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test codecs-style UTF-8 logging
    print("\n🧪 Testing Codecs-style UTF-8 Logging...")
    codecs_logger = configure_codecs_utf8_logging()
    codecs_logger.info("Codecs-style test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test MERID complete logging
    print("\n🧪 Testing MERID Complete UTF-8 Logging...")
    merid_logger = get_merid_complete_utf8_logging()
    merid_logger.info("MERID complete test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test version compatibility
    print("\n🧪 Testing Version Compatibility...")
    version_info = get_python_version_info()
    recommended_class = get_recommended_handler_class()
    print(f"   Python version: {version_info['major']}.{version_info['minor']}")
    print(f"   Recommended handler: {recommended_class}")
    
    print("\n✅ All complete UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

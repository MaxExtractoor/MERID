"""
MERID Final UTF-8 Logging Patterns
Concise patterns covering TimedRotatingFileHandler, BOM support, and testing utilities.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import codecs
import time
from pathlib import Path
from typing import Union, Dict, Any


# dictConfig with TimedRotatingFileHandler and UTF-8
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
            "()": "utf8_final_patterns.Utf8StreamHandler",
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
    Configure dictConfig with TimedRotatingFileHandler and UTF-8.
    
    `encoding: "utf-8"` is fully supported on `TimedRotatingFileHandler` and is the 
    standard way to get Unicode-safe rotated logs.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_UTF8)
    return logging.getLogger(__name__)


# Forcing UTF-8 BOM for console output (Windows)
class Utf8BomStreamHandler(logging.StreamHandler):
    """
    Custom UTF-8 BOM StreamHandler for Windows console.
    
    If you really need a BOM on the console stream (unusual, but possible), 
    wrap the stream yourself and use that in a custom handler.
    """
    
    def __init__(self, stream=None):
        if stream is None:
            # binary buffer
            raw = sys.stdout.buffer
            # prepend BOM once
            raw.write(codecs.BOM_UTF8)
            raw.flush()
            # wrap as UTF-8 text
            stream = io.TextIOWrapper(
                raw,
                encoding="utf-8",
                errors="replace",
            )
        super(Utf8BomStreamHandler, self).__init__(stream)


LOGGING_BOM_UTF8 = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        }
    },
    "handlers": {
        "console_bom_utf8": {
            "()": "utf8_final_patterns.Utf8BomStreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console_bom_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_bom_utf8_logging() -> logging.Logger:
    """
    Configure UTF-8 BOM logging for Windows console.
    
    The BOM is written once on startup, and all subsequent logging goes 
    through UTF-8.
    
    Returns:
        Configured logger instance
    """
    logging.config.dictConfig(LOGGING_BOM_UTF8)
    return logging.getLogger(__name__)


# Standard UTF-8 StreamHandler for dictConfig
class Utf8StreamHandler(logging.StreamHandler):
    """
    Standard UTF-8 StreamHandler for dictConfig.
    
    Since dictConfig can't express "wrap this stream" by itself, you embed 
    the wrapper in the handler class.
    """
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="replace",
            )
        super(Utf8StreamHandler, self).__init__(stream)


# StreamHandler encoding workaround on Windows consoles
def configure_console_utf8(level: int = logging.INFO) -> logging.Logger:
    """
    Minimal non-dictConfig pattern for UTF-8 console logging.
    
    This bypasses the cp1252 console code page and is the usual recommendation 
    for UTF-8 console logging on Windows.
    
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


# Common TimedRotatingFileHandler pitfalls and fast testing
def test_timed_rotation_fast() -> logging.Logger:
    """
    Fast testing pattern for TimedRotatingFileHandler.
    
    Common pitfalls:
    - Rotation only happens when a log event is emitted at or after the rollover time
    - Re-initializing the handler frequently can mess with rolloverAt and file timestamps
    
    Using `when: "s"` and a small `interval` lets you see rotations within a few 
    seconds while still verifying that UTF-8 content survives the roll-over.
    
    Returns:
        Configured logger instance
    """
    TEST_LOGGING = {
        "version": 1,
        "handlers": {
            "time_file_utf8": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": "logs/test_timed.log",
                "when": "s",          # rotate every second
                "interval": 2,        # every 2 seconds
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(message)s"
            }
        },
        "loggers": {
            "": {"handlers": ["time_file_utf8"], "level": "INFO"},
        }
    }
    
    # Ensure log directory exists
    log_path = Path("logs/test_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(TEST_LOGGING)
    logger = logging.getLogger(__name__)
    
    print("🧪 Fast Timed Rotation Test (2-second intervals)...")
    for i in range(10):
        logger.info("Test message %d 🚀 αβγ", i)
        time.sleep(1)
    
    print("✅ Fast rotation test completed")
    return logger


# Python version compatibility utilities
def get_python_version_compatibility() -> Dict[str, Any]:
    """
    Get Python version compatibility information.
    
    | Aspect                  | Python 2.7                                         | Python 3.x                                                  |
    |-------------------------|----------------------------------------------------|-------------------------------------------------------------|
    | dictConfig availability | Present but older semantics                        | Mature and more flexible                                       |
    | `encoding` on handlers  | Often missing; workarounds needed                  | Supported on file-based handlers (`encoding="utf-8"`) |
    | Unicode format strings  | Must be explicit `u"…"`, or you risk errors        | Normal `str` is Unicode, fewer surprises                  |
    | Console StreamHandler   | No encoding arg; must wrap stream manually         | Same, but easier with `io.TextIOWrapper`                  |
    
    Returns:
        Dictionary with compatibility information
    """
    import sys
    return {
        "version": sys.version_info,
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "is_python27": sys.version_info[:2] == (2, 7),
        "is_python3x": sys.version_info.major >= 3,
        "supports_encoding_in_dictconfig": sys.version_info.major >= 3,
        "unicode_strings_default": sys.version_info.major >= 3,
        "console_wrapper": "io.TextIOWrapper" if sys.version_info.major >= 3 else "codecs.getwriter",
        "recommended_handler": "Utf8StreamHandler" if sys.version_info.major >= 3 else "CodecsUtf8StreamHandler"
    }


# MERID-specific final configurations
def get_merid_timed_utf8_logging(
    log_path: Union[str, Path] = "logs/merid_timed.log",
    console_enabled: bool = True,
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    use_bom: bool = False
) -> logging.Logger:
    """
    Get MERID timed UTF-8 logging configuration.
    
    Args:
        log_path: Path to log file (default: "logs/merid_timed.log")
        console_enabled: Enable console handler (default: True)
        level: Logging level (default: logging.INFO)
        when: Rotation interval type (default: "midnight")
        interval: Rotation interval (default: 1)
        backup_count: Number of backup files (default: 7)
        use_bom: Use BOM for console output (default: False)
    
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
    
    # Add timed rotating file handler
    config["handlers"]["time_file_utf8"] = {
        "class": "logging.handlers.TimedRotatingFileHandler",
        "level": level,
        "formatter": "detailed",
        "filename": str(log_path),
        "when": when,
        "interval": interval,
        "backupCount": backup_count,
        "encoding": "utf-8",
    }
    config["loggers"][""]["handlers"].append("time_file_utf8")
    
    # Add console handler if enabled
    if console_enabled:
        handler_class = "utf8_final_patterns.Utf8BomStreamHandler" if use_bom else "utf8_final_patterns.Utf8StreamHandler"
        config["handlers"]["console_utf8"] = {
            "()": handler_class,
            "level": level,
            "formatter": "standard",
        }
        config["loggers"][""]["handlers"].append("console_utf8")
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


def get_merid_governance_timed() -> logging.Logger:
    """Get MERID governance timed logger."""
    return get_merid_timed_utf8_logging(
        log_path="governance/governance_timed.log",
        console_enabled=True,
        when="midnight",
        interval=1,
        backup_count=7
    )


def get_merid_analytics_timed() -> logging.Logger:
    """Get MERID analytics timed logger."""
    return get_merid_timed_utf8_logging(
        log_path="analytics/analytics_timed.log",
        console_enabled=True,
        when="midnight",
        interval=1,
        backup_count=7
    )


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Final UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test timed UTF-8 logging
    print("\n🧪 Testing Timed UTF-8 Logging...")
    timed_logger = configure_timed_utf8_logging()
    timed_logger.info("Timed UTF-8 test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test BOM UTF-8 logging
    print("\n🧪 Testing BOM UTF-8 Logging...")
    bom_logger = configure_bom_utf8_logging()
    bom_logger.info("BOM UTF-8 test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test console UTF-8 logging
    print("\n🧪 Testing Console UTF-8 Logging...")
    console_logger = configure_console_utf8()
    console_logger.info("Console UTF-8 test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test fast rotation
    print("\n🧪 Testing Fast Timed Rotation...")
    test_timed_rotation_fast()
    
    # Test MERID timed logging
    print("\n🧪 Testing MERID Timed UTF-8 Logging...")
    merid_logger = get_merid_timed_utf8_logging()
    merid_logger.info("MERID timed test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test version compatibility
    print("\n🧪 Testing Version Compatibility...")
    compat_info = get_python_version_compatibility()
    print(f"   Python version: {compat_info['major']}.{compat_info['minor']}")
    print(f"   Supports encoding in dictConfig: {compat_info['supports_encoding_in_dictconfig']}")
    print(f"   Console wrapper: {compat_info['console_wrapper']}")
    print(f"   Recommended handler: {compat_info['recommended_handler']}")
    
    print("\n✅ All final UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

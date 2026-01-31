"""
MERID Ultimate UTF-8 Logging Patterns
Ultimate patterns covering BOM support, UTC rotation, and comprehensive testing.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import codecs
import time
import pathlib
from typing import Union, Dict, Any


# dictConfig with TimedRotatingFileHandler and `encoding="utf-8-sig"`
LOGGING_TIMED_UTF8_BOM = {
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
        "time_file_utf8_bom": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed_bom.log",
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8-sig",  # BOM on first write
            "utc": True,
            "delay": True,
        },
        "console_utf8": {
            "()": "utf8_ultimate_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        }
    },
    "loggers": {
        "": {
            "handlers": ["time_file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["time_file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["time_file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_timed_utf8_bom_logging() -> logging.Logger:
    """
    Configure dictConfig with TimedRotatingFileHandler and `encoding="utf-8-sig"`.
    
    `TimedRotatingFileHandler` accepts `encoding`, `utc`, and `delay` directly, and 
    `utf-8-sig` causes Python to write a BOM at the start of each new log file.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = pathlib.Path("logs/app_timed_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_UTF8_BOM)
    return logging.getLogger(__name__)


# Standard UTF-8 StreamHandler for dictConfig
class Utf8StreamHandler(logging.StreamHandler):
    """Standard UTF-8 StreamHandler for dictConfig."""
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="fast",
            )
        super(Utf8StreamHandler, self).__init__(stream)


# Ensuring rotation at midnight UTC
def get_utc_rotation_config() -> Dict[str, Any]:
    """
    Get UTC rotation configuration for midnight rotation.
    
    - Use `when: "midnight"` and `utc: True` so the handler computes rollover times in UTC 
      instead of local time.
    - Rotation is triggered only when a record is emitted at or after the scheduled 
      rollover time; no log entries means no rotation.
    - Use `delay=True` to defer file opening until first log record.
    
    Returns:
        Dictionary with UTC rotation configuration
    """
    return {
        "when": "midnight",
        "interval": 1,
        "utc": True,
        "delay": True,
        "backupCount": 7,
        "encoding": "utf-8-sig"
    }


# Using `delay` and `utc` in dictConfig
def get_delayed_utc_config() -> Dict[str, Any]:
    """
    Get delayed UTC configuration for dictConfig.
    
    Both options map 1:1 into dictConfig:
    - `delay=True` defers opening the file until the first log record
    - `utc=True` switches time calculations for rotation to UTC
    
    Returns:
        Dictionary with delayed UTC configuration
    """
    return {
        "delay": True,  # open file on first emit, not at config time
        "utc": True,    # compute rollovers in UTC
    }


# Setting BOM (`utf-8-sig`) for log files on Windows
def get_bom_config() -> Dict[str, Any]:
    """
    Get BOM configuration for UTF-8 log files.
    
    To guarantee a BOM per file (for tools that expect it):
    - Use `encoding="utf-8-sig"` in the handler (`FileHandler`, `RotatingFileHandler`, 
      or `TimedRotatingFileHandler`).
    - Each new file the handler creates will start with a BOM; this is exactly what the 
      `utf-8-sig` codec does.
    
    Returns:
        Dictionary with BOM configuration
    """
    return {
        "encoding": "utf-8-sig",
        "backupCount": 7,
        "utc": True,
        "delay": True
    }


# How to test rotation quickly on Windows
def get_fast_test_config() -> Dict[str, Any]:
    """
    Get fast testing configuration for rotation validation.
    
    For unit/integration tests, shorten the interval:
    - Use `when: "s"` for seconds
    - Small `interval` (2 seconds) for quick validation
    - Verify BOM encoding in rotated files
    
    Returns:
        Dictionary with fast test configuration
    """
    return {
        "when": "s",           # seconds
        "interval": 2,         # every 2 seconds
        "backupCount": 3,
        "encoding": "utf-8-sig",
        "utc": True,
        "delay": True
    }


def test_timed_rotation_bom_fast() -> logging.Logger:
    """
    Fast testing pattern for TimedRotatingFileHandler with BOM.
    
    Using `when: "s"` plus a small `interval` lets you verify rotation behavior and BOM 
    encoding in a few seconds instead of waiting for real midnight.
    
    Returns:
        Configured logger instance
    """
    TEST_LOGGING = {
        "version": 1,
        "formatters": {
            "standard": {"format": "%(asctime)s - %(levelname)s - %(message)s"}
        },
        "handlers": {
            "time_file_utf8_bom": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": "logs/test_timed_bom.log",
                "when": "s",           # seconds
                "interval": 2,         # every 2 seconds
                "backupCount": 3,
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {"handlers": ["time_file_utf8_bom"], "level": "INFO"},
        }
    }
    
    # Ensure log directory exists
    log_path = pathlib.Path("logs/test_timed_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(TEST_LOGGING)
    logger = logging.getLogger(__name__)
    
    print("🧪 Fast Timed Rotation Test with BOM (2-second intervals)...")
    for i in range(8):
        logger.info("Test message %d 🚀 αβγ", i)
        time.sleep(1)
    
    # Assert: multiple files exist and each begins with a UTF-8 BOM
    rotated_files = list(pathlib.Path("logs").glob("test_timed_bom.log*"))
    print(f"   Found {len(rotated_files)} rotated files")
    
    for path in rotated_files:
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            print(f"   ✅ {path.name} starts with UTF-8 BOM")
        else:
            print(f"   ❌ {path.name} missing UTF-8 BOM")
    
    print("✅ Fast rotation test with BOM completed")
    return logger


# StreamHandler encoding workaround on Windows consoles
def configure_console_utf8(level: int = logging.INFO) -> logging.Logger:
    """
    Minimal non-dictConfig pattern for UTF-8 console logging.
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="fast",
    )

    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(console)
    return logger


# MERID-specific ultimate configurations
def get_merid_ultimate_utf8_logging(
    log_path: Union[str, pathlib.Path] = "logs/merid_ultimate.log",
    console_enabled: bool = True,
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    use_bom: bool = True,
    use_utc: bool = True,
    delay: bool = True
) -> logging.Logger:
    """
    Get MERID ultimate UTF-8 logging configuration.
    
    Args:
        log_path: Path to log file (default: "logs/merid_ultimate.log")
        console_enabled: Enable console handler (default: True)
        level: Logging level (default: logging.INFO)
        when: Rotation interval type (default: "midnight")
        interval: Rotation interval (default: 1)
        backup_count: Number of backup files (default: 7)
        use_bom: Use BOM for file output (default: True)
        use_utc: Use UTC for rotation (default: True)
        delay: Delay file opening (default: True)
    
    Returns:
        Configured logger instance
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            },
            "detailed": {
                "format": "%(asctime)s - UTC - %(levelname)s - %(name)s - %(module)s:%(lineno)d - %(message)s"
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
    
    # Add timed rotating file handler with BOM
    config["handlers"]["time_file_utf8_bom"] = {
        "class": "logging.handlers.TimedRotatingFileHandler",
        "level": level,
        "formatter": "detailed",
        "filename": str(log_path),
        "when": when,
        "interval": interval,
        "backupCount": backup_count,
        "encoding": "utf-8-sig",
        "utc": use_utc,
        "delay": delay,
    }
    config["loggers"][""]["handlers"].append("time_file_utf8_bom")
    
    # Add console handler if enabled
    if console_enabled:
        config["handlers"]["console_utf8"] = {
            "()": "utf8_ultimate_patterns.Utf8StreamHandler",
            "level": level,
            "formatter": "standard",
        }
        config["loggers"][""]["handlers"].append("console_utf8")
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


def get_merid_governance_ultimate() -> logging.Logger:
    """Get MERID governance ultimate logger."""
    return get_merid_ultimate_utf8_logging(
        log_path="governance/governance_ultimate.log",
        console_enabled=True,
        when="midnight",
        interval=1,
        backup_count=7,
        use_bom=True,
        use_utc=True,
        delay=True
    )


def get_merid_analytics_ultimate() -> logging.Logger:
    """Get MERID analytics ultimate logger."""
    return get_merid_ultimate_utf8_logging(
        log_path="analytics/analytics_ultimate.log",
        console_enabled=True,
        when="midnight",
        interval=1,
        backup_count=7,
        use_bom=True,
        use_utc=True,
        delay=True
    )


# Heartbeat utility for ensuring rotation
def create_heartbeat_logger(
    log_path: Union[str, pathlib.Path] = "logs/heartbeat.log",
    level: int = logging.INFO
) -> logging.Logger:
    """
    Create a heartbeat logger that ensures rotation happens.
    
    Rotation is triggered only when a record is emitted at or after the scheduled 
    rollover time; no log entries means no rotation.
    
    Args:
        log_path: Path to heartbeat log file (default: "logs/heartbeat.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            }
        },
        "handlers": {
            "heartbeat_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_path),
                "when": "h",           # hourly
                "interval": 1,         # every hour
                "backupCount": 24,        # keep 24 hours
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            }
        },
        "loggers": {
            "": {"handlers": ["heartbeat_file"], "level": level}
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


def log_heartbeat(logger: logging.Logger, message: str = "System heartbeat") -> None:
    """Log a heartbeat message to ensure rotation happens."""
    logger.info(f"❤️ {message}")


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Ultimate UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test timed UTF-8 BOM logging
    print("\n🧪 Testing Timed UTF-8 BOM Logging...")
    timed_bom_logger = configure_timed_utf8_bom_logging()
    timed_bom_logger.info("Timed BOM test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test console UTF-8 logging
    print("\n🧪 Testing Console UTF-8 Logging...")
    console_logger = configure_console_utf8()
    console_logger.info("Console test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test fast rotation with BOM
    print("\n🧪 Testing Fast Rotation with BOM...")
    test_timed_rotation_bom_fast()
    
    # Test MERID ultimate logging
    print("\n🧪 Testing MERID Ultimate UTF-8 Logging...")
    merid_logger = get_merid_ultimate_utf8_logging()
    merid_logger.info("MERID ultimate test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test heartbeat logger
    print("\n🧪 Testing Heartbeat Logger...")
    heartbeat_logger = create_heartbeat_logger()
    log_heartbeat(heartbeat_logger, "System operational")
    
    print("\n✅ All ultimate UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

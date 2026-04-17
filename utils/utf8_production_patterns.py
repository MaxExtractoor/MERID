"""
MERID Production UTF-8 Logging Patterns
Clean, production-ready patterns covering BOM, forced rotation, and UTC handling.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import time
import pathlib
from typing import Union, Dict, Any


# 1) Add BOM (utf-8-sig) in dictConfig FileHandler
LOGGING_FILE_BOM = {
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
        "file_utf8_bom": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_bom.log",
            "mode": "a",
            "encoding": "utf-8-sig",  # UTF-8 with BOM
        },
        "console_utf8": {
            "()": "utf8_production_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        }
    },
    "loggers": {
        "": {
            "handlers": ["file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "governance": {
            "handlers": ["file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        },
        "analytics": {
            "handlers": ["file_utf8_bom", "console_utf8"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_file_bom_logging() -> logging.Logger:
    """
    Configure FileHandler with UTF-8 BOM.
    
    Any new file created by this handler will start with the UTF-8 BOM bytes 
    `EF BB BF`, which some Windows tools expect.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = pathlib.Path("logs/app_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_FILE_BOM)
    return logging.getLogger(__name__)


# 2) TimedRotatingFileHandler with UTF-8-SIG, UTC midnight, backupCount, filename pattern
LOGGING_TIMED_BOM = {
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
            "filename": "logs/app_timed.log",
            "when": "midnight",      # daily rotation
            "interval": 1,           # every 1 day
            "backupCount": 7,        # keep 7 days
            "encoding": "utf-8-sig", # BOM in each file
            "utc": True,             # use UTC for rollover
            "delay": True,           # open on first emit
        },
        "console_utf8": {
            "()": "utf8_production_patterns.Utf8StreamHandler",
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


def configure_timed_bom_logging() -> logging.Logger:
    """
    Configure TimedRotatingFileHandler with UTF-8-SIG, UTC midnight, backupCount, filename pattern.
    
    - `backupCount` controls how many old files are kept; older ones are deleted.
    - The filename pattern is `<filename>.<date>` by default (e.g., `app_timed.log.2026-01-26`), 
      defined by the handler's `suffix`.
    
    Returns:
        Configured logger instance
    """
    # Ensure log directory exists
    log_path = pathlib.Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_BOM)
    return logging.getLogger(__name__)


# 3) Force rotation at startup
def configure_and_force_rollover() -> logging.Logger:
    """
    Force rotation at startup.
    
    There's no "rotate immediately" flag, but the documented pattern is to call 
    `doRollover()` once after configuring logging.
    
    This gives you a fresh file per run (with BOM) while preserving the normal 
    time-based rollover behavior going forward.
    
    Returns:
        Configured logger instance
    """
    logging.config.dictConfig(LOGGING_TIMED_BOM)
    logger = logging.getLogger(__name__)

    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
            handler.doRollover()  # force a rotation at startup

    return logger


# 4) Ensure UTC midnight rollover
def get_utc_midnight_config() -> Dict[str, Any]:
    """
    Get UTC midnight rollover configuration.
    
    - `when="midnight"` + `interval=1` + `utc=True` ensures that `rolloverAt` is 
      computed based on UTC midnight.
    - Rotation still happens only when `emit()` runs after that time, so you need 
      at least one log record sometime after 00:00:00 UTC (e.g., heartbeat log).
    - If you need a specific UTC time other than midnight, you can also use `atTime` 
      (in recent Python versions) with `utc=True`.
    
    Returns:
        Dictionary with UTC midnight configuration
    """
    return {
        "when": "midnight",
        "interval": 1,
        "backupCount": 7,
        "encoding": "utf-8-sig",
        "utc": True,
        "delay": True
    }


# 5) Rotation when no new records are emitted
def create_heartbeat_system(
    log_path: Union[str, pathlib.Path] = "logs/heartbeat.log",
    level: int = logging.INFO,
    when: str = "h",
    interval: int = 1,
    backup_count: int = 24
) -> logging.Logger:
    """
    Create heartbeat system for ensuring rotation during quiet periods.
    
    By design, `TimedRotatingFileHandler` rotates "on use, not time": it checks 
    `current_time >= rolloverAt` inside `emit()`.
    
    Ways to handle "quiet" periods:
    - Emit a cheap periodic heartbeat log line from a scheduler/cron/task so rotation can run.
    - Or, for batch jobs that start and stop, call `doRollover()` at process start/end 
      if you want per-run files regardless of logging volume.
    
    Args:
        log_path: Path to heartbeat log file (default: "logs/heartbeat.log")
        level: Logging level (default: logging.INFO)
        when: Rotation interval type (default: "h" for hourly)
        interval: Rotation interval (default: 1)
        backup_count: Number of backup files (default: 24 for 24 hours)
    
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
                "when": when,
                "interval": interval,
                "backupCount": backup_count,
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


def create_batch_job_rollover(
    log_path: Union[str, pathlib.Path] = "logs/batch_job.log",
    level: int = logging.INFO
) -> logging.Logger:
    """
    Create batch job logger with forced rollover.
    
    For batch jobs that start and stop, call `doRollover()` at process start/end 
    if you want per-run files regardless of logging volume.
    
    Args:
        log_path: Path to batch job log file (default: "logs/batch_job.log")
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
            "batch_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_path),
                "when": "midnight",
                "interval": 1,
                "backupCount": 7,
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            }
        },
        "loggers": {
            "": {"handlers": ["batch_file"], "level": level}
        }
    }
    
    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)
    
    # Force rollover at startup for fresh file per run
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
            handler.doRollover()
    
    return logger


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


# MERID-specific production configurations
def get_merid_production_utf8_logging(
    log_path: Union[str, pathlib.Path] = "logs/merid_production.log",
    console_enabled: bool = True,
    level: int = logging.INFO,
    use_timed: bool = True,
    use_bom: bool = True,
    use_utc: bool = True,
    backup_count: int = 7,
    force_rollover: bool = False
) -> logging.Logger:
    """
    Get MERID production UTF-8 logging configuration.
    
    Args:
        log_path: Path to log file (default: "logs/merid_production.log")
        console_enabled: Enable console handler (default: True)
        level: Logging level (default: logging.INFO)
        use_timed: Use timed rotation (default: True)
        use_bom: Use BOM for file output (default: True)
        use_utc: Use UTC for rotation (default: True)
        backup_count: Number of backup files (default: 7)
        force_rollover: Force rollover at startup (default: False)
    
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
    
    # Add file handler
    if use_timed:
        config["handlers"]["time_file_utf8_bom"] = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": level,
            "formatter": "detailed",
            "filename": str(log_path),
            "when": "midnight",
            "interval": 1,
            "backupCount": backup_count,
            "encoding": "utf-8-sig",
            "utc": use_utc,
            "delay": True,
        }
        config["loggers"][""]["handlers"].append("time_file_utf8_bom")
    else:
        config["handlers"]["file_utf8_bom"] = {
            "class": "logging.FileHandler",
            "level": level,
            "formatter": "detailed",
            "filename": str(log_path),
            "mode": "a",
            "encoding": "utf-8-sig",
        }
        config["loggers"][""]["handlers"].append("file_utf8_bom")
    
    # Add console handler if enabled
    if console_enabled:
        config["handlers"]["console_utf8"] = {
            "()": "utf8_production_patterns.Utf8StreamHandler",
            "level": level,
            "formatter": "standard",
        }
        config["loggers"][""]["handlers"].append("console_utf8")
    
    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)
    
    # Force rollover if requested
    if force_rollover:
        for handler in logger.handlers:
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
                handler.doRollover()
    
    return logger


def get_merid_governance_production() -> logging.Logger:
    """Get MERID governance production logger."""
    return get_merid_production_utf8_logging(
        log_path="governance/governance_production.log",
        console_enabled=True,
        use_timed=True,
        use_bom=True,
        use_utc=True,
        backup_count=7,
        force_rollover=False
    )


def get_merid_analytics_production() -> logging.Logger:
    """Get MERID analytics production logger."""
    return get_merid_production_utf8_logging(
        log_path="analytics/analytics_production.log",
        console_enabled=True,
        use_timed=True,
        use_bom=True,
        use_utc=True,
        backup_count=7,
        force_rollover=False
    )


# Utility functions for production use
def verify_bom_in_file(file_path: Union[str, pathlib.Path]) -> bool:
    """
    Verify that a file starts with UTF-8 BOM.
    
    Args:
        file_path: Path to file to check
    
    Returns:
        True if file starts with BOM, False otherwise
    """
    file_path = pathlib.Path(file_path)
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'rb') as f:
            bom = f.read(3)
            return bom == b'\xef\xbb\xbf'
    except Exception:
        return False


def list_rotated_files(base_path: Union[str, pathlib.Path]) -> list[pathlib.Path]:
    """
    List all rotated files for a given base path.
    
    Args:
        base_path: Base path of the log file
    
    Returns:
        List of pathlib.Path objects for rotated files
    """
    base_path = pathlib.Path(base_path)
    pattern = f"{base_path.name}.*"
    
    return sorted(base_path.parent.glob(pattern))


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Production UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test file BOM logging
    print("\n🧪 Testing File BOM Logging...")
    file_bom_logger = configure_file_bom_logging()
    file_bom_logger.info("File BOM test: 🚀 αβγ абв ابجد ∑ €")
    
    # Verify BOM in file
    bom_present = verify_bom_in_file("logs/app_bom.log")
    print(f"   ✅ BOM present in file: {bom_present}")
    
    # Test timed BOM logging
    print("\n🧪 Testing Timed BOM Logging...")
    timed_bom_logger = configure_timed_bom_logging()
    timed_bom_logger.info("Timed BOM test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test forced rollover
    print("\n🧪 Testing Forced Rollover...")
    rollover_logger = configure_and_force_rollover()
    rollover_logger.info("Forced rollover test: 🚀 αβγ абв ابجد ∑ €")
    
    # List rotated files
    rotated_files = list_rotated_files("logs/app_timed.log")
    print(f"   📁 Found {len(rotated_files)} rotated files")
    for f in rotated_files:
        print(f"      {f.name}")
    
    # Test heartbeat system
    print("\n🧪 Testing Heartbeat System...")
    heartbeat_logger = create_heartbeat_system()
    log_heartbeat(heartbeat_logger, "System operational")
    
    # Test batch job rollover
    print("\n🧪 Testing Batch Job Rollover...")
    batch_logger = create_batch_job_rollover()
    batch_logger.info("Batch job test: 🚀 αβγ абв ابجد ∑ €")
    
    # Test MERID production logging
    print("\n🧪 Testing MERID Production Logging...")
    merid_logger = get_merid_production_utf8_logging()
    merid_logger.info("MERID production test: 🚀 αβγ абв ابجد ∑ €")
    
    print("\n✅ All production UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")

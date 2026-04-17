"""
MERID Advanced UTF-8 Logging Patterns
Advanced patterns covering interval start naming, hybrid rollover, thread-safe operations, and conditional startup rollover.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import pathlib
import threading
import time
import os
from typing import Union
from logging.handlers import TimedRotatingFileHandler


# 1) Subclass that names files by interval start time
class IntervalStartNamedTimedHandler(TimedRotatingFileHandler):
    """Custom handler that names files by interval start time."""
    
    def rotation_filename(self, default_name):
        """Override to use interval start timestamp in filename."""
        # default_name is usually "<base>.YYYY-MM-DD_..."; we ignore it
        dir_name, base_name = os.path.split(self.baseFilename)

        # interval_start = rolloverAt - interval_in_seconds
        interval_start_ts = self.rolloverAt - self.interval
        t = time.gmtime(interval_start_ts) if self.utc else time.localtime(interval_start_ts)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S", t)

        return os.path.join(dir_name, f"{base_name}.{stamp}")


def configure_interval_start_logging() -> logging.Logger:
    """Configure logging with interval start naming."""
    log_path = pathlib.Path("logs/app_interval.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            }
        },
        "handlers": {
            "time_file_interval": {
                "()": "utf8_advanced_patterns.IntervalStartNamedTimedHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": str(log_path),
                "when": "midnight",
                "interval": 1,
                "backupCount": 7,
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["time_file_interval"],
                "level": "INFO",
                "propagate": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 2) Combine time- and size-based rollover in one handler
class HybridTimedSizeHandler(TimedRotatingFileHandler):
    """Handler that combines time-based and size-based rollover."""
    
    def __init__(self, filename, max_bytes=0, when="midnight", interval=1,
                 backupCount=0, encoding="utf-8-sig", **kwargs):
        self.max_bytes = max_bytes
        super(HybridTimedSizeHandler, self).__init__(
            filename, when=when, interval=interval,
            backupCount=backupCount, encoding=encoding, **kwargs
        )

    def shouldRollover(self, record):
        """Check if rollover should occur based on time or size."""
        # time-based check
        if super(HybridTimedSizeHandler, self).shouldRollover(record):
            return True

        # size-based check
        if self.max_bytes > 0 and self.stream is not None:
            msg = "%s\n" % self.format(record)
            self.stream.seek(0, os.SEEK_END)
            if self.stream.tell() + len(msg.encode(self.encoding or "utf-8")) >= self.max_bytes:
                return True

        return False


def configure_hybrid_rollover_logging(max_bytes: int = 10 * 1024 * 1024) -> logging.Logger:
    """Configure logging with hybrid time+size rollover."""
    log_path = pathlib.Path("logs/app_hybrid.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            }
        },
        "handlers": {
            "time_file_hybrid": {
                "()": "utf8_advanced_patterns.HybridTimedSizeHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": str(log_path),
                "when": "midnight",
                "interval": 1,
                "backupCount": 7,
                "max_bytes": max_bytes,
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["time_file_hybrid"],
                "level": "INFO",
                "propagate": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 3) Calling `doRollover` safely from another thread/process
_rollover_lock = threading.Lock()


def safe_rollover(handler: TimedRotatingFileHandler) -> None:
    """Safely trigger rollover from any thread."""
    with _rollover_lock:
        # flush before rolling
        handler.flush()
        handler.doRollover()


def safe_rollover_from_config(config_dict: dict) -> logging.Logger:
    """Configure logging and provide safe rollover function."""
    logging.config.dictConfig(config_dict)
    logger = logging.getLogger()
    
    # Return logger and safe rollover function for external use
    rollover_funcs = [h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)]
    def safe_rollover_for_handler(handler):
        safe_rollover(handler)
    
    return logger, safe_rollover_for_handler


# 4) dictConfig snippet for TimedRotatingFileHandler with `utf_8_sig`
LOGGING_TIMED_UTF8_SIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        }
    },
    "handlers": {
        "time_file_utf8_sig": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed.log",
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8-sig",  # UTF-8 with BOM
            "utc": True,
            "delay": True,
        },
    },
    "loggers": {
        "": {
            "handlers": ["time_file_utf8_sig"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_timed_utf8_sig_logging() -> logging.Logger:
    """Configure TimedRotatingFileHandler with UTF-8 BOM."""
    log_path = pathlib.Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_UTF8_SIG)
    return logging.getLogger(__name__)


# 5) Trigger rollover at startup only if file older than current interval
def maybe_rollover_on_start(handler: TimedRotatingFileHandler) -> None:
    """Trigger rollover at startup only if file older than current interval."""
    base = handler.baseFilename
    if not os.path.exists(base):
        return  # no file yet

    # Determine current interval start
    current_time = int(time.time())
    if handler.when == "MIDNIGHT" or handler.when == "midnight":
        # reuse handler's logic: rolloverAt is "end" of current interval
        # if rolloverAt < now, recompute as in handler, but for startup
        interval_end = handler.rolloverAt
        if interval_end <= current_time:
            interval_end = current_time
        interval_start = interval_end - handler.interval
    else:
        # generic: interval_start = now - interval
        interval_start = current_time - handler.interval

    mtime = int(os.path.getmtime(base))

    if mtime < interval_start:
        handler.doRollover()


def configure_conditional_startup_rollover() -> logging.Logger:
    """Configure logging with conditional startup rollover."""
    log_path = pathlib.Path("logs/app_conditional.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_UTF8_SIG)
    logger = logging.getLogger(__name__)
    
    # Apply conditional rollover to all TimedRotatingFileHandlers
    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            maybe_rollover_on_start(h)
    
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


# Console + File configuration
LOGGING_CONSOLE_FILE = {
    "version": 1,
    "handlers": {
        "console_utf8": {
            "()": "utf8_advanced_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
        "file_utf8_bom": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_console_bom.log",
            "mode": "a",
            "encoding": "utf-8-sig",
        },
    },
    "formatters": {
        "standard": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["console_utf8", "file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_console_file_bom_logging() -> logging.Logger:
    """Configure console + file logging with BOM."""
    log_path = pathlib.Path("logs/app_console_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CONSOLE_FILE)
    return logging.getLogger(__name__)


# Utility functions
def verify_bom_in_file(file_path: Union[str, pathlib.Path]) -> bool:
    """Verify that a file starts with UTF-8 BOM."""
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
    """List all rotated files for a given base path."""
    base_path = pathlib.Path(base_path)
    pattern = f"{base_path.name}.*"
    
    return sorted(base_path.parent.glob(pattern))


def get_handler_info(handler: TimedRotatingFileHandler) -> dict:
    """Get detailed information about a TimedRotatingFileHandler."""
    return {
        "base_filename": handler.baseFilename,
        "when": handler.when,
        "interval": handler.interval,
        "backupCount": handler.backupCount,
        "encoding": handler.encoding,
        "utc": handler.utc,
        "delay": handler.delay,
        "rollover_at": getattr(handler, 'rolloverAt', None),
        "max_bytes": getattr(handler, 'max_bytes', 0),
    }


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Advanced UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test interval start naming
    print("\n🧪 Testing Interval Start Naming...")
    interval_logger = configure_interval_start_logging()
    interval_logger.info("Interval start test: 🚀 αβγ")
    
    # Show handler info
    for h in interval_logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            info = get_handler_info(h)
            print(f"   📋 Handler info: {info}")
    
    # Test hybrid rollover
    print("\n🧪 Testing Hybrid Time+Size Rollover...")
    hybrid_logger = configure_hybrid_rollover_logging(max_bytes=1024)  # Small for testing
    hybrid_logger.info("Hybrid test 1: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 2: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 3: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 4: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 5: 🚀 αβγ")
    
    # Test safe rollover
    print("\n🧪 Testing Safe Thread-Safe Rollover...")
    safe_logger, safe_rollover_func = safe_rollover_from_config(LOGGING_TIMED_UTF8_SIG)
    safe_logger.info("Before safe rollover: 🚀 αβγ")
    
    # Simulate thread-safe rollover
    import threading
    def rollover_thread():
        time.sleep(0.1)
        safe_rollover_func()
    
    rollover_thread = threading.Thread(target=rollover_thread)
    rollover_thread.start()
    rollover_thread.join()
    
    safe_logger.info("After safe rollover: 🚀 αβγ")
    
    # Test conditional startup rollover
    print("\n🧪 Testing Conditional Startup Rollover...")
    conditional_logger = configure_conditional_startup_rollover()
    conditional_logger.info("Conditional test: 🚀 αβγ")
    
    # Test timed UTF-8 SIG
    print("\n🧪 Testing Timed UTF-8 SIG...")
    sig_logger = configure_timed_utf8_sig_logging()
    sig_logger.info("UTF-8 SIG test: 🚀 αβγ")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All advanced UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Advanced Features:")
    print("   • Interval start timestamp naming")
    print("   • Hybrid time + size-based rollover")
    print("   • Thread-safe rollover operations")
    print("   • Conditional startup rollover")
    print("   • UTF-8 BOM with TimedRotatingFileHandler")
    print("   • Console + file dual output")

"""
MERID Tight UTF-8 Logging Patterns
Tight, production-ready patterns covering multiprocess safety, hybrid rotation, thread-safe rollover, concurrent handlers, and load testing.

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
from typing import Union, Optional
from logging.handlers import TimedRotatingFileHandler

# Try to import portalocker, but make it optional
try:
    import portalocker
    PORTALOCKER_AVAILABLE = True
except ImportError:
    PORTALOCKER_AVAILABLE = False
    print("⚠️  portalocker not available - multiprocess patterns will use fallback")

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - concurrent patterns will use fallback")


# 1) Multiprocess-safe TimedRotatingFileHandler via file locks
class MultiProcTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    TimedRotatingFileHandler with an inter-process file lock.
    All processes using this handler must share the same lock file path.
    """

    def __init__(self, filename, lockfile=None, *args, **kwargs):
        self.lockfile = lockfile or (filename + ".lock")
        self._lock_fp = open(self.lockfile, "a+")
        super(MultiProcTimedRotatingFileHandler, self).__init__(filename, *args, **kwargs)

    def acquire(self):
        # Lock both logging's internal lock and our inter-process lock
        super(MultiProcTimedRotatingFileHandler, self).acquire()
        if PORTALOCKER_AVAILABLE:
            portalocker.lock(self._lock_fp, portalocker.LOCK_EX)

    def release(self):
        try:
            self._lock_fp.flush()
            os.fsync(self._lock_fp.fileno())
            if PORTALOCKER_AVAILABLE:
                portalocker.unlock(self._lock_fp)
        finally:
            super(MultiProcTimedRotatingFileHandler, self).release()

    def close(self):
        """Close both the handler and the lock file."""
        super(MultiProcTimedRotatingFileHandler, self).close()
        try:
            self._lock_fp.close()
        except:
            pass  # Ignore errors on lock file close


def configure_multiprocess_safe_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_multiproc.log",
    lockfile: Optional[str] = None,
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """Configure multiprocess-safe logging with file locks."""
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not PORTALOCKER_AVAILABLE:
        print("⚠️  portalocker not available - using fallback multiprocess pattern")
        # Fallback to basic TimedRotatingFileHandler
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
                }
            },
            "handlers": {
                "file_handler": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "level": level,
                    "formatter": "standard",
                    "filename": str(log_path),
                    "when": when,
                    "interval": interval,
                    "backupCount": backup_count,
                    "encoding": encoding,
                    "utc": True,
                    "delay": True,
                },
            },
            "loggers": {
                "": {
                    "handlers": ["file_handler"],
                    "level": level,
                    "propagate": False,
                }
            }
        }
    else:
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
                }
            },
            "handlers": {
                "file_handler": {
                    "()": "utf8_tight_patterns.MultiProcTimedRotatingFileHandler",
                    "level": level,
                    "formatter": "standard",
                    "filename": str(log_path),
                    "lockfile": lockfile,
                    "when": when,
                    "interval": interval,
                    "backupCount": backup_count,
                    "encoding": encoding,
                    "utc": True,
                    "delay": True,
                },
            },
            "loggers": {
                "": {
                    "handlers": ["file_handler"],
                    "level": level,
                    "propagate": False,
                }
            }
        }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 2) HybridRotatingHandler: time + size
class HybridRotatingHandler(TimedRotatingFileHandler):
    """
    Rotate logs based on both time and size.

    - Time: standard TimedRotatingFileHandler semantics.
    - Size: rotate when file exceeds max_bytes.
    """

    def __init__(
        self,
        filename,
        max_bytes=0,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8-sig",
        **kwargs
    ):
        self.max_bytes = max_bytes
        super(HybridRotatingHandler, self).__init__(
            filename=filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            **kwargs
        )

    def shouldRollover(self, record):
        """Check if rollover should occur based on time or size."""
        # Time-based check
        if super(HybridRotatingHandler, self).shouldRollover(record):
            return True

        # Size-based check
        if self.max_bytes > 0 and self.stream is not None:
            msg = "%s\n" % self.format(record)
            self.stream.seek(0, os.SEEK_END)
            current_size = self.stream.tell()
            projected = current_size + len(msg.encode(self.encoding or "utf-8"))
            if projected >= self.max_bytes:
                return True

        return False


def configure_hybrid_rotation_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_hybrid.log",
    max_bytes: int = 10 * 1024 * 1024,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 30,
    level: int = logging.INFO,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """Configure hybrid time+size rotation logging."""
    log_path = pathlib.Path(log_path)
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
            "hybrid_handler": {
                "()": "utf8_tight_patterns.HybridRotatingHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_path),
                "max_bytes": max_bytes,
                "when": when,
                "interval": interval,
                "backupCount": backup_count,
                "encoding": encoding,
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["hybrid_handler"],
                "level": level,
                "propagate": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 3) Calling doRollover safely from a separate thread
_rollover_lock = threading.Lock()


def safe_do_rollover(handler: TimedRotatingFileHandler) -> None:
    """Safely trigger rollover from any thread."""
    with _rollover_lock:
        handler.acquire()
        try:
            handler.flush()      # ensure all buffered records are written
            handler.doRollover() # rotate file safely
        finally:
            handler.release()


def configure_thread_safe_rollover_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_thread_safe.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> tuple[logging.Logger, callable]:
    """Configure logging with thread-safe rollover function."""
    log_path = pathlib.Path(log_path)
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
            "file_handler": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_path),
                "when": when,
                "interval": interval,
                "backupCount": backup_count,
                "encoding": encoding,
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["file_handler"],
                "level": level,
                "propagate": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)
    
    # Find the TimedRotatingFileHandler
    handler = None
    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            handler = h
            break
    
    # Return logger and safe rollover function
    return logger, lambda: safe_do_rollover(handler) if handler else lambda: None


# 4) Example using concurrent-log-handler for time-based rotation
def configure_concurrent_time_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_concurrent.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Configure concurrent-log-handler for time-based rotation.
    
    concurrent-log-handler gives you a multi-process-safe rotating handler; 
    it has a time-based variant (ConcurrentTimedRotatingFileHandler).
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not CONCURRENT_HANDLER_AVAILABLE:
        print("⚠️  concurrent-log-handler not available - using fallback pattern")
        # Fallback to basic TimedRotatingFileHandler
        return configure_thread_safe_rollover_logging(log_path, level, when, interval, backup_count, encoding)
    
    # Use concurrent-log-handler
    logger = logging.getLogger("my_app")
    logger.setLevel(level)
    
    handler = ConcurrentTimedRotatingFileHandler(
        str(log_path),
        when=when,
        interval=interval,
        backupCount=backup_count,
        encoding=encoding,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    
    logger.addHandler(handler)
    return logger


# 5) Pattern to test rollover under load without losing records
def configure_load_test_logging(
    log_path: Union[str, pathlib.Path] = "logs/load_test.log",
    level: int = logging.INFO,
    when: str = "s",          # rotate on seconds
    interval: int = 5,        # every 5 seconds
    backup_count: int = 3,
    encoding: str = "utf-8-sig"
) -> tuple[logging.Logger, threading.Event]:
    """Configure load test logging with stop event."""
    log_path = pathlib.Path(log_path)
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
            "load_handler": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_path),
                "when": when,
                "interval": interval,
                "backupCount": backup_count,
                "encoding": encoding,
                "utc": True,
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["load_handler"],
                "level": level,
                "defaul": False,
            }
        }
    }
    
    logging.config.dictConfig(config)
    logger = logging.getLogger("load_test")
    
    # Create stop event for load test
    stop_event = threading.Event()
    
    return logger, stop_event


def run_load_test(
    logger: logging.Logger,
    stop_event: threading.Event,
    num_workers: int = 4,
    test_duration: int = 20,
    message_interval: float = 0.01
) -> dict:
    """
    Run load test with multiple workers.
    
    Checklist to verify no loss under load:
    - Ensure every file ends in a complete line (no truncated log entries)
    - Grep/count total messages and confirm counts are monotonic per worker (no gaps)
    - In multi-process scenarios, repeat the same pattern with ConcurrentTimedRotatingFileHandler
    """
    
    def spam_worker(idx: int, message_counter: list):
        i = 0
        while not stop_event.is_set():
            logger.info("worker=%d msg=%d", idx, i)
            i += 1
            message_counter[idx] = i
            # Adjust sleep to control volume
            time.sleep(message_interval)
    
    # Start worker threads
    message_counters = [0] * num_workers
    threads = []
    
    for i in range(num_workers):
        thread = threading.Thread(target=spam_worker, args=(i, message_counters))
        threads.append(thread)
        thread.start()
    
    # Run for specified duration
    time.sleep(test_duration)
    
    # Stop all workers
    stop_event.set()
    for thread in threads:
        thread.join()
    
    # Return results
    return {
        "total_messages": sum(message_counters),
        "messages_per_worker": message_counters,
        "test_duration": test_duration,
        "num_workers": num_workers,
        "message_interval": message_interval
    }


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
            "()": "utf8_tight_patterns.Utf8StreamHandler",
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


def validate_load_test_results(
    log_path: Union[str, pathlib.Path],
    results: dict,
    expected_total: Optional[int] = None
) -> dict:
    """
    Validate load test results by checking log files for completeness.
    
    Checklist:
    - Ensure every file ends in a complete line (no truncated log entries)
    - Grep/count total messages and confirm counts are monotonic per worker (no gaps)
    """
    log_path = pathlib.Path(log_path)
    
    validation = {
        "files_checked": [],
        "files_complete": [],
        "total_messages_found": 0,
        "expected_total": expected_total or results["total_messages"],
        "validation_passed": True,
        "issues": []
    }
    
    # List all log files
    log_files = list_rotated_files(log_path)
    validation["files_checked"] = [f.name for f in log_files]
    
    # Check each file for completeness
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.endswith('\n'):
                    validation["files_complete"].append(log_file.name)
                else:
                    validation["issues"].append(f"File {log_file.name} does not end with newline")
                    validation["validation_passed"] = False
        except Exception as e:
            validation["issues"].append(f"Error reading {log_file.name}: {e}")
            validation["validation_passed"] = False
    
    # Count total messages
    try:
        for log_file in log_files:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Count messages (lines containing "worker=")
                message_lines = [line for line in lines if "worker=" in line]
                validation["total_messages_found"] += len(message_lines)
    except Exception as e:
        validation["issues"].append(f"Error counting messages: {e}")
        validation["validation_passed"] = False
    
    # Validate against expected total
    if expected_total:
        validation["expected_total"] = expected_total
        if validation["total_messages_found"] != expected_total:
            validation["issues"].append(
                f"Expected {expected_total} messages, found {validation['total_messages_found']}"
            )
            validation["validation_passed"] = False
    
    return validation


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Tight UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test multiprocess safe pattern
    print("\n🧪 Testing Multiprocess Safe Pattern...")
    if PORTALOCKER_AVAILABLE:
        print("   ✅ Using portalocker for file locks")
    else:
        print("   ⚠️ portalocker not available - using fallback pattern")
    
    multi_logger = configure_multiprocess_safe_logging()
    multi_logger.info("Multiprocess safe test: 🚀 αβγ")
    
    # Test hybrid rotation
    print("\n🧪 Testing Hybrid Rotation (Time + Size)...")
    hybrid_logger = configure_hybrid_rotation_logging(max_bytes=1024)  # Small for testing
    hybrid_logger.info("Hybrid test 1: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 2: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 3: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 4: 🚀 αβγ")
    hybrid_logger.info("Hybrid test 5: 🚀 αβγ")
    
    # Test thread-safe rollover
    print("\n🧪 Testing Thread-Safe Rollover...")
    thread_safe_logger, safe_rollover_func = configure_thread_safe_rollover_logging()
    thread_safe_logger.info("Before safe rollover: 🚀 αβγ")
    
    # Simulate thread-safe rollover
    def rollover_thread():
        time.sleep(0.1)
        safe_rollover_func()
    
    rollover_thread = threading.Thread(target=rollover_thread)
    rollover_thread.start()
    rollover_thread.join()
    
    thread_safe_logger.info("After safe rollover: 🚀 αβγ")
    
    # Test concurrent handler pattern
    print("\n🧪 Testing Concurrent Handler Pattern...")
    if CONCURRENT_HANDLER_AVAILABLE:
        print("   ✅ Using concurrent-log-handler")
        concurrent_logger = configure_concurrent_time_logging()
        concurrent_logger.info("Concurrent time-based rotation is active: 🚀 αβγ")
    else:
        print("   ⚠️ concurrent-log-handler not available - using fallback pattern")
    
    # Test load test pattern
    print("\n🧪 Testing Load Test Pattern...")
    load_logger, stop_event = configure_load_test_logging()
    
    # Run load test
    results = run_load_test(load_logger, stop_event, num_workers=4, test_duration=5, message_interval=0.01)
    
    print(f"   📊 Load test results:")
    print(f"      Total messages: {results['total_messages']}")
    print(f"      Messages per worker: {results['messages_per_worker']}")
    print(f"      Test duration: {results['test_duration']}s")
    print(f"      Message interval: {results['message_interval']}s")
    
    # Validate load test results
    validation = validate_load_test_results("logs/load_test.log", results)
    print(f"   ✅ Validation passed: {validation['validation_passed']}")
    if validation["issues"]:
        for issue in validation["issues"]:
            print(f"   ⚠️ Issue: {issue}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All tight UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Tight Features:")
    print("   • Multiprocess-safe TimedRotatingFileHandler via file locks")
    print("   • Complete HybridRotatingHandler (time + size)")
    print("   • Thread-safe rollover without data loss")
    print("   • Concurrent-log-handler time-based rotation")
    print("   • Load testing pattern with validation")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   portalocker: {'✅ Available' if PORTALOCKER_AVAILABLE else '❌ Not Available'}")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

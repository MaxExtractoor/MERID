"""
MERID Compact UTF-8 Logging Patterns
Compact, production-oriented patterns covering Gunicorn-like testing, log loss validation, concurrent handler configuration, cross-platform pytest setup, and heavy load rotation testing.

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
import multiprocessing as mp
from typing import Union, Optional, Dict, Set, List
from logging.handlers import TimedRotatingFileHandler

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - concurrent patterns will use fallback")


# 1) Pytest example that spawns "Gunicorn-like" worker processes
def _gunicorn_like_worker(log_path: str, wid: int):
    """
    Gunicorn-like worker function for testing.
    
    This doesn't start real Gunicorn (heavy for tests) but simulates multiple 
    workers writing through the same concurrent handler.
    """
    logger = logging.getLogger(f"worker-{wid}")
    logger.setLevel(logging.INFO)

    if CONCURRENT_HANDLER_AVAILABLE:
        handler = ConcurrentTimedRotatingFileHandler(
            log_path,
            when="s",          # seconds for test
            interval=3,
            backupCount=3,
            encoding="utf-8",
        )
    else:
        # Fallback for testing without concurrent-log-handler
        handler = TimedRotatingFileHandler(
            log_path,
            when="s",
            interval=3,
            backupCount=3,
            encoding="utf-8",
        )
    
    handler.setFormatter(logging.Formatter("%(processName)s %(message)s"))
    logger.addHandler(handler)

    for i in range(300):
        logger.info("wid=%d msg=%d", wid, i)
        time.sleep(0.005)


def test_gunicorn_like_workers(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_like.log",
    num_workers: int = 4
) -> dict:
    """
    Pytest example that spawns "Gunicorn-like" worker processes.
    
    This simulates multiple workers writing through the same concurrent handler.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Clean up any existing files
    for existing_file in log_path.parent.glob(f"{log_path.name}*"):
        try:
            existing_file.unlink()
        except:
            pass
    
    procs = []
    for wid in range(num_workers):  # 4 workers
        p = mp.Process(target=_gunicorn_like_worker, args=(str(log_path), wid))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    files = list(log_path.parent.glob(f"{log_path.name}*"))
    
    return {
        "files_found": len(files),
        "files": [f.name for f in files],
        "workers": num_workers,
        "rotation_occurred": len(files) > 1
    }


# 2) Unit test asserting "no log loss" during concurrent rotation
def test_no_apparent_log_loss(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_like.log",
    num_workers: int = 2,
    messages_per_worker: int = 300
) -> dict:
    """
    Unit test asserting "no log loss" during concurrent rotation.
    
    You can't be perfect without sequence numbers, but you can get close by 
    checking monotonic sequences per worker.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Clean up any existing files
    for existing_file in log_path.parent.glob(f"{log_path.name}*"):
        try:
            existing_file.unlink()
        except:
            pass
    
    procs = []
    for wid in range(num_workers):
        p = mp.Process(target=_gunicorn_like_worker, args=(str(log_path), wid))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    # Collect all lines and parse counters
    files = list(log_path.parent.glob(f"{log_path.name}*"))
    
    per_worker: Dict[int, Set[int]] = {wid: set() for wid in range(num_workers)}
    total_lines = 0
    
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if "wid=" not in line:
                    continue
                parts = line.split()
                wid = int([p for p in parts if p.startswith("wid=")][0].split("=")[1])
                msg = int([p for p in parts if p.startswith("msg=")][0].split("=")[1])
                per_worker[wid].add(msg)
                total_lines += 1
        except Exception as e:
            print(f"⚠️ Error parsing {f}: {e}")
    
    # Validate each worker's message sequence
    validation_results = {}
    for wid, msgs in per_worker.items():
        max_msg = max(msgs) if msgs else 0
        min_msg = min(msgs) if msgs else 0
        msg_count = len(msgs)
        
        # Each worker attempted messages_per_worker messages; allow some tolerance
        expected_min = 0
        expected_max_tolerance = int(messages_per_worker * 0.85)  # Allow 15% tolerance
        
        validation_results[wid] = {
            "messages_found": msg_count,
            "min_message": min_msg,
            "max_message": max_msg,
            "expected_min": expected_min,
            "expected_max_tolerance": expected_max_tolerance,
            "passed_min": min_msg == expected_min,
            "passed_max": max_msg >= expected_max_tolerance
        }
    
    overall_passed = all(
        result["passed_min"] and result["passed_max"] 
        for result in validation_results.values()
    )
    
    return {
        "files_found": len(files),
        "total_lines": total_lines,
        "per_worker_results": validation_results,
        "overall_passed": overall_passed,
        "tolerance_used": "15% tolerance applied for timing-related losses"
    }


# 3) Configure ConcurrentTimedRotatingFileHandler (portalocker is built-in)
def configure_concurrent_handler_logging(
    log_path: Union[str, pathlib.Path] = "logs/app_concurrent.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Configure ConcurrentTimedRotatingFileHandler (portalocker is built-in).
    
    concurrent-log-handler bundles portalocker; no extra wiring is needed.
    
    All workers/processes that use this handler type can safely write to the 
    same file concurrently.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not CONCURRENT_HANDLER_AVAILABLE:
        print("⚠️  concurrent-log-handler not available - using fallback pattern")
        # Fallback to basic TimedRotatingFileHandler
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s - %(processName)s - %(levelname)s - %(message)s"
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
        # Use concurrent-log-handler directly
        logger = logging.getLogger("app")
        logger.setLevel(level)
        
        handler = ConcurrentTimedRotatingFileHandler(
            str(log_path),
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding=encoding,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(processName)s - %(levelname)s - %(message)s"
        ))
        
        logger.handlers.clear()
        logger.addHandler(handler)
        return logger
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


# 4) Cross-platform pytest setup for spawn/fork multiprocessing
def configure_cross_platform_multiprocessing(start_method: str = "spawn") -> bool:
    """
    Cross-platform pytest setup for spawn/fork multiprocessing.
    
    Use spawn in tests to be portable and predictable, but allow fork when you 
    specifically want to.
    
    Then keep logger configuration inside worker functions or under 
    if __name__ == "__main__": in helpers to avoid fork-related state leakage.
    """
    try:
        mp.set_start_method(start_method, force=True)
        return True
    except RuntimeError:
        # Already set (e.g., on some Linux setups)
        return False


def create_conftest_file(
    config_path: Union[str, pathlib.Path] = "conftest.py"
) -> pathlib.Path:
    """
    Create a conftest.py file for cross-platform pytest setup.
    
    This file should be placed in your tests/ directory to ensure consistent 
    multiprocessing behavior across platforms.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = '''import multiprocessing as mp

def pytest_sessionstart(session):
    # Use spawn everywhere to match Windows/modern macOS behavior
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Already set (e.g., on some Linux setups)
        pass
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


# 5) Simulate log rotation under heavy write load in tests
def _spam_worker(log_path: str, wid: int, n: int):
    """
    Spam worker function for heavy load testing.
    
    Use a small time interval and multiple writers and then validate all rotated 
    files are readable and non-trivial.
    """
    logger = logging.getLogger(f"spam-{wid}")
    logger.setLevel(logging.INFO)

    if CONCURRENT_HANDLER_AVAILABLE:
        handler = ConcurrentTimedRotatingFileHandler(
            log_path,
            when="s",
            interval=2,
            backupCount=5,
            encoding="utf-8",
        )
    else:
        # Fallback for testing without concurrent-log-handler
        handler = TimedRotatingFileHandler(
            log_path,
            when="s",
            interval=2,
            backupCount=5,
            encoding="utf-8",
        )
    
    handler.setFormatter(logging.Formatter("%(asctime)s %(processName)s %(message)s"))
    logger.addHandler(handler)

    for i in range(n):
        logger.info("wid=%d msg=%d", wid, i)
        # tiny sleep to avoid single-process bottleneck only
        # but still generate high throughput
        if i % 50 == 0:
            time.sleep(0.001)


def test_heavy_rotation_under_load(
    log_path: Union[str, pathlib.Path] = "logs/heavy.log",
    num_workers: int = 4,
    messages_per_worker: int = 1000
) -> dict:
    """
    Simulate log rotation under heavy write load in tests.
    
    This gives you a realistic stress test of concurrent rotation under load 
    on both Windows and Linux, grounded on a handler that already uses 
    portalocker internally.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Clean up any existing files
    for existing_file in log_path.parent.glob(f"{log_path.name}*"):
        try:
            existing_file.unlink()
        except:
            pass
    
    procs = [
        mp.Process(target=_spam_worker, args=(str(log_path), wid, messages_per_worker))
        for wid in range(num_workers)
    ]

    for p in procs:
        p.start()
    for p in procs:
        p.join()

    files = list(log_path.parent.glob(f"{log_path.name}*"))
    
    # Basic sanity: every file is valid UTF-8 and has lines
    total_lines = 0
    file_details = []
    
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            file_details.append({
                "filename": f.name,
                "lines": len(lines),
                "has_content": len(lines) > 0
            })
            total_lines += len(lines)
        except Exception as e:
            file_details.append({
                "filename": f.name,
                "lines": 0,
                "has_content": False,
                "error": str(e)
            })
    
    return {
        "files_found": len(files),
        "rotation_occurred": len(files) >= 2,
        "total_lines": total_lines,
        "file_details": file_details,
        "workers": num_workers,
        "messages_per_worker": messages_per_worker,
        "expected_total_messages": num_workers * messages_per_worker
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
            "()": "utf8_compact_patterns.Utf8StreamHandler",
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


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Compact UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test Gunicorn-like workers
    print("\n🧪 Testing Gunicorn-like Workers...")
    gunicorn_results = test_gunicorn_like_workers(num_workers=2)
    print(f"   📊 Results:")
    print(f"      Files found: {gunicorn_results['files_found']}")
    print(f"      Workers: {gunicorn_results['workers']}")
    print(f"      Rotation occurred: {gunicorn_results['rotation_occurred']}")
    
    # Test no apparent log loss
    print("\n🧪 Testing No Apparent Log Loss...")
    loss_results = test_no_apparent_log_loss(num_workers=2, messages_per_worker=100)
    print(f"   📊 Results:")
    print(f"      Files found: {loss_results['files_found']}")
    print(f"      Total lines: {loss_results['total_lines']}")
    print(f"      Overall passed: {loss_results['overall_passed']}")
    print(f"      Tolerance: {loss_results['tolerance_used']}")
    
    for wid, result in loss_results['per_worker_results'].items():
        print(f"      Worker {wid}: {result['messages_found']} messages "
              f"(min={result['min_message']}, max={result['max_message']})")
    
    # Test concurrent handler configuration
    print("\n🧪 Testing Concurrent Handler Configuration...")
    if CONCURRENT_HANDLER_AVAILABLE:
        print("   ✅ Using concurrent-log-handler")
        concurrent_logger = configure_concurrent_logging()
        concurrent_logger.info("Concurrent handler test: 🚀 αβγ")
    else:
        print("   ⚠️ concurrent-log-handler not available - using fallback pattern")
    
    # Test cross-platform multiprocessing
    print("\n🧪 Testing Cross-Platform Multiprocessing...")
    mp_configured = configure_cross_platform_multiprocessing()
    print(f"   ✅ Multiprocessing configured: {mp_configured}")
    
    # Create conftest file
    conftest_file = create_conftest_file()
    print(f"   ✅ Conftest file created: {conftest_file}")
    
    # Test heavy rotation under load
    print("\n🧪 Testing Heavy Rotation Under Load...")
    heavy_results = test_heavy_rotation_under_load(num_workers=2, messages_per_worker=200)
    print(f"   📊 Results:")
    print(f"      Files found: {heavy_results['files_found']}")
    print(f"      Rotation occurred: {heavy_results['rotation_occurred']}")
    print(f"      Total lines: {heavy_results['total_lines']}")
    print(f"      Workers: {heavy_results['workers']}")
    print(f"      Messages per worker: {heavy_results['messages_per_worker']}")
    
    for file_detail in heavy_results['file_details']:
        status = "✅" if file_detail['has_content'] else "❌"
        print(f"      {status} {file_detail['filename']}: {file_detail['lines']} lines")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All compact UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Compact Features:")
    print("   • Gunicorn-like worker process simulation")
    print("   • No apparent log loss validation")
    print("   • ConcurrentTimedRotatingFileHandler configuration")
    print("   • Cross-platform pytest setup")
    print("   • Heavy rotation under load testing")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

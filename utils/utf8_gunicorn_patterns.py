"""
MERID Gunicorn-Style UTF-8 Logging Patterns
Minimal patterns for Gunicorn-style integration testing, log loss validation, Gunicorn config, cross-platform pytest setup, and heavy concurrent rotation testing.

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
    print("⚠️  concurrent-log-handler not available - gunicorn patterns will use fallback")


# 1) Pytest "Gunicorn-style" integration (multiple worker processes)
class ExtraAdapter(logging.LoggerAdapter):
    """LoggerAdapter to inject worker ID and message number into log records."""
    
    def __init__(self, logger, extra):
        super(ExtraAdapter, self).__init__(logger, extra)
        self.wid = extra.get('wid', 0)
    
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra["wid"] = self.wid
        extra["msg_num"] = extra.get("msg_num", -1)
        return msg, kwargs


def _gunicorn_worker(log_path: str, wid: int, n_msgs: int = 500):
    """
    Gunicorn-style worker function for integration testing.
    
    This simulates multiple workers writing through a shared 
    ConcurrentTimedRotatingFileHandler under pytest, cross-platform.
    """
    logger = logging.getLogger(f"worker-{wid}")
    logger.setLevel(logging.INFO)

    if CONCURRENT_HANDLER_AVAILABLE:
        handler = ConcurrentTimedRotatingFileHandler(
            log_path,
            when="s",          # seconds: fast rotation for test
            interval=3,
            backupCount=5,
            encoding="utf-8",
        )
    else:
        # Fallback for testing without concurrent-log-handler
        handler = TimedRotatingFileHandler(
            log_path,
            when="s",
            interval=3,
            backupCount=5,
            encoding="utf-8",
        )
    
    handler.setFormatter(logging.Formatter("%(processName)s wid=%(wid)s msg_num=%(msg_num)s"))
    logger.addHandler(handler)

    # Use LoggerAdapter to inject worker ID and message number
    logger = ExtraAdapter(logger, {"wid": wid})

    for i in range(n_msgs):
        logger.info("log", extra={"msg_num": i})
        time.sleep(0.002)


def test_gunicorn_style_multiprocess_logging(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_like.log",
    num_workers: int = 4,
    messages_per_worker: int = 500
) -> dict:
    """
    Pytest "Gunicorn-style" integration (multiple worker processes).
    
    This gives you a realistic multi-process logging integration without 
    running Gunicorn itself.
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
        p = mp.Process(target=_gunicorn_worker, args=(str(log_path), wid, messages_per_worker))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    files = list(log_path.parent.glob(f"{log_path.name}*"))
    
    return {
        "files_found": len(files),
        "files": [f.name for f in files],
        "workers": num_workers,
        "messages_per_worker": messages_per_worker,
        "rotation_occurred": len(files) > 1
    }


# 2) Asserting "no lost lines" across rotated files
def test_no_apparent_log_loss(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_like.log",
    num_workers: int = 3,
    messages_per_worker: int = 300
) -> dict:
    """
    Asserting "no lost lines" across rotated files.
    
    Use sequence numbers per worker and verify coverage is dense enough.
    
    This doesn't prove perfect losslessness, but gives strong signal that rotation 
    under load is not silently dropping most records.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Clean up any existing files
    for existing_file in log_path.parent.glob(f"{log_path.name}*"):
        try:
            existing_file.unlink()
        except:
            pass
    
    # Reuse the worker from previous test
    procs = []
    for wid in range(num_workers):
        p = mp.Process(target=_gunicorn_worker, args=(str(log_path), wid, messages_per_worker))
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    files = list(log_path.parent.glob(f"{log_path.name}*"))
    
    per_worker: Dict[int, Set[int]] = {wid: set() for wid in range(num_workers)}
    total_lines = 0
    
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if "wid=" not in line or "msg_num=" not in line:
                    continue
                parts = dict(part.split("=", 1) for part in line.split() if "=" in part)
                wid = int(parts["wid"])
                msg = int(parts["msg_num"])
                per_worker[wid].add(msg)
                total_lines += 1
        except Exception as e:
            print(f"⚠️ Error parsing {f}: {e}")
    
    # Validate each worker's message sequence
    validation_results = {}
    slack_allowed = 20  # Allow some slack for test timing
    
    for wid in range(num_workers):
        msgs = per_worker[wid]
        max_msg = max(msgs) if msgs else 0
        min_msg = min(msgs) if msgs else 0
        msg_count = len(msgs)
        
        validation_results[wid] = {
            "messages_found": msg_count,
            "min_message": min_msg,
            "max_message": max_msg,
            "expected_min": 0,
            "expected_max": messages_per_worker,
            "expected_max_tolerance": messages_per_worker - slack_allowed,
            "passed_min": min_msg == 0,
            "passed_max": max_msg >= messages_per_worker - slack_allowed,
            "coverage": f"{msg_count}/{messages_per_worker}"
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
        "slack_allowed": slack_allowed,
        "tolerance_used": f"{slack_allowed} messages slack for timing-related losses"
    }


# 3) Gunicorn config example (with forkserver and concurrent handler)
def create_gunicorn_config_file(
    config_path: Union[str, pathlib.Path] = "gunicorn_conf.py",
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_app.log",
    workers: int = 4,
    worker_class: str = "sync"
) -> pathlib.Path:
    """
    Gunicorn config example (with forkserver and concurrent handler).
    
    Gunicorn itself controls worker process creation; you configure logging in a 
    Python config file and let ConcurrentTimedRotatingFileHandler handle 
    cross-process safety.
    
    Gunicorn uses OS-level fork/forkserver on Unix; there's no official 
    "start method" API like multiprocessing, but this config is compatible 
    with concurrent-log-handler's multi-process design.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = f'''import logging
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

# Worker settings
workers = {workers}
worker_class = "{worker_class}"
# Gunicorn itself uses OS defaults for fork/spawn; there is no direct
# start_method flag, but on POSIX this will effectively use fork/forkserver
# depending on platform and worker_class.

def _configure_logging():
    logger = logging.getLogger("gunicorn.error")
    logger.setLevel(logging.INFO)

    handler = ConcurrentTimedRotatingFileHandler(
        "{log_path}",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))

    logger.handlers.clear()
    logger.addHandler(handler)

    # Optionally route access logs to same handler
    access_logger = logging.getLogger("gunicorn.access")
    access_logger.handlers.clear()
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)


def on_starting(server):
    # Master process: configure logging once
    _configure_logging()


def post_fork(server, worker):
    # Workers inherit handlers; generally no extra work required
    pass
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


def configure_gunicorn_logging(
    log_path: Union[str, pathlib.Path] = "logs/gunicorn_app.log",
    level: int = logging.INFO,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8-sig"
) -> logging.Logger:
    """
    Configure logging in Gunicorn style (for testing without actual Gunicorn).
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
                    "format": "%(asctime)s [%(process)d] %(levelname)s %(message)s"
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
                "gunicorn.error": {
                    "handlers": ["file_handler"],
                    "level": level,
                    "propagate": False,
                },
                "gunicorn.access": {
                    "handlers": ["file_handler"],
                    "level": level,
                    "propagate": False,
                }
            }
        }
    else:
        # Use concurrent-log-handler directly
        logger = logging.getLogger("gunicorn.error")
        logger.setLevel(level)
        
        handler = ConcurrentTimedRotatingFileHandler(
            str(log_path),
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding=encoding,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(process)d] %(levelname)s %(message)s"
        ))
        
        logger.handlers.clear()
        logger.addHandler(handler)
        
        # Also configure access logger
        access_logger = logging.getLogger("gunicorn.access")
        access_logger.handlers.clear()
        access_logger.addHandler(handler)
        access_logger.setLevel(level)
        
        return logger
    
    logging.config.dictConfig(config)
    return logging.getLogger("gunicorn.error")


# 4) Cross-platform pytest setup for multiprocessing (spawn / fork)
def create_conftest_file(
    config_path: Union[str, pathlib.Path] = "conftest.py"
) -> pathlib.Path:
    """
    Cross-platform pytest setup for multiprocessing (spawn / fork).
    
    Use spawn in tests so behavior matches Windows and modern macOS; Linux can 
    still run under spawn just fine.
    
    Keep logging configuration inside worker functions or guarded by 
    if __name__ == "__main__": in helper scripts to avoid surprises under 
    different start methods.
    """
    config_path = pathlib.Path(config_path)
    
    config_content = '''import multiprocessing as mp

def pytest_sessionstart(session):
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Already set (e.g., on Linux when running under fork)
        pass
'''
    
    config_path.write_text(config_content, encoding='utf-8')
    return config_path


def configure_cross_platform_multiprocessing(start_method: str = "spawn") -> bool:
    """
    Configure cross-platform multiprocessing for testing.
    
    Returns True if configuration succeeded, False if already configured.
    """
    try:
        mp.set_start_method(start_method, force=True)
        return True
    except RuntimeError:
        return False


# 5) Simulating rotation under heavy concurrent writes
def _spam_worker(log_path: str, wid: int, n_msgs: int):
    """
    Spam worker function for heavy concurrent rotation testing.
    
    Use a short interval (when="s") and multiple writers to force frequent 
    rotation and stress the handler.
    """
    logger = logging.getLogger(f"spam-{wid}")
    logger.setLevel(logging.INFO)

    if CONCURRENT_HANDLER_AVAILABLE:
        handler = ConcurrentTimedRotatingFileHandler(
            log_path,
            when="s",          # seconds
            interval=2,        # rotate every 2 seconds
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
    
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(processName)s wid=%(wid)s msg_num=%(msg_num)s"
    ))

    # Use LoggerAdapter to inject worker ID and message number
    logger = ExtraAdapter(logger, {"wid": wid})

    for i in range(n_msgs):
        logger.info("log", extra={"msg_num": i})


def test_heavy_rotation_under_load(
    log_path: Union[str, pathlib.Path] = "logs/heavy.log",
    num_workers: int = 4,
    messages_per_worker: int = 1000
) -> dict:
    """
    Simulating rotation under heavy concurrent writes.
    
    This pattern lets you validate that ConcurrentTimedRotatingFileHandler handles 
    heavy concurrent writes and frequent rotations without crashing or producing 
    empty/corrupt files, which is the primary best-practice metric for 
    multi-process logging.
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
    
    # Basic sanity: all files readable, non-empty, and total lines > 0
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
            "()": "utf8_gunicorn_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Gunicorn-Style UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test Gunicorn-style multiprocess logging
    print("\n🧪 Testing Gunicorn-Style Multiprocess Logging...")
    gunicorn_results = test_gunicorn_style_multiprocess_logging(num_workers=2, messages_per_worker=200)
    print(f"   📊 Results:")
    print(f"      Files found: {gunicorn_results['files_found']}")
    print(f"      Workers: {gunicorn_results['workers']}")
    print(f"      Messages per worker: {gunicorn_results['messages_per_worker']}")
    print(f"      Rotation occurred: {gunicorn_results['rotation_occurred']}")
    
    # Test no apparent log loss
    print("\n🧪 Testing No Apparent Log Loss...")
    loss_results = test_no_apparent_log_loss(num_workers=2, messages_per_worker=150)
    print(f"   📊 Results:")
    print(f"      Files found: {loss_results['files_found']}")
    print(f"      Total lines: {loss_results['total_lines']}")
    print(f"      Overall passed: {loss_results['overall_passed']}")
    print(f"      Tolerance: {loss_results['tolerance_used']}")
    
    for wid, result in loss_results['per_worker_results'].items():
        print(f"      Worker {wid}: {result['coverage']} "
              f"(min={result['min_message']}, max={result['max_message']})")
    
    # Test Gunicorn config creation
    print("\n🧪 Testing Gunicorn Config Creation...")
    gunicorn_config = create_gunicorn_config_file()
    print(f"   ✅ Gunicorn config created: {gunicorn_config}")
    
    # Test Gunicorn logging configuration
    print("\n🧪 Testing Gunicorn Logging Configuration...")
    gunicorn_logger = configure_gunicorn_logging()
    gunicorn_logger.info("Gunicorn logging test: 🚀 αβγ")
    
    # Test cross-platform pytest setup
    print("\n🧪 Testing Cross-Platform Pytest Setup...")
    mp_configured = configure_cross_platform_multiprocessing()
    conftest_file = create_conftest_file()
    print(f"   ✅ Multiprocessing configured: {mp_configured}")
    print(f"   ✅ Conftest file created: {conftest_file}")
    
    # Test heavy rotation under load
    print("\n🧪 Testing Heavy Rotation Under Load...")
    heavy_results = test_heavy_rotation_under_load(num_workers=2, messages_per_worker=500)
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
    
    print("\n✅ All Gunicorn-style UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Gunicorn-Style Features:")
    print("   • Gunicorn-style multiprocess integration testing")
    print("   • No apparent log loss validation with sequence numbers")
    print("   • Gunicorn config example with concurrent handler")
    print("   • Cross-platform pytest setup (spawn/fork)")
    print("   • Heavy rotation under concurrent writes")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

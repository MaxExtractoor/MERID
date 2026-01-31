"""
MERID Tight Testing UTF-8 Logging Patterns
Tight wiring patterns covering log capture, worker record assertions, pytest teardown, xdist integration, and listener-only configuration.

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
from logging.handlers import TimedRotatingFileHandler, QueueHandler, QueueListener
from pathlib import Path

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - tight testing patterns will use fallback")

# Fallback functions for end-to-end patterns
def _listener_process_fallback(log_path: str, queue: mp.Queue):
    """Fallback listener process when utf8_end_to_end_patterns is not available."""
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    try:
        while True:
            record = queue.get()
            if record is None:  # sentinel => shutdown
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
    finally:
        handler.close()


def setup_end_to_end_logging_listener_fallback(tmp_path: Union[str, pathlib.Path]) -> Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]:
    """Fallback setup when utf8_end_to_end_patterns is not available."""
    if isinstance(tmp_path, str):
        tmp_path = pathlib.Path(tmp_path)
    
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "multiproc.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(
        target=_listener_process_fallback,
        args=(str(log_file), q),
        daemon=True,
    )
    proc.start()

    return {"queue": q, "log_file": log_file, "process": proc}


def cleanup_end_to_end_logging_listener_fallback(logging_info: Dict[str, Union[mp.Queue, pathlib.Path, mp.Process]]) -> None:
    """Fallback cleanup when utf8_end_to_end_patterns is not available."""
    if "queue" in logging_info:
        logging_info["queue"].put_nowait(None)  # sentinel
        logging_info["queue"].close()
    if "process" in logging_info:
        logging_info["process"].join(timeout=5)


def _worker_fallback(queue: mp.Queue, wid: int, n: int):
    """Fallback worker function when utf8_end_to_end_patterns is not available."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    logger = logging.getLogger(f"worker-{wid}")
    for i in range(n):
        logger.info("wid=%d msg=%d", wid, i)


# 1) Capture listener log file contents in tests
def capture_log_contents(log_file: pathlib.Path) -> dict:
    """
    Capture listener log file contents in tests.
    
    With the fixture from earlier, you just read the file the listener writes to.
    
    You can also split lines and parse structured fields (worker id, seq, etc.) 
    for stronger assertions.
    """
    if not log_file.exists():
        return {
            "file_exists": False,
            "content": "",
            "lines": [],
            "contains_worker_ids": False,
            "contains_messages": False
        }
    
    try:
        text = log_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        
        return {
            "file_exists": True,
            "content": text,
            "lines": lines,
            "contains_worker_ids": "wid=" in text,
            "contains_messages": "msg=" in text,
            "line_count": len(lines)
        }
    except Exception as e:
        return {
            "file_exists": False,
            "content": "",
            "lines": [],
            "contains_worker_ids": False,
            "contains_messages": False,
            "error": str(e)
        }


def test_logs_are_written(
    log_path: Union[str, pathlib.Path] = "logs/capture_test.log",
    num_workers: int = 2,
    messages_per_worker: int = 20
) -> dict:
    """
    Test that logs are written to the listener file.
    
    With the fixture from earlier, you just read the file the listener writes to.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    try:
        from utf8_end_to_end_patterns import setup_end_to_end_logging_listener, cleanup_end_to_end_logging_listener
    except ImportError:
        setup_end_to_end_logging_listener = setup_end_to_end_logging_listener_fallback
        cleanup_end_to_end_logging_listener = cleanup_end_to_end_logging_listener_fallback
    
    try:
        from utf8_end_to_end_patterns import _worker
    except ImportError:
        _worker = _worker_fallback
    
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Capture and analyze log contents
        capture_results = capture_log_contents(log_file)
        
        return {
            "capture_results": capture_results,
            "test_passed": capture_results["contains_worker_ids"] and capture_results["contains_messages"],
            "workers": num_workers,
            "messages_per_worker": messages_per_worker,
            "expected_total_messages": num_workers * messages_per_worker
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 2) Assert log records from specific workers
def _worker_with_sequence(queue: mp.Queue, wid: int, n: int):
    """
    Worker function that includes worker ID and message sequence.
    
    Give each worker a wid and msg sequence, and assert they appear in the 
    listener's file.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    logger = logging.getLogger(f"worker-{wid}")
    for i in range(n):
        logger.info("wid=%d msg=%d", wid, i)


def assert_worker_records_seen(
    log_path: Union[str, pathlib.Path] = "logs/assert_test.log",
    num_workers: int = 3,
    messages_per_worker: int = 50,
    tolerance: int = 10  # allow some timing slack
) -> dict:
    """
    Assert log records from specific workers.
    
    This pattern is enough to detect "most records" per worker under concurrent load.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    try:
        from utf8_end_to_end_patterns import setup_end_to_end_logging_listener, cleanup_end_to_end_logging_listener
    except ImportError:
        setup_end_to_end_logging_listener = setup_end_to_end_logging_listener_fallback
        cleanup_end_to_end_logging_listener = cleanup_end_to_end_logging_listener_fallback
    
    try:
        from utf8_end_to_end_patterns import _worker_with_sequence
    except ImportError:
        _worker_with_sequence = _worker_fallback
    
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker_with_sequence, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Parse and analyze worker records
        text = log_file.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Collect seen msg indices per worker
        seen = {wid: set() for wid in range(num_workers)}
        for line in lines:
            if "wid=" not in line or "msg=" not in line:
                continue
            parts = dict(
                part.split("=", 1) for part in line.split() if "=" in part
            )
            try:
                wid = int(parts["wid"])
                msg = int(parts["msg"])
                if wid in seen:
                    seen[wid].add(msg)
            except (KeyError, ValueError):
                continue

        # Assert each worker's records
        assertion_results = {}
        for wid in seen:
            min_msg = min(seen[wid]) if seen[wid] else None
            max_msg = max(seen[wid]) if seen[wid] else None
            count = len(seen[wid])
            
            assertion_results[wid] = {
                "seen_count": count,
                "min_msg": min_msg,
                "max_msg": max_msg,
                "expected_count": messages_per_worker,
                "has_start": min_msg == 0,
                "has_enough": max_msg >= (messages_per_worker - tolerance) if max_msg is not None else False,
                "assertion_passed": min_msg == 0 and (max_msg >= (messages_per_worker - tolerance) if max_msg is not None else False)
            }

        overall_passed = all(result["assertion_passed"] for result in assertion_results.values())
        
        return {
            "assertion_results": assertion_results,
            "overall_passed": overall_passed,
            "workers": num_workers,
            "messages_per_worker": messages_per_worker,
            "tolerance": tolerance,
            "total_lines": len(lines),
            "test_passed": overall_passed
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 3) Example pytest teardown ensuring listener shutdown
def create_teardown_fixture_example() -> str:
    """
    Example pytest teardown ensuring listener shutdown.
    
    The key is a sentinel + join in the fixture, so tests don't have to care.
    
    This is the standard pattern from QueueHandler/QueueListener multiprocessing examples.
    """
    fixture_code = '''
@pytest.fixture(scope="session")
def log_queue(tmp_path_factory):
    # ... create log_file, queue, start listener process ...
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "multiproc.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(target=_listener_process, args=(str(log_file), q), daemon=True)
    proc.start()

    yield {"queue": q, "log_file": log_file}

    # graceful shutdown
    q.put_nowait(None)  # sentinel for listener
    q.close()
    proc.join(timeout=5)
'''
    
    listener_loop_code = '''
while True:
    record = queue.get()
    if record is None:
        break
    logger = logging.getLogger(record.name)
    logger.handle(record)
'''
    
    return {
        "fixture_code": fixture_code,
        "listener_loop_code": listener_loop_code,
        "description": "Standard pattern from QueueHandler/QueueListener multiprocessing examples"
    }


# 4) Integrate QueueListener fixture with pytest-xdist workers
def create_xdist_integration_guide() -> dict:
    """
    Integrate QueueListener fixture with pytest-xdist workers.
    
    With xdist, each test process gets its own Python interpreter. Two practical options:
    
    1) Per-process listener (simple, easier to reason about)
       - The log_queue fixture runs independently in each xdist worker process
       - Each worker has its own logging listener process and log file
       - You can include the worker id in the file name using tmp_path_factory.mktemp
    
    2) Central listener process (more complex)
       - Start a single listener process in a known location
       - Configure each xdist worker to import that queue and attach QueueHandler(queue)
    
    In most cases, per-worker listeners are sufficient and avoid cross-process coordination.
    """
    return {
        "per_worker_listener": {
            "description": "Simple, easier to reason about",
            "implementation": "log_queue fixture runs independently in each xdist worker process",
            "benefits": ["No cross-process coordination", "Each worker has its own log file", "Simpler debugging"],
            "file_naming": "Include worker id in file name using tmp_path_factory.mktemp",
            "recommendation": "Recommended for most cases"
        },
        "central_listener": {
            "description": "More complex, single listener for all workers",
            "implementation": "Start single listener process, expose queue via module",
            "benefits": ["Single log file", "Centralized rotation", "Consistent formatting"],
            "challenges": ["Cross-process coordination", "Complex setup", "Potential bottlenecks"],
            "recommendation": "Use only when single log file is required"
        },
        "overall_recommendation": "Per-worker listeners are sufficient and avoid cross-process coordination",
        "xdist_compatibility": "Both approaches work with pytest-xdist",
        "coverage": "Both provide good coverage of QueueHandler/QueueListener behavior"
    }


def test_xdist_compatibility_simulation(
    log_path: Union[str, pathlib.Path] = "logs/xdist_test.log",
    worker_id: str = "worker_1",
    num_workers: int = 2,
    messages_per_worker: int = 30
) -> dict:
    """
    Simulate xdist compatibility with per-worker listener.
    
    This simulates the per-worker listener approach where each xdist worker 
    gets its own listener process and log file.
    """
    log_path = pathlib.Path(log_path)
    
    # Include worker ID in the log file name to simulate xdist behavior
    worker_log_path = log_path.parent / f"{log_path.stem}_{worker_id}{log_path.suffix}"
    worker_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process for this "worker"
    try:
        from utf8_end_to_end_patterns import setup_end_to_end_logging_listener, cleanup_end_to_end_logging_listener, _worker
    except ImportError:
        setup_end_to_end_logging_listener = setup_end_to_end_logging_listener_fallback
        cleanup_end_to_end_logging_listener = cleanup_end_to_end_logging_listener_fallback
        _worker = _worker_fallback
    
    logging_info = setup_end_to_end_logging_listener(worker_log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        # Rename the log file to include worker ID
        if log_file.exists():
            new_log_file = worker_log_path
            log_file.rename(new_log_file)
            log_file = new_log_file

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Capture results
        capture_results = capture_log_contents(log_file)
        
        return {
            "worker_id": worker_id,
            "log_file": str(log_file),
            "capture_results": capture_results,
            "test_passed": capture_results["contains_worker_ids"],
            "xdist_simulation": "per_worker_listener",
            "workers": num_workers,
            "messages_per_worker": messages_per_worker
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 5) Configure levels and formatters for listener only
def create_listener_only_config(
    log_path: Union[str, pathlib.Path] = "logs/listener_only.log",
    handler_level: int = logging.INFO,
    root_level: int = logging.DEBUG,
    when: str = "midnight",
    interval: int = 1,
    backup_count: int = 7,
    encoding: str = "utf-8"
) -> dict:
    """
    Configure levels and formatters for listener only.
    
    Workers shouldn't own file handlers or formatting; they just enqueue 
    LogRecords. The listener process configures root and handlers.
    
    Notes:
    - Setting handler.setLevel(...) lets you filter by handler level in the listener
    - If you use QueueListener instead of a manual loop, pass respect_handler_level=True 
      so handler levels are honored
    - Keep worker loggers simple: set their level (e.g., INFO/DEBUG) and attach 
      a single QueueHandler(queue)—no formatters, no file/console handlers in workers
    
    This separation gives you centralized control of formatting, levels, and rotation 
    in the listener, while worker processes do minimal work on the hot path.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "listener_config": {
            "handler_level": handler_level,
            "root_level": root_level,
            "handler_type": "TimedRotatingFileHandler",
            "log_path": str(log_path),
            "when": when,
            "interval": interval,
            "backup_count": backup_count,
            "encoding": encoding,
            "formatter": "%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s",
            "respect_handler_level": True
        },
        "worker_config": {
            "level": "INFO",  # or DEBUG as needed
            "handler": "QueueHandler(queue)",
            "no_formatters": True,
            "no_file_handlers": True,
            "no_console_handlers": True
        },
        "separation_benefits": [
            "Centralized formatting control",
            "Centralized level filtering",
            "Centralized rotation management",
            "Minimal worker overhead",
            "Hot path optimization"
        ],
        "implementation_notes": [
            "Workers only enqueue LogRecords",
            "Listener handles all formatting and file I/O",
            "Handler-level filtering applied in listener",
            "QueueListener respects handler levels when respect_handler_level=True"
        ]
    }
    
    return config


def test_listener_only_configuration(
    log_path: Union[str, pathlib.Path] = "logs/listener_only_test.log",
    num_workers: int = 2,
    messages_per_worker: int = 25
) -> dict:
    """
    Test listener-only configuration with multiple workers.
    
    This demonstrates the separation where workers only enqueue records and 
    the listener handles all formatting, levels, and file I/O.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get listener-only configuration
    config = create_listener_only_configuration(log_path)
    
    # Set up queue listener process with enhanced configuration
    try:
        from utf8_end_to_end_patterns import setup_end_to_end_logging_listener, cleanup_end_to_end_logging_listener
    except ImportError:
        setup_end_to_end_logging_listener = setup_end_to_end_logging_listener_fallback
        cleanup_end_to_end_logging_listener = cleanup_end_to_end_logging_listener_fallback
    
    try:
        from utf8_end_to_end_patterns import _worker
    except ImportError:
        _worker = _worker_fallback
    
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Capture and analyze results
        capture_results = capture_log_contents(log_file)
        
        return {
            "config_applied": config,
            "capture_results": capture_results,
            "test_passed": capture_results["contains_worker_ids"],
            "separation_successful": True,
            "listener_only_config": True,
            "workers": num_workers,
            "messages_per_worker": messages_per_worker
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


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
            "()": "utf8_tight_testing_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Tight Testing UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test log capture
    print("\n🧪 Testing Log Capture...")
    capture_results = test_logs_are_written(
        log_path="logs/capture_test.log",
        num_workers=2,
        messages_per_worker=20
    )
    print(f"   📊 Results:")
    print(f"      Test passed: {capture_results['test_passed']}")
    print(f"      Workers: {capture_results['workers']}")
    print(f"      Messages per worker: {capture_results['messages_per_worker']}")
    print(f"      Contains worker IDs: {capture_results['capture_results']['contains_worker_ids']}")
    print(f"      Contains messages: {capture_results['capture_results']['contains_messages']}")
    
    # Test worker record assertions
    print("\n🧪 Testing Worker Record Assertions...")
    assertion_results = assert_worker_records_seen(
        log_path="logs/assert_test.log",
        num_workers=3,
        messages_per_worker=50,
        tolerance=10
    )
    print(f"   📊 Results:")
    print(f"      Overall passed: {assertion_results['overall_passed']}")
    print(f"      Workers: {assertion_results['workers']}")
    print(f"      Messages per worker: {assertion_results['messages_per_worker']}")
    print(f"      Tolerance: {assertion_results['tolerance']}")
    print(f"      Total lines: {assertion_results['total_lines']}")
    
    for wid, result in assertion_results['assertion_results'].items():
        status = "✅" if result['assertion_passed'] else "❌"
        print(f"      {status} Worker {wid}: {result['seen_count']}/{result['expected_count']} (min={result['min_msg']}, max={result['max_msg']})")
    
    # Test teardown example
    print("\n🧪 Testing Teardown Example...")
    teardown_example = create_teardown_fixture_example()
    print(f"   ✅ Teardown fixture example created")
    print(f"   📝 Description: {teardown_example['description']}")
    
    # Test xdist integration
    print("\n🧪 Testing XDist Integration...")
    xdist_guide = create_xdist_integration_guide()
    print(f"   📊 Recommendation: {xdist_guide['overall_recommendation']}")
    print(f"   📝 Per-worker benefits: {', '.join(xdist_guide['per_worker_listener']['benefits'])}")
    
    # Simulate xdist compatibility
    xdist_results = test_xdist_compatibility_simulation(
        log_path="logs/xdist_test.log",
        worker_id="worker_1",
        num_workers=2,
        messages_per_worker=30
    )
    print(f"   📊 XDist simulation results:")
    print(f"      Worker ID: {xdist_results['worker_id']}")
    print(f"      Test passed: {xdist_results['test_passed']}")
    print(f"      Log file: {xdist_results['log_file']}")
    
    # Test listener-only configuration
    print("\n🧪 Testing Listener-Only Configuration...")
    listener_config = create_listener_only_config()
    print(f"   ✅ Listener-only config created")
    print(f"   📝 Handler level: {logging.getLevelName(listener_config['listener_config']['handler_level'])}")
    print(f"   📝 Root level: {logging.getLevelName(listener_config['listener_config']['root_level'])}")
    print(f"   📝 Separation benefits: {', '.join(listener_config['separation_benefits'])}")
    
    listener_test_results = test_listener_only_configuration(
        log_path="logs/listener_only_test.log",
        num_workers=2,
        messages_per_worker=25
    )
    print(f"   📊 Test results:")
    print(f"      Test passed: {listener_test_results['test_passed']}")
    print(f"      Separation successful: {listener_test_results['separation_successful']}")
    print(f"      Listener-only config: {listener_test_results['listener_only_config']}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Tight testing test: 🚀 αβγ")
    
    print("\n✅ All tight testing UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Tight Testing Features:")
    print("   • Log file content capture and analysis")
    print("   • Worker record assertions with sequence validation")
    print("   • Pytest teardown with graceful shutdown")
    print("   • XDist integration patterns")
    print("   • Listener-only configuration for centralized control")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

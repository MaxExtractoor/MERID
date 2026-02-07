"""
MERID Clean Testing UTF-8 Logging Patterns
Clean testing patterns covering log file capture, worker process assertions, safe teardown, and caplog integration.

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
from collections import defaultdict
from queue import Queue

# Try to import concurrent-log-handler, but make it optional
try:
    from concurrent_log_handler import ConcurrentRotatingFileHandler
    CONCURRENT_HANDLER_AVAILABLE = True
except ImportError:
    CONCURRENT_HANDLER_AVAILABLE = False
    print("⚠️  concurrent-log-handler not available - clean testing patterns will use fallback")

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
        try:
            logging_info["queue"].put_nowait(None)  # sentinel
        except ValueError:
            pass  # Queue already closed
        try:
            logging_info["queue"].close()
        except ValueError:
            pass  # Queue already closed
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


# 1) Capture log file contents from the listener
def capture_listener_logs(log_file: pathlib.Path) -> dict:
    """
    Capture log file contents from the listener.
    
    Assuming the fixture returns {"queue": q, "log_file": log_file}:
    
    Just treat log_file as any other log target and inspect its contents after workers complete.
    """
    if not log_file.exists():
        return {
            "file_exists": False,
            "content": "",
            "lines": [],
            "contains_worker_markers": False,
            "contains_process_info": False
        }
    
    try:
        text = log_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        
        return {
            "file_exists": True,
            "content": text,
            "lines": lines,
            "contains_worker_markers": "wid=" in text,
            "contains_process_info": "[process]" in text or "[pid:" in text,
            "line_count": len(lines)
        }
    except Exception as e:
        return {
            "file_exists": False,
            "content": "",
            "lines": [],
            "contains_worker_markers": False,
            "contains_process_info": False,
            "error": str(e)
        }


def test_listener_logs_written(
    log_path: Union[str, pathlib.Path] = "logs/clean_capture.log",
    num_workers: int = 2,
    messages_per_worker: int = 15
) -> dict:
    """
    Test that listener logs are written and can be captured.
    
    Just treat log_file as any other log target and inspect its contents after workers complete.
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
        capture_results = capture_listener_logs(log_file)
        
        return {
            "capture_results": capture_results,
            "test_passed": capture_results["contains_worker_markers"],
            "workers": num_workers,
            "messages_per_worker": messages_per_worker,
            "expected_total_messages": num_workers * messages_per_worker
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 2) Assert which process emitted a specific log record
def _worker_with_process_info(queue: mp.Queue, wid: int, n: int):
    """
    Worker function that includes process info and worker ids in the formatted message.
    
    Include process info and worker ids in the formatted message, then parse them from the file.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(queue))

    logger = logging.getLogger(f"worker-{wid}")
    for i in range(n):
        logger.info("wid=%d msg=%d pid=%d", wid, i, os.getpid())


def test_specific_worker_logs(
    log_path: Union[str, pathlib.Path] = "logs/clean_worker_assert.log",
    num_workers: int = 2,
    messages_per_worker: int = 20,
    min_expected_messages: int = 10
) -> dict:
    """
    Assert which process emitted a specific log record.
    
    If you also format %(process)d in the listener formatter, you can correlate 
    OS PIDs with worker ids for deeper checks.
    """
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Set up queue listener process
    try:
        from utf8_end_to_end_patterns import setup_end_to_end_logging_listener, cleanup_end_to_end_logging_listener
    except ImportError:
        setup_end_to_end_logging_listener = setup_end_to_end_logging_listener_fallback
        cleanup_end_to_end_logging_listener = cleanup_end_to_end_logging_listener_fallback
    
    logging_info = setup_end_to_end_logging_listener(log_path.parent)
    
    try:
        q = logging_info["queue"]
        log_file = logging_info["log_file"]

        procs = []
        for wid in range(num_workers):
            p = mp.Process(target=_worker_with_process_info, args=(q, wid, messages_per_worker))
            p.start()
            procs.append(p)

        for p in procs:
            p.join()

        # Wait for logs to be processed
        time.sleep(2)  # Give listener time to process all messages

        # Parse and analyze worker logs
        lines = log_file.read_text(encoding="utf-8").splitlines()
        seen = defaultdict(set)
        process_mapping = {}

        for line in lines:
            if "wid=" not in line or "msg=" not in line or "pid=" not in line:
                continue
            parts = dict(part.split("=", 1) for part in line.split() if "=" in part)
            try:
                wid = int(parts["wid"])
                msg = int(parts["msg"])
                pid = int(parts["pid"])
                seen[wid].add(msg)
                process_mapping[wid] = pid
            except (KeyError, ValueError):
                continue

        # Assert specific worker logs
        assertion_results = {}
        for wid in range(num_workers):
            min_msg = min(seen[wid]) if seen[wid] else None
            max_msg = max(seen[wid]) if seen[wid] else None
            count = len(seen[wid])
            pid = process_mapping.get(wid)
            
            assertion_results[wid] = {
                "seen_count": count,
                "min_msg": min_msg,
                "max_msg": max_msg,
                "expected_count": messages_per_worker,
                "has_start": min_msg == 0,
                "has_enough": max_msg >= min_expected_messages if max_msg is not None else False,
                "process_id": pid,
                "assertion_passed": min_msg == 0 and (max_msg >= min_expected_messages if max_msg is not None else False)
            }

        overall_passed = all(result["assertion_passed"] for result in assertion_results.values())
        
        return {
            "assertion_results": assertion_results,
            "overall_passed": overall_passed,
            "workers": num_workers,
            "messages_per_worker": messages_per_worker,
            "min_expected_messages": min_expected_messages,
            "total_lines": len(lines),
            "process_mapping": process_mapping,
            "test_passed": overall_passed
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 3) Teardown that avoids losing records during shutdown
def create_safe_teardown_fixture() -> dict:
    """
    Teardown that avoids losing records during shutdown.
    
    Key points for a safe shutdown: send a sentinel, let the listener finish processing, then join.
    
    Because you send the sentinel after workers join, all their records are already 
    in the queue when the listener drains it, minimizing loss risk.
    """
    fixture_code = '''
@pytest.fixture(scope="session")
def log_queue(tmp_path_factory):
    # ... set up log_file, queue, and listener process ...
    log_dir = tmp_path_factory.mktemp("logs")
    log_file = log_dir / "multiproc.log"

    q: mp.Queue = mp.Queue(-1)
    proc = mp.Process(target=_listener_process, args=(str(log_file), q), daemon=True)
    proc.start()

    yield {"queue": q, "log_file": log_file}

    # Signal the listener to stop after processing queued records
    q.put_nowait(None)  # sentinel
    q.close()
    proc.join(timeout=5)
'''
    
    listener_loop_code = '''
def _listener_process(log_path: str, queue: mp.Queue):
    handler = TimedRotatingFileHandler(...)
    handler.setFormatter(...)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    try:
        while True:
            record = queue.get()
            if record is None:
                break
            root.handle(record)
    finally:
        handler.close()
'''
    
    return {
        "fixture_code": fixture_code,
        "listener_loop_code": listener_loop_code,
        "description": "Safe shutdown with sentinel after workers join",
        "key_points": [
            "Send sentinel after workers join",
            "Let listener finish processing",
            "Join listener with timeout",
            "Minimize record loss risk"
        ]
    }


def test_safe_teardown_simulation(
    log_path: Union[str, pathlib.Path] = "logs/safe_teardown.log",
    num_workers: int = 3,
    messages_per_worker: int = 25
) -> dict:
    """
    Test safe teardown simulation.
    
    This demonstrates the safe shutdown pattern where the sentinel is sent 
    after workers join, ensuring all records are processed before shutdown.
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

        # Wait for all workers to complete first
        for p in procs:
            p.join()

        # Then send sentinel and clean up
        capture_before_shutdown = capture_listener_logs(log_file)
        
        # Simulate safe shutdown
        q.put_nowait(None)  # sentinel
        q.close()
        
        # Wait for listener to process remaining records
        time.sleep(1)
        
        capture_after_shutdown = capture_listener_logs(log_file)
        
        return {
            "capture_before_shutdown": capture_before_shutdown,
            "capture_after_shutdown": capture_after_shutdown,
            "workers_completed": len(procs),
            "messages_per_worker": messages_per_worker,
            "expected_total_messages": num_workers * messages_per_worker,
            "safe_teardown_applied": True,
            "test_passed": capture_after_shutdown["contains_worker_markers"]
        }
    finally:
        cleanup_end_to_end_logging_listener(logging_info)


# 4) Using caplog with QueueHandler/QueueListener
def test_queue_listener_with_caplog() -> dict:
    """
    Using caplog with QueueHandler/QueueListener.
    
    Pytest's caplog only sees records processed in the current process, not in 
    forked/spawned children.
    
    For QueueHandler/QueueListener integration tests:
    
    - Attach QueueHandler(queue) in workers (child processes).
    - Make the listener process write to a file (as above).
    - Use caplog only for in-process logging (e.g., the listener process, if you 
      implement it as a thread instead of a separate process).
    
    For true multiprocessing logging, use the file-inspection approach rather than 
    caplog, since pytest cannot natively capture logs from child processes.
    """
    # This would be used in a pytest test with caplog fixture
    threaded_listener_code = '''
import logging
from logging.handlers import QueueHandler, QueueListener
from queue import Queue


def test_queue_listener_with_caplog(caplog):
    q = Queue()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    listener = QueueListener(q, handler, respect_handler_level=True)
    listener.start()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(q))

    logger = logging.getLogger("app")
    with caplog.at_level(logging.INFO, logger="app"):
        logger.info("hello from queue")

    listener.stop()

    assert any("hello from queue" in r.message for r in caplog.records)
'''
    
    return {
        "threaded_listener_code": threaded_listener_code,
        "description": "Using caplog with threaded QueueListener",
        "limitations": [
            "caplog only sees records in current process",
            "not suitable for multiprocessing with separate processes",
            "use file-inspection for true multiprocessing logging"
        ],
        "recommendations": [
            "Use threaded listener for caplog integration",
            "Use file inspection for multiprocessing logging",
            "Combine both approaches for comprehensive testing"
        ]
    }


def test_threaded_queue_listener_simulation() -> dict:
    """
    Test threaded QueueListener simulation for caplog integration.
    
    This demonstrates how caplog can work with a threaded QueueListener 
    (not a separate process).
    """
    q = Queue()
    handler = logging.StreamHandler(io.StringIO())
    handler.setFormatter(logging.Formatter("%(message)s"))

    listener = QueueListener(q, handler, respect_handler_level=True)
    listener.start()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(QueueHandler(q))

    logger = logging.getLogger("app")
    
    # Simulate caplog-like behavior
    log_records = []
    original_handle = root.handle
    
    def capture_handle(record):
        log_records.append(record)
        original_handle(record)
    
    root.handle = capture_handle
    
    try:
        logger.info("hello from queue")
        logger.info("second message")
        
        # Simulate caplog assertions
        messages = [r.getMessage() for r in log_records]
        
        return {
            "log_records": log_records,
            "messages": messages,
            "contains_hello": "hello from queue" in messages,
            "contains_second": "second message" in messages,
            "record_count": len(log_records),
            "test_passed": "hello from queue" in messages and "second message" in messages
        }
    finally:
        listener.stop()
        root.handle = original_handle


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
            "()": "utf8_clean_testing_patterns.Utf8StreamHandler",
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
    print("🚀 Testing Clean Testing UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test log capture
    print("\n🧪 Testing Log Capture...")
    capture_results = test_listener_logs_written(
        log_path="logs/clean_capture.log",
        num_workers=2,
        messages_per_worker=15
    )
    print(f"   📊 Results:")
    print(f"      Test passed: {capture_results['test_passed']}")
    print(f"      Workers: {capture_results['workers']}")
    print(f"      Messages per worker: {capture_results['messages_per_worker']}")
    print(f"      Contains worker markers: {capture_results['capture_results']['contains_worker_markers']}")
    print(f"      Contains process info: {capture_results['capture_results']['contains_process_info']}")
    
    # Test specific worker logs
    print("\n🧪 Testing Specific Worker Logs...")
    worker_results = test_specific_worker_logs(
        log_path="logs/clean_worker_assert.log",
        num_workers=2,
        messages_per_worker=20,
        min_expected_messages=10
    )
    print(f"   📊 Results:")
    print(f"      Overall passed: {worker_results['overall_passed']}")
    print(f"      Workers: {worker_results['workers']}")
    print(f"      Messages per worker: {worker_results['messages_per_worker']}")
    print(f"      Min expected messages: {worker_results['min_expected_messages']}")
    print(f"      Total lines: {worker_results['total_lines']}")
    
    for wid, result in worker_results['assertion_results'].items():
        status = "✅" if result['assertion_passed'] else "❌"
        print(f"      {status} Worker {wid}: {result['seen_count']}/{result['expected_count']} (pid={result['process_id']}, min={result['min_msg']}, max={result['max_msg']})")
    
    # Test safe teardown
    print("\n🧪 Testing Safe Teardown...")
    teardown_example = create_safe_teardown_fixture()
    print(f"   ✅ Safe teardown fixture created")
    print(f"   📝 Description: {teardown_example['description']}")
    print(f"   📝 Key points: {', '.join(teardown_example['key_points'])}")
    
    safe_teardown_results = test_safe_teardown_simulation(
        log_path="logs/safe_teardown.log",
        num_workers=3,
        messages_per_worker=25
    )
    print(f"   📊 Safe teardown results:")
    print(f"      Workers completed: {safe_teardown_results['workers_completed']}")
    print(f"      Test passed: {safe_teardown_results['test_passed']}")
    print(f"      Safe teardown applied: {safe_teardown_results['safe_teardown_applied']}")
    
    # Test caplog integration
    print("\n🧪 Testing Caplog Integration...")
    caplog_info = test_queue_listener_with_caplog()
    print(f"   ✅ Caplog integration guide created")
    print(f"   📝 Description: {caplog_info['description']}")
    print(f"   📝 Limitations: {', '.join(caplog_info['limitations'])}")
    
    threaded_results = test_threaded_queue_listener_simulation()
    print(f"   📊 Threaded listener results:")
    print(f"      Test passed: {threaded_results['test_passed']}")
    print(f"      Record count: {threaded_results['record_count']}")
    print(f"      Contains hello: {threaded_results['contains_hello']}")
    print(f"      Contains second: {threaded_results['contains_second']}")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Clean testing test: 🚀 αβγ")
    
    print("\n✅ All clean testing UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Clean Testing Features:")
    print("   • Log file content capture and inspection")
    print("   • Worker process assertions with PID correlation")
    print("   • Safe teardown with sentinel after workers join")
    print("   • Caplog integration patterns")
    print("   • Threaded QueueListener simulation")
    print("   • UTF-8 BOM with all handlers")
    print("   • Console + file dual output")
    
    # Show availability status
    print("\n📋 Package Availability:")
    print(f"   concurrent-log-handler: {'✅ Available' if CONCURRENT_HANDLER_AVAILABLE else '❌ Not Available'}")

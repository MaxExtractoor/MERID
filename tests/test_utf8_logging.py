"""
MERID UTF-8 Logging Unit Tests
Comprehensive tests for production-ready UTF-8 logging.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
from pathlib import Path
import pytest

from utils.utf8_logging import configure_utf8_logging, get_governance_logger, get_analytics_logger, get_production_logger


def test_file_handler_uses_utf8(tmp_path: Path):
    """Test that UTF-8 characters are correctly written and read back from log files."""
    log_file = tmp_path / "test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)

    msg = "UTF-8 test 🚀 αβγ абв ابجد ∑ €"
    logger.info(msg)

    logger.handlers.clear()  # ensure file is flushed/closed by GC
    text = log_file.read_text(encoding="utf-8")

    assert "UTF-8 test" in text
    assert "🚀" in text
    assert "αβγ" in text
    assert "абв" in text
    assert "ابجد" in text
    assert "∑" in text
    assert "€" in text


def test_multiple_handlers_present(tmp_path: Path):
    """Test that both console and file handlers exist."""
    log_file = tmp_path / "test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)

    handlers = logger.handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    assert any(isinstance(h, logging.FileHandler) for h in handlers)
    assert len(handlers) == 2


def test_handlers_cleared_before_config(tmp_path: Path):
    """Test that pre-existing handlers get cleared, so cp1252 handlers cannot cause regressions."""
    # Add a dummy handler that should be removed
    root = logging.getLogger()
    original_handler_count = len(root.handlers)
    root.addHandler(logging.StreamHandler())

    log_file = tmp_path / "test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)

    # Only our two handlers remain
    assert len(logger.handlers) == 2
    # Clean up
    root.handlers.clear()


def test_governance_logger_configuration():
    """Test that governance logger is properly configured."""
    logger = get_governance_logger()
    
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.INFO
    assert len(logger.handlers) == 2
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_analytics_logger_configuration():
    """Test that analytics logger is properly configured."""
    logger = get_analytics_logger()
    
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.INFO
    assert len(logger.handlers) == 2
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_production_logger_custom_path(tmp_path: Path):
    """Test production logger with custom path."""
    custom_log_path = tmp_path / "custom" / "production.log"
    logger = get_production_logger("test_system", custom_log_path)
    
    assert logger.name == "test_system"
    assert len(logger.handlers) == 2
    assert custom_log_path.parent.exists()


def test_production_logger_default_path():
    """Test production logger with default path."""
    logger = get_production_logger("test_system")
    
    assert logger.name == "test_system"
    assert len(logger.handlers) == 2


def test_log_directory_creation(tmp_path: Path):
    """Test that log directories are created automatically."""
    nested_log_path = tmp_path / "nested" / "deep" / "test.log"
    logger = configure_utf8_logging(nested_log_path, level=logging.INFO)
    
    assert nested_log_path.parent.exists()
    assert nested_log_path.parent.is_dir()


def test_unicode_character_roundtrip(tmp_path: Path):
    """Test comprehensive Unicode character roundtrip."""
    log_file = tmp_path / "unicode_test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)
    
    # Test various Unicode categories
    test_messages = [
        "ASCII: Hello World",
        "Emoji: 🚀📊✅🔧🚨🌙📈🔗👥🎯",
        "Greek: αβγδεζηθικλμνξοπρστυφχψω",
        "Cyrillic: абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "Arabic: ابجدہحخدذرزسشصضطظعغفققكلم",
        "Math: ∑∏∫∮∯∰∱∲∳∴∵∶∷∸∹∺∻∼∽∾∿",
        "Currency: $€£¥₹₽₩₪₫₭₮₯₰₱₲₳₴₵₶₷₸₹₺",
        "Punctuation: «»""''—–…",
        "Symbols: ©®™℠℞℧Åℬℭ℮ℯℰℱℲℳℴℵℶℷℸℹ℺℻ℼℽℾℿ",
    ]
    
    for msg in test_messages:
        logger.info(msg)
    
    logger.handlers.clear()
    text = log_file.read_text(encoding="utf-8")
    
    # Verify all messages are present
    for msg in test_messages:
        assert msg in text, f"Message not found in log: {msg}"


def test_logging_levels(tmp_path: Path):
    """Test different logging levels work correctly."""
    log_file = tmp_path / "levels_test.log"
    logger = configure_utf8_logging(log_file, level=logging.DEBUG)
    
    logger.debug("Debug message 🐛")
    logger.info("Info message ℹ️")
    logger.warning("Warning message ⚠️")
    logger.error("Error message ❌")
    logger.critical("Critical message 🚨")
    
    logger.handlers.clear()
    text = log_file.read_text(encoding="utf-8")
    
    assert "Debug message 🐛" in text
    assert "Info message ℹ️" in text
    assert "Warning message ⚠️" in text
    assert "Error message ❌" in text
    assert "Critical message 🚨" in text


def test_error_handling_replace(tmp_path: Path):
    """Test that errors="replace" prevents crashes."""
    log_file = tmp_path / "error_test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)
    
    # This should not crash even with problematic characters
    try:
        logger.info("Test with various characters: \x00\x01\x02 🚀")
        logger.handlers.clear()
        text = log_file.read_text(encoding="utf-8")
        assert "Test with various characters" in text
    except Exception as e:
        pytest.fail(f"Logging should not crash: {e}")


def test_concurrent_logging(tmp_path: Path):
    """Test that concurrent logging works without issues."""
    import threading
    import time
    
    log_file = tmp_path / "concurrent_test.log"
    logger = configure_utf8_logging(log_file, level=logging.INFO)
    
    def log_worker(worker_id: int):
        for i in range(10):
            logger.info(f"Worker {worker_id}: Message {i} 🚀")
            time.sleep(0.001)  # Small delay to interleave messages
    
    # Start multiple threads
    threads = []
    for i in range(5):
        thread = threading.Thread(target=log_worker, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    logger.handlers.clear()
    text = log_file.read_text(encoding="utf-8")
    
    # Verify all messages are present
    for worker_id in range(5):
        for i in range(10):
            expected_msg = f"Worker {worker_id}: Message {i} 🚀"
            assert expected_msg in text, f"Missing message: {expected_msg}"


if __name__ == "__main__":
    # Run smoke test
    pytest.main([__file__, "-v"])

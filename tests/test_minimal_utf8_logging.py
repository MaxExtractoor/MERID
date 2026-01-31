"""
MERID Minimal UTF-8 Logging Unit Tests
Comprehensive tests for minimal UTF-8 logging with rotating handlers.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
from pathlib import Path
import pytest

from utils.minimal_utf8_logging import (
    configure_utf8_file_logging,
    configure_utf8_rotating_logging,
    configure_utf8_console_and_file,
    get_governance_file_logger,
    get_analytics_file_logger,
    get_production_file_logger,
    get_governance_rotating_logger,
    get_analytics_rotating_logger,
    get_production_rotating_logger,
)


def test_utf8_file_logging_writes_non_ascii(tmp_path: Path):
    """Test that UTF-8 file logging writes non-ASCII characters correctly."""
    log_file = tmp_path / "test.log"
    logger = configure_utf8_file_logging(log_file, level=logging.INFO)

    msg = "UTF-8 test: 🚀 αβγ абв ابجد ∑ €"
    logger.info(msg)

    # Ensure file is flushed/closed
    for h in logger.handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")

    assert "UTF-8 test:" in text
    assert "🚀" in text
    assert "αβγ" in text
    assert "абв" in text
    assert "ابجد" in text
    assert "∑" in text
    assert "€" in text


def test_rotating_handler_uses_utf8(tmp_path: Path):
    """Test that rotating handler uses UTF-8 encoding correctly."""
    log_file = tmp_path / "rotating.log"
    logger = configure_utf8_rotating_logging(
        log_file, 
        level=logging.INFO, 
        max_bytes=100, 
        backup_count=1
    )

    msg = "Unicode: 🚀"
    for _ in range(10):
        logger.info(msg)

    # At least one log file should exist and be readable as UTF-8
    files = list(tmp_path.glob("rotating.log*"))
    assert files

    for f in files:
        content = f.read_text(encoding="utf-8")
        assert "Unicode:" in content


def test_console_and_file_uses_utf8(tmp_path: Path):
    """Test that both console and file handlers use UTF-8."""
    log_file = tmp_path / "console_file.log"
    logger = configure_utf8_console_and_file(
        log_file, 
        level=logging.INFO, 
        max_bytes=100, 
        backup_count=1
    )

    msg = "Console+File: 🚀 αβγ"
    logger.info(msg)

    # Verify file content
    for h in logger.handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    assert "Console+File: 🚀 αβγ" in text

    # Verify handlers
    handlers = logger.handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    assert any(isinstance(h, RotatingFileHandler) for h in handlers)


def test_log_directory_creation(tmp_path: Path):
    """Test that log directories are created automatically."""
    nested_log_path = tmp_path / "nested" / "deep" / "test.log"
    logger = configure_utf8_file_logging(nested_log_path, level=logging.INFO)
    
    assert nested_log_path.parent.exists()
    assert nested_log_path.parent.is_dir()


def test_governance_file_logger():
    """Test governance file logger configuration."""
    logger = get_governance_file_logger()
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_analytics_file_logger():
    """Test analytics file logger configuration."""
    logger = get_analytics_file_logger()
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_production_file_logger():
    """Test production file logger configuration."""
    logger = get_production_file_logger("test_system")
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_governance_rotating_logger():
    """Test governance rotating logger configuration."""
    logger = get_governance_rotating_logger()
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def test_analytics_rotating_logger():
    """Test analytics rotating logger configuration."""
    logger = get_analytics_rotating_logger()
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def test_production_rotating_logger():
    """Test production rotating logger configuration."""
    logger = get_production_rotating_logger("test_system")
    
    assert isinstance(logger, logging.Logger)
    assert len(logger.handlers) == 1
    assert any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def test_unicode_character_comprehensive(tmp_path: Path):
    """Test comprehensive Unicode character support."""
    log_file = tmp_path / "comprehensive.log"
    logger = configure_utf8_file_logging(log_file, level=logging.INFO)
    
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
        "Symbols: ©®™℠℞℧Åℬℭ℮ℯℰℱℲℳℴℵℶℷℸℹ℺ℽℾℿ",
    ]
    
    for msg in test_messages:
        logger.info(msg)
    
    # Ensure file is flushed/closed
    for h in logger.handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    
    # Verify all messages are present
    for msg in test_messages:
        assert msg in text, f"Missing message: {msg}"


def test_logging_levels(tmp_path: Path):
    """Test different logging levels work correctly."""
    log_file = tmp_path / "levels_test.log"
    logger = configure_utf8_file_logging(log_file, level=logging.DEBUG)
    
    logger.debug("Debug message 🐛")
    logger.info("Info message ℹ️")
    logger.warning("Warning message ⚠️")
    logger.error("Error message ❌")
    logger.critical("Critical message 🚨")
    
    # Ensure file is flushed/closed
    for h in logger.handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    
    assert "Debug message 🐛" in text
    assert "Info message ℹ️" in text
    assert "Warning message ⚠️" in text
    assert "Error message ❌" in text
    assert "Critical message 🚨" in text


def test_rotation_behavior(tmp_path: Path):
    """Test that log rotation works correctly."""
    log_file = tmp_path / "rotation_test.log"
    logger = configure_utf8_rotating_logging(
        log_file, 
        level=logging.INFO, 
        max_bytes=50, 
        backup_count=2
    )
    
    # Write enough data to trigger rotation
    long_msg = "Rotation test: 🚀 αβγ абв ابجد ∑ €" * 10
    for i in range(5):
        logger.info(f"Batch {i}: {long_msg}")
    
    # Should have multiple files due to rotation
    files = list(tmp_path.glob("rotation_test.log*"))
    assert len(files) > 1, "Log rotation should have created multiple files"
    
    # All files should be readable as UTF-8
    for f in files:
        content = f.read_text(encoding="utf-8")
        assert "Batch" in content
        assert "🚀" in content


def test_handler_cleanup(tmp_path: Path):
    """Test that handlers are properly cleaned up."""
    log_file = tmp_path / "cleanup_test.log"
    
    # Add a dummy handler first
    root = logging.getLogger()
    original_handler_count = len(root.handlers)
    root.addHandler(logging.StreamHandler())
    
    # Configure our logger
    logger = configure_utf8_file_logging(log_file, level=logging.INFO)
    
    # Only our file handler should remain
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.FileHandler)
    
    # Clean up
    for h in logger.handlers:
        h.close()
    logger.handlers.clear()


if __name__ == "__main__":
    # Run smoke test
    pytest.main([__file__, "-v"])

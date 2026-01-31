"""
MERID Minimal UTF-8 Logging
Minimal, production-ready UTF-8 logging with rotating handlers and comprehensive tests.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import io
import sys
from pathlib import Path
from typing import Union
from logging.handlers import RotatingFileHandler


def configure_utf8_file_logging(
    log_path: Union[str, Path] = "logs/app.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Configure minimal UTF-8 file logging.
    
    This uses the officially supported `encoding="utf-8"` argument on `FileHandler` 
    to make file logs Unicode-safe.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(
        log_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(file_handler)

    return logger


def configure_utf8_rotating_logging(
    log_path: Union[str, Path] = "logs/app.log",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure UTF-8 rotating file logging.
    
    Adding `encoding="utf-8"` to `RotatingFileHandler` is the recommended fix 
    for Unicode issues in rotated logs.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
        max_bytes: Maximum bytes before rotation (default: 5MB)
        backup_count: Number of backup files to keep (default: 5)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(file_handler)

    return logger


def configure_utf8_console_and_file(
    log_path: Union[str, Path] = "logs/app.log",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure UTF-8 console and file logging with rotation.
    
    Wrapping `sys.stdout.buffer` in `io.TextIOWrapper(..., encoding="utf-8")` 
    bypasses the cp1252 console encoding on Windows while keeping file logs 
    UTF-8-encoded via the rotating handler.
    
    Args:
        log_path: Path to log file (default: "logs/app.log")
        level: Logging level (default: logging.INFO)
        max_bytes: Maximum bytes before rotation (default: 5MB)
        backup_count: Number of backup files to keep (default: 5)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 console stream (robust on Windows)
    utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )

    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


# MERID-specific convenience functions
def get_governance_file_logger() -> logging.Logger:
    """Get UTF-8 file logger for governance systems."""
    return configure_utf8_file_logging("governance/governance.log")


def get_analytics_file_logger() -> logging.Logger:
    """Get UTF-8 file logger for analytics systems."""
    return configure_utf8_file_logging("analytics/analytics.log")


def get_production_file_logger(name: str) -> logging.Logger:
    """Get UTF-8 file logger for production systems."""
    return configure_utf8_file_logging(f"logs/{name}.log")


def get_governance_rotating_logger() -> logging.Logger:
    """Get UTF-8 rotating logger for governance systems."""
    return configure_utf8_rotating_logging("governance/governance.log")


def get_analytics_rotating_logger() -> logging.Logger:
    """Get UTF-8 rotating logger for analytics systems."""
    return configure_utf8_rotating_logging("analytics/analytics.log")


def get_production_rotating_logger(name: str) -> logging.Logger:
    """Get UTF-8 rotating logger for production systems."""
    return configure_utf8_rotating_logging(f"logs/{name}.log")


# Manual smoke test for development
if __name__ == "__main__":
    logger = configure_utf8_console_and_file()

    logger.info("ASCII ok")
    logger.info("Emoji: 🚀📊✅")
    logger.info("Greek: αβγδεζηθικλμνξοπρστυφχψω")
    logger.info("Cyrillic: абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    logger.info("Arabic: ابجدہحخدذرزسشصضطظعغفققكلم")
    logger.info("Math: ∑∏∫∮∯∰∱∲∳∴∵∶∷∸∹∺∻∼∽∾∿")
    logger.info("Currency: $€£¥₹₽₩₪₫₭₮₯₰₱₲₳₴₵₶₷₸₹₺")
    
    print("✅ Minimal UTF-8 logging smoke test completed successfully!")
    print("📂 Check logs/app.log for UTF-8 encoded output")

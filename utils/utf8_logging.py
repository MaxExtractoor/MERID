"""
MERID UTF-8 Logging Utility
Production-ready UTF-8 logging setup with Windows compatibility.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import sys
import io
from pathlib import Path
from typing import Union


def configure_utf8_logging(
    log_path: Union[str, Path] = "logs/merid.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Configure production-ready UTF-8 logging for MERID systems.
    
    This function sets up robust UTF-8 logging that works on Windows without
    touching system locale, following patterns used in real Windows-heavy deployments.
    
    Args:
        log_path: Path to log file (default: "logs/merid.log")
        level: Logging level (default: logging.INFO)
    
    Returns:
        Configured logger instance
    
    Features:
        - UTF-8 console output bypassing Windows cp1252
        - UTF-8 encoded log files
        - Error handling prevents crashes on bad code points
        - Dual output (console + file) production pattern
        - Automatic log directory creation
        - Handler cleanup to remove cp1252 handlers
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    # Ensure log directory exists
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

    file_handler = logging.FileHandler(
        log_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


def get_governance_logger() -> logging.Logger:
    """Get logger configured for governance scheduler."""
    return configure_utf8_logging("governance/scheduler.log")


def get_analytics_logger() -> logging.Logger:
    """Get logger configured for cohort analytics."""
    return configure_utf8_logging("analytics/cohort_analytics.log")


def get_production_logger(name: str, log_path: Union[str, Path] = None) -> logging.Logger:
    """
    Get a production logger with UTF-8 configuration.
    
    Args:
        name: Logger name (for identification)
        log_path: Optional custom log path
    
    Returns:
        Configured logger instance
    """
    if log_path is None:
        log_path = f"logs/{name}.log"
    
    logger = configure_utf8_logging(log_path)
    logger.name = name
    return logger


# Manual smoke test for development
if __name__ == "__main__":
    logger = configure_utf8_logging()

    logger.info("ASCII ok")
    logger.info("Emoji: 🚀📊✅")
    logger.info("Greek: αβγδεζηθικλμνξοπρστυφχψω")
    logger.info("Cyrillic: абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    logger.info("Arabic: ابجدہحخدذرزسشصضطظعغفققكلم")
    logger.info("Math: ∑∏∫∮∯∰∱∲∳∴∵∶∷∸∹∺∻∼∽∾∿")
    logger.info("Currency: $€£¥₹₽₩₪₫₭₮₯₰₱₲₳₴₵₶₷₸₹₺")
    
    print("✅ UTF-8 logging smoke test completed successfully!")
    print("📂 Check logs/merid.log for UTF-8 encoded output")

"""
Centralized logging configuration for MERID production stack.

This module provides:
- Standardized log formatting
- Consistent log level configuration
- Structured logging support
- Correlation ID tracking
- Log handler management
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


# Standard log format with correlation ID support
STANDARD_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
STANDARD_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Simplified format for console output
CONSOLE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


class CorrelationIdFilter(logging.Filter):
    """Filter to add correlation ID to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation_id to log record if not present."""
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = ''
        return True


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    use_console: bool = True,
    use_structured: bool = False
) -> None:
    """
    Configure centralized logging for MERID.
    
    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path for file output
        use_console: Whether to output to console
        use_structured: Whether to use structured logging format
    """
    
    # Convert log level string to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Add correlation ID filter
    correlation_filter = CorrelationIdFilter()
    
    # Create formatter
    if use_structured:
        formatter = logging.Formatter(STANDARD_FORMAT, datefmt=STANDARD_DATE_FORMAT)
    else:
        formatter = logging.Formatter(CONSOLE_FORMAT, datefmt=STANDARD_DATE_FORMAT)
    
    # Add console handler
    if use_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(correlation_filter)
        root_logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(correlation_filter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)


def get_log_level() -> str:
    """
    Get the current log level from environment variable.
    
    Returns:
        Log level string (default: INFO)
    """
    import os
    return os.getenv('MERID_LOG_LEVEL', 'INFO')


def should_log_to_file() -> bool:
    """
    Determine if logging should go to a file.
    
    Returns:
        True if MERID_LOG_FILE is set, False otherwise
    """
    import os
    return os.getenv('MERID_LOG_FILE') is not None


def get_log_file_path() -> Optional[Path]:
    """
    Get the log file path from environment variable.
    
    Returns:
        Path to log file, or None if not set
    """
    import os
    log_file = os.getenv('MERID_LOG_FILE')
    if log_file:
        return Path(log_file)
    return None


def initialize_production_logging() -> None:
    """
    Initialize logging for production environment.
    
    This is called during application startup to configure logging
    based on environment variables.
    """
    log_level = get_log_level()
    log_file = get_log_file_path()
    
    setup_logging(
        log_level=log_level,
        log_file=log_file,
        use_console=True,
        use_structured=True
    )
    
    # Log initialization
    logger = logging.getLogger('utils.logging_config')
    logger.info(
        f"Logging initialized: level={log_level}, file={log_file}"
    )


def initialize_test_logging() -> None:
    """
    Initialize logging for test environment.
    
    This suppresses most logging during tests to reduce noise.
    """
    setup_logging(
        log_level="WARNING",
        use_console=True,
        use_structured=False
    )

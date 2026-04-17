"""Tests for utils/logger.py."""
import sys

# conftest.py stubs utils.logger to avoid Neo4j/Redis cold-start; remove the
# stub so this file can import the real implementation under test.
sys.modules.pop("utils.logger", None)

import pytest
import logging
import os
from unittest.mock import Mock, patch, MagicMock
from utils.logger import get_logger, SafeRotatingFileHandler, _LOGGER_CACHE


class TestSafeRotatingFileHandler:
    """Test SafeRotatingFileHandler."""

    @patch('utils.logger.os.path.exists')
    @patch('utils.logger.os.remove')
    @patch('utils.logger.os.rename')
    def test_doRollover_handles_windows_errors(self, mock_rename, mock_remove, mock_exists):
        """Test doRollover handles Windows permission errors."""
        mock_exists.return_value = True
        mock_remove.side_effect = PermissionError("Access denied")
        
        handler = SafeRotatingFileHandler("test.log", maxBytes=1000, backupCount=3)
        handler.stream = Mock()
        handler.baseFilename = "test.log"
        
        # Should not raise despite errors
        handler.doRollover()


class TestGetLogger:
    """Test get_logger function."""

    def test_returns_logger(self):
        """Test get_logger returns a Logger instance."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_caches_logger(self):
        """Test logger is cached and reused."""
        logger1 = get_logger("cached_test")
        logger2 = get_logger("cached_test")
        assert logger1 is logger2

    def test_logger_has_handlers(self):
        """Test returned logger has handlers configured."""
        logger = get_logger("handler_test")
        assert len(logger.handlers) > 0

    def test_logger_level_info(self):
        """Test logger level is set to INFO."""
        logger = get_logger("level_test")
        assert logger.level == logging.INFO

    def test_logger_no_propagate(self):
        """Test logger does not propagate to root."""
        logger = get_logger("propagate_test")
        assert logger.propagate is False

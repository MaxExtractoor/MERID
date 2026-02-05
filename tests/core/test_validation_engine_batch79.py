"""Tests for core/validation/engine.py - Batch 79."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.validation.engine import ValidationEngine


class TestValidationEngine:
    """Tests for ValidationEngine."""

    def test_init_with_validators(self):
        """Test initialization with validators."""
        mock_validators = [MagicMock(), MagicMock()]
        engine = ValidationEngine(validators=mock_validators)
        assert engine.validators == mock_validators

    def test_init_empty_validators(self):
        """Test initialization with empty validators."""
        engine = ValidationEngine(validators=[])
        assert engine.validators == []


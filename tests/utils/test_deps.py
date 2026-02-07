"""Tests for utils/deps.py."""
import pytest
from unittest.mock import patch, MagicMock
from utils.deps import (
    optional_dependency, dependency_available, require_dependency,
    dependency_report, get_ccxt, get_ccxt_async,
    torch_available, gym_available, networkx_available
)


class TestOptionalDependency:
    """Test optional_dependency function."""

    @patch('utils.deps.import_module')
    def test_import_success(self, mock_import):
        """Test successful import."""
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        result = optional_dependency("some_module")
        assert result is mock_module

    @patch('utils.deps.import_module')
    def test_import_not_found(self, mock_import):
        """Test import not found."""
        mock_import.side_effect = ModuleNotFoundError()
        result = optional_dependency("missing_module")
        assert result is None

    @patch('utils.deps.import_module')
    def test_import_error(self, mock_import):
        """Test import error."""
        mock_import.side_effect = Exception("Import error")
        result = optional_dependency("error_module")
        assert result is None


class TestDependencyAvailable:
    """Test dependency_available function."""

    @patch('utils.deps.optional_dependency')
    def test_available(self, mock_optional):
        """Test dependency is available."""
        mock_optional.return_value = MagicMock()
        assert dependency_available("module") is True

    @patch('utils.deps.optional_dependency')
    def test_not_available(self, mock_optional):
        """Test dependency is not available."""
        mock_optional.return_value = None
        assert dependency_available("module") is False


class TestRequireDependency:
    """Test require_dependency function."""

    @patch('utils.deps.optional_dependency')
    def test_require_success(self, mock_optional):
        """Test successful require."""
        mock_module = MagicMock()
        mock_optional.return_value = mock_module
        result = require_dependency("module")
        assert result is mock_module

    @patch('utils.deps.optional_dependency')
    def test_require_failure(self, mock_optional):
        """Test failed require raises RuntimeError."""
        mock_optional.return_value = None
        with pytest.raises(RuntimeError, match="requires"):
            require_dependency("module", feature="feature1")


class TestDependencyReport:
    """Test dependency_report function."""

    @patch('utils.deps.dependency_available')
    def test_report(self, mock_available):
        """Test report generation."""
        mock_available.return_value = True
        report = dependency_report()
        assert "ccxt" in report
        assert "torch" in report
        assert "gymnasium" in report
        assert "networkx" in report
        assert "email_validator" in report
        assert all(report.values())


class TestConvenienceFunctions:
    """Test convenience functions."""

    @patch('utils.deps.optional_dependency')
    def test_get_ccxt(self, mock_optional):
        """Test get_ccxt function."""
        mock_module = MagicMock()
        mock_optional.return_value = mock_module
        result = get_ccxt()
        assert result is mock_module

    @patch('utils.deps.optional_dependency')
    def test_get_ccxt_async(self, mock_optional):
        """Test get_ccxt_async function."""
        mock_module = MagicMock()
        mock_optional.return_value = mock_module
        result = get_ccxt_async()
        assert result is mock_module
        mock_optional.assert_called_with("ccxt.async_support")

    @patch('utils.deps.dependency_available')
    def test_torch_available(self, mock_available):
        """Test torch_available function."""
        mock_available.return_value = True
        assert torch_available() is True

    @patch('utils.deps.dependency_available')
    def test_gym_available(self, mock_available):
        """Test gym_available function."""
        mock_available.return_value = True
        assert gym_available() is True

    @patch('utils.deps.dependency_available')
    def test_networkx_available(self, mock_available):
        """Test networkx_available function."""
        mock_available.return_value = True
        assert networkx_available() is True

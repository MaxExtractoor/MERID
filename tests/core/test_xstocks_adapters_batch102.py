"""Tests for core/xstocks_adapters.py - Batch 102."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.xstocks_adapters import (
    XStocksTONAdapter, TokenizedEquityAdapter, SymbolNormalizer
)


class TestXStocksTONAdapter:
    """Tests for XStocksTONAdapter."""

    @pytest.fixture
    def adapter(self):
        with patch('core.xstocks_adapters.get_multichain_wallet'):
            return XStocksTONAdapter()

    def test_initialization(self, adapter):
        assert adapter is not None
        assert len(adapter._asset_registry) == 6

    def test_get_asset_found(self, adapter):
        asset = adapter.get_asset("TSLAx")
        assert asset is not None
        assert asset.symbol == "TSLAx"


class TestSymbolNormalizer:
    """Tests for SymbolNormalizer."""

    @pytest.fixture
    def normalizer(self):
        return SymbolNormalizer()

    def test_normalize_known_symbol(self, normalizer):
        result = normalizer.normalize("TSLAx")
        assert result["underlying"] == "TSLA"

    def test_get_underlying(self, normalizer):
        assert normalizer.get_underlying("TSLAx") == "TSLA"

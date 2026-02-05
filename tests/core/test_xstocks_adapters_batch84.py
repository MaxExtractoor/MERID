"""Tests for core/xstocks_adapters.py - Batch 84."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.xstocks_adapters import (
    AssetType, TradingHours, TokenizedAsset, AssetQuote,
    XStocksTONAdapter, SymbolNormalizer, get_xstocks_router
)


class TestEnums:
    """Tests for enums."""

    def test_asset_type_values(self):
        assert AssetType.XSTOCK_TON.value == "xstock_ton"
        assert AssetType.TOKENIZED_EQUITY.value == "tokenized_equity"

    def test_trading_hours_values(self):
        assert TradingHours.OPEN.value == "open"
        assert TradingHours.CLOSED.value == "closed"


class TestXStocksTONAdapter:
    """Tests for XStocksTONAdapter."""

    @pytest.fixture
    def adapter(self):
        with patch('core.xstocks_adapters.get_multichain_wallet'):
            return XStocksTONAdapter()

    def test_initialization(self, adapter):
        assert len(adapter._asset_registry) == 6
        assert "TSLAx" in adapter._asset_registry

    def test_get_asset_found(self, adapter):
        asset = adapter.get_asset("TSLAx")
        assert asset is not None
        assert asset.symbol == "TSLAx"
        assert asset.underlying_symbol == "TSLA"

    def test_get_asset_not_found(self, adapter):
        asset = adapter.get_asset("UNKNOWN")
        assert asset is None

    def test_get_quote_found(self, adapter):
        quote = adapter.get_quote("TSLAx")
        assert quote is not None
        assert quote.symbol == "TSLAx"
        assert quote.bid > 0

    def test_get_quote_not_found(self, adapter):
        quote = adapter.get_quote("UNKNOWN")
        assert quote is None


class TestSymbolNormalizer:
    """Tests for SymbolNormalizer."""

    @pytest.fixture
    def normalizer(self):
        return SymbolNormalizer()

    def test_normalize_known_symbol(self, normalizer):
        result = normalizer.normalize("TSLAx")
        assert result["underlying"] == "TSLA"
        assert result["xstock_ton"] == "TSLAx"

    def test_normalize_underlying(self, normalizer):
        result = normalizer.normalize("TSLA")
        assert result["underlying"] == "TSLA"

    def test_normalize_unknown_symbol(self, normalizer):
        result = normalizer.normalize("UNKNOWN")
        assert result == {"underlying": "UNKNOWN"}

    def test_get_underlying(self, normalizer):
        assert normalizer.get_underlying("TSLAx") == "TSLA"
        assert normalizer.get_underlying("TSLA") == "TSLA"

    def test_get_variant_found(self, normalizer):
        result = normalizer.get_variant("TSLA", AssetType.XSTOCK_TON)
        assert result == "TSLAx"

    def test_get_variant_not_found(self, normalizer):
        result = normalizer.get_variant("UNKNOWN", AssetType.XSTOCK_TON)
        assert result is None


class TestSingleton:
    """Tests for singleton."""

    def test_get_xstocks_router_singleton(self):
        with patch('core.xstocks_adapters.get_multichain_wallet'):
            router1 = get_xstocks_router()
            router2 = get_xstocks_router()
            assert router1 is router2

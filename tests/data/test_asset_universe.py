"""Tests for data/asset_universe.py."""
import pytest
from data.asset_universe import (
    Asset, ASSET_UNIVERSE, CATEGORIES, MARKET_CAP_TIERS,
    get_asset, get_assets_by_category, get_all_symbols, get_all_coingecko_ids, get_watchlist_symbols
)


class TestAsset:
    """Test Asset dataclass."""

    def test_creation(self):
        """Test Asset creation."""
        asset = Asset(
            symbol="BTC/USDT",
            name="Bitcoin",
            category="Layer1",
            coingecko_id="bitcoin",
            market_cap_rank=1,
            is_layer1=True
        )
        assert asset.symbol == "BTC/USDT"
        assert asset.name == "Bitcoin"
        assert asset.category == "Layer1"
        assert asset.coingecko_id == "bitcoin"
        assert asset.market_cap_rank == 1
        assert asset.is_layer1 is True
        assert asset.is_defi is False
        assert asset.is_layer2 is False

    def test_default_flags(self):
        """Test Asset with default boolean flags."""
        asset = Asset(
            symbol="ETH/USDT",
            name="Ethereum",
            category="Layer1",
            coingecko_id="ethereum",
            market_cap_rank=2
        )
        assert asset.is_defi is False
        assert asset.is_layer1 is False
        assert asset.is_layer2 is False


class TestAssetUniverse:
    """Test ASSET_UNIVERSE dictionary."""

    def test_btc_in_universe(self):
        """Test BTC is in asset universe."""
        assert "BTC" in ASSET_UNIVERSE
        btc = ASSET_UNIVERSE["BTC"]
        assert btc.symbol == "BTC/USDT"
        assert btc.is_layer1 is True

    def test_eth_in_universe(self):
        """Test ETH is in asset universe."""
        assert "ETH" in ASSET_UNIVERSE
        eth = ASSET_UNIVERSE["ETH"]
        assert eth.symbol == "ETH/USDT"
        assert eth.is_layer1 is True

    def test_defi_assets(self):
        """Test DeFi assets are marked correctly."""
        uni = ASSET_UNIVERSE.get("UNI")
        assert uni is not None
        assert uni.is_defi is True
        assert uni.category == "DeFi"

    def test_layer2_assets(self):
        """Test Layer 2 assets are marked correctly."""
        matic = ASSET_UNIVERSE.get("MATIC")
        assert matic is not None
        assert matic.is_layer2 is True
        assert matic.category == "Layer2"


class TestCategories:
    """Test CATEGORIES dictionary."""

    def test_layer1_category(self):
        """Test layer1 category contains layer1 assets."""
        layer1 = CATEGORIES.get("layer1", [])
        assert "BTC" in layer1
        assert "ETH" in layer1
        assert "SOL" in layer1

    def test_defi_category(self):
        """Test defi category contains defi assets."""
        defi = CATEGORIES.get("defi", [])
        assert "UNI" in defi
        assert "AAVE" in defi

    def test_meme_category(self):
        """Test meme category contains meme assets."""
        meme = CATEGORIES.get("meme", [])
        assert "DOGE" in meme
        assert "SHIB" in meme

    def test_gaming_category(self):
        """Test gaming category contains gaming assets."""
        gaming = CATEGORIES.get("gaming", [])
        assert "AXS" in gaming
        assert "SAND" in gaming

    def test_stablecoin_category(self):
        """Test stablecoin category contains stablecoins."""
        stable = CATEGORIES.get("stablecoin", [])
        assert "USDT" in stable
        assert "USDC" in stable


class TestMarketCapTiers:
    """Test MARKET_CAP_TIERS dictionary."""

    def test_large_cap(self):
        """Test large cap tier contains top 10 assets."""
        large_cap = MARKET_CAP_TIERS.get("large_cap", [])
        assert "BTC" in large_cap
        assert "ETH" in large_cap
        # All should have rank <= 10
        for symbol in large_cap:
            assert ASSET_UNIVERSE[symbol].market_cap_rank <= 10

    def test_mid_cap(self):
        """Test mid cap tier contains rank 11-30 assets."""
        mid_cap = MARKET_CAP_TIERS.get("mid_cap", [])
        for symbol in mid_cap:
            rank = ASSET_UNIVERSE[symbol].market_cap_rank
            assert 10 < rank <= 30

    def test_small_cap(self):
        """Test small cap tier contains rank > 30 assets."""
        small_cap = MARKET_CAP_TIERS.get("small_cap", [])
        for symbol in small_cap:
            assert ASSET_UNIVERSE[symbol].market_cap_rank > 30


class TestGetAsset:
    """Test get_asset function."""

    def test_get_existing_asset(self):
        """Test getting existing asset."""
        asset = get_asset("BTC")
        assert asset is not None
        assert asset.symbol == "BTC/USDT"

    def test_get_missing_asset(self):
        """Test getting non-existent asset."""
        asset = get_asset("NONEXISTENT")
        assert asset is None


class TestGetAssetsByCategory:
    """Test get_assets_by_category function."""

    def test_get_layer1_assets(self):
        """Test getting layer1 assets."""
        assets = get_assets_by_category("layer1")
        assert len(assets) > 0
        for asset in assets:
            assert asset.is_layer1 is True

    def test_get_defi_assets(self):
        """Test getting defi assets."""
        assets = get_assets_by_category("defi")
        assert len(assets) > 0
        for asset in assets:
            assert asset.is_defi is True

    def test_get_invalid_category(self):
        """Test getting assets for invalid category."""
        assets = get_assets_by_category("invalid")
        assert assets == []


class TestGetAllSymbols:
    """Test get_all_symbols function."""

    def test_returns_symbols(self):
        """Test that symbols are returned."""
        symbols = get_all_symbols()
        assert len(symbols) > 0
        assert "BTC/USDT" in symbols
        assert "ETH/USDT" in symbols

    def test_all_symbols_valid(self):
        """Test that all returned symbols are valid."""
        symbols = get_all_symbols()
        for symbol in symbols:
            assert "/" in symbol  # All symbols should have format XXX/YYY


class TestGetAllCoinGeckoIds:
    """Test get_all_coingecko_ids function."""

    def test_returns_ids(self):
        """Test that CoinGecko IDs are returned."""
        ids = get_all_coingecko_ids()
        assert len(ids) > 0
        assert "bitcoin" in ids
        assert "ethereum" in ids


class TestGetWatchlistSymbols:
    """Test get_watchlist_symbols function."""

    def test_returns_20_symbols(self):
        """Test that watchlist returns top 20 symbols."""
        symbols = get_watchlist_symbols()
        assert len(symbols) == 20

    def test_returns_top_by_market_cap(self):
        """Test that watchlist returns assets sorted by market cap."""
        symbols = get_watchlist_symbols()
        # First symbol should be BTC (rank 1)
        first_asset = None
        for asset in ASSET_UNIVERSE.values():
            if asset.symbol == symbols[0]:
                first_asset = asset
                break
        assert first_asset is not None
        assert first_asset.market_cap_rank == 1

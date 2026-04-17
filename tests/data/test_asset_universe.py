"""Tests for data/asset_universe.py."""
import pytest
from data.asset_universe import (
    Asset, ASSET_UNIVERSE, CATEGORIES, MARKET_CAP_TIERS,
    SWARM_HIGH_SIGNAL, SWARM_ARB_ELIGIBLE, SWARM_PERP_ENABLED, SWARM_TIER1,
    get_asset, get_assets_by_category, get_all_symbols, get_all_coingecko_ids,
    get_watchlist_symbols, get_top_50, get_swarm_eligible, get_arb_candidates,
    get_perp_universe,
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

    def test_swarm_metric_defaults(self):
        """New swarm metric fields default correctly."""
        asset = Asset("X/USDT", "X Token", "Layer1", "x-token", 99)
        assert asset.liquidity_tier == 3
        assert asset.has_perp is False
        assert asset.signal_quality == "medium"
        assert asset.arb_eligible is False

    def test_swarm_metric_tier1(self):
        """BTC should be tier-1 with high signal and arb-eligible."""
        btc = ASSET_UNIVERSE["BTC"]
        assert btc.liquidity_tier == 1
        assert btc.has_perp is True
        assert btc.signal_quality == "high"
        assert btc.arb_eligible is True


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
        """Test Layer 2 assets are marked correctly (POL replaced MATIC)."""
        pol = ASSET_UNIVERSE.get("POL")
        assert pol is not None
        assert pol.is_layer2 is True
        assert pol.category == "Layer2"
        assert "MATIC" not in ASSET_UNIVERSE, "MATIC was renamed to POL"


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
        """Test stable category contains stablecoins (key renamed stablecoin->stable)."""
        stable = CATEGORIES.get("stable", [])
        assert "USDT" in stable
        assert "USDC" in stable
        assert CATEGORIES.get("stablecoin") is None, "old key 'stablecoin' should not exist"


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
        """Test small cap tier contains rank 31-50 assets (top-50 enforced)."""
        small_cap = MARKET_CAP_TIERS.get("small_cap", [])
        for symbol in small_cap:
            rank = ASSET_UNIVERSE[symbol].market_cap_rank
            assert 30 < rank <= 50, f"{symbol} rank {rank} out of small_cap bounds"


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


class TestSwarmViews:
    """Test swarm-agent specific views and helpers."""

    def test_top_50_returns_sorted_base_assets(self):
        """get_top_50() returns sorted base assets with no perp aliases."""
        top = get_top_50()
        assert len(top) > 0
        for i in range(len(top) - 1):
            assert top[i].market_cap_rank <= top[i + 1].market_cap_rank
        for a in top:
            assert a.market_cap_rank <= 50
            assert ":" not in a.symbol  # no perp aliases

    def test_get_swarm_eligible_signal_quality(self):
        """get_swarm_eligible returns only high/medium signal assets."""
        eligible = get_swarm_eligible()
        for a in eligible:
            assert a.signal_quality in ("high", "medium")

    def test_get_arb_candidates(self):
        """get_arb_candidates returns only arb_eligible assets."""
        candidates = get_arb_candidates()
        assert len(candidates) > 0
        for a in candidates:
            assert a.arb_eligible is True
        assert any(a.symbol == "BTC/USDT" for a in candidates)

    def test_get_perp_universe(self):
        """get_perp_universe returns base assets with has_perp=True."""
        perps = get_perp_universe()
        assert len(perps) > 0
        for a in perps:
            assert a.has_perp is True
            assert ":" not in a.symbol  # no perp alias entries

    def test_swarm_module_level_views(self):
        """Module-level swarm views are non-empty and consistent."""
        assert len(SWARM_HIGH_SIGNAL) > 0
        assert len(SWARM_ARB_ELIGIBLE) > 0
        assert len(SWARM_PERP_ENABLED) > 0
        assert len(SWARM_TIER1) > 0
        for key in SWARM_TIER1:
            assert ASSET_UNIVERSE[key].liquidity_tier == 1
        for key in SWARM_ARB_ELIGIBLE:
            assert ASSET_UNIVERSE[key].arb_eligible is True

    def test_top_50_enforcement(self):
        """No asset in ASSET_UNIVERSE has market_cap_rank > 50 (base assets)."""
        for key, asset in ASSET_UNIVERSE.items():
            if ":" not in asset.symbol and asset.category != "Stable":
                assert asset.market_cap_rank <= 50, (
                    f"{key} has rank {asset.market_cap_rank} > 50"
                )

    def test_swarm_eligible_no_perp_aliases(self):
        """get_swarm_eligible() must never return perp-alias Assets."""
        for a in get_swarm_eligible():
            assert ":" not in a.symbol, f"Perp alias leaked: {a.symbol!r}"

    def test_arb_candidates_no_perp_aliases(self):
        """get_arb_candidates() must never return perp-alias Assets."""
        for a in get_arb_candidates():
            assert ":" not in a.symbol, f"Perp alias leaked: {a.symbol!r}"

    def test_swarm_views_no_perp_keys(self):
        """Module-level SWARM_* key lists must not contain '-PERP' or 'BNBUS'."""
        for view_name, view in [
            ("SWARM_HIGH_SIGNAL", SWARM_HIGH_SIGNAL),
            ("SWARM_ARB_ELIGIBLE", SWARM_ARB_ELIGIBLE),
            ("SWARM_PERP_ENABLED", SWARM_PERP_ENABLED),
            ("SWARM_TIER1", SWARM_TIER1),
        ]:
            for key in view:
                assert "-PERP" not in key, f"{view_name} contains perp alias key {key!r}"
                assert key != "BNBUS", f"{view_name} contains BNBUS alias"

    def test_market_cap_tiers_no_perp_keys(self):
        """MARKET_CAP_TIERS must not contain '-PERP' keys or 'BNBUS'."""
        for tier, keys in MARKET_CAP_TIERS.items():
            for key in keys:
                assert "-PERP" not in key, f"{tier} contains perp alias {key!r}"
                assert key != "BNBUS", f"{tier} contains BNBUS alias"

    def test_categories_no_perp_keys(self):
        """CATEGORIES must not contain '-PERP' keys or 'BNBUS'."""
        for cat, keys in CATEGORIES.items():
            for key in keys:
                assert "-PERP" not in key, f"CATEGORIES[{cat!r}] contains perp alias {key!r}"
                assert key != "BNBUS", f"CATEGORIES[{cat!r}] contains BNBUS alias"

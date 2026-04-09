"""
Asset Universe - Comprehensive cryptocurrency coverage
Bloomberg Terminal equivalent asset list with real-time data
"""

from typing import Dict, List
from dataclasses import dataclass

@dataclass
class Asset:
    """Asset definition with metadata."""
    symbol: str
    name: str
    category: str
    coingecko_id: str
    market_cap_rank: int
    is_defi: bool = False
    is_layer1: bool = False
    is_layer2: bool = False


ASSET_UNIVERSE: Dict[str, Asset] = {
    # ── Kalshi-path assets (bare symbol, USD-denominated) ─────────────────
    # PATCH-1 / EGG-1: The five Kalshi crypto assets are keyed with bare
    # symbols ("BTC", not "BTC/USDT") so that the live_price_feed Kalshi
    # spot cache and asset_universe agree on the canonical key.
    'BTC': Asset('BTC', 'Bitcoin', 'Layer1', 'bitcoin', 1, is_layer1=True),
    'ETH': Asset('ETH', 'Ethereum', 'Layer1', 'ethereum', 2, is_layer1=True),
    'SOL': Asset('SOL', 'Solana', 'Layer1', 'solana', 5, is_layer1=True),
    'XRP': Asset('XRP', 'Ripple', 'Layer1', 'ripple', 6, is_layer1=True),
    'DOGE': Asset('DOGE', 'Dogecoin', 'Meme', 'dogecoin', 8, is_layer1=True),

    # ── Perp / USDT-quoted entries (non-Kalshi uses) ────────────────────
    'BTC-PERP': Asset('BTC/USDT:USDT', 'Bitcoin Perp', 'Perp', 'bitcoin', 1, is_layer1=True),
    'ETH-PERP': Asset('ETH/USDT:USDT', 'Ethereum Perp', 'Perp', 'ethereum', 2, is_layer1=True),
    'SOL-PERP': Asset('SOL/USDT:USDT', 'Solana Perp', 'Perp', 'solana', 5, is_layer1=True),

    # ── Other Layer 1 assets (not on Kalshi) ────────────────────────────
    'BNB': Asset('BNB/USDT', 'BNB', 'Layer1', 'binancecoin', 4, is_layer1=True),
    'BNBUS': Asset('BNB/USD', 'BNB (US Spot)', 'Layer1', 'binancecoin', 4, is_layer1=True),
    'ADA': Asset('ADA/USDT', 'Cardano', 'Layer1', 'cardano', 9, is_layer1=True),
    'AVAX': Asset('AVAX/USDT', 'Avalanche', 'Layer1', 'avalanche-2', 10, is_layer1=True),
    'DOT': Asset('DOT/USDT', 'Polkadot', 'Layer1', 'polkadot', 13, is_layer1=True),
    'ATOM': Asset('ATOM/USDT', 'Cosmos', 'Layer1', 'cosmos', 18, is_layer1=True),
    'NEAR': Asset('NEAR/USDT', 'NEAR Protocol', 'Layer1', 'near', 20, is_layer1=True),
    'APT': Asset('APT/USDT', 'Aptos', 'Layer1', 'aptos', 22, is_layer1=True),
    'SUI': Asset('SUI/USDT', 'Sui', 'Layer1', 'sui', 24, is_layer1=True),
    'INJ': Asset('INJ/USDT', 'Injective', 'Layer1', 'injective-protocol', 28, is_layer1=True),
    'SEI': Asset('SEI/USDT', 'Sei', 'Layer1', 'sei-network', 32, is_layer1=True),
    'TIA': Asset('TIA/USDT', 'Celestia', 'Layer1', 'celestia', 26, is_layer1=True),
    'LTC': Asset('LTC/USDT', 'Litecoin', 'Layer1', 'litecoin', 19, is_layer1=True),
    'BCH': Asset('BCH/USDT', 'Bitcoin Cash', 'Layer1', 'bitcoin-cash', 21, is_layer1=True),
    'ALGO': Asset('ALGO/USDT', 'Algorand', 'Layer1', 'algorand', 33, is_layer1=True),
    'VET': Asset('VET/USDT', 'VeChain', 'Layer1', 'vechain', 37, is_layer1=True),
    'ICP': Asset('ICP/USDT', 'Internet Computer', 'Layer1', 'internet-computer', 39, is_layer1=True),

    # Layer 2
    'POL': Asset('POL/USDT', 'Polygon', 'Layer2', 'polygon-ecosystem-token', 15, is_layer2=True),
    'OP': Asset('OP/USDT', 'Optimism', 'Layer2', 'optimism', 27, is_layer2=True),
    'ARB': Asset('ARB/USDT', 'Arbitrum', 'Layer2', 'arbitrum', 29, is_layer2=True),
    'STRK': Asset('STRK/USDT', 'Starknet', 'Layer2', 'starknet', 41, is_layer2=True),
    'BASE': Asset('BASE/USDT', 'Base', 'Layer2', 'base', 65, is_layer2=True),

    # Perp-focused venues (extra markets)
    'BTC-OKX-PERP': Asset('BTC/USDT:USDT', 'BTC Perp (OKX)', 'Perp', 'bitcoin', 1, is_layer1=True),
    'ETH-OKX-PERP': Asset('ETH/USDT:USDT', 'ETH Perp (OKX)', 'Perp', 'ethereum', 2, is_layer1=True),
    'SOL-OKX-PERP': Asset('SOL/USDT:USDT', 'SOL Perp (OKX)', 'Perp', 'solana', 5, is_layer1=True),
    'DOGE-OKX-PERP': Asset('DOGE/USDT:USDT', 'DOGE Perp (OKX)', 'Perp', 'dogecoin', 8),

    # DeFi Protocols
    'UNI': Asset('UNI/USDT', 'Uniswap', 'DeFi', 'uniswap', 16, is_defi=True),
    'LINK': Asset('LINK/USDT', 'Chainlink', 'DeFi', 'chainlink', 14, is_defi=True),
    'AAVE': Asset('AAVE/USDT', 'Aave', 'DeFi', 'aave', 35, is_defi=True),
    'MKR': Asset('MKR/USDT', 'Maker', 'DeFi', 'maker', 40, is_defi=True),
    'CRV': Asset('CRV/USDT', 'Curve', 'DeFi', 'curve-dao-token', 45, is_defi=True),
    'COMP': Asset('COMP/USDT', 'Compound', 'DeFi', 'compound-governance-token', 50, is_defi=True),
    'SNX': Asset('SNX/USDT', 'Synthetix', 'DeFi', 'synthetix-network-token', 55, is_defi=True),
    'SUSHI': Asset('SUSHI/USDT', 'SushiSwap', 'DeFi', 'sushi', 60, is_defi=True),
    'GMX': Asset('GMX/USDT', 'GMX', 'DeFi', 'gmx', 43, is_defi=True),
    'DYDX': Asset('DYDX/USDT', 'dYdX', 'DeFi', 'dydx', 34, is_defi=True),

    # Meme Coins (non-Kalshi)
    'SHIB': Asset('SHIB/USDT', 'Shiba Inu', 'Meme', 'shiba-inu', 11),
    'PEPE': Asset('PEPE/USDT', 'Pepe', 'Meme', 'pepe', 25),
    'FLOKI': Asset('FLOKI/USDT', 'Floki', 'Meme', 'floki', 48),
    'BONK': Asset('BONK/USDT', 'Bonk', 'Meme', 'bonk', 52),

    # Infrastructure / Storage / Data
    'FIL': Asset('FIL/USDT', 'Filecoin', 'Storage', 'filecoin', 30),
    'AR': Asset('AR/USDT', 'Arweave', 'Storage', 'arweave', 42),
    'GRT': Asset('GRT/USDT', 'The Graph', 'Indexing', 'the-graph', 44),
    'RNDR': Asset('RNDR/USDT', 'Render', 'Computing', 'render-token', 38),
    'TIA-PERP': Asset('TIA/USDT:USDT', 'Celestia Perp', 'Perp', 'celestia', 26, is_layer1=True),

    # Gaming & Metaverse
    'AXS': Asset('AXS/USDT', 'Axie Infinity', 'Gaming', 'axie-infinity', 46),
    'SAND': Asset('SAND/USDT', 'The Sandbox', 'Metaverse', 'the-sandbox', 49),
    'MANA': Asset('MANA/USDT', 'Decentraland', 'Metaverse', 'decentraland', 51),
    'IMX': Asset('IMX/USDT', 'Immutable X', 'Gaming', 'immutable-x', 47),

    # AI & Data
    'FET': Asset('FET/USDT', 'Fetch.ai', 'AI', 'fetch-ai', 54),
    'OCEAN': Asset('OCEAN/USDT', 'Ocean Protocol', 'Data', 'ocean-protocol', 58),
    'AGIX': Asset('AGIX/USDT', 'SingularityNET', 'AI', 'singularitynet', 62),
    'TURBO': Asset('TURBO/USDT', 'Turbo', 'AI', 'turbo', 66),

    # Privacy
    'XMR': Asset('XMR/USDT', 'Monero', 'Privacy', 'monero', 36),
    'ZEC': Asset('ZEC/USDT', 'Zcash', 'Privacy', 'zcash', 64),

    # Stablecoins (for reference / cross-venue checks)
    'USDT': Asset('USDT/USD', 'Tether', 'Stablecoin', 'tether', 3),
    'USDC': Asset('USDC/USD', 'USD Coin', 'Stablecoin', 'usd-coin', 7),
    'DAI': Asset('DAI/USD', 'Dai', 'Stablecoin', 'dai', 17),

    # Emerging assets
    'PYTH': Asset('PYTH/USDT', 'Pyth Network', 'Oracle', 'pyth-network', 59),
    'JTO': Asset('JTO/USDT', 'Jito', 'DeFi', 'jito-governance-token', 63),
    'BEAM': Asset('BEAM/USDT', 'Beam', 'Gaming', 'beam', 67),
    'TIA-SPOT': Asset('TIA/USD', 'Celestia (USD)', 'Layer1', 'celestia', 26, is_layer1=True),
}


# Category groupings for filtering
CATEGORIES = {
    'layer1': [k for k, v in ASSET_UNIVERSE.items() if v.is_layer1],
    'layer2': [k for k, v in ASSET_UNIVERSE.items() if v.is_layer2],
    'defi': [k for k, v in ASSET_UNIVERSE.items() if v.is_defi],
    'meme': [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Meme'],
    'gaming': [k for k, v in ASSET_UNIVERSE.items() if v.category in ['Gaming', 'Metaverse']],
    'ai': [k for k, v in ASSET_UNIVERSE.items() if v.category in ['AI', 'Data']],
    'privacy': [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Privacy'],
    'infrastructure': [k for k, v in ASSET_UNIVERSE.items() if v.category in ['Storage', 'Indexing', 'Computing']],
    'stablecoin': [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Stablecoin'],
}


# Market cap tiers
MARKET_CAP_TIERS = {
    'large_cap': [k for k, v in ASSET_UNIVERSE.items() if v.market_cap_rank <= 10],
    'mid_cap': [k for k, v in ASSET_UNIVERSE.items() if 10 < v.market_cap_rank <= 30],
    'small_cap': [k for k, v in ASSET_UNIVERSE.items() if v.market_cap_rank > 30],
}


def get_asset(symbol: str) -> Asset:
    """Get asset by symbol."""
    return ASSET_UNIVERSE.get(symbol)


def get_assets_by_category(category: str) -> List[Asset]:
    """Get all assets in a category."""
    symbols = CATEGORIES.get(category, [])
    return [ASSET_UNIVERSE[s] for s in symbols]


def get_all_symbols() -> List[str]:
    """Get all trading symbols."""
    return [asset.symbol for asset in ASSET_UNIVERSE.values()]


def get_all_coingecko_ids() -> List[str]:
    """Get all CoinGecko IDs for batch API calls."""
    return [asset.coingecko_id for asset in ASSET_UNIVERSE.values()]


def get_watchlist_symbols() -> List[str]:
    """Get default watchlist (top 20 by market cap)."""
    sorted_assets = sorted(ASSET_UNIVERSE.items(), key=lambda x: x[1].market_cap_rank)
    return [asset[1].symbol for asset in sorted_assets[:20]]

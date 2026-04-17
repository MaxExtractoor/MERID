"""
Asset Universe — Top-50 cryptocurrency coverage by market-cap rank.

Metrics annotated for swarm/agent consumption:
  liquidity_tier   1 (deepest) -> 3 (shallowest)  drives position sizing
  has_perp         perpetual swap available for hedging / funding-rate signals
  signal_quality   'high' | 'medium' | 'low'  ML forecaster confidence floor
  arb_eligible     cross-venue spread opportunity exists
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class Asset:
    """Asset definition with metadata and swarm-agent metrics."""
    symbol: str
    name: str
    category: str
    coingecko_id: str
    market_cap_rank: int
    is_defi: bool = False
    is_layer1: bool = False
    is_layer2: bool = False
    liquidity_tier: int = 3          # 1=highest (BTC/ETH), 2=mid, 3=lower
    has_perp: bool = False           # perpetual swap available
    signal_quality: str = 'medium'   # 'high' | 'medium' | 'low'
    arb_eligible: bool = False       # viable cross-venue arbitrage


ASSET_UNIVERSE: Dict[str, Asset] = {
    # ── Layer 1: Large Cap (rank 1-10) ────────────────────────────────────────
    'BTC':      Asset('BTC/USDT',      'Bitcoin',          'Layer1', 'bitcoin',                1,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'BTC-PERP': Asset('BTC/USDT:USDT', 'Bitcoin Perp',     'Perp',   'bitcoin',                1,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'ETH':      Asset('ETH/USDT',      'Ethereum',         'Layer1', 'ethereum',               2,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'ETH-PERP': Asset('ETH/USDT:USDT', 'Ethereum Perp',    'Perp',   'ethereum',               2,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'BNB':      Asset('BNB/USDT',      'BNB',              'Layer1', 'binancecoin',            4,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'BNBUS':    Asset('BNB/USD',        'BNB (USD)',        'Layer1', 'binancecoin',            4,  is_layer1=True,  liquidity_tier=1, signal_quality='high'),
    'SOL':      Asset('SOL/USDT',      'Solana',           'Layer1', 'solana',                 5,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'SOL-PERP': Asset('SOL/USDT:USDT', 'Solana Perp',      'Perp',   'solana',                 5,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'XRP':      Asset('XRP/USDT',      'Ripple',           'Layer1', 'ripple',                 6,  is_layer1=True,  liquidity_tier=1, has_perp=True,  signal_quality='high', arb_eligible=True),
    'ADA':      Asset('ADA/USDT',      'Cardano',          'Layer1', 'cardano',                9,  is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'AVAX':     Asset('AVAX/USDT',     'Avalanche',        'Layer1', 'avalanche-2',            10, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    # ── Layer 1: Mid Cap (rank 13-33) ───────────────────────────────────────
    'DOT':      Asset('DOT/USDT',      'Polkadot',         'Layer1', 'polkadot',               13, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'ATOM':     Asset('ATOM/USDT',     'Cosmos',           'Layer1', 'cosmos',                 18, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'LTC':      Asset('LTC/USDT',      'Litecoin',         'Layer1', 'litecoin',               19, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'NEAR':     Asset('NEAR/USDT',     'NEAR Protocol',    'Layer1', 'near',                   20, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'BCH':      Asset('BCH/USDT',      'Bitcoin Cash',     'Layer1', 'bitcoin-cash',           21, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'APT':      Asset('APT/USDT',      'Aptos',            'Layer1', 'aptos',                  22, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'SUI':      Asset('SUI/USDT',      'Sui',              'Layer1', 'sui',                    24, is_layer1=True,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'TIA':      Asset('TIA/USDT',      'Celestia',         'Layer1', 'celestia',               26, is_layer1=True,  has_perp=True),
    'TIA-PERP': Asset('TIA/USDT:USDT', 'Celestia Perp',   'Perp',   'celestia',               26, is_layer1=True,  has_perp=True),
    'INJ':      Asset('INJ/USDT',      'Injective',        'Layer1', 'injective-protocol',     28, is_layer1=True,  has_perp=True),
    'SEI':      Asset('SEI/USDT',      'Sei',              'Layer1', 'sei-network',            32, is_layer1=True,  has_perp=True),
    'ALGO':     Asset('ALGO/USDT',     'Algorand',         'Layer1', 'algorand',               33, is_layer1=True,  signal_quality='low'),
    'VET':      Asset('VET/USDT',      'VeChain',          'Layer1', 'vechain',                37, is_layer1=True,  signal_quality='low'),
    'ICP':      Asset('ICP/USDT',      'Internet Computer','Layer1', 'internet-computer',      39, is_layer1=True,  signal_quality='low'),
    # ── Layer 2 ───────────────────────────────────────────────────────────
    'POL':      Asset('POL/USDT',      'Polygon',          'Layer2', 'polygon-ecosystem-token',15, is_layer2=True,  liquidity_tier=2, arb_eligible=True),
    'OP':       Asset('OP/USDT',       'Optimism',         'Layer2', 'optimism',               27, is_layer2=True,  has_perp=True,  arb_eligible=True),
    'ARB':      Asset('ARB/USDT',      'Arbitrum',         'Layer2', 'arbitrum',               29, is_layer2=True,  has_perp=True,  arb_eligible=True),
    'STRK':     Asset('STRK/USDT',     'Starknet',         'Layer2', 'starknet',               41, is_layer2=True,  signal_quality='low'),
    # ── Perp aliases (top-50 underlyings only) ──────────────────────────────────
    'DOGE-PERP':Asset('DOGE/USDT:USDT','Dogecoin Perp',    'Perp',   'dogecoin',               8,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    # ── DeFi ─────────────────────────────────────────────────────────────
    'LINK':     Asset('LINK/USDT',     'Chainlink',        'DeFi',   'chainlink',              14, is_defi=True,    liquidity_tier=2, has_perp=True,  signal_quality='high', arb_eligible=True),
    'UNI':      Asset('UNI/USDT',      'Uniswap',          'DeFi',   'uniswap',                16, is_defi=True,    liquidity_tier=2, has_perp=True,  signal_quality='high', arb_eligible=True),
    'DYDX':     Asset('DYDX/USDT',     'dYdX',             'DeFi',   'dydx',                   34, is_defi=True,    has_perp=True,  arb_eligible=True),
    'AAVE':     Asset('AAVE/USDT',     'Aave',             'DeFi',   'aave',                   35, is_defi=True,    has_perp=True,  signal_quality='high', arb_eligible=True),
    'XMR':      Asset('XMR/USDT',      'Monero',           'Privacy','monero',                 36, signal_quality='low'),
    'RNDR':     Asset('RNDR/USDT',     'Render',           'Compute','render-token',            38),
    'MKR':      Asset('MKR/USDT',      'Maker',            'DeFi',   'maker',                  40, is_defi=True),
    'AR':       Asset('AR/USDT',       'Arweave',          'Storage','arweave',                 42, signal_quality='low'),
    'GMX':      Asset('GMX/USDT',      'GMX',              'DeFi',   'gmx',                    43, is_defi=True,    arb_eligible=True),
    'GRT':      Asset('GRT/USDT',      'The Graph',        'Indexing','the-graph',              44, signal_quality='low'),
    'CRV':      Asset('CRV/USDT',      'Curve',            'DeFi',   'curve-dao-token',        45, is_defi=True,    has_perp=True),
    'AXS':      Asset('AXS/USDT',      'Axie Infinity',    'Gaming', 'axie-infinity',           46, signal_quality='low'),
    'IMX':      Asset('IMX/USDT',      'Immutable X',      'Gaming', 'immutable-x',             47, signal_quality='low'),
    'FIL':      Asset('FIL/USDT',      'Filecoin',         'Storage','filecoin',                30, signal_quality='low'),
    # ── Meme ──────────────────────────────────────────────────────────────
    'DOGE':     Asset('DOGE/USDT',     'Dogecoin',         'Meme',   'dogecoin',               8,  liquidity_tier=2, has_perp=True,  arb_eligible=True),
    'SHIB':     Asset('SHIB/USDT',     'Shiba Inu',        'Meme',   'shiba-inu',              11, liquidity_tier=2, has_perp=True),
    'PEPE':     Asset('PEPE/USDT',     'Pepe',             'Meme',   'pepe',                   25, has_perp=True),
    'FLOKI':    Asset('FLOKI/USDT',    'Floki',            'Meme',   'floki',                  48, signal_quality='low'),
    'SAND':     Asset('SAND/USDT',     'The Sandbox',      'Metaverse','the-sandbox',           49, signal_quality='low'),
    'COMP':     Asset('COMP/USDT',     'Compound',         'DeFi',   'compound-governance-token',50, is_defi=True),
    # ── Stablecoins (cross-venue reference + depegging signals) ───────────────
    'USDT':     Asset('USDT/USD',      'Tether',           'Stable', 'tether',                 3,  liquidity_tier=1, signal_quality='high'),
    'USDC':     Asset('USDC/USD',      'USD Coin',         'Stable', 'usd-coin',               7,  liquidity_tier=1, signal_quality='high'),
    'DAI':      Asset('DAI/USD',       'Dai',              'Stable', 'dai',                    17, liquidity_tier=2, signal_quality='high'),
}


_BASE_ONLY = lambda k: '-PERP' not in k and k != 'BNBUS'  # noqa: E731

# Category groupings for filtering — base assets only (no perp aliases)
CATEGORIES = {
    'layer1':         [k for k, v in ASSET_UNIVERSE.items() if v.is_layer1 and _BASE_ONLY(k)],
    'layer2':         [k for k, v in ASSET_UNIVERSE.items() if v.is_layer2 and _BASE_ONLY(k)],
    'defi':           [k for k, v in ASSET_UNIVERSE.items() if v.is_defi and _BASE_ONLY(k)],
    'meme':           [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Meme' and _BASE_ONLY(k)],
    'gaming':         [k for k, v in ASSET_UNIVERSE.items() if v.category in ('Gaming', 'Metaverse') and _BASE_ONLY(k)],
    'privacy':        [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Privacy' and _BASE_ONLY(k)],
    'infrastructure': [k for k, v in ASSET_UNIVERSE.items() if v.category in ('Storage', 'Indexing', 'Compute') and _BASE_ONLY(k)],
    'stable':         [k for k, v in ASSET_UNIVERSE.items() if v.category == 'Stable' and _BASE_ONLY(k)],
}

# Market cap tiers — base assets only, all entries are rank <= 50
MARKET_CAP_TIERS = {
    'large_cap': [k for k, v in ASSET_UNIVERSE.items() if v.market_cap_rank <= 10 and _BASE_ONLY(k)],
    'mid_cap':   [k for k, v in ASSET_UNIVERSE.items() if 10 < v.market_cap_rank <= 30 and _BASE_ONLY(k)],
    'small_cap': [k for k, v in ASSET_UNIVERSE.items() if 30 < v.market_cap_rank <= 50 and _BASE_ONLY(k)],
}

# Swarm-agent views — base assets only (perp aliases and BNBUS excluded)
SWARM_HIGH_SIGNAL  = [k for k, v in ASSET_UNIVERSE.items() if v.signal_quality == 'high'  and _BASE_ONLY(k)]
SWARM_ARB_ELIGIBLE = [k for k, v in ASSET_UNIVERSE.items() if v.arb_eligible               and _BASE_ONLY(k)]
SWARM_PERP_ENABLED = [k for k, v in ASSET_UNIVERSE.items() if v.has_perp and 'PERP' not in k and k != 'BNBUS']
SWARM_TIER1        = [k for k, v in ASSET_UNIVERSE.items() if v.liquidity_tier == 1         and _BASE_ONLY(k)]


def get_asset(symbol: str) -> Asset:
    """Get asset by symbol."""
    return ASSET_UNIVERSE.get(symbol)


def get_assets_by_category(category: str) -> List[Asset]:
    """Get all assets in a category."""
    return [ASSET_UNIVERSE[s] for s in CATEGORIES.get(category, [])]


def get_all_symbols() -> List[str]:
    """Get all trading symbols."""
    return [v.symbol for v in ASSET_UNIVERSE.values()]


def get_all_coingecko_ids() -> List[str]:
    """Get all unique CoinGecko IDs for batch API calls."""
    seen: set = set()
    ids = []
    for v in ASSET_UNIVERSE.values():
        if v.coingecko_id not in seen:
            seen.add(v.coingecko_id)
            ids.append(v.coingecko_id)
    return ids


def get_watchlist_symbols() -> List[str]:
    """Top-20 base assets by market cap rank (no perp aliases)."""
    base = [(k, v) for k, v in ASSET_UNIVERSE.items() if 'PERP' not in k and k != 'BNBUS']
    return [v.symbol for _, v in sorted(base, key=lambda x: x[1].market_cap_rank)[:20]]


def get_top_50() -> List[Asset]:
    """All base assets ranked 1-50, no perp/alias duplicates, sorted by rank."""
    _ALIAS = {'PERP', 'BNBUS'}
    base = [(k, v) for k, v in ASSET_UNIVERSE.items()
            if not any(tag in k for tag in _ALIAS)]
    return [v for _, v in sorted(base, key=lambda x: x[1].market_cap_rank)]


def get_swarm_eligible() -> List[Asset]:
    """Base assets with signal_quality high/medium — usable by ML forecasters."""
    return [v for k, v in ASSET_UNIVERSE.items()
            if v.signal_quality in ('high', 'medium') and _BASE_ONLY(k)]


def get_arb_candidates() -> List[Asset]:
    """Base assets eligible for cross-venue arbitrage strategies."""
    return [v for k, v in ASSET_UNIVERSE.items() if v.arb_eligible and _BASE_ONLY(k)]


def get_perp_universe() -> List[Asset]:
    """Base assets that have a perpetual swap (for funding-rate / hedge strategies)."""
    return [v for k, v in ASSET_UNIVERSE.items() if v.has_perp and 'PERP' not in k]

"""
Market Heatmap Data Builder for MERID.

Provides a clean data pipeline from market data sources (dxFeed adapter,
paper trading engine) to heatmap/radar-ready snapshots.

Usage:
    from core.market_heatmap import build_heatmap_snapshot, build_radar_snapshot
    heatmap = build_heatmap_snapshot(quotes)
    radar = build_radar_snapshot(quotes, positions)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _build_sector_map() -> Dict[str, str]:
    try:
        from data.asset_universe import ASSET_UNIVERSE
        _cat_to_sector = {
            "Layer1": "Crypto L1", "Layer2": "Crypto L2",
            "DeFi": "DeFi", "Meme": "Meme", "Metaverse": "Gaming/Meta",
            "Gaming": "Gaming/Meta", "Storage": "Infrastructure",
            "Indexing": "Infrastructure", "Compute": "Infrastructure",
            "Privacy": "Privacy",
        }
        result: Dict[str, str] = {}
        for key, asset in ASSET_UNIVERSE.items():
            if ":" in asset.symbol or asset.category == "Stable" or "-PERP" in key:
                continue
            sector = _cat_to_sector.get(asset.category, "Other")
            if asset.market_cap_rank <= 3 and asset.category == "Layer1":
                sector = "Crypto Major"
            result[key] = sector
        return result
    except Exception:
        from merid.constants import CRYPTO_15M_ASSETS
        return {asset: "Crypto Major" for asset in CRYPTO_15M_ASSETS}


def _build_category_symbols() -> Dict[str, List[str]]:
    try:
        from data.asset_universe import ASSET_UNIVERSE, SWARM_TIER1, SWARM_ARB_ELIGIBLE, CATEGORIES
        return {
            "core": [k for k in SWARM_TIER1 if ":" not in ASSET_UNIVERSE[k].symbol],
            "onchain": CATEGORIES.get("layer2", []),
            "perps": [k for k, v in ASSET_UNIVERSE.items()
                      if v.has_perp and v.liquidity_tier <= 2 and ":" not in v.symbol
                      and "-PERP" not in k],
            "defi": CATEGORIES.get("defi", []),
            "meme": CATEGORIES.get("meme", []),
        }
    except Exception:
        from merid.constants import CRYPTO_15M_ASSETS
        return {"core": list(CRYPTO_15M_ASSETS)}


SECTOR_MAP: Dict[str, str] = _build_sector_map()
CATEGORY_SYMBOLS: Dict[str, List[str]] = _build_category_symbols()


def build_heatmap_snapshot(
    quotes: List[Dict[str, Any]],
    positions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build hierarchical sector → instrument heatmap data.

    Args:
        quotes: list of {symbol, price, change_pct, ...} from market data
        positions: optional list of {symbol, pnl, exposure, side} from paper engine

    Returns:
        dict of sector → list of instrument dicts with pnl, exposure, risk_pct
    """
    # Index positions by symbol
    pos_map: Dict[str, Dict[str, Any]] = {}
    for p in (positions or []):
        sym = p.get("symbol", "")
        if sym in pos_map:
            pos_map[sym]["pnl"] += p.get("pnl", 0)
            pos_map[sym]["exposure"] += p.get("exposure", 0)
        else:
            pos_map[sym] = {
                "pnl": p.get("pnl", 0),
                "exposure": p.get("exposure", 0),
                "side": p.get("side", "long"),
            }

    sectors: Dict[str, List[Dict[str, Any]]] = {}

    for q in quotes:
        symbol = q.get("symbol", "").replace("/USDT", "").replace("USDT", "")
        sector = SECTOR_MAP.get(symbol, "Other")
        pos = pos_map.get(symbol, {})

        entry = {
            "symbol": symbol,
            "pnl": round(pos.get("pnl", 0), 2),
            "exposure": round(pos.get("exposure", 0), 2),
            "side": pos.get("side", "long"),
            "change_pct": round(q.get("change_pct", q.get("change_pct_24h", 0)), 2),
            "risk_pct": 0,
        }

        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append(entry)

    return sectors


def build_radar_snapshot(
    quotes: List[Dict[str, Any]],
    positions: Optional[List[Dict[str, Any]]] = None,
    category: str = "all",
) -> List[Dict[str, Any]]:
    """
    Build instrument radar/scanner data.

    Args:
        quotes: list of {symbol, price, change_24h, volume_24h, ...}
        positions: optional list of {symbol, pnl, exposure}
        category: filter category (all, core, onchain, perps, defi, meme)

    Returns:
        list of instrument dicts ready for the radar table
    """
    # Determine target symbols
    if category == "all":
        target_symbols = set()
        for syms in CATEGORY_SYMBOLS.values():
            target_symbols.update(syms)
    else:
        target_symbols = set(CATEGORY_SYMBOLS.get(category, []))

    # Index positions
    pnl_map: Dict[str, float] = {}
    exp_map: Dict[str, float] = {}
    for p in (positions or []):
        sym = p.get("symbol", "")
        pnl_map[sym] = pnl_map.get(sym, 0) + p.get("pnl", 0)
        exp_map[sym] = exp_map.get(sym, 0) + p.get("exposure", 0)

    # Index quotes by symbol
    quote_map: Dict[str, Dict[str, Any]] = {}
    for q in quotes:
        sym = q.get("symbol", "").replace("/USDT", "").replace("USDT", "")
        quote_map[sym] = q

    instruments = []
    for symbol in sorted(target_symbols):
        q = quote_map.get(symbol, {})
        instruments.append({
            "symbol": symbol,
            "price": q.get("price", 0),
            "change_24h": q.get("change_24h", q.get("change_pct_24h", 0)),
            "volume_24h": q.get("volume_24h", 0),
            "pnl": round(pnl_map.get(symbol, 0), 2),
            "exposure": round(exp_map.get(symbol, 0), 2),
            "signal_strength": 0,
            "sector": SECTOR_MAP.get(symbol, "Other"),
            "category": category if category != "all" else SECTOR_MAP.get(symbol, "Other"),
        })

    return instruments

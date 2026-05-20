"""
Compare Kalshi Trade Logs with Spot Price to Kalshi Contract Data

This script fetches recent Kalshi fills and compares them with spot price
and Kalshi-implied spot data to analyze basis at trade execution time.

Usage:
    python scripts/compare_kalshi_trades_spot.py --hours 24
    python scripts/compare_kalshi_trades_spot.py --since 2026-05-10
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import json

sys.path.insert(0, ".")

import httpx


async def fetch_kalshi_fills(base_url: str = "http://localhost:8011", hours: int = 24) -> List[Dict[str, Any]]:
    """Fetch recent Kalshi fills from the fills ledger API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/api/v1/kalshi/fills",
            params={"since_hours": hours, "limit": 500}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("fills", [])


async def fetch_spot_basis(base_url: str = "http://localhost:8011") -> Dict[str, Any]:
    """Fetch current spot/Kalshi basis data."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url}/api/v1/kalshi/spot-basis")
        response.raise_for_status()
        return response.json()


async def fetch_spot_basis_stats(base_url: str = "http://localhost:8011", window_minutes: int = 60) -> Dict[str, Any]:
    """Fetch rolling spot/Kalshi basis statistics."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/api/v1/kalshi/spot-basis/stats",
            params={"window_minutes": window_minutes}
        )
        response.raise_for_status()
        return response.json()


async def fetch_crypto_spot_kalshi(base_url: str = "http://localhost:8011") -> Dict[str, Any]:
    """Fetch crypto spot vs Kalshi contract prices."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url}/api/v1/crypto/spot-vs-kalshi")
        response.raise_for_status()
        return response.json()


def extract_asset_from_ticker(ticker: str) -> Optional[str]:
    """Extract asset symbol from Kalshi ticker (e.g., 'KXBTC-...' -> 'BTC')."""
    if ticker.startswith("KXBTC"):
        return "BTC"
    elif ticker.startswith("KXETH"):
        return "ETH"
    elif ticker.startswith("KXSOL"):
        return "SOL"
    elif ticker.startswith("KXXRP"):
        return "XRP"
    elif ticker.startswith("KXDOGE"):
        return "DOGE"
    return None


def is_15m_binary(ticker: str) -> bool:
    """Check if ticker is a 15-minute binary option."""
    return "15M" in ticker.upper()


def get_market_timeframe(ticker: str) -> str:
    """Extract timeframe from ticker (e.g., '15M', '1H', '1D')."""
    if "15M" in ticker.upper():
        return "15m"
    elif "1H" in ticker.upper():
        return "1h"
    elif "1D" in ticker.upper():
        return "1d"
    elif "1W" in ticker.upper():
        return "1w"
    return "unknown"


def compare_fills_with_spot(
    fills: List[Dict[str, Any]],
    spot_basis: Dict[str, Any],
    spot_basis_stats: Dict[str, Any],
    crypto_spot_kalshi: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare fills with spot and Kalshi contract data.
    
    For 15m binaries: Probability/edge analysis (contract price vs realized outcome)
    For multi-strike (1H+): Strike vs spot comparison
    """
    
    report = {
        "total_fills": len(fills),
        "by_asset": {},
        "by_timeframe": {"15m": {"count": 0, "fills": []}, "1h+": {"count": 0, "fills": []}},
        "fills_with_spot_data": 0,
        "fills_without_spot_data": 0,
        "15m_binary_stats": {
            "yes_count": 0,
            "no_count": 0,
            "avg_yes_price_cents": 0,
            "avg_no_price_cents": 0,
            "yes_hit_rate": 0.0,  # Will need settlement data
            "no_hit_rate": 0.0,
        },
        "fills": []
    }
    
    assets_data = spot_basis.get("assets", {})
    stats_data = spot_basis_stats.get("assets", {})
    crypto_data = crypto_spot_kalshi.get("assets", {})
    
    for fill in fills:
        ticker = fill.get("ticker", "")
        asset = extract_asset_from_ticker(ticker)
        is_15m = is_15m_binary(ticker)
        timeframe = get_market_timeframe(ticker)
        
        if not asset:
            continue
        
        fill_report = {
            "fill_id": fill.get("fill_id"),
            "ticker": ticker,
            "asset": asset,
            "side": fill.get("side"),
            "quantity": fill.get("quantity"),
            "price_cents": fill.get("price_cents"),
            "executed_at": fill.get("executed_at"),
            "strike_price": fill.get("strike_price"),
            "timeframe": timeframe,
            "is_15m_binary": is_15m,
            # Common fields
            "spot_price": None,
            "implied_spot_mid": None,
            "basis_mid": None,
            "alignment": None,
            # 15m-specific fields
            "contract_probability": None,  # price_cents / 100
            "settlement_outcome": None,  # 0 or 1 (if settled)
            "realized_edge": None,  # settlement_outcome - contract_probability
            # Multi-strike fields
            "spot_vs_contract_delta": None
        }
        
        # Get current spot basis data for this asset
        asset_basis = assets_data.get(asset, {})
        asset_stats = stats_data.get(asset, {})
        asset_crypto = crypto_data.get(asset, {})
        
        if asset_basis:
            fill_report["spot_price"] = asset_basis.get("spot_price")
            fill_report["implied_spot_mid"] = asset_basis.get("implied_spot_mid")
            fill_report["basis_mid"] = asset_basis.get("basis_mid")
            fill_report["alignment"] = asset_basis.get("alignment")
            report["fills_with_spot_data"] += 1
        else:
            report["fills_without_spot_data"] += 1
        
        # 15m binary analysis
        if is_15m:
            # Contract price is the market-implied probability (cents -> 0-1)
            price_cents = fill.get("price_cents")
            if price_cents is not None:
                fill_report["contract_probability"] = price_cents / 100.0
            
            # For 15m, we track YES vs NO counts and average prices
            side = fill.get("side")
            if side == "yes":
                report["15m_binary_stats"]["yes_count"] += 1
                if price_cents is not None:
                    yes_count = report["15m_binary_stats"]["yes_count"]
                    avg_yes = report["15m_binary_stats"]["avg_yes_price_cents"]
                    report["15m_binary_stats"]["avg_yes_price_cents"] = (avg_yes * (yes_count - 1) + price_cents) / yes_count
            elif side == "no":
                report["15m_binary_stats"]["no_count"] += 1
                if price_cents is not None:
                    no_count = report["15m_binary_stats"]["no_count"]
                    avg_no = report["15m_binary_stats"]["avg_no_price_cents"]
                    report["15m_binary_stats"]["avg_no_price_cents"] = (avg_no * (no_count - 1) + price_cents) / no_count
            
            report["by_timeframe"]["15m"]["count"] += 1
            report["by_timeframe"]["15m"]["fills"].append(fill_report)
        else:
            # Multi-strike analysis: calculate delta between spot and contract strike
            strike = fill.get("strike_price")
            spot = asset_basis.get("spot_price") if asset_basis else None
            if strike and spot:
                fill_report["spot_vs_contract_delta"] = ((strike - spot) / spot) * 100
            
            report["by_timeframe"]["1h+"]["count"] += 1
            report["by_timeframe"]["1h+"]["fills"].append(fill_report)
        
        # Add rolling stats
        if asset_stats:
            fill_report["rolling_basis_mean"] = asset_stats.get("basis_mean")
            fill_report["rolling_basis_median"] = asset_stats.get("basis_median")
            fill_report["rolling_offside_pct"] = asset_stats.get("offside_pct")
        
        # Add crypto contract data
        if asset_crypto:
            fill_report["crypto_spot_usd"] = asset_crypto.get("spot_usd")
            fill_report["crypto_total_contracts"] = asset_crypto.get("total_contracts")
        
        report["fills"].append(fill_report)
        
        # Aggregate by asset
        if asset not in report["by_asset"]:
            report["by_asset"][asset] = {
                "count": 0,
                "total_quantity": 0,
                "avg_price_cents": 0,
                "avg_basis": 0,
                "avg_spot_vs_contract_delta": 0,
                "15m_count": 0,
                "multi_strike_count": 0
            }
        
        asset_report = report["by_asset"][asset]
        asset_report["count"] += 1
        asset_report["total_quantity"] += fill.get("quantity", 0)
        asset_report["avg_price_cents"] = (
            (asset_report["avg_price_cents"] * (asset_report["count"] - 1) + fill.get("price_cents", 0)) / asset_report["count"]
        )
        
        if is_15m:
            asset_report["15m_count"] += 1
        else:
            asset_report["multi_strike_count"] += 1
        
        if fill_report["basis_mid"] is not None:
            asset_report["avg_basis"] = (
                (asset_report["avg_basis"] * (asset_report["count"] - 1) + fill_report["basis_mid"]) / asset_report["count"]
            )
        
        if fill_report["spot_vs_contract_delta"] is not None:
            asset_report["avg_spot_vs_contract_delta"] = (
                (asset_report["avg_spot_vs_contract_delta"] * (asset_report["count"] - 1) + fill_report["spot_vs_contract_delta"]) / asset_report["count"]
            )
    
    return report


def print_report(report: Dict[str, Any]):
    """Print a formatted comparison report."""
    print("=" * 80)
    print("KALSHI TRADE LOGS vs SPOT/CONTRACT DATA COMPARISON")
    print("=" * 80)
    print(f"Total Fills Analyzed: {report['total_fills']}")
    print(f"Fills with Spot Data: {report['fills_with_spot_data']}")
    print(f"Fills without Spot Data: {report['fills_without_spot_data']}")
    print()
    
    print("BY TIMEFRAME:")
    print("-" * 80)
    print(f"15m Binary Options: {report['by_timeframe']['15m']['count']} fills")
    print(f"Multi-Strike (1H+): {report['by_timeframe']['1h+']['count']} fills")
    print()
    
    if report['by_timeframe']['15m']['count'] > 0:
        print("15M BINARY STATS (Probability/Edge Analysis):")
        print("-" * 80)
        stats = report['15m_binary_stats']
        print(f"YES Orders: {stats['yes_count']}")
        print(f"NO Orders: {stats['no_count']}")
        print(f"Avg YES Price (cents): {stats['avg_yes_price_cents']:.2f}")
        print(f"Avg NO Price (cents): {stats['avg_no_price_cents']:.2f}")
        print(f"YES Hit Rate: {stats['yes_hit_rate']:.2%} (requires settlement data)")
        print(f"NO Hit Rate: {stats['no_hit_rate']:.2%} (requires settlement data)")
        print()
    
    print("BY ASSET:")
    print("-" * 80)
    for asset, data in report["by_asset"].items():
        print(f"{asset}:")
        print(f"  Count: {data['count']}")
        print(f"  15m Count: {data['15m_count']}")
        print(f"  Multi-Strike Count: {data['multi_strike_count']}")
        print(f"  Total Quantity: {data['total_quantity']}")
        print(f"  Avg Price (cents): {data['avg_price_cents']:.2f}")
        print(f"  Avg Basis (implied - spot): ${data['avg_basis']:.2f}")
        print(f"  Avg Spot vs Contract Delta: {data['avg_spot_vs_contract_delta']:.2f}%")
        print()
    
    print("RECENT FILLS (last 10):")
    print("-" * 80)
    for fill in report["fills"][:10]:
        print(f"Fill ID: {fill['fill_id']}")
        print(f"  Ticker: {fill['ticker']}")
        print(f"  Asset: {fill['asset']}")
        print(f"  Timeframe: {fill['timeframe']}")
        print(f"  Is 15m Binary: {fill['is_15m_binary']}")
        print(f"  Side: {fill['side']}")
        print(f"  Quantity: {fill['quantity']}")
        print(f"  Price (cents): {fill['price_cents']}")
        print(f"  Strike: {fill['strike_price']}")
        print(f"  Spot Price: ${fill['spot_price']}" if fill['spot_price'] else f"  Spot Price: N/A")
        print(f"  Implied Spot: ${fill['implied_spot_mid']}" if fill['implied_spot_mid'] else f"  Implied Spot: N/A")
        print(f"  Basis: ${fill['basis_mid']}" if fill['basis_mid'] is not None else f"  Basis: N/A")
        print(f"  Alignment: {fill['alignment']}" if fill['alignment'] else f"  Alignment: N/A")
        if fill['is_15m_binary']:
            print(f"  Contract Probability: {fill['contract_probability']:.2%}" if fill['contract_probability'] is not None else f"  Contract Probability: N/A")
            print(f"  Settlement Outcome: {fill['settlement_outcome']}" if fill['settlement_outcome'] is not None else f"  Settlement Outcome: N/A")
            print(f"  Realized Edge: {fill['realized_edge']:.2%}" if fill['realized_edge'] is not None else f"  Realized Edge: N/A")
        else:
            print(f"  Spot vs Contract Delta: {fill['spot_vs_contract_delta']:.2f}%" if fill['spot_vs_contract_delta'] is not None else f"  Spot vs Contract Delta: N/A")
        print(f"  Executed At: {fill['executed_at']}")
        print()


async def main():
    parser = argparse.ArgumentParser(description="Compare Kalshi trade logs with spot price to Kalshi contract data")
    parser.add_argument("--hours", type=int, default=24, help="Hours of fills to analyze (default: 24)")
    parser.add_argument("--base-url", type=str, default="http://localhost:8011", help="Base URL for MERID API")
    parser.add_argument("--output", type=str, help="Output file path for JSON report")
    parser.add_argument("--window-minutes", type=int, default=60, help="Rolling stats window in minutes (default: 60)")
    
    args = parser.parse_args()
    
    print(f"Fetching Kalshi fills from last {args.hours} hours...")
    fills = await fetch_kalshi_fills(base_url=args.base_url, hours=args.hours)
    print(f"Found {len(fills)} fills")
    
    print("Fetching current spot/Kalshi basis data...")
    spot_basis = await fetch_spot_basis(base_url=args.base_url)
    
    print("Fetching rolling spot/Kalshi basis statistics...")
    spot_basis_stats = await fetch_spot_basis_stats(base_url=args.base_url, window_minutes=args.window_minutes)
    
    print("Fetching crypto spot vs Kalshi contract prices...")
    crypto_spot_kalshi = await fetch_crypto_spot_kalshi(base_url=args.base_url)
    
    print("Comparing fills with spot/contract data...")
    report = compare_fills_with_spot(fills, spot_basis, spot_basis_stats, crypto_spot_kalshi)
    
    print_report(report)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())

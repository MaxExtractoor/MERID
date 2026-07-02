"""
Spot Price Parity Helpers - Symmetric 5-Asset Behavior with Diagnostics

Ensures all 5 assets (BTC, ETH, SOL, XRP, DOGE) are treated identically
with explicit per-asset configuration and comprehensive parity diagnostics.
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)

# Asset configuration with explicit per-asset settings
ASSET_CONFIG = {
    "BTC": {
        "pair": "BTC-USD",
        "price_range": (1000.0, 500000.0),
        "timeout_s": 4.0,
        "provider": "coinbase_public",
        "priority": 1  # Primary asset
    },
    "ETH": {
        "pair": "ETH-USD", 
        "price_range": (10.0, 20000.0),
        "timeout_s": 4.0,
        "provider": "coinbase_public",
        "priority": 2
    },
    "SOL": {
        "pair": "SOL-USD",
        "price_range": (0.10, 1000.0),
        "timeout_s": 4.0,  # Same timeout as others - no special treatment
        "provider": "coinbase_public",
        "priority": 3
    },
    "XRP": {
        "pair": "XRP-USD",
        "price_range": (0.001, 100.0),
        "timeout_s": 4.0,
        "provider": "coinbase_public", 
        "priority": 4
    },
    "DOGE": {
        "pair": "DOGE-USD",
        "price_range": (0.0001, 10.0),
        "timeout_s": 4.0,
        "provider": "coinbase_public",
        "priority": 5
    }
}

@dataclass
class SpotFetchResult:
    """Result of individual asset spot price fetch."""
    asset: str
    success: bool
    price: Optional[float] = None
    timestamp_ms: Optional[int] = None
    latency_ms: Optional[float] = None
    error_kind: Optional[str] = None  # "timeout", "http_error", "parse_error", "validation_error"
    provider: Optional[str] = None
    warning_message: Optional[str] = None
    
    def is_valid(self) -> bool:
        return self.success and self.price is not None
    
    def has_error(self) -> bool:
        return self.error_kind is not None

@dataclass 
class SpotParitySummary:
    """Summary of spot fetch parity across all assets."""
    cycle_id: int
    timestamp_ms: int
    results: Dict[str, SpotFetchResult] = field(default_factory=dict)
    
    def success_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)
    
    def failure_count(self) -> int:
        return len(self.results) - self.success_count()
    
    def get_failed_assets(self) -> List[str]:
        return [asset for asset, result in self.results.items() if not result.success]
    
    def get_error_distribution(self) -> Dict[str, int]:
        """Count errors by type."""
        error_counts = {}
        for result in self.results.values():
            if result.error_kind:
                error_counts[result.error_kind] = error_counts.get(result.error_kind, 0) + 1
        return error_counts
    
    def has_parity_violation(self) -> bool:
        """Check if there's a parity violation (partial failures)."""
        return 0 < self.success_count() < len(self.results)
    
    def get_parity_violation_message(self) -> str:
        """Get detailed parity violation message."""
        if not self.has_parity_violation():
            return ""
        
        failed = self.get_failed_assets()
        errors = self.get_error_distribution()
        return f"[SPOT-PARITY] asset={','.join(failed)} inconsistent with others ({self.success_count()}/{len(self.results)} success) errors={errors}"

def validate_spot_price(asset: str, price: float) -> Tuple[bool, Optional[str]]:
    """
    Validate spot price against asset-specific reasonable bounds.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        price: Price to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    config = ASSET_CONFIG.get(asset)
    if not config:
        return False, f"Unknown asset: {asset}"
    
    min_price, max_price = config["price_range"]
    
    if not (min_price <= price <= max_price):
        return False, f"Price ${price:.6f} outside reasonable range [${min_price:.2f}, ${max_price:.2f}]"
    
    if price <= 0:
        return False, f"Price must be positive: ${price:.6f}"
    
    # Additional sanity checks
    if asset == "BTC" and price > 1000000:  # BTC > $1M
        return False, f"BTC price ${price:.2f} exceeds sanity check ($1M)"
    
    if asset == "DOGE" and price > 100:  # DOGE > $100
        return False, f"DOGE price ${price:.6f} exceeds sanity check ($100)"
    
    return True, None

async def fetch_spot_symmetric(asset: str, fetch_func, cycle_id: int) -> SpotFetchResult:
    """
    Fetch spot price with symmetric behavior across all assets.
    
    Args:
        asset: Asset symbol
        fetch_func: Async function to fetch price (asset, timeout) -> dict
        cycle_id: Current cycle ID for tracking
        
    Returns:
        SpotFetchResult with detailed diagnostics
    """
    config = ASSET_CONFIG.get(asset)
    if not config:
        return SpotFetchResult(
            asset=asset,
            success=False,
            error_kind="config_error",
            warning_message=f"Asset {asset} not in configuration"
        )
    
    start_time = time.time()
    
    try:
        # Use asset-specific timeout (same for all assets)
        timeout = config["timeout_s"]
        provider = config["provider"]
        
        logger.debug(f"[SPOT-PARITY] Cycle {cycle_id} fetching {asset} from {provider} timeout={timeout}s")
        
        # Call the actual fetch function
        data = await asyncio.wait_for(fetch_func(asset, timeout), timeout=timeout)
        
        if data is None:
            return SpotFetchResult(
                asset=asset,
                success=False,
                error_kind="fetch_error",
                latency_ms=(time.time() - start_time) * 1000,
                provider=provider,
                warning_message="Fetch function returned None"
            )
        
        # Extract price and validate
        price = data.get('price')
        timestamp_ms = data.get('timestamp')
        
        if price is None:
            return SpotFetchResult(
                asset=asset,
                success=False,
                error_kind="parse_error",
                latency_ms=(time.time() - start_time) * 1000,
                provider=provider,
                warning_message="No price in response"
            )
        
        # Validate price
        is_valid, error_msg = validate_spot_price(asset, price)
        if not is_valid:
            return SpotFetchResult(
                asset=asset,
                success=False,
                error_kind="validation_error",
                latency_ms=(time.time() - start_time) * 1000,
                provider=provider,
                warning_message=error_msg
            )
        
        # Success
        return SpotFetchResult(
            asset=asset,
            success=True,
            price=price,
            timestamp_ms=timestamp_ms,
            latency_ms=(time.time() - start_time) * 1000,
            provider=provider
        )
        
    except asyncio.TimeoutError:
        return SpotFetchResult(
            asset=asset,
            success=False,
            error_kind="timeout",
            latency_ms=timeout * 1000,  # Full timeout duration
            provider=provider,
            warning_message=f"Timeout after {timeout}s"
        )
    except Exception as e:
        return SpotFetchResult(
            asset=asset,
            success=False,
            error_kind="exception",
            latency_ms=(time.time() - start_time) * 1000,
            provider=provider,
            warning_message=str(e)
        )

async def fetch_all_spot_parity(fetch_func, cycle_id: int) -> SpotParitySummary:
    """
    Fetch spot prices for all assets with symmetric behavior and parity checking.
    
    Args:
        fetch_func: Async function to fetch price (asset, timeout) -> dict
        cycle_id: Current cycle ID for tracking
        
    Returns:
        SpotParitySummary with results and parity analysis
    """
    start_time = time.time()
    timestamp_ms = int(start_time * 1000)
    
    logger.info(f"[SPOT-PARITY] Cycle {cycle_id} starting symmetric fetch for {len(ASSET_CONFIG)} assets")
    
    # Fetch all assets concurrently
    tasks = []
    for asset in ASSET_CONFIG.keys():
        task = fetch_spot_symmetric(asset, fetch_func, cycle_id)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Build summary
    summary = SpotParitySummary(
        cycle_id=cycle_id,
        timestamp_ms=timestamp_ms,
        results={}
    )
    
    for i, asset in enumerate(ASSET_CONFIG.keys()):
        result = results[i]
        if isinstance(result, Exception):
            # Handle unexpected exceptions
            summary.results[asset] = SpotFetchResult(
                asset=asset,
                success=False,
                error_kind="exception",
                warning_message=str(result)
            )
        else:
            summary.results[asset] = result
    
    # Log parity summary
    success_count = summary.success_count()
    total_count = len(summary.results)
    
    logger.info(f"[SPOT-PARITY] Cycle {cycle_id} completed: {success_count}/{total_count} successful")
    
    # Log per-asset results
    for asset, result in summary.results.items():
        if result.success:
            logger.info(f"[SPOT-PARITY] Cycle {cycle_id} {asset}: ${result.price:.2f} ({result.latency_ms:.1f}ms) {result.provider}")
        else:
            logger.warning(f"[SPOT-PARITY] Cycle {cycle_id} {asset}: {result.error_kind} - {result.warning_message}")
    
    # Check for parity violations
    if summary.has_parity_violation():
        logger.error(summary.get_parity_violation_message())
    
    return summary

def log_parity_diagnostics(summary: SpotParitySummary) -> None:
    """
    Log comprehensive parity diagnostics for monitoring.
    
    Args:
        summary: SpotParitySummary to log diagnostics for
    """
    # Per-cycle parity log (as requested in the requirements)
    for asset, result in summary.results.items():
        success_flag = "✓" if result.success else "✗"
        latency_str = f"{result.latency_ms:.1f}" if result.latency_ms else "N/A"
        error_str = result.error_kind or "none"
        
        # Calculate freshness for successful fetches
        freshness_s = "N/A"
        if result.success and result.timestamp_ms:
            freshness_s = (time.time() * 1000 - result.timestamp_ms) / 1000.0
            freshness_str = f"{freshness_s:.1f}"
        else:
            freshness_str = "N/A"
        
        logger.info(
            f"[SPOT-PARITY-ROW] cycle={summary.cycle_id} asset={asset} "
            f"provider={result.provider or 'none'} success={success_flag} "
            f"latency_ms={latency_str} freshness_s={freshness_str} error_kind={error_str}"
        )
    
    # Parity violation warning
    if summary.has_parity_violation():
        failed_assets = summary.get_failed_assets()
        error_dist = summary.get_error_distribution()
        
        logger.warning(
            f"[SPOT-PARITY] Cycle {summary.cycle_id}: Partial failure detected. "
            f"Failed: {', '.join(failed_assets)}. "
            f"Error distribution: {error_dist}. "
            f"Success rate: {summary.success_count()}/{len(summary.results)} ({summary.success_count()/len(summary.results)*100:.1f}%)"
        )
    
    # Latency analysis
    latencies = [r.latency_ms for r in summary.results.values() if r.latency_ms is not None]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)
        
        logger.info(
            f"[SPOT-PARITY] Cycle {summary.cycle_id} latency: "
            f"avg={avg_latency:.1f}ms min={min_latency:.1f}ms max={max_latency:.1f}ms"
        )
        
        # Check for latency outliers (>3x average)
        for asset, result in summary.results.items():
            if result.success and result.latency_ms and result.latency_ms > avg_latency * 3:
                logger.warning(
                    f"[SPOT-PARITY] Cycle {summary.cycle_id} {asset} latency outlier: "
                    f"{result.latency_ms:.1f}ms vs avg {avg_latency:.1f}ms"
                )

def get_asset_provider(asset: str) -> Optional[str]:
    """Get the provider for a given asset."""
    config = ASSET_CONFIG.get(asset)
    return config.get("provider") if config else None

def get_asset_timeout(asset: str) -> float:
    """Get the timeout for a given asset."""
    config = ASSET_CONFIG.get(asset)
    return config.get("timeout_s", 4.0) if config else 4.0

def is_asset_supported(asset: str) -> bool:
    """Check if asset is supported in parity configuration."""
    return asset in ASSET_CONFIG

def get_supported_assets() -> List[str]:
    """Get list of all supported assets."""
    return list(ASSET_CONFIG.keys())

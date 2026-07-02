"""
Kelly Position Sizing - Classical Kelly Criterion for Crypto Trading

Use classical Kelly on backtest stats, then run at a fraction (0.25-0.5 Kelly) for safety.
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class KellyStats:
    """Kelly statistics for position sizing."""
    win_rate: float      # 0..1
    win_loss_ratio: float  # avg_win / avg_loss
    
    def __post_init__(self):
        """Validate inputs."""
        if not (0 <= self.win_rate <= 1):
            raise ValueError("win_rate must be between 0 and 1")
        if self.win_loss_ratio <= 0:
            raise ValueError("win_loss_ratio must be positive")

def kelly_fraction(stats: KellyStats) -> float:
    """
    Return full Kelly fraction.
    
    Kelly formula: f* = W - (1-W)/R
    where W is win rate and R is average win / average loss.
    
    Args:
        stats: KellyStats with win_rate and win_loss_ratio
        
    Returns:
        Kelly fraction clipped to [0, 1], 0 if negative
    """
    W = stats.win_rate
    R = stats.win_loss_ratio
    
    if R <= 0:
        logger.warning("Invalid win_loss_ratio, returning 0")
        return 0.0
    
    # Kelly formula
    f = W - (1 - W) / R
    
    # Clip to [0, 1]
    if f < 0:
        logger.info(f"Negative Kelly fraction {f:.3f}, returning 0")
        return 0.0
    
    f_clipped = min(f, 1.0)
    
    logger.debug(f"Kelly fraction: {f_clipped:.3f} (W={W:.3f}, R={R:.3f})")
    
    return f_clipped

def kelly_position_size(
    capital_usd: float, 
    contract_notional_usd: float, 
    stats: KellyStats, 
    fraction_of_kelly: float = 0.5
) -> int:
    """
    Convert Kelly fraction to # contracts with safety factor.
    
    Args:
        capital_usd: Total capital available
        contract_notional_usd: Notional value per contract
        stats: Kelly statistics for the asset
        fraction_of_kelly: Safety factor (0.25-0.5 typical)
        
    Returns:
        Number of contracts to trade
    """
    if capital_usd <= 0 or contract_notional_usd <= 0:
        logger.warning("Invalid capital or contract notional")
        return 0
    
    if not (0 < fraction_of_kelly <= 1):
        logger.warning("fraction_of_kelly must be between 0 and 1")
        return 0
    
    # Calculate full Kelly fraction
    f_star = kelly_fraction(stats)
    
    # Apply safety factor
    f_use = f_star * fraction_of_kelly
    
    # Calculate risk amount in USD
    risk_usd = capital_usd * f_use
    
    if risk_usd <= 0:
        return 0
    
    # Convert to contracts
    contracts = int(risk_usd / contract_notional_usd)
    
    logger.info(f"Kelly sizing: {contracts} contracts "
                f"(f*={f_star:.3f}, safety={fraction_of_kelly:.2f}, risk=${risk_usd:.2f})")
    
    return max(contracts, 0)

def calculate_kelly_stats_from_trades(trades: list) -> KellyStats:
    """
    Calculate Kelly statistics from trade results.
    
    Args:
        trades: List of trade PnL values (positive for wins, negative for losses)
        
    Returns:
        KellyStats object
    """
    if not trades:
        logger.warning("No trades provided, using conservative defaults")
        return KellyStats(win_rate=0.5, win_loss_ratio=1.0)
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    win_rate = len(wins) / len(trades)
    
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0  # Avoid division by zero
    
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0
    
    stats = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    
    logger.info(f"Kelly stats from {len(trades)} trades: "
                f"win_rate={win_rate:.3f}, win_loss_ratio={win_loss_ratio:.2f}")
    
    return stats

def validate_kelly_parameters(stats: KellyStats, fraction_of_kelly: float) -> dict:
    """
    Validate Kelly parameters and return recommendations.
    
    Args:
        stats: Kelly statistics
        fraction_of_kelly: Safety factor being used
        
    Returns:
        Dictionary with validation results and recommendations
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Check win rate
    if stats.win_rate < 0.5:
        validation["warnings"].append(f"Low win rate: {stats.win_rate:.2f}")
        validation["recommendations"].append("Consider improving signal quality before trading")
    
    # Check win/loss ratio
    if stats.win_loss_ratio < 1.0:
        validation["warnings"].append(f"Win/loss ratio < 1: {stats.win_loss_ratio:.2f}")
        validation["recommendations"].append("Average wins should exceed average losses")
    
    # Check safety factor
    if fraction_of_kelly > 0.5:
        validation["warnings"].append(f"High Kelly fraction: {fraction_of_kelly:.2f}")
        validation["recommendations"].append("Consider using 0.25-0.5 Kelly for safety")
    
    # Calculate full Kelly
    full_kelly = kelly_fraction(stats)
    if full_kelly > 0.25:
        validation["warnings"].append(f"High full Kelly: {full_kelly:.3f}")
        validation["recommendations"].append("Full Kelly > 25% is aggressive, consider reducing exposure")
    
    # Overall validity
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

# Example usage:
"""
# Calculate Kelly position size
stats = KellyStats(win_rate=0.55, win_loss_ratio=1.5)
contracts = kelly_position_size(
    capital_usd=100000,
    contract_notional_usd=1.0,
    stats=stats,
    fraction_of_kelly=0.3
)
print(f"Recommended position size: {contracts} contracts")

# Calculate from trade results
trade_pnls = [100, -50, 75, -25, 150, -75, 50, -30]
trade_stats = calculate_kelly_stats_from_trades(trade_pnls)
print(f"Trade stats: win_rate={trade_stats.win_rate:.2f}, ratio={trade_stats.win_loss_ratio:.2f}")

# Validate parameters
validation = validate_kelly_parameters(trade_stats, fraction_of_kelly=0.3)
print(f"Validation: {validation}")
"""

"""
RCK + Bayesian Dataclasses for Production Integration

Clean dataclasses that wrap the advanced RCK + Bayesian pipeline
for seamless integration with Crypto15MLane.

Key features:
- ConsensusResult: Complete consensus output with Bayesian learning
- RiskDecisionResult: Complete risk decision with RCK details
- RCKConfig: Per-symbol RCK parameters
- BayesianConfig: Per-symbol Bayesian parameters
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class ConfidenceLevel(Enum):
    """Confidence level based on sample size."""
    LOW = "low"        # < 10 historical trades
    MEDIUM = "medium"  # 10-30 historical trades  
    HIGH = "high"      # > 30 historical trades


@dataclass
class BayesianLearningResult:
    """Results from Bayesian p_true estimation."""
    prior_strength: float
    posterior_alpha: float
    posterior_beta: float
    posterior_mean: float
    historical_wins: int
    historical_losses: int
    total_historical: int
    feature_adjustment: float
    confidence: ConfidenceLevel
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prior_strength": self.prior_strength,
            "posterior_alpha": self.posterior_alpha,
            "posterior_beta": self.posterior_beta,
            "posterior_mean": self.posterior_mean,
            "historical_wins": self.historical_wins,
            "historical_losses": self.historical_losses,
            "total_historical": self.total_historical,
            "feature_adjustment": self.feature_adjustment,
            "confidence": self.confidence.value,
        }


@dataclass
class ConsensusResult:
    """Complete consensus result for a 15m crypto market."""
    # Market identifiers
    market_id: str
    market_title: str
    symbol: str
    direction: str  # "yes" or "no"
    
    # Probabilities (vig-adjusted)
    p_true: float                    # Bayesian estimated true probability
    p_implied: float                 # De-vigged market implied probability
    fair_yes_prob: float            # De-vigged YES probability
    fair_no_prob: float             # De-vigged NO probability
    
    # Market prices
    yes_price_cents: int
    no_price_cents: int
    
    # Edge calculation
    edge_bps: float                 # Edge in basis points (p_true - p_implied) * 10000
    
    # Features used for estimation
    features: Dict[str, Any]
    
    # Bayesian learning details
    bayesian_learning: BayesianLearningResult
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "market_title": self.market_title,
            "symbol": self.symbol,
            "direction": self.direction,
            "p_true": self.p_true,
            "p_implied": self.p_implied,
            "fair_yes_prob": self.fair_yes_prob,
            "fair_no_prob": self.fair_no_prob,
            "yes_price_cents": self.yes_price_cents,
            "no_price_cents": self.no_price_cents,
            "edge_bps": self.edge_bps,
            "features": self.features,
            "bayesian_learning": self.bayesian_learning.to_dict(),
        }


@dataclass
class RCKSolverResult:
    """Results from RCK solver."""
    method: str                    # "rck_solver" or "fallback"
    f_rck: Optional[float]         # Raw RCK fraction
    target_drawdown: float         # Target maximum drawdown
    drawdown_probability: float    # Max probability of exceeding target
    safety_factor: float           # Additional safety margin
    fraction_of_full: float        # Fraction of full Kelly
    solver_paths: int             # Monte Carlo paths used
    solver_trades: int            # Trades per path
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "f_rck": self.f_rck,
            "target_drawdown": self.target_drawdown,
            "drawdown_probability": self.drawdown_probability,
            "safety_factor": self.safety_factor,
            "fraction_of_full": self.fraction_of_full,
            "solver_paths": self.solver_paths,
            "solver_trades": self.solver_trades,
        }


@dataclass
class RiskDecisionResult:
    """Complete risk decision result with RCK details."""
    # Decision approval
    approved: bool
    
    # Position sizing
    position_size: float
    bankroll_before: float
    bankroll_after: float
    
    # Kelly fractions
    kelly_fraction_full: float     # Full Kelly from p_true
    kelly_fraction_used: float     # Final fraction after RCK + safety
    
    # RCK details
    risk_constrained_kelly: RCKSolverResult
    
    # Risk metrics
    edge_bps: float
    current_positions: int
    
    # Fear & Greed adjustment
    fear_greed_applied: bool
    fg_multiplier: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "position_size": self.position_size,
            "bankroll_before": self.bankroll_before,
            "bankroll_after": self.bankroll_after,
            "kelly_fraction_full": self.kelly_fraction_full,
            "kelly_fraction_used": self.kelly_fraction_used,
            "risk_constrained_kelly": self.risk_constrained_kelly.to_dict(),
            "edge_bps": self.edge_bps,
            "current_positions": self.current_positions,
            "fear_greed_applied": self.fear_greed_applied,
            "fg_multiplier": self.fg_multiplier,
        }


@dataclass
class BayesianConfig:
    """Bayesian configuration per symbol."""
    symbol: str
    prior_strength: int           # Pseudo-count n0
    rti_weight: float = 0.06      # RTI signal weight
    flow_weight: float = 0.03     # Flow imbalance weight
    fg_weight: float = 1.0        # Fear & Greed weight (as-is)
    asset_weight: float = 0.05    # Asset sentiment weight
    
    @classmethod
    def get_defaults(cls) -> Dict[str, "BayesianConfig"]:
        """Get default Bayesian configurations per symbol."""
        return {
            "BTC": cls(symbol="BTC", prior_strength=30),
            "ETH": cls(symbol="ETH", prior_strength=25),
            "SOL": cls(symbol="SOL", prior_strength=40),
            "XRP": cls(symbol="XRP", prior_strength=45),
        }


@dataclass
class RCKConfig:
    """RCK configuration per symbol."""
    symbol: str
    target_drawdown: float         # Maximum drawdown (e.g., 0.1 for 10%)
    drawdown_probability: float    # Max probability of exceeding target
    safety_factor: float           # Additional safety margin
    min_fraction: float = 0.01     # Minimum Kelly fraction
    
    @classmethod
    def get_defaults(cls) -> Dict[str, "RCKConfig"]:
        """Get default RCK configurations per symbol."""
        return {
            "BTC": cls(symbol="BTC", target_drawdown=0.10, drawdown_probability=0.10, safety_factor=0.8),
            "ETH": cls(symbol="ETH", target_drawdown=0.08, drawdown_probability=0.12, safety_factor=0.8),
            "SOL": cls(symbol="SOL", target_drawdown=0.05, drawdown_probability=0.15, safety_factor=0.8),
            "XRP": cls(symbol="XRP", target_drawdown=0.05, drawdown_probability=0.15, safety_factor=0.8),
        }


@dataclass
class Crypto15MLaneRCKConfig:
    """Extended configuration for Crypto15MLane with RCK + Bayesian parameters."""
    # Existing lane config fields would be here
    symbol: str
    
    # RCK parameters
    rck_config: RCKConfig = field(default_factory=lambda: RCKConfig(
        symbol="BTC", target_drawdown=0.10, drawdown_probability=0.10, safety_factor=0.8
    ))

    # Bayesian parameters
    bayesian_config: BayesianConfig = field(default_factory=lambda: BayesianConfig(
        symbol="BTC", prior_strength=30
    ))
    
    # Global safety factors
    global_safety_factor: float = 0.8
    min_edge_threshold_bps: float = 30.0
    
    @classmethod
    def create_for_symbol(cls, symbol: str) -> "Crypto15MLaneRCKConfig":
        """Create configuration for a specific symbol with defaults."""
        rck_defaults = RCKConfig.get_defaults()
        bayesian_defaults = BayesianConfig.get_defaults()
        
        rck_cfg = rck_defaults.get(symbol) or RCKConfig(
            symbol=symbol, target_drawdown=0.10, drawdown_probability=0.10, safety_factor=0.8
        )
        bayes_cfg = bayesian_defaults.get(symbol) or BayesianConfig(symbol=symbol, prior_strength=30)
        return cls(
            symbol=symbol,
            rck_config=rck_cfg,
            bayesian_config=bayes_cfg,
        )


# Factory functions for easy integration
def create_consensus_result(
    market_data: Dict[str, Any],
    p_true: float,
    p_implied: float,
    fair_yes_prob: float,
    fair_no_prob: float,
    features: Dict[str, Any],
    bayesian_result: BayesianLearningResult
) -> ConsensusResult:
    """Create ConsensusResult from lane data."""
    yes_price_cents = market_data.get("yes_price_cents", 50)
    no_price_cents = market_data.get("no_price_cents", 50)
    
    edge_bps = (p_true - p_implied) * 10000
    direction = "yes" if edge_bps > 0 else "no"
    
    return ConsensusResult(
        market_id=market_data.get("market_id", ""),
        market_title=market_data.get("market_title", ""),
        symbol=market_data.get("symbol", ""),
        direction=direction,
        p_true=p_true,
        p_implied=p_implied,
        fair_yes_prob=fair_yes_prob,
        fair_no_prob=fair_no_prob,
        yes_price_cents=yes_price_cents,
        no_price_cents=no_price_cents,
        edge_bps=edge_bps,
        features=features,
        bayesian_learning=bayesian_result,
    )


def create_risk_decision_result(
    approved: bool,
    position_size: float,
    bankroll_before: float,
    bankroll_after: float,
    kelly_full: float,
    kelly_used: float,
    rck_result: RCKSolverResult,
    edge_bps: float,
    current_positions: int,
    fg_applied: bool = False,
    fg_multiplier: float = 1.0
) -> RiskDecisionResult:
    """Create RiskDecisionResult from lane data."""
    return RiskDecisionResult(
        approved=approved,
        position_size=position_size,
        bankroll_before=bankroll_before,
        bankroll_after=bankroll_after,
        kelly_fraction_full=kelly_full,
        kelly_fraction_used=kelly_used,
        risk_constrained_kelly=rck_result,
        edge_bps=edge_bps,
        current_positions=current_positions,
        fear_greed_applied=fg_applied,
        fg_multiplier=fg_multiplier,
    )

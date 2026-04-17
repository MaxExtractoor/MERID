"""
Crypto15MLane — Generic end-to-end orchestration for crypto 15m Kalshi trading.

Wires together:
  - Kalshi market discovery (KalshiMarketCatalog)
  - Sentiment stack (SentimentBus → SentimentBundle + Fibonacci smoothing)
  - Swarm consensus (SwarmConsensusAggregator)
  - Risk evaluation (CryptoSwarmRisk + SentimentRiskDial)
  - Order execution (KalshiExecutor, mode-guarded)
  - Observability (structured logging of every decision)

Supports BTC, ETH, SOL, XRP, DOGE with both live and paper trading modes.
"""

from __future__ import annotations

import threading
import asyncio
import datetime as dt
from utils.logger import get_logger
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Literal
from enum import Enum

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Symbol definitions
# ---------------------------------------------------------------------------

CryptoSymbol = Literal["BTC", "ETH", "SOL", "XRP", "DOGE"]


# ---------------------------------------------------------------------------
# Kelly sizing utilities
# ---------------------------------------------------------------------------

def kelly_fraction_binary(p_true: float, price: float) -> float:
    """Full Kelly fraction for a binary (payoff 1/0) bet. [web:71]"""
    b = (1.0 - price) / price
    q = 1.0 - p_true
    f_star = (b * p_true - q) / b
    return max(0.0, min(f_star, 1.0))


def simulate_path(f: float, p_true: float, price: float, n_trades: int = 500) -> dict:
    """Simulate a wealth path under constant fraction f. [web:71][web:80]"""
    import numpy as np
    
    wealth = 1.0
    wealth_path = [wealth]
    b = (1.0 - price) / price

    for _ in range(n_trades):
        bet = f * wealth
        win = np.random.rand() < p_true
        if win:
            wealth += bet * b
        else:
            wealth -= bet
        wealth_path.append(wealth)

    wealth_path = np.array(wealth_path)
    max_wealth = np.maximum.accumulate(wealth_path)
    drawdown = 1.0 - wealth_path / max_wealth
    return {
        "final_wealth": wealth_path[-1],
        "max_drawdown": drawdown.max(),
        "log_growth": np.log(wealth_path[-1]),
    }


def solve_rck_fraction(p_true: float,
                       price: float,
                       target_dd: float = 0.1,
                       dd_prob: float = 0.1,
                       n_paths: int = 500,
                       n_trades: int = 500) -> float:
    """
    Risk-constrained Kelly fraction.
    Pick f <= f_Kelly such that P(max_drawdown > target_dd) <= dd_prob,
    while maximizing expected log growth. [web:69][web:71][web:80]
    """
    import numpy as np
    
    f_kelly = kelly_fraction_binary(p_true, price)
    if f_kelly <= 0:
        return 0.0

    candidates = np.linspace(0.1 * f_kelly, f_kelly, 12)
    best_f, best_growth = 0.0, -np.inf

    for f in candidates:
        dds = []
        growths = []
        for _ in range(n_paths):
            res = simulate_path(f, p_true, price, n_trades)
            dds.append(res["max_drawdown"])
            growths.append(res["log_growth"])
        dds = np.array(dds)
        growths = np.array(growths)

        prob_exceed = (dds > target_dd).mean()
        avg_growth = growths.mean()

        if prob_exceed <= dd_prob and avg_growth > best_growth:
            best_growth = avg_growth
            best_f = f

    return best_f


def devig_yes_no(yes_price: float, no_price: float) -> tuple[float, float]:
    """
    De-vig Kalshi YES/NO prices.
    yes_price, no_price: contract prices in 0..1
    Returns de-vigged implied probabilities p_yes, p_no. [web:75][web:78]
    """
    # Raw implied probabilities
    p_yes_raw = yes_price
    p_no_raw = no_price

    s = p_yes_raw + p_no_raw
    if s <= 0:
        return 0.5, 0.5
    return p_yes_raw / s, p_no_raw / s


def get_bayesian_prior_strength(symbol: str) -> int:
    """
    Get Bayesian prior strength (pseudo-count) per symbol.
    
    Guidelines:
    - Small n_0 (5-20): Quick adaptation, good for unstable models
    - Moderate n_0 (20-50): Balanced, default for BTC/ETH 15m
    - Higher n_0 for thin assets: Trust market more for SOL/XRP
    """
    if symbol == "BTC":
        return 30  # Moderate strength for liquid BTC
    elif symbol == "ETH":
        return 25  # Moderate strength for correlated ETH
    elif symbol == "SOL":
        return 40  # Higher strength for thinner SOL market
    elif symbol == "XRP":
        return 45  # Higher strength for moderate XRP liquidity
    else:
        return 35  # Default moderate strength


def estimate_p_true_advanced(
    symbol: str,
    yes_price_cents: int,
    no_price_cents: int,
    features: dict,
    historical_wins: int = 0,
    historical_losses: int = 0
) -> dict:
    """
    Advanced p_true estimation with vig adjustment and Bayesian updating.
    
    Args:
        symbol: Crypto symbol (BTC/ETH/SOL/XRP)
        yes_price_cents: YES price in cents
        no_price_cents: NO price in cents  
        features: RTI, FG, flow, sentiment features
        historical_wins: Historical wins for this symbol
        historical_losses: Historical losses for this symbol
        
    Returns:
        Dictionary with p_true, de-vigged probabilities, and learning stats
    """
    # Convert to decimal prices
    yes_price = yes_price_cents / 100.0
    no_price = no_price_cents / 100.0
    
    # De-vig Kalshi prices
    fair_yes_prob, fair_no_prob = devig_yes_no(yes_price, no_price)
    
    # Get symbol-specific prior strength
    prior_strength = get_bayesian_prior_strength(symbol)
    
    # Set Beta prior from de-vigged market probability
    prior_alpha = fair_yes_prob * prior_strength
    prior_beta = fair_no_prob * prior_strength
    
    # Update with historical data
    posterior_alpha = prior_alpha + historical_wins
    posterior_beta = prior_beta + historical_losses
    posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
    
    # Adjust with current features (reduced weights for 15m)
    delta = 0.0
    delta += 0.06 * features.get("rti_signal", 0.0)      # RTI weight
    delta += 0.03 * (features.get("flow_imbalance", 0.0) - 0.5)  # Flow weight
    delta += features.get("fg_contrarian", 0.0)             # FG as is
    delta += 0.05 * (features.get("asset_sentiment", 0.5) - 0.5)  # Asset sentiment
    
    # Final p_true estimate
    p_true = max(0.01, min(0.99, posterior_mean + delta))
    
    return {
        "p_true": p_true,
        "fair_yes_prob": fair_yes_prob,
        "fair_no_prob": fair_no_prob,
        "prior_strength": prior_strength,
        "posterior_alpha": posterior_alpha,
        "posterior_beta": posterior_beta,
        "posterior_mean": posterior_mean,
        "historical_wins": historical_wins,
        "historical_losses": historical_losses,
        "total_historical": historical_wins + historical_losses,
        "feature_adjustment": delta,
        "confidence": "high" if (historical_wins + historical_losses) >= 30 else "medium" if (historical_wins + historical_losses) >= 10 else "low"
    }


def devig_kalshi_prices(yes_price_cents: int, no_price_cents: int) -> tuple[float, float]:
    """
    Remove vig (house edge) from Kalshi YES/NO prices.
    
    Args:
        yes_price_cents: YES price in cents (1-99)
        no_price_cents: NO price in cents (1-99)
        
    Returns:
        (fair_yes_prob, fair_no_prob): De-vigged probabilities that sum to 1.0
    """
    # Convert to decimal probabilities
    p_yes_raw = yes_price_cents / 100.0
    p_no_raw = no_price_cents / 100.0
    
    # Calculate overround (vig)
    overround = p_yes_raw + p_no_raw
    
    if overround <= 0:
        # Fallback to equal probabilities if invalid
        return 0.5, 0.5
    
    # De-vig using multiplicative method
    fair_yes_prob = p_yes_raw / overround
    fair_no_prob = p_no_raw / overround
    
    return fair_yes_prob, fair_no_prob


def bayesian_update_p_true(
    prior_alpha: float, 
    prior_beta: float, 
    wins: int, 
    losses: int
) -> float:
    """
    Bayesian update for p_true using Beta-Binomial conjugate prior.
    
    Args:
        prior_alpha: Alpha parameter of Beta prior (successes)
        prior_beta: Beta parameter of Beta prior (failures)
        wins: Number of observed wins
        losses: Number of observed losses
        
    Returns:
        Posterior mean probability (p_true)
    """
    posterior_alpha = prior_alpha + wins
    posterior_beta = prior_beta + losses
    posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
    return posterior_mean


def estimate_p_true_bayesian(
    implied_prob: float, 
    features: dict, 
    symbol: str,
    historical_wins: int = 0,
    historical_losses: int = 0,
    prior_strength: float = 5.0
) -> float:
    """
    Estimate true probability using Bayesian updating with historical data.
    
    Args:
        implied_prob: De-vigged implied probability from market
        features: {
            "rti_signal": float,          # directional score -1..+1
            "fg_contrarian": float,      # -0.05..+0.05
            "flow_imbalance": float,     # 0..1
            "asset_sentiment": float,     # per-asset sentiment score
        }
        symbol: Crypto symbol for historical prior
        historical_wins: Historical wins for this symbol/signal config
        historical_losses: Historical losses for this symbol/signal config
        prior_strength: Strength of prior (equivalent sample size)
        
    Returns:
        Estimated true probability (0-1)
    """
    # 1) Start with de-vigged implied probability as prior mean
    prior_mean = implied_prob
    
    # 2) Convert to Beta prior parameters
    # Use prior_strength to control how much weight we give to prior vs data
    prior_alpha = prior_mean * prior_strength
    prior_beta = (1 - prior_mean) * prior_strength
    
    # 3) Update with historical data
    posterior_mean = bayesian_update_p_true(prior_alpha, prior_beta, historical_wins, historical_losses)
    
    # 4) Adjust with current features (similar to previous approach)
    delta = 0.0
    delta += 0.08 * features.get("rti_signal", 0.0)      # Reduced weight for RTI
    delta += 0.04 * (features.get("flow_imbalance", 0.0) - 0.5)  # Reduced weight for flow
    delta += features.get("fg_contrarian", 0.0)             # Keep FG as is
    
    # 5) Apply per-asset sentiment adjustment
    asset_sentiment = features.get("asset_sentiment", 0.5)
    delta += 0.06 * (asset_sentiment - 0.5)  # Further reduced for 15m
    
    # 6) Combine posterior mean with feature adjustments
    p_true = max(0.01, min(0.99, posterior_mean + delta))
    return p_true


def choose_fractional_kelly_risk_constrained(
    p_true: float, 
    price: float,
    target_drawdown: float = 0.5,
    max_dd_probability: float = 0.2,
    min_fraction: float = 0.1,
    max_fraction: float = 0.5
) -> float:
    """
    Choose optimal fractional Kelly using risk-constrained simulation.
    
    Args:
        p_true: True win probability
        price: Market price (0-1)
        target_drawdown: Maximum acceptable drawdown (e.g., 0.5 = 50%)
        max_dd_probability: Acceptable probability of exceeding target drawdown
        min_fraction: Minimum Kelly fraction to consider
        max_fraction: Maximum Kelly fraction to consider
        
    Returns:
        Optimal Kelly fraction that meets drawdown constraints
    """
    import numpy as np
    
    def simulate_trajectory(f: float, n_trades: int = 1000) -> dict:
        """Simulate wealth path for given Kelly fraction."""
        wealth = 1.0
        wealth_path = [wealth]
        b = (1 - price) / price  # odds if win

        for _ in range(n_trades):
            bet_size = f * wealth
            win = np.random.rand() < p_true
            if win:
                wealth += bet_size * b
            else:
                wealth -= bet_size
            wealth_path.append(wealth)

        wealth_path = np.array(wealth_path)
        max_wealth = np.maximum.accumulate(wealth_path)
        drawdown = 1 - wealth_path / max_wealth
        max_dd = drawdown.max()
        return {
            "final_wealth": wealth_path[-1],
            "max_drawdown": max_dd,
            "log_growth": np.log(wealth_path[-1]),
        }
    
    # Grid search over fractions
    fractions = np.linspace(min_fraction, max_fraction, 9)
    best_f = min_fraction
    best_growth = -np.inf

    for f in fractions:
        dds = []
        growths = []
        
        # Monte Carlo simulation
        for _ in range(200):  # Sample size for empirical distribution
            res = simulate_trajectory(f)
            dds.append(res["max_drawdown"])
            growths.append(res["log_growth"])
        
        dds = np.array(dds)
        growths = np.array(growths)

        prob_exceed_dd = (dds > target_drawdown).mean()
        avg_growth = growths.mean()

        # Choose fraction that meets drawdown constraint with best growth
        if prob_exceed_dd <= max_dd_probability and avg_growth > best_growth:
            best_growth = avg_growth
            best_f = f

    return best_f


def calculate_lambda_risk_aversion(drawdown_floor: float, max_probability: float) -> float:
    """
    Calculate λ (risk aversion parameter) for risk-constrained Kelly.
    
    From RCK paper: λ = log(β) / log(α)
    where α = drawdown_floor, β = max_probability
    
    Args:
        drawdown_floor: α - wealth floor (e.g., 0.9 for 10% drawdown)
        max_probability: β - tolerable probability (e.g., 0.1 for 10% chance)
        
    Returns:
        Risk aversion parameter λ
    """
    import math
    
    if drawdown_floor <= 0 or drawdown_floor >= 1:
        raise ValueError("drawdown_floor must be in (0, 1)")
    if max_probability <= 0 or max_probability >= 1:
        raise ValueError("max_probability must be in (0, 1)")
    
    lambda_risk = math.log(max_probability) / math.log(drawdown_floor)
    return lambda_risk


def risk_constrained_kelly_convex(
    p_true: float,
    price: float,
    lambda_risk: float,
    max_fraction: float = None,
    n_samples: int = 1000
) -> float:
    """
    Solve risk-constrained Kelly using convex optimization approximation.
    
    Maximizes: E[log(W)] - λ * Var[log(W)]
    subject to: 0 <= f <= f_kelly
    
    Args:
        p_true: True win probability
        price: Market price (0-1)
        lambda_risk: Risk aversion parameter λ
        max_fraction: Maximum fraction to consider (defaults to full Kelly)
        n_samples: Number of Monte Carlo samples for expectation/variance
        
    Returns:
        Optimal Kelly fraction under risk constraint
    """
    import numpy as np
    
    # Calculate full Kelly as upper bound
    f_kelly = kelly_fraction_binary(p_true, price)
    if max_fraction is None:
        max_fraction = f_kelly
    
    if f_kelly <= 0:
        return 0.0
    
    # Sample fractions to evaluate
    fractions = np.linspace(0, min(f_kelly, max_fraction), 50)
    
    def objective_function(f: float) -> float:
        """Calculate E[log(W)] - λ * Var[log(W)] for fraction f."""
        outcomes = []
        
        # Monte Carlo simulation for this fraction
        for _ in range(n_samples):
            wealth = 1.0
            b = (1 - price) / price
            
            # Simulate single bet
            bet = f * wealth
            win = np.random.rand() < p_true
            if win:
                wealth += bet * b
            else:
                wealth -= bet
            
            outcomes.append(np.log(wealth))
        
        outcomes = np.array(outcomes)
        expected_log_growth = outcomes.mean()
        variance_log_growth = outcomes.var()
        
        # Risk-constrained objective
        return expected_log_growth - lambda_risk * variance_log_growth
    
    # Find fraction that maximizes risk-constrained objective
    best_f = 0.0
    best_objective = -np.inf
    
    for f in fractions:
        obj_val = objective_function(f)
        if obj_val > best_objective:
            best_objective = obj_val
            best_f = f
    
    return best_f


def advanced_risk_constrained_kelly(
    p_true: float,
    price: float,
    drawdown_floor: float = 0.9,    # 10% drawdown limit
    max_probability: float = 0.1,    # 10% chance of exceeding
    method: str = "convex",          # "convex" or "monte_carlo"
    n_simulations: int = 500
) -> dict:
    """
    Advanced risk-constrained Kelly with both methods.
    
    Args:
        p_true: True win probability
        price: Market price (0-1)
        drawdown_floor: α - wealth floor (e.g., 0.9 for 10% drawdown)
        max_probability: β - tolerable probability (e.g., 0.1 for 10% chance)
        method: Which method to use ("convex" or "monte_carlo")
        n_simulations: Number of simulations for Monte Carlo method
        
    Returns:
        Dictionary with optimal fraction and method details
    """
    # Calculate λ from drawdown constraints
    lambda_risk = calculate_lambda_risk_aversion(drawdown_floor, max_probability)
    
    if method == "convex":
        optimal_f = risk_constrained_kelly_convex(p_true, price, lambda_risk)
    else:
        # Monte Carlo method
        target_dd = 1 - drawdown_floor  # Convert floor to drawdown amount
        optimal_f = solve_rck_fraction(
            p_true, price, target_dd, max_probability,
            n_paths=n_simulations, n_trades=500
        )
    
    # Get full Kelly for comparison
    f_kelly = kelly_fraction_binary(p_true, price)
    
    return {
        "optimal_fraction": optimal_f,
        "full_kelly": f_kelly,
        "fraction_of_full": optimal_f / f_kelly if f_kelly > 0 else 0,
        "lambda_risk": lambda_risk,
        "method": method,
        "drawdown_floor": drawdown_floor,
        "max_probability": max_probability,
        "constraints": {
            "max_drawdown": 1 - drawdown_floor,
            "max_probability": max_probability
        }
    }


def estimate_p_true(implied: float, features: dict) -> float:
    """
    Legacy p_true estimation function (kept for compatibility).
    
    Args:
        implied: Implied probability from Kalshi price (0-1)
        features: Feature dictionary
        
    Returns:
        Estimated true probability (0-1)
    """
    # 1) Start from model probability if available, else implied
    p = features.get("kalshi_model_prob", implied)

    # 2) Directional RTI + flow signals
    delta = 0.0
    delta += 0.10 * features.get("rti_signal", 0.0)
    delta += 0.05 * (features.get("flow_imbalance", 0.0) - 0.5)

    # 3) Fear/greed as small nudge (contrarian signal)
    delta += features.get("fg_contrarian", 0.0)

    # 4) Per-asset sentiment adjustment (15m optimized)
    asset_sentiment = features.get("asset_sentiment", 0.5)
    delta += 0.08 * (asset_sentiment - 0.5)  # Scale down asset sentiment impact

    # 5) Apply delta with bounds checking
    p_true = max(0.01, min(0.99, p + delta))
    return p_true


# ---------------------------------------------------------------------------
# Lane configuration
# ---------------------------------------------------------------------------

@dataclass
class Crypto15MLaneConfig:
    """Runtime configuration for crypto 15m lanes with RCK + Bayesian parameters."""
    # Symbol and market discovery
    symbol: CryptoSymbol
    series_ticker: str = ""  # Will be auto-generated: KXBTC, KXETH, etc.
    timeframe: str = "15m"
    max_markets_per_cycle: int = 5

    # Position sizing and risk
    max_positions: int = 1
    max_markets_live: int = 1
    base_kelly_fraction: float = 0.25
    min_edge_bps: int = 50
    fear_greed_weight: float = 0.5
    risk_stream_topic: str = ""

    # Timing constraints
    min_time_to_expiry_secs: int = 60
    max_time_to_expiry_secs: int = 15 * 60
    cycle_interval_seconds: float = 60.0
    sentiment_refresh_seconds: float = 300.0
    phase_refresh_seconds: float = 86_400.0

    # Mode and execution
    paper: bool = False  # paper ladder flag
    enable: bool = True

    # Base trade size
    base_trade_size: float = 0.10  # dollars (minimum attempt size)

    # Observability
    log_every_cycle: bool = True
    log_rationale: bool = True

    # ---------------------------------------------------------------------------
    # RCK + Bayesian Configuration (NEW)
    # ---------------------------------------------------------------------------
    
    # RCK parameters per symbol
    rck_target_drawdown: float = 0.10      # Target maximum drawdown
    rck_drawdown_probability: float = 0.10 # Max probability of exceeding target
    rck_safety_factor: float = 0.8         # Additional safety margin
    rck_min_fraction: float = 0.01         # Minimum Kelly fraction
    
    # Bayesian parameters per symbol
    bayesian_prior_strength: int = 30      # Pseudo-count n0 for Beta prior
    bayesian_rti_weight: float = 0.06      # RTI signal weight
    bayesian_flow_weight: float = 0.03     # Flow imbalance weight
    bayesian_asset_weight: float = 0.05    # Asset sentiment weight
    
    # Global safety parameters
    global_safety_factor: float = 0.8       # Additional safety factor
    min_edge_threshold_bps: float = 30.0    # Minimum edge threshold

    def __post_init__(self):
        # Auto-generate series ticker and risk topic if not provided
        if not self.series_ticker:
            self.series_ticker = f"KX{self.symbol}"
        if not self.risk_stream_topic:
            mode_suffix = ".paper" if self.paper else ""
            self.risk_stream_topic = f"risk.crypto.{self.symbol.lower()}15m{mode_suffix}"
        
        # Set symbol-specific RCK + Bayesian defaults
        self._set_symbol_defaults()
    
    def _set_symbol_defaults(self):
        """Set symbol-specific RCK and Bayesian defaults."""
        if self.symbol == "BTC":
            self.rck_target_drawdown = 0.10
            self.rck_drawdown_probability = 0.10
            self.bayesian_prior_strength = 30
        elif self.symbol == "ETH":
            self.rck_target_drawdown = 0.08
            self.rck_drawdown_probability = 0.12
            self.bayesian_prior_strength = 25
        elif self.symbol == "SOL":
            self.rck_target_drawdown = 0.05
            self.rck_drawdown_probability = 0.15
            self.bayesian_prior_strength = 40
        elif self.symbol == "XRP":
            self.rck_target_drawdown = 0.05
            self.rck_drawdown_probability = 0.15
            self.bayesian_prior_strength = 45


# ---------------------------------------------------------------------------
# Lane state
# ---------------------------------------------------------------------------

@dataclass
class LaneCycleResult:
    """Result of one Crypto15MLane cycle."""
    cycle_id: str
    timestamp: datetime
    markets_found: int
    sentiment_bundle: Optional[Dict[str, Any]]
    consensus: Optional[Dict[str, Any]]
    risk_decision: Optional[Dict[str, Any]]
    order_result: Optional[Dict[str, Any]]
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Lane implementation
# ---------------------------------------------------------------------------

class Crypto15MLane:
    """
    Orchestrates one full crypto 15m trading cycle:
    
    1. Market discovery (KalshiMarketCatalog)
    2. Sentiment aggregation (SentimentBus)
    3. Swarm consensus (SwarmConsensusAggregator)
    4. Risk evaluation (CryptoSwarmRisk + FearGreedContext)
    5. Order execution (live or paper)
    6. Observability (structured logging)
    """
    
    def __init__(
        self,
        cfg: Crypto15MLaneConfig,
        kalshi_client,
        price_feed,
        risk_bus,
        portfolio,
    ):
        self.cfg = cfg
        self.kalshi = kalshi_client
        self.price_feed = price_feed
        self.risk_bus = risk_bus
        self.portfolio = portfolio
        
        # Lane identification
        self.lane_id = f"{cfg.symbol}_15M"
        
        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_cycle: Optional[LaneCycleResult] = None
        
        # Metrics and observability
        self._cycle_count = 0
        self._last_cycle_time = 0.0
        
        logger.info("Initialized Crypto15MLane: %s (paper=%s)", self.lane_id, cfg.paper)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_cycle(self) -> Optional[LaneCycleResult]:
        return self._last_cycle

    async def start(self) -> None:
        """Start the lane's main loop."""
        if self._running:
            logger.warning("%s: already running", self.lane_id)
            return
        
        if not self.cfg.enable:
            logger.info("%s: disabled in config, not starting", self.lane_id)
            return
        
        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("%s: started (paper=%s)", self.lane_id, self.cfg.paper)

    async def stop(self) -> None:
        """Stop the lane's main loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("%s: stopped", self.lane_id)

    async def _main_loop(self) -> None:
        """Main trading loop."""
        logger.info("%s: entering main loop (interval=%.1fs)", self.lane_id, self.cfg.cycle_interval_seconds)
        
        while self._running:
            try:
                cycle_start = time.time()
                result = await self._run_cycle()
                self._last_cycle = result
                self._cycle_count += 1
                self._last_cycle_time = cycle_start
                
                # Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.cfg.cycle_interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                logger.info("%s: main loop cancelled", self.lane_id)
                break
            except Exception as exc:
                logger.error("%s: main loop error: %s", self.lane_id, exc)
                await asyncio.sleep(10)  # Brief delay on error

    async def _run_cycle(self) -> LaneCycleResult:
        """Run one complete trading cycle."""
        cycle_id = f"{self.lane_id}_{int(time.time())}"
        start_time = datetime.now(timezone.utc)
        
        logger.debug("%s: starting cycle %s", self.lane_id, cycle_id)
        
        # 1. Market discovery
        markets = await self._discover_markets()
        if not markets:
            return LaneCycleResult(
                cycle_id=cycle_id,
                timestamp=start_time,
                markets_found=0,
                sentiment_bundle=None,
                consensus=None,
                risk_decision=None,
                order_result=None,
                blocked_reason="no_markets_found"
            )
        
        # 2. Sentiment aggregation
        sentiment_bundle = await self._aggregate_sentiment()
        
        # 3. Swarm consensus
        consensus = await self._get_consensus(markets, sentiment_bundle)
        
        # 4. Risk evaluation
        risk_decision = await self._evaluate_risk(consensus, sentiment_bundle)
        
        # 5. Order execution
        order_result = None
        if risk_decision and risk_decision.get("approved", False):
            order_result = await self._execute_order(risk_decision, consensus, cycle_id)
        else:
            blocked_reason = risk_decision.get("blocked_reason", "unknown") if risk_decision else "no_risk_decision"
            logger.info("%s: order blocked: %s", self.lane_id, blocked_reason)
        
        return LaneCycleResult(
            cycle_id=cycle_id,
            timestamp=start_time,
            markets_found=len(markets),
            sentiment_bundle=sentiment_bundle,
            consensus=consensus,
            risk_decision=risk_decision,
            order_result=order_result,
            blocked_reason=risk_decision.get("blocked_reason") if risk_decision else None
        )

    async def _discover_markets(self) -> List[Dict[str, Any]]:
        """Discover suitable 15m crypto markets for this symbol."""
        try:
            # Get market catalog
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            # Only refresh if catalog is empty; the periodic _refresh_loop handles
            # routine updates (refreshing here unconditionally causes a second back-to-back
            # full refresh every time _discover_markets is called).
            if not catalog.get_all_markets():
                await catalog.refresh()

            # Filter by symbol, timeframe, and category for 15m crypto markets
            markets = catalog.get_markets_by_asset(self.cfg.symbol, timeframe="15m", category="CRYPTO")
            
            # Apply timing constraints
            now = time.time()
            filtered_markets = []
            for market in markets:
                if not market.market.active:
                    continue
                
                # Check expiry constraints
                if market.market.close_time:
                    time_to_expiry = market.market.close_time.timestamp() - now
                    if not (self.cfg.min_time_to_expiry_secs <= time_to_expiry <= self.cfg.max_time_to_expiry_secs):
                        continue
                
                filtered_markets.append({
                    "ticker": market.market.ticker,
                    "title": market.market.title,
                    "yes_price_cents": market.market.yes_price,  # Keep as cents for clarity
                    "no_price_cents": market.market.no_price,
                    "close_time": market.market.close_time,
                })
            
            # Limit number of markets
            filtered_markets = filtered_markets[:self.cfg.max_markets_per_cycle]
            
            logger.debug("%s: found %d suitable 15m crypto markets", self.lane_id, len(filtered_markets))
            return filtered_markets
            
        except Exception as exc:
            logger.error("%s: market discovery failed: %s", self.lane_id, exc)
            return []

    async def _aggregate_sentiment(self) -> Optional[Dict[str, Any]]:
        """Aggregate sentiment data optimized for 15m crypto trading."""
        try:
            # Get Fear & Greed context (global risk dial)
            from merid.prediction.fear_greed_context import get_fear_greed_context_service
            fg_service = get_fear_greed_context_service()
            fg_snapshot = await fg_service.get_snapshot()
            
            # Get Kalshi signals (includes Fear & Greed)
            kalshi_fg_data = {}
            try:
                from merid.signals.kalshi_signals import get_kalshi_signal_generator
                signal_generator = get_kalshi_signal_generator()
                kalshi_signals = await signal_generator.generate_all()
                
                # Filter for Fear & Greed signals
                fg_signals = [s for s in kalshi_signals if hasattr(s, 'signal_type') and s.signal_type == 'fear_greed']
                kalshi_fg_data = fg_signals[0].to_dict() if fg_signals else {}
            except Exception as exc:
                logger.debug("%s: Kalshi signals unavailable: %s", self.lane_id, exc)
            
            # Optimized 15m sentiment features per asset
            asset_sentiment = await self._get_asset_sentiment_15m()
            
            # Combine sentiment sources with 15m optimization
            sentiment_bundle = {
                "fear_greed": {
                    "score": fg_snapshot.score,
                    "classification": fg_snapshot.classification,
                    "trend": fg_snapshot.trend,
                    "contrarian_signal": fg_snapshot.contrarian_signal,
                    "is_extreme_fear": fg_snapshot.is_extreme_fear,
                    "is_extreme_greed": fg_snapshot.is_extreme_greed,
                },
                "kalshi_signals": kalshi_fg_data,
                "asset_sentiment_15m": asset_sentiment,  # Per-asset fast sentiment
                "weight": self.cfg.fear_greed_weight,
                "lookback_minutes": 30,  # Tight lookback for 15m trading
            }
            
            logger.debug("%s: sentiment aggregated (15m optimized)", self.lane_id)
            return sentiment_bundle
            
        except Exception as exc:
            logger.error("%s: sentiment aggregation failed: %s", self.lane_id, exc)
            return None

    async def _get_asset_sentiment_15m(self) -> Dict[str, Any]:
        """Get fast, per-asset sentiment optimized for 15m horizons."""
        try:
            # Try to pull real per-asset sentiment from the sentiment bus
            try:
                from merid.sentiment.sentiment_bus import get_sentiment_bus
                bus = get_sentiment_bus()
                bundle = bus.get_latest(self.cfg.symbol)
                if bundle:
                    return {
                        "symbol": self.cfg.symbol,
                        "sentiment_score_5m": float(bundle.get("score_5m", 0.0)),
                        "sentiment_score_15m": float(bundle.get("score_15m", 0.0)),
                        "sentiment_score_30m": float(bundle.get("score_30m", 0.0)),
                        "sentiment_trend": bundle.get("trend", "neutral"),
                        "social_volume": int(bundle.get("social_volume", 0)),
                        "news_sentiment": float(bundle.get("news_sentiment", 0.0)),
                        "technical_signal": float(bundle.get("technical_signal", 0.0)),
                        "confidence": float(bundle.get("confidence", 0.0)),
                    }
            except Exception as exc:
                logger.debug("%s: sentiment bus unavailable: %s", self.lane_id, exc)

            # Honest zeros — no fake bullish bias
            return {
                "symbol": self.cfg.symbol,
                "sentiment_score_5m": 0.0,
                "sentiment_score_15m": 0.0,
                "sentiment_score_30m": 0.0,
                "sentiment_trend": "neutral",
                "social_volume": 0,
                "news_sentiment": 0.0,
                "technical_signal": 0.0,
                "confidence": 0.0,
            }

        except Exception as exc:
            logger.debug("%s: Failed to get asset sentiment: %s", self.lane_id, exc)
            return {}

    async def _get_consensus(self, markets: List[Dict[str, Any]], sentiment_bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Get swarm consensus for trading decision with proper bps math."""
        try:
            if not markets:
                return None
            
            # Select best market (simplified - would use edge calculations in production)
            best_market = markets[0]
            
            # Apply Fear & Greed contrarian signal (global risk dial)
            edge_adjustment = 0.0
            if sentiment_bundle and "fear_greed" in sentiment_bundle:
                fg = sentiment_bundle["fear_greed"]
                edge_adjustment = fg["contrarian_signal"] * sentiment_bundle.get("weight", 0.5)
            
            # Apply per-asset sentiment adjustments for 15m trading
            asset_adj = 0.0
            if sentiment_bundle and "asset_sentiment_15m" in sentiment_bundle:
                asset = sentiment_bundle["asset_sentiment_15m"]
                # Use 15m sentiment score as additional edge signal
                asset_score = asset.get("sentiment_score_15m", 0.5)
                asset_adj = (asset_score - 0.5) * 0.3  # Scale down asset sentiment impact
                
                # Boost confidence for high-volume assets
                if asset.get("social_volume", 0) > 100:
                    asset_adj *= 1.2
            
            # Advanced p_true estimation with vig adjustment and Bayesian updating
            yes_price_cents = best_market.get("yes_price_cents", 50)
            no_price_cents = 100 - yes_price_cents  # NO price is complement of YES price
            
            # Extract features for p_true estimation
            features = {
                "rti_signal": 0.0,           # RTI directional signal (placeholder)
                "fg_contrarian": 0.0,         # Fear & Greed contrarian signal
                "flow_imbalance": 0.5,        # Order flow imbalance (placeholder)
                "asset_sentiment": 0.5,       # Per-asset sentiment
            }
            
            # Add Fear & Greed contrarian signal
            if sentiment_bundle and "fear_greed" in sentiment_bundle:
                fg = sentiment_bundle["fear_greed"]
                features["fg_contrarian"] = fg.get("contrarian_signal", 0.0)
            
            # Add per-asset sentiment from 15m optimized features
            if sentiment_bundle and "asset_sentiment_15m" in sentiment_bundle:
                asset = sentiment_bundle["asset_sentiment_15m"]
                features["asset_sentiment"] = asset.get("sentiment_score_15m", 0.5)
                features["flow_imbalance"] = 0.5 + (asset.get("social_volume", 0) / 200.0)  # Normalize volume
            
            # Get historical performance data
            historical_wins = getattr(self, '_historical_wins', 0)
            historical_losses = getattr(self, '_historical_losses', 0)
            
            # Advanced p_true estimation with vig adjustment
            p_true_result = estimate_p_true_advanced(
                symbol=self.cfg.symbol,
                yes_price_cents=yes_price_cents,
                no_price_cents=no_price_cents,
                features=features,
                historical_wins=historical_wins,
                historical_losses=historical_losses
            )
            
            p_true = p_true_result["p_true"]
            fair_yes_prob = p_true_result["fair_yes_prob"]
            fair_no_prob = p_true_result["fair_no_prob"]
            
            # Edge calculation: edge = p_true - p_implied (using de-vigged implied)
            edge_prob = p_true - fair_yes_prob
            edge_pct = edge_prob * 100.0       # Convert to percentage points
            edge_bps = edge_pct * 100.0        # Convert to bps
            
            # Edge calculation: edge = p_true - p_implied (already calculated above)
            # No additional adjustments needed since p_true already incorporates sentiment
            
            consensus = {
                "market_id": best_market["ticker"],
                "market_title": best_market["title"],
                "direction": "yes" if edge_bps > 0 else "no",
                "p_true": p_true,                    # Advanced Bayesian estimated true probability
                "p_implied": fair_yes_prob,           # De-vigged market implied probability
                "yes_price_cents": yes_price_cents,
                "no_price_cents": no_price_cents,
                "fair_yes_prob": fair_yes_prob,      # De-vigged YES probability
                "fair_no_prob": fair_no_prob,        # De-vigged NO probability
                "edge_bps": edge_bps,                # Edge in bps (p_true - p_implied)
                "features": features,                 # Debug: features used for p_true
                # Advanced Bayesian learning details
                "bayesian_learning": {
                    "prior_strength": p_true_result["prior_strength"],
                    "posterior_alpha": p_true_result["posterior_alpha"],
                    "posterior_beta": p_true_result["posterior_beta"],
                    "posterior_mean": p_true_result["posterior_mean"],
                    "historical_wins": p_true_result["historical_wins"],
                    "historical_losses": p_true_result["historical_losses"],
                    "total_historical": p_true_result["total_historical"],
                    "feature_adjustment": p_true_result["feature_adjustment"],
                    "confidence": p_true_result["confidence"],
                }
            }
            
            logger.debug("%s: consensus: p_true=%.3f, p_implied=%.3f, edge_bps=%.1f (advanced)", 
                        self.lane_id, p_true, fair_yes_prob, edge_bps)
            return consensus
            
        except Exception as exc:
            logger.error("%s: consensus calculation failed: %s", self.lane_id, exc)
            return None

    async def _evaluate_risk(self, consensus: Optional[Dict[str, Any]], sentiment_bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Evaluate risk and decide whether to trade with Kelly sizing."""
        try:
            if not consensus:
                return None
            
            edge_bps = consensus.get("edge_bps", 0)
            
            # Check minimum edge requirement
            if abs(edge_bps) < self.cfg.min_edge_bps:
                return {
                    "approved": False,
                    "blocked_reason": f"edge_too_small: {edge_bps:.1f} < {self.cfg.min_edge_bps}",
                    "edge_bps": edge_bps,
                }
            
            # Check position limits with real position counts
            current_positions = await self._get_current_positions()
            if current_positions >= self.cfg.max_positions:
                return {
                    "approved": False,
                    "blocked_reason": f"max_positions_reached: {current_positions} >= {self.cfg.max_positions}",
                    "current_positions": current_positions,
                }
            
            # Advanced risk-constrained Kelly sizing with RCK solver
            p_true = consensus["p_true"]          # Advanced Bayesian estimated true probability
            price = consensus["yes_price_cents"] / 100.0  # Convert to decimal
            
            if not (0 < p_true < 1) or price <= 0:
                return {
                    "approved": False,
                    "blocked_reason": f"invalid_inputs: p_true={p_true}, price={price}",
                    "edge_bps": edge_bps,
                }
            
            # Use advanced RCK solver with symbol-specific constraints
            try:
                # Configure RCK constraints based on symbol volatility
                if self.cfg.symbol == "BTC":
                    target_dd = 0.10      # 10% drawdown limit
                    dd_prob = 0.10        # 10% chance of exceeding
                elif self.cfg.symbol == "ETH":
                    target_dd = 0.08       # 8% drawdown limit  
                    dd_prob = 0.12         # 12% chance of exceeding
                else:  # SOL, XRP (higher volatility)
                    target_dd = 0.05       # 5% drawdown limit
                    dd_prob = 0.15         # 15% chance of exceeding
                
                # Solve RCK using Monte Carlo approximation
                f_rck = solve_rck_fraction(
                    p_true=p_true,
                    price=price,
                    target_dd=target_dd,
                    dd_prob=dd_prob,
                    n_paths=1000,
                    n_trades=500
                )
                
                # Get full Kelly for comparison
                f_full = kelly_fraction_binary(p_true, price)
                
                # Apply additional safety factor (fractional Kelly)
                f_used = f_rck * 0.8  # Additional 20% safety margin
                
                logger.debug("%s: RCK solved: f_rck=%.4f, f_used=%.4f (fraction_of_full=%.3f)", 
                           self.lane_id, f_rck, f_used, f_used / f_full if f_full > 0 else 0)
                
            except Exception as exc:
                # Fallback to simple fractional Kelly on error
                logger.warning("%s: RCK solver failed, using fallback: %s", self.lane_id, exc)
                f_full = kelly_fraction_binary(p_true, price)
                f_used = f_full * self.cfg.base_kelly_fraction  # Fallback to configured fraction
            
            # Get bankroll and calculate position size
            try:
                bankroll = self.portfolio.get_lane_bankroll(self.lane_id)
            except Exception:
                bankroll = self.cfg.base_trade_size * 100  # Fallback bankroll
            
            # Position sizing with RCK
            kelly_size = bankroll * f_used
            position_size = max(self.cfg.base_trade_size, kelly_size)
            
            # Optional Fear & Greed scaling (as size modifier, not directional)
            fg_multiplier = 1.0
            if sentiment_bundle and "fear_greed" in sentiment_bundle:
                fg = sentiment_bundle["fear_greed"]
                if fg["is_extreme_fear"]:
                    fg_multiplier = 1.05  # Very small increase in RCK mode
                elif fg["is_extreme_greed"]:
                    fg_multiplier = 0.95  # Very small decrease in RCK mode
            
            position_size *= fg_multiplier
            
            risk_decision = {
                "approved": True,
                "position_size": position_size,
                "edge_bps": edge_bps,
                "direction": consensus["direction"],
                "market_id": consensus["market_id"],
                "p_true": p_true,
                "p_implied": consensus["p_implied"],
                "price": price,
                "current_positions": current_positions,
                "kelly_fraction_full": f_full,
                "kelly_fraction_used": f_used,
                "bankroll": bankroll,
                "kelly_size": kelly_size,
                "fear_greed_applied": sentiment_bundle is not None,
                "fg_multiplier": fg_multiplier,
                # Advanced RCK solver details
                "risk_constrained_kelly": {
                    "method": "rck_solver",
                    "f_rck": f_rck if 'f_rck' in locals() else None,
                    "target_drawdown": target_dd if 'target_dd' in locals() else None,
                    "drawdown_probability": dd_prob if 'dd_prob' in locals() else None,
                    "safety_factor": 0.8,
                    "fraction_of_full": f_used / f_full if f_full > 0 else 0,
                    "solver_paths": 1000,
                    "solver_trades": 500,
                }
            }
            
            logger.debug("%s: risk approved: size=%.2f, edge_bps=%.1f, kelly=%.4f (RCK solver)", 
                        self.lane_id, position_size, edge_bps, f_used)
            return risk_decision
            
        except Exception as exc:
            logger.error("%s: risk evaluation failed: %s", self.lane_id, exc)
            return None

    async def _execute_order(self, risk_decision: Dict[str, Any], consensus: Dict[str, Any], cycle_id: str) -> Optional[Dict[str, Any]]:
        """Execute order (live or paper)."""
        try:
            order = {
                "market_id": risk_decision["market_id"],
                "side": risk_decision["direction"],
                "size": risk_decision["position_size"],
                "edge_bps": risk_decision["edge_bps"],
                "cycle_id": cycle_id,
            }
            
            # Check with risk bus first
            ctx = {
                "edge_bps": risk_decision["edge_bps"],
                "probability": risk_decision.get("p_true", 0.5),
                "direction": risk_decision["direction"],
                "fear_greed_weight": consensus.get("sentiment_weight", 0.0),
            }
            
            allowed = await self.risk_bus.check_lane_order(self.lane_id, order, ctx)
            if not allowed:
                logger.debug("%s: order blocked by risk_bus", self.lane_id)
                return {"submitted": False, "reason": "risk_bus_blocked", "cycle_id": cycle_id}

            # Paper vs Live execution
            if self.cfg.paper:
                return await self._execute_paper_order(order, ctx)
            else:
                return await self._execute_live_order(order, ctx, consensus)
                
        except Exception as exc:
            logger.error("%s: order execution failed: %s", self.lane_id, exc)
            return {"submitted": False, "reason": str(exc), "cycle_id": cycle_id}

    async def _execute_paper_order(self, order: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Execute paper order (virtual fill)."""
        try:
            # Paper ladder: record virtual fill, no Kalshi side effect
            await self.portfolio.paper_fill(order, ctx)
            await self.risk_bus.publish_order_event(self.cfg.risk_stream_topic, order, ctx)
            
            logger.info(
                "%s[PAPER]: simulated %s on %s size=%.2f edge_bps=%.1f",
                self.lane_id,
                order["side"],
                order["market_id"],
                order["size"],
                ctx["edge_bps"],
            )
            
            return {
                "submitted": True,
                "simulated": True,
                "mode": "paper",
                "market_id": order["market_id"],
                "side": order["side"],
                "size": order["size"],
                "edge_bps": ctx["edge_bps"],
                "cycle_id": order["cycle_id"],
            }
            
        except Exception as exc:
            logger.error("%s: paper order failed: %s", self.lane_id, exc)
            return {"submitted": False, "reason": str(exc), "cycle_id": order["cycle_id"]}

    async def _execute_live_order(self, order: Dict[str, Any], ctx: Dict[str, Any], consensus: Dict[str, Any]) -> Dict[str, Any]:
        """Execute live order on Kalshi with proper API fields."""
        try:
            # Calculate contract details with proper Kalshi API format
            limit_prob = consensus.get("probability", 0.5)   # 0-1 probability
            price_cents = max(int(limit_prob * 100), 1)     # Kalshi expects price in cents
            
            # Calculate contracts based on position size and price
            price_dollars = price_cents / 100.0
            contracts = max(1, int(order["size"] / price_dollars))

            order_result = await self.kalshi.place_order(
                market_ticker=order["market_id"],
                outcome=order["side"].upper(),  # "YES" / "NO"
                side="buy",
                quantity=contracts,
                order_type="limit",
                price=price_cents,
                metadata={"cycle_id": order["cycle_id"]},
            )
            
            await self.risk_bus.publish_order_event(self.cfg.risk_stream_topic, order, ctx)
            
            logger.info(
                "%s: placed %s on %s size=%.2f edge_bps=%.1f price=%d¢ contracts=%d",
                self.lane_id,
                order["side"],
                order["market_id"],
                order["size"],
                ctx["edge_bps"],
                price_cents,
                contracts,
            )
            
            return {
                "submitted": True,
                "simulated": False,
                "mode": "live",
                "market_id": order["market_id"],
                "side": order["side"],
                "size": order["size"],
                "contracts": contracts,
                "price_cents": price_cents,
                "order_result": order_result,
                "cycle_id": order["cycle_id"],
            }
            
        except Exception as exc:
            logger.warning("%s: order failed: %s", self.lane_id, exc)
            return {"submitted": False, "reason": str(exc), "cycle_id": order["cycle_id"]}

    async def _get_current_positions(self) -> int:
        """Get current number of open positions from portfolio."""
        try:
            return await self.portfolio.count_open_positions(
                symbol=self.cfg.symbol,
                timeframe=self.cfg.timeframe,
                mode="paper" if self.cfg.paper else "live",
            )
        except Exception as exc:
            logger.debug("%s: failed to get position count: %s", self.lane_id, exc)
            return 0

    def update_historical_performance(self, won: bool):
        """
        Update historical win/loss record for Bayesian p_true estimation.
        
        Args:
            won: True if the trade was a winner, False if loser
        """
        if won:
            self._historical_wins = getattr(self, '_historical_wins', 0) + 1
        else:
            self._historical_losses = getattr(self, '_historical_losses', 0) + 1
        
        logger.debug("%s: updated historical record: %d wins, %d losses", 
                    self.lane_id, self._historical_wins, self._historical_losses)

    def get_bayesian_stats(self) -> Dict[str, Any]:
        """Get Bayesian learning statistics for monitoring."""
        wins = getattr(self, '_historical_wins', 0)
        losses = getattr(self, '_historical_losses', 0)
        total = wins + losses
        
        if total == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "sample_size": 0,
                "confidence": "insufficient_data"
            }
        
        win_rate = wins / total
        # Approximate confidence interval width (simplified)
        confidence_interval = 1.96 * (win_rate * (1 - win_rate) / total) ** 0.5
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "sample_size": total,
            "confidence_interval": confidence_interval,
            "confidence": "high" if total >= 30 else "medium" if total >= 10 else "low"
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current lane status for monitoring with advanced RCK and Bayesian data."""
        # Extract metrics from last cycle
        last_edge = 0.0
        last_p_true = 0.0
        last_p_implied = 0.0
        fg_contrarian = 0.0
        kelly_used = 0.0
        rck_method = "none"
        lambda_risk = None
        fraction_of_full = 0.0
        
        if self._last_cycle and self._last_cycle.consensus:
            consensus = self._last_cycle.consensus
            last_edge = float(consensus.get("edge_bps", 0.0))
            last_p_true = float(consensus.get("p_true", 0.0))
            last_p_implied = float(consensus.get("p_implied", 0.0))
        
        if self._last_cycle and self._last_cycle.sentiment_bundle:
            fg = self._last_cycle.sentiment_bundle.get("fear_greed", {})
            fg_contrarian = float(fg.get("contrarian_signal", 0.0))
        
        if self._last_cycle and self._last_cycle.risk_decision:
            risk = self._last_cycle.risk_decision
            kelly_used = float(risk.get("kelly_fraction_used", 0.0))
            
            # Extract RCK details
            rck_info = risk.get("risk_constrained_kelly", {})
            rck_method = rck_info.get("method", "none")
            lambda_risk = rck_info.get("lambda_risk")
            fraction_of_full = rck_info.get("fraction_of_full", 0.0)

        # Get Bayesian learning statistics
        bayesian_stats = self.get_bayesian_stats()

        return {
            "lane_id": self.lane_id + ("_PAPER" if self.cfg.paper else ""),
            "symbol": self.cfg.symbol,
            "running": self._running,
            "enabled": self.cfg.enable,
            "paper": self.cfg.paper,
            "cycle_count": self._cycle_count,
            "last_cycle_time": self._last_cycle_time,
            "last_cycle": self._last_cycle.timestamp.isoformat() if self._last_cycle else None,
            "last_edge_bps": last_edge,
            "last_p_true": last_p_true,        # Bayesian estimated true probability
            "last_p_model": last_p_true,       # Alias for UI compatibility
            "last_p_implied": last_p_implied, # De-vigged market implied probability
            "last_fg_contrarian": fg_contrarian,
            "last_kelly_used": kelly_used,
            "bayesian_learning": bayesian_stats,  # Historical performance stats
            "risk_constrained_kelly": {
                "method": rck_method,
                "lambda_risk": lambda_risk,
                "fraction_of_full": fraction_of_full,
                "constraints": {
                    "drawdown_limit": "10%" if self.cfg.symbol == "BTC" else "8%" if self.cfg.symbol == "ETH" else "5%",
                    "max_probability": "10%" if self.cfg.symbol == "BTC" else "12%" if self.cfg.symbol == "ETH" else "15%"
                }
            },
            "open_positions": 0,  # Will be updated by real position counting
            "max_positions": self.cfg.max_positions,
            "markets_live": 0,     # Will be updated by market discovery
            "max_markets_live": self.cfg.max_markets_live,
            "last_updated": self._last_cycle_time,
            "config": {
                "max_positions": self.cfg.max_positions,
                "base_kelly_fraction": self.cfg.base_kelly_fraction,
                "min_edge_bps": self.cfg.min_edge_bps,
                "fear_greed_weight": self.cfg.fear_greed_weight,
            },
        }

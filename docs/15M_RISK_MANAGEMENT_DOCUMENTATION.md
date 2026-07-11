# Kalshi 15m Risk Management and Position Limits Documentation

## Overview

The Kalshi 15m risk management system enforces position limits, exposure tracking, and drawdown-based scaling for the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE). The system uses a shared $1 exposure cap across all assets, with window-based tracking and adaptive risk bands.

## Architecture

### Component Hierarchy

```
KalshiCrypto15mRiskEnvelope (Risk Parameters)
├── GlobalAllocator (Order Selection)
│   └── OrderCandidate (Potential Orders)
└── Window Tracking (Module-Level State)
    ├── Agent Exposure Tracking
    ├── Total Venue Exposure Tracking
    └── Per-Asset Exposure Tracking
```

### Key Files

- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- **Global Allocator**: `merid/risk/profiles/global_allocator.py`
- **Position Cache**: `merid/event_venues/kalshi/position_cache.py`
- **Position Monitor**: `merid/position_management/position_monitor.py`
- **Kalshi Risk**: `merid/event_venues/kalshi/kalshi_risk.py`

## Risk Envelope (KalshiCrypto15mRiskEnvelope)

### Purpose

The risk envelope is the single source of truth for all risk parameters for the kalshi_crypto_15m_v2 profile. All values are derived from profile config and live bankroll, with no hardcoded values.

### Module-Level Window Tracking (CRITICAL FIX 2026-07-06)

**Problem**: `get_kalshi_crypto_15m_risk_envelope()` computes a FRESH envelope on every call, so window exposure stored on envelope instances was discarded immediately. `check_window_limit()` always saw $0 exposure and the fixed $1.00 cap never engaged.

**Solution**: Window tracking state MUST live at module level so every envelope instance reads/writes the same cumulative exposure for the current 15m window.

```python
_WINDOW_TRACKING_LOCK = threading.Lock()
_WINDOW_TRACKING_STATE: Dict[str, Any] = {
    "window_start_ts": 0.0,
    "agent_exposure_usd": {},   # agent_id -> cumulative executed notional this window
    "total_exposure_usd": 0.0,  # cumulative executed notional across all agents this window
    "agent_resting_exposure_usd": {},  # agent_id -> cumulative resting order notional this window
    "total_resting_exposure_usd": 0.0,  # cumulative resting order notional across all agents this window
    "peak_bankroll_usd": 0.0,  # Peak bankroll at window start for consistent $1 cap calculation
    "asset_exposure_usd": {},  # asset -> cumulative executed notional this window (for monitoring, not enforcement)
}
```

**Window Alignment**: Windows are aligned to epoch 900s boundaries to match Kalshi 15m market windows (e.g., 06:00:00-06:15:00).

### Key Parameters

```python
@dataclass
class KalshiCrypto15mRiskEnvelope:
    # Input Parameters
    live_bankroll_usd: float
    profile_capital_usd: float  # From profile YAML (0 = use live bankroll)
    
    # Computed Venue-Level Caps
    max_single_order_notional_usd: float
    max_total_notional_usd: float
    max_concurrent_trades: int
    
    # Per-Asset Caps (BTC/ETH/SOL/XRP/DOGE)
    asset_max_notional_usd: Dict[str, float]
    
    # Depth Thresholds (single source of truth for 15m stack)
    asset_depth_thresholds: Dict[str, Dict[str, int]]
    
    # Per-Agent Defaults
    agent_max_notional_usd: float
    agent_max_orders_per_window: int
    agent_max_yes_position: int
    agent_max_no_position: int
    
    # Cycle Risk Cap
    max_cycle_risk_pct: float
    
    # Window-Based Risk Tracking (HARD STOP)
    # CRITICAL: Uses fixed $1.00 exposure cap (MERID_FIXED_EXPOSURE_CAP_USD)
    # Percentage-based limits (3% per-agent, 5% total venue) are DISABLED
    guardrails_per_window_risk_pct: float  # DEPRECATED: Not used (fixed $1 cap instead)
    guardrails_total_venue_risk_pct: float  # DEPRECATED: Not used (fixed $1 cap instead)
    per_agent_window_limit_usd: float  # DEPRECATED: Not used (fixed $1 cap instead)
    total_venue_window_limit_usd: float  # Fixed $1.00 exposure cap (MERID_FIXED_EXPOSURE_CAP_USD)
    
    # Window tracking state
    window_start_ts: float
    agent_window_exposure_usd: Dict[str, float]
    total_window_exposure_usd: float
    agent_resting_exposure_usd: Dict[str, float]
    total_resting_exposure_usd: float
    
    # Guardrails
    daily_loss_enabled: bool
    max_daily_loss_usd: float
    drawdown_halt_pct: float
    drawdown_unwind_pct: float
    
    # Drawdown Tracking
    peak_equity_usd: float
    current_equity_usd: float
    current_drawdown_pct: float
    
    # Kelly Fraction
    kelly_fraction: float
    
    # Adaptive Risk Scaling
    adaptive_risk_bands: List[Dict[str, float]]
    per_trade_risk_multiplier: float
    is_halted: bool
    current_risk_band: RiskBand
    resume_if_drawdown_improves: bool
    
    # Correlation Tracking
    correlation_tracking_enabled: bool
    correlation_threshold: float
    correlation_multiplier: float
```

### Risk Bands

```python
class RiskBand(Enum):
    """Explicit risk bands for drawdown-based scaling."""
    NORMAL = "normal"      # 0-10% drawdown, 100% risk multiplier
    WARNING = "warning"    # 10-12% drawdown, 50% risk multiplier
    DOWNSIZE = "downsize"  # 12-15% drawdown, 25% risk multiplier
    HALT = "halt"          # 15%+ drawdown, 0% risk multiplier (manual resume required)
```

### Drawdown Tracking

```python
def update_drawdown(self, current_equity_usd: float):
    """Update drawdown tracking with current equity."""
    
    # Validate input
    if current_equity_usd is None or current_equity_usd < 0:
        raise ValueError(f"Invalid current_equity_usd: {current_equity_usd}")
    
    self.current_equity_usd = current_equity_usd
    
    # Update peak equity
    if current_equity_usd > self.peak_equity_usd:
        self.peak_equity_usd = current_equity_usd
        logger.info(f"[DRAWDOWN] New peak equity: ${self.peak_equity_usd:.2f}")
    
    # Handle fresh account (peak_equity == 0)
    if self.peak_equity_usd == 0:
        self.current_drawdown_pct = 0.0
        logger.warning("[DRAWDOWN] Peak equity is 0, treating as fresh account")
    else:
        # Compute drawdown with floating-point tolerance
        self.current_drawdown_pct = (self.peak_equity_usd - current_equity_usd) / self.peak_equity_usd
        self.current_drawdown_pct = max(0.0, min(1.0, self.current_drawdown_pct))
    
    # Update adaptive risk and halt state
    self._update_adaptive_risk()
    
    # Set halt state based on drawdown threshold
    self.is_halted = self.current_drawdown_pct >= self.drawdown_halt_pct
```

### Adaptive Risk Scaling

```python
def _update_adaptive_risk(self):
    """Update per-trade risk multiplier based on drawdown bands."""
    
    for band in self.adaptive_risk_bands:
        if self.current_drawdown_pct <= band['max_drawdown_pct']:
            self.per_trade_risk_multiplier = band['multiplier']
            
            # Map multiplier to explicit RiskBand
            if band['multiplier'] == 1.0:
                self.current_risk_band = RiskBand.NORMAL
            elif band['multiplier'] == 0.5:
                self.current_risk_band = RiskBand.WARNING
            elif band['multiplier'] == 0.25:
                self.current_risk_band = RiskBand.DOWNSIZE
            elif band['multiplier'] == 0.0:
                self.current_risk_band = RiskBand.HALT
            else:
                self.current_risk_band = RiskBand.NORMAL
            
            logger.info(
                f"[RISK-ENVELOPE] Band change: drawdown={self.current_drawdown_pct:.2%}, "
                f"multiplier={self.per_trade_risk_multiplier:.2f}, "
                f"band={self.current_risk_band.value}"
            )
            return
    
    # Default to halt if no band matches
    self.per_trade_risk_multiplier = 0.0
    self.current_risk_band = RiskBand.HALT
    logger.warning(
        f"[RISK-ENVELOPE] Halt triggered: drawdown={self.current_drawdown_pct:.2%} >= halt={self.drawdown_halt_pct:.2%}"
    )
```

### Window Limit Check (HARD STOP)

```python
def check_window_limit(
    self,
    agent_id: str,
    order_notional_usd: float,
    current_ts: float,
    custom_per_agent_limit_pct: Optional[float] = None,
    custom_total_venue_limit_pct: Optional[float] = None,
    asset: Optional[str] = None,
) -> tuple[bool, str]:
    """Check if order would exceed window-based risk limits (HARD STOP).
    
    CRITICAL FIX 2026-07-08: 
    - Uses peak bankroll at window start for consistent 5% calculation
    - Adds 3% per-asset window limit enforcement
    
    Returns:
        Tuple of (allowed, reason)
    """
    
    # Read cumulative exposure from module-level shared state
    with _WINDOW_TRACKING_LOCK:
        _roll_window_if_needed_locked(current_ts, self.live_bankroll_usd)
        current_agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0)
        current_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        current_agent_resting = _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"].get(agent_id, 0.0)
        current_total_resting = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
        peak_bankroll_usd = _WINDOW_TRACKING_STATE["peak_bankroll_usd"] or self.live_bankroll_usd
        current_asset_exposure = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0) if asset else 0.0
    
    # CRITICAL FIX 2026-07-10: DISABLED per-agent limit check
    # The global slot allocator enforces $1.00 total cap across all 5 agents
    # Per-agent limit check was blocking each agent at $1.00 individually
    fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
    total_venue_limit_usd = custom_total_venue_limit_pct if custom_total_venue_limit_pct else fixed_exposure_cap_usd
    
    # CRITICAL FIX 2026-07-10: DISABLED per-asset limit check
    # The global slot allocator enforces $1.00 total cap across all 5 assets
    # Per-asset limit check was redundant and conflicted with slot allocator
    
    # Calculate total venue window limit (including resting orders)
    new_total_exposure = current_total_exposure + order_notional_usd
    new_total_venue = new_total_exposure + current_total_resting  # Executed + Resting
    
    # Check total venue window limit (HARD STOP) - includes resting orders
    if new_total_venue > total_venue_limit_usd:
        reason = (
            f"total_venue_window_limit: "
            f"executed=${current_total_exposure:.2f} + resting=${current_total_resting:.2f} + order=${order_notional_usd:.2f} "
            f"= ${new_total_venue:.2f} > limit=${total_venue_limit_usd:.2f} - HARD STOP"
        )
        logger.warning(f"[WINDOW-TRACKING] {reason}")
        return False, reason
    
    logger.info(
        f"[WINDOW-TRACKING] Window check OK: agent={agent_id} asset={asset or 'N/A'} "
        f"venue_exposure=${current_total_exposure:.2f}+${order_notional_usd:.2f} <= ${total_venue_limit_usd:.2f}"
    )
    return True, ""
```

**CRITICAL FIX 2026-07-10**: Per-agent and per-asset limit checks DISABLED. The global slot allocator is the single source of truth for $1.00 total exposure enforcement across all 5 assets. This allows agents to compete for the shared $1.00 pool based on edge quality.

### Order Execution Recording

```python
def record_order_execution(
    self,
    agent_id: str,
    order_notional_usd: float,
    asset: Optional[str] = None,
) -> None:
    """Record order execution in window tracking.
    
    CRITICAL FIX 2026-07-08: Added asset parameter for per-asset exposure tracking.
    """
    
    with _WINDOW_TRACKING_LOCK:
        # Update agent exposure
        _WINDOW_TRACKING_STATE["agent_exposure_usd"][agent_id] = (
            _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0) + order_notional_usd
        )
        
        # Update total exposure
        _WINDOW_TRACKING_STATE["total_exposure_usd"] += order_notional_usd
        
        # Update per-asset exposure
        if asset:
            _WINDOW_TRACKING_STATE["asset_exposure_usd"][asset] = (
                _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0) + order_notional_usd
            )
    
    logger.info(
        f"[WINDOW-TRACKING] Recorded execution: agent={agent_id} asset={asset or 'N/A'} "
        f"notional=${order_notional_usd:.2f}"
    )
```

### Window Roll

```python
def _roll_window_if_needed_locked(current_ts: float, current_bankroll_usd: float = 0.0) -> None:
    """Reset shared window state when a new 15m window begins. Caller holds lock.
    
    CRITICAL FIX 2026-07-08: Capture peak bankroll at window start for consistent 5% calculation.
    """
    bucket_start = _window_bucket_start(current_ts)
    if bucket_start != _WINDOW_TRACKING_STATE["window_start_ts"]:
        old_window_start = _WINDOW_TRACKING_STATE["window_start_ts"]
        old_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        _WINDOW_TRACKING_STATE["window_start_ts"] = bucket_start
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["asset_exposure_usd"] = {}
        
        # Lock in peak bankroll at window start
        if current_bankroll_usd > 0:
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = current_bankroll_usd
        elif _WINDOW_TRACKING_STATE["peak_bankroll_usd"] > 0:
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = _WINDOW_TRACKING_STATE["peak_bankroll_usd"]
        else:
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = current_bankroll_usd
        
        logger.info(
            f"[WINDOW-TRACKING] New 15m window started at ts={bucket_start:.0f} - "
            f"old_window_start={old_window_start:.0f} "
            f"old_total_exposure=${old_total_exposure:.2f} "
            f"peak_bankroll=${_WINDOW_TRACKING_STATE['peak_bankroll_usd']:.2f}"
        )
```

### Force Reset (Recovery)

```python
def force_reset_window_exposure(envelope=None, reason="startup") -> None:
    """Force reset window exposure tracking state.
    
    CRITICAL: This is for recovery when window exposure gets stuck due to
    missing position closure events (e.g., positions closed outside the system,
    or shutdown before closure events were processed).
    """
    import time
    current_ts = time.time()
    
    with _WINDOW_TRACKING_LOCK:
        stale_agent_exposure = dict(_WINDOW_TRACKING_STATE["agent_exposure_usd"])
        stale_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        stale_window_start = _WINDOW_TRACKING_STATE["window_start_ts"]
        
        _WINDOW_TRACKING_STATE["window_start_ts"] = _window_bucket_start(current_ts)
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = 0.0
        _WINDOW_TRACKING_STATE["asset_exposure_usd"] = {}
    
    logger.warning(
        f"[WINDOW-TRACKING] FORCE RESET at ts={current_ts:.0f} - "
        f"reason={reason} "
        f"stale_total_exposure=${stale_total_exposure:.2f}"
    )
```

### Depth Thresholds

```python
def get_depth_thresholds(self, asset: str) -> Dict[str, int]:
    """Get depth thresholds for a specific asset from profile YAML.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
        
    Returns:
        Dict with min_depth_yes and min_depth_no thresholds
        
    Raises:
        KeyError: If asset not found in depth thresholds (no silent defaults)
    """
    if asset not in self.asset_depth_thresholds:
        raise KeyError(f"Asset {asset} not found in depth thresholds. "
                      f"Available assets: {list(self.asset_depth_thresholds.keys())}")
    return self.asset_depth_thresholds[asset]
```

**Purpose**: Single source of truth for depth thresholds across the 15m stack. Replaces hardcoded literals in market state and orderbook logic.

### Feature Flag

```python
def is_risk_envelope_enabled() -> bool:
    """Check if risk envelope is enabled via feature flag.
    
    Feature flag MERID_RISK_ENVELOPE_ENABLED allows runtime disabling of the envelope
    for rollback scenarios. Default is True (enabled).
    """
    enabled = os.getenv("MERID_RISK_ENVELOPE_ENABLED", "true").lower() in ("true", "1", "yes")
    logger.info(f"[RISK-ENVELOPE-FEATURE-FLAG] MERID_RISK_ENVELOPE_ENABLED={enabled}")
    return enabled
```

## Global Allocator

### Purpose

The global allocator replaces per-asset caps with a top-N edge knapsack allocator under venue cap. It implements a shared $1 pool model where assets compete for capital based on edge quality.

### Core Idea

- Collect all candidates from all agents in a cycle
- Sort by edge (descending)
- Greedy fill under venue cap ($1.00)
- Only submit orders that fit under the cap

**Benefits**:
- Best edges get prioritized
- Total exposure ≤ venue cap (shared $1 pool across all assets)
- No artificial per-asset limits
- Concentration on highest expected returns
- 1 contract per asset per window
- Entry prices in 5c-95c range (expanded for skewed markets)
- Confidence ≥ 50%
- Edge ≥ 2.0% (actual percentage)

### Order Candidate

```python
@dataclass
class OrderCandidate:
    """Represents a potential order from an agent."""
    asset: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    count: int
    edge_pct: float
    confidence: float
    model_prob: float
    agent_name: str
    
    @property
    def notional_usd(self) -> float:
        """Calculate order notional in USD."""
        return (self.price_cents * self.count) / 100.0
    
    @property
    def edge_score(self) -> float:
        """Composite edge score for ranking."""
        return self.edge_pct * self.confidence
```

### Global Allocator Initialization

```python
class GlobalAllocator:
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
        min_confidence: float = 0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
        min_price_cents: int = 5,  # Minimum entry price (5c) - expanded for skewed markets
        max_price_cents: int = 95,  # Maximum entry price (95c) - expanded for skewed markets
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset
        enable_correlation_control: bool = False,
        per_asset_min_edge_pct: dict = None,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct
        self.min_confidence = min_confidence
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        # Per-asset edge thresholds (aligned with risk_parameters.py market entry thresholds)
        if per_asset_min_edge_pct is None:
            self.per_asset_min_edge_pct = {
                "BTC": 1.75,   # EDGE_MARKET_ENTRY_BTC
                "ETH": 2.0,    # EDGE_MARKET_ENTRY_ETH
                "SOL": 2.5,    # EDGE_MARKET_ENTRY_SOL
                "XRP": 3.0,    # EDGE_MARKET_ENTRY_XRP
                "DOGE": 3.5,   # EDGE_MARKET_ENTRY_DOGE
            }
        else:
            self.per_asset_min_edge_pct = per_asset_min_edge_pct
```

**CRITICAL FIX 2026-07-10**: Aligned edge thresholds with agent grid edge units (actual percentage, not decimal). Previous values (0.05%) were 40x lower than agent grid values (2.0%).

### Allocation Algorithm

```python
def allocate(
    self,
    candidates: List[OrderCandidate],
    current_positions: Optional[Dict[str, float]] = None
) -> List[OrderCandidate]:
    """Allocate orders based on edge ranking under venue cap with shared $1 pool.
    
    CRITICAL: This implements the shared $1 pool model where assets compete for capital.
    No per-asset budgets - total exposure across all assets must be ≤ $1.00.
    """
    
    # Filter by minimum edge (per-asset thresholds aligned with risk_parameters.py)
    filtered = []
    for c in candidates:
        asset_min_edge = self.per_asset_min_edge_pct.get(c.asset, self.min_edge_pct)
        if c.edge_pct >= asset_min_edge:
            filtered.append(c)
    
    # Filter by minimum confidence (50%)
    conf_filtered = [c for c in filtered if c.confidence >= self.min_confidence]
    
    # Filter by price range (5c-95c)
    price_filtered = [c for c in conf_filtered if self.min_price_cents <= c.price_cents <= self.max_price_cents]
    
    # Optimal knapsack-style allocation under $1 cap
    # For small asset universe (5 assets), brute-force all combinations to find optimal
    from itertools import combinations
    
    # Group candidates by asset (1 per asset max)
    asset_candidates = {}
    for candidate in price_filtered:
        if candidate.asset not in asset_candidates:
            asset_candidates[candidate.asset] = candidate  # Keep best per asset
    
    unique_candidates = list(asset_candidates.values())
    
    # Try all combinations (2^n where n=5, so max 32 combinations)
    best_combination = []
    best_total_edge = 0.0
    best_total_notional = 0.0
    
    for r in range(1, len(unique_candidates) + 1):
        for combo in combinations(unique_candidates, r):
            total_notional = sum(c.notional_usd for c in combo)
            
            # Skip if exceeds cap
            if total_notional > self.venue_cap_usd:
                continue
            
            # Check per-asset concentration limit
            combo_valid = True
            for candidate in combo:
                asset_with_order = candidate.notional_usd
                max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction
                if asset_with_order > max_asset_notional:
                    combo_valid = False
                    break
            
            if not combo_valid:
                continue
            
            # Calculate total edge score for this combination
            total_edge = sum(c.edge_score for c in combo)
            
            # Prefer combination with higher total edge
            if total_edge > best_total_edge or (total_edge == best_total_edge and total_notional < best_total_notional):
                best_combination = list(combo)
                best_total_edge = total_edge
                best_total_notional = total_notional
    
    return best_combination
```

**Algorithm**: Brute-force knapsack (2^n combinations) is optimal for small asset universe (n=5, max 32 combinations). Ensures we get the best combination of edges that fits under cap.

### Allocation Summary

```python
def get_allocation_summary(self, chosen: List[OrderCandidate]) -> Dict[str, Any]:
    """Get summary of allocation decisions."""
    
    if not chosen:
        return {
            "total_orders": 0,
            "total_notional": 0.0,
            "asset_breakdown": {},
            "avg_edge": 0.0,
            "utilization_pct": 0.0
        }
    
    total_notional = sum(c.notional_usd for c in chosen)
    asset_breakdown = {}
    for c in chosen:
        asset_breakdown[c.asset] = asset_breakdown.get(c.asset, 0.0) + c.notional_usd
    
    avg_edge = sum(c.edge_pct for c in chosen) / len(chosen)
    
    return {
        "total_orders": len(chosen),
        "total_notional": total_notional,
        "asset_breakdown": asset_breakdown,
        "avg_edge": avg_edge,
        "utilization_pct": (total_notional / self.venue_cap_usd) * 100
    }
```

### Creation from Envelope

```python
def create_global_allocator_from_envelope(envelope: Any) -> GlobalAllocator:
    """Create GlobalAllocator from risk envelope configuration.
    
    CRITICAL: Uses shared $1 pool model with per-asset edge thresholds aligned with risk_parameters.py.
    """
    venue_cap = envelope.max_total_notional_usd if hasattr(envelope, 'max_total_notional_usd') else 1.00
    
    # CRITICAL: Use the shared $1 pool parameters (no per-asset rescaling)
    min_edge_pct = 2.0  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
    min_confidence = 0.50  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
    
    return GlobalAllocator(
        venue_cap_usd=venue_cap,
        min_edge_pct=min_edge_pct,
        min_confidence=min_confidence,
        per_asset_min_edge_pct={
            "BTC": 1.75,
            "ETH": 2.0,
            "SOL": 2.5,
            "XRP": 3.0,
            "DOGE": 3.5,
        }
    )
```

## Position Cache

### Purpose

The position cache provides real-time position tracking updated from WebSocket fill events, reducing latency from REST polling to sub-second updates.

### Key Features

- Real-time position tracking from WebSocket fill events
- Identifies test and expired tickers
- Provides fallback market price retrieval
- Tracks fill source, scale-out, entry intent, and ratchet profit floors
- Supports exposure calculation and fill application logic

### CachedPosition Dataclass

```python
@dataclass
class CachedPosition:
    """Detailed position state from position cache."""
    ticker: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    current_price_cents: int
    unrealized_pnl_cents: float
    realized_pnl_cents: float
    fill_source: str  # "ws" or "rest"
    scale_out: bool
    entry_intent: str  # "swing" or "scalp"
    ratchet_profit_floor_cents: float
    last_update_ts: float
    is_test: bool
    is_expired: bool
```

### Exposure Calculation

```python
def get_total_exposure(self) -> float:
    """Calculate total exposure across all positions."""
    total = 0.0
    for ticker, pos in self._positions.items():
        if pos and pos.contracts > 0:
            total += (pos.contracts * pos.current_price_cents) / 100.0
    return total

def get_asset_exposure(self, asset: str) -> float:
    """Calculate exposure for a specific asset."""
    total = 0.0
    for ticker, pos in self._positions.items():
        if pos and pos.contracts > 0 and asset.lower() in ticker.lower():
            total += (pos.contracts * pos.current_price_cents) / 100.0
    return total
```

## Position Monitor

### Purpose

The position monitor manages swing trading exit management, tracking open positions and enforcing take-profit and stop-loss exits.

### Key Features

- Tracks open positions and computes PnL
- Enforces take-profit and stop-loss exits
- Registers exit intent callbacks
- Thread-safe position storage and retrieval
- Releases window capacity in risk envelope on position close

### Exit Enforcement

```python
def check_exit_conditions(self, position: CachedPosition) -> Optional[Dict[str, Any]]:
    """Check if position should be exited based on TP/SL conditions."""
    
    if position.contracts == 0:
        return None
    
    # Calculate PnL
    pnl_cents = (position.current_price_cents - position.avg_price_cents) * position.contracts
    if position.side == "no":
        pnl_cents = -pnl_cents  # NO positions have inverted PnL
    
    # Check take-profit
    if pnl_cents >= self.take_profit_cents:
        return {"action": "exit", "reason": "take_profit", "pnl_cents": pnl_cents}
    
    # Check stop-loss
    if pnl_cents <= -self.stop_loss_cents:
        return {"action": "exit", "reason": "stop_loss", "pnl_cents": pnl_cents}
    
    return None
```

## Kalshi Risk Manager

### Purpose

The Kalshi risk manager is a venue-aware risk layer that provides fee calculation, Kelly position sizing, and risk-reducing trade detection.

### Key Features

- Fee calculation via unified fees module
- Kelly position sizing with clamping and fee awareness
- Risk-reducing trade detection
- Tiered fee schedule and edge clamping
- Integration with cycle drawdown manager

### Kelly Sizing

```python
def calculate_kelly_size(
    self,
    edge_pct: float,
    price_cents: int,
    bankroll_usd: float,
) -> int:
    """Calculate position size using Kelly criterion."""
    
    # Get Kelly fraction from risk envelope
    kelly_fraction = self.risk_envelope.kelly_fraction
    
    # Calculate base size
    base_size_usd = bankroll_usd * kelly_fraction
    base_size_contracts = int(base_size_usd / (price_cents / 100.0))
    
    # Clamp to min/max
    min_size = 1
    max_size = self.risk_envelope.max_single_order_notional_usd / (price_cents / 100.0)
    
    size = max(min_size, min(base_size_contracts, int(max_size)))
    
    return size
```

## Critical Fixes

### Fix 1: Module-Level Window Tracking (2026-07-06)

**Problem**: Window exposure stored on envelope instances was discarded immediately because envelopes are recomputed on every call. The 3%/5% HARD STOPs never engaged.

**Solution**: Window tracking state moved to module level so every envelope instance reads/writes the same cumulative exposure.

### Fix 2: Peak Bankroll at Window Start (2026-07-08)

**Problem**: 5% limit calculation used current bankroll, causing fluctuations if bankroll changed mid-window.

**Solution**: Lock in peak bankroll at window start for consistent 5% calculation.

### Fix 3: Resting Order Exposure (2026-07-08)

**Problem**: Multiple resting orders could exceed window limits when they executed.

**Solution**: Include resting order exposure in window limit checks to prevent accumulation.

### Fix 4: Per-Agent Limit Disabled (2026-07-10)

**Problem**: Per-agent limit check blocked each agent at $1.00 individually, preventing the slot allocator from properly allocating shared capital.

**Solution**: Disabled per-agent limit check. The global slot allocator is the single source of truth for $1.00 total exposure enforcement.

### Fix 5: Per-Asset Limit Disabled (2026-07-10)

**Problem**: Per-asset limit check was redundant and conflicted with slot allocator.

**Solution**: Disabled per-asset limit check. The global slot allocator enforces $1.00 total cap across all 5 assets.

### Fix 6: Edge Threshold Alignment (2026-07-10)

**Problem**: Global allocator edge thresholds (0.05%) were 40x lower than agent grid values (2.0%), causing candidates to be filtered incorrectly.

**Solution**: Aligned edge thresholds with agent grid edge units (actual percentage, not decimal).

## Risk Parameters

### Venue Cap

- **Total exposure cap**: $1.00 (shared pool across all 5 assets)
- **Per-asset limit**: None (assets compete for capital based on edge)
- **Per-agent limit**: None (agents compete for capital based on edge)

### Window Limits

- **Per-agent window limit**: DISABLED (slot allocator enforces $1.00 total)
- **Total venue window limit**: $1.00 (HARD STOP)
- **Per-asset window limit**: DISABLED (slot allocator enforces $1.00 total)

### Entry Thresholds

- **Minimum edge**: 2.0% (actual percentage)
- **Minimum confidence**: 50%
- **Price range**: 5c-95c (expanded for skewed markets)

### Per-Asset Edge Thresholds

- **BTC**: 1.75%
- **ETH**: 2.0%
- **SOL**: 2.5%
- **XRP**: 3.0%
- **DOGE**: 3.5%

### Drawdown Bands

- **Normal**: 0-10% drawdown, 100% risk multiplier
- **Warning**: 10-12% drawdown, 50% risk multiplier
- **Downsize**: 12-15% drawdown, 25% risk multiplier
- **Halt**: 15%+ drawdown, 0% risk multiplier (manual resume required)

## Monitoring and Observability

### Key Log Messages

- `[WINDOW-TRACKING]`: Window tracking events (roll, reset, check)
- `[RISK-ENVELOPE]`: Risk envelope events (band change, halt)
- `[DRAWDOWN]`: Drawdown tracking events (new peak, current)
- `[GLOBAL-ALLOCATOR]`: Allocation events (filter, choose, summary)

### Metrics

- **Window exposure**: Cumulative exposure per agent and total
- **Resting exposure**: Cumulative resting order exposure
- **Drawdown**: Current drawdown percentage
- **Risk band**: Current risk band (normal/warning/downsize/halt)
- **Allocation utilization**: Percentage of $1.00 cap used
- **Average edge**: Average edge of chosen orders

## References

- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- **Global Allocator**: `merid/risk/profiles/global_allocator.py`
- **Position Cache**: `merid/event_venues/kalshi/position_cache.py`
- **Position Monitor**: `merid/position_management/position_monitor.py`
- **Kalshi Risk**: `merid/event_venues/kalshi/kalshi_risk.py`

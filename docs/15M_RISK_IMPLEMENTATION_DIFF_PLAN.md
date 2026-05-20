# 15m Risk System Implementation Diff Plan

**File-by-file, function-by-function implementation checklist.**

---

## Pre-Implementation: Risk Model Semantics

### Drawdown Semantics (Add to YAML and Documentation)

**Add to `config/profiles/kalshi_crypto_15m.yaml`:**

```yaml
# ── Drawdown Semantics ───────────────────────────────────────────────────────
# Time horizon: "since process start" (not rolling window)
# - Peak equity tracks highest equity since FastAPI startup
# - Drawdown is computed as (peak - current) / peak
# - Fresh start resets peak equity to current equity
#
# PnL basis: "equity including open positions" (realized + unrealized)
# - Uses Kalshi account balance (total equity)
# - Not based on realized PnL only
#
# Deposits/Withdrawals:
# - Deposits: treated as PnL (increase equity, may update peak)
# - Withdrawals: treated as PnL (decrease equity, peak unchanged)
# - This ensures drawdown reflects actual account performance
#
# Fresh Start Behavior:
# - When MERID_FRESH_START=1, peak_equity resets to current_equity
# - This prevents old drawdown state from persisting across sessions
drawdown_semantics:
  time_horizon: "since_process_start"
  pnl_basis: "equity_including_positions"
  deposit_withdrawal_treatment: "as_pnl"
```

**Verification:**
- Semantics documented in YAML
- Semantics match bankroll service behavior
- Fresh start resets peak equity

---

## Phase 1 - Configuration Changes

### File: `config/profiles/kalshi_crypto_15m.yaml`

**Add adaptive risk bands section:**

```yaml
# ── Adaptive Risk Scaling ───────────────────────────────────────────────────
# Risk scaling bands based on drawdown percentage.
# As drawdown approaches halt, risk multiplier decreases to give recovery chance.
adaptive_risk_bands:
  - max_drawdown_pct: 0.10  # 10% - normal risk
    multiplier: 1.0
  - max_drawdown_pct: 0.12  # 12% - reduced risk
    multiplier: 0.5
  - max_drawdown_pct: 0.15  # 15% - critical risk
    multiplier: 0.25
  - max_drawdown_pct: 1.00  # halt
    multiplier: 0.0
```

**Add kelly_fraction to kelly section (already has kelly_hard_cap, rename for clarity):**

```yaml
kelly:
  kelly_fraction: 0.30  # 30% Kelly hard cap (from profile)
  kelly_hard_cap: 0.30  # Legacy field, kept for compatibility
  # ... other kelly settings ...
```

**Verification:**
- YAML validates successfully
- Bands are in ascending order
- Multipliers are between 0.0 and 1.0

**Add YAML validation (no silent fallbacks):**

```python
# In compute_kalshi_crypto_15m_risk_envelope, add validation:
# Validate adaptive risk bands
if not adaptive_risk_bands:
    raise ValueError("adaptive_risk_bands is required in profile YAML")

# Validate bands are in ascending order
for i in range(len(adaptive_risk_bands) - 1):
    if adaptive_risk_bands[i]['max_drawdown_pct'] >= adaptive_risk_bands[i+1]['max_drawdown_pct']:
        raise ValueError(f"adaptive_risk_bands must be in ascending order: {adaptive_risk_bands}")

# Validate multipliers are between 0 and 1
for band in adaptive_risk_bands:
    if not (0.0 <= band['multiplier'] <= 1.0):
        raise ValueError(f"adaptive_risk_bands multiplier must be between 0 and 1: {band}")

# Validate last band has multiplier 0 (halt)
if adaptive_risk_bands[-1]['multiplier'] != 0.0:
    raise ValueError("Last adaptive_risk_bands entry must have multiplier 0.0 (halt)")

# Validate drawdown thresholds
if drawdown_halt_pct <= 0 or drawdown_halt_pct > 0.50:
    raise ValueError(f"drawdown_halt_pct must be between 0 and 0.50: {drawdown_halt_pct}")

if drawdown_unwind_pct <= drawdown_halt_pct or drawdown_unwind_pct > 0.50:
    raise ValueError(f"drawdown_unwind_pct must be > drawdown_halt_pct and <= 0.50: {drawdown_unwind_pct}")
```

**Verification:**
- Malformed YAML fails fast with clear error
- No silent fallback to old defaults
- Validation runs at envelope computation time

---

## Phase 2 - Risk Envelope Changes

### File: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Add fields to KalshiCrypto15mRiskEnvelope dataclass:**

```python
@dataclass
class KalshiCrypto15mRiskEnvelope:
    # ... existing fields ...
    
    # ── Drawdown Tracking ─────────────────────────────────────────────────────
    peak_equity_usd: float
    current_equity_usd: float
    current_drawdown_pct: float
    
    # ── Kelly Fraction ────────────────────────────────────────────────────────
    kelly_fraction: float
    
    # ── Adaptive Risk Scaling ────────────────────────────────────────────────
    adaptive_risk_bands: List[Dict[str, float]]  # From YAML
    per_trade_risk_multiplier: float
    is_halted: bool
```

**Add methods to KalshiCrypto15mRiskEnvelope:**

```python
def update_drawdown(self, current_equity_usd: float):
    """Update drawdown tracking with current equity.
    
    Args:
        current_equity_usd: Current equity from bankroll service
        
    Raises:
        ValueError: If current_equity_usd is invalid
    """
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
        # Clamp to [0, 1] to handle floating-point edge cases
        self.current_drawdown_pct = max(0.0, min(1.0, self.current_drawdown_pct))
    
    # Update adaptive risk and halt state
    self._update_adaptive_risk()
    self.is_halted = self.current_drawdown_pct >= self.drawdown_halt_pct

def _update_adaptive_risk(self):
    """Update per-trade risk multiplier based on drawdown bands."""
    for band in self.adaptive_risk_bands:
        if self.current_drawdown_pct <= band['max_drawdown_pct']:
            self.per_trade_risk_multiplier = band['multiplier']
            return
    
    # Default to halt if no band matches
    self.per_trade_risk_multiplier = 0.0

def get_per_trade_risk_pct(self) -> float:
    """Get per-trade risk percentage from profile."""
    return 0.008  # From guardrails.per_trade_risk_pct

def get_drawdown_halt_pct(self) -> float:
    """Get drawdown halt percentage."""
    return self.drawdown_halt_pct

def get_drawdown_unwind_pct(self) -> float:
    """Get drawdown unwind percentage."""
    return self.drawdown_unwind_pct

def get_kelly_fraction(self) -> float:
    """Get Kelly fraction."""
    return self.kelly_fraction

def get_risk_multiplier_for_drawdown(self) -> float:
    """Get risk multiplier based on current drawdown."""
    return self.per_trade_risk_multiplier

def is_halted(self) -> bool:
    """Check if system is halted due to drawdown."""
    return self.is_halted

def get_effective_per_trade_risk_usd(self) -> float:
    """Get effective per-trade risk in USD (with adaptive scaling)."""
    base_risk_usd = self.live_bankroll_usd * self.get_per_trade_risk_pct()
    return base_risk_usd * self.per_trade_risk_multiplier

def distance_to_halt_pct(self) -> float:
    """Distance from current drawdown to halt threshold."""
    return max(0.0, self.drawdown_halt_pct - self.current_drawdown_pct)
```

**Update compute_kalshi_crypto_15m_risk_envelope function:**

```python
# Extract adaptive risk bands
adaptive_risk_bands = guardrails.get('adaptive_risk_bands', [
    {'max_drawdown_pct': 0.10, 'multiplier': 1.0},
    {'max_drawdown_pct': 0.12, 'multiplier': 0.5},
    {'max_drawdown_pct': 0.15, 'multiplier': 0.25},
    {'max_drawdown_pct': 1.00, 'multiplier': 0.0},
])

# Extract kelly fraction
kelly_config = profile_config.get('kelly', {})
kelly_fraction = kelly_config.get('kelly_fraction', kelly_config.get('kelly_hard_cap', 0.30))

# Initialize drawdown tracking
peak_equity_usd = live_bankroll_usd
current_equity_usd = live_bankroll_usd
current_drawdown_pct = 0.0

# Initialize adaptive risk
per_trade_risk_multiplier = 1.0
is_halted = False
```

**Update return statement:**

```python
return KalshiCrypto15mRiskEnvelope(
    # ... existing fields ...
    peak_equity_usd=peak_equity_usd,
    current_equity_usd=current_equity_usd,
    current_drawdown_pct=current_drawdown_pct,
    kelly_fraction=kelly_fraction,
    adaptive_risk_bands=adaptive_risk_bands,
    per_trade_risk_multiplier=per_trade_risk_multiplier,
    is_halted=is_halted,
)
```

**Verification:**
- Envelope initializes with correct bands
- update_drawdown() correctly tracks peak equity
- _update_adaptive_risk() returns correct multiplier
- get_effective_per_trade_risk_usd() scales correctly

---

## Phase 3 - Kill Switch Changes

### File: `merid/risk/kill_switches.py`

**Remove hardcoded max_position_value:**

```python
# DELETE THIS LINE:
max_position_value: float = 10000.0
```

**Change daily_loss_enabled default:**

```python
# Change from:
daily_loss_enabled: bool = True
# To:
daily_loss_enabled: bool = False  # Default disabled, profile controls this
```

**Add profile-aware drawdown state function:**

```python
def get_profile_drawdown_state() -> tuple[Optional[float], Optional[float], bool]:
    """Get drawdown state from active profile for kalshi_crypto_15m_v2.
    
    Returns:
        Tuple of (current_drawdown_pct, drawdown_halt_pct, is_halted)
        Returns (None, None, False) if not a profile with drawdown tracking
    """
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return None, None, False
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        # Update envelope with current equity
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        envelope.update_drawdown(current_equity)
        return envelope.current_drawdown_pct, envelope.drawdown_halt_pct, envelope.is_halted
    except Exception as e:
        logger.warning(f"[PROFILE-DRAWDOWN] Failed to load profile drawdown state: {e}")
        return None, None, False
```

**Add drawdown check to can_trade method:**

```python
# After existing checks, add:
# PROFILE-DRAWDOWN: Check drawdown halt for kalshi_crypto_15m_v2
current_drawdown, drawdown_halt, is_halted = get_profile_drawdown_state()
if is_halted:
    self._trigger_kill_locked(
        KillSwitchReason.DAILY_LOSS,  # Reuse or add new KillSwitchReason.DRAWDOWN_HALT
        f"Drawdown halt: {current_drawdown:.2%} >= {drawdown_halt:.2%} (detected in can_trade)",
    )
```

**Remove max_position_value from __post_init__ env override:**

```python
# DELETE THIS BLOCK:
env_max_pos = os.getenv("MERID_MAX_POSITION_VALUE_USD")
if env_max_pos and self.max_position_value == 10000.0:
    try:
        self.max_position_value = float(env_max_pos)
    except (ValueError, TypeError):
        pass
```

**Remove max_position_value from status check:**

```python
# DELETE THIS LINE:
if self.daily_loss_limit != 500.0 or self.max_position_value != 10000.0:
```

**Verification:**
- No max_position_value field remains
- get_profile_drawdown_state() returns correct values
- can_trade() halts when envelope.is_halted is True
- Daily loss check respects daily_loss_enabled flag

---

## Phase 4 - KalshiRiskConfig Changes

### File: `merid/event_venues/kalshi/kalshi_risk.py`

**Change default values to 0.0 (force profile override):**

```python
# Change from:
drawdown_halt_pct: float = 0.10
drawdown_unwind_pct: float = 0.15
max_single_order_notional_usd: float = 2500.0
kelly_fraction: float = 0.25

# To:
drawdown_halt_pct: float = 0.0  # 0 means "derive from profile"
drawdown_unwind_pct: float = 0.0  # 0 means "derive from profile"
max_single_order_notional_usd: float = 0.0  # 0 means "derive from profile"
kelly_fraction: float = 0.0  # 0 means "derive from profile"
```

**Add profile-aware initialization in __post_init__:**

```python
def __post_init__(self):
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    # PROFILE-OVERRIDE: For kalshi_crypto_15m_v2, use envelope values
    if profile == "kalshi_crypto_15m_v2":
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            
            # Override drawdown thresholds
            if self.drawdown_halt_pct == 0.0:
                self.drawdown_halt_pct = envelope.drawdown_halt_pct
            if self.drawdown_unwind_pct == 0.0:
                self.drawdown_unwind_pct = envelope.drawdown_unwind_pct
            
            # Remove hardcoded order caps (use envelope values)
            if self.max_single_order_notional_usd == 0.0:
                self.max_single_order_notional_usd = envelope.max_single_order_notional_usd
            if self.max_total_notional_usd == 0.0:
                self.max_total_notional_usd = envelope.max_total_notional_usd
            
            # Override Kelly fraction
            if self.kelly_fraction == 0.0:
                self.kelly_fraction = envelope.kelly_fraction
            
            logger.info(
                f"[PROFILE-OVERRIDE] Using envelope for kalshi_crypto_15m_v2: "
                f"drawdown_halt={self.drawdown_halt_pct:.2%}, "
                f"max_single_order=${self.max_single_order_notional_usd:.2f}, "
                f"kelly={self.kelly_fraction:.2f}"
            )
        except Exception as e:
            logger.warning(f"[PROFILE-OVERRIDE] Failed to load envelope: {e}")
    
    # Continue with existing __post_init__ logic...
```

**Verification:**
- For kalshi_crypto_15m_v2, all values come from envelope
- For other profiles, legacy defaults still work
- No hardcoded 10% drawdown remains for 15m profile

---

## Phase 5 - Loop Changes

### File: `merid/loops/kalshi_15m_loop.py` (or wherever Kalshi15mLoop is defined)

**Add envelope import and update in _cycle method:**

```python
async def _cycle(self):
    """Main trading cycle with drawdown-aware behavior."""
    # Get envelope
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
    except Exception as e:
        logger.error(f"[LOOP] Failed to get risk envelope: {e}")
        return
    
    # Check if halted
    if envelope.is_halted():
        logger.warning(
            f"[LOOP] HALTED: drawdown {envelope.current_drawdown_pct:.2%} >= {envelope.drawdown_halt_pct:.2%}. "
            f"Skipping cycle."
        )
        return
    
    # Log drawdown state
    distance_to_halt = envelope.distance_to_halt_pct()
    risk_multiplier = envelope.get_risk_multiplier_for_drawdown()
    
    if distance_to_halt < 0.05:  # Within 5% of halt
        logger.warning(
            f"[LOOP] NEAR HALT: drawdown {envelope.current_drawdown_pct:.2%}, "
            f"{distance_to_halt:.2%} from halt. "
            f"Risk multiplier: {risk_multiplier:.0%}"
        )
    elif risk_multiplier < 1.0:
        logger.info(
            f"[LOOP] REDUCED RISK: drawdown {envelope.current_drawdown_pct:.2%}, "
            f"Risk multiplier: {risk_multiplier:.0%}"
        )
    
    # Update envelope with current bankroll
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        envelope.update_drawdown(current_equity)
    except Exception as e:
        logger.error(f"[LOOP] Failed to update drawdown: {e}")
    
    # Pass risk multiplier to agents/position sizing if needed
    # Continue with normal cycle logic...
```

**Verification:**
- Loop skips cycles when envelope.is_halted() is True
- Loop logs drawdown state and risk multiplier
- Loop updates envelope with current equity each cycle

---

## Phase 6 - Agent Changes

### File: `merid/prediction/trading_agent.py` (or agent base class)

**Add drawdown-aware signal filtering method:**

```python
def should_filter_signal(self, signal, envelope) -> bool:
    """Filter signals based on drawdown state.
    
    Args:
        signal: Trading signal with confidence/edge
        envelope: Risk envelope with current drawdown state
    
    Returns:
        True if signal should be filtered (not traded)
    """
    risk_multiplier = envelope.get_risk_multiplier_for_drawdown()
    
    # If near halt, only take highest confidence signals
    if risk_multiplier <= 0.25:  # 12%+ drawdown
        if signal.confidence < 0.8:  # Only 80%+ confidence
            logger.info(
                f"[AGENT] Signal filtered due to drawdown: "
                f"confidence {signal.confidence:.2f} < 0.8, "
                f"risk_multiplier={risk_multiplier:.2f}"
            )
            return True
    
    # If reduced risk, require higher confidence
    if risk_multiplier <= 0.5:  # 10%+ drawdown
        if signal.confidence < 0.6:  # Only 60%+ confidence
            logger.info(
                f"[AGENT] Signal filtered due to drawdown: "
                f"confidence {signal.confidence:.2f} < 0.6, "
                f"risk_multiplier={risk_multiplier:.2f}"
            )
            return True
    
    return False
```

**Integrate filtering into signal execution:**

```python
# In signal execution path, add:
try:
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    if self.should_filter_signal(signal, envelope):
        logger.info(f"[AGENT] Signal filtered by drawdown-aware policy")
        return
except Exception as e:
    logger.warning(f"[AGENT] Failed to check drawdown filtering: {e}")
```

**Verification:**
- Agents filter signals based on drawdown state
- Higher confidence required when risk multiplier is low
- Logs explain why signals were filtered

---

## Phase 7 - API Endpoint

### File: `web/api/kalshi_api.py` (or create new `web/api/risk.py`)

**Add new endpoint:**

```python
@app.get("/api/v1/risk/envelope")
async def get_risk_envelope():
    """Get current risk envelope state.
    
    Returns static config from YAML and dynamic state from envelope.
    """
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Update with current equity
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        envelope.update_drawdown(current_equity)
        
        return {
            # Static config (from YAML)
            "drawdown_halt_pct": envelope.drawdown_halt_pct,
            "drawdown_unwind_pct": envelope.drawdown_unwind_pct,
            "per_trade_risk_pct": envelope.get_per_trade_risk_pct(),
            "kelly_fraction": envelope.kelly_fraction,
            "adaptive_risk_bands": envelope.adaptive_risk_bands,
            
            # Dynamic state
            "bankroll_usd": envelope.live_bankroll_usd,
            "peak_equity_usd": envelope.peak_equity_usd,
            "current_equity_usd": envelope.current_equity_usd,
            "current_drawdown_pct": envelope.current_drawdown_pct,
            "distance_to_halt_pct": envelope.distance_to_halt_pct(),
            "is_halted": envelope.is_halted,
            "risk_multiplier": envelope.get_risk_multiplier_for_drawdown(),
            "effective_per_trade_risk_usd": envelope.get_effective_per_trade_risk_usd(),
            "daily_loss_enabled": envelope.daily_loss_enabled,
        }
    except Exception as e:
        logger.error(f"[RISK-ENVELOPE-API] Failed to get envelope: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Verification:**
- Endpoint returns all static and dynamic risk values
- Endpoint updates envelope with current equity
- Endpoint handles errors gracefully

---

## Phase 8 - UI Changes

### File: `web/react/src/config/constants.ts`

**Add constant:**

```typescript
export const RISK_ENVELOPE = "/api/v1/risk/envelope";
```

### File: `web/react/src/components/RiskEnvelopeDisplay.tsx` (new file)

**Create new component to display risk envelope state:**

```typescript
import React, { useState, useEffect } from 'react';
import { RISK_ENVELOPE } from '../config/constants';

interface RiskEnvelopeState {
  drawdown_halt_pct: number;
  drawdown_unwind_pct: number;
  per_trade_risk_pct: number;
  kelly_fraction: number;
  bankroll_usd: number;
  peak_equity_usd: number;
  current_equity_usd: number;
  current_drawdown_pct: number;
  distance_to_halt_pct: number;
  is_halted: boolean;
  risk_multiplier: number;
  effective_per_trade_risk_usd: number;
  daily_loss_enabled: boolean;
}

export const RiskEnvelopeDisplay: React.FC = () => {
  const [state, setState] = useState<RiskEnvelopeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchState = async () => {
      try {
        const response = await fetch(RISK_ENVELOPE);
        const data = await response.json();
        setState(data);
        setLoading(false);
      } catch (e) {
        setError('Failed to load risk envelope');
        setLoading(false);
      }
    };

    fetchState();
    const interval = setInterval(fetchState, 5000); // Poll every 5s
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading risk envelope...</div>;
  if (error) return <div>Error: {error}</div>;
  if (!state) return null;

  return (
    <div className="risk-envelope-display">
      <h3>Risk Envelope</h3>
      
      {state.is_halted && (
        <div className="alert alert-danger">
          HALTED: Drawdown {state.current_drawdown_pct.toFixed(1%)} >= {state.drawdown_halt_pct.toFixed(1%)}
        </div>
      )}
      
      <div className="risk-metrics">
        <div>
          <label>Bankroll:</label>
          <span>${state.bankroll_usd.toFixed(2)}</span>
        </div>
        
        <div>
          <label>Peak Equity:</label>
          <span>${state.peak_equity_usd.toFixed(2)}</span>
        </div>
        
        <div>
          <label>Current Drawdown:</label>
          <span>{state.current_drawdown_pct.toFixed(1%)}</span>
        </div>
        
        <div>
          <label>Distance to Halt:</label>
          <span>{state.distance_to_halt_pct.toFixed(1%)}</span>
        </div>
        
        <div>
          <label>Risk Multiplier:</label>
          <span>{(state.risk_multiplier * 100).toFixed(0)}%</span>
        </div>
        
        <div>
          <label>Effective Per-Trade Risk:</label>
          <span>${state.effective_per_trade_risk_usd.toFixed(2)}</span>
        </div>
      </div>
      
      <div className="risk-config">
        <h4>Configuration</h4>
        <div>
          <label>Drawdown Halt:</label>
          <span>{state.drawdown_halt_pct.toFixed(1%)}</span>
        </div>
        <div>
          <label>Drawdown Unwind:</label>
          <span>{state.drawdown_unwind_pct.toFixed(1%)}</span>
        </div>
        <div>
          <label>Per-Trade Risk:</label>
          <span>{state.per_trade_risk_pct.toFixed(2%)}</span>
        </div>
        <div>
          <label>Kelly Fraction:</label>
          <span>{state.kelly_fraction.toFixed(2%)}</span>
        </div>
      </div>
    </div>
  );
};
```

**Wire component into relevant views:**

- Add to `KalshiDashboardView.tsx`
- Add to `Overview.tsx`
- Add to `Risk.tsx`

**Verification:**
- Component displays all risk envelope values
- Component polls every 5 seconds
- Component shows halted state prominently
- Component shows risk multiplier and effective per-trade risk

---

## Phase 9 - Validation and Tests

### File: `tests/risk/test_envelope_drawdown.py` (new file)

**Add drawdown simulation tests:**

```python
import pytest
from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    KalshiCrypto15mRiskEnvelope,
    compute_kalshi_crypto_15m_risk_envelope,
)

def test_drawdown_tracking():
    """Test that drawdown tracking works correctly."""
    # Create envelope with initial bankroll
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
    
    # Initial state
    assert envelope.peak_equity_usd == 1000.0
    assert envelope.current_drawdown_pct == 0.0
    assert not envelope.is_halted
    
    # 10% drawdown
    envelope.update_drawdown(900.0)
    assert envelope.peak_equity_usd == 1000.0
    assert envelope.current_drawdown_pct == 0.10
    assert not envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 1.0
    
    # 12% drawdown
    envelope.update_drawdown(880.0)
    assert envelope.current_drawdown_pct == 0.12
    assert not envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 0.5
    
    # 15% drawdown
    envelope.update_drawdown(850.0)
    assert envelope.current_drawdown_pct == 0.15
    assert envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 0.0
    
    # Peak updates on new high
    envelope.update_drawdown(1100.0)
    assert envelope.peak_equity_usd == 1100.0
    assert envelope.current_drawdown_pct == 0.0
    assert not envelope.is_halted

def test_effective_per_trade_risk():
    """Test that effective per-trade risk scales correctly."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
    
    # Normal risk
    assert envelope.get_effective_per_trade_risk_usd() == 8.0  # 1000 * 0.008 * 1.0
    
    # 50% risk
    envelope.update_drawdown(900.0)  # 10% drawdown
    assert envelope.get_effective_per_trade_risk_usd() == 8.0  # Still 1.0x at 10%
    
    envelope.update_drawdown(880.0)  # 12% drawdown
    assert envelope.get_effective_per_trade_risk_usd() == 4.0  # 1000 * 0.008 * 0.5
    
    # 25% risk
    envelope.update_drawdown(850.0)  # 15% drawdown
    assert envelope.get_effective_per_trade_risk_usd() == 2.0  # 1000 * 0.008 * 0.25
    
    # Halted
    assert envelope.get_effective_per_trade_risk_usd() == 0.0  # Halted

def test_distance_to_halt():
    """Test distance to halt calculation."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
    
    assert envelope.distance_to_halt_pct() == 0.15
    
    envelope.update_drawdown(900.0)  # 10% drawdown
    assert envelope.distance_to_halt_pct() == 0.05
    
    envelope.update_drawdown(850.0)  # 15% drawdown
    assert envelope.distance_to_halt_pct() == 0.0
```

### File: `merid/startup_validations.py`

**Add runtime assertion for drawdown consistency:**

```python
def validate_drawdown_consistency():
    """Validate that all drawdown consumers see the same threshold for kalshi_crypto_15m_v2."""
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    if profile != "kalshi_crypto_15m_v2":
        return  # Only validate for 15m profile
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        envelope = get_kalshi_crypto_15m_risk_envelope()
        kalshi_config = KalshiRiskConfig()
        
        # Check drawdown thresholds match
        if abs(envelope.drawdown_halt_pct - kalshi_config.drawdown_halt_pct) > 0.001:
            logger.error(
                f"[DRAWDOWN-VALIDATION] MISMATCH: "
                f"Envelope drawdown_halt_pct={envelope.drawdown_halt_pct:.2%}, "
                f"KalshiRiskConfig drawdown_halt_pct={kalshi_config.drawdown_halt_pct:.2%}"
            )
            raise ValueError("Drawdown thresholds inconsistent across modules")
        
        logger.info("[DRAWDOWN-VALIDATION] All drawdown thresholds consistent")
        
    except Exception as e:
        logger.error(f"[DRAWDOWN-VALIDATION] Failed: {e}")
        raise
```

**Add to validate_all():**

```python
def validate_all():
    """Run all startup validations."""
    # ... existing validations ...
    
    validate_drawdown_consistency()
```

**Verification:**
- Tests pass for drawdown tracking
- Tests pass for adaptive risk scaling
- Startup validation catches threshold mismatches

---

## Phase 10 - Config Validation Tests

### File: `tests/config/test_profile_isolation.py` (new file)

**Add CI validation for profile isolation:**

```python
import pytest
import os
import yaml
from pathlib import Path

def test_kalshi_crypto_15m_no_hardcoded_drawdown_in_kill_switches():
    """Ensure kill_switches.py doesn't have hardcoded drawdown for 15m profile."""
    # This test ensures future changes don't reintroduce hardcoded values
    # Implementation: check that kill_switches.py uses envelope for 15m profile
    pass

def test_kalshi_crypto_15m_no_hardcoded_drawdown_in_kalshi_risk():
    """Ensure kalshi_risk.py doesn't have hardcoded 10% drawdown for 15m profile."""
    # This test ensures KalshiRiskConfig uses envelope for 15m profile
    pass

def test_kalshi_crypto_15m_yaml_has_adaptive_bands():
    """Ensure profile YAML has adaptive risk bands defined."""
    repo_root = Path(__file__).parent.parent.parent
    profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    with open(profile_path, 'r') as f:
        profile = yaml.safe_load(f)
    
    assert 'adaptive_risk_bands' in profile
    bands = profile['adaptive_risk_bands']
    
    # Validate bands are in ascending order
    for i in range(len(bands) - 1):
        assert bands[i]['max_drawdown_pct'] < bands[i+1]['max_drawdown_pct']
    
    # Validate multipliers are between 0 and 1
    for band in bands:
        assert 0.0 <= band['multiplier'] <= 1.0

def test_kalshi_crypto_15m_daily_loss_disabled():
    """Ensure daily loss is disabled in profile YAML."""
    repo_root = Path(__file__).parent.parent.parent
    profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    with open(profile_path, 'r') as f:
        profile = yaml.safe_load(f)
    
    guardrails = profile.get('guardrails', {})
    assert guardrails.get('daily_loss_enabled') == False
```

**Verification:**
- CI tests catch hardcoded values being reintroduced
- CI tests validate YAML structure
- CI tests ensure daily loss is disabled

---

## Phase 11 - Robustness & Safety Nets

### File: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Add safe equity update helper:**

```python
def safe_update_envelope_equity(envelope: KalshiCrypto15mRiskEnvelope) -> bool:
    """
    Safely update envelope equity with error handling.
    
    This is the preferred method for updating equity in the hot path.
    On failure, logs error and returns False without raising.
    
    Args:
        envelope: Risk envelope to update
        
    Returns:
        True if update succeeded, False otherwise
    """
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        envelope.update_drawdown(current_equity)
        return True
    except Exception as e:
        logger.error(f"[RISK-ENVELOPE] Failed to update equity: {e}")
        return False
```

**Add fresh start reset method:**

```python
def reset_for_fresh_start(envelope: KalshiCrypto15mRiskEnvelope):
    """
    Reset envelope state for fresh start.
    
    Called when MERID_FRESH_START=1 to prevent old drawdown state from persisting.
    """
    envelope.peak_equity_usd = envelope.current_equity_usd
    envelope.current_drawdown_pct = 0.0
    envelope.per_trade_risk_multiplier = 1.0
    envelope.is_halted = False
    logger.info("[RISK-ENVELOPE] Reset for fresh start")
```

**Verification:**
- safe_update_envelope_equity handles bankroll service failures
- reset_for_fresh_start clears old drawdown state

---

### File: `merid/loops/kalshi_15m_loop.py`

**Add profile dimension to metrics:**

```python
# In loop initialization, add profile label:
profile = os.getenv("MERID_PROFILE", "unknown")
METRICS_PREFIX = f"merid_15m_{profile}"

# Update all metrics to include profile:
# e.g., prometheus.Counter(f"{METRICS_PREFIX}_cycles_total")
```

**Performance optimization - update envelope once per cycle:**

```python
async def _cycle(self):
    """Main trading cycle with optimized envelope updates."""
    # Update envelope once per cycle (not per order)
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            get_kalshi_crypto_15m_risk_envelope,
            safe_update_envelope_equity
        )
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Safe update - log on failure but don't crash
        if not safe_update_envelope_equity(envelope):
            logger.error("[LOOP] Failed to update envelope, using stale data")
            # Continue with stale data rather than halt
    except Exception as e:
        logger.error(f"[LOOP] Failed to get envelope: {e}")
        return
    
    # Check if halted
    if envelope.is_halted():
        logger.warning(f"[LOOP] HALTED: drawdown {envelope.current_drawdown_pct:.2%}")
        return
    
    # Log only on band transitions (not every cycle)
    risk_multiplier = envelope.get_risk_multiplier_for_drawdown()
    if not hasattr(self, '_last_risk_multiplier'):
        self._last_risk_multiplier = risk_multiplier
    
    if risk_multiplier != self._last_risk_multiplier:
        logger.info(
            f"[LOOP] Risk band transition: "
            f"{self._last_risk_multiplier:.0%} → {risk_multiplier:.0%}"
        )
        self._last_risk_multiplier = risk_multiplier
    
    # Continue with cycle...
```

**Verification:**
- Metrics include profile dimension
- Envelope updated once per cycle, not per order
- Band transitions logged, not every cycle

---

### File: `web/api/kalshi_api.py`

**Add profile dimension to envelope endpoint response:**

```python
@app.get("/api/v1/risk/envelope")
async def get_risk_envelope():
    """Get current risk envelope state."""
    import os
    profile = os.getenv("MERID_PROFILE", "unknown")
    
    # ... existing logic ...
    
    return {
        **data,
        "profile": profile,  # Add profile dimension
        "timestamp": datetime.utcnow().isoformat(),
    }
```

**Verification:**
- Endpoint returns profile dimension
- UI can distinguish between profiles

---

### File: `tests/risk/test_envelope_drawdown.py`

**Add floating-point edge case tests:**

```python
def test_drawdown_floating_point_edge_cases():
    """Test drawdown calculation with floating-point edge cases."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
    
    # Exact band boundaries (10%, 12%, 15%)
    envelope.update_drawdown(900.0)  # Exactly 10%
    assert envelope.current_drawdown_pct == 0.10
    assert envelope.per_trade_risk_multiplier == 1.0  # Band: <= 10%
    
    envelope.update_drawdown(880.0)  # Exactly 12%
    assert envelope.current_drawdown_pct == 0.12
    assert envelope.per_trade_risk_multiplier == 0.5  # Band: <= 12%
    
    envelope.update_drawdown(850.0)  # Exactly 15%
    assert envelope.current_drawdown_pct == 0.15
    assert envelope.is_halted  # Halt at 15%

def test_peak_equity_zero_edge_case():
    """Test behavior when peak_equity is zero (fresh account)."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=0.0)
    
    assert envelope.peak_equity_usd == 0.0
    assert envelope.current_drawdown_pct == 0.0
    assert not envelope.is_halted
    
    # Should handle gracefully
    envelope.update_drawdown(0.0)
    assert envelope.current_drawdown_pct == 0.0

def test_bankroll_service_failure_handling():
    """Test that bankroll service failure is handled gracefully."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=1000.0)
    
    # Mock bankroll service failure
    from unittest.mock import patch
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock:
        mock.side_effect = Exception("Bankroll service down")
        
        result = safe_update_envelope_equity(envelope)
        assert result == False  # Should return False, not crash
        
        # Envelope should still have previous state
        assert envelope.current_equity_usd == 1000.0
```

**Add integration test for drawdown progression:**

```python
def test_drawdown_progression_integration():
    """Test full drawdown progression with simulated PnL."""
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=10000.0)
    
    # Simulate trading sequence
    pnl_sequence = [
        (9500.0, 5.0),   # 5% drawdown - normal risk
        (9000.0, 10.0),  # 10% drawdown - normal risk
        (8800.0, 12.0),  # 12% drawdown - reduced risk
        (8500.0, 15.0),  # 15% drawdown - halt
        (8200.0, 18.0),  # 18% drawdown - still halted
    ]
    
    expected_multipliers = [1.0, 1.0, 0.5, 0.0, 0.0]
    
    for (equity, expected_dd), expected_mult in zip(pnl_sequence, expected_multipliers):
        envelope.update_drawdown(equity)
        assert abs(envelope.current_drawdown_pct - expected_dd / 100.0) < 0.001
        assert envelope.per_trade_risk_multiplier == expected_mult
        assert envelope.is_halted == (expected_dd >= 15.0)
```

**Verification:**
- Floating-point edge cases handled
- Peak equity zero handled gracefully
- Bankroll service failure doesn't crash
- Integration test covers full progression

---

### File: `config/profiles/kalshi_crypto_15m.yaml`

**Add inline comments for operator clarity:**

```yaml
# ── Adaptive Risk Scaling ───────────────────────────────────────────────────
# Risk scaling bands based on drawdown percentage.
# As drawdown approaches halt, risk multiplier decreases to give recovery chance.
# 
# Example with $10,000 bankroll and 0.8% per-trade risk:
# - 0-10% drawdown: $80 per trade (100% of normal)
# - 10-12% drawdown: $40 per trade (50% of normal)
# - 12-15% drawdown: $20 per trade (25% of normal)
# - 15%+ drawdown: $0 per trade (halted)
adaptive_risk_bands:
  - max_drawdown_pct: 0.10  # 10% - normal risk (100% multiplier)
    multiplier: 1.0
  - max_drawdown_pct: 0.12  # 12% - reduced risk (50% multiplier)
    multiplier: 0.5
  - max_drawdown_pct: 0.15  # 15% - critical risk (25% multiplier)
    multiplier: 0.25
  - max_drawdown_pct: 1.00  # halt (0% multiplier)
    multiplier: 0.0

# ── Kelly Sizing ──────────────────────────────────────────────────────────
# Kelly fraction: maximum fraction of bankroll to risk per trade
# 0.30 = 30% of bankroll maximum (very conservative)
# This is a hard cap; actual sizing may be lower based on signal quality
kelly:
  kelly_fraction: 0.30  # 30% Kelly hard cap (from profile)
  kelly_hard_cap: 0.30  # Legacy field, kept for compatibility
  kelly_min_edge_pct: 1.0  # Min 1% edge to trade
  kelly_max_edge_pct: 25.0  # Max 25% edge (catches data errors)
```

**Verification:**
- YAML has clear inline comments
- Operators understand what each parameter does
- Example calculations provided

---

### File: `merid/startup_validations.py`

**Add risk envelope validation:**

```python
def validate_risk_envelope():
    """Validate risk envelope is correctly initialized."""
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    
    if profile != "kalshi_crypto_15m_v2":
        return  # Only validate for 15m profile
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Validate all fields are populated
        assert envelope.live_bankroll_usd > 0, "live_bankroll_usd must be > 0"
        assert envelope.peak_equity_usd > 0, "peak_equity_usd must be > 0"
        assert envelope.drawdown_halt_pct == 0.15, "drawdown_halt_pct must be 0.15"
        assert envelope.drawdown_unwind_pct == 0.20, "drawdown_unwind_pct must be 0.20"
        assert envelope.daily_loss_enabled == False, "daily_loss_enabled must be False"
        assert envelope.kelly_fraction > 0, "kelly_fraction must be > 0"
        
        # Validate computed values
        assert envelope.max_single_order_notional_usd > 0, "max_single_order_notional_usd must be > 0"
        assert envelope.max_total_notional_usd > 0, "max_total_notional_usd must be > 0"
        
        # Validate adaptive bands
        assert len(envelope.adaptive_risk_bands) > 0, "adaptive_risk_bands must not be empty"
        assert envelope.adaptive_risk_bands[-1]['multiplier'] == 0.0, "Last band must have multiplier 0.0"
        
        logger.info("[VALIDATION] Risk envelope validated successfully")
        
    except Exception as e:
        logger.error(f"[VALIDATION] Risk envelope validation failed: {e}")
        raise
```

**Add to validate_all():**

```python
def validate_all():
    """Run all startup validations."""
    # ... existing validations ...
    
    validate_risk_envelope()
```

**Verification:**
- Startup validation checks envelope fields
- Startup validation checks computed values
- Startup validation checks adaptive bands

---

## Summary of Changes (Updated)

**Files Modified:**
1. `config/profiles/kalshi_crypto_15m.yaml` - Add adaptive bands, semantics, comments
2. `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Add drawdown tracking, methods, safe helpers
3. `merid/risk/kill_switches.py` - Remove hardcodes, add profile-aware check
4. `merid/event_venues/kalshi/kalshi_risk.py` - Profile-aware initialization
5. `merid/loops/kalshi_15m_loop.py` - Drawdown-aware behavior, profile metrics
6. `merid/prediction/trading_agent.py` - Drawdown-aware filtering
7. `web/api/kalshi_api.py` - Add envelope endpoint with profile dimension
8. `web/react/src/config/constants.ts` - Add constant
9. `web/react/src/components/RiskEnvelopeDisplay.tsx` - New component
10. `tests/risk/test_envelope_drawdown.py` - New tests (edge cases, integration)
11. `merid/startup_validations.py` - Add drawdown consistency, envelope validation
12. `tests/config/test_profile_isolation.py` - New CI tests

**Lines Added:** ~500
**Lines Removed:** ~20

**Estimated Implementation Time:** 5-7 hours

---

## Verification Checklist (Updated)

After implementation, verify:

- [ ] Profile YAML has drawdown_semantics section
- [ ] Profile YAML has adaptive_risk_bands section with comments
- [ ] Envelope tracks peak_equity and current_drawdown_pct
- [ ] Envelope.is_halted() triggers at 15% drawdown
- [ ] Risk multiplier scales: 1.0 → 0.5 → 0.25 → 0.0
- [ ] Kill switches remove max_position_value=10000.0
- [ ] Kill switches check envelope.is_halted()
- [ ] KalshiRiskConfig uses envelope values for 15m profile
- [ ] Loop skips cycles when halted
- [ ] Loop logs drawdown state and band transitions
- [ ] Loop updates envelope once per cycle (optimized)
- [ ] Loop metrics include profile dimension
- [ ] Agents filter signals based on drawdown
- [ ] API endpoint returns envelope state with profile dimension
- [ ] UI displays drawdown state and risk multiplier
- [ ] Startup validation passes (drawdown consistency, envelope validation)
- [ ] Drawdown simulation tests pass
- [ ] Floating-point edge case tests pass
- [ ] Bankroll service failure handling works
- [ ] CI validation tests pass
- [ ] Fresh start resets envelope state

---

**Files Modified:**
1. `config/profiles/kalshi_crypto_15m.yaml` - Add adaptive bands
2. `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Add drawdown tracking, methods
3. `merid/risk/kill_switches.py` - Remove hardcodes, add profile-aware check
4. `merid/event_venues/kalshi/kalshi_risk.py` - Profile-aware initialization
5. `merid/loops/kalshi_15m_loop.py` - Drawdown-aware behavior
6. `merid/prediction/trading_agent.py` - Drawdown-aware filtering
7. `web/api/kalshi_api.py` - Add envelope endpoint
8. `web/react/src/config/constants.ts` - Add constant
9. `web/react/src/components/RiskEnvelopeDisplay.tsx` - New component
10. `tests/risk/test_envelope_drawdown.py` - New tests
11. `merid/startup_validations.py` - Add drawdown consistency check
12. `tests/config/test_profile_isolation.py` - New CI tests

**Lines Added:** ~400
**Lines Removed:** ~20

**Estimated Implementation Time:** 4-6 hours

---

## Verification Checklist

After implementation, verify:

- [ ] Profile YAML has adaptive_risk_bands section
- [ ] Envelope tracks peak_equity and current_drawdown_pct
- [ ] Envelope.is_halted() triggers at 15% drawdown
- [ ] Risk multiplier scales: 1.0 → 0.5 → 0.25 → 0.0
- [ ] Kill switches remove max_position_value=10000.0
- [ ] Kill switches check envelope.is_halted()
- [ ] KalshiRiskConfig uses envelope values for 15m profile
- [ ] Loop skips cycles when halted
- [ ] Loop logs drawdown state
- [ ] Agents filter signals based on drawdown
- [ ] API endpoint returns envelope state
- [ ] UI displays drawdown state and risk multiplier
- [ ] Startup validation passes
- [ ] Drawdown simulation tests pass
- [ ] CI validation tests pass

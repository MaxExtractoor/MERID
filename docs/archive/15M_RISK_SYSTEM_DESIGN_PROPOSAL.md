# 15m Risk System Design Proposal

**If this were my project, here's exactly how I would set it up.**

---

## Core Design Philosophy

1. **Single Source of Truth:** Profile YAML is the ONLY writable risk config. All other modules read from envelope.
2. **Dynamic Scaling:** All USD limits are percentages of live bankroll. Zero hardcoded dollar values in production code.
3. **Drawdown-Centric:** Drawdown is the primary hard guard. Everything else is advisory or derived.
4. **Graceful Degradation:** System reduces risk as drawdown approaches, not binary on/off until halt.
5. **Profile Isolation:** For `kalshi_crypto_15m_v2`, bypass all legacy risk paths. Use envelope only.

---

## Architecture

```
Profile YAML (kalshi_crypto_15m.yaml)
    ↓
Risk Envelope (computes all limits from profile + live bankroll)
    ↓
    ├─→ Kill Switches (checks envelope for drawdown state)
    ├─→ Order Router (uses envelope for position sizing)
    ├─→ Loop (checks envelope for risk utilization)
    └─→ Agents (use envelope for per-trade risk)
```

---

## Mathematical Model

### Drawdown Calculation

```
peak_equity_usd = max(historical_equity_usd)
current_equity_usd = live_bankroll_usd
current_drawdown_pct = (peak_equity_usd - current_equity_usd) / peak_equity_usd
```

### Adaptive Risk Scaling

As drawdown approaches halt, reduce per-trade risk:

```
if current_drawdown_pct >= drawdown_halt_pct:
    per_trade_risk_multiplier = 0.0  # HALT
elif current_drawdown_pct >= 0.12:  # 12% (80% of 15%)
    per_trade_risk_multiplier = 0.25  # 25% of normal
elif current_drawdown_pct >= 0.10:  # 10% (67% of 15%)
    per_trade_risk_multiplier = 0.50  # 50% of normal
else:
    per_trade_risk_multiplier = 1.0  # Normal
```

**Rationale:** This gives the system time to recover before hitting the hard halt. At 10% drawdown (2/3 of halt), you still have 5% buffer to try to recover with reduced risk.

### Position Sizing

```
max_single_order_usd = bankroll_usd * per_trade_risk_pct * per_trade_risk_multiplier
max_total_notional_usd = bankroll_usd * max_total_notional_pct
max_asset_notional_usd = bankroll_usd * asset_max_notional_pct
```

### Kelly Fraction

From profile YAML:
```
kelly_fraction = profile.kelly.kelly_hard_cap * confidence_multiplier
```

Where confidence_multiplier is based on signal quality (edge, probability, etc.).

---

## Risk Envelope Changes

### Add to `KalshiCrypto15mRiskEnvelope`:

```python
@dataclass
class KalshiCrypto15mRiskEnvelope:
    # ... existing fields ...
    
    # ── Drawdown Tracking ─────────────────────────────────────────────────────
    peak_equity_usd: float  # Highest equity seen
    current_equity_usd: float  # Current equity from bankroll
    current_drawdown_pct: float  # Current drawdown percentage
    
    # ── Kelly Fraction ────────────────────────────────────────────────────────
    kelly_fraction: float  # From profile (default 0.30 hard cap)
    
    # ── Computed Adaptive Risk ───────────────────────────────────────────────
    per_trade_risk_multiplier: float  # Adaptive scaling based on drawdown
    is_halted: bool  # True if drawdown >= halt threshold
```

### Add Methods:

```python
def update_drawdown(self, current_equity_usd: float):
    """Update drawdown tracking with current equity."""
    self.current_equity_usd = current_equity_usd
    if current_equity_usd > self.peak_equity_usd:
        self.peak_equity_usd = current_equity_usd
    
    if self.peak_equity_usd > 0:
        self.current_drawdown_pct = (self.peak_equity_usd - current_equity_usd) / self.peak_equity_usd
    else:
        self.current_drawdown_pct = 0.0
    
    # Update adaptive risk scaling
    self._update_adaptive_risk()
    
    # Check halt condition
    self.is_halted = self.current_drawdown_pct >= self.drawdown_halt_pct

def _update_adaptive_risk(self):
    """Update per-trade risk multiplier based on drawdown."""
    if self.is_halted:
        self.per_trade_risk_multiplier = 0.0
    elif self.current_drawdown_pct >= 0.12:  # 80% of halt
        self.per_trade_risk_multiplier = 0.25
    elif self.current_drawdown_pct >= 0.10:  # 67% of halt
        self.per_trade_risk_multiplier = 0.50
    else:
        self.per_trade_risk_multiplier = 1.0

def get_effective_per_trade_risk_usd(self) -> float:
    """Get effective per-trade risk in USD (with adaptive scaling)."""
    base_risk_usd = self.live_bankroll_usd * 0.008  # 0.8% from profile
    return base_risk_usd * self.per_trade_risk_multiplier

def distance_to_halt_pct(self) -> float:
    """Distance from current drawdown to halt threshold."""
    return max(0.0, self.drawdown_halt_pct - self.current_drawdown_pct)
```

### Update `compute_kalshi_crypto_15m_risk_envelope`:

```python
# Add drawdown tracking initialization
peak_equity_usd = live_bankroll_usd  # Start at current
current_equity_usd = live_bankroll_usd
current_drawdown_pct = 0.0

# Add kelly fraction from profile
kelly_config = profile_config.get('kelly', {})
kelly_fraction = kelly_config.get('kelly_hard_cap', 0.30)

# Add adaptive risk initialization
per_trade_risk_multiplier = 1.0
is_halted = False
```

---

## Kill Switch Changes

### In `kill_switches.py`:

**Remove:**
```python
max_position_value: float = 10000.0  # DELETE THIS
```

**Change default:**
```python
daily_loss_enabled: bool = False  # Changed from True (profile controls this)
```

**Add profile-aware drawdown check:**

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
        return envelope.current_drawdown_pct, envelope.drawdown_halt_pct, envelope.is_halted
    except Exception as e:
        logger.warning(f"[PROFILE-DRAWDOWN] Failed to load profile drawdown state: {e}")
        return None, None, False
```

**Add to `can_trade`:**

```python
# PROFILE-DRAWDOWN: Check drawdown halt for kalshi_crypto_15m_v2
current_drawdown, drawdown_halt, is_halted = get_profile_drawdown_state()
if is_halted:
    self._trigger_kill_locked(
        KillSwitchReason.DAILY_LOSS,  # Reuse or add new reason
        f"Drawdown halt: {current_drawdown:.2%} >= {drawdown_halt:.2%} (detected in can_trade)",
    )
```

---

## KalshiRiskConfig Changes

### In `kalshi_risk.py`:

**Add profile-aware initialization:**

```python
def __post_init__(self):
    # PROFILE-OVERRIDE: For kalshi_crypto_15m_v2, use envelope values
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            
            # Override drawdown thresholds
            self.drawdown_halt_pct = envelope.drawdown_halt_pct
            self.drawdown_unwind_pct = envelope.drawdown_unwind_pct
            
            # Remove hardcoded order caps (use envelope values)
            self.max_single_order_notional_usd = envelope.max_single_order_notional_usd
            self.max_total_notional_usd = envelope.max_total_notional_usd
            
            # Override Kelly fraction
            self.kelly_fraction = envelope.kelly_fraction
            
            logger.info(
                f"[PROFILE-OVERRIDE] Using envelope for kalshi_crypto_15m_v2: "
                f"drawdown_halt={self.drawdown_halt_pct:.2%}, "
                f"max_single_order=${self.max_single_order_notional_usd:.2f}, "
                f"kelly={self.kelly_fraction:.2f}"
            )
        except Exception as e:
            logger.warning(f"[PROFILE-OVERRIDE] Failed to load envelope: {e}")
```

**Remove hardcoded defaults (keep as 0.0 or None to force profile override):**

```python
drawdown_halt_pct: float = 0.0  # 0 means "derive from profile"
max_single_order_notional_usd: float = 0.0  # 0 means "derive from profile"
kelly_fraction: float = 0.0  # 0 means "derive from profile"
```

---

## Loop Changes

### In `Kalshi15mLoop`:

**Add drawdown-aware behavior:**

```python
async def _cycle(self):
    """Main trading cycle with drawdown-aware behavior."""
    # Get envelope
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    # Check if halted
    if envelope.is_halted:
        logger.warning(
            f"[LOOP] HALTED: drawdown {envelope.current_drawdown_pct:.2%} >= {envelope.drawdown_halt_pct:.2%}. "
            f"Skipping cycle."
        )
        return
    
    # Log drawdown state
    distance_to_halt = envelope.distance_to_halt_pct()
    if distance_to_halt < 0.05:  # Within 5% of halt
        logger.warning(
            f"[LOOP] NEAR HALT: drawdown {envelope.current_drawdown_pct:.2%}, "
            f"{distance_to_halt:.2%} from halt. "
            f"Risk multiplier: {envelope.per_trade_risk_multiplier:.0%}"
        )
    
    # Update envelope with current bankroll
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        envelope.update_drawdown(current_equity)
    except Exception as e:
        logger.error(f"[LOOP] Failed to update drawdown: {e}")
    
    # Continue with normal cycle logic...
```

---

## Agent Changes

### In agent signal generation:

**Add drawdown-aware signal filtering:**

```python
def should_filter_signal(self, signal, envelope) -> bool:
    """Filter signals based on drawdown state."""
    # If near halt, only take highest confidence signals
    if envelope.current_drawdown_pct >= 0.10:  # 10% drawdown
        if signal.confidence < 0.8:  # Only 80%+ confidence
            logger.info(f"[AGENT] Signal filtered due to drawdown: confidence {signal.confidence:.2f} < 0.8")
            return True
    
    return False
```

---

## UI Changes

### Update React components to read from envelope:

**Add API endpoint:**

```python
@app.get("/api/v1/risk/envelope")
async def get_risk_envelope():
    """Get current risk envelope state."""
    envelope = get_kalshi_crypto_15m_risk_envelope()
    return {
        "bankroll_usd": envelope.live_bankroll_usd,
        "peak_equity_usd": envelope.peak_equity_usd,
        "current_drawdown_pct": envelope.current_drawdown_pct,
        "drawdown_halt_pct": envelope.drawdown_halt_pct,
        "distance_to_halt_pct": envelope.distance_to_halt_pct(),
        "is_halted": envelope.is_halted,
        "per_trade_risk_multiplier": envelope.per_trade_risk_multiplier,
        "max_single_order_usd": envelope.get_effective_per_trade_risk_usd(),
        "daily_loss_enabled": envelope.daily_loss_enabled,
    }
```

**Update UI to display:**
- Current drawdown % with progress bar
- Distance to halt % (e.g., "5% from halt")
- Risk multiplier (e.g., "50% of normal risk")
- Halted state (red banner if halted)

---

## Configuration Changes

### Update `kalshi_crypto_15m.yaml`:

**Add Kelly fraction:**

```yaml
kelly:
  kelly_fraction: 0.30  # 30% Kelly hard cap (from profile)
  kelly_hard_cap: 0.30
  # ... other kelly settings ...
```

**Add adaptive risk thresholds (optional):**

```yaml
guardrails:
  # ... existing settings ...
  
  # Adaptive risk scaling thresholds
  adaptive_risk:
    warning_threshold_pct: 0.10  # 10% - reduce risk to 50%
    critical_threshold_pct: 0.12  # 12% - reduce risk to 25%
```

---

## Validation and Testing

### Startup Validation:

```python
def validate_risk_envelope():
    """Validate envelope is correctly initialized."""
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    # Check all fields are populated
    assert envelope.live_bankroll_usd > 0
    assert envelope.peak_equity_usd > 0
    assert envelope.drawdown_halt_pct == 0.15
    assert envelope.drawdown_unwind_pct == 0.20
    assert envelope.daily_loss_enabled == False
    assert envelope.kelly_fraction > 0
    
    # Check computed values
    assert envelope.max_single_order_notional_usd > 0
    assert envelope.max_total_notional_usd > 0
    
    logger.info("[VALIDATION] Risk envelope validated successfully")
```

### Drawdown Simulation Test:

```python
def test_drawdown_halt():
    """Test that drawdown halt triggers correctly."""
    envelope = get_kalshi_crypto_15m_risk_envelope(initial_bankroll=1000.0)
    
    # Simulate losses
    envelope.update_drawdown(900.0)  # 10% drawdown
    assert not envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 0.50
    
    envelope.update_drawdown(880.0)  # 12% drawdown
    assert not envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 0.25
    
    envelope.update_drawdown(850.0)  # 15% drawdown
    assert envelope.is_halted
    assert envelope.per_trade_risk_multiplier == 0.0
```

---

## Summary of Changes

### Priority 1 - Critical (Blockers):

1. **Add drawdown tracking to envelope** - peak_equity, current_drawdown_pct, is_halted
2. **Remove hardcoded max_position_value=10000.0** from kill_switches.py
3. **Align drawdown thresholds** - change 10% defaults to 15% or derive from envelope
4. **Add profile-aware initialization** to KalshiRiskConfig

### Priority 2 - High (Important):

5. **Add adaptive risk scaling** to envelope
6. **Add drawdown check to kill switch** can_trade()
7. **Add drawdown-aware behavior** to loop
8. **Remove hardcoded Kelly fraction** - use envelope value

### Priority 3 - Medium (Nice to have):

9. **Add drawdown-aware signal filtering** to agents
10. **Update UI** to show drawdown state
11. **Add validation** at startup
12. **Add tests** for drawdown behavior

---

## Why This Design?

**1. Drawdown tracking in envelope:**
- Envelope already computes all other risk limits
- Adding drawdown tracking makes it the complete risk authority
- Single source of truth for all risk state

**2. Adaptive risk scaling:**
- Binary halt is harsh - system should try to recover
- Reducing risk as drawdown approaches gives recovery chance
- 10% → 50% risk, 12% → 25% risk, 15% → halt
- Mathematically sound: still have buffer to recover

**3. Profile-aware initialization:**
- For kalshi_crypto_15m_v2, bypass all legacy defaults
- Envelope is the only source of truth
- Other profiles unaffected (backward compatible)

**4. Remove hardcoded dollar values:**
- All limits are percentages of live bankroll
- Scales automatically as account grows/shrinks
- No manual adjustments needed

**5. Kelly from profile:**
- Kelly is a sizing parameter, belongs in risk config
- Hardcoded 0.25 across 40+ files is wrong
- Profile should control Kelly fraction

---

## Verification Checklist

After implementation, verify:

- [ ] Envelope tracks peak_equity and current_drawdown_pct
- [ ] Envelope.is_halted triggers at 15% drawdown
- [ ] Per-trade risk scales down at 10% and 12% drawdown
- [ ] Kill switch checks envelope.is_halted before allowing trades
- [ ] KalshiRiskConfig uses envelope values for kalshi_crypto_15m_v2
- [ ] Loop logs drawdown state and skips cycles when halted
- [ ] No hardcoded dollar values in risk code for this profile
- [ ] All drawdown thresholds are 15% (not 10% or 12%)
- [ ] Kelly fraction comes from profile (not hardcoded 0.25)
- [ ] UI shows drawdown state and distance to halt
- [ ] Startup validation passes
- [ ] Drawdown simulation test passes

---

## Next Steps

1. **Implement Priority 1 changes** (envelope drawdown tracking, remove hardcodes)
2. **Test drawdown behavior** with simulation
3. **Implement Priority 2 changes** (adaptive scaling, kill switch integration)
4. **Test end-to-end** with live bankroll
5. **Implement Priority 3 changes** (UI, validation, tests)
6. **Deploy to paper trading** for validation
7. **Deploy to live** after paper validation

This design ensures the 15m stack is genuinely adaptive, self-consistent, and drawdown-centric as intended.

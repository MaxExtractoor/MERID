"""Risk State Snapshot — Aggregated view of all risk controls.

Provides a single source of truth for operator visibility into:
- Kill switch states (guard + risk_controller)
- Cap utilization (domain, venue, asset)
- CQI throttling and cooldown status
- Recent PROTECT and cap violation events
"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime

from merid.execution_guard import ExecutionGuard


class CapSnapshot(BaseModel):
    """Single cap snapshot with limit, usage, and utilization."""
    name: str
    limit: float
    used: float
    remaining: float
    utilization_pct: float


class KillSwitchSnapshot(BaseModel):
    """Kill switch state from a single source."""
    active: bool
    reason: str
    activated_at: Optional[str] = None


class CQISnapshot(BaseModel):
    """CQI and throttling state."""
    score: float
    throttle_pct: float
    block_below: float
    full_above: float


class CooldownSnapshot(BaseModel):
    """Cooldown status."""
    active: bool
    seconds_remaining: float
    cooldown_seconds: float


class PromotionSnapshot(BaseModel):
    """Promotion enforcement state."""
    enforcement_enabled: bool
    eligible_domains: List[str]
    blocked_agents: List[str]
    report_stale: bool


class RiskSnapshot(BaseModel):
    """Complete risk state snapshot for operator visibility."""
    timestamp: str
    
    # Convenience: overall trading blocked status
    trading_blocked: bool
    trading_blocked_reason: str
    
    # Kill switches
    kill_switch_guard: KillSwitchSnapshot
    kill_switch_risk_controller: KillSwitchSnapshot
    
    # Caps
    domains: Dict[str, CapSnapshot]
    venues: Dict[str, CapSnapshot]
    assets: Dict[str, CapSnapshot]
    
    # Throttling
    cqi: CQISnapshot
    cooldown: CooldownSnapshot
    
    # Promotion
    promotion: PromotionSnapshot
    
    # Recent events (last N)
    recent_protect_events: List[str]
    recent_cap_events: List[str]


def get_risk_snapshot(
    recent_event_limit: int = 10,
    include_verdicts: bool = False,
    guard: Optional[ExecutionGuard] = None,
) -> RiskSnapshot:
    """Aggregate complete risk state from all upstream components.
    
    Args:
        recent_event_limit: Number of recent events to include
        include_verdicts: Whether to include recent trade verdicts
        guard: Optional ExecutionGuard instance (uses singleton if None)
        
    Returns:
        RiskSnapshot with current state of all risk controls
    """
    from merid.execution_guard import get_execution_guard
    from merid.risk.kill_switches import risk_controller
    
    now = datetime.utcnow().isoformat() + "Z"
    guard = guard or get_execution_guard()
    
    # Get guard summary
    guard_summary = guard.summary()
    
    # Build kill switch snapshots
    kill_switch_guard = KillSwitchSnapshot(
        active=guard.kill_switch_active,
        reason=guard_summary.get("global_kill_reason", ""),
    )
    
    # Risk controller kill switch
    rc_status = risk_controller.get_status() if hasattr(risk_controller, 'get_status') else {}
    rc_kill_reason = rc_status.get('kill_reason') if isinstance(rc_status, dict) else None
    # get_status() exposes can_trade / state — not kill_switch_active (see kalshi /risk parity)
    _rc_active = False
    if isinstance(rc_status, dict):
        _rc_active = not rc_status.get("can_trade", True) or rc_status.get("state") == "triggered"
    kill_switch_risk_controller = KillSwitchSnapshot(
        active=_rc_active,
        reason=rc_kill_reason or '',
        activated_at=rc_status.get("kill_timestamp") if isinstance(rc_status, dict) else None,
    )
    
    # Build domain caps
    domains = {}
    for name, data in guard_summary.get('domain_caps', {}).items():
        limit = data.get('max_daily_notional_usd', 0.0)
        used = data.get('daily_notional_usd', 0.0)
        domains[name] = CapSnapshot(
            name=name,
            limit=limit,
            used=used,
            remaining=limit - used if limit > used else 0.0,
            utilization_pct=(used / limit * 100) if limit > 0 else 0.0,
        )
    
    # Build venue caps
    venues = {}
    for name, data in guard_summary.get('venue_caps', {}).items():
        limit = data.get('max_exposure_usd', 0.0)
        used = data.get('current_exposure_usd', 0.0)
        venues[name] = CapSnapshot(
            name=name,
            limit=limit,
            used=used,
            remaining=limit - used if limit > used else 0.0,
            utilization_pct=(used / limit * 100) if limit > 0 else 0.0,
        )
    
    # Build asset caps
    assets = {}
    for name, data in guard_summary.get('asset_caps', {}).items():
        limit = data.get('max_daily_notional_usd', 0.0)
        used = data.get('daily_notional_usd', 0.0)
        assets[name] = CapSnapshot(
            name=name,
            limit=limit,
            used=used,
            remaining=limit - used if limit > used else 0.0,
            utilization_pct=(used / limit * 100) if limit > 0 else 0.0,
        )
    
    # CQI state
    cqi_config = guard_summary.get('cqi_throttle_config', {})
    last_cqi = guard_summary.get('last_cqi', {})
    # Get first domain's CQI or default
    cqi_score = next(iter(last_cqi.values()), 0.5) if last_cqi else 0.5
    
    cqi = CQISnapshot(
        score=cqi_score,
        throttle_pct=guard_summary.get('cqi_throttle_config', {}).get('throttle_pct', 100.0),
        block_below=cqi_config.get('block_below', 0.3),
        full_above=cqi_config.get('full_above', 0.8),
    )
    
    # Cooldown state
    import time
    last_exec = getattr(guard, '_last_execution_at', 0)
    cooldown_secs = getattr(guard, '_cooldown_seconds', 5.0)
    time_since = time.time() - last_exec
    cooldown_active = time_since < cooldown_secs
    
    cooldown = CooldownSnapshot(
        active=cooldown_active,
        seconds_remaining=max(0.0, cooldown_secs - time_since) if cooldown_active else 0.0,
        cooldown_seconds=cooldown_secs,
    )
    
    # Promotion state
    promo = guard_summary.get('promotion_enforcement', {})
    promotion = PromotionSnapshot(
        enforcement_enabled=promo.get('enabled', True),
        eligible_domains=promo.get('eligible_domains', []),
        blocked_agents=promo.get('blocked_agents', []),
        report_stale=promo.get('stale', True),
    )
    
    # Recent events - pull from trade log
    recent_protect_events = []
    recent_cap_events = []
    
    if include_verdicts:
        verdicts = guard.recent_verdicts(recent_event_limit)
        for v in verdicts:
            reason = v.get('reason', '')
            plan_id = v.get('plan_id', 'unknown')
            if 'kill_switch' in reason.lower() or 'protect' in reason.lower():
                recent_protect_events.append(f"[{plan_id}] {reason}")
            elif 'cap' in reason.lower() or 'clamped' in reason.lower():
                recent_cap_events.append(f"[{plan_id}] {reason}")
    
    # Compute overall trading blocked status
    trading_blocked = (
        kill_switch_guard.active or 
        kill_switch_risk_controller.active or
        cooldown_active
    )
    
    # Build reason string
    block_reasons = []
    if kill_switch_guard.active:
        block_reasons.append(f"guard: {kill_switch_guard.reason}")
    if kill_switch_risk_controller.active:
        block_reasons.append(f"risk_controller: {kill_switch_risk_controller.reason}")
    if cooldown_active:
        block_reasons.append("cooldown")
    trading_blocked_reason = "; ".join(block_reasons) if block_reasons else ""
    
    return RiskSnapshot(
        timestamp=now,
        trading_blocked=trading_blocked,
        trading_blocked_reason=trading_blocked_reason,
        kill_switch_guard=kill_switch_guard,
        kill_switch_risk_controller=kill_switch_risk_controller,
        domains=domains,
        venues=venues,
        assets=assets,
        cqi=cqi,
        cooldown=cooldown,
        promotion=promotion,
        recent_protect_events=recent_protect_events,
        recent_cap_events=recent_cap_events,
    )

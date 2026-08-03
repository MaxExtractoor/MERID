"""
Risk Envelope Service - Single canonical service for all risk envelope operations.

Encapsulates bankroll access completely - downstream code never reads bankroll directly.
All sizing must go through this service to prevent future duplication of risk calculation logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DynamicSource(Enum):
    """Source of dynamic value computation."""
    BANKROLL = "bankroll"  # Computed from live bankroll
    CONTEXT = "context"    # Computed from realized PnL/volatility
    STATIC = "static"      # Static from profile YAML
    INVARIANT = "invariant"  # Hard-coded invariant (never changes)


@dataclass(frozen=True)
class RiskEnvelopeConfig:
    """
    Read-only configuration interface for risk envelope.
    
    All fields are frozen to prevent modification after creation.
    Downstream code must use get_config() to access these values.
    """
    
    # ── Dynamic (bankroll-driven) ───────────────────────────────────────
    live_bankroll_usd: float  # Live bankroll from BankrollServiceV2
    per_trade_risk_pct: float
    max_cycle_risk_pct: float
    max_total_notional_usd: float
    max_single_order_notional_usd: float
    asset_max_notional_usd: Dict[str, float]
    
    # ── Static (profile-configured) ───────────────────────────────────────
    # CRITICAL FIX (2026-07-17): Removed max_concurrent_trades - $1 exposure cap is the limit
    agent_max_yes_position: int
    agent_max_no_position: int
    agent_max_orders_per_window: int
    
    # ── Invariants (hard-coded) ───────────────────────────────────────────
    max_position_per_contract: int  # 500 (Kalshi limit)
    max_book_staleness_ms: int      # 30000 (PRODUCTION INVARIANT)
    
    # ── Metadata for validation ───────────────────────────────────────────
    dynamic_sources: Dict[str, DynamicSource]
    
    def get_dynamic_source(self, field_name: str) -> DynamicSource:
        """Get the source type for a field (for validation)."""
        return self.dynamic_sources.get(field_name, DynamicSource.STATIC)


class RiskEnvelopeService:
    """
    Single canonical service for all risk envelope operations.
    
    Encapsulates bankroll access completely - downstream code never
    reads bankroll directly. All sizing must go through this service.
    
    Usage:
        service = get_risk_envelope_service()
        config = service.get_config()
        per_trade_risk = config.per_trade_risk_pct
    """
    
    _instance: Optional["RiskEnvelopeService"] = None
    _envelope: Optional[RiskEnvelopeConfig] = None
    _last_bankroll_usd: Optional[float] = None
    _last_update_ts: Optional[float] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._envelope is not None:
            return  # Already initialized
        
        # Load envelope on first access
        self._refresh_envelope()
    
    def _refresh_envelope(self) -> None:
        """Refresh envelope from live bankroll and profile YAML."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
        )
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        
        # Get live bankroll (ONLY place bankroll is accessed)
        live_bankroll_usd = get_equity_for_risk_calc_sync()
        
        if live_bankroll_usd is None or live_bankroll_usd <= 0:
            logger.warning(f"[RISK-ENVELOPE] Bankroll not ready yet (${live_bankroll_usd}), skipping refresh")
            return  # Skip refresh if bankroll not ready, will retry on next cycle
        
        # Compute envelope
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd)
        
        # Convert to read-only config interface
        self._envelope = RiskEnvelopeConfig(
            # Dynamic (bankroll-driven)
            live_bankroll_usd=live_bankroll_usd,
            per_trade_risk_pct=envelope.get_per_trade_risk_pct(),
            max_cycle_risk_pct=envelope.max_cycle_risk_pct,
            max_total_notional_usd=envelope.max_total_notional_usd,
            max_single_order_notional_usd=envelope.max_single_order_notional_usd,
            asset_max_notional_usd=envelope.asset_max_notional_usd,
            
            # Static (profile-configured)
            # CRITICAL FIX (2026-07-17): Removed max_concurrent_trades - $1 exposure cap is the limit
            agent_max_yes_position=envelope.agent_max_yes_position,
            agent_max_no_position=envelope.agent_max_no_position,
            agent_max_orders_per_window=envelope.agent_max_orders_per_window,
            
            # Invariants (hard-coded)
            max_position_per_contract=500,  # Kalshi retail limit
            max_book_staleness_ms=30000,    # PRODUCTION INVARIANT
            
            # Metadata
            dynamic_sources={
                "live_bankroll_usd": DynamicSource.BANKROLL,
                "per_trade_risk_pct": DynamicSource.BANKROLL,
                "max_cycle_risk_pct": DynamicSource.BANKROLL,
                "max_total_notional_usd": DynamicSource.BANKROLL,
                "max_single_order_notional_usd": DynamicSource.BANKROLL,
                "asset_max_notional_usd": DynamicSource.BANKROLL,
                # CRITICAL FIX (2026-07-17): Removed max_concurrent_trades - $1 exposure cap is the limit
                "agent_max_yes_position": DynamicSource.STATIC,
                "agent_max_no_position": DynamicSource.STATIC,
                "agent_max_orders_per_window": DynamicSource.STATIC,
                "max_position_per_contract": DynamicSource.INVARIANT,
                "max_book_staleness_ms": DynamicSource.INVARIANT,
            }
        )
        
        self._last_bankroll_usd = live_bankroll_usd
        self._last_update_ts = time.time()
        
        # 2026-07-08: DISABLED percentage-based logging - using fixed $1 exposure model
        logger.info(
            f"[RISK-ENVELOPE-SERVICE] Envelope refreshed: bankroll=${live_bankroll_usd:.2f}, "
            f"per_trade_risk=DISABLED (fixed $1 exposure model), "
            f"max_total=${self._envelope.max_total_notional_usd:.2f}"
        )
    
    def get_config(self) -> RiskEnvelopeConfig:
        """Get current risk envelope configuration (read-only)."""
        if self._envelope is None:
            self._refresh_envelope()
        return self._envelope
    
    def refresh_if_stale(self, max_age_seconds: float = 30.0) -> None:
        """Refresh envelope if older than max_age_seconds."""
        if self._last_update_ts is None:
            self._refresh_envelope()
            return
        
        age = time.time() - self._last_update_ts
        if age > max_age_seconds:
            logger.info(f"[RISK-ENVELOPE-SERVICE] Envelope stale ({age:.1f}s > {max_age_seconds}s), refreshing")
            self._refresh_envelope()
    
    def get_bankroll_for_diagnostics(self) -> float:
        """
        Get bankroll value for diagnostics/logging ONLY.
        
        This is the ONLY public method that exposes bankroll.
        All other sizing must use get_config() fields.
        """
        if self._last_bankroll_usd is None:
            self._refresh_envelope()
        return self._last_bankroll_usd


def get_risk_envelope_service() -> RiskEnvelopeService:
    """Get the global risk envelope service singleton."""
    return RiskEnvelopeService()

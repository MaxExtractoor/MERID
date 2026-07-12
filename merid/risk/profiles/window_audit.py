"""
Window-Level Audit Function for 15m Kalshi Crypto Trading

This module provides auditing functions to verify the critical invariants
of the shared $1 pool allocation model:

- Sum of prices of all traded contracts in a window ≤ 100c ($1.00)
- No asset has more than 1 contract per window
- All entry prices are in [10c, 50c] range
- Total risk across all assets ≤ $1.00 (shared pool, not per-asset)

This becomes the "green/red" indicator that the allocator and order builder
are honoring the regime.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("merid.risk.profiles.window_audit")


@dataclass
class WindowAuditResult:
    """Result of a window-level audit."""
    window_start_ts: float
    window_end_ts: float
    assets_traded: List[str]
    prices_cents: List[int]
    total_risk_usd: float
    contracts_per_asset: Dict[str, int]
    ok: bool
    violations: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "window_start_ts": self.window_start_ts,
            "window_end_ts": self.window_end_ts,
            "assets_traded": self.assets_traded,
            "prices_cents": self.prices_cents,
            "total_risk_usd": self.total_risk_usd,
            "contracts_per_asset": self.contracts_per_asset,
            "ok": self.ok,
            "violations": self.violations
        }


class WindowAuditor:
    """
    Auditor for 15-minute window invariants.
    
    CRITICAL RULES TO VERIFY:
    - Sum of prices of all traded contracts in a window ≤ 100c ($1.00)
    - No asset has more than 1 contract per window
    - All entry prices are in [10c, 75c] range (canonical band)
    - Total risk across all assets ≤ $1.00 (shared pool, not per-asset)
    """
    
    def __init__(
        self,
        max_total_risk_usd: float = 1.00,
        min_price_cents: int = 10,  # 2026-07-12: Canonical price band (10c) - aligned with GlobalSlotAllocator
        max_price_cents: int = 75,  # 2026-07-12: Canonical price band (75c) - aligned with GlobalSlotAllocator
        max_contracts_per_asset: int = 1
    ):
        self.max_total_risk_usd = max_total_risk_usd
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_contracts_per_asset = max_contracts_per_asset
        
        logger.info(
            "[WINDOW-AUDITOR] Initialized: max_total_risk=$%.2f, price_range=[%dc-%dc], max_contracts_per_asset=%d",
            max_total_risk_usd, min_price_cents, max_price_cents, max_contracts_per_asset
        )
    
    def audit_window(
        self,
        orders: List[Dict[str, Any]],
        window_start_ts: float,
        window_end_ts: float
    ) -> WindowAuditResult:
        """
        Audit a completed 15-minute window for invariant violations.
        
        Args:
            orders: List of orders placed in the window, each containing:
                - asset: str (e.g., "BTC", "ETH")
                - price_cents: int
                - count: int
            window_start_ts: Window start timestamp
            window_end_ts: Window end timestamp
        
        Returns:
            WindowAuditResult with audit findings
        """
        violations = []
        
        # Track contracts per asset
        contracts_per_asset: Dict[str, int] = {}
        
        # Track prices and assets
        prices_cents = []
        assets_traded = []
        total_risk_usd = 0.0
        
        for order in orders:
            asset = order.get("asset")
            price_cents = order.get("price_cents", 0)
            count = order.get("count", 1)
            
            # Track asset
            if asset not in assets_traded:
                assets_traded.append(asset)
            
            # Track contracts per asset
            contracts_per_asset[asset] = contracts_per_asset.get(asset, 0) + count
            
            # Track price
            prices_cents.append(price_cents)
            
            # Calculate risk
            order_risk_usd = (price_cents * count) / 100.0
            total_risk_usd += order_risk_usd
            
            # Check price range
            if not (self.min_price_cents <= price_cents <= self.max_price_cents):
                violations.append(
                    f"Price out of range: asset={asset} price={price_cents}c (expected [{self.min_price_cents}c-{self.max_price_cents}c])"
                )
        
        # Check contracts per asset
        for asset, count in contracts_per_asset.items():
            if count > self.max_contracts_per_asset:
                violations.append(
                    f"Too many contracts for asset: asset={asset} count={count} (max={self.max_contracts_per_asset})"
                )
        
        # Check total risk
        if total_risk_usd > self.max_total_risk_usd:
            violations.append(
                f"Total risk exceeded: total_risk=${total_risk_usd:.2f} (max=${self.max_total_risk_usd:.2f})"
            )
        
        # Check sum of prices (cents)
        total_price_cents = sum(prices_cents)
        if total_price_cents > 100:  # 100c = $1.00
            violations.append(
                f"Sum of prices exceeded: total_price={total_price_cents}c (max=100c)"
            )
        
        ok = len(violations) == 0
        
        result = WindowAuditResult(
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            assets_traded=assets_traded,
            prices_cents=prices_cents,
            total_risk_usd=total_risk_usd,
            contracts_per_asset=contracts_per_asset,
            ok=ok,
            violations=violations
        )
        
        # Log audit result
        if ok:
            logger.info(
                "[15M-WINDOW-AUDIT] OK: assets_traded=%d, prices=%s, total_risk=$%.2f, contracts_per_asset=%s",
                len(assets_traded), prices_cents, total_risk_usd, contracts_per_asset
            )
        else:
            logger.error(
                "[15M-WINDOW-AUDIT] FAILED: assets_traded=%d, prices=%s, total_risk=$%.2f, contracts_per_asset=%s, violations=%s",
                len(assets_traded), prices_cents, total_risk_usd, contracts_per_asset, violations
            )
        
        return result
    
    def audit_live_window(
        self,
        current_orders: List[Dict[str, Any]],
        window_start_ts: float
    ) -> WindowAuditResult:
        """
        Audit the current (in-progress) window for invariant violations.
        
        This is called during the window to catch violations early.
        
        Args:
            current_orders: Orders placed so far in the current window
            window_start_ts: Current window start timestamp
        
        Returns:
            WindowAuditResult with audit findings
        """
        import time
        window_end_ts = time.time()
        return self.audit_window(current_orders, window_start_ts, window_end_ts)


def create_window_auditor_from_envelope(envelope: Any) -> WindowAuditor:
    """
    Create WindowAuditor from risk envelope configuration.
    
    Args:
        envelope: Risk envelope instance
    
    Returns:
        Configured WindowAuditor
    """
    max_total_risk_usd = envelope.max_total_notional_usd if hasattr(envelope, 'max_total_notional_usd') else 1.00
    
    # Use price range from profile guardrails if available
    min_price_cents = 10  # 2026-07-12: Canonical price band (10c) - aligned with GlobalSlotAllocator
    max_price_cents = 75  # 2026-07-12: Canonical price band (75c) - aligned with GlobalSlotAllocator
    
    if hasattr(envelope, 'guardrails_min_contract_price_cents'):
        min_price_cents = envelope.guardrails_min_contract_price_cents
    if hasattr(envelope, 'guardrails_max_contract_price_cents'):
        max_price_cents = envelope.guardrails_max_contract_price_cents
    
    return WindowAuditor(
        max_total_risk_usd=max_total_risk_usd,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        max_contracts_per_asset=1
    )

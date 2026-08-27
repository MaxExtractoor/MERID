"""Continuous Reconciliation Loop Against Kalshi API.

This module provides:
- PortfolioReconciler: Compares internal state to Kalshi API periodically
- Discrepancy detection and alerting
- Configurable tolerances for cash, positions, and PnL
- Background task for continuous reconciliation

Design principles:
- Kalshi API is control/sanity-check, not primary state
- Reconcile every N minutes (configurable)
- Alert only when discrepancies exceed thresholds and persist
- Store reconciliation results for investigation
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_models import (
    PortfolioSnapshot,
    ReconciliationResult,
    Position,
)
from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine
# CRITICAL FIX: Make bankroll service import lazy to prevent import-time bankroll service initialization
# This was triggering bankroll service initialization during KalshiVenueClient import
def _get_bankroll_service():
    """Lazy import wrapper for bankroll_service to prevent import-time initialization."""
    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
    return get_bankroll_service
from merid.event_venues.kalshi.client import KalshiVenueClient as KalshiClient

logger = get_logger("merid.event_venues.kalshi.portfolio_reconciliation")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

def _get_reconciliation_config() -> Dict[str, Any]:
    """Get reconciliation thresholds from profile YAML or fallback to env vars."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        adapter = get_active_profile()
        if adapter is not None and hasattr(adapter, 'profile') and adapter.profile is not None:
            # Check if profile has reconciliation section
            if hasattr(adapter.profile, 'reconciliation'):
                recon_config = adapter.profile.reconciliation
                return {
                    "interval_seconds": getattr(recon_config, 'reconciliation_interval_seconds', 300),
                    "cash_tolerance_cents": getattr(recon_config, 'cash_tolerance_cents', 1),
                    "pnl_tolerance_cents": getattr(recon_config, 'pnl_tolerance_cents', 10),
                    "position_tolerance_contracts": getattr(recon_config, 'position_tolerance_contracts', 0),
                    "discrepancy_persistence_cycles": getattr(recon_config, 'discrepancy_persistence_cycles', 2),
                }
    except Exception:
        pass
    
    # Fallback to environment variables
    return {
        "interval_seconds": int(os.getenv("MERID_PORTFOLIO_RECONCILIATION_INTERVAL_SECONDS", "300")),
        "cash_tolerance_cents": int(os.getenv("MERID_PORTFOLIO_CASH_TOLERANCE_CENTS", "1")),
        "pnl_tolerance_cents": int(os.getenv("MERID_PORTFOLIO_PNL_TOLERANCE_CENTS", "10")),
        "position_tolerance_contracts": int(os.getenv("MERID_PORTFOLIO_POSITION_TOLERANCE_CONTRACTS", "0")),
        "discrepancy_persistence_cycles": int(os.getenv("MERID_PORTFOLIO_DISCREPANCY_PERSISTENCE_CYCLES", "2")),
    }

_RECONCILIATION_CONFIG = _get_reconciliation_config()
_RECONCILIATION_INTERVAL_SECONDS = _RECONCILIATION_CONFIG["interval_seconds"]
_CASH_TOLERANCE_CENTS = _RECONCILIATION_CONFIG["cash_tolerance_cents"]
_PNL_TOLERANCE_CENTS = _RECONCILIATION_CONFIG["pnl_tolerance_cents"]
_POSITION_TOLERANCE_CONTRACTS = _RECONCILIATION_CONFIG["position_tolerance_contracts"]
_DISCREPANCY_PERSISTENCE_CYCLES = _RECONCILIATION_CONFIG["discrepancy_persistence_cycles"]


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio Reconciler
# ═══════════════════════════════════════════════════════════════════════════

class PortfolioReconciler:
    """Continuous reconciliation loop against Kalshi API.
    
    Compares internal portfolio state (from event replay) to
    Kalshi's balance/portfolio endpoints and alerts on discrepancies.
    """
    
    _instance: Optional["PortfolioReconciler"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "PortfolioReconciler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._local_lock = threading.Lock()
        self._engine = get_portfolio_engine()
        self._bankroll_service = _get_bankroll_service()()
        self._kalshi_client = KalshiClient()
        
        # Reconciliation state
        self._enabled = True
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_reconciliation: Optional[datetime] = None
        self._discrepancy_history: Dict[str, int] = {}  # type -> consecutive count
        
        # Statistics
        self._reconciliation_count = 0
        self._discrepancy_count = 0
        
        self._initialized = True
        logger.info("PortfolioReconciler initialized")
    
    async def reconcile_once(self, account_id: str = "default") -> ReconciliationResult:
        """Perform a single reconciliation cycle.
        
        Args:
            account_id: Account to reconcile
            
        Returns:
            ReconciliationResult with comparison results
        """
        logger.info("Reconciliation: starting cycle for account=%s", account_id)
        
        # Get internal snapshot
        internal_snapshot = self._engine.get_snapshot(account_id)
        
        # Fetch Kalshi state
        kalshi_balance = None
        kalshi_timestamp = None
        
        try:
            # Use v2 bankroll service for reconciliation (single source of truth)
            summary = await self._bankroll_service.get_summary(caller_module="portfolio_reconciliation")
            
            # Convert v2 summary to legacy balance format for compatibility
            from merid.event_venues.kalshi.bankroll_service import BankrollResult
            kalshi_balance = BankrollResult(
                success=True,
                balance_cents=int(summary.available_cash_usd * 100) if summary.available_cash_usd else 0,
                portfolio_value_cents=await self._bankroll_service.get_portfolio_value_cents(),
                equity_usd=summary.equity_usd,
                timestamp=summary.as_of.timestamp() if summary.as_of else datetime.now(timezone.utc).timestamp(),
            )
            kalshi_timestamp = summary.as_of
        except Exception as e:
            logger.error(
                "Reconciliation: failed to fetch Kalshi balance: %s",
                e,
                exc_info=True
            )
            return ReconciliationResult(
                account_id=account_id,
                timestamp=datetime.now(timezone.utc),
                is_match=False,
                discrepancies=[f"Failed to fetch Kalshi balance: {e}"],
            )
        
        # Compare cash
        internal_cash = internal_snapshot.cash_available_cents
        kalshi_cash = kalshi_balance.balance_cents if kalshi_balance else 0
        cash_diff = kalshi_cash - internal_cash
        has_cash_discrepancy = abs(cash_diff) > _CASH_TOLERANCE_CENTS

        # Log equity reconciliation
        logger.info(
            "[EQUITY-RECON] bankroll_service_v2=%dc internal_ledger=%dc global_risk_guard=N/A diff=%dc match=%s",
            kalshi_cash, internal_cash, cash_diff, not has_cash_discrepancy
        )
        
        # Compare positions (detailed)
        internal_position_count = internal_snapshot.position_count
        kalshi_positions = []
        kalshi_position_count = 0
        position_discrepancies = []
        
        try:
            # Fetch positions from Kalshi portfolio endpoint
            kalshi_positions = await self._kalshi_client.get_positions_async()
            kalshi_position_count = len([p for p in kalshi_positions if p.quantity != 0])
            
            # Build position maps for comparison
            internal_pos_map = {
                f"{pos.ticker}_{pos.side}": pos
                for pos in internal_snapshot.positions.values()
                if pos.is_open
            }
            kalshi_pos_map = {
                f"{p.ticker}_{p.side}": p
                for p in kalshi_positions
                if p.quantity != 0
            }
            
            # Check for missing or extra positions
            all_keys = set(internal_pos_map.keys()) | set(kalshi_pos_map.keys())
            for key in all_keys:
                internal_pos = internal_pos_map.get(key)
                kalshi_pos = kalshi_pos_map.get(key)
                
                if internal_pos and not kalshi_pos:
                    position_discrepancies.append(
                        f"Position in internal but not Kalshi: {key} qty={internal_pos.quantity}"
                    )
                elif kalshi_pos and not internal_pos:
                    position_discrepancies.append(
                        f"Position in Kalshi but not internal: {key} qty={kalshi_pos.quantity}"
                    )
                else:
                    # Both exist - compare details
                    qty_diff = abs(internal_pos.quantity - kalshi_pos.quantity)
                    if qty_diff > _POSITION_TOLERANCE_CONTRACTS:
                        position_discrepancies.append(
                            f"Position quantity mismatch {key}: internal={internal_pos.quantity} kalshi={kalshi_pos.quantity}"
                        )
                    
                    price_diff = abs(internal_pos.avg_entry_price_cents - kalshi_pos.avg_entry_price_cents)
                    if price_diff > 1:  # Allow 1 cent rounding
                        position_discrepancies.append(
                            f"Position avg price mismatch {key}: internal={internal_pos.avg_entry_price_cents}c kalshi={kalshi_pos.avg_entry_price_cents}c"
                        )
                    
        except Exception as e:
            logger.error("Reconciliation: failed to fetch Kalshi positions: %s", e, exc_info=True)
            position_discrepancies.append(f"Failed to fetch Kalshi positions: {e}")
        
        position_diff_count = abs(internal_position_count - kalshi_position_count)
        has_position_discrepancy = len(position_discrepancies) > 0 or position_diff_count > 0
        
        # Compare PnL
        internal_pnl = internal_snapshot.total_pnl_cents
        kalshi_pnl = kalshi_balance.portfolio_value_cents - kalshi_balance.balance_cents if kalshi_balance else 0
        pnl_diff = kalshi_pnl - internal_pnl
        has_pnl_discrepancy = abs(pnl_diff) > _PNL_TOLERANCE_CENTS
        
        # Validate fundamental accounting equation
        # Current Equity = Initial Balance + Deposits - Withdrawals + Realized PnL + Unrealized PnL
        accounting_validation_discrepancies = []
        if kalshi_balance:
            try:
                from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine
                engine = get_portfolio_engine()
                
                # Get cash ledger for deposits/withdrawals
                cash_ledger = engine._cash_ledger if hasattr(engine, '_cash_ledger') else []
                total_deposits = sum(
                    entry.amount_cents for entry in cash_ledger
                    if entry.account_id == account_id and entry.event_type.value == "deposit"
                )
                total_withdrawals = sum(
                    entry.amount_cents for entry in cash_ledger
                    if entry.account_id == account_id and entry.event_type.value == "withdrawal"
                )
                
                # Calculate expected equity from accounting equation
                # Note: Initial balance is tracked as first deposit or inferred from cash ledger
                initial_balance = total_deposits if total_deposits > 0 else internal_snapshot.cash_available_cents
                expected_equity = initial_balance - total_withdrawals + internal_snapshot.realized_pnl_cents + internal_snapshot.unrealized_pnl_cents
                actual_equity = kalshi_balance.balance_cents + kalshi_balance.portfolio_value_cents
                
                accounting_diff = actual_equity - expected_equity
                if abs(accounting_diff) > _PNL_TOLERANCE_CENTS:
                    accounting_validation_discrepancies.append(
                        f"Accounting equation violation: expected_equity={expected_equity}c actual_equity={actual_equity}c diff={accounting_diff}c "
                        f"(deposits={total_deposits}c withdrawals={total_withdrawals}c realized={internal_snapshot.realized_pnl_cents}c unrealized={internal_snapshot.unrealized_pnl_cents}c)"
                    )
                    logger.warning(
                        "Reconciliation: Accounting equation violation - %s",
                        accounting_validation_discrepancies[0]
                    )
                
                # Validate position_cache realized PnL against fills_ledger canonical source
                # This detects calculation drift between real-time cache and persistent ledger
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                    position_cache = get_position_cache()
                    fills_ledger = get_fills_ledger()
                    
                    # Sum realized PnL from position_cache (per-position tracking)
                    cache_positions = position_cache.get_all_positions(validate_freshness=False)
                    cache_realized_pnl = sum(
                        float(getattr(pos, 'realized_pnl_usd', 0)) * 100  # Convert USD to cents
                        for pos in cache_positions.values()
                    )
                    
                    # Get canonical realized PnL from fills_ledger
                    ledger_summary = fills_ledger.summary()
                    ledger_realized_pnl = ledger_summary.get("total_realized_pnl_usd", 0) * 100  # Convert USD to cents
                    
                    # Compare (allow tolerance for rounding differences)
                    pnl_drift = abs(cache_realized_pnl - ledger_realized_pnl)
                    if pnl_drift > _PNL_TOLERANCE_CENTS:
                        accounting_validation_discrepancies.append(
                            f"PnL calculation drift: position_cache={cache_realized_pnl}c fills_ledger={ledger_realized_pnl}c diff={pnl_drift}c"
                        )
                        logger.warning(
                            "Reconciliation: PnL calculation drift detected - position_cache=%dc fills_ledger=%dc diff=%dc",
                            cache_realized_pnl,
                            ledger_realized_pnl,
                            pnl_drift
                        )
                except Exception as e:
                    logger.debug("Reconciliation: PnL drift validation skipped (position_cache/fills_ledger unavailable): %s", e)
            except Exception as e:
                logger.debug("Reconciliation: Accounting equation validation skipped (portfolio_engine unavailable): %s", e)
        
        # Build result
        discrepancies = []
        if has_cash_discrepancy:
            discrepancies.append(f"Cash discrepancy: {cash_diff} cents")
        if has_position_discrepancy:
            discrepancies.append(f"Position discrepancies: {position_diff_count} count diff, {len(position_discrepancies)} detail issues")
            discrepancies.extend(position_discrepancies[:5])  # Include first 5 detailed issues
        if has_pnl_discrepancy:
            discrepancies.append(f"PnL discrepancy: {pnl_diff} cents")
        if accounting_validation_discrepancies:
            discrepancies.extend(accounting_validation_discrepancies)
        
        is_match = not (has_cash_discrepancy or has_position_discrepancy or has_pnl_discrepancy or len(accounting_validation_discrepancies) > 0)
        
        result = ReconciliationResult(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            is_match=is_match,
            cash_diff_cents=cash_diff,
            cash_tolerance_cents=_CASH_TOLERANCE_CENTS,
            position_diff_count=position_diff_count,
            pnl_diff_cents=pnl_diff,
            pnl_tolerance_cents=_PNL_TOLERANCE_CENTS,
            internal_sequence_id=internal_snapshot.sequence_id,
            kalshi_api_timestamp=kalshi_timestamp,
            discrepancies=discrepancies,
        )
        
        # Update statistics
        self._reconciliation_count += 1
        if not is_match:
            self._discrepancy_count += 1
        
        # Log result
        if is_match:
            logger.info(
                "Reconciliation: MATCH (cash=%dc positions=%d pnl=%dc)",
                cash_diff,
                position_diff_count,
                pnl_diff
            )
        else:
            logger.warning(
                "Reconciliation: DISCREPANCY (cash=%dc positions=%d pnl=%dc)",
                cash_diff,
                position_diff_count,
                pnl_diff
            )
            
            # Track persistence
            for discrepancy_type in ["cash", "position", "pnl"]:
                key = f"{account_id}_{discrepancy_type}"
                self._discrepancy_history[key] = self._discrepancy_history.get(key, 0) + 1
                
                # Alert if persists
                if self._discrepancy_history[key] >= _DISCREPANCY_PERSISTENCE_CYCLES:
                    logger.error(
                        "Reconciliation: PERSISTENT DISCREPANCY (%s) for %d cycles - %s",
                        discrepancy_type,
                        self._discrepancy_history[key],
                        discrepancies
                    )
        
        self._last_reconciliation = datetime.now(timezone.utc)
        return result
    
    async def start(self, account_id: str = "default") -> None:
        """Start continuous reconciliation loop.
        
        Args:
            account_id: Account to reconcile
        """
        if self._running:
            logger.warning("Reconciliation: already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._reconciliation_loop(account_id))
        logger.info(
            "Reconciliation: started (interval=%ds, account=%s)",
            _RECONCILIATION_INTERVAL_SECONDS,
            account_id
        )
    
    async def stop(self) -> None:
        """Stop continuous reconciliation loop."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Reconciliation: stopped")
    
    async def _reconciliation_loop(self, account_id: str) -> None:
        """Background reconciliation loop."""
        while self._running:
            try:
                await self.reconcile_once(account_id)
            except Exception as e:
                logger.error(
                    "Reconciliation: error in loop: %s",
                    e,
                    exc_info=True
                )
            
            # Wait for next cycle
            await asyncio.sleep(_RECONCILIATION_INTERVAL_SECONDS)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get reconciliation statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._local_lock:
            return {
                "enabled": self._enabled,
                "running": self._running,
                "reconciliation_count": self._reconciliation_count,
                "discrepancy_count": self._discrepancy_count,
                "last_reconciliation": self._last_reconciliation.isoformat() if self._last_reconciliation else None,
                "discrepancy_history": self._discrepancy_history.copy(),
                "interval_seconds": _RECONCILIATION_INTERVAL_SECONDS,
                "cash_tolerance_cents": _CASH_TOLERANCE_CENTS,
                "pnl_tolerance_cents": _PNL_TOLERANCE_CENTS,
                "position_tolerance_contracts": _POSITION_TOLERANCE_CONTRACTS,
                "discrepancy_persistence_cycles": _DISCREPANCY_PERSISTENCE_CYCLES,
            }
    
    def enable(self) -> None:
        """Enable reconciliation."""
        with self._local_lock:
            self._enabled = True
            logger.info("Reconciliation: enabled")
    
    def disable(self) -> None:
        """Disable reconciliation."""
        with self._local_lock:
            self._enabled = False
            logger.info("Reconciliation: disabled")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

def get_portfolio_reconciler() -> PortfolioReconciler:
    """Get the singleton PortfolioReconciler instance."""
    return PortfolioReconciler()

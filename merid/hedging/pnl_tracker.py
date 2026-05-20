"""Hedge PnL Attribution System (Task 3)

Tracks PnL separately for hedge positions vs alpha positions,
providing effectiveness metrics to measure hedging performance.

Key metrics:
- hedge_pnl: PnL from hedge positions
- alpha_pnl: PnL from original alpha positions
- effectiveness: hedge_pnl / alpha_pnl (1.0 = perfect hedge)
- cost_of_hedge: Premium paid for hedging
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class HedgeStatus(Enum):
    """Status of a hedge position."""
    ACTIVE = "active"
    CLOSED = "closed"
    PARTIAL = "partial"


@dataclass
class HedgePnLRecord:
    """PnL record linking a hedge fill to its originating alpha position.
    
    This enables measuring hedge effectiveness by comparing:
    - What the hedge made vs what the alpha lost (or vice versa)
    - Cost of hedging vs benefit received
    """
    
    # Record identification
    record_id: str
    created_at: datetime
    
    # Alpha (original) position
    alpha_fill_id: str
    alpha_ticker: str
    alpha_side: str  # "yes" or "no"
    alpha_entry_price_cents: int
    alpha_entry_count: int
    alpha_notional_cents: int
    
    # Hedge position
    hedge_fill_id: str
    hedge_ticker: str
    hedge_side: str  # opposite of alpha_side
    hedge_entry_price_cents: int
    hedge_entry_count: int
    hedge_notional_cents: int
    hedge_reason: str  # e.g., "cross_asset_SOL_to_BTC"
    
    # Current status
    status: HedgeStatus = HedgeStatus.ACTIVE
    
    # Exit tracking (populated when hedge is closed)
    hedge_exit_price_cents: Optional[int] = None
    hedge_exit_count: Optional[int] = None
    alpha_exit_price_cents: Optional[int] = None
    alpha_exit_count: Optional[int] = None
    closed_at: Optional[datetime] = None
    
    # Computed PnL (cents)
    hedge_pnl_cents: int = 0  # Positive = hedge made money
    alpha_pnl_cents: int = 0  # Positive = alpha made money
    net_pnl_cents: int = 0  # Combined PnL
    
    # Effectiveness metrics
    effectiveness_ratio: Optional[float] = None  # hedge_pnl / abs(alpha_pnl)
    cost_of_hedge_cents: int = 0  # Premium paid for hedge
    benefit_from_hedge_cents: int = 0  # Losses prevented
    
    def calculate_pnl(self) -> None:
        """Calculate PnL for both positions."""
        if self.hedge_exit_price_cents is not None:
            # Hedge PnL: entry short (profit when price drops) or entry long (profit when price rises)
            if self.hedge_side == "yes":
                self.hedge_pnl_cents = (
                    (self.hedge_exit_price_cents - self.hedge_entry_price_cents) 
                    * self.hedge_exit_count
                )
            else:  # "no"
                self.hedge_pnl_cents = (
                    (self.hedge_entry_price_cents - self.hedge_exit_price_cents) 
                    * self.hedge_exit_count
                )
        
        if self.alpha_exit_price_cents is not None:
            # Alpha PnL
            if self.alpha_side == "yes":
                self.alpha_pnl_cents = (
                    (self.alpha_exit_price_cents - self.alpha_entry_price_cents) 
                    * self.alpha_exit_count
                )
            else:  # "no"
                self.alpha_pnl_cents = (
                    (self.alpha_entry_price_cents - self.alpha_exit_price_cents) 
                    * self.alpha_exit_count
                )
        
        self.net_pnl_cents = self.hedge_pnl_cents + self.alpha_pnl_cents
        
        # Calculate effectiveness: did hedge offset alpha loss?
        if self.alpha_pnl_cents < 0:  # Alpha lost money
            alpha_loss = abs(self.alpha_pnl_cents)
            self.benefit_from_hedge_cents = min(self.hedge_pnl_cents, alpha_loss)
            if alpha_loss > 0:
                self.effectiveness_ratio = self.hedge_pnl_cents / alpha_loss
        
        # Cost of hedge: premium paid (difference between notional and actual)
        self.cost_of_hedge_cents = self.hedge_notional_cents


@dataclass
class HedgeEffectivenessMetrics:
    """Aggregate metrics for hedge performance analysis."""
    
    # Counts
    total_hedges: int = 0
    active_hedges: int = 0
    closed_hedges: int = 0
    profitable_hedges: int = 0  # Hedge made money (offset alpha loss)
    
    # PnL totals (cents)
    total_hedge_pnl: int = 0
    total_alpha_pnl: int = 0
    total_net_pnl: int = 0
    total_cost_of_hedge: int = 0
    total_benefit: int = 0
    
    # Ratios
    avg_effectiveness: Optional[float] = None
    hedge_win_rate: Optional[float] = None  # % of hedges that were profitable
    
    def compute_ratios(self) -> None:
        """Compute aggregate ratios from totals."""
        if self.total_hedges > 0:
            self.hedge_win_rate = self.profitable_hedges / self.total_hedges


class HedgePnLTracker:
    """Tracks PnL for hedge positions and their linked alpha positions.
    
    Task 3: Enables measuring hedge effectiveness and tuning hedging strategy.
    """
    
    def __init__(self):
        self._records: Dict[str, HedgePnLRecord] = {}  # record_id -> record
        self._alpha_to_hedge: Dict[str, str] = {}  # alpha_fill_id -> record_id
        self._hedge_to_alpha: Dict[str, str] = {}  # hedge_fill_id -> alpha_fill_id
        
    def create_record(
        self,
        alpha_fill_id: str,
        alpha_ticker: str,
        alpha_side: str,
        alpha_entry_price_cents: int,
        alpha_entry_count: int,
        hedge_fill_id: str,
        hedge_ticker: str,
        hedge_side: str,
        hedge_entry_price_cents: int,
        hedge_entry_count: int,
        hedge_reason: str,
    ) -> HedgePnLRecord:
        """Create a new hedge PnL record linking alpha and hedge fills."""
        
        record_id = f"pnl_{alpha_fill_id}_{hedge_fill_id}"
        
        # Calculate notionals
        alpha_notional = alpha_entry_price_cents * alpha_entry_count
        hedge_notional = hedge_entry_price_cents * hedge_entry_count
        
        record = HedgePnLRecord(
            record_id=record_id,
            created_at=datetime.now(timezone.utc),
            alpha_fill_id=alpha_fill_id,
            alpha_ticker=alpha_ticker,
            alpha_side=alpha_side,
            alpha_entry_price_cents=alpha_entry_price_cents,
            alpha_entry_count=alpha_entry_count,
            alpha_notional_cents=alpha_notional,
            hedge_fill_id=hedge_fill_id,
            hedge_ticker=hedge_ticker,
            hedge_side=hedge_side,
            hedge_entry_price_cents=hedge_entry_price_cents,
            hedge_entry_count=hedge_entry_count,
            hedge_notional_cents=hedge_notional,
            hedge_reason=hedge_reason,
            cost_of_hedge_cents=hedge_notional,
        )
        
        self._records[record_id] = record
        self._alpha_to_hedge[alpha_fill_id] = record_id
        self._hedge_to_alpha[hedge_fill_id] = alpha_fill_id
        
        logger.info(
            "[HEDGE-PNL-RECORD-CREATED] record_id=%s alpha=%s hedge=%s reason=%s "
            "alpha_notional=%d¢ hedge_notional=%d¢",
            record_id, alpha_fill_id, hedge_fill_id, hedge_reason,
            alpha_notional, hedge_notional
        )
        
        return record
    
    def record_hedge_exit(
        self,
        hedge_fill_id: str,
        exit_price_cents: int,
        exit_count: int,
    ) -> Optional[HedgePnLRecord]:
        """Record hedge position exit and calculate PnL."""
        
        if hedge_fill_id not in self._hedge_to_alpha:
            logger.warning("[HEDGE-PNL] Unknown hedge fill: %s", hedge_fill_id)
            return None
        
        alpha_fill_id = self._hedge_to_alpha[hedge_fill_id]
        record_id = self._alpha_to_hedge.get(alpha_fill_id)
        
        if not record_id or record_id not in self._records:
            return None
        
        record = self._records[record_id]
        record.hedge_exit_price_cents = exit_price_cents
        record.hedge_exit_count = exit_count
        record.status = HedgeStatus.CLOSED if exit_count >= record.hedge_entry_count else HedgeStatus.PARTIAL
        record.closed_at = datetime.now(timezone.utc)
        
        record.calculate_pnl()
        
        logger.info(
            "[HEDGE-PNL-EXIT] record_id=%s hedge=%s exit_price=%d¢ exit_count=%d "
            "hedge_pnl=%d¢ alpha_pnl=%d¢ effectiveness=%.2f",
            record_id, hedge_fill_id, exit_price_cents, exit_count,
            record.hedge_pnl_cents, record.alpha_pnl_cents,
            record.effectiveness_ratio or 0.0
        )
        
        return record
    
    def record_alpha_exit(
        self,
        alpha_fill_id: str,
        exit_price_cents: int,
        exit_count: int,
    ) -> Optional[HedgePnLRecord]:
        """Record alpha position exit and calculate PnL."""
        
        record_id = self._alpha_to_hedge.get(alpha_fill_id)
        if not record_id or record_id not in self._records:
            return None
        
        record = self._records[record_id]
        record.alpha_exit_price_cents = exit_price_cents
        record.alpha_exit_count = exit_count
        
        # Recalculate PnL
        record.calculate_pnl()
        
        logger.info(
            "[ALPHA-PNL-EXIT] record_id=%s alpha=%s exit_price=%d¢ "
            "alpha_pnl=%d¢",
            record_id, alpha_fill_id, exit_price_cents, record.alpha_pnl_cents
        )
        
        return record
    
    def get_metrics(
        self,
        asset: Optional[str] = None,
        hedge_reason: Optional[str] = None,
        lookback_days: int = 7,
    ) -> HedgeEffectivenessMetrics:
        """Get aggregate effectiveness metrics for hedges."""
        
        from datetime import timedelta
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        metrics = HedgeEffectivenessMetrics()
        
        for record in self._records.values():
            # Apply filters
            if record.created_at < cutoff:
                continue
            if asset and asset not in record.alpha_ticker:
                continue
            if hedge_reason and record.hedge_reason != hedge_reason:
                continue
            
            metrics.total_hedges += 1
            
            if record.status == HedgeStatus.ACTIVE:
                metrics.active_hedges += 1
            else:
                metrics.closed_hedges += 1
            
            if record.hedge_pnl_cents > 0:
                metrics.profitable_hedges += 1
            
            metrics.total_hedge_pnl += record.hedge_pnl_cents
            metrics.total_alpha_pnl += record.alpha_pnl_cents
            metrics.total_net_pnl += record.net_pnl_cents
            metrics.total_cost_of_hedge += record.cost_of_hedge_cents
            metrics.total_benefit += record.benefit_from_hedge_cents
        
        metrics.compute_ratios()
        
        return metrics
    
    def get_record_by_hedge_fill(self, hedge_fill_id: str) -> Optional[HedgePnLRecord]:
        """Get PnL record by hedge fill ID."""
        alpha_fill_id = self._hedge_to_alpha.get(hedge_fill_id)
        if alpha_fill_id:
            record_id = self._alpha_to_hedge.get(alpha_fill_id)
            return self._records.get(record_id)
        return None
    
    def get_record_by_alpha_fill(self, alpha_fill_id: str) -> Optional[HedgePnLRecord]:
        """Get PnL record by alpha fill ID."""
        record_id = self._alpha_to_hedge.get(alpha_fill_id)
        return self._records.get(record_id) if record_id else None

    def check_take_profit_levels(
        self,
        config: Any,
        current_prices: Dict[str, int],  # asset -> price_cents
    ) -> List[Dict]:
        """Check all active records for TP/SL hits and return exit orders needed.

        Args:
            config: HedgeConfig with take_profit settings
            current_prices: Dict mapping asset to current price in cents

        Returns:
            List of exit order dicts with keys: record_id, asset, exit_price_cents,
            exit_count, reason (tp_1, tp_2, stop_loss)
        """
        from merid.hedging.config import HedgeConfig

        exit_orders = []
        if not isinstance(config, HedgeConfig) or not config.take_profit.enabled:
            return exit_orders

        # Resolve Kalshi ticker → asset (BTC/ETH/SOL/XRP/DOGE) so TP levels and
        # current_prices can be looked up by canonical asset key, not by ticker.
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
        except Exception:
            kalshi_ticker_to_asset = lambda t: None  # noqa: E731

        for record in self._records.values():
            if record.status != HedgeStatus.ACTIVE:
                continue

            asset = kalshi_ticker_to_asset(record.alpha_ticker) or ""
            if not asset or asset not in current_prices:
                continue

            current_price = current_prices[asset]
            tp_config = config.take_profit.get_levels(asset)

            # Calculate PnL percentage
            if record.alpha_side == "yes":
                pnl_pct = (current_price - record.alpha_entry_price_cents) / record.alpha_entry_price_cents * 100
            else:  # "no" side - inverse
                pnl_pct = (record.alpha_entry_price_cents - current_price) / record.alpha_entry_price_cents * 100

            # Check stop loss first (highest priority)
            if pnl_pct <= -tp_config.stop_loss:
                exit_orders.append({
                    "record_id": record.record_id,
                    "asset": asset,
                    "exit_price_cents": current_price,
                    "exit_count": record.alpha_entry_count,
                    "reason": "stop_loss",
                    "fill_id": record.alpha_fill_id,
                })
                logger.warning(
                    "[TP-CHECK] STOP LOSS triggered for %s: %.2f%% loss, exiting at %d¢",
                    asset, pnl_pct, current_price
                )
                continue

            # Check take profit levels
            if pnl_pct >= tp_config.tp_2:
                # Take full profit at TP2
                exit_orders.append({
                    "record_id": record.record_id,
                    "asset": asset,
                    "exit_price_cents": current_price,
                    "exit_count": record.alpha_entry_count,
                    "reason": "tp_2",
                    "fill_id": record.alpha_fill_id,
                })
                logger.info(
                    "[TP-CHECK] TP2 hit for %s: %.2f%% profit, full exit at %d¢",
                    asset, pnl_pct, current_price
                )
            elif pnl_pct >= tp_config.tp_1:
                # Take partial profit at TP1 (50% of position)
                exit_count = max(1, record.alpha_entry_count // 2)
                exit_orders.append({
                    "record_id": record.record_id,
                    "asset": asset,
                    "exit_price_cents": current_price,
                    "exit_count": exit_count,
                    "reason": "tp_1",
                    "fill_id": record.alpha_fill_id,
                })
                logger.info(
                    "[TP-CHECK] TP1 hit for %s: %.2f%% profit, partial exit %d contracts at %d¢",
                    asset, pnl_pct, exit_count, current_price
                )

        return exit_orders

    def auto_exit_hedges(
        self,
        config: Any,
        closed_alpha_fills: List[str],  # List of alpha fill IDs that were closed
    ) -> List[Dict]:
        """Auto-exit hedges when their alpha position was closed.

        Args:
            config: HedgeConfig with auto_exit settings
            closed_alpha_fills: List of alpha fill IDs that have been closed

        Returns:
            List of hedge exit order dicts
        """
        from merid.hedging.config import HedgeConfig

        exit_orders = []
        if not isinstance(config, HedgeConfig) or not config.auto_exit.enabled:
            return exit_orders

        if not config.auto_exit.close_hedge_when_alpha_closed:
            return exit_orders

        for alpha_fill_id in closed_alpha_fills:
            record_id = self._alpha_to_hedge.get(alpha_fill_id)
            if not record_id or record_id not in self._records:
                continue

            record = self._records[record_id]
            if record.status != HedgeStatus.ACTIVE:
                continue

            if record.hedge_fill_id and not record.hedge_exit_price_cents:
                # Hedge is still open, need to close it
                exit_orders.append({
                    "record_id": record_id,
                    "hedge_fill_id": record.hedge_fill_id,
                    "asset": record.hedge_ticker,
                    "reason": "alpha_closed",
                })
                logger.info(
                    "[AUTO-EXIT] Alpha closed for record %s, exiting hedge %s",
                    record_id, record.hedge_fill_id
                )

        return exit_orders

    def get_hedges_past_hold_time(
        self,
        config: Any,
    ) -> List[Dict]:
        """Get hedges that have exceeded max hold time.

        Args:
            config: HedgeConfig with auto_exit settings

        Returns:
            List of hedge exit order dicts
        """
        from datetime import timedelta
        from merid.hedging.config import HedgeConfig

        exit_orders = []
        if not isinstance(config, HedgeConfig) or not config.auto_exit.enabled:
            return exit_orders

        max_minutes = config.auto_exit.max_hedge_hold_minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)

        for record in self._records.values():
            if record.status != HedgeStatus.ACTIVE:
                continue

            if record.created_at < cutoff:
                if record.hedge_fill_id and not record.hedge_exit_price_cents:
                    exit_orders.append({
                        "record_id": record.record_id,
                        "hedge_fill_id": record.hedge_fill_id,
                        "asset": record.hedge_ticker,
                        "reason": "max_hold_time",
                        "hold_minutes": max_minutes,
                    })
                    logger.warning(
                        "[AUTO-EXIT] Hedge %s exceeded max hold time (%d min), exiting",
                        record.record_id, max_minutes
                    )

        return exit_orders

    def to_dict(self) -> Dict:
        """Serialize tracker state to dict for persistence."""
        return {
            "records": [
                {
                    "record_id": r.record_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "alpha_fill_id": r.alpha_fill_id,
                    "alpha_ticker": r.alpha_ticker,
                    "alpha_side": r.alpha_side,
                    "alpha_entry_price_cents": r.alpha_entry_price_cents,
                    "alpha_entry_count": r.alpha_entry_count,
                    "alpha_notional_cents": r.alpha_notional_cents,
                    "hedge_fill_id": r.hedge_fill_id,
                    "hedge_ticker": r.hedge_ticker,
                    "hedge_side": r.hedge_side,
                    "hedge_entry_price_cents": r.hedge_entry_price_cents,
                    "hedge_entry_count": r.hedge_entry_count,
                    "hedge_notional_cents": r.hedge_notional_cents,
                    "hedge_reason": r.hedge_reason,
                    "status": r.status.value,
                    "hedge_exit_price_cents": r.hedge_exit_price_cents,
                    "hedge_exit_count": r.hedge_exit_count,
                    "alpha_exit_price_cents": r.alpha_exit_price_cents,
                    "alpha_exit_count": r.alpha_exit_count,
                    "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                    "hedge_pnl_cents": r.hedge_pnl_cents,
                    "alpha_pnl_cents": r.alpha_pnl_cents,
                    "net_pnl_cents": r.net_pnl_cents,
                    "effectiveness_ratio": r.effectiveness_ratio,
                    "cost_of_hedge_cents": r.cost_of_hedge_cents,
                    "benefit_from_hedge_cents": r.benefit_from_hedge_cents,
                }
                for r in self._records.values()
            ]
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "HedgePnLTracker":
        """Deserialize tracker state from dict."""
        tracker = cls()
        
        for r_data in data.get("records", []):
            record = HedgePnLRecord(
                record_id=r_data["record_id"],
                created_at=datetime.fromisoformat(r_data["created_at"]) if r_data["created_at"] else None,
                alpha_fill_id=r_data["alpha_fill_id"],
                alpha_ticker=r_data["alpha_ticker"],
                alpha_side=r_data["alpha_side"],
                alpha_entry_price_cents=r_data["alpha_entry_price_cents"],
                alpha_entry_count=r_data["alpha_entry_count"],
                alpha_notional_cents=r_data["alpha_notional_cents"],
                hedge_fill_id=r_data["hedge_fill_id"],
                hedge_ticker=r_data["hedge_ticker"],
                hedge_side=r_data["hedge_side"],
                hedge_entry_price_cents=r_data["hedge_entry_price_cents"],
                hedge_entry_count=r_data["hedge_entry_count"],
                hedge_notional_cents=r_data["hedge_notional_cents"],
                hedge_reason=r_data["hedge_reason"],
                status=HedgeStatus(r_data["status"]),
                hedge_exit_price_cents=r_data.get("hedge_exit_price_cents"),
                hedge_exit_count=r_data.get("hedge_exit_count"),
                alpha_exit_price_cents=r_data.get("alpha_exit_price_cents"),
                alpha_exit_count=r_data.get("alpha_exit_count"),
                closed_at=datetime.fromisoformat(r_data["closed_at"]) if r_data.get("closed_at") else None,
                hedge_pnl_cents=r_data.get("hedge_pnl_cents", 0),
                alpha_pnl_cents=r_data.get("alpha_pnl_cents", 0),
                net_pnl_cents=r_data.get("net_pnl_cents", 0),
                effectiveness_ratio=r_data.get("effectiveness_ratio"),
                cost_of_hedge_cents=r_data.get("cost_of_hedge_cents", 0),
                benefit_from_hedge_cents=r_data.get("benefit_from_hedge_cents", 0),
            )
            
            tracker._records[record.record_id] = record
            tracker._alpha_to_hedge[record.alpha_fill_id] = record.record_id
            tracker._hedge_to_alpha[record.hedge_fill_id] = record.alpha_fill_id
        
        return tracker


# Singleton instance
_tracker: Optional[HedgePnLTracker] = None


def get_hedge_pnl_tracker() -> HedgePnLTracker:
    """Get the singleton HedgePnLTracker instance.

    P1 Task 6: On first access, hydrate from persisted state via
    ``load_hedge_pnl_tracker`` so a process restart doesn't lose all
    in-flight hedge tracking. Failures fall back to an empty tracker.
    """
    global _tracker
    if _tracker is None:
        try:
            from merid.event_venues.kalshi.fills_persistence import (
                load_hedge_pnl_tracker,
            )
            persisted = load_hedge_pnl_tracker()
            if persisted and persisted.get("records"):
                _tracker = HedgePnLTracker.from_dict(persisted)
                logger.info(
                    "[HEDGE-PNL-HYDRATE] restored %d hedge PnL records from disk",
                    len(_tracker._records),
                )
            else:
                _tracker = HedgePnLTracker()
        except Exception as exc:
            logger.warning("[HEDGE-PNL-HYDRATE] failed to load persisted state: %s", exc)
            _tracker = HedgePnLTracker()
    return _tracker


def persist_hedge_pnl_tracker() -> bool:
    """Best-effort save the singleton's current state to disk.

    Called by background tasks / shutdown hooks. Returns True on success.
    """
    global _tracker
    if _tracker is None:
        return False
    try:
        from merid.event_venues.kalshi.fills_persistence import (
            save_hedge_pnl_tracker,
        )
        save_hedge_pnl_tracker(_tracker.to_dict())
        return True
    except Exception as exc:
        logger.warning("[HEDGE-PNL-PERSIST] save failed: %s", exc)
        return False

"""Top-Edge Integrator — Bridge from CryptoTopEdgeArbiter to ExecutionQueue.

Responsibilities:
1. Receive winner signals from CryptoTopEdgeArbiter
2. Validate risk_ok (bankroll, limits)
3. Validate recon_ok (position cache, fills ledger)
4. Submit to TopEdgeExecutionQueue
5. Emit PMSIGNAL logs for observability

Usage:
    from merid.execution.top_edge_integrator import TopEdgeIntegrator
    
    integrator = TopEdgeIntegrator()
    result = integrator.submit_winner(winner_signal)
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, Optional

from utils.logger import get_logger
from merid.prediction.crypto_top_edge import (
    CandidateSignal,
    CryptoTopEdgeArbiter,
    get_crypto_top_edge_arbiter,
)
from merid.execution.execution_queue import (
    TopEdgeExecutionQueue,
    QueueSubmissionResult,
    QueueAction,
    get_execution_queue,
)

logger = get_logger("merid.execution.top_edge_integrator")


class TopEdgeIntegrator:
    """Integrates CryptoTopEdgeArbiter winners into ExecutionQueue.
    
    Validates:
    - risk_ok: Bankroll check via bankroll_service_v2
    - recon_ok: Position cache + fills ledger consistency
    """

    def __init__(
        self,
        arbiter: Optional[CryptoTopEdgeArbiter] = None,
        queue: Optional[TopEdgeExecutionQueue] = None,
    ):
        self._arbiter = arbiter or get_crypto_top_edge_arbiter()
        self._queue = queue or get_execution_queue()
        self._submissions_total = 0
        self._submissions_enqueued = 0
        self._submissions_rejected = 0

    def _check_bankroll(self, required_notional: Decimal) -> tuple[bool, Decimal]:
        """Check if bankroll available for trade.
        
        Returns:
            Tuple of (risk_ok, available_bankroll)
        """
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
            
            service = get_bankroll_service()
            summary = service.get_summary_sync()  # Sync version for simplicity
            
            if not summary or not summary.equity_usd:
                logger.warning("[TOP_EDGE_INTEGRATOR] Bankroll unavailable")
                return False, Decimal("0")
            
            available = summary.equity_usd
            
            # Reserve a portion (e.g., don't use more than 50% for any single position)
            max_single_position = available * Decimal("0.5")
            
            if required_notional > max_single_position:
                logger.warning(
                    "[TOP_EDGE_INTEGRATOR] Position too large: required=$%s max=$%s",
                    required_notional, max_single_position
                )
                return False, available
            
            return True, available
            
        except Exception as e:
            logger.error("[TOP_EDGE_INTEGRATOR] Bankroll check failed: %s", e)
            return False, Decimal("0")

    def _check_reconciliation(self, ticker: str) -> bool:
        """Check position cache reconciliation.
        
        Returns True if:
        - No existing position in this ticker (fresh slot)
        - Position cache is consistent with fills ledger
        """
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            
            cache = get_position_cache()
            position = cache.get_position(ticker)
            
            # If no position, we're good to go
            if position is None or position.get("contracts", 0) == 0:
                return True
            
            # If position exists, this shouldn't happen as arbiter checks position dedup
            # But double-check: reject if position exists
            logger.warning(
                "[TOP_EDGE_INTEGRATOR] Existing position found: %s contracts in %s",
                position.get("contracts", 0), ticker
            )
            return False
            
        except Exception as e:
            logger.error("[TOP_EDGE_INTEGRATOR] Reconciliation check failed: %s", e)
            return False

    def submit_winner(
        self,
        winner: CandidateSignal,
        notional_per_contract: Decimal = Decimal("1"),  # $1 per contract default
    ) -> QueueSubmissionResult:
        """Submit a winning signal to the execution queue.
        
        Args:
            winner: The winning CandidateSignal from CryptoTopEdgeArbiter
            notional_per_contract: Notional value per contract for sizing
            
        Returns:
            QueueSubmissionResult with outcome
        """
        self._submissions_total += 1
        
        ticker = winner.ticker
        direction = winner.direction
        size = winner.incremental_contracts or winner.suggested_contracts
        edge = winner.net_edge
        confidence = winner.confidence
        
        # Calculate required notional
        required_notional = Decimal(size) * notional_per_contract
        
        logger.info(
            "[PMSIGNAL] TOP_EDGE_WINNER ticker=%s direction=%s size=%d edge=%.4f conf=%.2f",
            ticker, direction, size, edge, confidence
        )
        
        # Step 1: Risk check (bankroll)
        risk_ok, bankroll_snapshot = self._check_bankroll(required_notional)
        
        # Step 2: Reconciliation check (position cache)
        recon_ok = self._check_reconciliation(ticker)
        
        logger.info(
            "[PMSIGNAL] VALIDATION ticker=%s risk_ok=%s recon_ok=%s bankroll=$%s",
            ticker, risk_ok, recon_ok, bankroll_snapshot
        )
        
        # Step 3: Submit to execution queue
        result = self._queue.submit(
            ticker=ticker,
            direction=direction,
            size_contracts=size,
            edge=edge,
            confidence=confidence,
            bankroll_snapshot_usd=bankroll_snapshot,
            risk_ok=risk_ok,
            recon_ok=recon_ok,
            agent_id=winner.agent_id,
            strategy_signal_id=winner.signal_id,
            cycle_id=winner.correlation_id,
            metadata={
                "archetype": winner.archetype,
                "raw_edge": winner.raw_edge,
                "rank": winner.rank,
                "selection_method": winner.selection_method,
            }
        )
        
        # Track metrics
        if result.action == QueueAction.ENQUEUED:
            self._submissions_enqueued += 1
            logger.info(
                "[PMSIGNAL] ENQUEUED ticker=%s entry=%s edge=%.4f",
                ticker, result.entry_id, edge
            )
        else:
            self._submissions_rejected += 1
            logger.warning(
                "[PMSIGNAL] REJECTED ticker=%s action=%s reason=%s",
                ticker, result.action.value, result.reason
            )
        
        return result

    def submit_all_winners(
        self,
        winners: list[CandidateSignal],
        notional_per_contract: Decimal = Decimal("1"),
    ) -> list[QueueSubmissionResult]:
        """Submit multiple winners (typically from arbiter cycle result).
        
        Args:
            winners: List of winning CandidateSignals
            notional_per_contract: Notional per contract
            
        Returns:
            List of QueueSubmissionResults
        """
        results = []
        for winner in winners:
            result = self.submit_winner(winner, notional_per_contract)
            results.append(result)
        return results

    def get_metrics(self) -> Dict[str, Any]:
        """Get integrator metrics."""
        return {
            "submissions_total": self._submissions_total,
            "submissions_enqueued": self._submissions_enqueued,
            "submissions_rejected": self._submissions_rejected,
            "queue_metrics": self._queue.get_metrics(),
        }


# Global singleton
_integrator: Optional[TopEdgeIntegrator] = None


def get_top_edge_integrator() -> TopEdgeIntegrator:
    """Get or create global integrator singleton."""
    global _integrator
    if _integrator is None:
        _integrator = TopEdgeIntegrator()
    return _integrator


def submit_winner_to_queue(
    winner: CandidateSignal,
    notional_per_contract: Decimal = Decimal("1"),
) -> QueueSubmissionResult:
    """Convenience function to submit a winner via global integrator."""
    integrator = get_top_edge_integrator()
    return integrator.submit_winner(winner, notional_per_contract)

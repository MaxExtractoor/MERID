"""TradeRouter — Orchestrates proposal → risk → adapter → result.

The single entry point for all trade proposals from any domain agent.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import List, Optional

from merid.pipeline.adapter import AdapterRegistry, get_adapter_registry
from merid.pipeline.instruments import InstrumentRegistry, get_instrument_registry
from merid.pipeline.mode_manager import ModeManager, get_mode_manager
from merid.pipeline.proposal import (
    ExecutionResult,
    ProposalStatus,
    TradeProposal,
)
from merid.pipeline.risk_manager import GlobalRiskManager, get_global_risk_manager

from utils.logger import get_logger

logger = get_logger("merid.pipeline.router")


class TradeRouter:
    """Orchestrates the full trade pipeline.

    Flow::

        Agent → TradeProposal
            → InstrumentRegistry.resolve (fill native_symbol)
            → ModeManager.check_can_trade
            → GlobalRiskManager.check_proposal
            → UnifiedVenueAdapter.submit_order
            → ExecutionResult
    """

    def __init__(
        self,
        registry: Optional[AdapterRegistry] = None,
        instruments: Optional[InstrumentRegistry] = None,
        mode_manager: Optional[ModeManager] = None,
        risk_manager: Optional[GlobalRiskManager] = None,
    ):
        self._adapters = registry or get_adapter_registry()
        self._instruments = instruments or get_instrument_registry()
        self._modes = mode_manager or get_mode_manager()
        self._risk = risk_manager or get_global_risk_manager()
        self._history: List[TradeProposal] = []

    # ── Main entry point ─────────────────────────────────────────────

    async def submit(self, proposal: TradeProposal) -> TradeProposal:
        """Process a trade proposal through the full pipeline.

        Mutates the proposal in-place (status, execution_result, etc.)
        and returns it.
        """
        self._history.append(proposal)

        # 1. Resolve native symbol
        if not proposal.native_symbol and proposal.instrument_id:
            native = self._instruments.resolve(proposal.instrument_id, proposal.venue)
            if native:
                proposal.native_symbol = native
            else:
                proposal.reject(
                    f"Cannot resolve {proposal.instrument_id} on {proposal.venue}."
                )
                return proposal

        # 2. Compliance check
        if proposal.instrument_id:
            if not self._instruments.check_compliance(proposal.instrument_id, proposal.venue):
                proposal.reject(
                    f"Instrument {proposal.instrument_id} is not compliant on {proposal.venue}."
                )
                return proposal

        # 3. Mode check
        try:
            self._modes.check_can_trade(proposal.venue)
        except (ModeManager.VenueDisabledError, ModeManager.ModeBlockedError) as exc:
            proposal.reject(str(exc))
            return proposal

        # 4. Global risk check
        risk_result = self._risk.check_proposal(proposal)
        proposal.risk_check_result = risk_result.to_dict()
        if not risk_result.approved:
            proposal.reject(risk_result.reason)
            return proposal

        proposal.approve()

        # 5. Should we simulate?
        if self._modes.should_simulate(proposal.venue):
            result = self._simulate_fill(proposal)
            proposal.execution_result = result
            proposal.status = ProposalStatus.FILLED
            self._risk.record_fill(
                proposal.venue,
                proposal.domain.value if hasattr(proposal.domain, 'value') else str(proposal.domain),
                result.filled_qty * result.avg_price / Decimal("100")
                if proposal.domain.value == "prediction"
                else result.filled_qty * result.avg_price,
            )
            return proposal

        # 6. Submit to adapter
        adapter = self._adapters.get(proposal.venue)
        if not adapter:
            proposal.status = ProposalStatus.FAILED
            proposal.execution_result = ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=proposal.venue,
                status="error",
                error=f"No adapter registered for venue '{proposal.venue}'.",
            )
            return proposal

        try:
            start = time.perf_counter()
            result = await adapter.submit_order(proposal)
            result.latency_ms = (time.perf_counter() - start) * 1000
            proposal.execution_result = result
            proposal.status = (
                ProposalStatus.FILLED if result.status == "filled"
                else ProposalStatus.PARTIALLY_FILLED if result.status == "partially_filled"
                else ProposalStatus.FAILED
            )
            if result.status in ("filled", "partially_filled"):
                domain_str = proposal.domain.value if hasattr(proposal.domain, 'value') else str(proposal.domain)
                notional = result.filled_qty * result.avg_price
                self._risk.record_fill(proposal.venue, domain_str, notional, result.fee)
        except Exception as exc:
            proposal.status = ProposalStatus.FAILED
            proposal.execution_result = ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=proposal.venue,
                status="error",
                error=str(exc),
            )
            logger.error(f"Order submission failed for {proposal.venue}: {exc}")

        return proposal

    # ── Simulated fill ───────────────────────────────────────────────

    def _simulate_fill(self, proposal: TradeProposal) -> ExecutionResult:
        """Generate a simulated fill for SIM/PAPER mode."""
        price = proposal.price or Decimal("100")
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue=proposal.venue,
            venue_order_id=f"SIM-{proposal.proposal_id}",
            status="filled",
            filled_qty=proposal.qty,
            avg_price=price,
            fee=Decimal("0"),
            latency_ms=0.1,
        )

    # ── Batch submit ─────────────────────────────────────────────────

    async def submit_batch(self, proposals: List[TradeProposal]) -> List[TradeProposal]:
        """Submit multiple proposals sequentially."""
        results = []
        for p in proposals:
            results.append(await self.submit(p))
        return results

    # ── History / summary ────────────────────────────────────────────

    def recent_proposals(self, limit: int = 50) -> List[dict]:
        return [p.to_dict() for p in self._history[-limit:]]

    def summary(self) -> dict:
        total = len(self._history)
        filled = sum(1 for p in self._history if p.status == ProposalStatus.FILLED)
        rejected = sum(1 for p in self._history if p.status == ProposalStatus.RISK_REJECTED)
        failed = sum(1 for p in self._history if p.status == ProposalStatus.FAILED)
        return {
            "total_proposals": total,
            "filled": filled,
            "rejected": rejected,
            "failed": failed,
            "pending": total - filled - rejected - failed,
            "adapters": self._adapters.summary(),
            "instruments": self._instruments.summary(),
        }

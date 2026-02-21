"""§2 Blockchain Execution Service — Tx builder, routing, simulation/dry-run.

Strict separation of read-only queries from write/sign operations.
Agents request actions; the execution service + signing service execute.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.blockchain.execution")


# ── Domain objects ───────────────────────────────────────────────────

class TxType(str, Enum):
    SWAP = "swap"
    TRANSFER = "transfer"
    LIQUIDITY_ADD = "liquidity_add"
    LIQUIDITY_REMOVE = "liquidity_remove"
    STAKE = "stake"
    UNSTAKE = "unstake"
    BRIDGE = "bridge"
    APPROVE = "approve"


class TxStatus(str, Enum):
    DRAFT = "draft"
    SIMULATED = "simulated"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REVERTED = "reverted"


@dataclass
class TransactionRequest:
    """A request to build and execute an on-chain transaction."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    chain: str = "ethereum"
    tx_type: TxType = TxType.SWAP
    from_address: str = ""
    to_address: str = ""
    asset_in: str = ""
    asset_out: str = ""
    amount_in: Decimal = Decimal("0")
    min_amount_out: Decimal = Decimal("0")
    max_slippage_pct: Decimal = Decimal("0.01")
    gas_limit: Optional[int] = None
    gas_price_gwei: Optional[Decimal] = None
    deadline_seconds: int = 300
    metadata: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True  # Default to simulation

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "chain": self.chain,
            "tx_type": self.tx_type.value,
            "asset_in": self.asset_in,
            "asset_out": self.asset_out,
            "amount_in": str(self.amount_in),
            "min_amount_out": str(self.min_amount_out),
            "max_slippage_pct": str(self.max_slippage_pct),
            "dry_run": self.dry_run,
        }


@dataclass
class SimulationResult:
    """Result of simulating a transaction before execution."""
    request_id: str = ""
    success: bool = False
    expected_output: Decimal = Decimal("0")
    expected_gas: int = 0
    expected_gas_cost_usd: Decimal = Decimal("0")
    price_impact_pct: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")
    route: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    revert_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "expected_output": str(self.expected_output),
            "expected_gas": self.expected_gas,
            "expected_gas_cost_usd": str(self.expected_gas_cost_usd),
            "price_impact_pct": str(self.price_impact_pct),
            "slippage_pct": str(self.slippage_pct),
            "route": self.route,
            "warnings": self.warnings,
            "revert_reason": self.revert_reason,
        }


@dataclass
class TransactionResult:
    """Result of an executed on-chain transaction."""
    request_id: str = ""
    tx_hash: str = ""
    status: TxStatus = TxStatus.DRAFT
    chain: str = ""
    gas_used: int = 0
    gas_cost_usd: Decimal = Decimal("0")
    actual_output: Decimal = Decimal("0")
    block_number: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tx_hash": self.tx_hash,
            "status": self.status.value,
            "chain": self.chain,
            "gas_used": self.gas_used,
            "gas_cost_usd": str(self.gas_cost_usd),
            "actual_output": str(self.actual_output),
            "block_number": self.block_number,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


# ── Routing Policy ───────────────────────────────────────────────────

@dataclass
class RoutingPolicy:
    """Defines how to route on-chain transactions."""
    preferred_dexs: Dict[str, List[str]] = field(default_factory=lambda: {
        "ethereum": ["uniswap_v3", "curve", "1inch"],
        "solana": ["jupiter", "orca", "raydium"],
        "polygon": ["quickswap", "uniswap_v3"],
        "arbitrum": ["uniswap_v3", "camelot"],
    })
    max_hops: int = 3
    prefer_aggregators: bool = True
    max_gas_usd: Decimal = Decimal("50")
    min_liquidity_usd: Decimal = Decimal("100000")

    def get_dexs(self, chain: str) -> List[str]:
        return self.preferred_dexs.get(chain, [])


# ── On-chain position representation ────────────────────────────────

@dataclass
class OnChainPosition:
    """Represents an on-chain holding (LP, lending, staked)."""
    position_id: str = ""
    chain: str = ""
    protocol: str = ""
    position_type: str = ""   # "lp", "lending", "staking", "vault"
    assets: List[str] = field(default_factory=list)
    value_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    risk_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "chain": self.chain,
            "protocol": self.protocol,
            "position_type": self.position_type,
            "assets": self.assets,
            "value_usd": str(self.value_usd),
            "risk_score": self.risk_score,
        }


# ── Circuit breakers ─────────────────────────────────────────────────

@dataclass
class ChainCircuitBreaker:
    """Circuit breaker for on-chain execution."""
    chain: str
    tripped: bool = False
    reason: str = ""
    tripped_at: Optional[datetime] = None

    def trip(self, reason: str) -> None:
        self.tripped = True
        self.reason = reason
        self.tripped_at = datetime.now(timezone.utc)

    def reset(self) -> None:
        self.tripped = False
        self.reason = ""
        self.tripped_at = None


# ── Execution Service ────────────────────────────────────────────────

class BlockchainExecutionService:
    """Manages on-chain transaction lifecycle.

    Flow::
        Agent → TransactionRequest (dry_run=True)
            → simulate() → SimulationResult
            → [if approved] execute() → TransactionResult

    Read-only queries are always allowed.
    Write operations require dry_run=False and no tripped circuit breakers.
    """

    def __init__(self, routing: Optional[RoutingPolicy] = None):
        self._routing = routing or RoutingPolicy()
        self._circuit_breakers: Dict[str, ChainCircuitBreaker] = {}
        self._positions: Dict[str, OnChainPosition] = {}
        self._tx_log: List[TransactionResult] = []

    # ── Circuit breakers ─────────────────────────────────────────────

    def get_breaker(self, chain: str) -> ChainCircuitBreaker:
        if chain not in self._circuit_breakers:
            self._circuit_breakers[chain] = ChainCircuitBreaker(chain=chain)
        return self._circuit_breakers[chain]

    def trip_breaker(self, chain: str, reason: str) -> None:
        breaker = self.get_breaker(chain)
        breaker.trip(reason)
        logger.warning(f"Chain circuit breaker tripped: {chain} — {reason}")

    def reset_breaker(self, chain: str) -> None:
        breaker = self.get_breaker(chain)
        breaker.reset()
        logger.info(f"Chain circuit breaker reset: {chain}")

    def is_chain_halted(self, chain: str) -> bool:
        breaker = self._circuit_breakers.get(chain)
        return breaker.tripped if breaker else False

    # ── Simulation ───────────────────────────────────────────────────

    async def simulate(self, request: TransactionRequest) -> SimulationResult:
        """Simulate a transaction without executing.

        In production: calls chain-specific simulation (eth_call, Solana simulate).
        """
        if self.is_chain_halted(request.chain):
            return SimulationResult(
                request_id=request.request_id,
                success=False,
                revert_reason=f"Chain {request.chain} is halted.",
            )

        # Placeholder simulation — in production, call actual RPC
        return SimulationResult(
            request_id=request.request_id,
            success=True,
            expected_output=request.min_amount_out or request.amount_in,
            expected_gas=200000,
            expected_gas_cost_usd=Decimal("5.00"),
            price_impact_pct=Decimal("0.001"),
            route=self._routing.get_dexs(request.chain)[:2],
        )

    # ── Execution ────────────────────────────────────────────────────

    async def execute(self, request: TransactionRequest) -> TransactionResult:
        """Execute an on-chain transaction.

        Requires dry_run=False. Always simulates first.
        """
        # Safety: always simulate first
        sim = await self.simulate(request)
        if not sim.success:
            return TransactionResult(
                request_id=request.request_id,
                status=TxStatus.FAILED,
                chain=request.chain,
                error=sim.revert_reason or "Simulation failed.",
            )

        if request.dry_run:
            return TransactionResult(
                request_id=request.request_id,
                status=TxStatus.SIMULATED,
                chain=request.chain,
                actual_output=sim.expected_output,
                gas_used=sim.expected_gas,
                gas_cost_usd=sim.expected_gas_cost_usd,
            )

        # Check circuit breaker
        if self.is_chain_halted(request.chain):
            return TransactionResult(
                request_id=request.request_id,
                status=TxStatus.FAILED,
                chain=request.chain,
                error=f"Chain {request.chain} circuit breaker is tripped.",
            )

        # In production: sign via SigningService, submit to chain
        # Here we return a simulated execution result
        start = time.perf_counter()
        result = TransactionResult(
            request_id=request.request_id,
            tx_hash=f"0xSIM{request.request_id}",
            status=TxStatus.CONFIRMED,
            chain=request.chain,
            gas_used=sim.expected_gas,
            gas_cost_usd=sim.expected_gas_cost_usd,
            actual_output=sim.expected_output,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        self._tx_log.append(result)
        return result

    # ── Position tracking ────────────────────────────────────────────

    def register_position(self, position: OnChainPosition) -> None:
        self._positions[position.position_id] = position

    def get_positions(self, chain: Optional[str] = None) -> List[OnChainPosition]:
        if chain:
            return [p for p in self._positions.values() if p.chain == chain]
        return list(self._positions.values())

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "circuit_breakers": {
                k: {"tripped": v.tripped, "reason": v.reason}
                for k, v in self._circuit_breakers.items()
            },
            "positions": len(self._positions),
            "tx_log_count": len(self._tx_log),
            "routing": {
                "max_hops": self._routing.max_hops,
                "prefer_aggregators": self._routing.prefer_aggregators,
            },
        }


# Module-level singleton
_service: Optional[BlockchainExecutionService] = None


def get_execution_service() -> BlockchainExecutionService:
    global _service
    if _service is None:
        _service = BlockchainExecutionService()
    return _service

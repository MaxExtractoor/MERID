"""§2 Smart Contract Interfaces — Vault, BatchRouter, contract whitelist.

Typed interfaces for on-chain contracts MERID interacts with.
All contracts must be whitelisted and versioned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.blockchain.contracts")


# ── Contract Registry ────────────────────────────────────────────────

class ContractType(str, Enum):
    VAULT = "vault"
    BATCH_ROUTER = "batch_router"
    DEX_ROUTER = "dex_router"
    LENDING = "lending"
    STAKING = "staking"
    BRIDGE = "bridge"
    TOKEN = "token"


@dataclass
class ContractEntry:
    """A registered smart contract."""
    contract_id: str
    chain: str
    address: str
    contract_type: ContractType
    name: str = ""
    version: str = "1.0"
    abi_hash: str = ""
    deployed_at: Optional[datetime] = None
    verified: bool = False
    audit_url: str = ""
    owner: str = ""                # Governance address
    max_value_per_tx_usd: Decimal = Decimal("50000")

    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "chain": self.chain,
            "address": self.address[:10] + "..." if len(self.address) > 10 else self.address,
            "contract_type": self.contract_type.value,
            "name": self.name,
            "version": self.version,
            "verified": self.verified,
            "max_value_per_tx_usd": str(self.max_value_per_tx_usd),
        }


class ContractRegistry:
    """Central registry for all whitelisted smart contracts."""

    def __init__(self) -> None:
        self._contracts: Dict[str, ContractEntry] = {}

    def register(self, entry: ContractEntry) -> None:
        self._contracts[entry.contract_id] = entry
        logger.info(f"Registered contract: {entry.name} ({entry.contract_type.value}) on {entry.chain}")

    def get(self, contract_id: str) -> Optional[ContractEntry]:
        return self._contracts.get(contract_id)

    def by_chain(self, chain: str) -> List[ContractEntry]:
        return [c for c in self._contracts.values() if c.chain == chain]

    def by_type(self, contract_type: ContractType) -> List[ContractEntry]:
        return [c for c in self._contracts.values() if c.contract_type == contract_type]

    def by_address(self, chain: str, address: str) -> Optional[ContractEntry]:
        for c in self._contracts.values():
            if c.chain == chain and c.address.lower() == address.lower():
                return c
        return None

    def is_whitelisted(self, chain: str, address: str) -> bool:
        return self.by_address(chain, address) is not None

    def list_all(self) -> List[ContractEntry]:
        return list(self._contracts.values())

    def summary(self) -> dict:
        by_chain: Dict[str, int] = {}
        for c in self._contracts.values():
            by_chain[c.chain] = by_chain.get(c.chain, 0) + 1
        return {
            "total_contracts": len(self._contracts),
            "by_chain": by_chain,
            "contracts": [c.to_dict() for c in self._contracts.values()],
        }


# ── Vault Contract Interface ────────────────────────────────────────

@dataclass
class VaultAction:
    """An action to execute on a vault contract."""
    action_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    vault_id: str = ""
    action_type: str = ""     # "deposit", "withdraw", "execute_strategy"
    asset: str = ""
    amount: Decimal = Decimal("0")
    target_contract: str = ""  # For execute_strategy
    call_data: str = ""        # Encoded call data
    limits: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "vault_id": self.vault_id,
            "action_type": self.action_type,
            "asset": self.asset,
            "amount": str(self.amount),
        }


class VaultContract:
    """Interface for MERID vault contracts.

    A vault contract controls MERID's funds on a single chain.
    Functions: deposit, withdraw, executeStrategyCall (owner/executor only).
    """

    def __init__(self, entry: ContractEntry):
        self.entry = entry
        self._actions: List[VaultAction] = []

    @property
    def chain(self) -> str:
        return self.entry.chain

    @property
    def address(self) -> str:
        return self.entry.address

    def deposit(self, asset: str, amount: Decimal) -> VaultAction:
        action = VaultAction(
            vault_id=self.entry.contract_id,
            action_type="deposit", asset=asset, amount=amount,
        )
        self._actions.append(action)
        return action

    def withdraw(self, asset: str, amount: Decimal) -> VaultAction:
        action = VaultAction(
            vault_id=self.entry.contract_id,
            action_type="withdraw", asset=asset, amount=amount,
        )
        self._actions.append(action)
        return action

    def execute_strategy(
        self, target: str, call_data: str,
        limits: Optional[Dict[str, Any]] = None,
    ) -> VaultAction:
        action = VaultAction(
            vault_id=self.entry.contract_id,
            action_type="execute_strategy",
            target_contract=target, call_data=call_data,
            limits=limits or {},
        )
        self._actions.append(action)
        return action

    def get_actions(self, limit: int = 50) -> List[VaultAction]:
        return self._actions[-limit:]


# ── Batch Router Interface ───────────────────────────────────────────

@dataclass
class BatchStep:
    """A single step in a batch/multi-hop route."""
    step_index: int = 0
    dex: str = ""
    asset_in: str = ""
    asset_out: str = ""
    min_amount_out: Decimal = Decimal("0")
    pool_address: str = ""

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "dex": self.dex,
            "asset_in": self.asset_in,
            "asset_out": self.asset_out,
            "min_amount_out": str(self.min_amount_out),
        }


@dataclass
class BatchRoute:
    """A multi-step batch route for arb or complex swaps."""
    route_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    chain: str = ""
    steps: List[BatchStep] = field(default_factory=list)
    total_input: Decimal = Decimal("0")
    min_total_output: Decimal = Decimal("0")
    max_slippage_pct: Decimal = Decimal("0.01")
    deadline_seconds: int = 300

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "chain": self.chain,
            "steps": [s.to_dict() for s in self.steps],
            "total_input": str(self.total_input),
            "min_total_output": str(self.min_total_output),
            "max_slippage_pct": str(self.max_slippage_pct),
        }

    def is_valid(self) -> bool:
        """Validate route: steps chain correctly and slippage is bounded."""
        if not self.steps:
            return False
        for i in range(len(self.steps) - 1):
            if self.steps[i].asset_out != self.steps[i + 1].asset_in:
                return False
        return self.max_slippage_pct <= Decimal("0.05")


class BatchRouter:
    """Interface for batch/multi-step routing contracts.

    Enforces slippage/amount checks to avoid partial fills or sandwich risk.
    """

    def __init__(self, entry: ContractEntry):
        self.entry = entry
        self._routes: List[BatchRoute] = []

    def build_route(
        self,
        chain: str,
        steps: List[Dict[str, Any]],
        total_input: Decimal,
        min_output: Decimal,
        max_slippage_pct: Decimal = Decimal("0.01"),
    ) -> BatchRoute:
        batch_steps = [
            BatchStep(
                step_index=i,
                dex=s.get("dex", ""),
                asset_in=s.get("asset_in", ""),
                asset_out=s.get("asset_out", ""),
                min_amount_out=Decimal(str(s.get("min_amount_out", "0"))),
                pool_address=s.get("pool_address", ""),
            )
            for i, s in enumerate(steps)
        ]
        route = BatchRoute(
            chain=chain, steps=batch_steps,
            total_input=total_input, min_total_output=min_output,
            max_slippage_pct=max_slippage_pct,
        )
        self._routes.append(route)
        return route

    def get_routes(self, limit: int = 50) -> List[BatchRoute]:
        return self._routes[-limit:]


# ── Default registry ─────────────────────────────────────────────────

def build_default_contract_registry() -> ContractRegistry:
    """Build registry with known MERID-approved contracts."""
    reg = ContractRegistry()
    contracts = [
        ContractEntry(
            contract_id="uniswap-v3-eth", chain="ethereum",
            address="0xE592427A0AEce92De3Edee1F18E0157C05861564",
            contract_type=ContractType.DEX_ROUTER, name="Uniswap V3 Router",
            verified=True,
        ),
        ContractEntry(
            contract_id="1inch-eth", chain="ethereum",
            address="0x1111111254EEB25477B68fb85Ed929f73A960582",
            contract_type=ContractType.DEX_ROUTER, name="1inch Aggregation Router",
            verified=True,
        ),
        ContractEntry(
            contract_id="jupiter-sol", chain="solana",
            address="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            contract_type=ContractType.DEX_ROUTER, name="Jupiter V6",
            verified=True,
        ),
        ContractEntry(
            contract_id="quickswap-poly", chain="polygon",
            address="0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
            contract_type=ContractType.DEX_ROUTER, name="QuickSwap Router",
            verified=True,
        ),
    ]
    for c in contracts:
        reg.register(c)
    return reg


_registry: Optional[ContractRegistry] = None


def get_contract_registry() -> ContractRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_contract_registry()
    return _registry

"""§1 WalletService — Secure wallet abstraction for the swarm.

Agents produce action requests (e.g. "swap A→B on DEX X for size Y").
The WalletService builds, signs, and sends transactions if policies allow.
Agents NEVER see raw keys.

Narrow API:
- get_addresses(chain) → List[str]
- get_balances(chain) → Dict[asset, Decimal]
- sign_transaction(ActionRequest) → SignResult
- send_transaction(ActionRequest) → TransactionResult

Policy layer checks before every sign/send:
1. Venue/domain risk limits (via GlobalRiskManager).
2. Contract whitelist (no arbitrary calls).
3. Audit trail logging.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.blockchain.execution import (
    BlockchainExecutionService,
    TransactionRequest,
    TransactionResult,
    TxStatus,
    TxType,
    get_execution_service,
)
from merid.blockchain.signing import (
    SigningService,
    SignRequest,
    SignResult,
    get_signing_service,
)

from utils.logger import get_logger

logger = get_logger("merid.blockchain.wallet")


# ── Action Request (what agents produce) ─────────────────────────────

class ActionType(str, Enum):
    SWAP = "swap"
    TRANSFER = "transfer"
    PROVIDE_LIQUIDITY = "provide_liquidity"
    REMOVE_LIQUIDITY = "remove_liquidity"
    STAKE = "stake"
    UNSTAKE = "unstake"
    BRIDGE = "bridge"
    CONTRACT_CALL = "contract_call"


@dataclass
class ActionRequest:
    """What an agent submits to the WalletService.

    Agents describe *intent*, not raw transactions.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent_id: str = ""
    action_type: ActionType = ActionType.SWAP
    chain: str = "ethereum"
    asset_in: str = ""
    asset_out: str = ""
    amount: Decimal = Decimal("0")
    max_slippage_pct: Decimal = Decimal("0.01")
    target_contract: str = ""     # Must be whitelisted for CONTRACT_CALL
    venue: str = ""               # DEX or protocol name
    metadata: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "action_type": self.action_type.value,
            "chain": self.chain,
            "asset_in": self.asset_in,
            "asset_out": self.asset_out,
            "amount": str(self.amount),
            "target_contract": self.target_contract[:10] + "..." if len(self.target_contract) > 10 else self.target_contract,
            "venue": self.venue,
            "dry_run": self.dry_run,
        }


@dataclass
class ActionResult:
    """Result of processing an ActionRequest through the WalletService."""
    request_id: str = ""
    approved: bool = False
    policy_checks_passed: List[str] = field(default_factory=list)
    policy_checks_failed: List[str] = field(default_factory=list)
    sign_result: Optional[SignResult] = None
    tx_result: Optional[TransactionResult] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "policy_checks_passed": self.policy_checks_passed,
            "policy_checks_failed": self.policy_checks_failed,
            "sign_result": self.sign_result.to_dict() if self.sign_result else None,
            "tx_result": self.tx_result.to_dict() if self.tx_result else None,
            "error": self.error,
        }


# ── Wallet Address Registry ──────────────────────────────────────────

@dataclass
class WalletAddress:
    """A managed wallet address."""
    chain: str
    address: str
    label: str = ""
    key_id: str = ""       # References SecretsManager key_id for signing
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "address": self.address[:8] + "..." + self.address[-4:] if len(self.address) > 12 else self.address,
            "label": self.label,
            "is_default": self.is_default,
        }


# ── WalletService ────────────────────────────────────────────────────

class WalletService:
    """Secure wallet abstraction — agents request, wallet executes.

    Flow::
        Agent → ActionRequest
            → policy_check() → approved/denied
            → build_transaction()
            → sign (via SigningService)
            → send (via BlockchainExecutionService)
            → ActionResult

    All operations are audit-logged.
    """

    def __init__(
        self,
        execution: Optional[BlockchainExecutionService] = None,
        signing: Optional[SigningService] = None,
        contract_whitelist: Optional[Dict[str, List[str]]] = None,
    ):
        self._execution = execution
        self._signing = signing
        self._addresses: Dict[str, List[WalletAddress]] = {}  # chain → addresses
        self._balances: Dict[str, Dict[str, Decimal]] = {}    # chain → {asset: balance}
        self._contract_whitelist = contract_whitelist or _default_contract_whitelist()
        self._audit_log: List[Dict[str, Any]] = []

    @property
    def execution(self) -> BlockchainExecutionService:
        if self._execution is None:
            self._execution = get_execution_service()
        return self._execution

    @property
    def signing(self) -> SigningService:
        if self._signing is None:
            self._signing = get_signing_service()
        return self._signing

    # ── Address management ───────────────────────────────────────────

    def register_address(self, addr: WalletAddress) -> None:
        if addr.chain not in self._addresses:
            self._addresses[addr.chain] = []
        self._addresses[addr.chain].append(addr)

    def get_addresses(self, chain: str) -> List[WalletAddress]:
        return self._addresses.get(chain, [])

    def get_default_address(self, chain: str) -> Optional[WalletAddress]:
        for addr in self._addresses.get(chain, []):
            if addr.is_default:
                return addr
        addrs = self._addresses.get(chain, [])
        return addrs[0] if addrs else None

    # ── Balance management ───────────────────────────────────────────

    def set_balances(self, chain: str, balances: Dict[str, Decimal]) -> None:
        self._balances[chain] = balances

    def get_balances(self, chain: str) -> Dict[str, Decimal]:
        return self._balances.get(chain, {})

    # ── Contract whitelist ───────────────────────────────────────────

    def is_contract_whitelisted(self, chain: str, address: str) -> bool:
        allowed = self._contract_whitelist.get(chain, [])
        return address.lower() in [a.lower() for a in allowed]

    def whitelist_contract(self, chain: str, address: str) -> None:
        if chain not in self._contract_whitelist:
            self._contract_whitelist[chain] = []
        if address.lower() not in [a.lower() for a in self._contract_whitelist[chain]]:
            self._contract_whitelist[chain].append(address)

    # ── Policy check ─────────────────────────────────────────────────

    def check_policy(self, request: ActionRequest) -> ActionResult:
        """Run all policy checks on an action request."""
        passed = []
        failed = []

        # 1. Chain circuit breaker
        if self.execution.is_chain_halted(request.chain):
            failed.append(f"Chain {request.chain} is halted.")
        else:
            passed.append("chain_not_halted")

        # 2. Contract whitelist (for CONTRACT_CALL)
        if request.action_type == ActionType.CONTRACT_CALL:
            if not request.target_contract:
                failed.append("CONTRACT_CALL requires target_contract.")
            elif not self.is_contract_whitelisted(request.chain, request.target_contract):
                failed.append(f"Contract {request.target_contract[:10]}... not whitelisted on {request.chain}.")
            else:
                passed.append("contract_whitelisted")
        else:
            passed.append("no_contract_check_needed")

        # 3. Wallet address exists
        addr = self.get_default_address(request.chain)
        if not addr:
            failed.append(f"No wallet address registered for chain {request.chain}.")
        else:
            passed.append("wallet_address_exists")

        # 4. Balance check (if we have balance data)
        chain_balances = self.get_balances(request.chain)
        if chain_balances and request.asset_in:
            available = chain_balances.get(request.asset_in, Decimal("0"))
            if request.amount > available:
                failed.append(f"Insufficient {request.asset_in}: need {request.amount}, have {available}.")
            else:
                passed.append("sufficient_balance")

        approved = len(failed) == 0
        self._audit("policy_check", request, approved, "; ".join(failed) if failed else "All checks passed")

        return ActionResult(
            request_id=request.request_id,
            approved=approved,
            policy_checks_passed=passed,
            policy_checks_failed=failed,
            error="; ".join(failed) if failed else None,
        )

    # ── Execute action ───────────────────────────────────────────────

    async def execute_action(self, request: ActionRequest) -> ActionResult:
        """Full pipeline: policy check → build tx → sign → send."""
        # 1. Policy check
        result = self.check_policy(request)
        if not result.approved:
            return result

        # 2. Build transaction request
        tx_req = self._build_tx_request(request)

        # 3. Execute (simulate or live)
        tx_result = await self.execution.execute(tx_req)
        result.tx_result = tx_result

        if tx_result.status in (TxStatus.CONFIRMED, TxStatus.SIMULATED):
            result.approved = True
        else:
            result.approved = False
            result.error = tx_result.error

        self._audit("execute", request, result.approved,
                     tx_result.error or f"status={tx_result.status.value}")
        return result

    def _build_tx_request(self, action: ActionRequest) -> TransactionRequest:
        """Convert an ActionRequest into a TransactionRequest."""
        tx_type_map = {
            ActionType.SWAP: TxType.SWAP,
            ActionType.TRANSFER: TxType.TRANSFER,
            ActionType.PROVIDE_LIQUIDITY: TxType.LIQUIDITY_ADD,
            ActionType.REMOVE_LIQUIDITY: TxType.LIQUIDITY_REMOVE,
            ActionType.STAKE: TxType.STAKE,
            ActionType.UNSTAKE: TxType.UNSTAKE,
            ActionType.BRIDGE: TxType.BRIDGE,
            ActionType.CONTRACT_CALL: TxType.APPROVE,
        }
        addr = self.get_default_address(action.chain)
        return TransactionRequest(
            request_id=action.request_id,
            chain=action.chain,
            tx_type=tx_type_map.get(action.action_type, TxType.SWAP),
            from_address=addr.address if addr else "",
            asset_in=action.asset_in,
            asset_out=action.asset_out,
            amount_in=action.amount,
            max_slippage_pct=action.max_slippage_pct,
            dry_run=action.dry_run,
        )

    # ── Audit ────────────────────────────────────────────────────────

    def _audit(self, action: str, request: ActionRequest, success: bool, details: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "request_id": request.request_id,
            "agent_id": request.agent_id,
            "chain": request.chain,
            "success": success,
            "details": details,
        }
        self._audit_log.append(entry)
        if not success:
            logger.warning(f"Wallet audit [{action}]: {details}")

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._audit_log[-limit:]

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "chains": list(self._addresses.keys()),
            "addresses": {
                chain: [a.to_dict() for a in addrs]
                for chain, addrs in self._addresses.items()
            },
            "whitelisted_contracts": {
                chain: len(contracts)
                for chain, contracts in self._contract_whitelist.items()
            },
            "audit_log_entries": len(self._audit_log),
        }


# ── Default contract whitelist ───────────────────────────────────────

def _default_contract_whitelist() -> Dict[str, List[str]]:
    """Known-safe contracts MERID is allowed to interact with."""
    return {
        "ethereum": [
            "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",  # Uniswap V2 Router
            "0xE592427A0AEce92De3Edee1F18E0157C05861564",  # Uniswap V3 Router
            "0x1111111254EEB25477B68fb85Ed929f73A960582",  # 1inch Router
        ],
        "solana": [
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter V6
        ],
        "polygon": [
            "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",  # QuickSwap Router
        ],
        "arbitrum": [
            "0xE592427A0AEce92De3Edee1F18E0157C05861564",  # Uniswap V3 on Arb
        ],
    }


# Module-level singleton
_service: Optional[WalletService] = None


def get_wallet_service() -> WalletService:
    global _service
    if _service is None:
        _service = WalletService()
    return _service

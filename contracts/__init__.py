"""
Contracts - Formal system contracts per MERID Four-System Architecture

This module exports the contract enforcement layer:
- SystemContracts: Negative constraints (what systems can NEVER do)
- CapitalFirewall: Capital movement rules with cooldowns and quorums

Reference: MERID Four-System Architecture
"""

from contracts.system_contracts import (
    SystemID,
    SystemContract,
    ContractViolation,
    ContractViolationError,
    ViolationType,
    ContractEnforcer,
    SYSTEM_CONTRACTS,
    INTELLIGENCE_CONTRACT,
    TRADING_CONTRACT,
    TREASURY_CONTRACT,
    GOVERNANCE_CONTRACT,
    get_contract_enforcer,
    enforce_contract,
)

from contracts.capital_firewall import (
    CapitalFirewall,
    FirewallConfig,
    TransferRequest,
    TransferType,
    TransferStatus,
    get_capital_firewall,
)

from contracts.intents import (
    Intent,
    IntentType,
    IntentStatus,
    IntentPriority,
    IntentPayload,
    SimulationResult,
    IntentProcessor,
    INTENT_APPROVAL_THRESHOLDS,
    INTENT_REQUIRES_SIMULATION,
    get_intent_processor,
)

from contracts.vault_governance import (
    VaultGovernance,
    VaultConfig,
    VaultOperation,
    VaultOperationRequest,
    OperationStatus,
    KeyHolder,
    KeyRole,
    get_vault_governance,
)

__all__ = [
    "SystemID",
    "SystemContract",
    "ContractViolation",
    "ContractViolationError",
    "ViolationType",
    "ContractEnforcer",
    "SYSTEM_CONTRACTS",
    "INTELLIGENCE_CONTRACT",
    "TRADING_CONTRACT",
    "TREASURY_CONTRACT",
    "GOVERNANCE_CONTRACT",
    "get_contract_enforcer",
    "enforce_contract",
    "CapitalFirewall",
    "FirewallConfig",
    "TransferRequest",
    "TransferType",
    "TransferStatus",
    "get_capital_firewall",
    "Intent",
    "IntentType",
    "IntentStatus",
    "IntentPriority",
    "IntentPayload",
    "SimulationResult",
    "IntentProcessor",
    "INTENT_APPROVAL_THRESHOLDS",
    "INTENT_REQUIRES_SIMULATION",
    "get_intent_processor",
    "VaultGovernance",
    "VaultConfig",
    "VaultOperation",
    "VaultOperationRequest",
    "OperationStatus",
    "KeyHolder",
    "KeyRole",
    "get_vault_governance",
]

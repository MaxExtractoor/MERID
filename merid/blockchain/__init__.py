"""MERID Blockchain Integration — On-chain data, execution, and security.

§1 On-chain data: OnChainDataService with Helius/Graph/Nansen adapters
§2 Execution: BlockchainExecutionService with tx builder, routing, dry-run
§3 Security: SecretsManager, SigningService, key rotation, audit logging
"""

from merid.blockchain.onchain_data import (
    OnChainDataAdapter,
    OnChainDataService,
    ExchangeFlow,
    WhaleActivity,
    ProtocolHealth,
    OnChainMetrics,
    get_onchain_data_service,
)
from merid.blockchain.execution import (
    BlockchainExecutionService,
    TransactionRequest,
    TransactionResult,
    RoutingPolicy,
    get_execution_service,
)
from merid.blockchain.secrets import (
    SecretsManager,
    SecretEntry,
    KeyPermission,
    get_secrets_manager,
)
from merid.blockchain.signing import (
    SigningService,
    SignRequest,
    SignResult,
    get_signing_service,
)

__all__ = [
    "BlockchainExecutionService",
    "ExchangeFlow",
    "KeyPermission",
    "OnChainDataAdapter",
    "OnChainDataService",
    "OnChainMetrics",
    "ProtocolHealth",
    "RoutingPolicy",
    "SecretEntry",
    "SecretsManager",
    "SignRequest",
    "SignResult",
    "SigningService",
    "TransactionRequest",
    "TransactionResult",
    "WhaleActivity",
    "get_execution_service",
    "get_onchain_data_service",
    "get_secrets_manager",
    "get_signing_service",
]

"""Local stub implementations for MERID web3 integration tests."""

import importlib

try:  # Bridge to external web3 Web3 class if available
    _ext_web3 = importlib.import_module("web3.main")
    Web3 = getattr(_ext_web3, "Web3", None)  # type: ignore
except Exception:  # pragma: no cover
    Web3 = None  # type: ignore

from .blockchain_connector import BlockchainConnector, TransactionResult, ContractCall  # noqa: F401
from .defi_integration import DeFiIntegration  # noqa: F401
from .onchain_verifier import OnchainVerifier  # noqa: F401

"""§3 BlockchainGateway — RPC aggregator, caching, normalized responses.

Single testable surface for all blockchain connectivity.
Proxies RPC/REST calls to providers, normalizes responses,
adds caching and environment-based protections.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.blockchain.gateway")


# ── RPC Provider ─────────────────────────────────────────────────────

class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class RPCProvider:
    """An RPC endpoint provider."""
    name: str
    chain: str
    url: str
    priority: int = 0          # Lower = preferred
    rate_limit_rps: int = 50
    status: ProviderStatus = ProviderStatus.HEALTHY
    latency_ms: float = 0.0
    error_count: int = 0
    last_checked: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "chain": self.chain,
            "priority": self.priority,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "error_count": self.error_count,
        }


# ── Cached response ──────────────────────────────────────────────────

@dataclass
class CachedResponse:
    """A cached RPC response."""
    key: str
    data: Any
    cached_at: float = field(default_factory=time.time)
    ttl_seconds: int = 30

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.cached_at) > self.ttl_seconds


# ── Normalized chain data ────────────────────────────────────────────

@dataclass
class BlockInfo:
    """Normalized block information."""
    chain: str = ""
    block_number: int = 0
    block_hash: str = ""
    timestamp: int = 0
    transaction_count: int = 0

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "block_number": self.block_number,
            "block_hash": self.block_hash[:16] + "..." if len(self.block_hash) > 16 else self.block_hash,
            "timestamp": self.timestamp,
            "transaction_count": self.transaction_count,
        }


@dataclass
class TokenBalance:
    """Normalized token balance."""
    chain: str = ""
    address: str = ""
    asset: str = ""
    balance: Decimal = Decimal("0")
    decimals: int = 18

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "asset": self.asset,
            "balance": str(self.balance),
        }


@dataclass
class GasEstimate:
    """Normalized gas/fee estimate."""
    chain: str = ""
    base_fee_gwei: Decimal = Decimal("0")
    priority_fee_gwei: Decimal = Decimal("0")
    estimated_cost_usd: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "base_fee_gwei": str(self.base_fee_gwei),
            "priority_fee_gwei": str(self.priority_fee_gwei),
            "estimated_cost_usd": str(self.estimated_cost_usd),
        }


# ── BlockchainGateway ────────────────────────────────────────────────

class BlockchainGateway:
    """Unified gateway for all blockchain RPC connectivity.

    Features:
    - Multi-provider with automatic failover.
    - Response caching with configurable TTL.
    - Environment-based protections (block writes in dev).
    - Normalized response objects.
    """

    def __init__(
        self,
        environment: str = "dev",
        cache_ttl_seconds: int = 30,
        block_writes_in_dev: bool = True,
    ):
        self.environment = environment
        self.cache_ttl_seconds = cache_ttl_seconds
        self.block_writes_in_dev = block_writes_in_dev
        self._providers: Dict[str, List[RPCProvider]] = {}  # chain → providers
        self._cache: Dict[str, CachedResponse] = {}
        self._request_count: int = 0
        self._error_count: int = 0

    # ── Provider management ──────────────────────────────────────────

    def register_provider(self, provider: RPCProvider) -> None:
        if provider.chain not in self._providers:
            self._providers[provider.chain] = []
        self._providers[provider.chain].append(provider)
        self._providers[provider.chain].sort(key=lambda p: p.priority)
        logger.info(f"Registered RPC provider: {provider.name} for {provider.chain}")

    def get_provider(self, chain: str) -> Optional[RPCProvider]:
        """Get the best healthy provider for a chain."""
        providers = self._providers.get(chain, [])
        for p in providers:
            if p.status != ProviderStatus.DOWN:
                return p
        return None

    def list_providers(self, chain: Optional[str] = None) -> List[RPCProvider]:
        if chain:
            return self._providers.get(chain, [])
        return [p for providers in self._providers.values() for p in providers]

    def mark_provider_down(self, name: str) -> None:
        for providers in self._providers.values():
            for p in providers:
                if p.name == name:
                    p.status = ProviderStatus.DOWN
                    logger.warning(f"Provider marked down: {name}")

    def mark_provider_healthy(self, name: str) -> None:
        for providers in self._providers.values():
            for p in providers:
                if p.name == name:
                    p.status = ProviderStatus.HEALTHY

    # ── Cache ────────────────────────────────────────────────────────

    def _cache_get(self, key: str) -> Optional[Any]:
        cached = self._cache.get(key)
        if cached and not cached.is_expired:
            return cached.data
        if cached and cached.is_expired:
            del self._cache[key]
        return None

    def _cache_set(self, key: str, data: Any) -> None:
        self._cache[key] = CachedResponse(key=key, data=data, ttl_seconds=self.cache_ttl_seconds)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ── Read operations (always allowed) ─────────────────────────────

    async def get_block(self, chain: str) -> Optional[BlockInfo]:
        """Get latest block info for a chain."""
        cache_key = f"block:{chain}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        provider = self.get_provider(chain)
        if not provider:
            return None

        self._request_count += 1
        # In production: call provider.url with eth_blockNumber / getSlot
        block = BlockInfo(chain=chain, block_number=0)
        self._cache_set(cache_key, block)
        return block

    async def get_balance(self, chain: str, address: str, asset: str = "native") -> Optional[TokenBalance]:
        """Get token balance for an address."""
        cache_key = f"balance:{chain}:{address}:{asset}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        provider = self.get_provider(chain)
        if not provider:
            return None

        self._request_count += 1
        # In production: call provider.url with eth_getBalance / getBalance
        balance = TokenBalance(chain=chain, address=address, asset=asset)
        self._cache_set(cache_key, balance)
        return balance

    async def estimate_gas(self, chain: str) -> Optional[GasEstimate]:
        """Get current gas/fee estimate."""
        cache_key = f"gas:{chain}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        provider = self.get_provider(chain)
        if not provider:
            return None

        self._request_count += 1
        estimate = GasEstimate(chain=chain)
        self._cache_set(cache_key, estimate)
        return estimate

    # ── Write operations (blocked in dev if configured) ──────────────

    async def send_raw_transaction(self, chain: str, signed_tx: str) -> Optional[str]:
        """Send a signed transaction. Blocked in dev by default."""
        if self.block_writes_in_dev and self.environment == "dev":
            logger.warning(f"Write blocked in dev environment for chain {chain}")
            return None

        provider = self.get_provider(chain)
        if not provider:
            return None

        self._request_count += 1
        # In production: call provider.url with eth_sendRawTransaction
        return f"0xSIM_TX_{chain}"

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "environment": self.environment,
            "block_writes_in_dev": self.block_writes_in_dev,
            "providers": {
                chain: [p.to_dict() for p in providers]
                for chain, providers in self._providers.items()
            },
            "cache_entries": len(self._cache),
            "total_requests": self._request_count,
            "total_errors": self._error_count,
        }


# ── Default gateway ──────────────────────────────────────────────────

def _build_default_gateway() -> BlockchainGateway:
    gw = BlockchainGateway(environment="dev")
    default_providers = [
        RPCProvider(name="helius-sol", chain="solana", url="https://rpc.helius.xyz", priority=0, rate_limit_rps=50),
        RPCProvider(name="infura-eth", chain="ethereum", url="https://mainnet.infura.io/v3", priority=0, rate_limit_rps=25),
        RPCProvider(name="alchemy-eth", chain="ethereum", url="https://eth-mainnet.g.alchemy.com/v2", priority=1, rate_limit_rps=25),
        RPCProvider(name="infura-poly", chain="polygon", url="https://polygon-mainnet.infura.io/v3", priority=0, rate_limit_rps=25),
        RPCProvider(name="infura-arb", chain="arbitrum", url="https://arbitrum-mainnet.infura.io/v3", priority=0, rate_limit_rps=25),
    ]
    for p in default_providers:
        gw.register_provider(p)
    return gw


_gateway: Optional[BlockchainGateway] = None


def get_blockchain_gateway() -> BlockchainGateway:
    global _gateway
    if _gateway is None:
        _gateway = _build_default_gateway()
    return _gateway

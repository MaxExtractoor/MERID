"""§1 On-Chain Data Service — Normalized adapters for on-chain intelligence.

Adapters: Helius (Solana), The Graph (EVM subgraphs), Nansen (analytics).
Domain objects: ExchangeFlow, WhaleActivity, ProtocolHealth, OnChainMetrics.
Strategy hooks: strategies request on-chain metrics via get_metrics().
"""

from __future__ import annotations

import threading
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.blockchain.onchain_data")


# ── Domain objects ───────────────────────────────────────────────────

class FlowDirection(str, Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


@dataclass
class ExchangeFlow:
    """CEX/DEX exchange inflow or outflow event."""
    chain: str = ""
    exchange: str = ""
    asset: str = ""
    direction: FlowDirection = FlowDirection.INFLOW
    amount: Decimal = Decimal("0")
    usd_value: Decimal = Decimal("0")
    tx_hash: str = ""
    block_number: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "chain": self.chain, "exchange": self.exchange, "asset": self.asset,
            "direction": self.direction.value, "amount": str(self.amount),
            "usd_value": str(self.usd_value), "tx_hash": self.tx_hash,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class WhaleActivity:
    """Large address/entity activity event."""
    chain: str = ""
    address: str = ""
    label: str = ""           # "smart_money", "whale", "fund", "unknown"
    action: str = ""          # "accumulate", "distribute", "transfer"
    asset: str = ""
    amount: Decimal = Decimal("0")
    usd_value: Decimal = Decimal("0")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "chain": self.chain, "address": self.address[:10] + "...",
            "label": self.label, "action": self.action, "asset": self.asset,
            "amount": str(self.amount), "usd_value": str(self.usd_value),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ProtocolHealth:
    """DeFi protocol health snapshot."""
    protocol: str = ""
    chain: str = ""
    tvl_usd: Decimal = Decimal("0")
    tvl_change_24h_pct: Decimal = Decimal("0")
    borrow_utilization_pct: Decimal = Decimal("0")
    liquidations_24h_usd: Decimal = Decimal("0")
    governance_events: List[str] = field(default_factory=list)
    risk_score: float = 0.0   # 0 = safe, 1 = high risk
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol, "chain": self.chain,
            "tvl_usd": str(self.tvl_usd),
            "tvl_change_24h_pct": str(self.tvl_change_24h_pct),
            "borrow_utilization_pct": str(self.borrow_utilization_pct),
            "liquidations_24h_usd": str(self.liquidations_24h_usd),
            "governance_events": self.governance_events,
            "risk_score": self.risk_score,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StablecoinMetrics:
    """Stablecoin supply and flow metrics."""
    asset: str = ""           # USDT, USDC, DAI
    total_supply: Decimal = Decimal("0")
    supply_change_24h: Decimal = Decimal("0")
    chain_distribution: Dict[str, Decimal] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "asset": self.asset, "total_supply": str(self.total_supply),
            "supply_change_24h": str(self.supply_change_24h),
            "chain_distribution": {k: str(v) for k, v in self.chain_distribution.items()},
        }


@dataclass
class OnChainMetrics:
    """Aggregated on-chain metrics for strategy consumption."""
    exchange_flows: List[ExchangeFlow] = field(default_factory=list)
    whale_activity: List[WhaleActivity] = field(default_factory=list)
    protocol_health: List[ProtocolHealth] = field(default_factory=list)
    stablecoin_metrics: List[StablecoinMetrics] = field(default_factory=list)
    net_exchange_flow_usd: Decimal = Decimal("0")  # positive = inflow (bearish)
    whale_accumulation_score: float = 0.0           # -1 to 1 (negative = distributing)
    defi_risk_score: float = 0.0                    # 0 to 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "net_exchange_flow_usd": str(self.net_exchange_flow_usd),
            "whale_accumulation_score": self.whale_accumulation_score,
            "defi_risk_score": self.defi_risk_score,
            "exchange_flows_count": len(self.exchange_flows),
            "whale_events_count": len(self.whale_activity),
            "protocols_tracked": len(self.protocol_health),
            "timestamp": self.timestamp.isoformat(),
        }

    def bias_signal(self) -> str:
        """Derive a directional bias from on-chain metrics.

        Returns 'bullish', 'bearish', or 'neutral'.
        """
        score = 0.0
        # Large net inflows to exchanges → bearish (selling pressure)
        if self.net_exchange_flow_usd > Decimal("1000000"):
            score -= 0.3
        elif self.net_exchange_flow_usd < Decimal("-1000000"):
            score += 0.3
        # Whale accumulation → bullish
        score += self.whale_accumulation_score * 0.4
        # High DeFi risk → bearish
        score -= self.defi_risk_score * 0.3

        if score > 0.15:
            return "bullish"
        elif score < -0.15:
            return "bearish"
        return "neutral"


# ── Adapter ABC ──────────────────────────────────────────────────────

class OnChainDataAdapter(ABC):
    """Abstract adapter for on-chain data providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (e.g. 'helius', 'the_graph', 'nansen')."""

    @property
    @abstractmethod
    def supported_chains(self) -> List[str]:
        """Chains this adapter supports."""

    @abstractmethod
    async def get_exchange_flows(self, asset: str, hours: int = 24) -> List[ExchangeFlow]:
        """Get exchange inflow/outflow events."""

    @abstractmethod
    async def get_whale_activity(self, asset: str, min_usd: float = 100000) -> List[WhaleActivity]:
        """Get whale/smart money activity."""

    @abstractmethod
    async def get_protocol_health(self, protocol: str) -> Optional[ProtocolHealth]:
        """Get DeFi protocol health snapshot."""

    async def health_check(self) -> Dict[str, Any]:
        return {"provider": self.provider_name, "status": "ok", "chains": self.supported_chains}


# ── Helius Adapter (Solana) ──────────────────────────────────────────

class HeliusAdapter(OnChainDataAdapter):
    """Helius API adapter for Solana on-chain data."""

    provider_name = "helius"
    supported_chains = ["solana"]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("HELIUS_API_KEY", "")
        self.base_url = "https://api.helius.xyz/v0"

    async def get_exchange_flows(self, asset: str, hours: int = 24) -> List[ExchangeFlow]:
        """Fetch Solana exchange flows via Helius enhanced transactions API."""
        # Production: call self.base_url/addresses/{addr}/transactions
        return []

    async def get_whale_activity(self, asset: str, min_usd: float = 100000) -> List[WhaleActivity]:
        """Fetch large Solana transfers via Helius."""
        return []

    async def get_protocol_health(self, protocol: str) -> Optional[ProtocolHealth]:
        """Fetch Solana DeFi protocol metrics."""
        return None


# ── The Graph Adapter (EVM) ──────────────────────────────────────────

class TheGraphAdapter(OnChainDataAdapter):
    """The Graph subgraph adapter for EVM on-chain data."""

    provider_name = "the_graph"
    supported_chains = ["ethereum", "polygon", "arbitrum"]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("THE_GRAPH_API_KEY", "")
        self.gateway_url = "https://gateway.thegraph.com/api"

    async def get_exchange_flows(self, asset: str, hours: int = 24) -> List[ExchangeFlow]:
        """Query Uniswap/Aave subgraphs for exchange flows."""
        return []

    async def get_whale_activity(self, asset: str, min_usd: float = 100000) -> List[WhaleActivity]:
        """Query token transfer subgraphs for whale activity."""
        return []

    async def get_protocol_health(self, protocol: str) -> Optional[ProtocolHealth]:
        """Query protocol-specific subgraphs (Aave, Compound, etc.)."""
        return None


# ── Nansen Adapter ───────────────────────────────────────────────────

class NansenAdapter(OnChainDataAdapter):
    """Nansen API adapter for cross-chain analytics."""

    provider_name = "nansen"
    supported_chains = ["ethereum", "solana", "polygon", "arbitrum", "bsc"]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NANSEN_API_KEY", "")
        self.base_url = "https://api.nansen.ai/v1"

    async def get_exchange_flows(self, asset: str, hours: int = 24) -> List[ExchangeFlow]:
        """Fetch exchange flow data from Nansen."""
        return []

    async def get_whale_activity(self, asset: str, min_usd: float = 100000) -> List[WhaleActivity]:
        """Fetch smart money / whale labels from Nansen."""
        return []

    async def get_protocol_health(self, protocol: str) -> Optional[ProtocolHealth]:
        """Fetch protocol analytics from Nansen."""
        return None


# ── OnChainDataService ───────────────────────────────────────────────

class OnChainDataService:
    """Aggregates on-chain data from all adapters into normalized metrics.

    Usage::

        svc = OnChainDataService()
        svc.register_adapter(HeliusAdapter())
        svc.register_adapter(TheGraphAdapter())
        metrics = await svc.get_metrics("BTC")
        bias = metrics.bias_signal()  # "bullish" / "bearish" / "neutral"
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, OnChainDataAdapter] = {}

    def register_adapter(self, adapter: OnChainDataAdapter) -> None:
        self._adapters[adapter.provider_name] = adapter
        logger.info(f"Registered on-chain adapter: {adapter.provider_name}")

    def get_adapter(self, name: str) -> Optional[OnChainDataAdapter]:
        return self._adapters.get(name)

    def list_adapters(self) -> List[str]:
        return list(self._adapters.keys())

    async def get_exchange_flows(self, asset: str, hours: int = 24) -> List[ExchangeFlow]:
        """Aggregate exchange flows from all adapters."""
        all_flows: List[ExchangeFlow] = []
        for adapter in self._adapters.values():
            try:
                flows = await adapter.get_exchange_flows(asset, hours)
                all_flows.extend(flows)
            except Exception as exc:
                logger.error(f"Exchange flow fetch failed ({adapter.provider_name}): {exc}")
        return all_flows

    async def get_whale_activity(self, asset: str, min_usd: float = 100000) -> List[WhaleActivity]:
        """Aggregate whale activity from all adapters."""
        all_activity: List[WhaleActivity] = []
        for adapter in self._adapters.values():
            try:
                activity = await adapter.get_whale_activity(asset, min_usd)
                all_activity.extend(activity)
            except Exception as exc:
                logger.error(f"Whale activity fetch failed ({adapter.provider_name}): {exc}")
        return all_activity

    async def get_protocol_health(self, protocol: str) -> List[ProtocolHealth]:
        """Get protocol health from all adapters that support it."""
        results: List[ProtocolHealth] = []
        for adapter in self._adapters.values():
            try:
                health = await adapter.get_protocol_health(protocol)
                if health:
                    results.append(health)
            except Exception as exc:
                logger.error(f"Protocol health fetch failed ({adapter.provider_name}): {exc}")
        return results

    async def get_metrics(self, asset: str = "BTC", hours: int = 24) -> OnChainMetrics:
        """Build aggregated on-chain metrics for strategy consumption."""
        flows = await self.get_exchange_flows(asset, hours)
        whales = await self.get_whale_activity(asset)

        # Compute net exchange flow
        net_flow = Decimal("0")
        for f in flows:
            if f.direction == FlowDirection.INFLOW:
                net_flow += f.usd_value
            else:
                net_flow -= f.usd_value

        # Compute whale accumulation score
        acc_score = 0.0
        if whales:
            acc = sum(1 for w in whales if w.action == "accumulate")
            dist = sum(1 for w in whales if w.action == "distribute")
            total = acc + dist
            if total > 0:
                acc_score = (acc - dist) / total

        return OnChainMetrics(
            exchange_flows=flows,
            whale_activity=whales,
            net_exchange_flow_usd=net_flow,
            whale_accumulation_score=acc_score,
        )

    def summary(self) -> dict:
        return {
            "adapters": [
                {"provider": a.provider_name, "chains": a.supported_chains}
                for a in self._adapters.values()
            ],
        }


# Module-level singleton
_service: Optional[OnChainDataService] = None
_service_lock = threading.Lock()


def get_onchain_data_service() -> OnChainDataService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = OnChainDataService()
    return _service

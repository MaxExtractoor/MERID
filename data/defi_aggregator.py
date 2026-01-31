"""
Multi-chain DeFi data aggregation service.

Abstracts per-chain fetchers (placeholder) and normalizes TVL, yield, and risk
metrics for downstream consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
import logging


logger = logging.getLogger(__name__)


@dataclass
class DeFiProtocolSnapshot:
    chain: str
    protocol: str
    tvl_usd: float
    apy: float
    risk_score: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RouteOption:
    """DeFi route option for swaps/yields."""
    protocol: str
    chain: str
    estimated_output: float
    gas_cost_usd: float
    net_output: float
    apy: float
    risk_score: float
    route_steps: List[str] = field(default_factory=list)


class DeFiAggregator:
    def __init__(self) -> None:
        self._snapshots: List[DeFiProtocolSnapshot] = []
        self._protocol_cache: Dict[str, DeFiProtocolSnapshot] = {}

    def record_snapshot(self, chain: str, protocol: str, tvl_usd: float, apy: float, risk_score: float) -> DeFiProtocolSnapshot:
        snapshot = DeFiProtocolSnapshot(chain=chain, protocol=protocol, tvl_usd=tvl_usd, apy=apy, risk_score=risk_score)
        self._snapshots.append(snapshot)
        self._protocol_cache[f"{chain}:{protocol}"] = snapshot
        logger.debug("Recorded DeFi snapshot %s/%s TVL %.2f", chain, protocol, tvl_usd)
        return snapshot

    def get_latest(self, limit: int = 50) -> List[DeFiProtocolSnapshot]:
        return list(self._snapshots[-limit:])
    
    def find_best_yield(
        self,
        asset: str,
        amount_usd: float,
        max_risk_score: float = 0.5,
        min_tvl_usd: float = 1_000_000,
    ) -> List[RouteOption]:
        """Find best yield opportunities across protocols."""
        candidates = []
        
        for key, snapshot in self._protocol_cache.items():
            if snapshot.risk_score > max_risk_score:
                continue
            if snapshot.tvl_usd < min_tvl_usd:
                continue
            
            estimated_output = amount_usd * (1 + snapshot.apy / 100)
            gas_cost = self._estimate_gas_cost(snapshot.chain)
            net_output = estimated_output - gas_cost
            
            route = RouteOption(
                protocol=snapshot.protocol,
                chain=snapshot.chain,
                estimated_output=estimated_output,
                gas_cost_usd=gas_cost,
                net_output=net_output,
                apy=snapshot.apy,
                risk_score=snapshot.risk_score,
                route_steps=[f"Deposit {asset} to {snapshot.protocol}"],
            )
            candidates.append(route)
        
        candidates.sort(key=lambda r: r.net_output, reverse=True)
        return candidates[:10]
    
    def optimize_route(
        self,
        from_asset: str,
        to_asset: str,
        amount: float,
        max_hops: int = 3,
    ) -> List[RouteOption]:
        """Optimize swap route across multiple protocols."""
        routes = []
        
        for key, snapshot in self._protocol_cache.items():
            if snapshot.tvl_usd < 100_000:
                continue
            
            slippage = self._estimate_slippage(amount, snapshot.tvl_usd)
            gas_cost = self._estimate_gas_cost(snapshot.chain)
            
            estimated_output = amount * (1 - slippage / 100)
            net_output = estimated_output - gas_cost
            
            route = RouteOption(
                protocol=snapshot.protocol,
                chain=snapshot.chain,
                estimated_output=estimated_output,
                gas_cost_usd=gas_cost,
                net_output=net_output,
                apy=0.0,
                risk_score=snapshot.risk_score,
                route_steps=[f"Swap {from_asset} → {to_asset} via {snapshot.protocol}"],
            )
            routes.append(route)
        
        routes.sort(key=lambda r: r.net_output, reverse=True)
        return routes[:5]
    
    def compare_protocols(
        self,
        asset: str,
        protocols: List[str],
    ) -> Dict[str, DeFiProtocolSnapshot]:
        """Compare specific protocols for an asset."""
        comparison = {}
        
        for protocol in protocols:
            for key, snapshot in self._protocol_cache.items():
                if snapshot.protocol == protocol:
                    comparison[protocol] = snapshot
                    break
        
        return comparison
    
    def get_protocol_stats(self, protocol: str) -> Dict[str, float]:
        """Get aggregated stats for a protocol across chains."""
        total_tvl = 0.0
        avg_apy = 0.0
        avg_risk = 0.0
        count = 0
        
        for key, snapshot in self._protocol_cache.items():
            if snapshot.protocol == protocol:
                total_tvl += snapshot.tvl_usd
                avg_apy += snapshot.apy
                avg_risk += snapshot.risk_score
                count += 1
        
        if count == 0:
            return {"total_tvl": 0.0, "avg_apy": 0.0, "avg_risk": 0.0}
        
        return {
            "total_tvl": total_tvl,
            "avg_apy": avg_apy / count,
            "avg_risk": avg_risk / count,
            "chain_count": count,
        }
    
    def _estimate_gas_cost(self, chain: str) -> float:
        """Estimate gas cost in USD for chain."""
        gas_costs = {
            "ethereum": 50.0,
            "arbitrum": 2.0,
            "optimism": 2.0,
            "polygon": 0.5,
            "bsc": 0.3,
            "avalanche": 1.0,
            "base": 1.5,
        }
        return gas_costs.get(chain.lower(), 5.0)
    
    def _estimate_slippage(self, amount_usd: float, tvl_usd: float) -> float:
        """Estimate slippage percentage based on trade size vs TVL."""
        if tvl_usd == 0:
            return 10.0
        
        trade_ratio = amount_usd / tvl_usd
        
        if trade_ratio < 0.001:
            return 0.1
        elif trade_ratio < 0.01:
            return 0.5
        elif trade_ratio < 0.05:
            return 1.0
        else:
            return min(5.0, trade_ratio * 100)

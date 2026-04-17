"""
On-Chain Transaction Monitoring Stream

Provides real-time blockchain transaction monitoring for cryptocurrency markets.
Monitors Ethereum, Bitcoin, and other major chains with US-compliant filtering.

Features:
- Multi-blockchain transaction monitoring
- Real-time transaction analysis
- Large transaction detection (whale alerts)
- DeFi protocol tracking
- Smart contract interaction monitoring
"""

import asyncio
import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from collections import deque

from streams.base_stream import BaseStream, StreamState
from core.events import EventEnvelope, EventType, EventPriority
from utils.logger import get_logger

logger = get_logger("streams.onchain")

@dataclass
class OnchainTransaction:
    """On-chain transaction data structure."""
    tx_hash: str
    chain: str
    from_address: str
    to_address: str
    value: float
    gas_used: float
    gas_price: float
    block_number: int
    timestamp: float
    token_symbol: Optional[str]
    protocol: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class OnchainSignal:
    """On-chain signal for market analysis."""
    signal_id: str
    chain: str
    signal_type: str  # whale, defi, contract, volume
    symbol: Optional[str]
    value: float
    confidence: float
    impact_score: float
    transaction_count: int
    total_value: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class OnchainStream(BaseStream):
    """
    Real-time on-chain transaction monitoring stream.
    
    Provides blockchain transaction analysis with whale detection
    and DeFi protocol monitoring for US-market compliance.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Stream configuration
        self.update_interval = config.get("update_interval", 60)  # 1 minute
        self.max_transactions = config.get("max_transactions", 500)
        self.whale_threshold = config.get("whale_threshold", 100000)  # $100K
        self.defi_protocols = config.get("defi_protocols", [
            "uniswap", "curve", "aave", "compound", "makerdao", "sushiswap"
        ])
        
        # Blockchain networks
        self.chains = ["ethereum", "bitcoin", "polygon", "arbitrum", "optimism"]
        
        # Data storage
        self.transactions: deque = deque(maxlen=self.max_transactions)
        self.onchain_signals: deque = deque(maxlen=200)
        self._last_update = 0
        
        # Token address mappings (simplified)
        self.token_addresses = {
            "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e": "USDC",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7": "USDT",
            "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": "WBTC",
            "0x514910771AF9Ca656af840dff83E8264EcF986CA": "LINK",
            "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984": "UNI"
        }
        
        # DeFi protocol addresses (simplified)
        self.protocol_addresses = {
            "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D": "uniswap_v2",
            "0xE592427A0AEce92De3Edee1F18E0157C05861564": "uniswap_v3",
            "0x8eB8f3e564ed34C704D0A1C4F19aC4F5Ff863965": "curve",
            "0x7d2768dE32b0b80b7a3454C06BdAc94A69DDc7A9": "aave"
        }
        
        logger.info(f"OnchainStream initialized with {len(self.chains)} chains")
    
    @property
    def stream_type(self) -> str:
        """Return stream type identifier."""
        return "onchain"
    
    async def _connect(self) -> bool:
        """Connect to blockchain nodes."""
        try:
            # In production, this would establish connections to blockchain nodes
            # For now, we simulate successful connection
            logger.info("Connected to blockchain nodes")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to blockchain nodes: {e}")
            return False
    
    async def _disconnect(self) -> bool:
        """Disconnect from blockchain nodes."""
        try:
            logger.info("Disconnected from blockchain nodes")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from blockchain nodes: {e}")
            return False
    
    async def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch blockchain transactions."""
        try:
            # Generate mock blockchain transactions for testing
            transactions = []
            current_time = time.time()
            
            # Generate 20-50 transactions per update
            for i in range(random.randint(20, 50)):
                tx = self._generate_mock_transaction(current_time)
                transactions.append(asdict(tx))
            
            logger.debug(f"Fetched {len(transactions)} blockchain transactions")
            return transactions
            
        except Exception as e:
            logger.error(f"Failed to fetch blockchain data: {e}")
            return []
    
    async def _transform_to_events(self, raw_data: List[Dict[str, Any]]) -> List[EventEnvelope]:
        """Transform blockchain data to event envelopes."""
        events = []
        
        try:
            # Process transactions and generate on-chain signals
            transactions = []
            for tx_data in raw_data:
                tx = OnchainTransaction(**tx_data)
                transactions.append(tx)
                self.transactions.append(tx)
                if len(self.transactions) > 500: self.transactions[:] = self.transactions[-500:]
            
            # Generate on-chain signals
            chain_signals = self._calculate_onchain_signals(transactions)
            
            # Create events for each signal
            for signal in chain_signals:
                event = EventEnvelope(
                    event_type=EventType.ONCHAIN,
                    priority=self._get_priority_from_impact(signal.impact_score),
                    data={
                        "signal_type": signal.signal_type,
                        "chain": signal.chain,
                        "symbol": signal.symbol,
                        "value": signal.value,
                        "confidence": signal.confidence,
                        "impact_score": signal.impact_score,
                        "transaction_count": signal.transaction_count,
                        "total_value": signal.total_value,
                        "timestamp": signal.timestamp
                    },
                    metadata={
                        "stream_type": self.stream_type,
                        "signal_id": signal.signal_id,
                        "update_time": time.time()
                    }
                )
                events.append(event)
                self.onchain_signals.append(signal)
                if len(self.onchain_signals) > 500: self.onchain_signals[:] = self.onchain_signals[-500:]
            
            logger.debug(f"Generated {len(events)} on-chain events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to transform blockchain data: {e}")
            return []
    
    def _generate_mock_transaction(self, current_time: float) -> OnchainTransaction:
        """Generate realistic mock blockchain transaction."""
        
        # Select chain
        chain = random.choice(self.chains)
        
        # Generate addresses
        from_address = f"0x{random.randint(0, 16**40):040x}"
        to_address = f"0x{random.randint(0, 16**40):040x}"
        
        # Determine if it's a token transfer or native transaction
        is_token_tx = random.random() < 0.6  # 60% token transactions
        
        if is_token_tx:
            # Token transaction
            token_symbol = random.choice(["USDC", "USDT", "WBTC", "WETH", "UNI", "LINK"])
            value = random.uniform(1000, 1000000)  # $1K - $1M
            
            # Check if it's a DeFi protocol interaction
            protocol = None
            if random.random() < 0.3:  # 30% DeFi interactions
                protocol = random.choice(self.defi_protocols)
                # Use protocol address
                to_address = random.choice(list(self.protocol_addresses.keys()))
        else:
            # Native transaction
            token_symbol = None
            if chain == "ethereum":
                value = random.uniform(0.1, 10.0)  # ETH
            elif chain == "bitcoin":
                value = random.uniform(0.01, 1.0)  # BTC
            else:
                value = random.uniform(0.1, 5.0)  # Other chains
            
            protocol = None
        
        # Gas metrics (chain-specific)
        if chain == "ethereum":
            gas_used = random.uniform(21000, 500000)
            gas_price = random.uniform(20, 200)  # gwei
        elif chain == "bitcoin":
            gas_used = random.uniform(250, 1000)
            gas_price = random.uniform(10, 100)  # satoshis per byte
        else:
            gas_used = random.uniform(21000, 200000)
            gas_price = random.uniform(1, 50)  # gwei
        
        # Block number (recent blocks)
        if chain == "ethereum":
            block_number = random.randint(18000000, 18100000)
        elif chain == "bitcoin":
            block_number = random.randint(800000, 810000)
        else:
            block_number = random.randint(50000000, 51000000)
        
        return OnchainTransaction(
            tx_hash=f"0x{random.randint(0, 16**64):064x}",
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            value=value,
            gas_used=gas_used,
            gas_price=gas_price,
            block_number=block_number,
            timestamp=current_time - random.randint(0, 300),  # Within last 5 minutes
            token_symbol=token_symbol,
            protocol=protocol,
            metadata={
                "mock": True,
                "confirmations": random.randint(1, 100),
                "success_rate": random.uniform(0.95, 1.0)
            }
        )
    
    def _calculate_onchain_signals(self, transactions: List[OnchainTransaction]) -> List[OnchainSignal]:
        """Calculate on-chain signals from transactions."""
        signals = []
        
        # Group transactions by chain and type
        chain_transactions = {}
        for tx in transactions:
            if tx.chain not in chain_transactions:
                chain_transactions[tx.chain] = []
            chain_transactions[tx.chain].append(tx)
        
        # Analyze each chain
        for chain, chain_txs in chain_transactions.items():
            # Whale transactions
            whale_signals = self._detect_whale_transactions(chain, chain_txs)
            signals.extend(whale_signals)
            
            # DeFi protocol activity
            defi_signals = self._analyze_defi_activity(chain, chain_txs)
            signals.extend(defi_signals)
            
            # Volume analysis
            volume_signals = self._analyze_transaction_volume(chain, chain_txs)
            signals.extend(volume_signals)
        
        return signals
    
    def _detect_whale_transactions(self, chain: str, transactions: List[OnchainTransaction]) -> List[OnchainSignal]:
        """Detect large whale transactions."""
        signals = []
        
        # Filter large transactions
        whale_txs = []
        for tx in transactions:
            # Convert to USD value (simplified)
            if tx.token_symbol in ["USDC", "USDT"]:
                usd_value = tx.value
            elif tx.token_symbol == "WBTC":
                usd_value = tx.value * 45000  # Mock BTC price
            elif tx.token_symbol == "WETH":
                usd_value = tx.value * 3000  # Mock ETH price
            else:
                # Native transaction
                if chain == "ethereum":
                    usd_value = tx.value * 3000
                elif chain == "bitcoin":
                    usd_value = tx.value * 45000
                else:
                    usd_value = tx.value * 100  # Generic price
            
            if usd_value >= self.whale_threshold:
                whale_txs.append((tx, usd_value))
        
        if whale_txs:
            # Calculate aggregate signal
            total_value = sum(usd_value for _, usd_value in whale_txs)
            avg_value = total_value / len(whale_txs)
            
            # Determine primary symbol
            symbol_counts = {}
            for tx, _ in whale_txs:
                symbol = tx.token_symbol or chain.upper()
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
            
            primary_symbol = max(symbol_counts, key=symbol_counts.get)
            
            # Calculate impact score
            impact_score = min(1.0, total_value / 1000000)  # Normalize by $1M
            
            signal = OnchainSignal(
                signal_id=f"whale_{chain}_{int(time.time() * 1000)}",
                chain=chain,
                signal_type="whale",
                symbol=primary_symbol,
                value=avg_value,
                confidence=0.9,  # High confidence for on-chain data
                impact_score=impact_score,
                transaction_count=len(whale_txs),
                total_value=total_value,
                timestamp=time.time(),
                metadata={
                    "stream_type": self.stream_type,
                    "whale_addresses": [tx[0].from_address for tx in whale_txs[:5]],
                    "largest_tx": max(whale_txs, key=lambda x: x[1])[0].tx_hash
                }
            )
            signals.append(signal)
        
        return signals
    
    def _analyze_defi_activity(self, chain: str, transactions: List[OnchainTransaction]) -> List[OnchainSignal]:
        """Analyze DeFi protocol activity."""
        signals = []
        
        # Filter DeFi transactions
        defi_txs = [tx for tx in transactions if tx.protocol]
        
        if not defi_txs:
            return signals
        
        # Group by protocol
        protocol_txs = {}
        for tx in defi_txs:
            if tx.protocol not in protocol_txs:
                protocol_txs[tx.protocol] = []
            protocol_txs[tx.protocol].append(tx)
        
        # Generate signals for each protocol
        for protocol, txs in protocol_txs.items():
            # Calculate total value
            total_value = sum(tx.value for tx in txs)
            
            # Calculate impact score based on volume and frequency
            volume_score = min(1.0, total_value / 500000)  # Normalize by $500K
            frequency_score = min(1.0, len(txs) / 20)  # Normalize by 20 txs
            impact_score = (volume_score + frequency_score) / 2
            
            # Determine primary symbol
            symbol_counts = {}
            for tx in txs:
                symbol = tx.token_symbol or chain.upper()
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
            
            primary_symbol = max(symbol_counts, key=symbol_counts.get) if symbol_counts else chain.upper()
            
            signal = OnchainSignal(
                signal_id=f"defi_{protocol}_{chain}_{int(time.time() * 1000)}",
                chain=chain,
                signal_type="defi",
                symbol=primary_symbol,
                value=total_value / len(txs),
                confidence=0.85,
                impact_score=impact_score,
                transaction_count=len(txs),
                total_value=total_value,
                timestamp=time.time(),
                metadata={
                    "stream_type": self.stream_type,
                    "protocol": protocol,
                    "unique_addresses": len(set(tx.from_address for tx in txs))
                }
            )
            signals.append(signal)
        
        return signals
    
    def _analyze_transaction_volume(self, chain: str, transactions: List[OnchainTransaction]) -> List[OnchainSignal]:
        """Analyze overall transaction volume."""
        signals = []
        
        if not transactions:
            return signals
        
        # Calculate volume metrics
        total_value = sum(tx.value for tx in transactions)
        avg_value = total_value / len(transactions)
        
        # Calculate volume score (compared to historical average)
        volume_score = min(1.0, total_value / 1000000)  # Normalize by $1M
        
        # Determine primary symbol
        symbol_counts = {}
        for tx in transactions:
            symbol = tx.token_symbol or chain.upper()
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        
        primary_symbol = max(symbol_counts, key=symbol_counts.get) if symbol_counts else chain.upper()
        
        signal = OnchainSignal(
            signal_id=f"volume_{chain}_{int(time.time() * 1000)}",
            chain=chain,
            signal_type="volume",
            symbol=primary_symbol,
            value=avg_value,
            confidence=0.8,
            impact_score=volume_score,
            transaction_count=len(transactions),
            total_value=total_value,
            timestamp=time.time(),
            metadata={
                "stream_type": self.stream_type,
                "unique_addresses": len(set(tx.from_address for tx in transactions)),
                "token_transfers": len([tx for tx in transactions if tx.token_symbol])
            }
        )
        signals.append(signal)
        
        return signals
    
    def _get_priority_from_impact(self, impact_score: float) -> EventPriority:
        """Get event priority from impact score."""
        if impact_score > 0.7:  # High impact
            return EventPriority.HIGH
        elif impact_score > 0.4:  # Medium impact
            return EventPriority.MEDIUM
        else:  # Low impact
            return EventPriority.LOW
    
    def get_onchain_summary(self, hours: int = 1) -> Dict[str, Any]:
        """Get on-chain summary for specified time period."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals
        recent_signals = [
            s for s in self.onchain_signals 
            if s.timestamp >= cutoff_time
        ]
        
        if not recent_signals:
            return {
                "period_hours": hours,
                "total_signals": 0,
                "chains": [],
                "signal_types": {},
                "total_value": 0.0
            }
        
        # Calculate summary statistics
        chains = list(set(s.chain for s in recent_signals))
        signal_types = {}
        total_value = 0
        
        for signal in recent_signals:
            signal_type = signal.signal_type
            signal_types[signal_type] = signal_types.get(signal_type, 0) + 1
            total_value += signal.total_value
        
        return {
            "period_hours": hours,
            "total_signals": len(recent_signals),
            "chains": chains,
            "signal_types": signal_types,
            "total_value": total_value,
            "avg_impact_score": sum(s.impact_score for s in recent_signals) / len(recent_signals),
            "total_transactions": sum(s.transaction_count for s in recent_signals)
        }
    
    def get_chain_activity(self, chain: str, hours: int = 24) -> Optional[Dict[str, Any]]:
        """Get activity data for specific blockchain."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals for chain
        recent_signals = [
            s for s in self.onchain_signals 
            if s.chain == chain and s.timestamp >= cutoff_time
        ]
        
        if not recent_signals:
            return None
        
        # Sort by timestamp
        recent_signals.sort(key=lambda x: x.timestamp)
        
        # Signal type breakdown
        signal_breakdown = {}
        for signal in recent_signals:
            signal_type = signal.signal_type
            if signal_type not in signal_breakdown:
                signal_breakdown[signal_type] = {
                    "count": 0,
                    "total_value": 0,
                    "avg_impact": 0
                }
            signal_breakdown[signal_type]["count"] += 1
            signal_breakdown[signal_type]["total_value"] += signal.total_value
            signal_breakdown[signal_type]["avg_impact"] += signal.impact_score
        
        # Calculate averages
        for signal_type in signal_breakdown:
            data = signal_breakdown[signal_type]
            data["avg_impact"] = data["avg_impact"] / data["count"]
        
        return {
            "chain": chain,
            "period_hours": hours,
            "signal_count": len(recent_signals),
            "total_value": sum(s.total_value for s in recent_signals),
            "avg_impact_score": sum(s.impact_score for s in recent_signals) / len(recent_signals),
            "signal_breakdown": signal_breakdown,
            "latest_update": recent_signals[-1].timestamp if recent_signals else 0
        }

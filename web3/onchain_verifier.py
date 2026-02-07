"""
On-Chain Data Verification System

Provides comprehensive on-chain data verification and validation
with US-compliant configuration and security checks.

Features:
- Transaction verification and validation
- Smart contract verification
- Price oracle verification
- Cross-chain data consistency
- US regulatory compliance checks
"""

import asyncio
import time
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import json

from web3.blockchain_connector import BlockchainConnector, TransactionResult
from utils.logger import get_logger

logger = get_logger("web3.onchain_verifier")

@dataclass
class VerificationResult:
    """Verification result data structure."""
    verification_id: str
    data_type: str  # transaction, contract, price, balance
    chain: str
    address: Optional[str]
    data_hash: str
    is_valid: bool
    confidence_score: float
    verification_time: float
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PriceVerification:
    """Price verification data structure."""
    token_pair: str
    chain: str
    price_onchain: float
    price_oracle: float
    deviation_percent: float
    is_valid: bool
    confidence_score: float
    timestamp: float
    sources: List[str] = field(default_factory=list)

@dataclass
class ContractVerification:
    """Smart contract verification data structure."""
    contract_address: str
    chain: str
    is_verified: bool
    source_code_available: bool
    audit_status: str
    security_score: float
    risk_level: str
    verification_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class OnchainVerifier:
    """
    Comprehensive on-chain data verification system.
    
    Provides transaction, contract, and price verification with
    US-compliant security checks and risk assessment.
    """
    
    def __init__(self, blockchain_connector: BlockchainConnector, config: Dict[str, Any]):
        self.blockchain_connector = blockchain_connector
        self.config = config
        
        # Verification settings
        self.verification_config = config.get("verification", {
            "confidence_threshold": 0.8,
            "price_deviation_threshold": 5.0,  # 5%
            "require_contract_verification": True,
            "security_check_enabled": True,
            "cross_chain_verification": True
        })
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "require_verified_contracts": True,
            "blacklisted_contracts": [],
            "suspicious_patterns": ["honeypot", "rug_pull"],
            "min_security_score": 0.7
        })
        
        # Known verified contracts (mock data)
        self.verified_contracts = {
            "ethereum": {
                "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e": "USDC",
                "0xdAC17F958D2ee523a2206206994597C13D831ec7": "USDT",
                "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": "WBTC",
                "0x514910771AF9Ca656af840dff83E8264EcF986CA": "LINK",
                "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984": "UNI"
            },
            "polygon": {
                "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174": "USDC",
                "0xc2132D05D31c914a87C6611C10748AEb04B58e8F": "USDT",
                "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6": "WBTC"
            }
        }
        
        # Security risk patterns (mock)
        self.risk_patterns = {
            "high_risk": ["honeypot", "rug_pull", "unlimited_mint"],
            "medium_risk": ["centralized", "upgradeable", "admin_keys"],
            "low_risk": ["standard_erc20", "verified", "audited"]
        }
        
        # Data storage
        self.verification_history: deque = deque(maxlen=1000)
        self.price_verifications: deque = deque(maxlen=500)
        self.contract_verifications: Dict[str, ContractVerification] = {}
        
        # Performance metrics
        self.verification_counts: Dict[str, int] = {}
        self.verification_times: Dict[str, List[float]] = {}
        
        logger.info("OnchainVerifier initialized")
    
    async def verify_transaction(self, chain: str, tx_hash: str) -> Optional[VerificationResult]:
        """Verify a transaction on-chain."""
        try:
            start_time = time.time()
            
            # Get transaction data
            tx_data = await self._get_transaction_data(chain, tx_hash)
            if not tx_data:
                return None
            
            # Calculate data hash
            data_hash = self._calculate_data_hash(tx_data)
            
            # Perform verification checks
            verification_checks = await self._perform_transaction_verification(chain, tx_data)
            
            # Calculate confidence score
            confidence = self._calculate_confidence_score(verification_checks)
            
            # Determine validity
            is_valid = confidence >= self.verification_config["confidence_threshold"]
            
            verification_time = time.time() - start_time
            
            result = VerificationResult(
                verification_id=f"tx_{chain}_{tx_hash[:10]}",
                data_type="transaction",
                chain=chain,
                address=tx_data.get("from"),
                data_hash=data_hash,
                is_valid=is_valid,
                confidence_score=confidence,
                verification_time=verification_time,
                metadata={
                    "tx_hash": tx_hash,
                    "checks": verification_checks,
                    "block_number": tx_data.get("block_number")
                }
            )
            
            self.verification_history.append(result)
            self._update_verification_metrics("transaction", verification_time)
            
            logger.info(f"Transaction verification completed: {tx_hash[:10]}... (confidence: {confidence:.2f})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to verify transaction {tx_hash}: {e}")
            return None
    
    async def verify_contract(self, chain: str, contract_address: str) -> Optional[ContractVerification]:
        """Verify a smart contract."""
        try:
            start_time = time.time()
            
            # Check if contract is already verified
            if contract_address in self.contract_verifications:
                cached = self.contract_verifications[contract_address]
                if time.time() - cached.verification_time < 3600:  # 1 hour cache
                    return cached
            
            # Get contract data
            contract_data = await self._get_contract_data(chain, contract_address)
            if not contract_data:
                return None
            
            # Perform verification checks
            verification_checks = await self._perform_contract_verification(chain, contract_address, contract_data)
            
            # Calculate security score
            security_score = self._calculate_security_score(verification_checks)
            
            # Determine risk level
            risk_level = self._determine_risk_level(security_score, verification_checks)
            
            # Check US compliance
            is_us_compliant = self._check_contract_us_compliance(contract_address, verification_checks)
            
            verification_time = time.time() - start_time
            
            result = ContractVerification(
                contract_address=contract_address,
                chain=chain,
                is_verified=verification_checks.get("source_verified", False),
                source_code_available=verification_checks.get("source_available", False),
                audit_status=verification_checks.get("audit_status", "unaudited"),
                security_score=security_score,
                risk_level=risk_level,
                verification_time=verification_time,
                metadata={
                    "checks": verification_checks,
                    "is_us_compliant": is_us_compliant,
                    "contract_type": verification_checks.get("contract_type", "unknown")
                }
            )
            
            self.contract_verifications[contract_address] = result
            self._update_verification_metrics("contract", verification_time)
            
            logger.info(f"Contract verification completed: {contract_address[:10]}... (security: {security_score:.2f})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to verify contract {contract_address}: {e}")
            return None
    
    async def verify_price(self, token_pair: str, chain: str, onchain_price: float, 
                         oracle_prices: Dict[str, float]) -> Optional[PriceVerification]:
        """Verify price data against multiple sources."""
        try:
            start_time = time.time()
            
            # Calculate price deviations
            deviations = {}
            for source, price in oracle_prices.items():
                deviation = abs(onchain_price - price) / price * 100
                deviations[source] = deviation
            
            # Calculate average deviation
            avg_deviation = sum(deviations.values()) / len(deviations) if deviations else 0
            
            # Determine validity
            is_valid = avg_deviation <= self.verification_config["price_deviation_threshold"]
            
            # Calculate confidence score
            confidence = max(0, 1 - (avg_deviation / 10))  # Linear decay
            
            verification_time = time.time() - start_time
            
            result = PriceVerification(
                token_pair=token_pair,
                chain=chain,
                price_onchain=onchain_price,
                price_oracle=sum(oracle_prices.values()) / len(oracle_prices) if oracle_prices else onchain_price,
                deviation_percent=avg_deviation,
                is_valid=is_valid,
                confidence_score=confidence,
                timestamp=time.time(),
                sources=list(oracle_prices.keys())
            )
            
            self.price_verifications.append(result)
            self._update_verification_metrics("price", verification_time)
            
            logger.info(f"Price verification completed: {token_pair} (deviation: {avg_deviation:.2f}%)")
            return result
            
        except Exception as e:
            logger.error(f"Failed to verify price {token_pair}: {e}")
            return None
    
    async def verify_cross_chain_data(self, token_address: str, chains: List[str]) -> Optional[Dict[str, Any]]:
        """Verify data consistency across multiple chains."""
        if not self.verification_config["cross_chain_verification"]:
            return None
        
        try:
            start_time = time.time()
            
            # Get data from all chains
            chain_data = {}
            for chain in chains:
                if chain not in self.blockchain_connector.chains:
                    continue
                
                # Get balance on this chain
                balance_data = await self.blockchain_connector.get_balance(chain, token_address)
                if balance_data:
                    chain_data[chain] = balance_data["balance"]
            
            # Calculate consistency metrics
            if len(chain_data) < 2:
                return None
            
            # Check for anomalies
            balances = list(chain_data.values())
            avg_balance = sum(balances) / len(balances)
            
            anomalies = []
            for chain, balance in chain_data.items():
                deviation = abs(balance - avg_balance) / avg_balance if avg_balance > 0 else 0
                if deviation > 0.5:  # 50% deviation threshold
                    anomalies.append({
                        "chain": chain,
                        "balance": balance,
                        "deviation": deviation
                    })
            
            verification_time = time.time() - start_time
            
            result = {
                "token_address": token_address,
                "chains_checked": chains,
                "chain_data": chain_data,
                "avg_balance": avg_balance,
                "anomalies": anomalies,
                "is_consistent": len(anomalies) == 0,
                "verification_time": verification_time,
                "timestamp": time.time()
            }
            
            logger.info(f"Cross-chain verification completed: {token_address[:10]}... ({len(chains)} chains)")
            return result
            
        except Exception as e:
            logger.error(f"Failed cross-chain verification for {token_address}: {e}")
            return None
    
    async def _get_transaction_data(self, chain: str, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get transaction data from blockchain."""
        # Mock transaction data
        from_addr = f"0x{hash(tx_hash) % (16**40):040x}"
        to_addr = f"0x{hash(tx_hash + 'to') % (16**40):040x}"
        
        return {
            "hash": tx_hash,
            "from": from_addr,
            "to": to_addr,
            "value": hash(tx_hash) % 1000000000000000000,
            "gas": 21000 + hash(tx_hash) % 100000,
            "gas_price": 20 + hash(tx_hash) % 50,
            "block_number": 18000000 + hash(tx_hash) % 1000,
            "status": 1
        }
    
    async def _get_contract_data(self, chain: str, contract_address: str) -> Optional[Dict[str, Any]]:
        """Get contract data from blockchain."""
        # Check if contract is in verified list
        is_verified = contract_address in self.verified_contracts.get(chain, {})
        
        return {
            "address": contract_address,
            "source_verified": is_verified,
            "source_available": is_verified,
            "audit_status": "audited" if is_verified else "unaudited",
            "contract_type": "ERC20" if is_verified else "unknown",
            "creation_block": 15000000 + hash(contract_address) % 1000000
        }
    
    async def _perform_transaction_verification(self, chain: str, tx_data: Dict[str, Any]) -> Dict[str, bool]:
        """Perform transaction verification checks."""
        checks = {}
        
        # Basic structure check
        checks["valid_structure"] = all(key in tx_data for key in ["from", "to", "value", "gas"])
        
        # Address format check
        checks["valid_addresses"] = (
            tx_data["from"].startswith("0x") and len(tx_data["from"]) == 42 and
            tx_data["to"].startswith("0x") and len(tx_data["to"]) == 42
        )
        
        # Value range check
        checks["valid_value"] = 0 <= tx_data["value"] <= 100000000000000000000  # Max 100 ETH
        
        # Gas check
        checks["valid_gas"] = 21000 <= tx_data["gas"] <= 1000000
        
        # Status check
        checks["valid_status"] = tx_data.get("status", 0) == 1
        
        return checks
    
    async def _perform_contract_verification(self, chain: str, contract_address: str, 
                                            contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform contract verification checks."""
        checks = {}
        
        # Source verification
        checks["source_verified"] = contract_data.get("source_verified", False)
        
        # Source availability
        checks["source_available"] = contract_data.get("source_available", False)
        
        # Audit status
        checks["audited"] = contract_data.get("audit_status") == "audited"
        
        # Known contract check
        checks["known_contract"] = contract_address in self.verified_contracts.get(chain, {})
        
        # Security patterns
        checks["has_security_issues"] = False  # Mock check
        
        return checks
    
    def _calculate_data_hash(self, data: Dict[str, Any]) -> str:
        """Calculate hash of data for verification."""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def _calculate_confidence_score(self, checks: Dict[str, bool]) -> float:
        """Calculate confidence score from verification checks."""
        if not checks:
            return 0.0
        
        passed_checks = sum(1 for check in checks.values() if check)
        total_checks = len(checks)
        
        return passed_checks / total_checks
    
    def _calculate_security_score(self, checks: Dict[str, Any]) -> float:
        """Calculate security score for contract."""
        score = 0.0
        
        # Source verification
        if checks.get("source_verified", False):
            score += 0.3
        
        # Audit status
        if checks.get("audited", False):
            score += 0.3
        
        # Known contract
        if checks.get("known_contract", False):
            score += 0.2
        
        # No security issues
        if not checks.get("has_security_issues", True):
            score += 0.2
        
        return min(1.0, score)
    
    def _determine_risk_level(self, security_score: float, checks: Dict[str, Any]) -> str:
        """Determine risk level based on security score and checks."""
        if security_score >= 0.8:
            return "low"
        elif security_score >= 0.6:
            return "medium"
        else:
            return "high"
    
    def _check_contract_us_compliance(self, contract_address: str, checks: Dict[str, Any]) -> bool:
        """Check if contract complies with US regulations."""
        # Check blacklist
        blacklist = self.us_compliance.get("blacklisted_contracts", [])
        if contract_address.lower() in [addr.lower() for addr in blacklist]:
            return False
        
        # Require verification
        if self.us_compliance.get("require_verified_contracts", True):
            if not checks.get("source_verified", False):
                return False
        
        return True
    
    def _update_verification_metrics(self, verification_type: str, verification_time: float):
        """Update verification performance metrics."""
        self.verification_counts[verification_type] = self.verification_counts.get(verification_type, 0) + 1
        
        if verification_type not in self.verification_times:
            self.verification_times[verification_type] = []
        
        self.verification_times[verification_type].append(verification_time)
        
        # Keep only last 100 measurements
        if len(self.verification_times[verification_type]) > 100:
            self.verification_times[verification_type] = self.verification_times[verification_type][-100:]
    
    def get_verification_summary(self) -> Dict[str, Any]:
        """Get summary of verification activities."""
        total_verifications = sum(self.verification_counts.values())
        
        avg_times = {}
        for vtype, times in self.verification_times.items():
            if times:
                avg_times[vtype] = sum(times) / len(times)
        
        return {
            "total_verifications": total_verifications,
            "verification_counts": self.verification_counts,
            "average_verification_times": avg_times,
            "contract_verifications": len(self.contract_verifications),
            "price_verifications": len(self.price_verifications),
            "verification_history_size": len(self.verification_history),
            "us_compliance": self.us_compliance,
            "verification_config": self.verification_config
        }
    
    def get_contract_verification_status(self, contract_address: str) -> Optional[ContractVerification]:
        """Get verification status for a specific contract."""
        return self.contract_verifications.get(contract_address)
    
    def is_contract_safe(self, contract_address: str) -> bool:
        """Check if a contract is considered safe for interaction."""
        verification = self.contract_verifications.get(contract_address)
        if not verification:
            return False
        
        # Check security score
        if verification.security_score < self.us_compliance.get("min_security_score", 0.7):
            return False
        
        # Check risk level
        if verification.risk_level == "high":
            return False
        
        return True

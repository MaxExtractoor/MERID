"""
Onchain Assertion Source

Provides onchain domain assertions to reduce blind spots in the reality system.
"""

import threading
import time
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
    RealityAssertion,
    AssertionStatus
)
from utils.logger import get_logger

logger = get_logger("onchain.assertion_source")


@dataclass
class OnchainAssertion:
    """Onchain data assertion for reality system."""
    chain_id: str
    block_number: int
    block_hash: str
    timestamp: float
    source: str
    confidence: float = 0.9


class OnchainAssertionSource:
    """
    Onchain data assertion source for reality system.
    
    Periodically registers onchain state assertions to reduce blind spots
    in the onchain domain.
    """
    
    def __init__(self):
        self.registry = get_reality_registry()
        self.last_assertion_time = 0.0
        self.assertion_interval = 120.0  # 2 minutes
        self.onchain_state_cache: Dict[str, OnchainAssertion] = {}
    
    def update_onchain_state(self, chain_id: str, block_number: int, block_hash: str, source: str = "rpc"):
        """Update onchain state and register assertion if needed."""
        current_time = time.time()
        
        # Cache the onchain state
        self.onchain_state_cache[chain_id] = OnchainAssertion(
            chain_id=chain_id,
            block_number=block_number,
            block_hash=block_hash,
            timestamp=current_time,
            source=source,
            confidence=0.9
        )
        
        # Register assertion if interval has passed
        if current_time - self.last_assertion_time >= self.assertion_interval:
            self._register_onchain_assertion(chain_id)
            self.last_assertion_time = current_time
    
    def _register_onchain_assertion(self, chain_id: str):
        """Register an onchain state assertion."""
        try:
            onchain_data = self.onchain_state_cache.get(chain_id)
            if not onchain_data:
                logger.warning(f"No onchain data available for {chain_id}")
                return
            
            # Create assertion
            assertion_id = self.registry.register_assertion(
                domain=AssertionDomain.ONCHAIN,
                description=f"Onchain state for {chain_id}: block {onchain_data.block_number}, hash {onchain_data.block_hash[:10]}...",
                confidence=onchain_data.confidence,
                provenance_score=0.8,
                regime_compatibility=1.0,
                decay_rate=0.03,  # Onchain data decays moderately
                validity_window=600.0,  # 10 minutes
                sources=[
                    AssertionProvenance(
                        source_id="onchain_feed",
                        module_id="onchain_assertion_source",
                        evidence_hash=f"onchain_{chain_id}_{onchain_data.timestamp}",
                        weight=1.0,
                        timestamp=onchain_data.timestamp
                    )
                ]
            )
            
            logger.info(f"Registered onchain assertion: {chain_id} - {assertion_id}")
            
        except Exception as e:
            logger.error(f"Error registering onchain assertion for {chain_id}: {e}")
    
    def register_batch_onchain_data(self, onchain_data_list: List[Dict]):
        """Register multiple onchain data assertions at once."""
        for onchain_data in onchain_data_list:
            chain_id = onchain_data.get("chain_id")
            block_number = onchain_data.get("block_number")
            block_hash = onchain_data.get("block_hash")
            source = onchain_data.get("source", "batch")
            
            if chain_id and block_number and block_hash:
                # Cache the onchain data
                current_time = time.time()
                self.onchain_state_cache[chain_id] = OnchainAssertion(
                    chain_id=chain_id,
                    block_number=block_number,
                    block_hash=block_hash,
                    timestamp=current_time,
                    source=source,
                    confidence=0.8
                )
                
                # Register assertion immediately for demo data (bypass interval check)
                if source == "demo":
                    self._register_onchain_assertion(chain_id)
                else:
                    self.update_onchain_state(chain_id, block_number, block_hash, source)
    
    def get_onchain_assertions(self) -> List[Dict]:
        """Get all onchain assertions from the registry."""
        try:
            assertions = self.registry.get_assertions_by_domain(AssertionDomain.ONCHAIN)
            
            # Get auditor for regime_entropy
            from core.reality_auditor import get_reality_auditor
            auditor = get_reality_auditor()
            current_time = time.time()
            
            return [
                {
                    "assertion_id": a.assertion_id,
                    "chain_id": a.description.split(":")[0].strip(),
                    "description": a.description,
                    "confidence_score": a.confidence_score,
                    "provenance_score": a.provenance_score,
                    "status": a.status.value,
                    "created_at": a.created_at,
                    "effective_confidence": a.effective_confidence(current_time, auditor.regime_entropy),
                    "is_usable": a.is_usable(current_time, auditor.regime_entropy)
                }
                for a in assertions
            ]
        except Exception as e:
            logger.error(f"Error getting onchain assertions: {e}")
            return []


# Singleton instance
_onchain_source: Optional[OnchainAssertionSource] = None
_onchain_source_lock = threading.Lock()


def get_onchain_assertion_source() -> OnchainAssertionSource:
    """Get the global onchain assertion source."""
    global _onchain_source
    if _onchain_source is None:
        with _onchain_source_lock:
            if _onchain_source is None:
                _onchain_source = OnchainAssertionSource()
    return _onchain_source


# Example usage
if __name__ == "__main__":
    # Create onchain assertion source
    source = get_onchain_assertion_source()
    
    # Update some onchain data
    source.update_onchain_state("ethereum", 18500000, "0x1234...", "rpc")
    source.update_onchain_state("polygon", 45000000, "0x5678...", "rpc")
    source.update_onchain_state("arbitrum", "12345678", "0x9abc...", "bootstrap")
    
    # Get onchain assertions
    assertions = source.get_onchain_assertions()
    print(f"Onchain assertions: {len(assertions)}")
    for assertion in assertions[:3]:  # Show first 3
        print(f"  - {assertion['chain_id']}: {assertion['status']} (confidence: {assertion['confidence_score']:.2f})")
    
    print("Onchain assertion source is ready!")

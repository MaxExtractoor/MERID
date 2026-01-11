"""
MERID Archive - Hash Chain Implementation

Provides cryptographic hash chain for tamper-proof audit trails.
Supports verification, merkle proofs, and chain export.

Part of MERID-ARCHIVE (Layer 7 - Memory & Forensics)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("archive.hashchain")


@dataclass
class Block:
    """A block in the hash chain."""
    index: int
    timestamp: float
    data: Dict[str, Any]
    previous_hash: str
    nonce: int = 0
    hash: str = ""
    
    def compute_hash(self) -> str:
        """Compute SHA-256 hash of block."""
        content = {
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        content_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Block':
        block = cls(
            index=data["index"],
            timestamp=data["timestamp"],
            data=data["data"],
            previous_hash=data["previous_hash"],
            nonce=data.get("nonce", 0),
        )
        block.hash = data.get("hash", block.compute_hash())
        return block


class HashChain:
    """
    Cryptographic hash chain for tamper-proof storage.
    
    Features:
    - Append-only chain
    - SHA-256 hashing
    - Integrity verification
    - Merkle root computation
    - Chain export/import
    """
    
    GENESIS_HASH = "0" * 64
    
    def __init__(self):
        self._chain: List[Block] = []
        self._create_genesis_block()
        
        logger.info("Hash chain initialized")
    
    def _create_genesis_block(self) -> None:
        """Create the genesis block."""
        genesis = Block(
            index=0,
            timestamp=time.time(),
            data={"type": "genesis", "message": "MERID Hash Chain Genesis"},
            previous_hash=self.GENESIS_HASH,
        )
        genesis.hash = genesis.compute_hash()
        self._chain.append(genesis)
    
    def add_block(self, data: Dict[str, Any]) -> Block:
        """Add a new block to the chain."""
        previous_block = self._chain[-1]
        
        new_block = Block(
            index=len(self._chain),
            timestamp=time.time(),
            data=data,
            previous_hash=previous_block.hash,
        )
        new_block.hash = new_block.compute_hash()
        
        self._chain.append(new_block)
        
        logger.debug(
            "Added block %d: hash=%s",
            new_block.index, new_block.hash[:16]
        )
        
        return new_block
    
    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """
        Verify the entire chain integrity.
        
        Returns (is_valid, first_invalid_index).
        """
        for i in range(1, len(self._chain)):
            current = self._chain[i]
            previous = self._chain[i - 1]
            
            # Verify current block hash
            if current.hash != current.compute_hash():
                logger.error("Block %d hash mismatch", i)
                return False, i
            
            # Verify chain link
            if current.previous_hash != previous.hash:
                logger.error("Block %d chain link broken", i)
                return False, i
        
        logger.info("Chain verified: %d blocks valid", len(self._chain))
        return True, None
    
    def verify_block(self, index: int) -> bool:
        """Verify a specific block."""
        if index < 0 or index >= len(self._chain):
            return False
        
        block = self._chain[index]
        return block.hash == block.compute_hash()
    
    def get_merkle_root(self) -> str:
        """Compute Merkle root of all block hashes."""
        if not self._chain:
            return self.GENESIS_HASH
        
        hashes = [block.hash for block in self._chain]
        
        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])  # Duplicate last if odd
            
            new_hashes = []
            for i in range(0, len(hashes), 2):
                combined = hashes[i] + hashes[i + 1]
                new_hash = hashlib.sha256(combined.encode()).hexdigest()
                new_hashes.append(new_hash)
            
            hashes = new_hashes
        
        return hashes[0]
    
    def get_merkle_proof(self, index: int) -> List[Tuple[str, str]]:
        """
        Get Merkle proof for a block.
        
        Returns list of (hash, position) tuples for verification.
        """
        if index < 0 or index >= len(self._chain):
            return []
        
        hashes = [block.hash for block in self._chain]
        proof = []
        
        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])
            
            if index % 2 == 0:
                if index + 1 < len(hashes):
                    proof.append((hashes[index + 1], "right"))
            else:
                proof.append((hashes[index - 1], "left"))
            
            new_hashes = []
            for i in range(0, len(hashes), 2):
                combined = hashes[i] + hashes[i + 1]
                new_hash = hashlib.sha256(combined.encode()).hexdigest()
                new_hashes.append(new_hash)
            
            hashes = new_hashes
            index = index // 2
        
        return proof
    
    def verify_merkle_proof(
        self,
        block_hash: str,
        proof: List[Tuple[str, str]],
        merkle_root: str,
    ) -> bool:
        """Verify a Merkle proof."""
        current_hash = block_hash
        
        for sibling_hash, position in proof:
            if position == "left":
                combined = sibling_hash + current_hash
            else:
                combined = current_hash + sibling_hash
            
            current_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        return current_hash == merkle_root
    
    def get_block(self, index: int) -> Optional[Block]:
        """Get block by index."""
        if 0 <= index < len(self._chain):
            return self._chain[index]
        return None
    
    def get_latest_block(self) -> Block:
        """Get the latest block."""
        return self._chain[-1]
    
    def get_chain_length(self) -> int:
        """Get chain length."""
        return len(self._chain)
    
    def export_chain(self) -> List[Dict[str, Any]]:
        """Export chain as list of dicts."""
        return [block.to_dict() for block in self._chain]
    
    def import_chain(self, chain_data: List[Dict[str, Any]]) -> bool:
        """
        Import chain from data.
        
        Returns True if import successful and chain valid.
        """
        imported_chain = [Block.from_dict(data) for data in chain_data]
        
        # Verify imported chain
        for i in range(1, len(imported_chain)):
            current = imported_chain[i]
            previous = imported_chain[i - 1]
            
            if current.hash != current.compute_hash():
                logger.error("Import failed: block %d hash invalid", i)
                return False
            
            if current.previous_hash != previous.hash:
                logger.error("Import failed: block %d chain broken", i)
                return False
        
        self._chain = imported_chain
        logger.info("Imported chain: %d blocks", len(self._chain))
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get chain statistics."""
        return {
            "chain_length": len(self._chain),
            "latest_hash": self._chain[-1].hash[:16] + "..." if self._chain else None,
            "merkle_root": self.get_merkle_root()[:16] + "...",
            "genesis_timestamp": self._chain[0].timestamp if self._chain else None,
            "latest_timestamp": self._chain[-1].timestamp if self._chain else None,
        }


# Singleton instance
_hash_chain: Optional[HashChain] = None


def get_hash_chain() -> HashChain:
    """Get the singleton hash chain."""
    global _hash_chain
    if _hash_chain is None:
        _hash_chain = HashChain()
    return _hash_chain

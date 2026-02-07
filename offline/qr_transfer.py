"""
QR-Based Intent Transfer.

Enables transfer of signed intents via QR codes for air-gapped
execution. Supports both generation and scanning of QR codes.

Version: 1.0.0
"""

from __future__ import annotations

import json
import time
import base64
import hashlib
import zlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("offline.qr_transfer")


class TransferType(Enum):
    """Types of QR transfers."""
    INTENT = "intent"
    SIGNATURE = "signature"
    EXECUTION_RESULT = "execution_result"
    STATE_SYNC = "state_sync"


class TransferStatus(Enum):
    """Status of a transfer."""
    PENDING = "pending"
    GENERATED = "generated"
    SCANNED = "scanned"
    VERIFIED = "verified"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass
class QRPayload:
    """A QR code payload."""
    payload_id: str
    transfer_type: TransferType
    data: Dict[str, Any]
    
    # Encoding
    compressed: bool = False
    encoded_data: str = ""
    
    # Security
    checksum: str = ""
    signature: Optional[str] = None
    
    # Multi-part support
    part_index: int = 0
    total_parts: int = 1
    
    # Timing
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "payload_id": self.payload_id,
            "transfer_type": self.transfer_type.value,
            "data": self.data,
            "compressed": self.compressed,
            "checksum": self.checksum,
            "signature": self.signature,
            "part_index": self.part_index,
            "total_parts": self.total_parts,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass
class SignedIntent:
    """A signed trading intent for QR transfer."""
    intent_id: str
    intent_type: str
    
    # Trade details
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: Optional[float] = None
    
    # Constraints
    max_slippage_pct: float = 1.0
    expires_at: float = 0.0
    
    # Signature
    signer_address: str = ""
    signature: str = ""
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    nonce: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "max_slippage_pct": self.max_slippage_pct,
            "expires_at": self.expires_at,
            "signer_address": self.signer_address,
            "signature": self.signature,
            "created_at": self.created_at,
            "nonce": self.nonce,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignedIntent":
        return cls(
            intent_id=data["intent_id"],
            intent_type=data["intent_type"],
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            quantity=data.get("quantity", 0.0),
            price=data.get("price"),
            max_slippage_pct=data.get("max_slippage_pct", 1.0),
            expires_at=data.get("expires_at", 0.0),
            signer_address=data.get("signer_address", ""),
            signature=data.get("signature", ""),
            created_at=data.get("created_at", time.time()),
            nonce=data.get("nonce", 0),
        )


class QRIntentTransfer:
    """
    QR-based intent transfer for air-gapped operation.
    
    Features:
    - Generate QR codes for signed intents
    - Scan and verify QR codes
    - Multi-part QR for large payloads
    - Compression for efficiency
    - Checksum verification
    """
    
    def __init__(self):
        self.logger = get_logger("offline.qr_transfer")
        
        # Pending transfers
        self._pending_transfers: Dict[str, QRPayload] = {}
        
        # Received transfers
        self._received_transfers: Dict[str, QRPayload] = {}
        
        # Multi-part assembly
        self._partial_payloads: Dict[str, List[Optional[QRPayload]]] = {}
        
        # Configuration
        self._max_qr_bytes: int = 2953  # QR code capacity (alphanumeric)
        self._default_expiry_seconds: float = 300.0  # 5 minutes
        self._compression_threshold: int = 500
    
    def generate_intent_qr(
        self,
        intent: SignedIntent,
        expiry_seconds: Optional[float] = None,
    ) -> List[str]:
        """Generate QR code data for a signed intent."""
        import uuid
        
        payload_id = f"qr_{uuid.uuid4().hex[:12]}"
        
        # Serialize intent
        intent_data = intent.to_dict()
        json_data = json.dumps(intent_data, separators=(",", ":"))
        
        # Compress if needed
        compressed = False
        if len(json_data) > self._compression_threshold:
            compressed_data = zlib.compress(json_data.encode())
            encoded = base64.b64encode(compressed_data).decode()
            compressed = True
        else:
            encoded = base64.b64encode(json_data.encode()).decode()
        
        # Calculate checksum
        checksum = hashlib.sha256(json_data.encode()).hexdigest()[:16]
        
        # Split into parts if needed
        parts = self._split_payload(encoded)
        
        qr_codes = []
        for i, part in enumerate(parts):
            payload = QRPayload(
                payload_id=payload_id,
                transfer_type=TransferType.INTENT,
                data=intent_data,
                compressed=compressed,
                encoded_data=part,
                checksum=checksum,
                signature=intent.signature,
                part_index=i,
                total_parts=len(parts),
                expires_at=time.time() + (expiry_seconds or self._default_expiry_seconds),
            )
            
            # Generate QR string
            qr_string = self._encode_qr_payload(payload)
            qr_codes.append(qr_string)
            
            self._pending_transfers[f"{payload_id}_{i}"] = payload
        
        self.logger.info(f"Generated {len(qr_codes)} QR code(s) for intent {intent.intent_id}")
        return qr_codes
    
    def _split_payload(self, encoded: str) -> List[str]:
        """Split encoded payload into QR-sized parts."""
        # Account for header overhead
        max_data_size = self._max_qr_bytes - 100
        
        if len(encoded) <= max_data_size:
            return [encoded]
        
        parts = []
        for i in range(0, len(encoded), max_data_size):
            parts.append(encoded[i:i + max_data_size])
        
        return parts
    
    def _encode_qr_payload(self, payload: QRPayload) -> str:
        """Encode payload for QR code."""
        # Format: MERID|version|type|id|part|total|compressed|checksum|data
        header = f"MERID|1|{payload.transfer_type.value}|{payload.payload_id}|{payload.part_index}|{payload.total_parts}|{int(payload.compressed)}|{payload.checksum}|"
        return header + payload.encoded_data
    
    def scan_qr(self, qr_data: str) -> Optional[Dict[str, Any]]:
        """Process scanned QR code data."""
        try:
            # Parse header
            parts = qr_data.split("|", 8)
            
            if len(parts) < 9 or parts[0] != "MERID":
                self.logger.error("Invalid QR format")
                return None
            
            version = parts[1]
            transfer_type = TransferType(parts[2])
            payload_id = parts[3]
            part_index = int(parts[4])
            total_parts = int(parts[5])
            compressed = bool(int(parts[6]))
            checksum = parts[7]
            encoded_data = parts[8]
            
            # Store part
            if payload_id not in self._partial_payloads:
                self._partial_payloads[payload_id] = [None] * total_parts
            
            self._partial_payloads[payload_id][part_index] = QRPayload(
                payload_id=payload_id,
                transfer_type=transfer_type,
                data={},
                compressed=compressed,
                encoded_data=encoded_data,
                checksum=checksum,
                part_index=part_index,
                total_parts=total_parts,
            )
            
            # Check if complete
            if all(p is not None for p in self._partial_payloads[payload_id]):
                return self._assemble_payload(payload_id)
            
            return {
                "status": "partial",
                "payload_id": payload_id,
                "received_parts": sum(1 for p in self._partial_payloads[payload_id] if p is not None),
                "total_parts": total_parts,
            }
            
        except Exception as e:
            self.logger.error(f"QR scan error: {e}")
            return None
    
    def _assemble_payload(self, payload_id: str) -> Dict[str, Any]:
        """Assemble multi-part payload."""
        parts = self._partial_payloads[payload_id]
        
        # Combine encoded data
        combined = "".join(p.encoded_data for p in parts)
        
        # Get metadata from first part
        first_part = parts[0]
        compressed = first_part.compressed
        checksum = first_part.checksum
        transfer_type = first_part.transfer_type
        
        # Decode
        try:
            decoded_bytes = base64.b64decode(combined)
            
            if compressed:
                json_data = zlib.decompress(decoded_bytes).decode()
            else:
                json_data = decoded_bytes.decode()
            
            # Verify checksum
            computed_checksum = hashlib.sha256(json_data.encode()).hexdigest()[:16]
            if computed_checksum != checksum:
                self.logger.error("Checksum verification failed")
                return {"status": "error", "error": "Checksum mismatch"}
            
            # Parse data
            data = json.loads(json_data)
            
            # Create received payload
            payload = QRPayload(
                payload_id=payload_id,
                transfer_type=transfer_type,
                data=data,
                compressed=compressed,
                checksum=checksum,
            )
            
            self._received_transfers[payload_id] = payload
            
            # Clean up partial
            del self._partial_payloads[payload_id]
            
            self.logger.info(f"Assembled payload: {payload_id}")
            
            return {
                "status": "complete",
                "payload_id": payload_id,
                "transfer_type": transfer_type.value,
                "data": data,
            }
            
        except Exception as e:
            self.logger.error(f"Assembly error: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_received_intent(self, payload_id: str) -> Optional[SignedIntent]:
        """Get a received intent."""
        payload = self._received_transfers.get(payload_id)
        if not payload or payload.transfer_type != TransferType.INTENT:
            return None
        
        return SignedIntent.from_dict(payload.data)
    
    def verify_intent_signature(self, intent: SignedIntent) -> bool:
        """Verify intent signature."""
        # In production, use actual signature verification
        # For now, just check signature exists
        if not intent.signature:
            return False
        
        # Check expiry
        if intent.expires_at and time.time() > intent.expires_at:
            self.logger.warning(f"Intent expired: {intent.intent_id}")
            return False
        
        return True
    
    def generate_execution_result_qr(
        self,
        intent_id: str,
        success: bool,
        result: Dict[str, Any],
    ) -> List[str]:
        """Generate QR code for execution result."""
        import uuid
        
        payload_id = f"result_{uuid.uuid4().hex[:8]}"
        
        result_data = {
            "intent_id": intent_id,
            "success": success,
            "result": result,
            "timestamp": time.time(),
        }
        
        json_data = json.dumps(result_data, separators=(",", ":"))
        encoded = base64.b64encode(json_data.encode()).decode()
        checksum = hashlib.sha256(json_data.encode()).hexdigest()[:16]
        
        parts = self._split_payload(encoded)
        
        qr_codes = []
        for i, part in enumerate(parts):
            payload = QRPayload(
                payload_id=payload_id,
                transfer_type=TransferType.EXECUTION_RESULT,
                data=result_data,
                encoded_data=part,
                checksum=checksum,
                part_index=i,
                total_parts=len(parts),
            )
            
            qr_string = self._encode_qr_payload(payload)
            qr_codes.append(qr_string)
        
        return qr_codes
    
    def get_pending_transfers(self) -> List[Dict[str, Any]]:
        """Get pending transfers."""
        return [p.to_dict() for p in self._pending_transfers.values()]
    
    def get_received_transfers(self) -> List[Dict[str, Any]]:
        """Get received transfers."""
        return [p.to_dict() for p in self._received_transfers.values()]
    
    def clear_expired(self) -> int:
        """Clear expired transfers."""
        expired_count = 0
        
        for key, payload in list(self._pending_transfers.items()):
            if payload.is_expired():
                del self._pending_transfers[key]
                expired_count += 1
        
        return expired_count
    
    def get_status(self) -> Dict[str, Any]:
        """Get QR transfer status."""
        return {
            "pending_transfers": len(self._pending_transfers),
            "received_transfers": len(self._received_transfers),
            "partial_payloads": len(self._partial_payloads),
            "max_qr_bytes": self._max_qr_bytes,
            "default_expiry_seconds": self._default_expiry_seconds,
        }


# Singleton
_qr_transfer: Optional[QRIntentTransfer] = None


def get_qr_transfer() -> QRIntentTransfer:
    """Get or create the QR Intent Transfer singleton."""
    global _qr_transfer
    if _qr_transfer is None:
        _qr_transfer = QRIntentTransfer()
    return _qr_transfer

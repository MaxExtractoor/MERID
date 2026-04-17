"""
Hardware Wallet Interface.

Provides integration with hardware wallets (Ledger, Trezor)
for secure offline signing.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
import secrets
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from utils.logger import get_logger

logger = get_logger("wallet.hardware")


class HardwareWalletType(Enum):
    """Supported hardware wallet types."""
    LEDGER = "ledger"
    TREZOR = "trezor"
    KEEPKEY = "keepkey"
    COLDCARD = "coldcard"


class ConnectionStatus(Enum):
    """Hardware wallet connection status."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LOCKED = "locked"
    ERROR = "error"


@dataclass
class HardwareWalletDevice:
    """A connected hardware wallet device."""
    device_id: str
    wallet_type: HardwareWalletType
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    
    # Device info
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    
    # Accounts
    accounts: List[Dict[str, Any]] = field(default_factory=list)
    selected_account_index: int = 0
    
    # Connection
    connected_at: Optional[float] = None
    last_activity: float = field(default_factory=time.time)
    
    # Capabilities
    supports_eip1559: bool = True
    supports_typed_data: bool = True
    max_derivation_depth: int = 5
    
    def get_selected_account(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.selected_account_index < len(self.accounts):
            return self.accounts[self.selected_account_index]
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "wallet_type": self.wallet_type.value,
            "status": self.status.value,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "accounts": self.accounts,
            "selected_account_index": self.selected_account_index,
            "connected_at": self.connected_at,
            "supports_eip1559": self.supports_eip1559,
            "supports_typed_data": self.supports_typed_data,
        }


@dataclass
class SigningRequest:
    """A request to sign with hardware wallet."""
    request_id: str
    device_id: str
    
    # Transaction details
    tx_type: str = "transaction"  # transaction, message, typed_data
    tx_data: Dict[str, Any] = field(default_factory=dict)
    
    # Status
    status: str = "pending"  # pending, awaiting_confirmation, signed, rejected, error
    signature: Optional[str] = None
    error: Optional[str] = None
    
    # Timing
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    timeout_seconds: float = 120.0
    
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.timeout_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "device_id": self.device_id,
            "tx_type": self.tx_type,
            "tx_data": self.tx_data,
            "status": self.status,
            "signature": self.signature,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "is_expired": self.is_expired(),
        }


class HardwareWalletInterface(ABC):
    """Abstract interface for hardware wallet implementations."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the hardware wallet."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the hardware wallet."""
        pass
    
    @abstractmethod
    async def get_accounts(self, derivation_path: str = "m/44'/60'/0'/0") -> List[Dict[str, Any]]:
        """Get accounts from the hardware wallet."""
        pass
    
    @abstractmethod
    async def sign_transaction(self, tx_data: Dict[str, Any]) -> Optional[str]:
        """Sign a transaction."""
        pass
    
    @abstractmethod
    async def sign_message(self, message: str) -> Optional[str]:
        """Sign a message."""
        pass


class LedgerInterface(HardwareWalletInterface):
    """Ledger hardware wallet interface."""
    
    def __init__(self, device: HardwareWalletDevice):
        self.device = device
        self.logger = get_logger("wallet.hardware.ledger")
    
    async def connect(self) -> bool:
        """Connect to Ledger device."""
        # In production, use ledgerblue or ledger-eth-lib
        self.device.status = ConnectionStatus.CONNECTING
        
        # Simulated connection
        self.device.status = ConnectionStatus.CONNECTED
        self.device.connected_at = time.time()
        self.device.model = "Ledger Nano X"
        self.device.firmware_version = "2.1.0"
        
        self.logger.info(f"Connected to Ledger: {self.device.model}")
        return True
    
    async def disconnect(self) -> None:
        """Disconnect from Ledger device."""
        self.device.status = ConnectionStatus.DISCONNECTED
        self.device.connected_at = None
        self.logger.info("Disconnected from Ledger")
    
    async def get_accounts(self, derivation_path: str = "m/44'/60'/0'/0") -> List[Dict[str, Any]]:
        """Get accounts from Ledger."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return []
        
        # Simulated accounts
        accounts = []
        for i in range(5):
            path = f"{derivation_path}/{i}"
            address = f"0x{secrets.token_hex(20)}"
            accounts.append({
                "index": i,
                "path": path,
                "address": address,
            })
        
        self.device.accounts = accounts
        return accounts
    
    async def sign_transaction(self, tx_data: Dict[str, Any]) -> Optional[str]:
        """Sign transaction with Ledger."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return None
        
        # In production, send to device and wait for user confirmation
        # Simulated signature
        signature = f"0x{secrets.token_hex(65)}"
        self.device.last_activity = time.time()
        
        self.logger.info("Transaction signed with Ledger")
        return signature
    
    async def sign_message(self, message: str) -> Optional[str]:
        """Sign message with Ledger."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return None
        
        signature = f"0x{secrets.token_hex(65)}"
        self.device.last_activity = time.time()
        
        self.logger.info("Message signed with Ledger")
        return signature


class TrezorInterface(HardwareWalletInterface):
    """Trezor hardware wallet interface."""
    
    def __init__(self, device: HardwareWalletDevice):
        self.device = device
        self.logger = get_logger("wallet.hardware.trezor")
    
    async def connect(self) -> bool:
        """Connect to Trezor device."""
        # In production, use trezorlib
        self.device.status = ConnectionStatus.CONNECTING
        
        self.device.status = ConnectionStatus.CONNECTED
        self.device.connected_at = time.time()
        self.device.model = "Trezor Model T"
        self.device.firmware_version = "2.5.3"
        
        self.logger.info(f"Connected to Trezor: {self.device.model}")
        return True
    
    async def disconnect(self) -> None:
        """Disconnect from Trezor device."""
        self.device.status = ConnectionStatus.DISCONNECTED
        self.device.connected_at = None
        self.logger.info("Disconnected from Trezor")
    
    async def get_accounts(self, derivation_path: str = "m/44'/60'/0'/0") -> List[Dict[str, Any]]:
        """Get accounts from Trezor."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return []
        
        accounts = []
        for i in range(5):
            path = f"{derivation_path}/{i}"
            address = f"0x{secrets.token_hex(20)}"
            accounts.append({
                "index": i,
                "path": path,
                "address": address,
            })
        
        self.device.accounts = accounts
        return accounts
    
    async def sign_transaction(self, tx_data: Dict[str, Any]) -> Optional[str]:
        """Sign transaction with Trezor."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return None
        
        signature = f"0x{secrets.token_hex(65)}"
        self.device.last_activity = time.time()
        
        self.logger.info("Transaction signed with Trezor")
        return signature
    
    async def sign_message(self, message: str) -> Optional[str]:
        """Sign message with Trezor."""
        if self.device.status != ConnectionStatus.CONNECTED:
            return None
        
        signature = f"0x{secrets.token_hex(65)}"
        self.device.last_activity = time.time()
        
        self.logger.info("Message signed with Trezor")
        return signature


class HardwareWalletManager:
    """
    Manages hardware wallet connections and signing.
    
    Features:
    - Multi-device support
    - Ledger and Trezor integration
    - Signing queue management
    - Timeout handling
    """
    
    def __init__(self):
        self.logger = get_logger("wallet.hardware")
        
        # Connected devices
        self._devices: Dict[str, HardwareWalletDevice] = {}
        self._interfaces: Dict[str, HardwareWalletInterface] = {}
        
        # Signing requests
        self._signing_requests: Dict[str, SigningRequest] = {}
    
    async def scan_devices(self) -> List[HardwareWalletDevice]:
        """Scan for connected hardware wallets."""
        # In production, use USB HID to detect devices
        # Simulated device detection
        devices = []
        
        # Simulate finding a Ledger
        ledger_device = HardwareWalletDevice(
            device_id=f"ledger_{secrets.token_hex(4)}",
            wallet_type=HardwareWalletType.LEDGER,
            model="Ledger Nano X",
        )
        devices.append(ledger_device)
        
        self.logger.info(f"Found {len(devices)} hardware wallet(s)")
        return devices
    
    async def connect_device(
        self,
        wallet_type: HardwareWalletType,
        device_id: Optional[str] = None,
    ) -> Optional[HardwareWalletDevice]:
        """Connect to a hardware wallet."""
        if device_id is None:
            device_id = f"{wallet_type.value}_{secrets.token_hex(4)}"
        
        device = HardwareWalletDevice(
            device_id=device_id,
            wallet_type=wallet_type,
        )
        
        # Create interface
        if wallet_type == HardwareWalletType.LEDGER:
            interface = LedgerInterface(device)
        elif wallet_type == HardwareWalletType.TREZOR:
            interface = TrezorInterface(device)
        else:
            self.logger.error(f"Unsupported wallet type: {wallet_type}")
            return None
        
        # Connect
        success = await interface.connect()
        if not success:
            return None
        
        # Get accounts
        await interface.get_accounts()
        
        self._devices[device_id] = device
        self._interfaces[device_id] = interface
        
        return device
    
    async def disconnect_device(self, device_id: str) -> bool:
        """Disconnect a hardware wallet."""
        interface = self._interfaces.get(device_id)
        if not interface:
            return False
        
        await interface.disconnect()
        
        del self._devices[device_id]
        del self._interfaces[device_id]
        
        return True
    
    def get_device(self, device_id: str) -> Optional[HardwareWalletDevice]:
        """Get a connected device."""
        return self._devices.get(device_id)
    
    def get_connected_devices(self) -> List[HardwareWalletDevice]:
        """Get all connected devices."""
        return [d for d in self._devices.values() if d.status == ConnectionStatus.CONNECTED]
    
    async def request_signature(
        self,
        device_id: str,
        tx_type: str,
        tx_data: Dict[str, Any],
    ) -> Optional[str]:
        """Request a signature from hardware wallet."""
        device = self._devices.get(device_id)
        interface = self._interfaces.get(device_id)
        
        if not device or not interface:
            self.logger.error(f"Device not found: {device_id}")
            return None
        
        if device.status != ConnectionStatus.CONNECTED:
            self.logger.error(f"Device not connected: {device_id}")
            return None
        
        request_id = f"sign_{secrets.token_hex(8)}"
        
        request = SigningRequest(
            request_id=request_id,
            device_id=device_id,
            tx_type=tx_type,
            tx_data=tx_data,
        )
        
        self._signing_requests[request_id] = request
        request.status = "awaiting_confirmation"
        
        # Execute signing
        try:
            if tx_type == "transaction":
                signature = await interface.sign_transaction(tx_data)
            elif tx_type == "message":
                signature = await interface.sign_message(tx_data.get("message", ""))
            else:
                signature = None
            
            if signature:
                request.status = "signed"
                request.signature = signature
            else:
                request.status = "error"
                request.error = "Signing failed"
            
        except Exception as e:
            request.status = "error"
            request.error = str(e)
            self.logger.error(f"Signing error: {e}")
        
        request.completed_at = time.time()
        return request.signature
    
    def get_signing_request(self, request_id: str) -> Optional[SigningRequest]:
        """Get a signing request."""
        return self._signing_requests.get(request_id)
    
    def get_pending_requests(self) -> List[SigningRequest]:
        """Get pending signing requests."""
        return [
            r for r in self._signing_requests.values()
            if r.status in ["pending", "awaiting_confirmation"] and not r.is_expired()
        ]
    
    def get_status(self) -> Dict[str, Any]:
        """Get hardware wallet manager status."""
        return {
            "connected_devices": len(self.get_connected_devices()),
            "pending_requests": len(self.get_pending_requests()),
            "devices": [d.to_dict() for d in self._devices.values()],
            "recent_requests": [
                r.to_dict() for r in list(self._signing_requests.values())[-10:]
            ],
        }


# Singleton
_hardware_wallet_manager: Optional[HardwareWalletManager] = None
_hardware_wallet_manager_lock = threading.Lock()


def get_hardware_wallet_manager() -> HardwareWalletManager:
    """Get or create the Hardware Wallet Manager singleton."""
    global _hardware_wallet_manager
    if _hardware_wallet_manager is None:
        with _hardware_wallet_manager_lock:
            if _hardware_wallet_manager is None:
                _hardware_wallet_manager = HardwareWalletManager()
    return _hardware_wallet_manager

"""
Wallet & Custody API Endpoints.

Provides API access to wallet management, vaults, and signing.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from wallet import (
    get_wallet_manager,
    get_vault_manager,
    get_key_manager,
    get_wallet_connect_manager,
    get_hardware_wallet_manager,
    VaultType,
)
from wallet.hardware_wallet import HardwareWalletType
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/wallet", tags=["wallet"])
logger = get_logger("web.api.wallet")


# ============================================
# REQUEST MODELS
# ============================================

class UnlockRequest(BaseModel):
    password: str


class ImportSeedRequest(BaseModel):
    seed_phrase: str
    label: str = ""
    chain: str = "ethereum"


class ImportKeyRequest(BaseModel):
    private_key: str
    label: str = ""
    chain: str = "ethereum"


class VaultDepositRequest(BaseModel):
    vault_type: str
    asset: str
    amount: float
    value_usd: float


class VaultWithdrawRequest(BaseModel):
    vault_type: str
    asset: str
    amount: float
    value_usd: float
    reason: str = ""


class VaultTransferRequest(BaseModel):
    from_vault: str
    to_vault: str
    asset: str
    amount: float
    value_usd: float
    reason: str = ""


class WalletConnectSignRequest(BaseModel):
    session_id: str
    method: str
    params: Dict[str, Any]


class HardwareSignRequest(BaseModel):
    device_id: str
    tx_type: str
    tx_data: Dict[str, Any]


# ============================================
# WALLET MANAGER ENDPOINTS
# ============================================

@router.get("/status")
async def get_wallet_status() -> Dict[str, Any]:
    """Get comprehensive wallet status."""
    return get_wallet_manager().get_status()


@router.post("/unlock")
async def unlock_wallet(request: UnlockRequest) -> Dict[str, Any]:
    """Unlock the wallet system."""
    success = get_wallet_manager().unlock(request.password)
    if success:
        return {"status": "unlocked"}
    raise HTTPException(status_code=401, detail="Invalid password")


@router.post("/lock")
async def lock_wallet() -> Dict[str, Any]:
    """Lock the wallet system."""
    get_wallet_manager().lock()
    return {"status": "locked"}


@router.post("/emergency-lock")
async def emergency_lock() -> Dict[str, Any]:
    """Emergency lock all wallets and freeze vaults."""
    get_wallet_manager().emergency_lock()
    return {"status": "emergency_locked"}


# ============================================
# KEY MANAGEMENT ENDPOINTS
# ============================================

@router.get("/keys")
async def list_keys() -> Dict[str, Any]:
    """List all stored keys (metadata only)."""
    keys = get_wallet_manager().list_keys()
    return {"count": len(keys), "keys": keys}


@router.post("/keys/import/seed")
async def import_seed_phrase(request: ImportSeedRequest) -> Dict[str, Any]:
    """Import a seed phrase (encrypted)."""
    key_id = get_wallet_manager().import_seed_phrase(
        request.seed_phrase,
        request.label,
        request.chain,
    )
    if key_id:
        return {"status": "imported", "key_id": key_id}
    raise HTTPException(status_code=400, detail="Import failed - check wallet is unlocked")


@router.post("/keys/import/private-key")
async def import_private_key(request: ImportKeyRequest) -> Dict[str, Any]:
    """Import a private key (encrypted)."""
    key_id = get_wallet_manager().import_private_key(
        request.private_key,
        request.label,
        request.chain,
    )
    if key_id:
        return {"status": "imported", "key_id": key_id}
    raise HTTPException(status_code=400, detail="Import failed - check wallet is unlocked")


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, reason: str = "") -> Dict[str, Any]:
    """Revoke a key."""
    success = get_wallet_manager().revoke_key(key_id, reason)
    if success:
        return {"status": "revoked", "key_id": key_id}
    raise HTTPException(status_code=404, detail="Key not found")


@router.get("/keys/audit")
async def get_key_audit_log(limit: int = 100) -> Dict[str, Any]:
    """Get key manager audit log."""
    log = get_key_manager().get_audit_log(limit)
    return {"count": len(log), "entries": log}


# ============================================
# VAULT ENDPOINTS
# ============================================

@router.get("/vaults")
async def get_vaults() -> Dict[str, Any]:
    """Get all vaults."""
    return get_vault_manager().get_status()


@router.get("/vaults/{vault_type}")
async def get_vault(vault_type: str) -> Dict[str, Any]:
    """Get a specific vault."""
    try:
        vtype = VaultType(vault_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vault type: {vault_type}")
    
    vault = get_wallet_manager().get_vault(vtype)
    if vault:
        return vault
    raise HTTPException(status_code=404, detail="Vault not found")


@router.post("/vaults/deposit")
async def deposit_to_vault(request: VaultDepositRequest) -> Dict[str, Any]:
    """Deposit to a vault."""
    try:
        vtype = VaultType(request.vault_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vault type: {request.vault_type}")
    
    success = get_wallet_manager().deposit_to_vault(
        vtype,
        request.asset,
        request.amount,
        request.value_usd,
    )
    if success:
        return {"status": "deposited"}
    raise HTTPException(status_code=400, detail="Deposit failed")


@router.post("/vaults/withdraw")
async def withdraw_from_vault(request: VaultWithdrawRequest) -> Dict[str, Any]:
    """Withdraw from a vault."""
    try:
        vtype = VaultType(request.vault_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vault type: {request.vault_type}")
    
    success = get_wallet_manager().withdraw_from_vault(
        vtype,
        request.asset,
        request.amount,
        request.value_usd,
        request.reason,
    )
    if success:
        return {"status": "withdrawn"}
    raise HTTPException(status_code=400, detail="Withdrawal failed - check limits and approvals")


@router.post("/vaults/transfer")
async def transfer_between_vaults(request: VaultTransferRequest) -> Dict[str, Any]:
    """Transfer between vaults."""
    try:
        from_type = VaultType(request.from_vault)
        to_type = VaultType(request.to_vault)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid vault type: {e}")
    
    transfer_id = get_wallet_manager().transfer_between_vaults(
        from_type,
        to_type,
        request.asset,
        request.amount,
        request.value_usd,
        request.reason,
    )
    if transfer_id:
        return {"status": "transferred", "transfer_id": transfer_id}
    raise HTTPException(status_code=400, detail="Transfer failed")


@router.get("/vaults/pending-approvals")
async def get_pending_approvals() -> Dict[str, Any]:
    """Get pending vault transfer approvals."""
    approvals = get_vault_manager().get_pending_approvals()
    return {"count": len(approvals), "approvals": approvals}


@router.post("/vaults/approve/{transfer_id}")
async def approve_transfer(transfer_id: str, approved_by: str = "admin") -> Dict[str, Any]:
    """Approve a pending transfer."""
    success = get_vault_manager().approve_transfer(transfer_id, approved_by)
    if success:
        return {"status": "approved"}
    raise HTTPException(status_code=404, detail="Transfer not found")


@router.post("/vaults/reject/{transfer_id}")
async def reject_transfer(transfer_id: str, reason: str = "") -> Dict[str, Any]:
    """Reject a pending transfer."""
    success = get_vault_manager().reject_transfer(transfer_id, reason)
    if success:
        return {"status": "rejected"}
    raise HTTPException(status_code=404, detail="Transfer not found")


@router.post("/vaults/{vault_id}/freeze")
async def freeze_vault(vault_id: str, reason: str = "") -> Dict[str, Any]:
    """Freeze a vault (emergency)."""
    success = get_vault_manager().freeze_vault(vault_id, reason)
    if success:
        return {"status": "frozen"}
    raise HTTPException(status_code=404, detail="Vault not found")


@router.post("/vaults/{vault_id}/unfreeze")
async def unfreeze_vault(vault_id: str) -> Dict[str, Any]:
    """Unfreeze a vault."""
    success = get_vault_manager().unfreeze_vault(vault_id)
    if success:
        return {"status": "unfrozen"}
    raise HTTPException(status_code=404, detail="Vault not found")


# ============================================
# WALLETCONNECT ENDPOINTS
# ============================================

@router.get("/walletconnect/status")
async def get_wallet_connect_status() -> Dict[str, Any]:
    """Get WalletConnect status."""
    return get_wallet_connect_manager().get_status()


@router.post("/walletconnect/session")
async def create_wallet_connect_session(chain_id: int = 1) -> Dict[str, Any]:
    """Create a WalletConnect session with QR code."""
    session = get_wallet_manager().create_wallet_connect_session(chain_id)
    return {"status": "created", "session": session}


@router.get("/walletconnect/sessions")
async def get_wallet_connect_sessions() -> Dict[str, Any]:
    """Get active WalletConnect sessions."""
    sessions = get_wallet_manager().get_wallet_connect_sessions()
    return {"count": len(sessions), "sessions": sessions}


@router.post("/walletconnect/disconnect/{session_id}")
async def disconnect_wallet_connect(session_id: str) -> Dict[str, Any]:
    """Disconnect a WalletConnect session."""
    success = get_wallet_manager().disconnect_wallet_connect(session_id)
    if success:
        return {"status": "disconnected"}
    raise HTTPException(status_code=404, detail="Session not found")


@router.post("/walletconnect/sign")
async def request_wallet_connect_sign(request: WalletConnectSignRequest) -> Dict[str, Any]:
    """Request signature via WalletConnect."""
    request_id = get_wallet_manager().request_wallet_connect_sign(
        request.session_id,
        request.method,
        request.params,
    )
    if request_id:
        return {"status": "requested", "request_id": request_id}
    raise HTTPException(status_code=400, detail="Sign request failed")


# ============================================
# HARDWARE WALLET ENDPOINTS
# ============================================

@router.get("/hardware/status")
async def get_hardware_wallet_status() -> Dict[str, Any]:
    """Get hardware wallet status."""
    return get_hardware_wallet_manager().get_status()


@router.post("/hardware/scan")
async def scan_hardware_wallets() -> Dict[str, Any]:
    """Scan for connected hardware wallets."""
    devices = await get_hardware_wallet_manager().scan_devices()
    return {"count": len(devices), "devices": [d.to_dict() for d in devices]}


@router.post("/hardware/connect/{wallet_type}")
async def connect_hardware_wallet(wallet_type: str) -> Dict[str, Any]:
    """Connect a hardware wallet."""
    try:
        wtype = HardwareWalletType(wallet_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid wallet type: {wallet_type}")
    
    device = await get_wallet_manager().connect_hardware_wallet(wtype)
    if device:
        return {"status": "connected", "device": device}
    raise HTTPException(status_code=400, detail="Connection failed")


@router.post("/hardware/disconnect/{device_id}")
async def disconnect_hardware_wallet(device_id: str) -> Dict[str, Any]:
    """Disconnect a hardware wallet."""
    success = await get_wallet_manager().disconnect_hardware_wallet(device_id)
    if success:
        return {"status": "disconnected"}
    raise HTTPException(status_code=404, detail="Device not found")


@router.get("/hardware/devices")
async def get_hardware_devices() -> Dict[str, Any]:
    """Get connected hardware wallets."""
    devices = get_wallet_manager().get_hardware_wallets()
    return {"count": len(devices), "devices": devices}


@router.post("/hardware/sign")
async def request_hardware_sign(request: HardwareSignRequest) -> Dict[str, Any]:
    """Request signature from hardware wallet."""
    signature = await get_wallet_manager().sign_with_hardware(
        request.device_id,
        request.tx_type,
        request.tx_data,
    )
    if signature:
        return {"status": "signed", "signature": signature}
    raise HTTPException(status_code=400, detail="Signing failed")


# ============================================
# TRANSACTION LIMITS
# ============================================

@router.get("/limits")
async def get_transaction_limits() -> Dict[str, Any]:
    """Get transaction limits."""
    manager = get_wallet_manager()
    return {
        "max_single_tx_usd": manager._max_single_tx_usd,
        "daily_limit_usd": manager._daily_limit_usd,
        "daily_spent_usd": manager._daily_spent_usd,
        "daily_remaining_usd": manager._daily_limit_usd - manager._daily_spent_usd,
    }


@router.post("/limits/reset")
async def reset_daily_limits() -> Dict[str, Any]:
    """Reset daily transaction limits."""
    get_wallet_manager().reset_daily_limits()
    return {"status": "reset"}

"""
Transaction Log.

Comprehensive logging of all financial transactions for
regulatory compliance and reconciliation.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("compliance.transaction")


class TransactionType(Enum):
    """Types of transactions."""
    TRADE = "trade"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    FEE = "fee"
    FUNDING = "funding"
    LIQUIDATION = "liquidation"
    SETTLEMENT = "settlement"


class TransactionStatus(Enum):
    """Status of a transaction."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERSED = "reversed"


@dataclass
class Transaction:
    """A financial transaction record."""
    tx_id: str
    tx_type: TransactionType
    status: TransactionStatus = TransactionStatus.PENDING
    
    # Amounts
    asset: str = ""
    quantity: float = 0.0
    price: float = 0.0
    value_usd: float = 0.0
    fee: float = 0.0
    fee_asset: str = "USD"
    
    # Parties
    from_account: str = ""
    to_account: str = ""
    counterparty: str = ""
    
    # Venue
    venue: str = ""
    venue_tx_id: str = ""
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    settlement_time: Optional[float] = None
    
    # References
    order_id: str = ""
    intent_id: str = ""
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    
    # Integrity
    tx_hash: str = ""
    
    def compute_hash(self) -> str:
        """Compute transaction hash."""
        data = {
            "tx_id": self.tx_id,
            "tx_type": self.tx_type.value,
            "asset": self.asset,
            "quantity": self.quantity,
            "price": self.price,
            "timestamp": self.timestamp,
        }
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:32]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "tx_type": self.tx_type.value,
            "status": self.status.value,
            "asset": self.asset,
            "quantity": self.quantity,
            "price": self.price,
            "value_usd": self.value_usd,
            "fee": self.fee,
            "fee_asset": self.fee_asset,
            "from_account": self.from_account,
            "to_account": self.to_account,
            "counterparty": self.counterparty,
            "venue": self.venue,
            "venue_tx_id": self.venue_tx_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "settlement_time": self.settlement_time,
            "order_id": self.order_id,
            "intent_id": self.intent_id,
            "metadata": self.metadata,
            "notes": self.notes,
            "tx_hash": self.tx_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        return cls(
            tx_id=data["tx_id"],
            tx_type=TransactionType(data["tx_type"]),
            status=TransactionStatus(data.get("status", "pending")),
            asset=data.get("asset", ""),
            quantity=data.get("quantity", 0.0),
            price=data.get("price", 0.0),
            value_usd=data.get("value_usd", 0.0),
            fee=data.get("fee", 0.0),
            fee_asset=data.get("fee_asset", "USD"),
            from_account=data.get("from_account", ""),
            to_account=data.get("to_account", ""),
            counterparty=data.get("counterparty", ""),
            venue=data.get("venue", ""),
            venue_tx_id=data.get("venue_tx_id", ""),
            timestamp=data.get("timestamp", time.time()),
            settlement_time=data.get("settlement_time"),
            order_id=data.get("order_id", ""),
            intent_id=data.get("intent_id", ""),
            metadata=data.get("metadata", {}),
            notes=data.get("notes", ""),
            tx_hash=data.get("tx_hash", ""),
        )


class TransactionLog:
    """
    Transaction logging system for compliance.
    
    Features:
    - Immutable transaction records
    - Query and filtering
    - Reconciliation support
    - Export for reporting
    """
    
    def __init__(self, log_dir: str = "data/transactions"):
        self.logger = get_logger("compliance.transaction")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory index
        self._transactions: Dict[str, Transaction] = {}
        
        # Statistics
        self._total_volume_usd: float = 0.0
        self._total_fees_usd: float = 0.0
        self._tx_count_by_type: Dict[str, int] = {}
        
        # Load recent transactions
        self._load_recent()
    
    def _load_recent(self, days: int = 7) -> None:
        """Load recent transactions into memory."""
        cutoff = time.time() - (days * 86400)
        
        for log_file in self.log_dir.glob("tx_*.jsonl"):
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        tx_data = json.loads(line)
                        if tx_data.get("timestamp", 0) >= cutoff:
                            tx = Transaction.from_dict(tx_data)
                            self._transactions[tx.tx_id] = tx
            except Exception as e:
                self.logger.error(f"Error loading {log_file}: {e}")
    
    def _get_log_file(self) -> Path:
        """Get current log file (rotates monthly)."""
        month = datetime.now(timezone.utc).strftime("%Y%m")
        return self.log_dir / f"tx_{month}.jsonl"
    
    def log_transaction(
        self,
        tx_type: TransactionType,
        asset: str,
        quantity: float,
        price: float = 0.0,
        value_usd: float = 0.0,
        fee: float = 0.0,
        fee_asset: str = "USD",
        from_account: str = "",
        to_account: str = "",
        counterparty: str = "",
        venue: str = "",
        venue_tx_id: str = "",
        order_id: str = "",
        intent_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> str:
        """Log a transaction."""
        import uuid
        
        tx_id = f"tx_{uuid.uuid4().hex[:16]}"
        
        # Calculate value if not provided
        if value_usd == 0.0 and price > 0:
            value_usd = quantity * price
        
        tx = Transaction(
            tx_id=tx_id,
            tx_type=tx_type,
            status=TransactionStatus.CONFIRMED,
            asset=asset,
            quantity=quantity,
            price=price,
            value_usd=value_usd,
            fee=fee,
            fee_asset=fee_asset,
            from_account=from_account,
            to_account=to_account,
            counterparty=counterparty,
            venue=venue,
            venue_tx_id=venue_tx_id,
            order_id=order_id,
            intent_id=intent_id,
            metadata=metadata or {},
            notes=notes,
        )
        
        tx.tx_hash = tx.compute_hash()
        
        # Store in memory
        self._transactions[tx_id] = tx
        
        # Persist to disk
        self._persist(tx)
        
        # Update stats
        self._total_volume_usd += abs(value_usd)
        self._total_fees_usd += fee
        type_key = tx_type.value
        self._tx_count_by_type[type_key] = self._tx_count_by_type.get(type_key, 0) + 1
        
        self.logger.info(f"Transaction logged: {tx_id} - {tx_type.value} {quantity} {asset}")
        
        return tx_id
    
    def _persist(self, tx: Transaction) -> None:
        """Persist transaction to disk."""
        log_file = self._get_log_file()
        
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(tx.to_dict()) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to persist transaction: {e}")
    
    def get_transaction(self, tx_id: str) -> Optional[Transaction]:
        """Get a transaction by ID."""
        return self._transactions.get(tx_id)
    
    def query(
        self,
        tx_type: Optional[TransactionType] = None,
        asset: Optional[str] = None,
        venue: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100,
    ) -> List[Transaction]:
        """Query transactions."""
        results = []
        
        for tx in self._transactions.values():
            if tx_type and tx.tx_type != tx_type:
                continue
            if asset and tx.asset != asset:
                continue
            if venue and tx.venue != venue:
                continue
            if start_time and tx.timestamp < start_time:
                continue
            if end_time and tx.timestamp > end_time:
                continue
            if status and tx.status != status:
                continue
            
            results.append(tx)
            
            if len(results) >= limit:
                break
        
        return sorted(results, key=lambda t: t.timestamp, reverse=True)
    
    def get_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get daily transaction summary."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Parse date
        start_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_time = start_dt.timestamp()
        end_time = start_time + 86400
        
        txs = self.query(start_time=start_time, end_time=end_time, limit=10000)
        
        volume_by_asset: Dict[str, float] = {}
        volume_usd = 0.0
        fees_usd = 0.0
        count_by_type: Dict[str, int] = {}
        
        for tx in txs:
            volume_by_asset[tx.asset] = volume_by_asset.get(tx.asset, 0) + abs(tx.quantity)
            volume_usd += abs(tx.value_usd)
            fees_usd += tx.fee
            count_by_type[tx.tx_type.value] = count_by_type.get(tx.tx_type.value, 0) + 1
        
        return {
            "date": date,
            "transaction_count": len(txs),
            "volume_usd": volume_usd,
            "fees_usd": fees_usd,
            "volume_by_asset": volume_by_asset,
            "count_by_type": count_by_type,
        }
    
    def reconcile(
        self,
        venue: str,
        external_transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Reconcile transactions with external venue data."""
        our_txs = {tx.venue_tx_id: tx for tx in self._transactions.values() if tx.venue == venue}
        
        matched = []
        missing_internal = []
        missing_external = []
        mismatched = []
        
        external_ids = set()
        
        for ext_tx in external_transactions:
            ext_id = ext_tx.get("id", "")
            external_ids.add(ext_id)
            
            if ext_id in our_txs:
                our_tx = our_txs[ext_id]
                
                # Check for mismatches
                if abs(our_tx.quantity - ext_tx.get("quantity", 0)) > 0.0001:
                    mismatched.append({
                        "venue_tx_id": ext_id,
                        "field": "quantity",
                        "internal": our_tx.quantity,
                        "external": ext_tx.get("quantity"),
                    })
                else:
                    matched.append(ext_id)
            else:
                missing_internal.append(ext_tx)
        
        for venue_tx_id in our_txs:
            if venue_tx_id not in external_ids:
                missing_external.append(our_txs[venue_tx_id].to_dict())
        
        return {
            "venue": venue,
            "matched_count": len(matched),
            "missing_internal": len(missing_internal),
            "missing_external": len(missing_external),
            "mismatched": len(mismatched),
            "reconciled": len(missing_internal) == 0 and len(missing_external) == 0 and len(mismatched) == 0,
            "details": {
                "missing_internal": missing_internal[:10],
                "missing_external": missing_external[:10],
                "mismatched": mismatched[:10],
            },
        }
    
    def export(
        self,
        start_time: float,
        end_time: float,
        format: str = "json",
    ) -> str:
        """Export transactions to file."""
        txs = self.query(start_time=start_time, end_time=end_time, limit=100000)
        
        export_dir = self.log_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        if format == "json":
            export_file = export_dir / f"tx_export_{timestamp}.json"
            with open(export_file, "w") as f:
                json.dump([t.to_dict() for t in txs], f, indent=2)
        elif format == "csv":
            export_file = export_dir / f"tx_export_{timestamp}.csv"
            import csv
            with open(export_file, "w", newline="") as f:
                if txs:
                    writer = csv.DictWriter(f, fieldnames=txs[0].to_dict().keys())
                    writer.writeheader()
                    for tx in txs:
                        writer.writerow(tx.to_dict())
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return str(export_file)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get transaction statistics."""
        return {
            "total_transactions": len(self._transactions),
            "total_volume_usd": self._total_volume_usd,
            "total_fees_usd": self._total_fees_usd,
            "count_by_type": self._tx_count_by_type,
            "log_dir": str(self.log_dir),
        }


# Singleton
_transaction_log: Optional[TransactionLog] = None
_transaction_log_lock = threading.Lock()


def get_transaction_log() -> TransactionLog:
    """Get or create the Transaction Log singleton."""
    global _transaction_log
    if _transaction_log is None:
        with _transaction_log_lock:
            if _transaction_log is None:
                _transaction_log = TransactionLog()
    return _transaction_log

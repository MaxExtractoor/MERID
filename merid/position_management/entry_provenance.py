"""
Durable entry-provenance snapshot store.

The exchange position record does not contain internal strategy policy metadata
(take-profit, stop-loss, edge-decay model, market close time).  This module
persists a snapshot of the entry policy at order-intent time and links it back
to fills and REST-reloaded positions by (client_order_id, ticker) and fill
identity.  Exit evaluation then consumes resolved provenance; it never invents
TP/SL/edge-decay parameters for an unresolved position.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.position_management.entry_provenance")


class ProvenanceState(Enum):
    """Distinct states for provenance resolution."""

    PROVENANCE_PENDING = "PROVENANCE_PENDING"
    PROVENANCE_RECOVERED = "PROVENANCE_RECOVERED"
    PROVENANCE_MISSING_FILLS = "PROVENANCE_MISSING_FILLS"
    PROVENANCE_MISSING_POLICY = "PROVENANCE_MISSING_POLICY"
    PROVENANCE_SIDE_MISMATCH = "PROVENANCE_SIDE_MISMATCH"
    PROVENANCE_QUANTITY_MISMATCH = "PROVENANCE_QUANTITY_MISMATCH"
    PROVENANCE_COST_BASIS_MISMATCH = "PROVENANCE_COST_BASIS_MISMATCH"
    PROVENANCE_LEGACY_UNRESOLVED = "PROVENANCE_LEGACY_UNRESOLVED"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"


@dataclass
class EntryProvenanceSnapshot:
    """Immutable snapshot of entry policy and edge-decay parameters.

    Created at order-intent time, persisted durably, and linked to fills and
    REST positions.
    """

    snapshot_id: str
    client_order_id: str
    ticker: str
    asset: str
    outcome_side: str
    order_intent_id: Optional[str] = None
    exit_policy_id: Optional[str] = None
    window_resolution_id: Optional[str] = None
    tp_policy_id: Optional[str] = None
    tp_policy_version: Optional[str] = None
    sl_policy_id: Optional[str] = None
    sl_policy_version: Optional[str] = None
    entry_fair_value: Optional[float] = None
    entry_market_value: Optional[float] = None
    entry_edge: Optional[float] = None
    entry_price_cents: Optional[int] = None
    entry_fill_time: Optional[datetime] = None
    # CRITICAL FIX (2026-08-23): Linkage fields populated at fill time.
    order_id: Optional[str] = None
    fill_id: Optional[str] = None
    # CRITICAL FIX (2026-08-23): Durable fill/entry-book provenance for REST
    # rehydration. These fields are written at fill time and allow a position
    # discovered later via REST sync to recover the original AT_FILL executable
    # book and pass spread-stop / model-exit invariants.
    entry_fill_price_cents: Optional[int] = None
    entry_fill_timestamp: Optional[datetime] = None
    entry_executable_bid_cents: Optional[int] = None
    entry_executable_ask_cents: Optional[int] = None
    entry_book_capture_quality: str = "UNKNOWN"
    entry_book_timestamp: Optional[datetime] = None
    entry_book_sequence: Optional[int] = None
    entry_book_source: Optional[str] = None
    edge_decay_model: str = "none"
    edge_decay_parameters: Dict[str, Any] = field(default_factory=dict)
    tp_capture_fraction: float = 0.75
    minimum_remaining_edge: float = 0.02
    sl_parameters: Dict[str, Any] = field(default_factory=dict)
    market_close_time: Optional[datetime] = None
    tp_price_cents: Optional[int] = None
    sl_price_cents: Optional[int] = None
    take_profit_r_multiple: Optional[float] = None
    stop_loss_enabled: bool = True
    max_hold_seconds: Optional[int] = 600
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Decimal):
                d[k] = str(v)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntryProvenanceSnapshot":
        def _dt(value: Any) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except Exception:
                    return None
            return None

        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            client_order_id=data.get("client_order_id", ""),
            ticker=data.get("ticker", ""),
            asset=data.get("asset", ""),
            outcome_side=data.get("outcome_side", ""),
            order_intent_id=data.get("order_intent_id"),
            exit_policy_id=data.get("exit_policy_id"),
            window_resolution_id=data.get("window_resolution_id"),
            tp_policy_id=data.get("tp_policy_id"),
            tp_policy_version=data.get("tp_policy_version"),
            sl_policy_id=data.get("sl_policy_id"),
            sl_policy_version=data.get("sl_policy_version"),
            entry_fair_value=data.get("entry_fair_value"),
            entry_market_value=data.get("entry_market_value"),
            entry_edge=data.get("entry_edge"),
            entry_price_cents=data.get("entry_price_cents"),
            entry_fill_time=_dt(data.get("entry_fill_time")),
            order_id=data.get("order_id"),
            fill_id=data.get("fill_id"),
            entry_fill_price_cents=data.get("entry_fill_price_cents"),
            entry_fill_timestamp=_dt(data.get("entry_fill_timestamp")),
            entry_executable_bid_cents=data.get("entry_executable_bid_cents"),
            entry_executable_ask_cents=data.get("entry_executable_ask_cents"),
            entry_book_capture_quality=data.get("entry_book_capture_quality", "UNKNOWN"),
            entry_book_timestamp=_dt(data.get("entry_book_timestamp")),
            entry_book_sequence=data.get("entry_book_sequence"),
            entry_book_source=data.get("entry_book_source"),
            edge_decay_model=data.get("edge_decay_model", "none"),
            edge_decay_parameters=data.get("edge_decay_parameters", {}),
            tp_capture_fraction=data.get("tp_capture_fraction", 0.75),
            minimum_remaining_edge=data.get("minimum_remaining_edge", 0.02),
            sl_parameters=data.get("sl_parameters", {}),
            market_close_time=_dt(data.get("market_close_time")),
            tp_price_cents=data.get("tp_price_cents"),
            sl_price_cents=data.get("sl_price_cents"),
            take_profit_r_multiple=data.get("take_profit_r_multiple"),
            stop_loss_enabled=data.get("stop_loss_enabled", True),
            max_hold_seconds=data.get("max_hold_seconds", 600),
            created_at=data.get("created_at", 0.0),
        )


@dataclass
class ProvenanceResolution:
    """Outcome of provenance resolution for a position."""

    state: ProvenanceState
    snapshot: Optional[EntryProvenanceSnapshot] = None
    missing_fields: List[str] = field(default_factory=list)
    complete: bool = False
    fills_found: int = 0
    fills_expected: int = 0
    cost_basis_resolved: bool = False
    tp_resolved: bool = False
    sl_resolved: bool = False
    action: str = ""

    def to_log_payload(self) -> Dict[str, Any]:
        return {
            "event": "POSITION_PROVENANCE_RESOLUTION",
            "state": self.state.value,
            "snapshot_id": self.snapshot.snapshot_id if self.snapshot else None,
            "missing_fields": self.missing_fields,
            "complete": self.complete,
            "fills_found": self.fills_found,
            "fills_expected": self.fills_expected,
            "cost_basis_resolved": self.cost_basis_resolved,
            "tp_resolved": self.tp_resolved,
            "sl_resolved": self.sl_resolved,
            "action": self.action,
        }


class EntryProvenanceStore:
    """Durable, process-restart-safe store for entry provenance snapshots."""

    _instance: Optional["EntryProvenanceStore"] = None

    def __new__(cls, *args, **kwargs) -> "EntryProvenanceStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, path: Optional[Path] = None) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._path = path or Path("data") / "entry_provenance_snapshots.json"
        self._snapshots: Dict[str, EntryProvenanceSnapshot] = {}
        self._by_ticker: Dict[str, List[EntryProvenanceSnapshot]] = {}
        self._by_order_id: Dict[str, EntryProvenanceSnapshot] = {}
        self._by_fill_id: Dict[str, EntryProvenanceSnapshot] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return
            for coid, raw in payload.items():
                try:
                    snap = EntryProvenanceSnapshot.from_dict(raw)
                    self._snapshots[coid] = snap
                    self._by_ticker.setdefault(snap.ticker, []).append(snap)
                    if snap.order_id:
                        self._by_order_id[snap.order_id] = snap
                    if snap.fill_id:
                        self._by_fill_id[snap.fill_id] = snap
                except Exception as e:
                    logger.warning("[ENTRY-PROVENANCE-STORE] Failed to load snapshot %s: %s", coid, e)
            logger.info(
                "[ENTRY-PROVENANCE-STORE] Loaded %d snapshots from %s",
                len(self._snapshots),
                self._path,
            )
        except Exception as e:
            logger.warning("[ENTRY-PROVENANCE-STORE] Failed to load store: %s", e)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {coid: snap.to_dict() for coid, snap in self._snapshots.items()}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception as e:
            logger.warning("[ENTRY-PROVENANCE-STORE] Failed to save store: %s", e)

    def register(self, snapshot: EntryProvenanceSnapshot) -> None:
        """Persist a new or replacement snapshot keyed by client_order_id."""
        if not snapshot.client_order_id:
            logger.warning("[ENTRY-PROVENANCE-STORE] Refusing to register snapshot without client_order_id")
            return
        # Remove old index entry if replacing.
        existing = self._snapshots.get(snapshot.client_order_id)
        if existing:
            if existing.ticker in self._by_ticker:
                try:
                    self._by_ticker[existing.ticker].remove(existing)
                except ValueError:
                    pass
            if existing.order_id and existing.order_id in self._by_order_id:
                del self._by_order_id[existing.order_id]
            if existing.fill_id and existing.fill_id in self._by_fill_id:
                del self._by_fill_id[existing.fill_id]
        self._snapshots[snapshot.client_order_id] = snapshot
        self._by_ticker.setdefault(snapshot.ticker, []).append(snapshot)
        if snapshot.order_id:
            self._by_order_id[snapshot.order_id] = snapshot
        if snapshot.fill_id:
            self._by_fill_id[snapshot.fill_id] = snapshot
        self._save()
        logger.info(
            "[ENTRY-PROVENANCE-STORE] Registered snapshot %s for coid=%s ticker=%s",
            snapshot.snapshot_id,
            snapshot.client_order_id,
            snapshot.ticker,
        )

    def get(self, client_order_id: Optional[str]) -> Optional[EntryProvenanceSnapshot]:
        return self._snapshots.get(client_order_id) if client_order_id else None

    def get_by_client_order_id(self, client_order_id: Optional[str]) -> Optional[EntryProvenanceSnapshot]:
        return self.get(client_order_id)

    def get_by_ticker(self, ticker: str) -> List[EntryProvenanceSnapshot]:
        return list(self._by_ticker.get(ticker, []))

    def get_by_order_id(self, order_id: Optional[str]) -> Optional[EntryProvenanceSnapshot]:
        return self._by_order_id.get(order_id) if order_id else None

    def get_by_fill_id(self, fill_id: Optional[str]) -> Optional[EntryProvenanceSnapshot]:
        return self._by_fill_id.get(fill_id) if fill_id else None

    def get_by_position_key(self, position_key: Any) -> Optional[EntryProvenanceSnapshot]:
        """Look up a snapshot by canonical position key (uses market ticker)."""
        if position_key is None:
            return None
        ticker = getattr(position_key, "market_ticker", None)
        if not ticker:
            return None
        candidates = self.get_by_ticker(ticker)
        return candidates[0] if candidates else None

    def get_by_ticker_and_side(
        self, ticker: str, outcome_side: str
    ) -> Optional[EntryProvenanceSnapshot]:
        """Return the most recent snapshot for a ticker and outcome side."""
        candidates = [
            s
            for s in self.get_by_ticker(ticker)
            if (s.outcome_side or "").lower() == (outcome_side or "").lower()
        ]
        if not candidates:
            return None
        # Prefer a snapshot that has been linked to a fill, then the most recent.
        linked = [s for s in candidates if s.fill_id]
        if linked:
            return max(linked, key=lambda s: s.created_at or 0.0)
        return max(candidates, key=lambda s: s.created_at or 0.0)

    def rehydrate_for_position(
        self,
        ticker: str,
        position_side: str,
        client_order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
        order_id: Optional[str] = None,
        position_qty_cc: Optional[int] = None,
        fills: Optional[List[Any]] = None,
    ) -> ProvenanceResolution:
        """Rehydrate a position's exit plan from durable provenance.

        Unlike ``resolve_provenance``, this path does NOT require fills. It is
        intended for REST-synced positions or startup-reloaded positions that
        have a durable policy snapshot but may not yet have fills in memory. If
        fills are provided they are used for validation, but a missing or empty
        fill list is not an automatic failure when a snapshot exists.
        """
        snapshot: Optional[EntryProvenanceSnapshot] = None

        # 1. Direct linkage lookups (strongest identity).
        if client_order_id:
            snapshot = self.get(client_order_id)
        if snapshot is None and fill_id:
            snapshot = self.get_by_fill_id(fill_id)
        if snapshot is None and order_id:
            snapshot = self.get_by_order_id(order_id)

        # 2. Ticker + side lookup for REST-only positions.
        if snapshot is None:
            snapshot = self.get_by_ticker_and_side(ticker, position_side)

        fills_found = len(fills) if fills else 0

        if snapshot is None:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_MISSING_POLICY,
                missing_fields=["entry_policy_snapshot"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=False,
                tp_resolved=False,
                sl_resolved=False,
                action="RETRY_POLICY_STORE",
            )

        # Validate provided fills if any; do not reject if missing.
        side_mismatch = False
        cost_basis_resolved = (
            snapshot.entry_fill_price_cents is not None
            or snapshot.entry_price_cents is not None
        )
        if fills:
            for fill in fills:
                fill_side = (
                    getattr(fill, "canonical_position_side", None)
                    or getattr(fill, "side", None)
                    or ""
                ).lower()
                if fill_side and fill_side != position_side.lower():
                    side_mismatch = True
                if getattr(fill, "canonical_leg_price_cents", None):
                    cost_basis_resolved = True

        if side_mismatch:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_SIDE_MISMATCH,
                snapshot=snapshot,
                missing_fields=["side"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=False,
                tp_resolved=False,
                sl_resolved=False,
                action="QUARANTINE_SIDE_RECONCILIATION",
            )

        # A position is rehydratable when its policy snapshot has a client
        # linkage and either a cost basis or a TP/SL policy. We do not demand
        # fills because REST sync may happen before the fills ledger is loaded.
        tp_resolved = (
            snapshot.tp_price_cents is not None and snapshot.tp_policy_id is not None
        )
        sl_resolved = (
            snapshot.sl_price_cents is not None and snapshot.sl_policy_id is not None
        )
        has_model = (
            snapshot.entry_fair_value is not None
            and snapshot.entry_market_value is not None
            and snapshot.entry_edge is not None
        )
        complete = (
            bool(snapshot.client_order_id)
            and cost_basis_resolved
            and (tp_resolved or sl_resolved or has_model)
        )

        missing: List[str] = []
        if not tp_resolved:
            missing.append("tp_policy")
        if not sl_resolved:
            missing.append("sl_policy")
        if not cost_basis_resolved:
            missing.append("cost_basis")

        if complete:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_RECOVERED,
                snapshot=snapshot,
                missing_fields=missing,
                fills_found=fills_found,
                fills_expected=1,
                complete=True,
                cost_basis_resolved=cost_basis_resolved,
                tp_resolved=tp_resolved,
                sl_resolved=sl_resolved,
                action="REHYDRATE_EXIT_PLAN",
            )

        return ProvenanceResolution(
            state=ProvenanceState.PROVENANCE_LEGACY_UNRESOLVED,
            snapshot=snapshot,
            missing_fields=missing,
            fills_found=fills_found,
            fills_expected=1,
            complete=False,
            cost_basis_resolved=cost_basis_resolved,
            tp_resolved=tp_resolved,
            sl_resolved=sl_resolved,
            action="REHYDRATE_PARTIAL",
        )

    def register_fill_linkage(
        self,
        client_order_id: str,
        order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
    ) -> None:
        """Update a snapshot with order_id / fill_id once the fill arrives."""
        snapshot = self.get(client_order_id)
        if snapshot is None:
            return
        changed = False
        if order_id and not snapshot.order_id:
            snapshot.order_id = order_id
            self._by_order_id[order_id] = snapshot
            changed = True
        if fill_id and not snapshot.fill_id:
            snapshot.fill_id = fill_id
            self._by_fill_id[fill_id] = snapshot
            changed = True
        if changed:
            self._save()
            logger.info(
                "[ENTRY-PROVENANCE-STORE] Linked snapshot %s to order_id=%s fill_id=%s",
                snapshot.snapshot_id, order_id, fill_id
            )

    def resolve_provenance(
        self,
        ticker: str,
        position_qty_cc: int,
        position_side: str,
        fills: Optional[List[Any]],
        client_order_id: Optional[str] = None,
    ) -> ProvenanceResolution:
        """Resolve provenance for a REST-reloaded or fill-built position.

        Args:
            ticker: market ticker
            position_qty_cc: absolute position quantity in centi-contracts
            position_side: "yes" or "no"
            fills: list of KalshiFill records for this ticker
            client_order_id: preferred client_order_id to look up the snapshot
        """
        snapshot: Optional[EntryProvenanceSnapshot] = None

        # 1. Direct client_order_id lookup.
        if client_order_id:
            snapshot = self.get(client_order_id)

        # 2. Try to find a snapshot from any fill's client_order_id.
        fill_client_order_ids: List[str] = []
        if not snapshot and fills:
            for fill in fills:
                coid = getattr(fill, "client_order_id", None)
                if coid and coid not in fill_client_order_ids:
                    fill_client_order_ids.append(coid)
                    candidate = self.get(coid)
                    if candidate and candidate.ticker == ticker:
                        snapshot = candidate
                        break

        # 3. Fallback: match by ticker and side.
        if not snapshot:
            candidates = self.get_by_ticker(ticker)
            for candidate in candidates:
                if candidate.outcome_side == position_side:
                    snapshot = candidate
                    break

        fills_found = len(fills) if fills else 0

        if not fills:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_MISSING_FILLS,
                snapshot=snapshot,
                missing_fields=["fills"],
                fills_found=0,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=False,
                tp_resolved=False,
                sl_resolved=False,
                action="FETCH_LIVE_AND_HISTORICAL_FILLS",
            )

        # If there is no policy snapshot at all, provenance is unresolved.
        if not snapshot:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_MISSING_POLICY,
                missing_fields=["entry_policy_snapshot"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=False,
                tp_resolved=False,
                sl_resolved=False,
                action="RETRY_POLICY_STORE",
            )

        # Validate side and quantity.
        fill_qty = 0
        side_mismatch = False
        cost_basis_resolved = False
        entry_price = None
        for fill in fills:
            fill_side = (
                getattr(fill, "canonical_position_side", None)
                or getattr(fill, "side", None)
                or ""
            ).lower()
            fill_qty += abs(getattr(fill, "quantity_cc", 0) or 0)
            if fill_side and fill_side != position_side.lower():
                side_mismatch = True
            if getattr(fill, "canonical_leg_price_cents", None):
                cost_basis_resolved = True
                if entry_price is None:
                    entry_price = getattr(fill, "canonical_leg_price_cents")

        if side_mismatch:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_SIDE_MISMATCH,
                snapshot=snapshot,
                missing_fields=["side"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=False,
                tp_resolved=False,
                sl_resolved=False,
                action="QUARANTINE_SIDE_RECONCILIATION",
            )

        # Allow 0.01 contract tolerance.
        if abs(fill_qty - position_qty_cc) > 1:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_QUANTITY_MISMATCH,
                snapshot=snapshot,
                missing_fields=["quantity"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=cost_basis_resolved,
                tp_resolved=False,
                sl_resolved=False,
                action="RECONCILE_FILLS_WITH_REST",
            )

        if not cost_basis_resolved:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_COST_BASIS_MISMATCH,
                snapshot=snapshot,
                missing_fields=["cost_basis"],
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                tp_resolved=False,
                sl_resolved=False,
                action="FETCH_HISTORICAL_FILLS",
            )

        tp_resolved = snapshot.tp_price_cents is not None and snapshot.tp_policy_id is not None
        sl_resolved = snapshot.sl_price_cents is not None and snapshot.sl_policy_id is not None

        missing = []
        if not tp_resolved:
            missing.append("tp_policy")
        if not sl_resolved:
            missing.append("sl_policy")
        if snapshot.market_close_time is None:
            missing.append("market_close_time")
        if snapshot.entry_fill_time is None:
            missing.append("entry_fill_time")
        if snapshot.edge_decay_model == "none":
            missing.append("edge_decay_model")

        if missing:
            return ProvenanceResolution(
                state=ProvenanceState.PROVENANCE_LEGACY_UNRESOLVED,
                snapshot=snapshot,
                missing_fields=missing,
                fills_found=fills_found,
                fills_expected=1,
                complete=False,
                cost_basis_resolved=True,
                tp_resolved=tp_resolved,
                sl_resolved=sl_resolved,
                action="RETRY_POLICY_STORE",
            )

        return ProvenanceResolution(
            state=ProvenanceState.PROVENANCE_RECOVERED,
            snapshot=snapshot,
            missing_fields=[],
            fills_found=fills_found,
            fills_expected=1,
            complete=True,
            cost_basis_resolved=True,
            tp_resolved=tp_resolved,
            sl_resolved=sl_resolved,
            action="EVALUATE_EXIT",
        )


def get_entry_provenance_store() -> EntryProvenanceStore:
    return EntryProvenanceStore()

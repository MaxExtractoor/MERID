"""§4 ComplianceRegistry — Venue/asset allowlist, regulatory checks, audit/record-keeping.

Config-driven compliance for MERID's blockchain and trading operations.
Enforced by GovernanceAgent and risk layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.blockchain.compliance")


# ── Classification ───────────────────────────────────────────────────

class EntityClassification(str, Enum):
    """What MERID is NOT (and what it is)."""
    PROPRIETARY_TRADER = "proprietary_trader"  # What we ARE
    NOT_EXCHANGE = "not_exchange"
    NOT_CUSTODIAN = "not_custodian"
    NOT_TOKEN_ISSUER = "not_token_issuer"
    NOT_BROKER_DEALER = "not_broker_dealer"


# ── Venue/Asset allowlist ────────────────────────────────────────────

class VenueStatus(str, Enum):
    ALLOWED = "allowed"
    RESTRICTED = "restricted"   # Allowed with limits
    PROHIBITED = "prohibited"


@dataclass
class VenueComplianceEntry:
    """Compliance status for a trading venue."""
    venue: str
    status: VenueStatus = VenueStatus.ALLOWED
    jurisdiction: str = "US"
    requires_kyc: bool = False
    max_leverage: float = 1.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "status": self.status.value,
            "jurisdiction": self.jurisdiction,
            "requires_kyc": self.requires_kyc,
            "max_leverage": self.max_leverage,
            "notes": self.notes,
        }


@dataclass
class AssetComplianceEntry:
    """Compliance status for a tradeable asset."""
    asset: str
    status: VenueStatus = VenueStatus.ALLOWED
    asset_type: str = "crypto"   # crypto, equity, prediction, stablecoin
    sanctions_screened: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "status": self.status.value,
            "asset_type": self.asset_type,
            "sanctions_screened": self.sanctions_screened,
            "notes": self.notes,
        }


# ── Audit record ─────────────────────────────────────────────────────

@dataclass
class ComplianceAuditRecord:
    """A compliance audit record for orders, fills, transfers."""
    record_id: str = ""
    record_type: str = ""      # "order", "fill", "transfer", "decision"
    venue: str = ""
    asset: str = ""
    direction: str = ""
    amount: str = ""
    agent_id: str = ""
    rationale: str = ""
    compliance_check: str = ""  # "passed", "flagged", "blocked"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "venue": self.venue,
            "asset": self.asset,
            "direction": self.direction,
            "amount": self.amount,
            "agent_id": self.agent_id,
            "compliance_check": self.compliance_check,
            "timestamp": self.timestamp.isoformat(),
        }


# ── ComplianceRegistry ───────────────────────────────────────────────

class ComplianceRegistry:
    """Central compliance registry for MERID.

    Manages:
    - Entity classification (what MERID is/isn't).
    - Venue allowlist/blocklist.
    - Asset allowlist/blocklist.
    - Audit record-keeping with retention.
    - Periodic review tracking.
    """

    def __init__(self, jurisdiction: str = "US"):
        self.jurisdiction = jurisdiction
        self.classifications: List[EntityClassification] = [
            EntityClassification.PROPRIETARY_TRADER,
            EntityClassification.NOT_EXCHANGE,
            EntityClassification.NOT_CUSTODIAN,
            EntityClassification.NOT_TOKEN_ISSUER,
            EntityClassification.NOT_BROKER_DEALER,
        ]
        self._venues: Dict[str, VenueComplianceEntry] = {}
        self._assets: Dict[str, AssetComplianceEntry] = {}
        self._audit_records: List[ComplianceAuditRecord] = []
        self._last_review: Optional[datetime] = None
        self._review_interval_days: int = 90

    # ── Venue management ─────────────────────────────────────────────

    def register_venue(self, entry: VenueComplianceEntry) -> None:
        self._venues[entry.venue] = entry

    def get_venue(self, venue: str) -> Optional[VenueComplianceEntry]:
        return self._venues.get(venue)

    def is_venue_allowed(self, venue: str) -> bool:
        entry = self._venues.get(venue)
        if not entry:
            return False  # Unknown venues are blocked by default
        return entry.status != VenueStatus.PROHIBITED

    def list_venues(self, status: Optional[VenueStatus] = None) -> List[VenueComplianceEntry]:
        if status:
            return [v for v in self._venues.values() if v.status == status]
        return list(self._venues.values())

    # ── Asset management ─────────────────────────────────────────────

    def register_asset(self, entry: AssetComplianceEntry) -> None:
        self._assets[entry.asset] = entry

    def get_asset(self, asset: str) -> Optional[AssetComplianceEntry]:
        return self._assets.get(asset)

    def is_asset_allowed(self, asset: str) -> bool:
        entry = self._assets.get(asset)
        if not entry:
            return True  # Unknown assets allowed by default (conservative: flip if needed)
        return entry.status != VenueStatus.PROHIBITED

    def list_assets(self, status: Optional[VenueStatus] = None) -> List[AssetComplianceEntry]:
        if status:
            return [a for a in self._assets.values() if a.status == status]
        return list(self._assets.values())

    # ── Compliance check ─────────────────────────────────────────────

    def check_trade(self, venue: str, asset: str, agent_id: str = "") -> ComplianceAuditRecord:
        """Check if a trade on venue/asset is compliant."""
        issues = []

        if not self.is_venue_allowed(venue):
            issues.append(f"Venue '{venue}' is prohibited.")
        if not self.is_asset_allowed(asset):
            issues.append(f"Asset '{asset}' is prohibited.")

        status = "passed" if not issues else "blocked"
        record = ComplianceAuditRecord(
            record_type="compliance_check",
            venue=venue, asset=asset, agent_id=agent_id,
            compliance_check=status,
            rationale="; ".join(issues) if issues else "All checks passed.",
        )
        self._audit_records.append(record)
        return record

    # ── Audit records ────────────────────────────────────────────────

    def record_event(self, record: ComplianceAuditRecord) -> None:
        self._audit_records.append(record)

    def get_audit_records(self, limit: int = 100) -> List[ComplianceAuditRecord]:
        return self._audit_records[-limit:]

    # ── Review tracking ──────────────────────────────────────────────

    def mark_review_complete(self) -> None:
        self._last_review = datetime.now(timezone.utc)

    @property
    def review_overdue(self) -> bool:
        if not self._last_review:
            return True
        age = (datetime.now(timezone.utc) - self._last_review).days
        return age >= self._review_interval_days

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "jurisdiction": self.jurisdiction,
            "classifications": [c.value for c in self.classifications],
            "venues_total": len(self._venues),
            "venues_allowed": len([v for v in self._venues.values() if v.status == VenueStatus.ALLOWED]),
            "venues_prohibited": len([v for v in self._venues.values() if v.status == VenueStatus.PROHIBITED]),
            "assets_total": len(self._assets),
            "audit_records": len(self._audit_records),
            "review_overdue": self.review_overdue,
            "last_review": self._last_review.isoformat() if self._last_review else None,
        }


# ── Default registry ─────────────────────────────────────────────────

def _build_default_compliance() -> ComplianceRegistry:
    reg = ComplianceRegistry(jurisdiction="US")

    # Venues
    venues = [
        VenueComplianceEntry(venue="kalshi", status=VenueStatus.ALLOWED, notes="US-regulated prediction market"),
        VenueComplianceEntry(venue="binance", status=VenueStatus.ALLOWED, notes="Binance.US for US users"),
        VenueComplianceEntry(venue="coinbase", status=VenueStatus.ALLOWED, notes="US-regulated CEX"),
        VenueComplianceEntry(venue="kraken", status=VenueStatus.ALLOWED, notes="US-regulated CEX"),
        VenueComplianceEntry(venue="okx", status=VenueStatus.RESTRICTED, notes="Data-only for US; no trading", max_leverage=1.0),
        VenueComplianceEntry(venue="alpaca", status=VenueStatus.ALLOWED, notes="US broker-dealer"),
        VenueComplianceEntry(venue="ibkr", status=VenueStatus.ALLOWED, notes="US broker-dealer"),
        VenueComplianceEntry(venue="polymarket", status=VenueStatus.PROHIBITED, notes="Not available for US users"),
        VenueComplianceEntry(venue="augur", status=VenueStatus.PROHIBITED, notes="Unregistered prediction market"),
        VenueComplianceEntry(venue="predictit", status=VenueStatus.PROHIBITED, notes="Winding down"),
    ]
    for v in venues:
        reg.register_venue(v)

    # Assets
    assets = [
        AssetComplianceEntry(asset="BTC", asset_type="crypto"),
        AssetComplianceEntry(asset="ETH", asset_type="crypto"),
        AssetComplianceEntry(asset="SOL", asset_type="crypto"),
        AssetComplianceEntry(asset="USDC", asset_type="stablecoin"),
        AssetComplianceEntry(asset="USDT", asset_type="stablecoin"),
        AssetComplianceEntry(asset="AAPL", asset_type="equity"),
        AssetComplianceEntry(asset="TSLA", asset_type="equity"),
        AssetComplianceEntry(asset="SPY", asset_type="equity"),
        AssetComplianceEntry(asset="TORN", status=VenueStatus.PROHIBITED, asset_type="crypto",
                             notes="OFAC sanctioned"),
    ]
    for a in assets:
        reg.register_asset(a)

    return reg


_registry: Optional[ComplianceRegistry] = None


def get_compliance_registry() -> ComplianceRegistry:
    global _registry
    if _registry is None:
        _registry = _build_default_compliance()
    return _registry

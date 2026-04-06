"""Pipeline Audit — per-cycle invariant checks for all 5 crypto assets.

Provides a structured, runtime-verified audit that BTC, ETH, SOL, XRP, and
DOGE are flowing through every stage of the CT pipeline: catalog → filter →
signal → CT → risk → execution.

Usage (called once per trade cycle from CT or a background task)::

    from merid.event_venues.kalshi.pipeline_audit import PipelineAudit, AuditResult

    audit = PipelineAudit()
    result = audit.run(cycle_stats=ct.last_cycle_stats, catalog_snapshot=snap)
    if not result.all_pass:
        logger.warning("[PIPELINE-AUDIT] blockers: %s", result.blockers)

Design
──────
The audit is split into three layers matching the problem statement:

  UPSTREAM  : Catalog / filter counts per asset+timeframe (non-zero invariant).
  CORE      : CT ANALYZE→CONSENSUS→SIZE→EXECUTE path; per-asset flow confirmed.
  DOWNSTREAM: Fill/PnL/exposure consistency; bankroll invariant components OK.

Each layer produces a list of ``AuditItem`` findings.  A finding can be:
  PASS  — invariant holds.
  WARN  — soft invariant (unusual but not fatal, e.g. zero markets in a
          timeframe that historically has markets).
  FAIL  — hard invariant broken (e.g. asset missing from by_asset_timeframe
          when catalog has live markets).

Run mode
────────
Call ``audit.run(...)`` at the end of each trade cycle.  The result is exposed
via ``CT.status()["pipeline_audit"]`` so the health API can surface blockers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from config.crypto_universe import CRYPTO_ASSETS_ORDERED, CRYPTO_TIMEFRAMES_ORDERED
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.pipeline_audit")

# ── All five required assets ───────────────────────────────────────────────
_REQUIRED_ASSETS: List[str] = CRYPTO_ASSETS_ORDERED  # ["BTC","ETH","SOL","XRP","DOGE"]


# ── Finding severity ──────────────────────────────────────────────────────

class Severity(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class AuditItem:
    """Single audit finding."""
    layer: str          # "UPSTREAM" | "CORE" | "DOWNSTREAM"
    phase: str          # e.g. "catalog", "filter", "edge", "kelly", "execution"
    asset: Optional[str]
    timeframe: Optional[str]
    severity: Severity
    message: str


@dataclass
class AuditResult:
    """Collected result of one audit run."""
    ts: float = field(default_factory=time.time)
    items: List[AuditItem] = field(default_factory=list)
    # Convenience roll-ups
    passes: int = 0
    warnings: int = 0
    failures: int = 0
    blockers: List[str] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return self.failures == 0

    def add(self, item: AuditItem) -> None:
        self.items.append(item)
        if item.severity == Severity.PASS:
            self.passes += 1
        elif item.severity == Severity.WARN:
            self.warnings += 1
        else:
            self.failures += 1
            self.blockers.append(
                f"[{item.layer}/{item.phase}] "
                f"{item.asset or '*'}/{item.timeframe or '*'}: {item.message}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "all_pass": self.all_pass,
            "passes": self.passes,
            "warnings": self.warnings,
            "failures": self.failures,
            "blockers": self.blockers,
            "items": [
                {
                    "layer": i.layer,
                    "phase": i.phase,
                    "asset": i.asset,
                    "timeframe": i.timeframe,
                    "severity": i.severity.value,
                    "message": i.message,
                }
                for i in self.items
            ],
        }


# ── CatalogSnapshot duck-type ─────────────────────────────────────────────

class _CatalogSnapshot:
    """Duck-type interface for catalog snapshot data.

    Accepts either a real ``CatalogSnapshot`` object (from market_catalog.py)
    or a plain dict with ``by_asset`` and ``by_timeframe`` keys.
    """

    def __init__(self, snapshot: Any) -> None:
        if isinstance(snapshot, dict):
            self._by_asset: Dict[str, int] = snapshot.get("by_asset", {})
            self._by_tf: Dict[str, int] = snapshot.get("by_timeframe", {})
            # by_asset_timeframe: {asset: {timeframe: count}}
            self._by_at: Dict[str, Dict[str, int]] = snapshot.get("by_asset_timeframe", {})
        else:
            # Real CatalogSnapshot object from market_catalog.CatalogSnapshot
            self._by_asset = getattr(snapshot, "by_asset", {})
            self._by_tf = getattr(snapshot, "by_timeframe", {})
            self._by_at = getattr(snapshot, "by_asset_timeframe", {})

    def count_for_asset(self, asset: str) -> int:
        return self._by_asset.get(asset, 0)

    def count_for_asset_tf(self, asset: str, timeframe: str) -> int:
        return self._by_at.get(asset, {}).get(timeframe, 0)


# ── Main audit class ──────────────────────────────────────────────────────

class PipelineAudit:
    """Per-cycle pipeline health audit for all 5 crypto assets.

    Checks three layers:
      1. UPSTREAM  — catalog & filter invariants.
      2. CORE      — CT evaluate/approve/execute flow per asset.
      3. DOWNSTREAM — fill reconciliation, bankroll invariant, exposure.
    """

    def run(
        self,
        cycle_stats: Optional[Dict[str, Any]] = None,
        catalog_snapshot: Any = None,
        downstream_state: Optional[Dict[str, Any]] = None,
    ) -> AuditResult:
        """Run all audit layers and return a consolidated AuditResult.

        Args:
            cycle_stats: CT._last_cycle_stats dict (may include per_asset_stats).
            catalog_snapshot: CatalogSnapshot object or equivalent dict.
            downstream_state: Optional dict with fill/PnL/exposure data.
        """
        result = AuditResult()
        snap = _CatalogSnapshot(catalog_snapshot) if catalog_snapshot is not None else None

        # Layer 1: Upstream
        self._audit_upstream(result, snap, cycle_stats)

        # Layer 2: Core CT loop
        self._audit_core(result, cycle_stats)

        # Layer 3: Downstream
        if downstream_state:
            self._audit_downstream(result, downstream_state)

        # Log summary.
        log_fn = logger.warning if not result.all_pass else logger.debug
        log_fn(
            "[PIPELINE-AUDIT] pass=%d warn=%d fail=%d all_pass=%s blockers=%s",
            result.passes, result.warnings, result.failures,
            result.all_pass, result.blockers or "none",
        )
        return result

    # ── Layer 1: Upstream ────────────────────────────────────────────────

    def _audit_upstream(
        self,
        result: AuditResult,
        snap: Optional[_CatalogSnapshot],
        cycle_stats: Optional[Dict[str, Any]],
    ) -> None:
        """Check catalog presence and filter pipeline counts per asset."""

        # 1a. Catalog — all 5 assets must be present when catalog is provided.
        if snap is not None:
            for asset in _REQUIRED_ASSETS:
                count = snap.count_for_asset(asset)
                if count == 0:
                    result.add(AuditItem(
                        layer="UPSTREAM", phase="catalog", asset=asset,
                        timeframe=None, severity=Severity.WARN,
                        message=f"No markets in catalog for {asset} — "
                                "Kalshi may have no live markets for this asset.",
                    ))
                else:
                    result.add(AuditItem(
                        layer="UPSTREAM", phase="catalog", asset=asset,
                        timeframe=None, severity=Severity.PASS,
                        message=f"{count} market(s) in catalog for {asset}.",
                    ))

        # 1b. Invariant: by_asset_timeframe must cover all 5 assets when
        #     cycle_stats includes scan_by_asset_timeframe counts.
        if cycle_stats:
            by_at: Dict[str, Dict[str, int]] = cycle_stats.get(
                "scan_by_asset_timeframe", {}
            )
            if by_at:
                for asset in _REQUIRED_ASSETS:
                    if asset not in by_at:
                        result.add(AuditItem(
                            layer="UPSTREAM", phase="filter", asset=asset,
                            timeframe=None, severity=Severity.FAIL,
                            message=f"{asset} missing from scan_by_asset_timeframe — "
                                    "CT did not scan any markets for this asset.",
                        ))
                    else:
                        total = sum(by_at[asset].values())
                        sev = Severity.PASS if total > 0 else Severity.WARN
                        result.add(AuditItem(
                            layer="UPSTREAM", phase="filter", asset=asset,
                            timeframe=None, severity=sev,
                            message=f"Filter produced {total} candidate(s) for {asset}.",
                        ))

        # 1c. Check per-asset edge/kelly counts in cycle_stats.
        if cycle_stats:
            per_asset: Dict[str, Any] = cycle_stats.get("per_asset_stats", {})
            for asset in _REQUIRED_ASSETS:
                stats = per_asset.get(asset, {})
                candidates = stats.get("candidates_seen", None)
                if candidates is None:
                    result.add(AuditItem(
                        layer="UPSTREAM", phase="signals", asset=asset,
                        timeframe=None, severity=Severity.WARN,
                        message=f"No per-asset stats for {asset} in cycle_stats — "
                                "check that CT populates per_asset_stats.",
                    ))
                elif candidates == 0:
                    result.add(AuditItem(
                        layer="UPSTREAM", phase="signals", asset=asset,
                        timeframe=None, severity=Severity.WARN,
                        message=f"0 candidates seen for {asset} this cycle.",
                    ))
                else:
                    result.add(AuditItem(
                        layer="UPSTREAM", phase="signals", asset=asset,
                        timeframe=None, severity=Severity.PASS,
                        message=f"{candidates} candidate(s) seen for {asset}.",
                    ))

    # ── Layer 2: Core CT loop ────────────────────────────────────────────

    def _audit_core(
        self,
        result: AuditResult,
        cycle_stats: Optional[Dict[str, Any]],
    ) -> None:
        """Check ANALYZE→CONSENSUS→SIZE→EXECUTE per asset."""
        if not cycle_stats:
            return

        per_asset: Dict[str, Any] = cycle_stats.get("per_asset_stats", {})
        for asset in _REQUIRED_ASSETS:
            stats = per_asset.get(asset, {})
            if not stats:
                continue

            # ANALYZE: candidates with non-zero edge
            evaluated = stats.get("evaluated", 0)
            approved = stats.get("approved", 0)
            vetoed = stats.get("vetoed", 0)
            veto_reasons: Dict[str, int] = stats.get("veto_reasons", {})

            # Check if all candidates are vetoed by edge_too_low / kelly=0
            if evaluated > 0 and approved == 0:
                # Every candidate vetoed — surface the dominant reason.
                dominant_reason = (
                    max(veto_reasons, key=lambda k: veto_reasons[k])
                    if veto_reasons else "unknown"
                )
                result.add(AuditItem(
                    layer="CORE", phase="consensus", asset=asset,
                    timeframe=None, severity=Severity.WARN,
                    message=(
                        f"{asset}: {evaluated} evaluated, 0 approved. "
                        f"Dominant veto: {dominant_reason} "
                        f"(counts: {veto_reasons})"
                    ),
                ))
            elif approved > 0:
                result.add(AuditItem(
                    layer="CORE", phase="consensus", asset=asset,
                    timeframe=None, severity=Severity.PASS,
                    message=f"{asset}: {approved} intent(s) approved out of {evaluated} evaluated.",
                ))

            # SIZE: check for kelly=0 on all candidates
            kelly_zeros = stats.get("kelly_zero_count", 0)
            if kelly_zeros > 0 and evaluated > 0:
                frac = kelly_zeros / max(evaluated, 1)
                sev = Severity.WARN if frac < 1.0 else Severity.FAIL
                result.add(AuditItem(
                    layer="CORE", phase="sizing", asset=asset,
                    timeframe=None, severity=sev,
                    message=(
                        f"{asset}: Kelly=0 on {kelly_zeros}/{evaluated} candidates. "
                        "Check edge wiring and fee gate."
                    ),
                ))

            # EXECUTE: check approved_intent vs submitted counts
            approved_intent = stats.get("approved_orders_intent", 0)
            submitted = stats.get("orders_submitted", 0)
            blocked_risk = stats.get("orders_blocked_by_risk", 0)
            blocked_kill = stats.get("orders_blocked_by_kill_switch", 0)

            if approved_intent > 0 and submitted == 0 and blocked_risk == 0 and blocked_kill == 0:
                result.add(AuditItem(
                    layer="CORE", phase="execution", asset=asset,
                    timeframe=None, severity=Severity.FAIL,
                    message=(
                        f"{asset}: {approved_intent} approved intent(s) but 0 orders submitted "
                        "and no risk/kill-switch block — MISSING EXECUTION PATH."
                    ),
                ))
            elif approved_intent > 0:
                result.add(AuditItem(
                    layer="CORE", phase="execution", asset=asset,
                    timeframe=None, severity=Severity.PASS,
                    message=(
                        f"{asset}: intent={approved_intent} submitted={submitted} "
                        f"blocked_risk={blocked_risk} blocked_kill={blocked_kill}."
                    ),
                ))

    # ── Layer 3: Downstream ──────────────────────────────────────────────

    def _audit_downstream(
        self,
        result: AuditResult,
        state: Dict[str, Any],
    ) -> None:
        """Check fills, exposure, and bankroll invariant."""

        # 3a. Fill schema — each asset's fills must have asset, contracts, entry_price.
        fills: List[Dict[str, Any]] = state.get("recent_fills", [])
        for fill in fills:
            fill_asset = fill.get("asset", "")
            if not fill_asset:
                result.add(AuditItem(
                    layer="DOWNSTREAM", phase="fills", asset=None,
                    timeframe=None, severity=Severity.WARN,
                    message="Fill missing 'asset' field — reconciliation schema mismatch.",
                ))
            elif fill_asset not in set(_REQUIRED_ASSETS):
                result.add(AuditItem(
                    layer="DOWNSTREAM", phase="fills", asset=fill_asset,
                    timeframe=None, severity=Severity.WARN,
                    message=f"Fill for unknown asset '{fill_asset}' — check asset detection.",
                ))

        # 3b. Exposure per asset — check for unexplained deltas.
        exposure: Dict[str, float] = state.get("exposure_by_asset", {})
        for asset in _REQUIRED_ASSETS:
            exp = exposure.get(asset, 0.0)
            if exp < 0:
                result.add(AuditItem(
                    layer="DOWNSTREAM", phase="exposure", asset=asset,
                    timeframe=None, severity=Severity.FAIL,
                    message=f"{asset}: negative exposure {exp:.2f}¢ — double-count or sign error.",
                ))

        # 3c. Bankroll invariant delta — warn if delta exceeds threshold.
        bankroll_state: Dict[str, Any] = state.get("bankroll", {})
        if bankroll_state:
            delta = bankroll_state.get("delta_cents", 0)
            epsilon = bankroll_state.get("epsilon_cents", 500)
            if abs(delta) > epsilon:
                result.add(AuditItem(
                    layer="DOWNSTREAM", phase="bankroll", asset=None,
                    timeframe=None, severity=Severity.WARN,
                    message=(
                        f"Bankroll invariant delta={delta}¢ exceeds epsilon={epsilon}¢. "
                        "Check cash + portfolio + realized PnL components."
                    ),
                ))
            else:
                result.add(AuditItem(
                    layer="DOWNSTREAM", phase="bankroll", asset=None,
                    timeframe=None, severity=Severity.PASS,
                    message=f"Bankroll invariant delta={delta}¢ within epsilon={epsilon}¢.",
                ))

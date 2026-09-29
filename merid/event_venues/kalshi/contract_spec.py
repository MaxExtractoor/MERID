"""Per-contract settlement-rule and fee-schedule validation.

The production settlement model assumes one specific payoff: the arithmetic
mean of once-per-second CF Benchmarks RTI observations over the final 60
seconds of the market.  A market whose published rules describe anything else
(a trimmed mean, a terminal point value, a different window or cadence, or a
non-RTI reference) cannot be priced by that model — trading it manufactures
false edge.  The same applies to fees: the decision and router math assume the
quadratic fee schedule with multiplier 1.0, so a series that reports a
different fee model must not be traded on the assumed parameters.

This module is fail-closed on settlement semantics: absent or unrecognized
rules text, an unimplemented aggregation, or a non-RTI reference is a
rejection, not a warning.  Fee identity is fail-closed on *declared*
mismatches only: Kalshi does not publish ``fee_type``/``fee_multiplier``
on every market record, so absent fee metadata marks the schedule
*unverified* (``fee_verified=False``) rather than incompatible — the
per-fill fee audit comparing reported vs modeled fees remains the drift
detector in that posture.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.kalshi.contract_spec")

# The aggregation model implemented by
# merid.prediction.settlement_distribution.compute_settlement_distribution.
IMPLEMENTED_AGGREGATION = "mean_1s_rti_60s"
IMPLEMENTED_REFERENCE = "cf_benchmarks_rti"

# Fee schedules the codebase can express exactly: the quadratic parabolic
# formula (rate * C * P * (1-P) rounded up to 0.01c).  Anything else reported
# by the venue is untradeable until implemented.
_SUPPORTED_FEE_TYPES = frozenset({"quadratic", "quadratic_with_maker_fees"})
_EXPECTED_FEE_MULTIPLIER = 1.0

_CFB_MARKERS = (
    "cf benchmarks",
    "real-time index",
    "real time index",
)
_RTI_TOKEN = re.compile(r"\b[a-z]*rti\b", re.IGNORECASE)  # RTI, BRTI, ERTI, …
_MEAN_MARKER = re.compile(
    r"\b(average|arithmetic mean|mean of|time[- ]?weighted|equally[- ]weighted)\b",
    re.IGNORECASE,
)
# Trimming/exclusion language changes the payoff and is not implemented.
_TRIM_MARKER = re.compile(
    r"\b(trim|trimmed|exclud\w*|discard\w*|drop\w*|outlier\w*)\b",
    re.IGNORECASE,
)
_WINDOW_SECONDS = re.compile(r"(\d+)\s*(?:-\s*)?seconds?\b", re.IGNORECASE)
_WINDOW_MINUTE_WORDS = re.compile(
    r"\b(final|last|preceding|prior to expiration|expiration)\b.{0,40}\bminute\b|"
    r"\bminute\b.{0,40}\b(preced|prior|before|final|last)\b|"
    r"\bsixty\s+seconds\b",
    re.IGNORECASE,
)
_INTERVAL_MARKER = re.compile(
    r"\b(per[- ]second|every second|each second|once per second|"
    r"1[- ]second|one[- ]second|per[- ]second intervals?)\b",
    re.IGNORECASE,
)
_TERMINAL_MARKER = re.compile(
    r"\b(value|price|index)\s+(as reported )?(at|on|as of)\s+"
    r"(the )?(expiration|expiry|close|settlement)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContractSpecEvaluation:
    """Result of validating a market's contract metadata against the model."""

    ticker: str
    recognized: bool
    compatible: bool
    aggregation: str
    reference: str
    expected_sample_count: Optional[int]
    window_seconds: Optional[int]
    sample_interval_seconds: Optional[int]
    rules_sha256: Optional[str]
    fee_type: Optional[str]
    fee_multiplier: Optional[float]
    fee_verified: bool
    maker_fee_verified: bool
    reasons: Tuple[str, ...]


def _parse_rules(
    rules_primary: Optional[str], rules_secondary: Optional[str]
) -> Tuple[str, str, Optional[int], Optional[int], Optional[int], Tuple[str, ...]]:
    """Classify the settlement rule text.

    Returns (reference, aggregation, sample_count, window_seconds,
    interval_seconds, reasons).  ``aggregation`` is one of
    ``mean_1s_rti_60s`` (the only implemented model), ``mean_rti_window_unknown``
    (average stated but window not verifiable), ``mean_rti_other_window``,
    ``filtered_mean`` (trimmed/excluded observations — not implemented), or
    ``terminal_value`` / ``unrecognized``.
    """
    reasons = []
    text = " ".join(
        t for t in (rules_primary, rules_secondary) if isinstance(t, str)
    )
    if not text.strip():
        return "unrecognized", "unrecognized", None, None, None, ("rules_text_absent",)

    lowered = text.lower()
    window_s: Optional[int] = None

    reference = "unrecognized"
    if any(m in lowered for m in _CFB_MARKERS) or _RTI_TOKEN.search(lowered):
        reference = IMPLEMENTED_REFERENCE

    if _TRIM_MARKER.search(lowered):
        # Any exclusion/trimming language means the payoff is not the plain
        # arithmetic mean this codebase implements.  A false positive here
        # (e.g. a benign "excluding fees" clause) rejects the market — the safe
        # direction; a false negative would price a trimmed mean with a
        # plain-mean model and manufacture false edge.
        aggregation = "filtered_mean"
        reasons.append("aggregation_trimmed_or_filtered")
    elif _MEAN_MARKER.search(lowered):
        m = _WINDOW_SECONDS.search(lowered)
        if m:
            window_s = int(m.group(1))
        elif _WINDOW_MINUTE_WORDS.search(lowered):
            window_s = 60
        if window_s == 60:
            aggregation = IMPLEMENTED_AGGREGATION
        elif window_s is None:
            aggregation = "mean_rti_window_unknown"
            reasons.append("settlement_window_not_stated")
        else:
            aggregation = "mean_rti_other_window"
            reasons.append(f"settlement_window_{window_s}s")
    elif _TERMINAL_MARKER.search(lowered):
        aggregation = "terminal_value"
        reasons.append("aggregation_terminal_point_value")
    else:
        aggregation = "unrecognized"
        reasons.append("aggregation_unrecognized")

    interval_s: Optional[int] = 1 if _INTERVAL_MARKER.search(lowered) else None
    if interval_s is None and window_s == 60 and re.search(
        r"\b60\s+(?:rti\s+)?(?:prices?|samples?|observations?)\b", lowered
    ):
        # "At the last minute before expiration, 60 RTI prices are collected"
        # — 60 samples over a 60s window implies the 1s cadence the model
        # banks even though the text never says "per second".
        interval_s = 1
    if aggregation == IMPLEMENTED_AGGREGATION and interval_s is None:
        reasons.append("sample_interval_not_stated")

    sample_count: Optional[int] = None
    if aggregation == IMPLEMENTED_AGGREGATION:
        # The implemented model banks one observation per second over the
        # 60s window; the count follows from the window, not the text.
        sample_count = 60

    return reference, aggregation, sample_count, window_s, interval_s, tuple(reasons)


def evaluate_market_contract(
    raw_fields: Dict[str, Any],
    ticker: str,
    maker_entries_enabled: bool = False,
) -> ContractSpecEvaluation:
    """Validate a market's declared contract/fee metadata against the model.

    ``raw_fields`` should carry ``rules_primary``, ``rules_secondary``,
    ``resolution_source``, ``fee_type``, ``fee_multiplier`` and
    ``fee_waiver_expiration_time_ms`` from the venue market record.

    Fail closed: absent rules text, an unimplemented aggregation, or
    unverifiable fee identity all return ``compatible=False``.
    ``maker_fee_verified`` is False when maker entries are enabled but the
    market's fee_type does not confirm maker pricing applies — callers must
    then restrict to the taker lane rather than reject outright.
    """
    rules_primary = raw_fields.get("rules_primary")
    rules_secondary = raw_fields.get("rules_secondary")

    rules_blob = "|".join(t for t in (rules_primary, rules_secondary) if t)
    rules_sha256 = hashlib.sha256(rules_blob.encode("utf-8")).hexdigest() if rules_blob else None

    reference, aggregation, sample_count, window_s, interval_s, reasons = _parse_rules(
        rules_primary, rules_secondary
    )
    reasons = list(reasons)

    recognized = reference == IMPLEMENTED_REFERENCE and aggregation != "unrecognized"
    compatible = recognized and aggregation == IMPLEMENTED_AGGREGATION
    if reference != IMPLEMENTED_REFERENCE:
        reasons.append("settlement_reference_not_cfb_rti")
    if recognized and aggregation != IMPLEMENTED_AGGREGATION:
        reasons.append(f"aggregation_unsupported:{aggregation}")

    # ── Fee-schedule identity ────────────────────────────────────────────────
    fee_type = raw_fields.get("fee_type")
    fee_multiplier = raw_fields.get("fee_multiplier")
    try:
        fee_multiplier = float(fee_multiplier) if fee_multiplier is not None else None
    except (TypeError, ValueError):
        reasons.append("fee_multiplier_unparseable")
        fee_multiplier = None

    fee_verified = False
    if fee_type is None and fee_multiplier is None:
        # Kalshi does not publish fee identity on the market record for these
        # series, so absence is *unverified*, not a declared mismatch: the
        # configured quadratic/multiplier-1.0 schedule stays active and the
        # per-fill fee audit (reported vs modeled) remains the drift
        # detector.  A fee_type/fee_multiplier that IS declared and
        # mismatches stays fatal below.
        reasons.append("fee_metadata_unverified")
    else:
        if fee_type is not None and str(fee_type).lower() not in _SUPPORTED_FEE_TYPES:
            compatible = False
            reasons.append(f"fee_type_unsupported:{fee_type}")
        if fee_multiplier is not None and abs(fee_multiplier - _EXPECTED_FEE_MULTIPLIER) > 1e-9:
            compatible = False
            reasons.append(f"fee_multiplier_mismatch:{fee_multiplier}")
        if fee_type is None or fee_multiplier is None:
            # Partial metadata cannot prove the applied schedule.
            compatible = False
            reasons.append("fee_metadata_incomplete")
        else:
            fee_verified = True

    maker_fee_verified = True
    if maker_entries_enabled:
        maker_fee_verified = str(fee_type or "").lower() == "quadratic_with_maker_fees"
        if not maker_fee_verified:
            reasons.append(f"maker_fees_unverified:{fee_type}")

    return ContractSpecEvaluation(
        ticker=ticker,
        recognized=recognized,
        compatible=compatible,
        aggregation=aggregation,
        reference=reference,
        expected_sample_count=sample_count,
        window_seconds=window_s,
        sample_interval_seconds=interval_s,
        rules_sha256=rules_sha256,
        fee_type=str(fee_type) if fee_type is not None else None,
        fee_multiplier=fee_multiplier,
        fee_verified=fee_verified,
        maker_fee_verified=maker_fee_verified,
        reasons=tuple(reasons),
    )


def extract_market_contract_fields(*objects: Any) -> Dict[str, Any]:
    """Collect contract/fee fields wherever the ingestion pipeline left them.

    Sources checked, in order: an ``EventMarket``-like object's ``raw_data``
    dict, then direct attributes on the object itself (e.g. ``KalshiMarket``).
    Later objects fill only missing keys, so pass the most authoritative
    object first.
    """
    keys = (
        "rules_primary",
        "rules_secondary",
        "resolution_source",
        "fee_type",
        "fee_multiplier",
        "fee_waiver_expiration_time_ms",
    )
    out: Dict[str, Any] = {}
    for obj in objects:
        if obj is None:
            continue
        raw = getattr(obj, "raw_data", None)
        if isinstance(raw, dict):
            for k in keys:
                if k not in out and raw.get(k) is not None:
                    out[k] = raw[k]
        for k in keys:
            if k not in out:
                v = getattr(obj, k, None)
                if v is not None:
                    out[k] = v
    return out

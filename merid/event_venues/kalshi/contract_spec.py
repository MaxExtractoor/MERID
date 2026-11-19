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


# ── YES-proposition classification ──────────────────────────────────────────
#
# The settlement-aggregation check above verifies *how* the official value is
# computed; it says nothing about *which side of the reference wins YES*.  The
# decision model prices exactly one directional claim —
# ``P(close_window_mean > open_window_mean)`` for the 15m up/down contracts
# (equivalently ``P(settlement_measure > reference)`` for threshold markets):
# YES must pay when the settlement measure is greater than or equal to the
# reference.  A market whose YES pays on the complement (below / at most), on
# a two-sided range, or on wording this parser cannot classify must fail
# closed — trading it would price the inverted or mis-specified claim.
#
# Comparison families recognised in the YES-resolution clause:
#   ge  — "at least", "or above", "greater than or equal", "not less than", …
#   gt  — "above", "greater than", "over", "exceeds", "higher than", …
#   le  — "at most", "or below", "less than or equal", "not more than", …
#   lt  — "below", "less than", "under", "lower than", "fewer than", …
# Only ``ge`` and ``gt`` are compatible with the implemented model (``ge`` is
# conservative: the model's continuous P(>) omits the rounded-tie mass that
# also pays YES).  ``le``/``lt`` are the inverted claim, ``range``/directional
# language and unclassifiable wording are all rejected.

_YES_RESOLUTION_ANCHOR = re.compile(
    r"\b(?:resolv\w*|settles?|pays?)\s+(?:out\s+)?(?:to\s+)?[\"']?yes\b|"
    r"\byes\b\s+(?:wins|pays)\b",
    re.IGNORECASE,
)
_NO_RESOLUTION_ANCHOR = re.compile(
    r"\b(?:resolv\w*|settles?|pays?)\s+(?:out\s+)?(?:to\s+)?[\"']?no\b|"
    r"\bno\b\s+(?:wins|pays)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_CUT = re.compile(
    r"\b(?:otherwise|unless|if not|fails?\s+to|does\s+not|provided\s+that)\b",
    re.IGNORECASE,
)
_PROPOSITION_NOUN = re.compile(
    r"\b(?:average|mean|rti|index|price|value|level|strike|benchmark)\b",
    re.IGNORECASE,
)
# Directional (non-comparative) language describing the inverted claim.
_INVERTED_DIRECTION = re.compile(
    r"\b(?:decreas\w*|declin\w*|fall\w*|drop\w*|goes?\s+down|moves?\s+down|"
    r"trends?\s+down|shuts?\s+down|closes?\s+down)\b",
    re.IGNORECASE,
)
_PROPOSITION_RANGE = re.compile(r"\bbetween\b", re.IGNORECASE)
# "or above"/"or below" appearing together describes a two-sided range.
_OR_ABOVE = re.compile(r"\bor\s+above\b", re.IGNORECASE)
_OR_BELOW = re.compile(r"\bor\s+below\b", re.IGNORECASE)
# Negated comparisons are rewritten to explicit family sentinels before the
# bare-word detectors run, so "not below" cannot leak into the lt family.
_NEG_GE = re.compile(
    r"\bnot\s+(?:less\s+than|below|lower\s+than|fewer\s+than)\b|"
    r"\bno\s+(?:less|fewer)\s+than\b",
    re.IGNORECASE,
)
_NEG_LE = re.compile(
    r"\bnot\s+(?:more\s+than|above|over|greater\s+than|higher\s+than|"
    r"exceeds?|exceeding)\b|\bno\s+more\s+than\b",
    re.IGNORECASE,
)
_CMP_GE = re.compile(
    r"\bat\s+least\b|\bor\s+above\b|\bat\s+or\s+above\b|"
    r"\babove\s+or\s+equal\b|\bequal\s+to\s+or\s+(?:greater|more|above|higher)\b|"
    r"\bgreater\s+than\s+or\s+equal\b|\bminimum\s+of\b|\b__GE__\b",
    re.IGNORECASE,
)
_CMP_LE = re.compile(
    r"\bat\s+most\b|\bor\s+below\b|\bat\s+or\s+below\b|"
    r"\bbelow\s+or\s+equal\b|\bless\s+than\s+or\s+equal\b|"
    r"\bequal\s+to\s+or\s+(?:less|fewer|below|lower)\b|\bmaximum\s+of\b|"
    r"\b__LE__\b",
    re.IGNORECASE,
)
_CMP_GT = re.compile(
    r"\bgreater\s+than\b(?!\s+or\s+equal)|\bmore\s+than\b(?!\s+or\s+equal)|"
    r"\babove\b(?!\s+or\s+equal)|\bover\b(?!\s+or\s+equal)|"
    r"\bexceeds?\b|\bexceeding\b|\bhigher\s+than\b",
    re.IGNORECASE,
)
_CMP_LT = re.compile(
    r"\bless\s+than\b(?!\s+or\s+equal)|\bbelow\b(?!\s+or\s+equal)|"
    r"\bunder\b|\blower\s+than\b|\bfewer\s+than\b",
    re.IGNORECASE,
)


def _yes_condition_texts(
    rules_primary: Optional[str], rules_secondary: Optional[str]
) -> list:
    """Extract the condition text governing each 'resolves to Yes' clause.

    Handles both phrasings — 'If <cond>, then the market resolves to Yes' and
    'the market resolves to Yes if <cond>' — by removing the anchor itself and
    any trailing 'resolves to No'/otherwise clause, rather than depending on
    clause order.
    """
    texts = []
    for raw_text in (rules_primary, rules_secondary):
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        for sent in _SENTENCE_SPLIT.split(raw_text):
            if not _YES_RESOLUTION_ANCHOR.search(sent):
                continue
            cond = _YES_RESOLUTION_ANCHOR.sub(" ", sent)
            cond = _NO_RESOLUTION_ANCHOR.split(cond)[0]
            cond = _CLAUSE_CUT.split(cond)[0]
            cond = re.sub(
                r"^(?:if|when|in\s+the\s+event\s+that|once|after|should|where)\s+",
                "",
                cond.strip(),
                flags=re.IGNORECASE,
            )
            cond = re.sub(
                r"\bthen\s+the\s+market\s*$", "", cond, flags=re.IGNORECASE
            )
            cond = cond.strip(" ,;:")
            if cond:
                texts.append(cond)
    return texts


def _classify_condition(cond: str) -> Tuple[frozenset, Tuple[str, ...]]:
    """Classify one YES-condition text into the set of comparison families it
    contains, plus the raw detector flags for audit reasons."""
    flags = []
    if _INVERTED_DIRECTION.search(cond):
        flags.append("inverted_dir")
    if _PROPOSITION_RANGE.search(cond) or (
        _OR_ABOVE.search(cond) and _OR_BELOW.search(cond)
    ):
        flags.append("range")

    masked = _NEG_GE.sub(" __GE__ ", cond)
    masked = _NEG_LE.sub(" __LE__ ", masked)
    # Compound families are masked out before the bare-word detectors run
    # so "equal to or above" cannot double-count as both ge and gt.
    remaining = masked
    for family, pattern in (
        ("ge", _CMP_GE),
        ("le", _CMP_LE),
        ("gt", _CMP_GT),
        ("lt", _CMP_LT),
    ):
        if pattern.search(remaining):
            flags.append(family)
            remaining = pattern.sub(" ", remaining)
    return frozenset(flags), tuple(flags)


def _classify_proposition(
    condition_texts: list,
) -> Tuple[str, Optional[str], Tuple[str, ...]]:
    """Reduce YES-condition texts to a single proposition verdict.

    Returns (proposition, comparison, reasons).  ``proposition`` is one of
    ``reference_ge`` / ``reference_gt`` (implemented), ``reference_le`` /
    ``reference_lt`` (inverted), ``range_or_bracket``, ``directional_inverted``,
    or ``unrecognized``.  Every extracted YES clause must classify to the same
    single comparison family — any disagreement, unclassifiable clause, or
    missing price/index operand fails closed.
    """
    reasons = []
    if not condition_texts:
        return "unrecognized", None, ("proposition_clause_absent",)

    families = set()
    saw_unclassifiable = False
    saw_nonprice_operands = False
    for cond in condition_texts:
        cond_families, flags = _classify_condition(cond)
        reasons.extend(f"proposition_flag:{f}" for f in flags)
        if not cond_families:
            saw_unclassifiable = True
            continue
        families.update(cond_families)
        if (
            cond_families & {"ge", "gt", "le", "lt"}
            and not _PROPOSITION_NOUN.search(cond)
        ):
            # A comparison with no price/index/average operand cannot be the
            # settlement proposition (e.g. 'if the committee is at least quorate').
            saw_nonprice_operands = True

    if saw_unclassifiable:
        reasons.append("proposition_clause_unclassifiable")
    if saw_nonprice_operands:
        reasons.append("proposition_operands_unverified")

    if len(families) != 1:
        if families:
            reasons.append("proposition_contradictory:" + "+".join(sorted(families)))
        return "unrecognized", None, tuple(reasons)

    family = next(iter(families))
    if saw_unclassifiable or saw_nonprice_operands:
        return "unrecognized", None, tuple(reasons)

    mapping = {
        "ge": ("reference_ge", "ge"),
        "gt": ("reference_gt", "gt"),
        "le": ("reference_le", "le"),
        "lt": ("reference_lt", "lt"),
        "range": ("range_or_bracket", None),
        "inverted_dir": ("directional_inverted", None),
    }
    proposition, comparison = mapping[family]
    if proposition in ("reference_le", "reference_lt"):
        reasons.append(f"proposition_inverted:{family}")
    elif proposition == "range_or_bracket":
        reasons.append("proposition_range_or_bracket")
    elif proposition == "directional_inverted":
        reasons.append("proposition_directional_inverted")
    return proposition, comparison, tuple(reasons)


_PROPOSITION_COMPATIBLE = frozenset({"reference_ge", "reference_gt"})
_PROPOSITION_RANGE_STRIKE_TYPES = frozenset({"range", "bracket", "between"})


def _proposition_from_strike_metadata(raw_fields: Dict[str, Any]) -> Optional[str]:
    """Detect range/bracket markets from structured strike fields.

    Returns ``"range_or_bracket"`` when a cap strike or a range/bracket
    strike_type is declared, else None.  ``floor_strike``/``strike_price``
    alone are the expected single-reference fields for up/down and threshold
    markets and do not trigger this.
    """
    cap = raw_fields.get("cap_strike")
    custom = raw_fields.get("custom_strike")
    if cap is None and isinstance(custom, dict):
        cap = custom.get("cap_strike")
    if cap is not None:
        return "range_or_bracket"
    strike_type = str(raw_fields.get("strike_type") or "").strip().lower()
    if strike_type in _PROPOSITION_RANGE_STRIKE_TYPES:
        return "range_or_bracket"
    return None


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
    proposition: str = "unrecognized"
    proposition_comparison: Optional[str] = None


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

    proposition, proposition_comparison, prop_reasons = _classify_proposition(
        _yes_condition_texts(rules_primary, rules_secondary)
    )
    reasons.extend(prop_reasons)

    if _proposition_from_strike_metadata(raw_fields) is not None:
        if proposition in _PROPOSITION_COMPATIBLE:
            reasons.append("proposition_metadata_contradiction")
        else:
            reasons.append("proposition_range_bracket")
        proposition = "range_or_bracket"
        proposition_comparison = None

    recognized = reference == IMPLEMENTED_REFERENCE and aggregation != "unrecognized"
    compatible = (
        recognized
        and aggregation == IMPLEMENTED_AGGREGATION
        and proposition in _PROPOSITION_COMPATIBLE
    )
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

    # Maker-lane verification asks whether the declared schedule bounds maker
    # cost at/below the modeled 0.0175*P*(1-P) rate — not whether makers pay.
    #   quadratic                    -> makers pay 0        (model is an upper bound)
    #   quadratic_with_maker_fees    -> makers pay 0.0175   (model is exact)
    # A declared fee_type is required either way: absent metadata cannot prove
    # the schedule, and an unsupported type has already failed `compatible`.
    maker_fee_verified = True
    if maker_entries_enabled:
        maker_fee_verified = str(fee_type or "").lower() in _SUPPORTED_FEE_TYPES
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
        proposition=proposition,
        proposition_comparison=proposition_comparison,
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
        "floor_strike",
        "cap_strike",
        "strike_price",
        "custom_strike",
        "strike_type",
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

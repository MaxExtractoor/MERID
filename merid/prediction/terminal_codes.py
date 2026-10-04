"""Canonical terminal-code taxonomy for 15m decision outcomes.

Every asset (BTC, ETH, SOL, XRP, DOGE) resolves to exactly one terminal code
per cycle through a single precedence order.  Raw rejection reasons are always
retained alongside the canonical code — the code answers "which gate first
stopped this asset", the raw reason preserves the producer's detail.

Precedence (first true blocker wins):
    MARKET_UNAVAILABLE      market not discovered / closed / settled
    TTE_ENTRY_CUTOFF        inside the per-band min-TTE exclusion
    BOOK_NOT_TRUSTED        book integrity / freshness / sequence / confidence
    SPOT_NOT_TRUSTED        spot/RTI reference unusable or warmup incomplete
    SIDE_NOT_LIQUID         no tradeable side has executable depth
    NO_ELIGIBLE_PRICE_BAND  no side sits inside an enabled price band
    NO_POSITIVE_EXECUTABLE_EDGE   both sides evaluated; neither has +EV
    EVIDENCE_HARD_BLOCK     dense matched toxic cell / evidence veto after
                            economics cleared (hard blocks only — soft or
                            sparse insufficiency is an edge-threshold failure)
    EDGE_BELOW_DYNAMIC_THRESHOLD  positive EV but below the dynamic required
                            edge (includes soft-penalty/challenge elevated
                            reserves the model edge could not clear)
    LOW_CONVICTION          economics cleared but |p_sel - 0.5| < the
                            per-asset conviction floor — a structural risk
                            veto, not an economics failure
    ALLOCATION_NOT_SELECTED candidate qualified but the top-3 allocator passed
    ENTRY_LIFECYCLE_INVALID missing protective exit / lifecycle invalid
    EXECUTION_REJECT        stale decision, passivity, or venue reject
    CANDIDATE_EMITTED       survived every gate

Compatibility members (MODEL_UNAVAILABLE, RISK_OR_ALLOCATION_REJECT,
UNCLASSIFIED) remain for states the canonical set cannot express; the
resolver only returns them when no canonical code applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TerminalCode(str, Enum):
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    TTE_ENTRY_CUTOFF = "TTE_ENTRY_CUTOFF"
    BOOK_NOT_TRUSTED = "BOOK_NOT_TRUSTED"
    SPOT_NOT_TRUSTED = "SPOT_NOT_TRUSTED"
    SIDE_NOT_LIQUID = "SIDE_NOT_LIQUID"
    NO_ELIGIBLE_PRICE_BAND = "NO_ELIGIBLE_PRICE_BAND"
    NO_POSITIVE_EXECUTABLE_EDGE = "NO_POSITIVE_EXECUTABLE_EDGE"
    EVIDENCE_HARD_BLOCK = "EVIDENCE_HARD_BLOCK"
    EDGE_BELOW_DYNAMIC_THRESHOLD = "EDGE_BELOW_DYNAMIC_THRESHOLD"
    LOW_CONVICTION = "LOW_CONVICTION"
    ALLOCATION_NOT_SELECTED = "ALLOCATION_NOT_SELECTED"
    ENTRY_LIFECYCLE_INVALID = "ENTRY_LIFECYCLE_INVALID"
    EXECUTION_REJECT = "EXECUTION_REJECT"
    CANDIDATE_EMITTED = "CANDIDATE_EMITTED"
    # Non-canonical compatibility codes — still emitted when the state cannot
    # be expressed in the canonical set (e.g. a model exception, a risk halt).
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    RISK_OR_ALLOCATION_REJECT = "RISK_OR_ALLOCATION_REJECT"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class DecisionSignals:
    """Normalized inputs to :func:`resolve_terminal_code`.

    Producers that already evaluated the structured pipeline can resolve the
    terminal state directly instead of round-tripping through reason strings.
    """

    market_available: bool = True
    tte_seconds: Optional[float] = None
    min_entry_tte_seconds: Optional[float] = None
    book_trusted: bool = True
    spot_trusted: bool = True
    any_side_has_real_liquidity: bool = True
    any_side_in_price_band: bool = True
    any_eligible_side_has_positive_net_ev: bool = False
    selected_side_evidence_hard_block: bool = False
    selected_side_clears_dynamic_threshold: bool = False
    selected_side_clears_conviction: bool = True
    allocator_selected: bool = False


def resolve_terminal_code(state: DecisionSignals) -> TerminalCode:
    """Resolve the single terminal state under the shared precedence rule."""
    if not state.market_available:
        return TerminalCode.MARKET_UNAVAILABLE
    if (
        state.tte_seconds is not None
        and state.min_entry_tte_seconds is not None
        and state.tte_seconds < state.min_entry_tte_seconds
    ):
        return TerminalCode.TTE_ENTRY_CUTOFF
    if not state.book_trusted:
        return TerminalCode.BOOK_NOT_TRUSTED
    if not state.spot_trusted:
        return TerminalCode.SPOT_NOT_TRUSTED
    if not state.any_side_has_real_liquidity:
        return TerminalCode.SIDE_NOT_LIQUID
    if not state.any_side_in_price_band:
        return TerminalCode.NO_ELIGIBLE_PRICE_BAND
    if not state.any_eligible_side_has_positive_net_ev:
        return TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE
    if state.selected_side_evidence_hard_block:
        return TerminalCode.EVIDENCE_HARD_BLOCK
    if not state.selected_side_clears_dynamic_threshold:
        return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD
    if not state.selected_side_clears_conviction:
        return TerminalCode.LOW_CONVICTION
    if not state.allocator_selected:
        return TerminalCode.ALLOCATION_NOT_SELECTED
    return TerminalCode.CANDIDATE_EMITTED


# Raw reason -> canonical terminal code.  Single precedence-ordered cascade:
# every producer reason string funnels through here so no module invents its
# own terminal vocabulary.
def canonical_terminal_code(
    rejection_reason: str,
    best_ev_cents: Optional[float] = None,
    *,
    regime_reject_cause: Optional[str] = None,
    candidate_present: bool = False,
) -> str:
    """Map a raw rejection reason to its canonical :class:`TerminalCode` value."""
    rl = (rejection_reason or "").strip().lower()

    if "lifecycle" in rl or "no_trade_without_exit" in rl:
        return TerminalCode.ENTRY_LIFECYCLE_INVALID.value

    if (
        "tte_entry_cutoff" in rl
        or rl.startswith("min_tte")
        or rl.startswith("final_minute")
        or "time_to_expiry" in rl
    ):
        return TerminalCode.TTE_ENTRY_CUTOFF.value

    if "price_band_both_sides_disabled" in rl:
        # The regime reject is conflated: a side still in-band without the
        # time bound means the window closed, not that price is out of range.
        if regime_reject_cause == "tte_floor":
            return TerminalCode.TTE_ENTRY_CUTOFF.value
        return TerminalCode.NO_ELIGIBLE_PRICE_BAND.value
    if "both_sides_disabled_regime" in rl or "price_band" in rl or "final_price_out_of_range" in rl:
        if regime_reject_cause == "tte_floor":
            return TerminalCode.TTE_ENTRY_CUTOFF.value
        return TerminalCode.NO_ELIGIBLE_PRICE_BAND.value

    if rl == "skip_market_not_ready":
        return TerminalCode.BOOK_NOT_TRUSTED.value
    if rl == "invalid_confidence":
        # The confidence engine fail-closes on untrusted book/spot inputs;
        # semantically a data-integrity rejection, not an edge rejection.
        return TerminalCode.BOOK_NOT_TRUSTED.value

    # Evidence families.  Soft/sparse/challenge "insufficient" codes mean the
    # model's net edge could not clear the *elevated* reserve — an
    # edge-threshold failure, not an evidence veto.  Note the production
    # reason stems drop the word "insufficient" for the sparse lane
    # (``evidence_sparse_matched_{side}`` is SPARSE_MATCHED_INSUFFICIENT).
    _evidence_soft = (
        "soft_penalty_insufficient",
        "challenge_insufficient",
        "sparse_matched",
        "evidence_empty_insufficient",
    )
    if any(s in rl for s in _evidence_soft):
        return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
    if "evidence_toxic_cell" in rl or "evidence_cell_insufficient" in rl:
        return TerminalCode.EVIDENCE_HARD_BLOCK.value
    if "evidence_escape_cap" in rl or "evidence_escape_disabled" in rl:
        # Escape-lane exhaustion blocks the bounded lane specifically; treat
        # as an evidence hard block so capacity issues stay visible.
        return TerminalCode.EVIDENCE_HARD_BLOCK.value
    if (
        rl.startswith("calibration_evidence")
        or rl.startswith("live_evidence")
        or rl.startswith("evidence_")
        or rl.startswith("market_fade_blocked")
    ):
        return TerminalCode.EVIDENCE_HARD_BLOCK.value

    if "insufficient_depth" in rl or rl.startswith("fill_or_depth"):
        return TerminalCode.SIDE_NOT_LIQUID.value

    if (
        rl.startswith("cost_basis_override")
        or rl == "directional_tie"
        or rl == "ev_gate_non_positive"
        or rl.startswith("no_positive_executable_edge")
    ):
        return TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE.value
    # 2026-10-04: bounded-lane floor miss — the lane's configured (possibly
    # negative) floor IS the dynamic required edge for that side, so a miss
    # canonicalizes to the same threshold code rather than an EV label.
    if "edge_below_lane_floor" in rl:
        return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value

    # 2026-10-04: structural conviction veto — the candidate cleared its
    # economics (lane floor or positive edge) but |p_sel - 0.5| fell below
    # the per-asset conviction floor.  Dedicated canonical code so funnel
    # aggregation does not have to parse raw reason strings; previously the
    # economics fallback relabelled these as EV failures.
    if rl.startswith("low_conviction"):
        return TerminalCode.LOW_CONVICTION.value

    if "edge_below_threshold" in rl or rl in (
        "insufficient_edge",
        "ev_extreme_price",
        "kelly_filter",
    ):
        if best_ev_cents is not None and best_ev_cents <= 0.0:
            return TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE.value
        return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value

    if rl.startswith("exception") or "model_unavailable" in rl:
        return TerminalCode.MODEL_UNAVAILABLE.value

    # Execution-coherence rejects (decision-age deadline, pre-submit strict
    # passivity, post-only repricing) — quote-to-submit failures, distinct
    # from strategy-edge rejects.
    if rl.startswith("stale_decision"):
        return TerminalCode.EXECUTION_REJECT.value
    if (
        rl.startswith("pre_submit_passivity")
        or rl.startswith("post_only_passivity")
        or rl.startswith("post_only_no_passive_price")
        or "post only cross" in rl
    ):
        return TerminalCode.EXECUTION_REJECT.value

    if rl in ("allocator_not_selected", "allocator_loss"):
        return TerminalCode.ALLOCATION_NOT_SELECTED.value
    if (
        rl.startswith("cooldown")
        or "session" in rl
        or "consecutive" in rl
        or "knapsack" in rl
        or rl.startswith("allocator")
        or "risk" in rl
    ):
        return TerminalCode.RISK_OR_ALLOCATION_REJECT.value
    if candidate_present:
        return TerminalCode.RISK_OR_ALLOCATION_REJECT.value

    # Evaluated-economics fallback (2026-09-30): when per-side net EVs were
    # computed, the record must never end at UNCLASSIFIED/MODEL_UNAVAILABLE —
    # the honest first economic blocker is that no side had positive
    # executable edge, or that the best side's positive edge still could not
    # clear its dynamic threshold.  Unknown reasons WITHOUT economics still
    # resolve to the compatibility codes.
    if not rl:
        if best_ev_cents is not None:
            if best_ev_cents <= 0.0:
                return TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE.value
            return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
        return TerminalCode.MODEL_UNAVAILABLE.value
    if best_ev_cents is not None:
        if best_ev_cents <= 0.0:
            return TerminalCode.NO_POSITIVE_EXECUTABLE_EDGE.value
        return TerminalCode.EDGE_BELOW_DYNAMIC_THRESHOLD.value
    return TerminalCode.UNCLASSIFIED.value

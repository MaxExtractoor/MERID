"""
Pure multi-condition exit evaluator.

Provides a decision-complete, side-aware evaluation of every exit condition for a
single position / snapshot pair.  The evaluator is stateless: it reads Position
and ExitPriceSnapshot state and returns immutable ExitCondition records.  The
caller (PositionMonitor) owns state transitions and emission.

This is the single place where the exit-precedence calculation is encoded for
audit records.  The actual exit trigger still flows through PositionMonitor, but
this module supplies the ``eligible_exit_reasons`` / ``suppressed_exit_reasons``
evidence.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from merid.position_management.exit_audit import ExitPriceSnapshot
from merid.position_management.exit_decision import get_priority_for_reason
from merid.position_management.exit_policy import ExitAction, ExitReason
from merid.position_management.position import Position, PositionSide, TrailingState, TrailingType


# Default timing / confirmation constants (overridable by caller)
DEFAULT_SOFT_STOP_MIN_OBSERVATIONS = int(os.getenv("MERID_SOFT_STOP_MIN_OBSERVATIONS", "2"))
DEFAULT_HARD_STOP_EXTRA_BUFFER_CENTS = int(os.getenv("MERID_HARD_STOP_EXTRA_BUFFER_CENTS", "1"))
DEFAULT_MIN_EDGE_DECAY_HOLD_SECONDS = float(os.getenv("MERID_MIN_EDGE_DECAY_HOLD_SECONDS", "30.0"))
DEFAULT_MIN_EXIT_HOLD_SECONDS = float(os.getenv("MERID_MIN_EXIT_HOLD_SECONDS", "2.0"))
DEFAULT_EXIT_PRICE_MAX_AGE_MS = float(os.getenv("MERID_EXIT_PRICE_MAX_AGE_MS", "10000.0"))
DEFAULT_TRAILING_ACTIVATION_DELAY_SEC = 30.0
DEFAULT_TRAILING_MIN_PROFIT_CENTS = 12
DEFAULT_TRAILING_PROFIT_ZONE_CENTS = 80
DEFAULT_TIME_STOP_R_THRESHOLD = 0.5


@dataclass(frozen=True)
class ExitCondition:
    """
    Immutable record for one evaluated exit condition.

    - ``reason``: the exit reason under evaluation
    - ``eligible``: True when the condition is met in this snapshot
    - ``priority``: higher = higher priority (from exit_decision)
    - ``evidence``: free-form dict with the precise values that decided eligibility
    """

    reason: ExitReason
    eligible: bool
    priority: int
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitEvaluation:
    """Result of evaluating all exit conditions for one snapshot."""

    conditions: List[ExitCondition]
    chosen: Optional[ExitCondition]
    eligible: List[ExitCondition]
    suppressed: List[ExitCondition]


def _is_snapshot_executable(snapshot: Optional[ExitPriceSnapshot]) -> bool:
    """Return True only when the snapshot is trusted for an exit decision."""
    if snapshot is None:
        return False
    return (
        snapshot.is_fresh(DEFAULT_EXIT_PRICE_MAX_AGE_MS)
        and snapshot.is_executable_for_exit()
        and snapshot.data_quality == "GOOD"
    )


def _snapshot_ineligibility_reason(snapshot: Optional[ExitPriceSnapshot]) -> str:
    if snapshot is None:
        return "missing_snapshot"
    if not snapshot.is_fresh(DEFAULT_EXIT_PRICE_MAX_AGE_MS):
        return f"stale_book_age_ms={snapshot.book_age_ms}"
    if not snapshot.has_bid_size:
        return "missing_bid_size"
    if not snapshot.executable:
        return "not_executable"
    if not (0 < snapshot.own_side_bid_cents < 100 and 0 < snapshot.own_side_ask_cents < 100):
        return f"invalid_prices_bid={snapshot.own_side_bid_cents}_ask={snapshot.own_side_ask_cents}"
    if snapshot.data_quality != "GOOD":
        return f"data_quality={snapshot.data_quality}"
    return "unknown"


def _hard_stop_price_cents(position: Position, hard_stop_extra_buffer_cents: int) -> Optional[int]:
    if position.stop_loss_price_cents is None:
        return None
    return position.stop_loss_price_cents - hard_stop_extra_buffer_cents


def _stop_loss_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
    soft_stop_min_observations: int,
    hard_stop_extra_buffer_cents: int,
) -> ExitCondition:
    """Evaluate stop-loss (hard / soft) condition.

    The legacy exit is disabled: even when the predicate would be eligible, the
    returned condition is ``eligible=False`` and is converted to a
    ``StopCandidate`` by the position monitor before any submission.
    """
    hard_price = _hard_stop_price_cents(position, hard_stop_extra_buffer_cents)
    evidence: Dict[str, Any] = {
        "stop_loss_price_cents": position.stop_loss_price_cents,
        "hard_stop_price_cents": hard_price,
        "current_price_cents": current_price_cents,
        "soft_stop_observations_before": position.soft_stop_observations,
        "soft_stop_min_observations": soft_stop_min_observations,
        "snapshot_executable": _is_snapshot_executable(snapshot),
    }

    if snapshot is not None:
        evidence["snapshot_book_age_ms"] = snapshot.book_age_ms
        evidence["snapshot_data_source"] = snapshot.data_source
        evidence["snapshot_data_quality"] = snapshot.data_quality

    if not getattr(position, "stop_loss_enabled", True) or position.stop_loss_price_cents is None:
        return ExitCondition(
            reason=ExitReason.STOP_LOSS,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
            evidence={**evidence, "ineligible_reason": "no_stop_loss_set"},
        )

    if not _is_snapshot_executable(snapshot):
        return ExitCondition(
            reason=ExitReason.STOP_LOSS,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
            evidence={
                **evidence,
                "ineligible_reason": _snapshot_ineligibility_reason(snapshot),
            },
        )

    # Hard stop: bid far below the configured stop (catastrophic move)
    if hard_price is not None and current_price_cents <= hard_price:
        return ExitCondition(
            reason=ExitReason.STOP_LOSS,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
            evidence={
                **evidence,
                "trigger_kind": "hard",
                "soft_stop_observations_after": position.soft_stop_observations + 1,
                "stop_path_disabled": True,
            },
        )

    # Soft stop: bid at or below the configured stop, requires confirmation
    if current_price_cents <= position.stop_loss_price_cents:
        new_obs = position.soft_stop_observations + 1
        if new_obs >= soft_stop_min_observations:
            return ExitCondition(
                reason=ExitReason.STOP_LOSS,
                eligible=False,
                priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
                evidence={
                    **evidence,
                    "trigger_kind": "soft",
                    "soft_stop_observations_after": new_obs,
                    "stop_path_disabled": True,
                },
            )
        return ExitCondition(
            reason=ExitReason.STOP_LOSS,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
            evidence={
                **evidence,
                "trigger_kind": "soft-pending",
                "soft_stop_observations_after": new_obs,
                "soft_observations_needed": soft_stop_min_observations - new_obs,
            },
        )

    # Price recovered above the stop
    if position.soft_stop_observations > 0:
        return ExitCondition(
            reason=ExitReason.STOP_LOSS,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
            evidence={
                **evidence,
                "trigger_kind": "none",
                "action": "reset_soft_observations",
                "soft_stop_observations_after": 0,
            },
        )

    return ExitCondition(
        reason=ExitReason.STOP_LOSS,
        eligible=False,
        priority=get_priority_for_reason(ExitReason.STOP_LOSS).value,
        evidence={**evidence, "trigger_kind": "none", "action": "none"},
    )


def _take_profit_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "take_profit_price_cents": position.take_profit_price_cents,
        "current_price_cents": current_price_cents,
        "snapshot_executable": _is_snapshot_executable(snapshot),
    }
    if snapshot is not None:
        evidence["snapshot_data_source"] = snapshot.data_source

    if position.take_profit_price_cents is None:
        return ExitCondition(
            reason=ExitReason.TAKE_PROFIT,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TAKE_PROFIT).value,
            evidence={**evidence, "ineligible_reason": "no_take_profit_set"},
        )

    if not _is_snapshot_executable(snapshot):
        return ExitCondition(
            reason=ExitReason.TAKE_PROFIT,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TAKE_PROFIT).value,
            evidence={**evidence, "ineligible_reason": _snapshot_ineligibility_reason(snapshot)},
        )

    eligible = current_price_cents >= position.take_profit_price_cents
    evidence["distance_to_tp_cents"] = position.take_profit_price_cents - current_price_cents
    return ExitCondition(
        reason=ExitReason.TAKE_PROFIT,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.TAKE_PROFIT).value,
        evidence=evidence,
    )


def _auto_exit_99c_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
    seconds_to_expiry: Optional[float],
) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "current_price_cents": current_price_cents,
        "own_side_bid_cents": snapshot.own_side_bid_cents if snapshot else None,
        "seconds_to_expiry": seconds_to_expiry,
    }

    check_price = current_price_cents
    if snapshot is not None and snapshot.own_side_bid_cents is not None:
        check_price = snapshot.own_side_bid_cents

    eligible = check_price >= 99
    evidence["check_price"] = check_price
    evidence["threshold"] = 99
    return ExitCondition(
        reason=ExitReason.AUTO_EXIT_99C,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.AUTO_EXIT_99C).value,
        evidence=evidence,
    )


def _trailing_config(position: Position) -> Tuple[int, int, float]:
    """Return (min_profit_cents, profit_zone_cents, activation_delay_sec) from profile or defaults."""
    min_profit_cents = DEFAULT_TRAILING_MIN_PROFIT_CENTS
    profit_zone_cents = DEFAULT_TRAILING_PROFIT_ZONE_CENTS
    activation_delay_sec = DEFAULT_TRAILING_ACTIVATION_DELAY_SEC
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            min_profit_cents = profile.trailing_stop_min_profit_cents
            profit_zone_cents = profile.trailing_stop_profit_zone_activation_cents
            activation_delay_sec = profile.trailing_stop_activation_delay_sec
    except Exception:
        pass
    return min_profit_cents, profit_zone_cents, activation_delay_sec


def _trailing_distance_cents(position: Position) -> Optional[int]:
    """Return the trailing give-back distance in cents for the current position."""
    if position.trailing_type == TrailingType.NONE:
        return None
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            if position.trailing_profit_zone_activated:
                return profile.trailing_stop_trailing_distance_cents_profit_zone
            return profile.trailing_stop_trailing_distance_cents
    except Exception:
        pass
    if position.trailing_type == TrailingType.FIXED_CENTS:
        return int(position.trailing_param)
    return None


def _trail_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
    now: float,
) -> ExitCondition:
    """Evaluate trailing-stop condition with arming delay and watermark guards."""
    evidence: Dict[str, Any] = {
        "trailing_type": position.trailing_type.value,
        "trailing_param": position.trailing_param,
        "trailing_state": position.trailing_state.value,
        "current_price_cents": current_price_cents,
        "avg_entry_price_cents": position.avg_entry_price_cents,
        "max_favorable_price_cents": position.max_favorable_price_cents,
        "high_watermark_cents": position.high_watermark_cents,
        "trail_armed_at": position.trail_armed_at,
        "trail_started_at": position.trail_started_at,
        "snapshot_executable": _is_snapshot_executable(snapshot),
    }

    if position.trailing_type == TrailingType.NONE:
        return ExitCondition(
            reason=ExitReason.TRAIL,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TRAIL).value,
            evidence={**evidence, "ineligible_reason": "trailing_not_enabled"},
        )

    min_profit_cents, profit_zone_cents, activation_delay_sec = _trailing_config(position)
    profit_cents = current_price_cents - position.avg_entry_price_cents
    evidence["min_profit_cents"] = min_profit_cents
    evidence["profit_cents"] = profit_cents
    evidence["activation_delay_sec"] = activation_delay_sec
    evidence["trail_armed_at"] = position.trail_armed_at
    evidence["trail_started_at"] = position.trail_started_at

    # Cannot arm and trigger on the same observation.
    if position.trailing_state == TrailingState.UNARMED:
        if profit_cents >= min_profit_cents:
            return ExitCondition(
                reason=ExitReason.TRAIL,
                eligible=False,
                priority=get_priority_for_reason(ExitReason.TRAIL).value,
                evidence={
                    **evidence,
                    "ineligible_reason": "arming",
                    "next_state": "ARMED",
                    "arm_profit_threshold_cents": min_profit_cents,
                },
            )
        return ExitCondition(
            reason=ExitReason.TRAIL,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TRAIL).value,
            evidence={**evidence, "ineligible_reason": "profit_below_arm_threshold"},
        )

    if position.trailing_state == TrailingState.ARMED:
        if position.trail_armed_at is None:
            return ExitCondition(
                reason=ExitReason.TRAIL,
                eligible=False,
                priority=get_priority_for_reason(ExitReason.TRAIL).value,
                evidence={**evidence, "ineligible_reason": "missing_arm_timestamp"},
            )
        elapsed = now - position.trail_armed_at
        if elapsed < activation_delay_sec:
            return ExitCondition(
                reason=ExitReason.TRAIL,
                eligible=False,
                priority=get_priority_for_reason(ExitReason.TRAIL).value,
                evidence={
                    **evidence,
                    "ineligible_reason": "activation_delay_pending",
                    "elapsed_sec": elapsed,
                    "activation_delay_sec": activation_delay_sec,
                },
            )
        # Delay elapsed - should transition to TRAILING in caller.
        return ExitCondition(
            reason=ExitReason.TRAIL,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TRAIL).value,
            evidence={
                **evidence,
                "ineligible_reason": "transitioning_to_trailing",
                "next_state": "TRAILING",
            },
        )

    if position.trailing_state == TrailingState.TRAILING:
        trail_distance = _trailing_distance_cents(position)
        if trail_distance is None:
            return ExitCondition(
                reason=ExitReason.TRAIL,
                eligible=False,
                priority=get_priority_for_reason(ExitReason.TRAIL).value,
                evidence={**evidence, "ineligible_reason": "cannot_compute_trail_distance"},
            )
        trail_level = position.max_favorable_price_cents - trail_distance
        evidence["trail_distance_cents"] = trail_distance
        evidence["trail_level_cents"] = trail_level
        eligible = current_price_cents <= trail_level
        return ExitCondition(
            reason=ExitReason.TRAIL,
            eligible=eligible,
            priority=get_priority_for_reason(ExitReason.TRAIL).value,
            evidence=evidence,
        )

    return ExitCondition(
        reason=ExitReason.TRAIL,
        eligible=False,
        priority=get_priority_for_reason(ExitReason.TRAIL).value,
        evidence={**evidence, "ineligible_reason": f"unexpected_state_{position.trailing_state.value}"},
    )


def _time_stop_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
    time_to_expiry_seconds: float,
) -> ExitCondition:
    """Evaluate volatility-adjusted time stop."""
    evidence: Dict[str, Any] = {
        "time_since_entry_seconds": position.time_since_entry_seconds,
        "time_to_expiry_seconds": time_to_expiry_seconds,
        "r_multiple": position.r_multiple,
        "vol_regime": position.vol_regime,
        "current_price_cents": current_price_cents,
    }

    try:
        from merid.position_management.exit_policy import ExitPolicy
        policy = ExitPolicy(
            position=position,
            current_price_cents=current_price_cents,
            unrealized_pnl_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            time_since_entry_seconds=position.time_since_entry_seconds,
            time_to_expiry_seconds=time_to_expiry_seconds,
            volatility_regime=position.vol_regime,
        )
        effective_max_hold = policy.get_effective_max_hold()
        eligible = (
            position.time_since_entry_seconds >= effective_max_hold
            and position.r_multiple >= DEFAULT_TIME_STOP_R_THRESHOLD
        )
        evidence["effective_max_hold_seconds"] = effective_max_hold
        evidence["threshold_r_multiple"] = DEFAULT_TIME_STOP_R_THRESHOLD
        return ExitCondition(
            reason=ExitReason.TIME_STOP,
            eligible=eligible,
            priority=get_priority_for_reason(ExitReason.TIME_STOP).value,
            evidence=evidence,
        )
    except Exception as exc:
        return ExitCondition(
            reason=ExitReason.TIME_STOP,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.TIME_STOP).value,
            evidence={**evidence, "ineligible_reason": f"evaluation_error: {exc}"},
        )


def _edge_decay_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    current_price_cents: int,
    time_to_expiry_seconds: float,
    min_edge_decay_hold_seconds: float,
) -> ExitCondition:
    """Evaluate edge-decay condition with hold and provenance guards."""
    evidence: Dict[str, Any] = {
        "entry_edge_pct": position.entry_edge_pct,
        "entry_model_version": position.entry_model_version,
        "entry_signal_id": position.entry_signal_id,
        "fill_source": position.fill_source,
        "time_since_entry_seconds": position.time_since_entry_seconds,
        "min_edge_decay_hold_seconds": min_edge_decay_hold_seconds,
        "current_price_cents": current_price_cents,
    }

    # Replay / REST-sync / historical / unmatched fills cannot activate edge decay.
    ineligible_source = position.fill_source in {"rest_sync", "replay", "historical", "manual", "unknown"}
    if ineligible_source or not position.entry_signal_id:
        return ExitCondition(
            reason=ExitReason.EDGE_DECAY,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.EDGE_DECAY).value,
            evidence={
                **evidence,
                "ineligible_reason": "provenance_ineligible",
                "provenance_detail": "replay_rest_historical_unmatched_or_missing_signal",
            },
        )

    if position.time_since_entry_seconds < min_edge_decay_hold_seconds:
        return ExitCondition(
            reason=ExitReason.EDGE_DECAY,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.EDGE_DECAY).value,
            evidence={
                **evidence,
                "ineligible_reason": "hold_guard",
                "guarded_edge_pct": position.entry_edge_pct,
            },
        )

    if not _is_snapshot_executable(snapshot):
        return ExitCondition(
            reason=ExitReason.EDGE_DECAY,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.EDGE_DECAY).value,
            evidence={**evidence, "ineligible_reason": _snapshot_ineligibility_reason(snapshot)},
        )

    current_edge_pct = None
    try:
        from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator
        edge_evaluator = EdgeBasedExitEvaluator()
        current_edge_pct = edge_evaluator.compute_current_edge(
            position=position,
            current_price_cents=current_price_cents,
            time_to_expiry_seconds=time_to_expiry_seconds,
        )
    except Exception as exc:
        evidence["edge_compute_error"] = str(exc)

    if current_edge_pct is None:
        current_edge_pct = float(position.entry_edge_pct)
        evidence["edge_fallback"] = "entry_edge_pct"

    evidence["current_edge_pct"] = current_edge_pct

    try:
        from merid.position_management.exit_policy import MIN_EDGE_THRESHOLD
        eligible = current_edge_pct <= MIN_EDGE_THRESHOLD
        evidence["min_edge_threshold"] = MIN_EDGE_THRESHOLD
        return ExitCondition(
            reason=ExitReason.EDGE_DECAY,
            eligible=eligible,
            priority=get_priority_for_reason(ExitReason.EDGE_DECAY).value,
            evidence=evidence,
        )
    except Exception as exc:
        return ExitCondition(
            reason=ExitReason.EDGE_DECAY,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.EDGE_DECAY).value,
            evidence={**evidence, "ineligible_reason": f"threshold_error: {exc}"},
        )


def _stale_data_condition(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    md_age_ms: Optional[int],
    max_age_ms: Optional[int],
) -> ExitCondition:
    """Evaluate stale market data condition."""
    evidence: Dict[str, Any] = {
        "md_age_ms": md_age_ms,
        "max_age_ms": max_age_ms,
        "snapshot_book_age_ms": snapshot.book_age_ms if snapshot else None,
        "snapshot_data_source": snapshot.data_source if snapshot else None,
    }

    if md_age_ms is None or max_age_ms is None:
        return ExitCondition(
            reason=ExitReason.STALE_DATA,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.STALE_DATA).value,
            evidence={**evidence, "ineligible_reason": "missing_md_age"},
        )

    eligible = md_age_ms > max_age_ms
    evidence["excess_age_ms"] = max(0, md_age_ms - max_age_ms)
    return ExitCondition(
        reason=ExitReason.STALE_DATA,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.STALE_DATA).value,
        evidence=evidence,
    )


def _dynamic_take_profit_condition(position: Position, current_price_cents: int) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "dynamic_tp_target_cents": position.dynamic_tp_target_cents,
        "current_price_cents": current_price_cents,
        "dynamic_tp_triggered": position.dynamic_tp_triggered,
    }
    if position.dynamic_tp_target_cents is None:
        return ExitCondition(
            reason=ExitReason.DYNAMIC_TAKE_PROFIT,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.DYNAMIC_TAKE_PROFIT).value,
            evidence={**evidence, "ineligible_reason": "no_dynamic_tp_target"},
        )
    eligible = current_price_cents >= position.dynamic_tp_target_cents and not position.dynamic_tp_triggered
    return ExitCondition(
        reason=ExitReason.DYNAMIC_TAKE_PROFIT,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.DYNAMIC_TAKE_PROFIT).value,
        evidence=evidence,
    )


def _scale_out_condition(position: Position, current_price_cents: int) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "scale_out_price_cents": position.scale_out_price_cents,
        "scale_out_triggered": position.scale_out_triggered,
        "current_price_cents": current_price_cents,
        "size": position.size,
    }
    if position.scale_out_price_cents is None:
        return ExitCondition(
            reason=ExitReason.SCALE_OUT,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.SCALE_OUT).value,
            evidence={**evidence, "ineligible_reason": "no_scale_out_target"},
        )
    eligible = (
        current_price_cents >= position.scale_out_price_cents
        and not position.scale_out_triggered
        and position.size > 0
    )
    return ExitCondition(
        reason=ExitReason.SCALE_OUT,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.SCALE_OUT).value,
        evidence=evidence,
    )


def _ratchet_floor_condition(position: Position, current_price_cents: int) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "ratchet_activated": position.ratchet_activated,
        "ratchet_hold_until": position.ratchet_hold_until,
        "ratchet_floor_price_cents": position.ratchet_floor_price_cents,
        "current_price_cents": current_price_cents,
    }
    if not position.ratchet_activated:
        return ExitCondition(
            reason=ExitReason.RATCHET_FLOOR,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
            evidence={**evidence, "ineligible_reason": "ratchet_not_activated"},
        )
    now = time.time()
    if position.ratchet_hold_until and now < position.ratchet_hold_until:
        return ExitCondition(
            reason=ExitReason.RATCHET_FLOOR,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
            evidence={
                **evidence,
                "ineligible_reason": "hold_period_pending",
                "hold_remaining_sec": position.ratchet_hold_until - now,
            },
        )
    if position.ratchet_floor_price_cents is None:
        return ExitCondition(
            reason=ExitReason.RATCHET_FLOOR,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
            evidence={**evidence, "ineligible_reason": "no_floor_price"},
        )
    eligible = current_price_cents <= position.ratchet_floor_price_cents
    return ExitCondition(
        reason=ExitReason.RATCHET_FLOOR,
        eligible=eligible,
        priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
        evidence=evidence,
    )


def _ratchet_trim_condition(position: Position, current_price_cents: int) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "ratchet_trimmed": position.ratchet_trimmed,
        "current_price_cents": current_price_cents,
        "size": position.size,
    }
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            if profile.ratchet_trim_position_enabled:
                trim_threshold = profile.ratchet_trim_threshold_cents
                trim_to = profile.ratchet_trim_to_contracts
                evidence["trim_threshold_cents"] = trim_threshold
                evidence["trim_to_contracts"] = trim_to
                eligible = (
                    not position.ratchet_trimmed
                    and position.size > trim_to
                    and current_price_cents >= trim_threshold
                )
                return ExitCondition(
                    reason=ExitReason.RATCHET_TRIM,
                    eligible=eligible,
                    priority=get_priority_for_reason(ExitReason.RATCHET_TRIM).value,
                    evidence=evidence,
                )
    except Exception:
        pass
    return ExitCondition(
        reason=ExitReason.RATCHET_TRIM,
        eligible=False,
        priority=get_priority_for_reason(ExitReason.RATCHET_TRIM).value,
        evidence={**evidence, "ineligible_reason": "profile_not_active_or_trim_disabled"},
    )


def _break_even_condition(position: Position, current_price_cents: int) -> ExitCondition:
    evidence: Dict[str, Any] = {
        "break_even_triggered": position.break_even_triggered,
        "initial_risk_cents": position.initial_risk_cents,
        "avg_entry_price_cents": position.avg_entry_price_cents,
        "current_price_cents": current_price_cents,
    }
    if position.break_even_triggered or position.initial_risk_cents <= 0:
        return ExitCondition(
            reason=ExitReason.RATCHET_FLOOR,
            eligible=False,
            priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
            evidence={**evidence, "ineligible_reason": "already_triggered_or_no_risk"},
        )
    current_r = (current_price_cents - position.avg_entry_price_cents) / position.initial_risk_cents
    eligible = current_r >= 1.0
    evidence["current_r"] = current_r
    return ExitCondition(
        reason=ExitReason.RATCHET_FLOOR,  # Use ratchet floor priority for bookkeeping
        eligible=False,  # Break-even is not an exit; caller handles state transition
        priority=get_priority_for_reason(ExitReason.RATCHET_FLOOR).value,
        evidence=evidence,
    )


def evaluate_exit_conditions(
    position: Position,
    snapshot: Optional[ExitPriceSnapshot],
    now: float,
    *,
    soft_stop_min_observations: int = DEFAULT_SOFT_STOP_MIN_OBSERVATIONS,
    hard_stop_extra_buffer_cents: int = DEFAULT_HARD_STOP_EXTRA_BUFFER_CENTS,
    min_edge_decay_hold_seconds: float = DEFAULT_MIN_EDGE_DECAY_HOLD_SECONDS,
    min_exit_hold_seconds: float = DEFAULT_MIN_EXIT_HOLD_SECONDS,
    time_to_expiry_seconds: Optional[float] = None,
    seconds_to_expiry: Optional[float] = None,
    md_age_ms: Optional[int] = None,
    max_age_ms: Optional[int] = None,
) -> List[ExitCondition]:
    """
    Evaluate every configured exit condition for the position and snapshot.

    Args:
        position: Position to evaluate
        snapshot: Executable same-side book snapshot (or None)
        now: monotonic timestamp of this evaluation
        soft_stop_min_observations: consecutive polls for soft stop confirmation
        hard_stop_extra_buffer_cents: extra buffer below SL for hard stop
        min_edge_decay_hold_seconds: minimum hold before edge decay can fire
        min_exit_hold_seconds: minimum seconds any exit can hold (except hard stop / market close)
        time_to_expiry_seconds: time to market expiry (for time stop / edge decay)
        seconds_to_expiry: time to market expiry (alias for settlement/99c context)
        md_age_ms: market data age in ms (for stale data check)
        max_age_ms: max allowed MD age in ms

    Returns:
        List of ExitCondition records, one per evaluated reason.
    """
    if time_to_expiry_seconds is None:
        time_to_expiry_seconds = seconds_to_expiry if seconds_to_expiry is not None else 900.0
    if seconds_to_expiry is None:
        seconds_to_expiry = time_to_expiry_seconds

    current_price_cents = snapshot.own_side_bid_cents if snapshot is not None else position.current_price_cents

    conditions: List[ExitCondition] = [
        _stop_loss_condition(
            position,
            snapshot,
            current_price_cents,
            soft_stop_min_observations,
            hard_stop_extra_buffer_cents,
        ),
        _take_profit_condition(position, snapshot, current_price_cents),
        _auto_exit_99c_condition(position, snapshot, current_price_cents, seconds_to_expiry),
        _trail_condition(position, snapshot, current_price_cents, now),
        _time_stop_condition(position, snapshot, current_price_cents, time_to_expiry_seconds),
        _edge_decay_condition(
            position,
            snapshot,
            current_price_cents,
            time_to_expiry_seconds,
            min_edge_decay_hold_seconds,
        ),
        _stale_data_condition(position, snapshot, md_age_ms, max_age_ms),
        _dynamic_take_profit_condition(position, current_price_cents),
        _scale_out_condition(position, current_price_cents),
        _ratchet_floor_condition(position, current_price_cents),
        _ratchet_trim_condition(position, current_price_cents),
    ]

    # Min-hold guard (except hard stop / market close).  Anything eligible within
    # the hold window is downgraded to not eligible with a hold reason.
    if position.time_since_entry_seconds < min_exit_hold_seconds:
        for i, condition in enumerate(conditions):
            if condition.eligible and condition.reason not in {ExitReason.STOP_LOSS, ExitReason.MARKET_EXPIRED}:
                evidence = dict(condition.evidence)
                evidence["ineligible_reason"] = "min_exit_hold_guard"
                evidence["min_exit_hold_seconds"] = min_exit_hold_seconds
                evidence["time_since_entry_seconds"] = position.time_since_entry_seconds
                conditions[i] = ExitCondition(
                    reason=condition.reason,
                    eligible=False,
                    priority=condition.priority,
                    evidence=evidence,
                )

    return conditions


def choose_exit_condition(
    conditions: List[ExitCondition],
    chosen_reason: Optional[ExitReason] = None,
) -> ExitEvaluation:
    """
    Partition conditions into eligible / suppressed and optionally override the chosen.

    Args:
        conditions: list from evaluate_exit_conditions
        chosen_reason: if provided, use this as the chosen reason instead of the
            highest-priority eligible condition (e.g. when the caller has already
            committed to an exit reason)

    Returns:
        ExitEvaluation with chosen, eligible, and suppressed lists.
    """
    eligible = [c for c in conditions if c.eligible]
    chosen: Optional[ExitCondition] = None

    if chosen_reason is not None:
        for condition in eligible:
            if condition.reason == chosen_reason:
                chosen = condition
                break

    if chosen is None and eligible:
        chosen = max(eligible, key=lambda c: c.priority)

    if chosen is not None:
        suppressed = [c for c in eligible if c.reason != chosen.reason]
    else:
        suppressed = []

    return ExitEvaluation(conditions=conditions, chosen=chosen, eligible=eligible, suppressed=suppressed)

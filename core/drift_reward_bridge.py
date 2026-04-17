"""
Bridge between DriftMonitoringPipeline and DriftRewardLoop.

The pipeline (core/drift_monitoring_pipeline.py) emits its own DriftEvent
objects via mitigation callbacks. The reward loop (core/drift_reward_loop.py)
expects core.drift_monitor.DriftEvent objects. This bridge adapts between
the two, forwarding pipeline drift events to the reward loop for automatic
de-risking and MARL reward adjustment.

Usage:
    from core.drift_reward_bridge import wire_drift_reward_loop
    wire_drift_reward_loop()  # Call once at startup
"""

from __future__ import annotations

from typing import Optional

from utils.logger import get_logger

logger = get_logger("core.drift_reward_bridge")

_wired = False


def wire_drift_reward_loop() -> bool:
    """
    Wire the DriftRewardLoop into the DriftMonitoringPipeline.

    Registers a mitigation callback for every MitigationAction so that
    drift events flow into the reward loop for penalty computation and
    de-risk decisions.

    Safe to call multiple times — only wires once.

    Returns True if wiring succeeded, False if dependencies unavailable.
    """
    global _wired
    if _wired:
        return True

    try:
        from core.drift_monitoring_pipeline import (
            DriftEvent as PipelineDriftEvent,
            DriftStatus,
            MitigationAction,
            get_drift_monitoring_pipeline,
        )
        from core.drift_monitor import (
            DriftEvent as MonitorDriftEvent,
            DriftSeverity,
            DriftSignal,
        )
        from core.drift_reward_loop import get_drift_reward_loop

        pipeline = get_drift_monitoring_pipeline()
        reward_loop = get_drift_reward_loop()

        # Map pipeline DriftStatus → reward loop DriftSeverity
        status_to_severity = {
            DriftStatus.STABLE: DriftSeverity.INFO,
            DriftStatus.WARNING: DriftSeverity.WARNING,
            DriftStatus.DEGRADED: DriftSeverity.WARNING,
            DriftStatus.CRITICAL: DriftSeverity.CRITICAL,
        }

        def _on_pipeline_drift(event: PipelineDriftEvent) -> None:
            """Adapt pipeline DriftEvent → monitor DriftEvent → reward loop."""
            severity = status_to_severity.get(event.status, DriftSeverity.INFO)

            # Build a monitor-style DriftEvent from pipeline event
            monitor_event = MonitorDriftEvent(
                event_id=event.event_id,
                component=event.source_id,
                component_type=event.drift_type.value,
                severity=severity,
                message=event.description,
                signals=[
                    DriftSignal(
                        metric_name=f"{event.drift_type.value}:{event.source_name}",
                        value=event.current_value,
                        reference=event.baseline_value,
                        threshold=event.deviation,
                    )
                ],
            )

            decision = reward_loop.process_drift_event(monitor_event)
            if decision:
                logger.info(
                    "Drift reward loop action: %s for %s (severity=%s)",
                    decision.action.value,
                    event.source_id,
                    severity.value,
                )

        # Register for all mitigation actions
        for action in MitigationAction:
            pipeline.register_mitigation_callback(action, _on_pipeline_drift)

        _wired = True
        logger.info(
            "DriftRewardLoop wired into DriftMonitoringPipeline "
            "(%d action callbacks registered)",
            len(MitigationAction),
        )
        return True

    except Exception as exc:
        logger.warning("Failed to wire drift reward loop: %s", exc)
        return False


def is_wired() -> bool:
    """Check if the bridge is active."""
    return _wired

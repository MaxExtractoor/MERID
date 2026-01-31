"""Dev swarm command runner with guardrail enforcement and explainability logging."""
from __future__ import annotations

import os
import shlex
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from core.explainability import (
    DecisionRationale,
    ExplanationContext,
    ExplanationType,
    FeatureAttribution,
    get_explainability_service,
)
from core.policy_engine import (
    GuardrailContext,
    PolicyDecision,
    evaluate_guardrail,
)
from latency_optimizer.orchestrator_hooks import LatencyProbe
from latency_optimizer.policies import OptimizationDecision


class CommandStatus(str, Enum):
    EXECUTED = "executed"
    PENDING_APPROVAL = "pending_approval"
    DENIED = "denied"
    ERROR = "error"


@dataclass
class CommandRequest:
    command: str
    surface: str
    action: str
    intent_id: str
    agent_id: str
    description: str = ""
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: int = 60
    latency_probe_config: Optional[Dict[str, Any]] = None


@dataclass
class CommandResult:
    status: CommandStatus
    exit_code: Optional[int]
    stdout: str
    stderr: str
    guardrail_decision: PolicyDecision
    guardrail_id: Optional[str]
    guardrail_rationale: str


class CommandRunner:
    """Executes commands with guardrail checks and explainability logging."""

    def __init__(self) -> None:
        self._explainability = get_explainability_service()

    def run(self, request: CommandRequest) -> CommandResult:
        probe = self._build_latency_probe(request)
        with (probe if probe else nullcontext()):
            context = GuardrailContext(
                surface=request.surface,
                action=request.action,
                metadata={"command": request.command, "intent_id": request.intent_id},
                agent_id=request.agent_id,
                intent_id=request.intent_id,
            )
            decision, guardrail_rationale, guardrail_id = evaluate_guardrail(context)

            if decision == PolicyDecision.DENY:
                result = CommandResult(
                    status=CommandStatus.DENIED,
                    exit_code=None,
                    stdout="",
                    stderr="Guardrail denied execution",
                    guardrail_decision=decision,
                    guardrail_id=guardrail_id,
                    guardrail_rationale=guardrail_rationale,
                )
            elif decision == PolicyDecision.REQUIRE_APPROVAL:
                result = CommandResult(
                    status=CommandStatus.PENDING_APPROVAL,
                    exit_code=None,
                    stdout="",
                    stderr="Human approval required",
                    guardrail_decision=decision,
                    guardrail_id=guardrail_id,
                    guardrail_rationale=guardrail_rationale,
                )
            else:
                try:
                    completed = subprocess.run(
                        shlex.split(request.command),
                        capture_output=True,
                        text=True,
                        cwd=request.cwd,
                        env=self._build_env(request.env),
                        timeout=request.timeout,
                        check=False,
                    )
                    status = (
                        CommandStatus.EXECUTED
                        if completed.returncode == 0
                        else CommandStatus.ERROR
                    )
                    result = CommandResult(
                        status=status,
                        exit_code=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        guardrail_decision=decision,
                        guardrail_id=guardrail_id,
                        guardrail_rationale=guardrail_rationale,
                    )
                except subprocess.TimeoutExpired as exc:
                    result = CommandResult(
                        status=CommandStatus.ERROR,
                        exit_code=None,
                        stdout=exc.stdout or "",
                        stderr=f"Timeout after {request.timeout}s",
                        guardrail_decision=decision,
                        guardrail_id=guardrail_id,
                        guardrail_rationale=guardrail_rationale,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result = CommandResult(
                        status=CommandStatus.ERROR,
                        exit_code=None,
                        stdout="",
                        stderr=str(exc),
                        guardrail_decision=decision,
                        guardrail_id=guardrail_id,
                        guardrail_rationale=guardrail_rationale,
                    )

        latency_decision = probe.decision if probe else None
        self._record_explainability(request, result, latency_decision=latency_decision)
        return result

    def _build_env(self, overrides: Optional[Dict[str, str]]) -> Dict[str, str]:
        env = os.environ.copy()
        if overrides:
            env.update(overrides)
        return env

    def _record_explainability(
        self,
        request: CommandRequest,
        result: CommandResult,
        *,
        latency_decision: Optional[OptimizationDecision] = None,
    ) -> None:
        summary = request.description or f"Command `{request.command}`"
        rationale = DecisionRationale(
            reason=f"Command {result.status.value}",
            inputs={"command": request.command, "cwd": request.cwd},
            features=[FeatureAttribution(name="command", value=request.command)],
            constraints={"surface": request.surface, "action": request.action},
            counterfactuals=[],
            telemetry_refs=[],
        )
        context = ExplanationContext(
            inputs={"command": request.command, "cwd": request.cwd},
            agent_id=request.agent_id,
            strategy=None,
            constraints={"surface": request.surface},
            expected_effect={"intent_id": request.intent_id},
            environment_flags={},
            tools_invoked=[request.command],
            alternatives_considered=[],
        )
        latency_kwargs = {}
        if latency_decision:
            latency_kwargs = {
                "latency_domain": latency_decision.domain,
                "latency_workflow": latency_decision.workflow,
                "latency_status": latency_decision.status,
                "latency_observed_ms": latency_decision.observed_ms,
                "latency_fallback_strategy": (
                    latency_decision.fallback.strategy_id
                    if latency_decision.fallback
                    else None
                ),
            }
        self._explainability.record_explanation(
            ExplanationType.DEV_COMMAND,
            summary,
            context,
            domain="dev_swarm",
            decision_id=request.intent_id,
            rationale=rationale,
            guardrail_id=result.guardrail_id,
            guardrail_decision=result.guardrail_decision.value,
            guardrail_rationale=result.guardrail_rationale,
            **latency_kwargs,
        )

    def _build_latency_probe(self, request: CommandRequest) -> Optional[LatencyProbe]:
        if not request.latency_probe_config:
            return None
        return LatencyProbe(**request.latency_probe_config)


_command_runner: Optional[CommandRunner] = None


def get_command_runner() -> CommandRunner:
    global _command_runner
    if _command_runner is None:
        _command_runner = CommandRunner()
    return _command_runner

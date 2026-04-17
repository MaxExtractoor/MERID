"""
Swarm design linter for static/dynamic checks across agent blueprints.

The linter enforces architectural conventions, safety constraints, and
observability requirements before new designs can be promoted into the swarm.
This allows Phase 9 to gate deployments with the same rigor as our runtime
controls without needing yet another external dependency.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class LintRule:
    """Reusable lint rule."""

    rule_id: str
    description: str
    severity: str  # INFO, WARN, ERROR
    check: Callable[[Dict[str, object]], Optional[str]]
    auto_fix: Optional[Callable[[Dict[str, object]], bool]] = None


@dataclass
class LintFinding:
    """Result of a lint rule evaluation."""

    rule_id: str
    message: str
    severity: str
    auto_fixed: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SwarmDesignLinter:
    """Runs lint rules over agent blueprints."""

    def __init__(self) -> None:
        self._rules: Dict[str, LintRule] = {}
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Seed the linter with the highest-signal rules for MERID."""

        def has_owner(blueprint: Dict[str, object]) -> Optional[str]:
            if not blueprint.get("owner"):
                return "Missing owner/responsible engineer"
            return None

        def has_runbook(blueprint: Dict[str, object]) -> Optional[str]:
            if not blueprint.get("runbook_url"):
                return "Missing runbook_url"
            return None

        def has_observability(blueprint: Dict[str, object]) -> Optional[str]:
            observability = blueprint.get("observability", {})
            if not isinstance(observability, dict):
                return "Observability block malformed"
            required = {"metrics", "alerts", "logs"}
            if not required.issubset(observability.keys()):
                return "Observability block missing metrics/alerts/logs"
            return None

        def enforce_leverage_limits(blueprint: Dict[str, object]) -> Optional[str]:
            leverage = float(blueprint.get("max_leverage", 1.0))
            if leverage > 3.0:
                return f"Max leverage {leverage} exceeds policy (3.0x)"
            return None

        self.register_rule(
            LintRule(
                rule_id="owner_required",
                description="Every blueprint must identify a responsible owner",
                severity="ERROR",
                check=has_owner,
            )
        )
        self.register_rule(
            LintRule(
                rule_id="runbook_required",
                description="Blueprints must link to incident/runbook docs",
                severity="WARN",
                check=has_runbook,
            )
        )
        self.register_rule(
            LintRule(
                rule_id="observability_contract",
                description="Require metrics/alerts/logs definitions",
                severity="ERROR",
                check=has_observability,
            )
        )
        self.register_rule(
            LintRule(
                rule_id="leverage_policy",
                description="Prevent leverage settings that exceed governance policy",
                severity="ERROR",
                check=enforce_leverage_limits,
            )
        )

    def register_rule(self, rule: LintRule) -> None:
        self._rules[rule.rule_id] = rule
        logger.debug("Registered lint rule %s", rule.rule_id)

    def run(self, blueprint: Dict[str, object]) -> List[LintFinding]:
        """Execute all lint rules against a single blueprint."""
        findings: List[LintFinding] = []
        for rule in self._rules.values():
            message = rule.check(blueprint)
            if message:
                auto_fixed = False
                if rule.auto_fix and rule.auto_fix(blueprint):
                    auto_fixed = True
                    logger.info("Auto-fixed %s for blueprint %s", rule.rule_id, blueprint.get("name"))
                findings.append(
                    LintFinding(
                        rule_id=rule.rule_id,
                        message=message,
                        severity=rule.severity,
                        auto_fixed=auto_fixed,
                    )
                )
        return findings

    def run_batch(self, blueprints: Iterable[Dict[str, object]]) -> Dict[str, List[LintFinding]]:
        """Batch linting helper."""
        results: Dict[str, List[LintFinding]] = {}
        for blueprint in blueprints:
            name = str(blueprint.get("name", "unnamed_agent"))
            results[name] = self.run(blueprint)
        return results


_swarm_design_linter: Optional[SwarmDesignLinter] = None
_swarm_design_linter_lock = threading.Lock()


def get_swarm_design_linter() -> SwarmDesignLinter:
    global _swarm_design_linter
    if _swarm_design_linter is None:
        with _swarm_design_linter_lock:
            if _swarm_design_linter is None:
                _swarm_design_linter = SwarmDesignLinter()
    return _swarm_design_linter

"""Swarm integrity and data-authenticity guardrails.

This module enforces two hard requirements before high-trust operations:
1) Swarm/agent/strategy components must be online, synced, and healthy.
2) Data sources must be verified and tagged with explicit trading modes.

It is intentionally deterministic and file-driven so CI and pytest can gate
integration/deployment paths without relying on live infrastructure.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from utils.logger import get_logger

logger = get_logger("core.swarm_integrity_guard")

UNVERIFIED_DATA_MESSAGE = "⚠️ Data unverified — check source or mode (mock/paper/live)."

_DEFAULT_POLICY: Dict[str, Any] = {
    "enforcement": {
        "require_full_health": True,
        "require_sync": True,
        "min_health_pct": 100.0,
        "allowed_data_sources": ["verified_backend", "deterministic_fixture"],
    },
    "reporting": {
        "required_mode_tags": ["mock", "paper", "live"],
        "unverified_data_message": UNVERIFIED_DATA_MESSAGE,
    },
}

_COMPONENT_KEYS = {
    "swarm_nodes": "swarm_node",
    "agent_pods": "agent_pod",
    "strategy_clusters": "strategy_cluster",
}


@dataclass
class IntegrityReport:
    """Normalized result for swarm integrity gate checks."""

    ok: bool
    issues: list[str] = field(default_factory=list)
    warning: str | None = None
    health_summary: Dict[str, Any] = field(default_factory=dict)
    data_summary: Dict[str, Any] = field(default_factory=dict)
    mode_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": list(self.issues),
            "warning": self.warning,
            "health_summary": dict(self.health_summary),
            "data_summary": dict(self.data_summary),
            "mode_tags": list(self.mode_tags),
        }


def _deep_merge(base: Dict[str, Any], overrides: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_policy_text(text: str) -> Dict[str, Any]:
    """Parse policy text as JSON first, then YAML if available.

    `.merid_safeguard.yml` is stored as JSON-compatible YAML so stdlib JSON works
    in all environments. YAML fallback is only used when available.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - exercised in environments without yaml
            raise ValueError(
                "Policy file is not valid JSON and PyYAML is unavailable"
            ) from exc
        parsed = yaml.safe_load(text)

    if not isinstance(parsed, dict):
        raise ValueError("Safeguard policy must deserialize to a JSON object")
    return parsed


def load_safeguard_policy(policy_path: str | os.PathLike[str] | None = None) -> Dict[str, Any]:
    """Load safeguard policy from disk, merged over safe defaults."""
    policy = _deep_merge({}, _DEFAULT_POLICY)
    if policy_path is None:
        policy_path = ".merid_safeguard.yml"

    path = Path(policy_path)
    if not path.exists():
        logger.info("Safeguard policy not found at %s, using defaults", path)
        return policy

    try:
        raw = _parse_policy_text(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse safeguard policy %s: %s", path, exc)
        return policy

    return _deep_merge(policy, raw)


def load_swarm_snapshot(snapshot_path: str | os.PathLike[str]) -> Dict[str, Any]:
    """Load JSON swarm health snapshot from disk."""
    path = Path(snapshot_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Swarm snapshot root must be an object")
    return payload


def _iter_components(snapshot: Mapping[str, Any]) -> Iterable[tuple[str, Dict[str, Any]]]:
    for key, component_type in _COMPONENT_KEYS.items():
        entries = snapshot.get(key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                yield component_type, dict(entry)


def evaluate_swarm_integrity(
    snapshot: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> IntegrityReport:
    """Evaluate snapshot against swarm and data-authenticity policy."""
    merged_policy = _deep_merge({}, _DEFAULT_POLICY)
    if policy:
        merged_policy = _deep_merge(merged_policy, policy)

    enforcement = merged_policy.get("enforcement", {})
    reporting = merged_policy.get("reporting", {})

    require_sync = bool(enforcement.get("require_sync", True))
    require_full_health = bool(enforcement.get("require_full_health", True))
    min_health_pct = float(enforcement.get("min_health_pct", 100.0))
    allowed_data_sources = {
        str(value).strip().lower()
        for value in enforcement.get("allowed_data_sources", ["verified_backend", "deterministic_fixture"])
    }
    required_modes = {
        str(value).strip().lower()
        for value in reporting.get("required_mode_tags", ["mock", "paper", "live"])
    }
    warning_message = str(reporting.get("unverified_data_message", UNVERIFIED_DATA_MESSAGE))

    issues: list[str] = []

    total_components = 0
    online_components = 0
    synced_components = 0
    healthy_components = 0

    for component_type, entry in _iter_components(snapshot):
        total_components += 1
        name = str(entry.get("name") or entry.get("id") or "unknown")
        online = bool(entry.get("online", False))
        synced = bool(entry.get("synced", False))

        try:
            health_pct = float(entry.get("health_pct", 0.0))
        except (TypeError, ValueError):
            health_pct = 0.0

        if online:
            online_components += 1
        else:
            issues.append(f"{component_type}:{name} is offline")

        if synced:
            synced_components += 1
        elif require_sync:
            issues.append(f"{component_type}:{name} is not synced")

        if health_pct >= min_health_pct:
            healthy_components += 1
        elif require_full_health:
            issues.append(
                f"{component_type}:{name} health {health_pct:.1f}% below {min_health_pct:.1f}%"
            )

    if total_components == 0:
        issues.append("No swarm component health entries were provided")

    data_sources_raw = snapshot.get("data_sources", [])
    data_sources = data_sources_raw if isinstance(data_sources_raw, list) else []

    total_sources = 0
    verified_sources = 0
    mode_tags: set[str] = set()
    saw_unverified = False

    for source in data_sources:
        if not isinstance(source, Mapping):
            continue
        total_sources += 1
        source_name = str(source.get("name") or source.get("id") or "unknown")
        source_type = str(source.get("source_type", "unknown")).strip().lower()
        verified = bool(source.get("verified", False))
        mode = str(source.get("mode", "unknown")).strip().lower()

        mode_tags.add(mode)

        if source_type not in allowed_data_sources:
            issues.append(
                f"data_source:{source_name} source_type '{source_type}' is not in allowed set"
            )

        if not verified:
            saw_unverified = True
            issues.append(f"data_source:{source_name} is not verified")
        else:
            verified_sources += 1

        if mode not in required_modes:
            issues.append(
                f"data_source:{source_name} mode '{mode}' is not one of {sorted(required_modes)}"
            )

    if total_sources == 0:
        saw_unverified = True
        issues.append("No data source provenance entries were provided")

    warning = warning_message if saw_unverified else None

    health_summary = {
        "total_components": total_components,
        "online_components": online_components,
        "synced_components": synced_components,
        "healthy_components": healthy_components,
        "all_online": total_components > 0 and online_components == total_components,
        "all_synced": total_components > 0 and synced_components == total_components,
        "all_healthy": total_components > 0 and healthy_components == total_components,
    }

    data_summary = {
        "total_sources": total_sources,
        "verified_sources": verified_sources,
        "all_verified": total_sources > 0 and verified_sources == total_sources,
    }

    return IntegrityReport(
        ok=not issues,
        issues=issues,
        warning=warning,
        health_summary=health_summary,
        data_summary=data_summary,
        mode_tags=sorted(mode_tags),
    )


def run_swarm_integrity_gate(
    *,
    snapshot_path: str | os.PathLike[str] | None = None,
    policy_path: str | os.PathLike[str] | None = None,
) -> IntegrityReport:
    """Load policy + snapshot and evaluate as a single gate operation."""
    policy = load_safeguard_policy(policy_path)

    snapshot_candidate = snapshot_path or os.getenv("MERID_SWARM_HEALTH_SNAPSHOT")
    if not snapshot_candidate:
        message = policy.get("reporting", {}).get(
            "unverified_data_message", UNVERIFIED_DATA_MESSAGE
        )
        return IntegrityReport(
            ok=False,
            issues=[
                "Missing swarm snapshot path. Set MERID_SWARM_HEALTH_SNAPSHOT or pass --snapshot."
            ],
            warning=str(message),
            health_summary={
                "total_components": 0,
                "online_components": 0,
                "synced_components": 0,
                "healthy_components": 0,
                "all_online": False,
                "all_synced": False,
                "all_healthy": False,
            },
            data_summary={"total_sources": 0, "verified_sources": 0, "all_verified": False},
            mode_tags=[],
        )

    snapshot = load_swarm_snapshot(snapshot_candidate)
    return evaluate_swarm_integrity(snapshot, policy=policy)

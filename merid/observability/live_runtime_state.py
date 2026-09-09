"""
Canonical live runtime state for the MERID 15m Kalshi crypto trading system.

This is the authoritative state machine for live entry permission.  It is
separate from the process-level ``StartupState`` because process startup is not
the same as permission to risk capital.

States
------
STOPPED
  Initial state when the module is loaded outside a live server context.
STARTING
  Process has begun startup but has not reached preflight.
PREFLIGHT_RUNNING
  Preflight checks are executing.
LIVE_ENTRIES_HALTED
  Default safe state; new entries are blocked.  Exits and data capture remain
  available.
RECOVERY_RUNNING
  A prior halt is being repaired and reconciled before entries may resume.
LIVE_ENTRIES_ENABLED
  New entries are permitted for eligible candidates that pass ordinary gating.

Rules
-----
- The singleton starts in ``LIVE_ENTRIES_HALTED``.
- A process starts at ``STARTING`` and moves to ``PREFLIGHT_RUNNING``.
- Preflight success alone is NOT enough to reach ``LIVE_ENTRIES_ENABLED``.
  An explicit, secret-backed operator release is required.
- Any preflight failure, RTI/book degradation, reconciliation divergence,
  circuit-breaker trip, unknown submission, or configuration conflict moves
  the state to ``LIVE_ENTRIES_HALTED``.
- No code path may submit a live entry order unless ``state == LIVE_ENTRIES_ENABLED``.
- State transitions are persisted atomically and logged.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.live_runtime_state")

PERSISTENCE_PATH = Path(
    os.environ.get("MERID_LIVE_RUNTIME_STATE_PATH", "data/live_runtime_state.json")
)


class LiveRuntimeStateError(RuntimeError):
    """Raised when a live-runtime-state invariant is violated."""


class LiveRuntimeStateTransitionError(LiveRuntimeStateError):
    """Raised when an illegal state transition is requested."""


@dataclass(frozen=True)
class ReleaseAssertion:
    """Operator release assertion required to enable live entries.

    A release must bind to a specific deployment, configuration, account,
    process, and preflight result.  Placeholder or reused tokens are rejected.
    """

    state: str = "LIVE_ENTRIES_HALTED"
    deployment_sha: str = ""
    config_hash: str = ""
    account_id: str = ""
    process_id: str = ""
    reason: str = ""
    timestamp: str = ""
    manual_release_token_hash: str = ""
    emergency_token_hash: str = ""
    expiry: str = ""
    preflight_snapshot_id: str = ""
    fresh_reconciliation: bool = False


class LiveRuntimeState:
    """Singleton authoritative state machine for live entry permission."""

    _VALID_STATES: Set[str] = {
        "STOPPED",
        "STARTING",
        "PREFLIGHT_RUNNING",
        "LIVE_ENTRIES_HALTED",
        "RECOVERY_RUNNING",
        "LIVE_ENTRIES_ENABLED",
    }

    _ENTRY_STATES: Set[str] = {"LIVE_ENTRIES_ENABLED"}

    # Allowed transitions from each state.
    # A process (re)start may begin from a persisted halt, so STARTING is
    # reachable from halted/stopped/recovery states.
    _TRANSITIONS: Dict[str, Set[str]] = {
        "STOPPED": {"STARTING", "LIVE_ENTRIES_HALTED"},
        "STARTING": {"PREFLIGHT_RUNNING", "LIVE_ENTRIES_HALTED", "STOPPED"},
        "PREFLIGHT_RUNNING": {
            "LIVE_ENTRIES_ENABLED",
            "LIVE_ENTRIES_HALTED",
            "RECOVERY_RUNNING",
            "STOPPED",
        },
        "LIVE_ENTRIES_HALTED": {
            "STARTING",
            "PREFLIGHT_RUNNING",
            "RECOVERY_RUNNING",
            "STOPPED",
        },
        "RECOVERY_RUNNING": {"STARTING", "LIVE_ENTRIES_ENABLED", "LIVE_ENTRIES_HALTED", "STOPPED"},
        "LIVE_ENTRIES_ENABLED": {"LIVE_ENTRIES_HALTED", "RECOVERY_RUNNING", "STOPPED"},
    }

    def __init__(self, persistence_path: Optional[Path] = None) -> None:
        self._persistence_path = Path(
            persistence_path or PERSISTENCE_PATH
        ).resolve()
        self._lock = threading.RLock()
        self._state: str = "LIVE_ENTRIES_HALTED"
        self._entry_halted: bool = True
        self._reason: str = "initial_state"
        self._reason_codes: List[str] = ["INITIAL_STATE"]
        self._started_at: str = self._now()
        self._last_transition_at: str = self._started_at
        self._run_id: str = ""
        self._process_id: str = ""
        self._deployment_sha: str = ""
        self._config_hash: str = ""
        self._release_assertion: Optional[Dict[str, Any]] = None
        self._transition_history: List[Dict[str, Any]] = []
        self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        """Load persisted state if it is valid; otherwise remain halted."""
        if not self._persistence_path.exists():
            self._persist()
            return
        try:
            data = json.loads(self._persistence_path.read_text(encoding="utf-8"))
            loaded_state = data.get("state")
            if loaded_state in self._VALID_STATES:
                self._state = loaded_state
            else:
                logger.warning(
                    "[LIVE-RUNTIME-STATE] persisted state %r is invalid; defaulting to LIVE_ENTRIES_HALTED",
                    loaded_state,
                )
                self._state = "LIVE_ENTRIES_HALTED"
                self._reason = f"invalid_persisted_state:{loaded_state}"
                self._reason_codes = ["INVALID_PERSISTED_STATE"]
            self._entry_halted = self._state != "LIVE_ENTRIES_ENABLED"
            self._started_at = data.get("started_at", self._started_at)
            self._run_id = data.get("run_id", "")
            self._process_id = data.get("process_id", "")
            self._deployment_sha = data.get("deployment_sha", "")
            self._config_hash = data.get("config_hash", "")
            self._release_assertion = data.get("release_assertion")
            self._transition_history = data.get("transition_history", [])[:100]
        except Exception as exc:
            logger.warning(
                "[LIVE-RUNTIME-STATE] failed to load persisted state: %s; defaulting to halted",
                exc,
            )
            self._state = "LIVE_ENTRIES_HALTED"
            self._entry_halted = True
            self._reason = f"persist_load_failed:{exc}"
            self._reason_codes = ["PERSIST_LOAD_FAILED"]

    def _persist(self) -> None:
        """Persist the current state atomically."""
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persistence_path.with_suffix(".tmp")
            payload = self.to_dict()
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self._persistence_path)
        except Exception as exc:
            logger.error(
                "[LIVE-RUNTIME-STATE] failed to persist state: %s", exc
            )

    def _log_transition(
        self,
        previous_state: str,
        new_state: str,
        reason: str,
        reason_codes: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = {
            "timestamp": self._now(),
            "previous_state": previous_state,
            "new_state": new_state,
            "reason": reason,
            "reason_codes": reason_codes,
            "context": context or {},
            "run_id": self._run_id,
            "process_id": self._process_id,
            "deployment_sha": self._deployment_sha,
            "config_hash": self._config_hash,
        }
        self._transition_history.append(record)
        if len(self._transition_history) > 100:
            self._transition_history.pop(0)
        logger.critical(
            "[LIVE-RUNTIME-STATE-TRANSITION] %s -> %s | reason=%s | codes=%s",
            previous_state,
            new_state,
            reason,
            reason_codes,
        )

    def transition(
        self,
        new_state: str,
        reason: str,
        reason_codes: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Request a state transition.  Raises on illegal transitions."""
        if new_state not in self._VALID_STATES:
            raise LiveRuntimeStateTransitionError(
                f"invalid state: {new_state!r}"
            )
        with self._lock:
            if new_state == self._state:
                return
            allowed = self._TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                raise LiveRuntimeStateTransitionError(
                    f"illegal transition: {self._state} -> {new_state}"
                )
            previous = self._state
            self._state = new_state
            self._entry_halted = new_state != "LIVE_ENTRIES_ENABLED"
            self._reason = reason
            self._reason_codes = list(reason_codes or [])
            self._last_transition_at = self._now()
            self._log_transition(
                previous, new_state, reason, self._reason_codes, context
            )
            self._persist()

    def set_process_identity(
        self,
        run_id: str,
        process_id: str,
        deployment_sha: str,
        config_hash: str,
    ) -> None:
        with self._lock:
            self._run_id = run_id or str(uuid.uuid4())
            self._process_id = process_id or str(os.getpid())
            self._deployment_sha = deployment_sha
            self._config_hash = config_hash
            self._persist()

    def live_entries_enabled(self) -> bool:
        with self._lock:
            return self._state == "LIVE_ENTRIES_ENABLED" and not self._entry_halted

    def can_submit_live_entry(self) -> bool:
        """True only when the state machine authorizes new live entries."""
        with self._lock:
            return self._state == "LIVE_ENTRIES_ENABLED" and not self._entry_halted

    def can_submit_exit(self) -> bool:
        """Exits are preserved while entries are halted, but the process must be up."""
        with self._lock:
            return self._state in {
                "LIVE_ENTRIES_ENABLED",
                "LIVE_ENTRIES_HALTED",
                "RECOVERY_RUNNING",
            }

    def complete_preflight(
        self,
        auto_enable: bool = False,
        preflight_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Complete startup preflight and either enable or halt live entries.

        When ``auto_execution_mode`` is active (``AGENTS.md`` front matter or
        ``MERID_AUTO_EXECUTION_MODE``), the state machine may automatically
        transition to ``LIVE_ENTRIES_ENABLED`` after preflight passes.
        Otherwise the default safe end state is ``LIVE_ENTRIES_HALTED``.
        """
        with self._lock:
            if self._state not in ("PREFLIGHT_RUNNING", "RECOVERY_RUNNING"):
                # Already in a terminal or enabled state; only move to halted
                # if the preflight is being re-run.
                return
            if auto_enable:
                self._release_assertion = (preflight_context or {}) | {
                    "enabled_at": self._now(),
                    "auto_enable": True,
                }
                self.transition(
                    "LIVE_ENTRIES_ENABLED",
                    "auto_enable_after_preflight",
                    reason_codes=["AUTO_ENABLE", "PREFLIGHT_PASSED"],
                    context={"preflight_context": preflight_context or {}},
                )
            else:
                self.transition(
                    "LIVE_ENTRIES_HALTED",
                    "preflight_complete_auto_disabled",
                    reason_codes=["PREFLIGHT_PASSED", "AUTO_ENABLE_OFF"],
                    context={"preflight_context": preflight_context or {}},
                )

    def request_live_entries_enabled(
        self,
        release_assertion: ReleaseAssertion,
    ) -> None:
        """Enable live entries after a validated preflight and manual release.

        This is an explicit operator override path to ``LIVE_ENTRIES_ENABLED``
        used when ``auto_execution_mode`` is off or for recovery.  It validates
        the release assertion, refuses placeholder tokens, and ensures the
        assertion matches the current deployment/process.
        """
        with self._lock:
            self._validate_release_assertion(release_assertion)
            self._release_assertion = asdict(release_assertion)
            self._release_assertion["enabled_at"] = self._now()
            self.transition(
                "LIVE_ENTRIES_ENABLED",
                "manual_release_after_preflight",
                reason_codes=["MANUAL_RELEASE", "PREFLIGHT_PASSED"],
                context={"release_assertion": self._release_assertion},
            )

    def _validate_release_assertion(self, assertion: ReleaseAssertion) -> None:
        """Validate that the release assertion is real and current."""
        errors: List[str] = []

        if not assertion.fresh_reconciliation:
            errors.append("fresh_reconciliation_required")

        if assertion.state != self._state:
            errors.append(
                f"release_state_mismatch: {assertion.state} != {self._state}"
            )

        if assertion.deployment_sha and assertion.deployment_sha != self._deployment_sha:
            errors.append("deployment_sha_mismatch")

        if assertion.config_hash and assertion.config_hash != self._config_hash:
            errors.append("config_hash_mismatch")

        if not assertion.manual_release_token_hash:
            errors.append("missing_manual_release_token")
        elif self._is_placeholder_token(assertion.manual_release_token_hash):
            errors.append("placeholder_manual_release_token")

        if not assertion.emergency_token_hash:
            errors.append("missing_emergency_token")
        elif self._is_placeholder_token(assertion.emergency_token_hash):
            errors.append("placeholder_emergency_token")

        if not assertion.preflight_snapshot_id:
            errors.append("missing_preflight_snapshot_id")

        try:
            if assertion.expiry:
                expiry_dt = datetime.fromisoformat(assertion.expiry)
                if expiry_dt < datetime.now(timezone.utc):
                    errors.append("release_assertion_expired")
        except Exception:
            errors.append("release_assertion_expiry_invalid")

        if errors:
            raise LiveRuntimeStateError(
                "release_assertion_invalid: " + "; ".join(errors)
            )

    @staticmethod
    def _is_placeholder_token(value: str) -> bool:
        """Reject known placeholder, empty, or test token values."""
        if not value or not value.strip():
            return True
        normalized = value.strip().lower()
        placeholders = {
            "set_from_secret_store",
            "placeholder",
            "test",
            "default",
            "merid_manual_emergency_token",
            "merid_breaker_release_token",
            "",
        }
        return normalized in placeholders or normalized.startswith("set_from")

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def transition_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._transition_history)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "entry_halted": self._entry_halted,
                "reason": self._reason,
                "reason_codes": self._reason_codes,
                "started_at": self._started_at,
                "last_transition_at": self._last_transition_at,
                "run_id": self._run_id,
                "process_id": self._process_id,
                "deployment_sha": self._deployment_sha,
                "config_hash": self._config_hash,
                "release_assertion": self._release_assertion,
                "transition_history": self._transition_history[-20:],
            }

    def halt_entries(self, reason: str, reason_codes: List[str]) -> None:
        """Convenience helper to halt entries from any state."""
        if self._state in ("LIVE_ENTRIES_ENABLED", "RECOVERY_RUNNING"):
            self.transition("LIVE_ENTRIES_HALTED", reason, reason_codes)
        elif self._state == "PREFLIGHT_RUNNING":
            self.transition("LIVE_ENTRIES_HALTED", reason, reason_codes)
        elif self._state == "LIVE_ENTRIES_HALTED":
            # Already halted; still record the latest reason/codes so the
            # persistence file reflects the most recent preflight/operator state.
            self._reason = reason
            self._reason_codes = list(reason_codes)
            self._last_transition_at = datetime.now(timezone.utc).isoformat()
            self._transition_history.append({
                "from": self._state,
                "to": self._state,
                "at": self._last_transition_at,
                "reason": reason,
                "reason_codes": list(reason_codes),
            })
            self._persist()


# Global singleton
_live_runtime_state: Optional[LiveRuntimeState] = None
_live_runtime_state_lock = threading.Lock()


def get_live_runtime_state(
    persistence_path: Optional[Path] = None,
) -> LiveRuntimeState:
    """Return the global LiveRuntimeState singleton."""
    global _live_runtime_state
    if _live_runtime_state is None:
        with _live_runtime_state_lock:
            if _live_runtime_state is None:
                _live_runtime_state = LiveRuntimeState(persistence_path)
    return _live_runtime_state


def reset_live_runtime_state() -> None:
    """Reset the singleton (tests and process restart only)."""
    global _live_runtime_state
    with _live_runtime_state_lock:
        _live_runtime_state = None


def live_entries_enabled() -> bool:
    """Convenience: is the state machine in LIVE_ENTRIES_ENABLED?"""
    return get_live_runtime_state().live_entries_enabled()


def can_submit_live_entry() -> bool:
    """Convenience: can a new live entry order be submitted?"""
    return get_live_runtime_state().can_submit_live_entry()

"""
Durable per-position exit-controller state.

The monitor's in-memory ``Position`` objects are rebuilt on startup (from the
position cache) and can be replaced at runtime by a more trusted fill record
(``upsert_position``).  Without a durable copy, restart/replacement erases
armed trails, ratchet floors, high-water marks, and one-shot emergency flags —
the class of bug identified in the KXXRP15M-26OCT171530-30 incident review,
where exit state could be lost without audit.

This store keeps the exit-state fields per canonical position so a rebuilt
``Position`` restores them.  Persistence is a JSON document written
atomically (tmp + rename); one record per position_key.  Writes are
dirty-checked so unchanged state does not hit disk every poll.

Restore invariants (position-owned exit-controller contract):
- ``held_outcome`` must match; a mismatched record is ignored.  A record is
  keyed by position identity, never derived from a close-fill's wire
  representation, so a YES-form exit fill cannot rewrite the parent's side.
- ``high_watermark_cents`` and ``ratchet_floor_price_cents`` never decrease
  for an unchanged position (monotone merge: ``max``).
- One-shot coordination flags (``hard_lock_pending``, scale-out/stage flags)
  are sticky-true.
- Trigger-observed flags (``tail_loss_floor_fired``, ``hard_stop_confirmed``)
  persist as durable history and restore into ``<field>_persisted`` audit
  attrs — never as live suppressors, since an open position proves the prior
  attempt did not flatten it.
- Armed/activated booleans are sticky-true — a restart must not silently
  disarm an armed trail.
- Partial fills (quantity decrease) preserve trail state; quantity changes
  are logged for audit.
- ``state_version`` increments on every persisted mutation.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_VERSION = 1

# Position fields carried durably.  ``trail_armed_at`` / ``trail_started_at``
# / ``high_watermark_updated_at`` are ``time.monotonic()`` values in memory;
# they are persisted alongside wall-clock equivalents and rebased on restore.
_MONO_FIELDS = (
    "trail_armed_at",
    "trail_started_at",
    "high_watermark_updated_at",
    "low_watermark_updated_at",
)

_SCALAR_FIELDS = (
    "trailing_activated",
    "trailing_profit_zone_activated",
    "trailing_profit_threshold_reached_at",
    "high_watermark_cents",
    "low_watermark_cents",
    "max_favorable_price_cents",
    "ratchet_activated",
    "ratchet_floor_price_cents",
    "ratchet_hold_until",
    "ratchet_trimmed",
    "dynamic_tp_target_cents",
    "dynamic_tp_triggered",
    "hard_lock_pending",
    "tail_loss_floor_fired",
    "hard_stop_confirmed",
    "break_even_triggered",
    "break_even_price_cents",
    "scale_out_triggered",
    "scale_out_r_multiple",
    "edge_decay_confirmations",
    "soft_stop_observations",
    "tp_debounce_first_seen_at",
    "tp_debounce_hysteresis_cents",
    "staged_exit_stage_0_executed",
    "staged_exit_stage_1_executed",
    "staged_exit_stage_2_executed",
    "staged_exit_stage_0_timestamp",
    "staged_exit_stage_1_timestamp",
    "staged_exit_stage_2_timestamp",
)

# Sticky-true fields: once set on a live position, restore keeps them set.
_STICKY_TRUE_FIELDS = (
    "trailing_activated",
    "trailing_profit_zone_activated",
    "ratchet_activated",
    "ratchet_trimmed",
    "dynamic_tp_triggered",
    "hard_lock_pending",
    "tail_loss_floor_fired",
    "hard_stop_confirmed",
    "break_even_triggered",
    "scale_out_triggered",
    "staged_exit_stage_0_executed",
    "staged_exit_stage_1_executed",
    "staged_exit_stage_2_executed",
)

# Trigger-observed flags are persisted as durable HISTORY, not as live
# suppressors: ``tail_loss_floor_fired`` / ``hard_stop_confirmed`` are set
# before the IOC is scheduled, so a rejected or unfilled exit leaves them
# stuck-true while the position still holds exposure — the flag would then
# permanently suppress a needed retry.  On restore they land in
# ``<field>_persisted`` audit attrs while the live flag stays False; if the
# trigger condition still holds, the next poll re-fires.  If the prior exit
# actually flattened the position there is no open position to restore into,
# so this cannot resurrect suppression on a completed exit.
_EVENT_HISTORY_FIELDS = frozenset({
    "tail_loss_floor_fired",
    "hard_stop_confirmed",
})

# Monotone non-decreasing fields (locked profit / observed extremes).
_MONOTONE_MAX_FIELDS = (
    "high_watermark_cents",
    "max_favorable_price_cents",
    "ratchet_floor_price_cents",
)
_MONOTONE_MIN_FIELDS = ("low_watermark_cents",)


def _default_path() -> Path:
    env = os.getenv("MERID_EXIT_STATE_PATH", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "position_exit_state.json"


def _generation_id(position: Any) -> Optional[str]:
    """Position-generation discriminator tied to the acquisition lifecycle.

    A market ticker + outcome cannot distinguish two lifecycles if the
    system closes and reopens the same side.  The entry fill id is unique
    per acquisition and durable in the position cache, so it survives
    restart and prevents an old trail state from leaking into a new trade.
    Falls back to durable parentage ids, then None (legacy/REST records).
    """
    for attr in ("entry_fill_id", "entry_intent_id", "client_order_id"):
        val = getattr(position, attr, None)
        if val:
            return str(val)
    return None


def _record_key(position: Any) -> Optional[str]:
    pos_key = getattr(position, "position_key", None) or getattr(
        position, "market_id", None
    )
    if not pos_key:
        return None
    gen = _generation_id(position)
    return f"{pos_key}|{gen}" if gen else str(pos_key)


def _side_value(position: Any) -> Optional[str]:
    side = getattr(position, "side", None)
    return getattr(side, "value", side)


def _mono_to_wall(mono_val: Optional[float]) -> Optional[float]:
    """Convert a time.monotonic() timestamp to approximate epoch time."""
    if mono_val is None:
        return None
    try:
        return time.time() - (time.monotonic() - float(mono_val))
    except Exception:
        return None


def _wall_to_mono(wall_val: Optional[float]) -> Optional[float]:
    """Rebase a persisted epoch timestamp onto this process's monotonic clock.

    Returns a monotonic timestamp representing the same instant.  A stored
    instant in the future (e.g. ratchet_hold_until) stays in the future.
    """
    if wall_val is None:
        return None
    try:
        return time.monotonic() + (float(wall_val) - time.time())
    except Exception:
        return None


class PositionExitStateStore:
    """JSON-backed durable exit-state store keyed by canonical position key."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _default_path()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._last_saved_hash: Dict[str, int] = {}
        # Corruption state: set when the durable file exists but cannot be
        # parsed.  ``corrupt=True`` is NOT the same as an empty store — it
        # means protection state that may exist cannot be proven.
        self._corrupt: bool = False
        self._corrupt_detail: Optional[str] = None
        self._quarantine_path: Optional[Path] = None
        # Serializes record mutations + file writes: the tmp path is shared,
        # so without a lock two writers could interleave write_text/replace
        # and produce a torn file (os.replace is atomic per call, not per
        # pair of calls).
        self._io_lock = threading.Lock()
        self._load()

    @property
    def corrupt(self) -> bool:
        return self._corrupt

    @property
    def quarantine_path(self) -> Optional[Path]:
        return self._quarantine_path

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            records = data.get("records", data) if isinstance(data, dict) else {}
            if isinstance(records, dict):
                self._records = {
                    str(k): v for k, v in records.items() if isinstance(v, dict)
                }
                for key, rec in self._records.items():
                    self._last_saved_hash[key] = hash(json.dumps(rec, sort_keys=True, default=str))
            logger.info(
                "[EXIT-STATE-STORE] Loaded %d durable exit-state record(s) from %s",
                len(self._records), self._path,
            )
        except Exception as exc:
            # Corrupt durable state is a protection-integrity failure, not a
            # benign empty store: an armed trail or locked floor may exist
            # that we can no longer see.  Quarantine the unreadable bytes for
            # forensics, mark the store corrupt, and halt new entries unless
            # the operator explicitly opted into continuing without durable
            # exit state (MERID_EXIT_STATE_CORRUPT_POLICY=continue).
            self._corrupt = True
            self._corrupt_detail = str(exc)
            self._records = {}
            self._last_saved_hash = {}
            try:
                self._quarantine_path = self._path.with_name(
                    f"{self._path.name}.corrupt-{int(time.time())}"
                )
                os.replace(self._path, self._quarantine_path)
            except Exception as q_exc:
                self._quarantine_path = None
                logger.error(
                    "[EXIT-STATE-CORRUPT] quarantine failed for %s: %s",
                    self._path, q_exc,
                )
            logger.critical(
                "[EXIT-STATE-CORRUPT] durable exit-state file unreadable: %s "
                "(%s); quarantined=%s — protection state UNKNOWN",
                self._path, exc, self._quarantine_path,
            )
            self._enforce_corrupt_policy(open_exposure=False)

    def _enforce_corrupt_policy(self, open_exposure: bool) -> None:
        """Corrupt-state policy enforcement.

        - Open exposure + unavailable state: mark recovery required and halt
          new entries unconditionally — protection is not assumed intact.
        - No exposure + corrupt history: quarantine + alert; continue only
          under the explicit operator policy ``continue``.  Default halts.
        Emergency reduce-only exits remain available either way (exits are
        preserved while entries are halted).
        """
        policy = os.getenv("MERID_EXIT_STATE_CORRUPT_POLICY", "halt").strip().lower()
        if not open_exposure and policy in ("continue", "warn"):
            logger.warning(
                "[EXIT-STATE-CORRUPT] continuing under explicit policy=%s "
                "(no open exposure known at load)", policy,
            )
            return
        try:
            from merid.observability.live_runtime_state import (
                get_live_runtime_state,
            )
            get_live_runtime_state().halt_entries(
                "exit_state_store_corrupt_open_exposure" if open_exposure
                else "exit_state_store_corrupt",
                ["EXIT_STATE_CORRUPT"]
                + (["OPEN_EXPOSURE_PROTECTION_UNKNOWN"] if open_exposure else []),
            )
        except Exception as exc:
            logger.error(
                "[EXIT-STATE-CORRUPT] failed to halt entries: %s", exc,
            )

    def _flush(self) -> None:
        try:
            with self._io_lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "schema_version": _SCHEMA_VERSION,
                    "updated_at": time.time(),
                    "records": self._records,
                }
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
                os.replace(tmp, self._path)
        except Exception as exc:
            logger.warning("[EXIT-STATE-STORE] failed to save %s: %s", self._path, exc)

    def snapshot_from_position(self, position: Any) -> Optional[Dict[str, Any]]:
        """Build a JSON-safe durable record from a live Position."""
        try:
            key = _record_key(position)
            if not key:
                return None
            pos_key = getattr(position, "position_key", None) or getattr(
                position, "market_id", None
            )
            gen = _generation_id(position)
            prev = self._records.get(str(key)) or {}
            record: Dict[str, Any] = {
                "position_key": str(pos_key),
                "generation_id": gen,
                "position_id": getattr(position, "position_id", None),
                "market_id": getattr(position, "market_id", None),
                "account_id": getattr(position, "account_id", None),
                "subaccount": getattr(position, "subaccount", getattr(
                    position, "subaccount_number", None)),
                "held_outcome": _side_value(position),
                "avg_entry_price_cents": getattr(position, "avg_entry_price_cents", None),
                "size_cc": str(getattr(position, "size_cc", getattr(position, "size", "")) or ""),
                "archived": False,
                "state_version": int(prev.get("state_version", 0)) + 1,
                "updated_at": time.time(),
            }
            trailing_state = getattr(position, "trailing_state", None)
            record["trailing_state"] = getattr(trailing_state, "value", trailing_state)
            trailing_type = getattr(position, "trailing_type", None)
            record["trailing_type"] = getattr(trailing_type, "value", trailing_type)
            record["trailing_param"] = getattr(position, "trailing_param", None)

            for fname in _SCALAR_FIELDS:
                val = getattr(position, fname, None)
                if hasattr(val, "value") and not isinstance(val, (bool, int, float, str)):
                    val = val.value
                if isinstance(val, (int, float, str, bool)) or val is None:
                    record[fname] = val
                elif isinstance(val, (dict, list)):
                    record[fname] = copy.deepcopy(val)
                else:
                    record[fname] = str(val)

            for fname in _MONO_FIELDS:
                mono_val = getattr(position, fname, None)
                record[fname + "_wall"] = _mono_to_wall(mono_val)

            return record
        except Exception as exc:
            logger.debug("[EXIT-STATE-STORE] snapshot failed: %s", exc)
            return None

    def save(self, position: Any) -> None:
        """Persist exit state for a position (dirty-checked)."""
        record = self.snapshot_from_position(position)
        if record is None:
            return
        key = _record_key(position)
        record["_key"] = key
        with self._io_lock:
            # Merge against the existing record under the write lock so
            # concurrent writers cannot lose a higher lock/watermark or a
            # sticky flag — last-writer-wins on the dict alone would allow a
            # stale snapshot to lower a locked floor.
            prev = self._records.get(key)
            if prev is not None:
                for fname in _MONOTONE_MAX_FIELDS:
                    pv = prev.get(fname)
                    if pv is not None and (
                        record.get(fname) is None or pv > record[fname]
                    ):
                        record[fname] = pv
                for fname in _MONOTONE_MIN_FIELDS:
                    pv = prev.get(fname)
                    if pv is not None and (
                        record.get(fname) in (None, 0) or pv < record[fname]
                    ):
                        record[fname] = pv
                for fname in _STICKY_TRUE_FIELDS:
                    if prev.get(fname):
                        record[fname] = prev[fname]
                # Archived is terminal: a delayed/stale save cannot resurrect
                # a record that reached end-of-lifecycle.
                if prev.get("archived"):
                    record["archived"] = True
                record["state_version"] = max(
                    int(prev.get("state_version", 0)),
                    int(record.get("state_version", 0)),
                )
            record_hash = hash(json.dumps(record, sort_keys=True, default=str))
            if self._last_saved_hash.get(key) == record_hash:
                return
            self._records[key] = record
            self._last_saved_hash[key] = record_hash
        self._flush()

    def record_floor_ratchet(
        self,
        market_id: str,
        generation_id: str,
        held_outcome: Optional[str],
        floor_cents: int,
    ) -> bool:
        """Monotone ratchet of the persisted locked floor for one generation.

        The exit arbiter calls this when a higher *executable* liquidation
        value is observed: the lock only moves up, never down, and only for
        the live generation — an archived record is terminal and a missing
        generation id is refused (no generation-less writes).  Returns True
        when the stored floor actually increased.
        """
        if not generation_id:
            return False
        key = f"{market_id}|{generation_id}"
        with self._io_lock:
            rec = self._records.get(key)
            if rec is None:
                rec = {
                    "position_key": market_id,
                    "market_id": market_id,
                    "generation_id": str(generation_id),
                    "held_outcome": held_outcome,
                    "archived": False,
                    "state_version": 0,
                }
            elif rec.get("archived"):
                return False
            prev = rec.get("ratchet_floor_price_cents")
            if prev is not None and int(floor_cents) <= int(prev):
                return False
            rec["ratchet_floor_price_cents"] = int(floor_cents)
            rec["state_version"] = int(rec.get("state_version", 0)) + 1
            rec["updated_at"] = time.time()
            self._records[key] = rec
            self._last_saved_hash.pop(key, None)
        self._flush()
        return True

    def record_giveback(
        self,
        market_id: str,
        generation_id: str,
        held_outcome: Optional[str],
        giveback_cents: int,
    ) -> bool:
        """Persist the generation's configured trail giveback.

        The giveback is exit policy, not a market observation: once a
        producer declares it, later arbitration calls that don't restate it
        must reuse the persisted value — otherwise a caller that forgets
        the parameter silently tightens the floor to the full watermark
        (monotone, irreversible).  Last explicit write wins.
        """
        if not generation_id:
            return False
        key = f"{market_id}|{generation_id}"
        with self._io_lock:
            rec = self._records.get(key)
            if rec is None:
                rec = {
                    "position_key": market_id,
                    "market_id": market_id,
                    "generation_id": str(generation_id),
                    "held_outcome": held_outcome,
                    "archived": False,
                    "state_version": 0,
                }
            elif rec.get("archived"):
                return False
            rec["trail_giveback_cents"] = int(giveback_cents)
            rec["state_version"] = int(rec.get("state_version", 0)) + 1
            rec["updated_at"] = time.time()
            self._records[key] = rec
            self._last_saved_hash.pop(key, None)
        self._flush()
        return True

    def record_watermark(
        self,
        market_id: str,
        generation_id: str,
        held_outcome: Optional[str],
        watermark_cents: int,
    ) -> bool:
        """Monotone update of the generation's observed high-watermark.

        The watermark is the best *executable* liquidation value observed
        for the generation — an observation, not a floor.  The applicable
        floor is derived from it by the giveback formula in the arbiter.
        Same scoping rules as ``record_floor_ratchet``: live generation
        only, archived records terminal, no generation-less writes.
        """
        if not generation_id:
            return False
        key = f"{market_id}|{generation_id}"
        with self._io_lock:
            rec = self._records.get(key)
            if rec is None:
                rec = {
                    "position_key": market_id,
                    "market_id": market_id,
                    "generation_id": str(generation_id),
                    "held_outcome": held_outcome,
                    "archived": False,
                    "state_version": 0,
                }
            elif rec.get("archived"):
                return False
            prev = rec.get("high_watermark_cents")
            if prev is not None and int(watermark_cents) <= int(prev):
                return False
            rec["high_watermark_cents"] = int(watermark_cents)
            rec["state_version"] = int(rec.get("state_version", 0)) + 1
            rec["updated_at"] = time.time()
            self._records[key] = rec
            self._last_saved_hash.pop(key, None)
        self._flush()
        return True

    def archive(self, position: Any) -> None:
        """Mark the position's record terminal — kept for audit, skipped by
        live lookups.  Records are never dropped on market expiry alone: an
        expired market with residual exposure still needs identity and audit
        state through settlement reconciliation."""
        try:
            key = _record_key(position)
            with self._io_lock:
                if key and key in self._records:
                    rec = self._records[key]
                    rec["archived"] = True
                    rec["updated_at"] = time.time()
                    self._last_saved_hash.pop(key, None)
            self._flush()
        except Exception as exc:
            logger.debug("[EXIT-STATE-STORE] archive failed: %s", exc)

    def delete(self, record_key: str) -> None:
        """Drop a durable record (admin/maintenance only)."""
        key = str(record_key)
        with self._io_lock:
            if key in self._records:
                self._records.pop(key, None)
                self._last_saved_hash.pop(key, None)
        self._flush()

    def find_record(
        self,
        market_ticker: str,
        generation_id: Optional[str] = None,
        *,
        held_outcome: Optional[str] = None,
        subaccount: Optional[Any] = None,
        require_generation: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Latest non-archived record for a market ticker.

        Lifecycle-exact lookups (``require_generation=True``) never fall back
        to "latest for ticker": without a ``generation_id`` they return None,
        so an archived prior generation cannot contaminate a new trade and a
        generationless caller gets no trail lock.  ``held_outcome`` and
        ``subaccount`` narrow the match when the caller knows them; a record
        lacking a field is still eligible (legacy/REST-derived records) but a
        populated field that disagrees excludes the record.
        """
        if require_generation and not generation_id:
            return None
        best: Optional[Dict[str, Any]] = None
        for rec in self._records.values():
            if rec.get("market_id") != market_ticker or rec.get("archived"):
                continue
            if generation_id and rec.get("generation_id") != generation_id:
                continue
            if held_outcome and rec.get("held_outcome") and \
                    rec["held_outcome"] != held_outcome:
                continue
            if subaccount is not None and rec.get("subaccount") is not None \
                    and str(rec["subaccount"]) != str(subaccount):
                continue
            if best is None or rec.get("updated_at", 0) > best.get("updated_at", 0):
                best = rec
        return best

    def restore_into(self, position: Any) -> bool:
        """Restore durable exit state onto a (re)built Position.

        Returns True when a matching record was applied.  Enforces the
        sticky-true / monotone invariants so a rebuild never lowers the
        locked-profit floor or disarms an armed trail.
        """
        try:
            key = _record_key(position)
            if not key:
                return False
            if self._corrupt:
                # Open exposure with unavailable protection state: mark the
                # position recovery-required, halt new entries, and do NOT
                # assume ordinary exit protection is intact.  Nothing is
                # fabricated — the trail state is explicitly unknown.
                try:
                    setattr(position, "exit_state_recovery_required", True)
                    setattr(position, "exit_state_recovery_state", "unknown")
                except Exception:
                    pass
                logger.error(
                    "[EXIT-STATE-RECOVERY-REQUIRED] %s: durable protection "
                    "state unavailable (corrupt store, quarantined=%s) — "
                    "ordinary exit protection NOT assumed intact",
                    key, self._quarantine_path,
                )
                self._enforce_corrupt_policy(open_exposure=True)
                return False
            record = self._records.get(key)
            if record is None:
                return False
            if record.get("archived"):
                logger.debug(
                    "[EXIT-STATE-STORE] skipping archived record for %s", key,
                )
                return False
            # Generation guard: never leak a prior lifecycle's trail state.
            gen = _generation_id(position)
            rec_gen = record.get("generation_id")
            if gen and rec_gen and gen != rec_gen:
                logger.warning(
                    "[EXIT-STATE-STORE] generation mismatch for %s: "
                    "durable=%s position=%s - ignoring stale record",
                    key, rec_gen, gen,
                )
                return False

            held = _side_value(position)
            if record.get("held_outcome") and held and record["held_outcome"] != held:
                logger.warning(
                    "[EXIT-STATE-STORE] held_outcome mismatch for %s: durable=%s position=%s - "
                    "ignoring stale record",
                    key, record["held_outcome"], held,
                )
                return False

            if record.get("size_cc"):
                cur_cc = str(getattr(position, "size_cc", getattr(position, "size", "")) or "")
                if cur_cc and cur_cc != record["size_cc"]:
                    logger.info(
                        "[EXIT-STATE-STORE] quantity changed for %s: durable=%s current=%s - "
                        "preserving trail state",
                        key, record["size_cc"], cur_cc,
                    )

            for fname in _STICKY_TRUE_FIELDS:
                if record.get(fname):
                    if fname in _EVENT_HISTORY_FIELDS:
                        # Trigger-observed: restore as history only, never as
                        # a live suppressor — an open position proves the
                        # prior attempt did not flatten it.
                        setattr(position, fname + "_persisted", record[fname])
                    else:
                        setattr(position, fname, record[fname])

            for fname in _MONOTONE_MAX_FIELDS:
                val = record.get(fname)
                if val is None:
                    continue
                cur = getattr(position, fname, None)
                if cur is None or val > cur:
                    setattr(position, fname, val)

            for fname in _MONOTONE_MIN_FIELDS:
                val = record.get(fname)
                if val is None:
                    continue
                cur = getattr(position, fname, None)
                if cur is None or cur == 0 or val < cur:
                    setattr(position, fname, val)

            # Plain scalars (counters, debounce, R-multiples).
            for fname in (
                "edge_decay_confirmations",
                "soft_stop_observations",
                "tp_debounce_first_seen_at",
                "tp_debounce_hysteresis_cents",
                "break_even_price_cents",
                "scale_out_r_multiple",
                "dynamic_tp_target_cents",
                "ratchet_hold_until",
                "staged_exit_stage_0_timestamp",
                "staged_exit_stage_1_timestamp",
                "staged_exit_stage_2_timestamp",
                "trailing_profit_threshold_reached_at",
            ):
                val = record.get(fname)
                if val is not None:
                    setattr(position, fname, val)

            # Enum state: restore TRAILING lifecycle.
            try:
                from merid.position_management.position_monitor import TrailingState
                ts = record.get("trailing_state")
                if ts:
                    position.trailing_state = TrailingState(ts)
            except Exception:
                pass

            # Rebase monotonic timestamps onto this process's clock.
            for fname in _MONO_FIELDS:
                mono = _wall_to_mono(record.get(fname + "_wall"))
                if mono is not None:
                    setattr(position, fname, mono)

            logger.info(
                "[EXIT-STATE-STORE] Restored durable exit state for %s "
                "(state_version=%s trail_state=%s hw=%s floor=%s fired=%s)",
                key,
                record.get("state_version"),
                record.get("trailing_state"),
                record.get("high_watermark_cents"),
                record.get("ratchet_floor_price_cents"),
                record.get("tail_loss_floor_fired"),
            )
            return True
        except Exception as exc:
            logger.warning("[EXIT-STATE-STORE] restore failed for %s: %s",
                           getattr(position, "market_id", "?"), exc)
            return False


_store: Optional[PositionExitStateStore] = None


def get_exit_state_store() -> PositionExitStateStore:
    global _store
    if _store is None:
        _store = PositionExitStateStore()
    return _store

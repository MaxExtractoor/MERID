"""
Ingress recorder — capture raw WebSocket/REST/RTI bytes at the boundary.

This module writes inbound messages to a JSON-line tape so a later replay
run can feed the same bytes through the production code path.  It is
intentionally off by default and adds near-zero overhead when disabled.

The recorder is the single writer to the process ingress tape: every
inbound byte that the strategy could consume flows through
:func:`record_ingress` and is assigned a monotonic ``capture_seq``.
Replay reads the tape in ``capture_seq`` order and dispatches back to the
same handlers, which is the first step toward making MERID deterministic
across runs.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from merid.data.replay_config_snapshot import capture_snapshot
from utils.logger import get_logger

logger = get_logger("merid.data.ingress_recorder")

_RECORD_FORMAT_VERSION = 1

# Stable source identifiers. These are written into every tape record.
SOURCE_KALSHI_WS = "kalshi_ws"
SOURCE_KALSHI_REST = "kalshi_rest"
SOURCE_CFB_RTI_WS = "cfb_rti_ws"
SOURCE_CFB_RTI_REST = "cfb_rti_rest"


@dataclass
class IngressRecorderConfig:
    """Runtime configuration for the ingress recorder."""

    enabled: bool = False
    base_dir: Path = Path("data/ingress")
    queue_size: int = 100_000
    rotation_minutes: int = 60
    rotation_bytes: int = 1_000_000_000  # 1 GB
    flush_interval_s: float = 1.0
    write_sha256: bool = False


class IngressRecorder:
    """Thread-safe, non-blocking ingress tape recorder.

    Records are pushed to an in-memory queue and flushed to a JSON-line
    tape by a dedicated writer thread.  When the queue is full the newest
    records are dropped rather than blocking the hot path.
    """

    def __init__(self, config: Optional[IngressRecorderConfig] = None):
        self._config = config or IngressRecorderConfig()
        self._enabled = self._config.enabled
        self._dropped_count = 0
        self._written_count = 0
        self._queue: Optional[queue.Queue] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._shutdown: Optional[threading.Event] = None
        self._capture_seq = 0
        self._current_file: Optional[Path] = None
        self._current_file_handle: Optional[Any] = None
        self._current_file_bytes = 0
        self._current_file_start_ts = 0.0
        self._last_flush_ts = 0.0
        self._part = 0
        self._pid = os.getpid()
        self._session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        if self._enabled:
            self._base_dir = self._config.base_dir
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._queue = queue.Queue(maxsize=self._config.queue_size)
            self._shutdown = threading.Event()
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                name="ingress-recorder",
                daemon=True,
            )
            self._writer_thread.start()
            logger.info(
                "[INGRESS-RECORDER] enabled base_dir=%s queue_size=%d "
                "rotation_min=%d rotation_bytes=%d",
                self._base_dir,
                self._config.queue_size,
                self._config.rotation_minutes,
                self._config.rotation_bytes,
            )
        else:
            logger.debug("[INGRESS-RECORDER] disabled")

    def record(
        self,
        source: str,
        payload: Union[str, bytes],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one inbound message. Safe to call from any thread or event loop."""
        if not self._enabled or self._queue is None:
            return
        received_at_ns = time.time_ns()
        try:
            self._queue.put_nowait((source, payload, metadata or {}, received_at_ns))
        except queue.Full:
            self._dropped_count += 1
            if self._dropped_count == 1 or self._dropped_count % 1000 == 0:
                logger.warning(
                    "[INGRESS-RECORDER] queue full — %d records dropped since start",
                    self._dropped_count,
                )

    def flush(self) -> None:
        """Signal the writer to flush and wait briefly for it to drain."""
        if not self._enabled or self._queue is None or self._shutdown is None:
            return
        self._queue.put(None)  # sentinel to wake writer
        deadline = time.monotonic() + 5.0
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        """Shutdown the writer and close the current file."""
        if not self._enabled or self._queue is None or self._shutdown is None:
            return
        self._shutdown.set()
        self._queue.put(None)
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=10.0)
        self._close_file()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def written_count(self) -> int:
        return self._written_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def _writer_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=self._config.flush_interval_s)
            except queue.Empty:
                self._maybe_flush()
                continue
            if item is None:
                self._maybe_flush(force=True)
                if self._shutdown is not None and self._shutdown.is_set():
                    break
                continue
            self._write_record(item)
            self._maybe_flush()

    def _write_record(self, item: tuple) -> None:
        source, raw_payload, metadata, received_at_ns = item
        self._capture_seq += 1
        record: Dict[str, Any] = {
            "v": _RECORD_FORMAT_VERSION,
            "capture_seq": self._capture_seq,
            "source": source,
            "received_at_ns": received_at_ns,
            "metadata": metadata,
        }

        if isinstance(raw_payload, str):
            record["payload"] = raw_payload
            record["encoding"] = "utf-8"
        else:
            try:
                record["payload"] = raw_payload.decode("utf-8")
                record["encoding"] = "utf-8"
            except UnicodeDecodeError:
                record["payload_b64"] = base64.b64encode(raw_payload).decode("ascii")
                record["encoding"] = "base64"

        if self._config.write_sha256:
            try:
                import hashlib

                h = hashlib.sha256()
                body = raw_payload if isinstance(raw_payload, bytes) else raw_payload.encode("utf-8")
                h.update(body)
                record["sha256"] = h.hexdigest()
            except Exception:
                pass

        line = json.dumps(record, default=str, ensure_ascii=False, separators=(",", ":")) + "\n"
        self._ensure_file_open()
        if self._current_file_handle is not None:
            try:
                self._current_file_handle.write(line)
            except Exception as exc:
                logger.error("[INGRESS-RECORDER] write failed: %s", exc)
                return
            self._current_file_bytes += len(line.encode("utf-8"))
            self._written_count += 1

    def _ensure_file_open(self) -> None:
        now = time.monotonic()
        rotation_due = (
            self._current_file is None
            or self._current_file_handle is None
            or (
                self._current_file_start_ts > 0
                and (now - self._current_file_start_ts) > (self._config.rotation_minutes * 60)
            )
            or (self._current_file_bytes >= self._config.rotation_bytes)
        )
        if not rotation_due:
            return

        self._close_file()
        if self._part == 0:
            # First tape file: snapshot the decision-relevant config once.
            try:
                capture_snapshot(self._base_dir)
            except Exception as exc:
                logger.warning("[INGRESS-RECORDER] config snapshot failed: %s", exc)
        self._part += 1
        self._current_file = (
            self._base_dir
            / f"ingress_{self._session_id}_{self._pid}_{self._part:04d}.jsonl"
        )
        try:
            self._current_file_handle = open(
                self._current_file, "a", encoding="utf-8", buffering=1
            )
        except Exception as exc:
            logger.error("[INGRESS-RECORDER] cannot open tape %s: %s", self._current_file, exc)
            self._current_file = None
            self._current_file_handle = None
            return

        self._current_file_bytes = 0
        self._current_file_start_ts = now
        self._last_flush_ts = now
        logger.info("[INGRESS-RECORDER] opened tape %s", self._current_file)

    def _close_file(self) -> None:
        if self._current_file_handle:
            try:
                self._current_file_handle.flush()
                self._current_file_handle.close()
            except Exception as exc:
                logger.warning("[INGRESS-RECORDER] close file error: %s", exc)
            finally:
                self._current_file_handle = None
                self._current_file = None

    def _maybe_flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_flush_ts) < self._config.flush_interval_s:
            return
        if self._current_file_handle:
            try:
                self._current_file_handle.flush()
                self._last_flush_ts = now
            except Exception as exc:
                logger.warning("[INGRESS-RECORDER] flush error: %s", exc)


def _config_from_settings() -> IngressRecorderConfig:
    """Build recorder config from MERID settings / env."""
    from merid.settings import settings

    def _env_bool(name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.lower() in ("1", "true", "yes", "on")

    base_dir = Path(
        os.environ.get("MERID_INGRESS_RECORDING_DIR")
        or str(settings.MERID_INGRESS_RECORDING_DIR or "data/ingress")
    )
    # Never record while replaying — recording the replay would create a
    # self-referential tape and corrupt the capture.
    replay_active = bool(
        os.environ.get("MERID_REPLAY_TAPE") or settings.MERID_REPLAY_TAPE
    )
    enabled = _env_bool(
        "MERID_INGRESS_RECORDING",
        settings.MERID_INGRESS_RECORDING_ENABLED or False,
    )
    return IngressRecorderConfig(
        enabled=enabled and not replay_active,
        base_dir=base_dir,
        queue_size=int(os.environ.get("MERID_INGRESS_QUEUE_SIZE", settings.MERID_INGRESS_QUEUE_SIZE)),
        rotation_minutes=int(os.environ.get("MERID_INGRESS_ROTATION_MINUTES", settings.MERID_INGRESS_ROTATION_MINUTES)),
        rotation_bytes=int(os.environ.get("MERID_INGRESS_ROTATION_BYTES", settings.MERID_INGRESS_ROTATION_BYTES)),
        flush_interval_s=float(os.environ.get("MERID_INGRESS_FLUSH_INTERVAL_S", settings.MERID_INGRESS_FLUSH_INTERVAL_S)),
        write_sha256=_env_bool("MERID_INGRESS_WRITE_SHA256", settings.MERID_INGRESS_WRITE_SHA256),
    )


_recorder: Optional[IngressRecorder] = None
_recorder_lock = threading.Lock()


def get_ingress_recorder() -> IngressRecorder:
    """Return the process-wide ingress recorder singleton."""
    global _recorder
    if _recorder is None:
        with _recorder_lock:
            if _recorder is None:
                _recorder = IngressRecorder(_config_from_settings())
    return _recorder


def record_ingress(
    source: str,
    payload: Union[str, bytes],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one inbound message.  Lazy-init wrapper intended for the hot path."""
    global _recorder
    if _recorder is None:
        _recorder = get_ingress_recorder()
    _recorder.record(source, payload, metadata)


def reset_ingress_recorder_for_tests(recorder: Optional[IngressRecorder] = None) -> None:
    """Replace the singleton recorder; intended for tests only."""
    global _recorder
    with _recorder_lock:
        if _recorder is not None:
            _recorder.close()
        _recorder = recorder


class IngressPlayer:
    """Minimal player for an ingress tape.

    Reads one or more JSON-line tape files, sorts records by capture_seq,
    and yields the raw payload back to the caller.  This is the reading side
    of the capture/replay boundary and is intentionally simple: the actual
    replay driver (Phase 2) will sit on top of it.
    """

    def __init__(self, tape_dir: Union[str, Path]):
        self._tape_dir = Path(tape_dir)

    def iter_records(self) -> List[Dict[str, Any]]:
        """Read all records in the tape directory and sort by capture_seq."""
        records: List[Dict[str, Any]] = []
        for path in sorted(self._tape_dir.glob("ingress_*.jsonl")):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        records.sort(key=lambda r: r.get("capture_seq", 0))
        return records

    @staticmethod
    def read_payload(record: Dict[str, Any]) -> Union[str, bytes]:
        """Extract the raw payload from a tape record."""
        if "payload_b64" in record:
            return base64.b64decode(record["payload_b64"])
        return record.get("payload", "")

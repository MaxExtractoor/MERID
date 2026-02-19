"""Tests for session log persistence and session identity."""

import json
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from core.session_log import (
    record_event,
    get_events,
    clear_events,
    get_session_info,
    flush_now,
    reload_from_disk,
    _flush_to_disk,
    LOG_FILE,
    _SESSION_ID,
)


class TestSessionIdentity:
    """Session ID and info."""

    def test_session_id_is_12_hex(self):
        assert len(_SESSION_ID) == 12
        assert all(c in "0123456789abcdef" for c in _SESSION_ID)

    def test_session_info_has_required_fields(self):
        info = get_session_info()
        assert "session_id" in info
        assert "start_time" in info
        assert "uptime_seconds" in info
        assert info["session_id"] == _SESSION_ID
        assert info["uptime_seconds"] >= 0


class TestSessionEventHint:
    """Events carry hint and session_id."""

    def setup_method(self):
        clear_events()

    def test_event_has_hint(self):
        evt = record_event("gate", "critical", "Test", hint="Do this")
        assert evt.hint == "Do this"
        d = evt.to_dict()
        assert d["hint"] == "Do this"

    def test_event_has_session_id(self):
        evt = record_event("gate", "info", "Test")
        assert evt.session_id == _SESSION_ID
        d = evt.to_dict()
        assert d["session_id"] == _SESSION_ID

    def test_event_without_hint(self):
        evt = record_event("mode", "info", "Test")
        assert evt.hint is None
        assert evt.to_dict()["hint"] is None


class TestPersistence:
    """Flush and reload from disk."""

    def setup_method(self):
        clear_events()
        # Clean up test file
        if LOG_FILE.exists():
            self._backup = LOG_FILE.read_text()
        else:
            self._backup = None

    def teardown_method(self):
        clear_events()
        if self._backup is not None:
            LOG_FILE.write_text(self._backup)
        elif LOG_FILE.exists():
            # Only delete if we created it
            pass

    def test_flush_writes_jsonl(self, tmp_path):
        test_file = tmp_path / "test_session.jsonl"
        with patch("core.session_log.LOG_FILE", test_file):
            record_event("gate", "critical", "Test flush", detail="detail1", hint="hint1")
            record_event("mode", "info", "Mode change")
            _flush_to_disk()

        assert test_file.exists()
        lines = test_file.read_text().strip().split("\n")
        assert len(lines) >= 2

        first = json.loads(lines[0])
        assert first["title"] == "Test flush"
        assert first["hint"] == "hint1"
        assert first["session_id"] == _SESSION_ID

    def test_reload_restores_events(self, tmp_path):
        test_file = tmp_path / "test_reload.jsonl"

        # Write some events
        events = [
            {"timestamp": time.time() - 60, "category": "gate", "severity": "critical",
             "title": "Old event", "detail": None, "hint": "old hint",
             "metadata": {}, "session_id": "prev_session"},
            {"timestamp": time.time() - 30, "category": "mode", "severity": "info",
             "title": "Mode event", "detail": None, "hint": None,
             "metadata": {}, "session_id": "prev_session"},
        ]
        with open(test_file, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        clear_events()
        with patch("core.session_log.LOG_FILE", test_file):
            loaded = reload_from_disk()

        assert loaded == 2
        all_events = get_events(limit=10)
        assert len(all_events) == 2
        assert all_events[0].title == "Mode event"  # newest first

    def test_reload_filters_by_session_id(self, tmp_path):
        test_file = tmp_path / "test_filter.jsonl"

        events = [
            {"timestamp": time.time() - 60, "category": "gate", "severity": "critical",
             "title": "Session A", "detail": None, "hint": None,
             "metadata": {}, "session_id": "aaa"},
            {"timestamp": time.time() - 30, "category": "gate", "severity": "info",
             "title": "Session B", "detail": None, "hint": None,
             "metadata": {}, "session_id": "bbb"},
        ]
        with open(test_file, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        clear_events()
        with patch("core.session_log.LOG_FILE", test_file):
            loaded = reload_from_disk(session_id="aaa")

        assert loaded == 1
        all_events = get_events(limit=10)
        assert all_events[0].title == "Session A"

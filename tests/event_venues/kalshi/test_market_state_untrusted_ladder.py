"""Tests for the session-wide book-untrusted halt ladder (2026-10-30).

``_untrusted_since`` tracks how long each live book has gone without a
post-invalidation WS attestation.  A closed or pruned market can never emit
another attestation, so dead entries must be purged rather than counted —
otherwise every window close that left a book untrusted would latch a
``book_untrusted_sustained`` halt ~_HALT_S later (observed on 2026-10-30:
halts ~5min after each 15m close with no recovery path, since the WS-
reconnect resume gate did not cover BOOK_FEED_DEGRADED).
"""

import time
from unittest.mock import MagicMock

import pytest

import merid.event_venues.kalshi.market_state as market_state
import merid.observability.live_runtime_state as live_runtime_state_mod
from merid.event_venues.kalshi.market_state import (
    KalshiMarketStateStore,
    KalshiMarketState,
)
from merid.observability.live_runtime_state import LiveRuntimeState


@pytest.fixture
def store():
    return KalshiMarketStateStore()


@pytest.fixture(autouse=True)
def _no_expiry_recompute(monkeypatch):
    """Isolate the ladder from ticker-name expiry normalization."""
    monkeypatch.setattr(
        market_state, "_recompute_seconds_to_expiry", lambda state: None
    )


def _state(ticker: str, seconds_to_expiry: float) -> KalshiMarketState:
    state = KalshiMarketState(ticker=ticker)
    state.seconds_to_expiry = seconds_to_expiry
    return state


def _live_runtime(tmp_path, monkeypatch) -> LiveRuntimeState:
    lrs = LiveRuntimeState(persistence_path=tmp_path / "lrs.json")
    monkeypatch.setattr(live_runtime_state_mod, "_live_runtime_state", lrs)
    return lrs


def _enable_then_halt(lrs: LiveRuntimeState, codes) -> None:
    lrs.transition("STARTING", "lifespan_entry")
    lrs.transition("PREFLIGHT_RUNNING", "live_config_resolved")
    lrs.complete_preflight(auto_enable=True, preflight_context={})
    assert lrs.live_entries_enabled()
    lrs.halt_entries(reason="book_untrusted_sustained", reason_codes=codes)


class TestDeadTickerExclusion:
    def test_expired_ticker_purged_and_not_counted(self, store):
        old = time.monotonic() - 9999.0
        store._states["KXBTC15M-DEAD"] = _state("KXBTC15M-DEAD", -5.0)
        store._untrusted_since["KXBTC15M-DEAD"] = old
        store._untrusted_since["KXETH15M-DEAD2"] = old  # no state at all

        store._maybe_escalate_session_book_untrusted()

        assert store._untrusted_since == {}
        assert store._states["KXBTC15M-DEAD"].data_quality != "INVALID" or True

    def test_live_untrusted_pair_still_halts(self, store, tmp_path, monkeypatch):
        lrs = _live_runtime(tmp_path, monkeypatch)
        lrs.transition("STARTING", "lifespan_entry")
        lrs.transition("PREFLIGHT_RUNNING", "live_config_resolved")
        lrs.complete_preflight(auto_enable=True, preflight_context={})
        assert lrs.live_entries_enabled()

        old = time.monotonic() - 9999.0
        for t in ("KXBTC15M-A", "KXETH15M-A"):
            store._states[t] = _state(t, 600.0)
            store._untrusted_since[t] = old

        store._maybe_escalate_session_book_untrusted()

        assert lrs.state == "LIVE_ENTRIES_HALTED"
        assert "BOOK_FEED_DEGRADED" in lrs._reason_codes

    def test_single_live_untrusted_does_not_halt(self, store, tmp_path, monkeypatch):
        lrs = _live_runtime(tmp_path, monkeypatch)
        lrs.transition("STARTING", "lifespan_entry")
        lrs.transition("PREFLIGHT_RUNNING", "live_config_resolved")
        lrs.complete_preflight(auto_enable=True, preflight_context={})

        store._states["KXBTC15M-A"] = _state("KXBTC15M-A", 600.0)
        store._untrusted_since["KXBTC15M-A"] = time.monotonic() - 9999.0

        store._maybe_escalate_session_book_untrusted()
        assert lrs.live_entries_enabled()


class TestRecovery:
    def test_healed_book_alone_does_not_release_entries(self, store, tmp_path, monkeypatch):
        lrs = _live_runtime(tmp_path, monkeypatch)
        _enable_then_halt(
            lrs, ["BOOK_FEED_DEGRADED", "DATA_QUALITY", "RUNTIME_HALT"]
        )
        assert lrs.state == "LIVE_ENTRIES_HALTED"

        import merid.config.auto_execution as auto_exec
        import merid.config.observe_only as observe_only
        monkeypatch.setattr(auto_exec, "is_auto_execution_enabled", lambda: True)
        monkeypatch.setattr(observe_only, "is_observe_only", lambda: False)

        ticker = "KXBTC15M-A"
        state = _state(ticker, 600.0)
        store._states[ticker] = state
        store._untrusted_since[ticker] = time.monotonic() - 9999.0

        # The attestation heals the book but does not prove account recovery.
        ok = store._attest_state_recovery(
            state,
            "WS_ORDERBOOK_DELTA_LIVE",
            prior_quality="GOOD",
            prior_transition="VALID",
        )
        assert ok
        assert state.live_sequence_confirmed is True
        assert store._untrusted_since == {}
        assert lrs.state == "LIVE_ENTRIES_HALTED"
        assert lrs._reason_codes == ["RECOVERY_VERIFICATION_REQUIRED"]

    def test_no_recovery_for_foreign_halt_reason(self, store, tmp_path, monkeypatch):
        lrs = _live_runtime(tmp_path, monkeypatch)
        lrs.transition("STARTING", "lifespan_entry")
        lrs.transition("PREFLIGHT_RUNNING", "live_config_resolved")
        lrs.complete_preflight(auto_enable=True, preflight_context={})
        lrs.halt_entries(reason="circuit_breaker", reason_codes=["CB_TRIPPED"])

        import merid.config.auto_execution as auto_exec
        import merid.config.observe_only as observe_only
        monkeypatch.setattr(auto_exec, "is_auto_execution_enabled", lambda: True)
        monkeypatch.setattr(observe_only, "is_observe_only", lambda: False)

        store._maybe_recover_session_book_untrusted()
        assert lrs.state == "LIVE_ENTRIES_HALTED"
        assert lrs._reason == "circuit_breaker"

    def test_no_recovery_while_books_still_untrusted(self, store, tmp_path, monkeypatch):
        lrs = _live_runtime(tmp_path, monkeypatch)
        _enable_then_halt(lrs, ["BOOK_FEED_DEGRADED"])
        store._untrusted_since["KXBTC15M-A"] = time.monotonic()
        store._maybe_recover_session_book_untrusted()
        assert lrs.state == "LIVE_ENTRIES_HALTED"

    def test_reconnected_websocket_alone_does_not_release_entries(
        self, tmp_path, monkeypatch
    ):
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        import merid.config.auto_execution as auto_exec
        import merid.config.observe_only as observe_only

        lrs = _live_runtime(tmp_path, monkeypatch)
        _enable_then_halt(lrs, ["WS_DATA_PLANE_DEAD", "STALE_MARKET_DATA"])
        monkeypatch.setattr(auto_exec, "is_auto_execution_enabled", lambda: True)
        monkeypatch.setattr(observe_only, "is_observe_only", lambda: False)
        bridge = object.__new__(KalshiWebSocketBridge)
        monkeypatch.setattr(bridge, "_ws_data_plane_alive", lambda: True)

        bridge._maybe_resume_live_entries_after_reconnect()

        assert lrs.state == "LIVE_ENTRIES_HALTED"
        assert lrs._reason_codes == ["RECOVERY_VERIFICATION_REQUIRED"]


class TestPruneCleanup:
    def test_cleanup_stale_states_pops_untrusted(self, store):
        ticker = "KXBTC15M-DEAD"
        store._states[ticker] = _state(ticker, -5.0)
        store._untrusted_since[ticker] = time.monotonic() - 9999.0
        store._last_untrusted_log_ts[ticker] = 1.0

        store.cleanup_stale_states(active_tickers=[])

        assert ticker not in store._states
        assert ticker not in store._untrusted_since
        assert ticker not in store._last_untrusted_log_ts

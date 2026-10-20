"""Regression: window-quota basket coherence (2026-10-20, KXSOL15M-2315).

Live failure replayed: SOL's quota YES attempt dropped pre-wire; the retry
re-derived direction fresh, r60 flicked +2.9bp -> -4.8bp in 13s, and the
lane emitted NO@52 while BTC/ETH/XRP/DOGE all bought YES.  SOL's NO filled
at the local dip and stopped out at -35c during the basket rally; DOGE's
identical NO attempt was saved only by a lucky miss.  The fix records the
emitted side per ticker (window-scoped), exposes a sibling-majority
consensus, and locks retries to the established side.
"""

import json
import os
import time
from datetime import datetime, timezone

import pytest

from merid.prediction import window_quota as wq


W = "26OCT192315"  # the 2315 window stamp shared by all five series


@pytest.fixture()
def state_path(tmp_path):
    return str(tmp_path / "quota.json")


def _seed(path, sides, window=W, ts=None):
    """Write a quota state file with one emitted side per ticker."""
    ts = time.time() if ts is None else float(ts)
    tickers = {}
    for asset, side in sides.items():
        t = f"KX{asset}15M-{window}-15"
        tickers[t] = {"n": 1, "first_ts": ts - 5, "last_ts": ts,
                      "first_side": side, "side": side}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": datetime.now(timezone.utc).date().isoformat(),
                   "count": len(tickers), "tickers": tickers}, f)


class TestSideRecording:
    def test_side_recorded_on_submission(self, state_path):
        wq.record_quota_submission(
            f"KXBTC15M-{W}-15", path=state_path, now=100.0, side="yes"
        )
        assert wq.quota_ticker_locked_side(
            f"KXBTC15M-{W}-15", path=state_path, now=100.0
        ) == "yes"

    def test_no_side_no_lock(self, state_path):
        wq.record_quota_submission(
            f"KXBTC15M-{W}-15", path=state_path, now=100.0
        )
        assert wq.quota_ticker_locked_side(
            f"KXBTC15M-{W}-15", path=state_path, now=100.0
        ) is None

    def test_side_survives_release(self, state_path):
        """The released slot frees the attempt budget, but the direction
        memory persists — this is the exact SOL pre-wire-drop whipsaw."""
        t = f"KXSOL15M-{W}-15"
        wq.record_quota_submission(t, path=state_path, now=100.0, side="yes")
        wq.release_quota_submission(t, path=state_path, now=105.0)
        assert wq.quota_ticker_attempts(t, path=state_path, now=105.0) == 0
        assert wq.quota_ticker_locked_side(
            t, path=state_path, now=105.0
        ) == "yes"

    def test_release_without_side_still_pops(self, state_path):
        t = f"KXSOL15M-{W}-15"
        wq.record_quota_submission(t, path=state_path, now=100.0)
        wq.release_quota_submission(t, path=state_path, now=105.0)
        assert wq.quota_ticker_locked_side(
            t, path=state_path, now=105.0
        ) is None


class TestWindowConsensus:
    def test_majority_yes(self, state_path):
        _seed(state_path, {"BTC": "yes", "XRP": "yes", "DOGE": "no"})
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) == "yes"

    def test_majority_no(self, state_path):
        _seed(state_path, {"BTC": "no", "ETH": "no", "XRP": "yes"})
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) == "no"

    def test_excludes_self(self, state_path):
        _seed(state_path, {"SOL": "no", "BTC": "yes"})
        # SOL's own dissenting record must not count toward consensus.
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) is None  # only 1 sibling vote < min 2

    def test_tie_returns_none(self, state_path):
        _seed(state_path, {"BTC": "yes", "ETH": "no"})
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) is None

    def test_other_windows_ignored(self, state_path):
        _seed(state_path, {"BTC": "no", "ETH": "no"}, window="26OCT192300")
        _seed(state_path, {}, window=W)  # nothing recorded in THIS window
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) is None

    def test_unparsable_ticker_returns_none(self, state_path):
        assert wq.quota_window_consensus("bad", path=state_path) is None

    def test_stale_votes_expire(self, state_path):
        """A majority built minutes ago must not bind a later dissenter —
        the basket may have genuinely turned since."""
        _seed(state_path, {"BTC": "yes", "XRP": "yes"},
              ts=time.time() - 300)
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) is None

    def test_min_votes_configurable(self, state_path, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_CONSENSUS_MIN", "3")
        _seed(state_path, {"BTC": "yes", "XRP": "yes"})
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) is None
        _seed(state_path, {"BTC": "yes", "XRP": "yes", "ETH": "yes"})
        assert wq.quota_window_consensus(
            f"KXSOL15M-{W}-15", path=state_path
        ) == "yes"


class TestOrderingRules:
    """The agent_grid reorder applied to quota_candidate_order output."""

    @staticmethod
    def _apply(dir_pref, argmax, locked, consensus):
        order = wq.quota_candidate_order(dir_pref, argmax)
        # 2026-10-20: consensus is consulted only on retries — a ticker
        # with no recorded side keeps its own argmax/dir read (KXDOGE15M-
        # 0015 flipped a correct argmax=no to YES at the basket top).
        if locked is not None:
            if consensus is not None:
                order = [consensus]
            elif order and order[0] != locked:
                order = [locked] + [s for s in order if s != locked]
        return order

    def test_sol_replay_consensus_overrides_dissent(self):
        """SOL at :43 — dir_pref=no argmax=no but basket emitted yes."""
        assert self._apply("no", "no", locked="yes",
                           consensus="yes") == ["yes"]

    def test_first_emission_ignores_consensus(self):
        """2026-10-20 KXDOGE15M-0015: a first emission (no recorded side)
        keeps its own argmax read even against a recorded majority —
        DOGE's argmax=no was flipped to YES at the top of a basket crash
        and the majority side settled ~1c."""
        assert self._apply("no", "no", locked=None,
                           consensus="yes") == ["no"]

    def test_lock_retries_same_side_first(self):
        """No consensus: a missed YES retries YES, not a noise flip."""
        assert self._apply("no", "no", locked="yes",
                           consensus=None) == ["yes", "no"]

    def test_consensus_overturns_stale_lock(self):
        """Real basket reversal mid-window may flip an established side."""
        assert self._apply("no", "no", locked="yes",
                           consensus="no") == ["no"]

    def test_no_coherence_inputs_unchanged(self):
        assert self._apply("no", "no", locked=None,
                           consensus=None) == ["no"]
        assert self._apply("yes", "no", locked=None,
                           consensus=None) == ["yes", "no"]


class TestBookMomentumVeto:
    """quota_side_book_fell — the 2026-10-20 KXXRP15M-0015 pattern:
    emissions kept buying YES while the ask collapsed 43->39->34."""

    def _hist(self, asks, now=1000.0, gap=8.0):
        # (ts, yes_ask, no_ask) samples, most recent last
        return [
            (now - (len(asks) - 1 - i) * gap, ya, 100 - ya)
            for i, ya in enumerate(asks)
        ]

    def test_collapsing_yes_ask_vetoes(self):
        h = self._hist([43, 40, 37, 34])
        assert wq.quota_side_book_fell(h, "yes", 34.0, now=1000.0)

    def test_stable_ask_does_not_veto(self):
        h = self._hist([58, 58, 59, 58])
        assert not wq.quota_side_book_fell(h, "yes", 58.0, now=1000.0)

    def test_rising_ask_does_not_veto(self):
        h = self._hist([40, 44, 48, 52])
        assert not wq.quota_side_book_fell(h, "yes", 52.0, now=1000.0)

    def test_other_side_unaffected(self):
        # YES ask collapsed but the NO ask rose symmetrically
        h = self._hist([43, 40, 37, 34])
        assert not wq.quota_side_book_fell(h, "no", 66.0, now=1000.0)

    def test_insufficient_samples_no_veto(self):
        h = self._hist([50, 40])
        assert not wq.quota_side_book_fell(h, "yes", 40.0, now=1000.0)

    def test_stale_samples_ignored(self):
        h = self._hist([90, 85, 80], gap=60.0)  # all outside 45s lookback
        h.append((1000.0, 40.0, 60.0))
        assert not wq.quota_side_book_fell(h, "yes", 40.0, now=1000.0)

    def test_drop_under_threshold_no_veto(self):
        h = self._hist([46, 44, 43, 41])  # only 5c drop
        assert not wq.quota_side_book_fell(h, "yes", 41.0, now=1000.0)

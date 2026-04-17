"""Neutral streak tracking for swarm health."""

from __future__ import annotations

from merid.sentiment.neutral_streak_tracker import advance_neutral_streak, reset_streak_state


def test_neutral_streak_accumulates_when_unusable() -> None:
    reset_streak_state()
    r = advance_neutral_streak(
        "BTC",
        "15m",
        consensus_usable=False,
        is_probability_neutral=True,
        dt_minutes=5.0,
        warn_after_minutes=100.0,
    )
    assert r["neutral_streak_minutes"] == 5.0
    r2 = advance_neutral_streak(
        "BTC",
        "15m",
        consensus_usable=False,
        is_probability_neutral=True,
        dt_minutes=5.0,
        warn_after_minutes=100.0,
    )
    assert r2["neutral_streak_minutes"] == 10.0
    reset_streak_state()


def test_warn_when_streak_exceeds_threshold() -> None:
    reset_streak_state()
    r = advance_neutral_streak(
        "ETH",
        "daily",
        consensus_usable=False,
        is_probability_neutral=False,
        dt_minutes=60.0,
        warn_after_minutes=30.0,
    )
    assert r["warn_long_neutral"] is True
    reset_streak_state()

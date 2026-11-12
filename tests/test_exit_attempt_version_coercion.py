"""Regression: exit dispatch must never die on a string version marker.

Live incident 2026-11-12 (KXXRP15M-26NOV112000-00): the REST-synced position
carried ``basis_version='v1'`` (string).  ``int('v1')`` raised inside the
``create_exit_attempt`` call in loop_15m, producing::

    [EXIT-ORDER-ATTEMPT] Failed to create durable exit attempt:
        invalid literal for int() with base 10: 'v1'
    [EXIT-ORDER-ATTEMPT] No durable exit attempt for position=KXXRP15M;
        refusing dispatch

on every monitor eval for the rest of the position's life — the loss_cap exit
at NO-bid 85c never reached the wire and the position rode to settlement.
Version markers are audit metadata; they must never refuse an exit.
"""

from merid.loop_15m import _coerce_attempt_version_int
from merid.position_management.position import Position, _coerce_version_int


def test_coerce_attempt_version_int_values():
    assert _coerce_attempt_version_int("v1") == 1
    assert _coerce_attempt_version_int("v2") == 2
    assert _coerce_attempt_version_int("2026-10-05") == 2026
    assert _coerce_attempt_version_int(3) == 3
    assert _coerce_attempt_version_int(2.0) == 2
    assert _coerce_attempt_version_int(True) == 1
    assert _coerce_attempt_version_int(None) == 0
    assert _coerce_attempt_version_int("") == 0
    assert _coerce_attempt_version_int("abc") == 0
    assert _coerce_attempt_version_int({"v": 1}) == 0


def test_position_coerce_version_int_matches_loop_helper():
    for value in ("v1", "v10", "2026-10-05", 0, 1, 7, 1.9, None, "", "x"):
        assert _coerce_version_int(value) == _coerce_attempt_version_int(value), value


def test_position_from_dict_coerces_string_basis_version():
    pos = Position.from_dict({
        "position_id": "KXXRP15M-26NOV112000-00",
        "market_id": "KXXRP15M-26NOV112000-00",
        "side": "no",
        "size": 3,
        "avg_entry_price_cents": 95,
        "basis_version": "v1",
    })
    assert pos.basis_version == 1
    assert isinstance(pos.basis_version, int)


def test_position_from_dict_numeric_basis_version_unchanged():
    pos = Position.from_dict({
        "position_id": "KXXRP15M-26NOV112000-00",
        "market_id": "KXXRP15M-26NOV112000-00",
        "side": "no",
        "size": 3,
        "avg_entry_price_cents": 95,
        "basis_version": 2,
    })
    assert pos.basis_version == 2

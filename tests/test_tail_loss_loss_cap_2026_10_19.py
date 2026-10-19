"""Tail-loss floor must route as LOSS_CAP, not HARD_STOP.

2026-10-19 incident: the position monitor's catastrophic tail-loss floor
(``MERID_TAIL_LOSS_DROP_CENTS``/``FLOOR_CENTS`` salvage) emitted
``trigger_reason="HARD_STOP"`` candidates.  The 2026-10-17 price-stop
shadow freeze puts ``HARD_STOP`` in ``SHADOWED_PRICE_STOP_TRIGGERS`` —
record-only, never submitted — so every tail-floor salvage died at the
shadow gate while ``tail_loss_floor_fired`` latched true:

* KXXRP15M-26OCT191630-30 YES@70: floor emitted exec=39c at tte=307s,
  shadowed, settled at ~0 (realized -71c instead of ~-31c).
* KXDOGE15M-26OCT191630-30 YES@69: floor emitted exec=35c at tte=307s,
  shadowed, settled at ~0 (-70c instead of ~-34c).
* KXETH15M-26OCT191645-45 NO@36: floor emitted exec=18c at tte=413s,
  shadowed, while the position was still live.

The taxonomy was already built for this: ``LOSS_CAP`` is the non-shadowed
mandatory-risk trigger (``_MANDATORY_RISK_TRIGGER_REASONS``,
``LOSS_SELL_EXEMPT_TRIGGERS``, ``_OPERATIONAL_TRIGGER_REASONS``,
firewall ``POSITION_LOSS_BUDGET``, ``MERID_EXIT_ALLOWED_REASONS``,
envelope/veto exempt).  The floor now emits LOSS_CAP; these tests pin
the trigger classification, its membership in the price-stop set (so the
settlement-phase gate and fair-value bypass treat it as an explicit
price trigger), and the exit-reason mapping (without which it fell back
to STOP_LOSS -> canonical stop_loss -> discretionary -> dead again).
"""

import inspect

import merid.event_venues.kalshi.stop_candidate as sc
import merid.position_management.position_monitor as pm
from merid.event_venues.kalshi.settlement_aligned_exit import (
    ExitClass,
    classify_trigger_reason,
)


def test_loss_cap_is_not_shadowed():
    """LOSS_CAP must never sit in the record-only trigger set."""
    assert "LOSS_CAP" not in sc.SHADOWED_PRICE_STOP_TRIGGERS


def test_hard_stop_remains_shadowed():
    """The ordinary armed bracket stop stays shadow-only — only the
    catastrophic tail floor was re-classed, not the price-stop freeze."""
    assert "HARD_STOP" in sc.SHADOWED_PRICE_STOP_TRIGGERS


def test_loss_cap_is_price_stop_trigger():
    """Tail-floor emissions carry no edge persistence or fair value;
    they must take the explicit-price-trigger branches downstream."""
    assert "LOSS_CAP" in sc.PRICE_STOP_TRIGGER_REASONS


def test_loss_cap_classifies_operational():
    """The submit path's classify gate must see LOSS_CAP as a
    live-allowed class (not UNKNOWN — that fails closed, and not
    DISCRETIONARY — that is observe-only while the EV gate is off)."""
    cls = classify_trigger_reason("LOSS_CAP")
    assert cls.live_allowed, f"LOSS_CAP classified {cls}"


def test_loss_cap_maps_to_loss_cap_exit_reason():
    """Without the mapping the intent exit_reason defaulted to
    STOP_LOSS -> canonical stop_loss -> discretionary -> gated again."""
    assert sc._STOP_TRIGGER_TO_EXIT_REASON.get("LOSS_CAP") == "LOSS_CAP"


def test_settlement_phase_allows_loss_cap_without_edge_persistence():
    """The monitor emits consecutive_edge_below=0; outside the close
    window the candidate must still be allowed through."""
    ok, reason = sc.settlement_phase_allows_stop(
        300.0, "LOSS_CAP", consecutive_edge_below=0
    )
    assert ok, reason


def test_settlement_phase_blocks_loss_cap_inside_close_window():
    """The close-window hold policy still applies to LOSS_CAP."""
    ok, reason = sc.settlement_phase_allows_stop(
        30.0, "LOSS_CAP", consecutive_edge_below=0
    )
    assert not ok
    assert "settlement_close_window" in reason


def test_tail_floor_emits_loss_cap_trigger():
    """Source-level pin: the position monitor's tail-loss floor block
    must emit trigger_reason="LOSS_CAP" (the armed bracket stop-loss at
    ~line 5984 keeps its deliberate HARD_STOP/shadowed class)."""
    src = inspect.getsource(pm)
    floor_idx = src.index("TAIL-LOSS-FLOOR triggered")
    # The emit block sits within ~2.5k chars after the trigger log line.
    emit_block = src[floor_idx:floor_idx + 4000]
    assert 'trigger_reason="LOSS_CAP"' in emit_block
    assert 'trigger_reason="HARD_STOP"' not in emit_block


def test_loss_sell_exempt_includes_loss_cap():
    """A catastrophic salvage sells below entry by construction — it
    must stay exempt from the profit-only breakeven floor."""
    assert "LOSS_CAP" in sc.LOSS_SELL_EXEMPT_TRIGGERS

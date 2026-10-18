"""Round-trip test for PositionExitStateStore: save -> 'restart' -> restore."""
import json, os, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_tmp = Path(tempfile.mkdtemp()) / "position_exit_state.json"
os.environ["MERID_EXIT_STATE_PATH"] = str(_tmp)
# Quarantine side-effects: no-exposure corrupt load continues under explicit
# policy; the halt path (if reached) writes to a throwaway state file.
os.environ["MERID_EXIT_STATE_CORRUPT_POLICY"] = "continue"
os.environ["MERID_LIVE_RUNTIME_STATE_PATH"] = str(
    _tmp.parent / "live_runtime_state_test.json")

from merid.position_management.position_exit_state import (
    PositionExitStateStore, get_exit_state_store,
)


class _Side:
    def __init__(self, v): self.value = v


class _TS:
    def __init__(self, v): self.value = v


class FakePos:
    def __init__(self, side="no", gen="fill_gen_1"):
        self.position_id = "KXXRP15M-TEST-1"
        self.market_id = "KXXRP15M-TEST-1"
        self.position_key = "kalshi:KXXRP15M-TEST-1"
        self.entry_fill_id = gen
        self.side = _Side(side)
        self.size = 3
        self.avg_entry_price_cents = 32
        self.trailing_activated = False
        self.trailing_profit_zone_activated = False
        self.trailing_profit_threshold_reached_at = None
        self.trailing_state = _TS("inactive")
        self.trailing_type = _TS("fixed_cents")
        self.trailing_param = 3
        self.high_watermark_cents = 0
        self.low_watermark_cents = 0
        self.max_favorable_price_cents = 0
        self.ratchet_activated = False
        self.ratchet_floor_price_cents = None
        self.ratchet_hold_until = None
        self.ratchet_trimmed = False
        self.dynamic_tp_target_cents = None
        self.dynamic_tp_triggered = False
        self.hard_lock_pending = None
        self.tail_loss_floor_fired = False
        self.hard_stop_confirmed = False
        self.break_even_triggered = False
        self.break_even_price_cents = None
        self.scale_out_triggered = False
        self.scale_out_r_multiple = None
        self.edge_decay_confirmations = 0
        self.soft_stop_observations = 0
        self.tp_debounce_first_seen_at = None
        self.tp_debounce_hysteresis_cents = None
        self.staged_exit_stage_0_executed = False
        self.staged_exit_stage_1_executed = False
        self.staged_exit_stage_2_executed = False
        self.staged_exit_stage_0_timestamp = None
        self.staged_exit_stage_1_timestamp = None
        self.staged_exit_stage_2_timestamp = None
        self.trail_armed_at = None
        self.trail_started_at = None
        self.high_watermark_updated_at = None
        self.low_watermark_updated_at = None


store = get_exit_state_store()

# Simulate a live position that armed and ratcheted.
p = FakePos(side="no")
p.trailing_activated = True
p.trailing_state = _TS("trailing")
p.trailing_profit_threshold_reached_at = time.time() - 30
p.high_watermark_cents = 69
p.max_favorable_price_cents = 69
p.ratchet_floor_price_cents = 55
p.tail_loss_floor_fired = True
p.hard_lock_pending = {"state": "PENDING", "trigger_bid_cents": 80}
p.soft_stop_observations = 2
p.trail_armed_at = time.monotonic() - 20
store.save(p)
assert _tmp.exists(), "durable file not written"

# 'Restart': fresh store instance reads the file.
store2 = PositionExitStateStore(path=_tmp)
fresh = FakePos(side="no")
ok = store2.restore_into(fresh)
assert ok, "restore returned False"
assert fresh.trailing_activated is True
assert fresh.high_watermark_cents == 69, fresh.high_watermark_cents
assert fresh.ratchet_floor_price_cents == 55
# Trigger-observed flags restore as history, never as live suppressors.
assert fresh.tail_loss_floor_fired is False
assert fresh.tail_loss_floor_fired_persisted is True
assert isinstance(fresh.hard_lock_pending, dict), fresh.hard_lock_pending
assert fresh.soft_stop_observations == 2
assert fresh.trail_armed_at is not None

# Invariant: held_outcome mismatch -> ignored.
wrong_side = FakePos(side="yes")
assert store2.restore_into(wrong_side) is False
assert wrong_side.trailing_activated is False

# Invariant: position-generation isolation â€” a same-ticker/same-side re-entry
# (new acquisition lifecycle) must not inherit the old trail state.
new_gen = FakePos(side="no", gen="fill_gen_2")
assert store2.restore_into(new_gen) is False
assert new_gen.trailing_activated is False
assert new_gen.high_watermark_cents == 0
assert new_gen.tail_loss_floor_fired is False

# Invariant: monotone merge never lowers the floor.
fresh.ratchet_floor_price_cents = 60
store2.save(fresh)  # durable record now has floor=60
key = "kalshi:KXXRP15M-TEST-1|fill_gen_1"
store2._records[key]["ratchet_floor_price_cents"] = 55
store3_pos = FakePos(side="no")
store3_pos.ratchet_floor_price_cents = 60
store2.restore_into(store3_pos)
assert store3_pos.ratchet_floor_price_cents == 60, store3_pos.ratchet_floor_price_cents

# Archive on terminal removal: record kept for audit, skipped on restore.
key = f"{fresh.position_key}|fill_gen_1"
store2.archive(fresh)
assert store2._records[key]["archived"] is True
revived = FakePos(side="no", gen="fill_gen_1")
assert store2.restore_into(revived) is False  # archived -> not restored

# find_record: live lookup for the firewall's trail-lock merge.
# (durable floor is 55 â€” the monotone test overwrote it after save())
store2._records[key]["archived"] = False
rec = store2.find_record("KXXRP15M-TEST-1")
assert rec is not None and rec["ratchet_floor_price_cents"] == 55
rec_none = store2.find_record("KXXRP15M-TEST-1", generation_id="fill_gen_2")
assert rec_none is None
store2._records[key]["archived"] = True
assert store2.find_record("KXXRP15M-TEST-1") is None

store2.delete(key)
assert key not in store2._records
assert _tmp.exists()

# --- Concurrent writers: interleaved saves must keep file valid JSON ------
import threading
store3 = PositionExitStateStore(path=_tmp)
errs = []
def writer(n):
    try:
        for i in range(30):
            w = FakePos(side="no", gen=f"gen_w{n}")
            w.market_id = f"KXT{n}-T"
            w.position_key = f"kalshi:KXT{n}-T"
            w.position_id = w.market_id
            w.high_watermark_cents = 50 + i
            w.ratchet_floor_price_cents = 40 + i
            store3.save(w)
    except Exception as e:
        errs.append(e)
threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
for t in threads: t.start()
for t in threads: t.join()
assert not errs, errs
# File must remain valid JSON after interleaved writes.
parsed = json.loads(_tmp.read_text())
assert isinstance(parsed.get("records"), dict)
for n in range(4):
    rec = store3.find_record(f"KXT{n}-T", generation_id=f"gen_w{n}")
    assert rec is not None and rec["ratchet_floor_price_cents"] == 69, rec

# --- Stale save must not resurrect an archived record ----------------------
stale = FakePos(side="no", gen="gen_w0")
stale.market_id = "KXT0-T"; stale.position_key = "kalshi:KXT0-T"
stale.high_watermark_cents = 10
store3.save(stale)
arch_key = "kalshi:KXT0-T|gen_w0"
store3.archive(stale)
assert store3._records[arch_key]["archived"] is True
stale2 = FakePos(side="no", gen="gen_w0")
stale2.market_id = "KXT0-T"; stale2.position_key = "kalshi:KXT0-T"
stale2.high_watermark_cents = 5  # delayed save with LOWER watermark
store3.save(stale2)
rec = store3._records[arch_key]
assert rec["archived"] is True, "stale save resurrected archived record"
assert rec["high_watermark_cents"] == 79, (
    f"monotone merge lost max watermark: {rec['high_watermark_cents']}")

# --- Corrupt / incompatible state file -> quarantine + recovery-required ---
_tmp.write_text("{not valid json!!!")
store_bad = PositionExitStateStore(path=_tmp)
assert store_bad.corrupt is True, "corrupt file not flagged"
assert store_bad._records == {}
assert not _tmp.exists(), "corrupt file not quarantined"
assert store_bad.quarantine_path is not None and store_bad.quarantine_path.exists()
assert store_bad.find_record("KXT0-T") is None
# Open exposure + unavailable state -> recovery required; protection unknown.
fresh2 = FakePos(side="no", gen="gen_w0"); fresh2.market_id = "KXT0-T"
fresh2.position_key = "kalshi:KXT0-T"
assert store_bad.restore_into(fresh2) is False
assert fresh2.exit_state_recovery_required is True
assert fresh2.exit_state_recovery_state == "unknown"
rt = json.loads(
    Path(os.environ["MERID_LIVE_RUNTIME_STATE_PATH"]).read_text())
assert rt["state"] == "LIVE_ENTRIES_HALTED", rt
assert "EXIT_STATE_CORRUPT" in rt.get("reason_codes", []), rt

# --- Crash-mid-write: .tmp residue must not corrupt the main file ---------
_tmp.write_text(json.dumps({"schema_version": 1, "records": {}}))
_tmp.with_suffix(".tmp").write_text("{partial write")
store_ok = PositionExitStateStore(path=_tmp)
assert store_ok._records == {}

print("EXIT STATE ROUND-TRIP: ALL CHECKS PASSED")


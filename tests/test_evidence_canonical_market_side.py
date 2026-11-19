"""Canonical market-side grouping + evidence provenance tests (2026-11-19).

Defect being pinned: ``mkey`` was ``ticker`` for 'fill' rows but
``ticker|side`` for 'veto'/'ebias' rows, so one market-side could occupy
two normalization groups in ``build_cells`` and carry ~2x effective
weight.  v2 unifies every source on ``venue-market-side`` =
``ticker|side``; these tests assert the per-cell bounded-weight invariant
and the observed-vs-counterfactual provenance fields.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from merid.execution.evidence_outcome_store import (
    EvidenceOutcomeStore,
    store_path_for,
)
from merid.prediction.evidence_policy import build_cells

NOW = 1_800_000_000.0


def _row(src, mkey, side="yes", px=50.0, tte=400.0, age_s=60.0,
         asset="BTC", settled_yes=1, fill_px=None, did=None,
         decision_ts=None):
    return {
        "src": src,
        "asset": asset,
        "side": side,
        "ticker": mkey.split("|")[0],
        "mkey": mkey,
        "decision_id": did or f"{src}-{mkey}-{age_s}",
        "entry_cents": px,
        "fill_px_cents": fill_px,
        "settled_yes": settled_yes,
        "settled_at": NOW - age_s,
        "decision_ts": decision_ts if decision_ts is not None else NOW - age_s,
        "seconds_to_close": tte,
    }


def _only_cell(cells):
    assert len(cells) == 1, cells.keys()
    return next(iter(cells.values()))


# ---------------------------------------------------------------------------
# build_cells: one market-side shares one bounded weight across sources
# ---------------------------------------------------------------------------

def test_fill_and_veto_same_market_side_share_one_weight():
    """ENTER + veto rows on the same ticker|side must total ~1 n_eff."""
    mkey = "KXBTC15M-T1|yes"
    rows = (
        [_row("fill", mkey, did=f"f{i}") for i in range(5)]
        + [_row("veto", mkey, did=f"v{i}") for i in range(7)]
    )
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    c = _only_cell(cells)
    assert c["n_markets"] == 1
    assert c["n_raw"] == 12
    assert c["n_fill"] == 5 and c["n_veto"] == 7
    # Bounded: the whole market-side contributes ~its newest decay (~1),
    # not ~2 as it did when fill rows keyed on bare ticker.
    assert 0.9 < c["n_eff"] <= 1.0001


def test_legacy_split_keys_would_double_count():
    """Contrast fixture: the OLD asymmetric keys give ~2x weight."""
    rows = (
        [_row("fill", "KXBTC15M-T1", did=f"f{i}") for i in range(5)]
        + [_row("veto", "KXBTC15M-T1|yes", did=f"v{i}") for i in range(7)]
    )
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    c = _only_cell(cells)
    assert c["n_markets"] == 2  # two phantom market-sides
    assert 1.9 < c["n_eff"] <= 2.0001


def test_multiple_observed_partial_fills_count_rows_not_markets():
    mkey = "KXETH15M-T2|no"
    rows = [
        _row("fill", mkey, side="no", fill_px=41.0, did=f"p{i}", age_s=60 + i)
        for i in range(3)
    ]
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    c = _only_cell(cells)
    assert c["n_observed_fill"] == 3          # rows/events
    assert c["n_observed_fill_markets"] == 1  # distinct market-sides
    assert c["n_markets"] == 1
    assert c["n_eff"] <= 1.0001


def test_observed_fill_plus_counterfactuals_still_one_weight():
    mkey = "KXSOL15M-T3|yes"
    rows = (
        [_row("fill", mkey, fill_px=52.0, did="obs")]
        + [_row("fill", mkey, did=f"cf{i}") for i in range(4)]
        + [_row("veto", mkey, did=f"v{i}") for i in range(6)]
    )
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    c = _only_cell(cells)
    assert c["n_observed_fill"] == 1
    assert c["n_observed_fill_markets"] == 1
    assert c["n_markets"] == 1
    assert c["n_eff"] <= 1.0001


def test_decay_weights_newest_row_dominates():
    """n_eff counts market-sides (~1 regardless of spread); decay shows
    in the win/loss split -- a 30d-old row at H=7d contributes ~5%."""
    mkey = "KXXRP15M-T4|yes"
    rows = [
        # old row WON (side yes == settled_yes), new row LOST.
        _row("fill", mkey, did="old", age_s=30 * 86400, settled_yes=1),
        _row("fill", mkey, did="new", age_s=60, settled_yes=0),
    ]
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    c = _only_cell(cells)
    assert c["n_raw"] == 2
    assert c["n_markets"] == 1
    assert 0.9 < c["n_eff"] <= 1.0001
    # Old win share ~0.05 -> cell reads ~95% loss, not 50/50.
    assert c["w"] < 0.10 and c["l"] > 0.85


def test_market_side_split_across_cells_shares_weight():
    """Same mkey in two price buckets: total weight across cells ~1."""
    mkey = "KXDOGE15M-T5|yes"
    rows = (
        [_row("fill", mkey, px=20.0, did=f"a{i}") for i in range(3)]
        + [_row("veto", mkey, px=80.0, did=f"b{i}") for i in range(3)]
    )
    cells = build_cells(rows, half_life_days=7.0, now=NOW)
    assert len(cells) == 2
    total = sum(c["n_eff"] for c in cells.values())
    assert 0.9 < total <= 1.0001
    for c in cells.values():
        assert c["n_markets"] == 1


# ---------------------------------------------------------------------------
# Store: canonical keys on extract, migration, provenance fields
# ---------------------------------------------------------------------------

@pytest.fixture()
def audit_db(tmp_path):
    path = tmp_path / "audit.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE strategy_decisions (
          decision_id TEXT PRIMARY KEY, decision_ts REAL,
          observed_at_ts REAL, decision_ts_iso TEXT,
          strategy_name TEXT, strategy_version TEXT, model_version TEXT,
          config_version TEXT, ticker TEXT, asset TEXT, close_ts REAL,
          close_ts_iso TEXT, seconds_to_close REAL,
          settlement_reference TEXT, settlement_rule_version TEXT,
          selected_side TEXT, decision TEXT, primary_reason_code TEXT,
          created_at REAL, admission_lane TEXT,
          is_eligible_for_research INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE strategy_decision_side_ev (
          decision_id TEXT, side TEXT,
          executable_entry_price_cents REAL, decision_lane TEXT,
          calibrated_probability REAL, expected_entry_slippage_cents REAL,
          exclusion_reason TEXT, passed_edge_gate INTEGER,
          counterfactual_execution_status TEXT,
          expected_net_ev_cents REAL, counterfactual_entry_source TEXT,
          counterfactual_assumed_filled_contracts REAL
        );
        CREATE TABLE strategy_decision_outcomes (
          decision_id TEXT PRIMARY KEY, settled_at REAL, settled_yes INTEGER,
          outcome_status TEXT, actual_fill_price_cents REAL,
          counterfactual_yes_pnl_cents REAL,
          counterfactual_no_pnl_cents REAL
        );
        CREATE INDEX idx_outcomes_settled_at
          ON strategy_decision_outcomes(settled_at);
        """
    )
    conn.commit()
    conn.close()
    return path


def _seed(conn, did, asset, side, px, settled_at, settled_yes,
          decision="ENTER", actual_fill=None):
    conn.execute(
        "INSERT INTO strategy_decisions (decision_id, decision_ts, ticker,"
        " asset, seconds_to_close, selected_side, decision)"
        " VALUES (?,?,?,?,?,?,?)",
        (did, settled_at, f"KX{asset}15M-{did}", asset, 400.0,
         side, decision),
    )
    conn.execute(
        "INSERT INTO strategy_decision_side_ev (decision_id, side,"
        " executable_entry_price_cents, counterfactual_execution_status)"
        " VALUES (?,?,?,?)",
        (did, side, px, "FULLY_EXECUTABLE"),
    )
    conn.execute(
        "INSERT INTO strategy_decision_outcomes (decision_id, settled_at,"
        " settled_yes, outcome_status, actual_fill_price_cents)"
        " VALUES (?,?,?,'SETTLED',?)",
        (did, settled_at, settled_yes, actual_fill),
    )


def _rw(path):
    return sqlite3.connect(str(path))


def test_extract_fill_mkey_is_canonical(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed(audit, "f1", "BTC", "no", 55, now - 100, 0)
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = sqlite3.connect(f"file:{audit_db}?mode=ro", uri=True)
    audit.row_factory = sqlite3.Row
    store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()
    fill = next(r for r in store.read_since(sconn, now - 86400)
                if r["src"] == "fill")
    assert fill["mkey"] == "KXBTC15M-f1|no"
    sconn.close()


def test_v1_store_migrates_to_canonical_keys(tmp_path, audit_db):
    """Rows stored under v1 keys are re-keyed in place on connect."""
    now = time.time()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    # Simulate v1 rows: fill keyed on bare ticker, veto on ticker|side,
    # version state absent (defaults to 1).
    for i, (src, mkey) in enumerate([
        ("fill", "KXBTC15M-old1"), ("veto", "KXBTC15M-old1|yes"),
        ("veto", "KXBTC15M-old2|no"),
    ]):
        sconn.execute(
            "INSERT INTO evidence_outcome_rows (row_key, src, asset, side,"
            " ticker, decision_id, mkey, entry_cents, settled_yes,"
            " settled_at, decision_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"{src}-{i}", src, "BTC", "yes" if "|yes" in mkey or src == "fill"
             else "no",
             mkey.split("|")[0], f"d{i}", mkey, 50.0, 1, now - 100, now - 100),
        )
    sconn.commit()
    # _connect() already migrated the empty store to v2; rewind the
    # version marker so the seeded v1 rows exercise the migration.
    sconn.execute(
        "UPDATE evidence_extract_state SET v='1' "
        "WHERE k='evidence_key_version'"
    )
    sconn.commit()
    sconn.close()

    # Reconnect: migration must run exactly once and re-key v1 rows.
    store2 = EvidenceOutcomeStore(store_path_for(audit_db))
    s2 = store2._connect()
    s2.row_factory = sqlite3.Row
    assert store2.key_version(s2) == 2
    mk = {r["decision_id"]: r["mkey"] for r in
          s2.execute("SELECT decision_id, mkey FROM evidence_outcome_rows")}
    assert mk["d0"] == "KXBTC15M-old1|yes"   # fill re-keyed ticker -> ticker|side
    assert mk["d1"] == "KXBTC15M-old1|yes"   # veto already canonical
    assert mk["d2"] == "KXBTC15M-old2|no"    # veto already canonical
    # row_keys rebuilt consistently -> re-extraction stays idempotent
    rk = {r["decision_id"]: r["row_key"] for r in
          s2.execute("SELECT decision_id, row_key FROM evidence_outcome_rows")}
    assert rk["d0"].endswith("KXBTC15M-old1|yes")
    # Idempotent: second connect is a no-op.
    s2.close()
    store3 = EvidenceOutcomeStore(store_path_for(audit_db))
    s3 = store3._connect()
    s3.row_factory = sqlite3.Row
    assert store3.key_version(s3) == 2
    s3.close()


def test_read_since_provenance_fields(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed(audit, "obs", "BTC", "yes", 50, now - 100, 1, actual_fill=49)
    _seed(audit, "hyp", "ETH", "no", 40, now - 100, 0)
    _seed(audit, "v1", "SOL", "yes", 60, now - 100, 1,
          decision="NO_TRADE")
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = sqlite3.connect(f"file:{audit_db}?mode=ro", uri=True)
    audit.row_factory = sqlite3.Row
    store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()
    rows = {r["decision_id"]: r
            for r in store.read_since(sconn, now - 86400)}

    obs = rows["obs"]
    assert obs["src"] == "fill"
    assert obs["evidence_kind"] == "observed_fill"
    assert obs["price_source"] == "actual_fill"
    assert obs["execution_observed"] is True

    # ENTER decision with no actual fill: executable-price counterfactual,
    # must NOT masquerade as observed execution.
    hyp = rows["hyp"]
    assert hyp["src"] == "fill" and hyp["fill_px_cents"] is None
    assert hyp["evidence_kind"] == "counterfactual_taker"
    assert hyp["price_source"] == "executable_fallback"
    assert hyp["execution_observed"] is False

    veto = rows["v1"]
    assert veto["src"] == "veto"
    assert veto["evidence_kind"] == "counterfactual_taker"
    assert veto["price_source"] == "counterfactual_executable"
    assert veto["execution_observed"] is False
    sconn.close()


def test_ebias_tagged_counterfactual_and_excluded_from_cells(tmp_path,
                                                           audit_db):
    """ebias rows are edge-bias diagnostics, never admission evidence."""
    now = time.time()
    audit = _rw(audit_db)
    conn = audit
    conn.execute(
        "INSERT INTO strategy_decisions (decision_id, decision_ts, ticker,"
        " asset, seconds_to_close, selected_side, decision)"
        " VALUES ('e1', ?, 'KXBTC15M-e1', 'BTC', 400.0, 'yes', 'NO_TRADE')",
        (now - 100,),
    )
    conn.execute(
        "INSERT INTO strategy_decision_side_ev (decision_id, side,"
        " executable_entry_price_cents, counterfactual_execution_status,"
        " expected_net_ev_cents) VALUES ('e1','yes',50,'FULLY_EXECUTABLE',2.5)",
    )
    conn.execute(
        "INSERT INTO strategy_decision_outcomes (decision_id, settled_at,"
        " settled_yes, outcome_status) VALUES ('e1', ?, 1, 'SETTLED')",
        (now - 100,),
    )
    conn.commit()
    conn.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = sqlite3.connect(f"file:{audit_db}?mode=ro", uri=True)
    audit.row_factory = sqlite3.Row
    store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()
    rows = store.read_since(sconn, now - 86400)
    eb = [r for r in rows if r["src"] == "ebias"]
    assert len(eb) == 1
    assert eb[0]["evidence_kind"] == "counterfactual_taker"
    assert eb[0]["execution_observed"] is False
    sconn.close()

def test_read_since_recanonicalizes_mixed_version_writes(tmp_path, audit_db):
    """A v1 writer appending bare-ticker fill keys after migration must not
    reintroduce split normalization groups: read_since derives mkey from
    authoritative ticker+side columns and preserves the stored value as
    provenance."""
    now = time.time()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    # Simulate a post-migration v1 write: stored mkey is the OLD bare
    # ticker form even though the store version marker is already v2.
    sconn.execute(
        "INSERT INTO evidence_outcome_rows (row_key, src, asset, side,"
        " ticker, decision_id, mkey, entry_cents, settled_yes,"
        " settled_at, decision_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy1", "fill", "BTC", "yes", "KXBTC15M-leg", "leg1",
         "KXBTC15M-leg", 50.0, 1, now - 100, now - 100),
    )
    sconn.commit()
    rows = store.read_since(sconn, now - 86400)
    r = next(x for x in rows if x["decision_id"] == "leg1")
    assert r["mkey"] == "KXBTC15M-leg|yes"       # canonical at read time
    assert r["stored_mkey"] == "KXBTC15M-leg"    # stored provenance kept
    sconn.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))

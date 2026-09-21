"""P0 must recover authoritative REST fills before identity comparison."""
from pathlib import Path


def test_p0_ingests_rest_fills_before_reconciliation_diff():
    source = Path("merid/preflight/p0.py").read_text(encoding="utf-8")
    ingest_pos = source.index("ledger.ingest_http_fills(fills)")
    compare_pos = source.index("only_exchange = ex_ids - set(in_by_id)")
    assert ingest_pos < compare_pos
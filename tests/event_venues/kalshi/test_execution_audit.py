from merid.event_venues.kalshi.execution_audit import (
    execution_path_histogram,
    record_execution_path,
    reset_execution_audit_for_testing,
)


def test_execution_path_histogram():
    reset_execution_audit_for_testing()
    record_execution_path("api")
    record_execution_path("api")
    assert execution_path_histogram()["api"] == 2

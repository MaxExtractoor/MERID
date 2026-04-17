from pathlib import Path

from merid.event_venues.kalshi.incidents.replayer import (
    KalshiIncidentReplayer,
    load_scenario,
)


def test_replay_synthetic_fomc(monkeypatch):
    scenario_path = Path("tests/fixtures/kalshi-incidents/2026-02-14-fomc.json")
    scenario = load_scenario(scenario_path)

    replayer = KalshiIncidentReplayer(scenario)
    replayer.replay_metrics()
    replayer.replay_cb_events()
    report = replayer.generate_report()

    assert report["scenario_id"] == "2026-02-14-fomc"
    assert report["observed_cb_events"] == report["expected_cb_events"] == 1
    assert report["latency_samples"] == 4

from __future__ import annotations


def test_get_threshold_status_handles_optimizer_errors(monkeypatch):
    import merid.sentiment as sentiment

    class BrokenOptimizer:
        def __init__(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "merid.sentiment.threshold_optimizer.VaderThresholdOptimizer",
        BrokenOptimizer,
    )

    status = sentiment.get_threshold_status()

    assert status["assets"] == {}
    assert status["last_optimized"] is None
    assert status["timestamp"]

from __future__ import annotations

from fastapi.testclient import TestClient

from web.main import app
from web.metrics import metrics


def test_metrics_endpoint_returns_text():
    metrics.reset()
    client = TestClient(app)

    # trigger a simple metric
    metrics.inc("test_metric", 2)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "test_metric 2" in r.text

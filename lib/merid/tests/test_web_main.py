from fastapi.testclient import TestClient
from merid_web import app


def test_home_page():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "MERID" in r.text


def test_submit_stream():
    client = TestClient(app)
    r = client.post("/submit", data={"source": "test", "payload": "hello"})
    assert r.status_code == 200
    # basic check: response body contains SSE 'data:' marker
    assert "data:" in r.text

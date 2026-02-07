from fastapi.testclient import TestClient
from merid_web import app


def test_submit_requires_nonempty_fields():
    client = TestClient(app)
    r = client.post("/submit", data={"source": "", "payload": ""})
    assert r.status_code == 200
    # Our handler returns a validation detail dict when field values are empty
    assert "detail" in r.json()


def test_submit_stream_schema_enforced():
    client = TestClient(app)
    r = client.post("/submit", data={"source": "test", "payload": "hello"})
    assert r.status_code == 200
    assert "data:" in r.text

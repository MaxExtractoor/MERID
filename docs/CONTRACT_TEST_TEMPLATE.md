# Contract Test Template

> Reusable pattern for adding structural contract tests to a new API surface.
> Only apply when driven by an actual bug class — not preemptively.

## When to Use

Add a new contract test module when you observe **repeated** issues in one of
these categories:

| Bug Class | Example | Contract Test Target |
|-----------|---------|---------------------|
| Frontend calls a route that doesn't exist | Dashboard shows 404 for risk summary | Route existence check (like `test_ui_backend_contract.py`) |
| Response shape doesn't match frontend expectations | Panel crashes on missing `.data.items` key | Response schema assertion |
| Auth/role mismatch | Operator endpoint accessible without auth | Auth requirement check |
| SSE stream dropped or misconfigured | Live panel shows stale data | SSE wiring check (like `test_sse_smoke.py`) |

## Step-by-Step

### 1. Define the contract artifact

Create a small JSON or Python dict that captures the **minimum expectations**
from the client side.

```python
# tests/contracts/risk_positions_contract.py
RISK_POSITIONS_CONTRACT = {
    "endpoint": "/api/v1/risk/positions",
    "method": "GET",
    "required_fields": ["positions", "total_value", "timestamp"],
    "position_fields": ["asset", "size", "entry_price", "current_price", "pnl"],
}
```

### 2. Write the structural test

```python
# tests/test_risk_positions_contract.py
"""Risk positions contract test.

Verifies the /api/v1/risk/positions endpoint returns the shape
expected by the RiskPositionsPanel component.
"""
import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def client(app_fixture):
    return TestClient(app_fixture, raise_server_exceptions=False)


class TestRiskPositionsContract:
    def test_endpoint_exists(self, client):
        resp = client.get("/api/v1/risk/positions")
        assert resp.status_code != 404, "Endpoint not registered"

    def test_response_has_required_fields(self, client):
        resp = client.get("/api/v1/risk/positions")
        if resp.status_code == 200:
            data = resp.json()
            for field in ["positions", "total_value", "timestamp"]:
                assert field in data, f"Missing required field: {field}"

    def test_position_shape(self, client):
        resp = client.get("/api/v1/risk/positions")
        if resp.status_code == 200:
            data = resp.json()
            if data.get("positions"):
                pos = data["positions"][0]
                for field in ["asset", "size", "entry_price"]:
                    assert field in pos, f"Position missing field: {field}"
```

### 3. Add to CI gate

In `.github/workflows/ci.yml` → `backend-structural-checks` job, append
the new test file:

```yaml
      - name: Run structural contract tests
        run: |
          python -m pytest \
            tests/test_ui_backend_contract.py \
            tests/test_sse_smoke.py \
            tests/test_kalshi_only_profile.py \
            tests/test_openapi_schema_sanity.py \
            tests/test_risk_positions_contract.py \  # ← new
            -v --tb=short --timeout=30
```

### 4. Add runtime monitoring (optional)

If the surface is critical enough to warrant runtime checks, add a
collector to the contract-health endpoint in `system_endpoints.py`:

```python
# Inside get_contract_health()
risk_shape_ok = True
try:
    resp = await some_internal_call()
    risk_shape_ok = all(f in resp for f in ["positions", "total_value"])
except Exception:
    risk_shape_ok = False

return {
    ...existing fields...,
    "risk_positions_shape_ok": risk_shape_ok,
}
```

## Checklist

- [ ] Triggered by a real, repeated bug class (not speculative)
- [ ] Contract artifact defined (JSON or Python dict)
- [ ] Structural test module created
- [ ] Added to CI `backend-structural-checks` job
- [ ] (Optional) Runtime check wired to contract-health endpoint
- [ ] (Optional) Grafana panel added for the new metric

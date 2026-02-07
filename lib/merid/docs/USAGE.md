# MERID — Usage Guide

## Quick start (local)

1. Install Python dev deps:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements-dev.txt
   ```

2. Run the backend tests:

   ```bash
   python -m pytest -q
   ```

3. Run the FastAPI server locally:

   ```bash
   python -m uvicorn web.main:app --reload
   # or use the Makefile
   make run
   ```

4. Visit the web endpoints:

   - Home page: http://localhost:8000/
   - Metrics: http://localhost:8000/metrics
   - Admin endpoints (requires admin token):
     - `GET /admin/lockdown`
     - `POST /admin/lockdown` (json `{"lock": true}`)
     - `GET /admin/audit`
     - `POST /admin/audit` (json `{"action": "...", "details": {...}}`)

   Dev admin token (default): `local-admin-token` (set `MERID_ADMIN_TOKEN` to change)

## Generate & validate schemas

This project keeps committed JSON schema artifacts in `generated/schemas/`.

- Generate schemas:

```bash
python -c "from web.schema_export import export_schemas; export_schemas('generated/schemas')"
```

- CI validates generated schemas match committed versions.

## E2E simulation

Run a deterministic E2E simulation to exercise trading flows and audit logging:

```bash
python scripts/run_e2e.py --steps 20 --threshold 50
```

The simulation will print summary JSON to stdout.

## Audit persistence

To enable durable audit logging, set the `MERID_AUDIT_FILE` environment variable to a file path. The server will persist each audit entry as a single JSON line in that file:

```bash
export MERID_AUDIT_FILE=/var/lib/merid/audits.log
# then run the server normally
python -m uvicorn web.main:app --reload
```

CI includes a lightweight E2E smoke job that runs `scripts/run_e2e.py` on PRs to catch regressions in the simulation and execution flows. Additionally, a scheduled nightly CI workflow runs a short E2E smoke daily (03:00 UTC) to provide continuous safety checks.

If the nightly E2E job fails, the repository will automatically file a GitHub issue labeled `nightly-e2e-failure` to surface the problem to operators for investigation.

## Docker

Build locally:

```bash
make build
```

Run locally:

```bash
make up
```

The service listens on port 8000.

## Flutter UI

- Run the Flutter tests (CI job runs these):

```bash
flutter test
```

- The ControlStation UI will prompt for an admin token when toggling lockdown and reads/writes the admin endpoints.

## Notes

- This repository is intentionally small and uses in-memory stores for testing. For production, replace the in-memory audit and order stores with durable, shared storage.

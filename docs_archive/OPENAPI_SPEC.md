# MERID OpenAPI Specification

This project uses FastAPI's built-in OpenAPI generator. The spec is always available from a running server.

## Access

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **Raw JSON:** `/openapi.json`

By default the API runs at `http://127.0.0.1:8000` and versioned endpoints are under `/api/v1`.

## Export a Snapshot

1. Start the backend (FastAPI app in `web/main.py`).
2. Fetch the spec JSON:

```
curl http://127.0.0.1:8000/openapi.json -o docs/openapi.json
```

3. Commit `docs/openapi.json` if you want a frozen snapshot for tooling.

## Notes

- The backend uses FastAPI's default OpenAPI generation; no custom schema overrides are required.
- Prediction market endpoints are exposed under `/api/v1/us-compliant/prediction-markets` for production (Kalshi). Non-US sources are used only for simulation/research.
- WebSocket payloads are documented separately in `docs/WEBSOCKET_MESSAGE_FORMATS.md`.

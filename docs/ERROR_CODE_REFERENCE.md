# MERID Error Code Reference

MERID primarily returns standard HTTP status codes with a JSON body containing a `detail` field.

## REST Error Shape

```json
{
  "detail": "Plan not found"
}
```

Validation errors (422) return FastAPI's default array of field errors.

## Common Status Codes

| Status | Meaning | Typical Causes |
|--------|---------|----------------|
| 400 | Bad Request | Missing/invalid parameters, malformed JSON |
| 401 | Unauthorized | Missing or invalid auth token |
| 403 | Forbidden | Authenticated but insufficient permissions |
| 404 | Not Found | Resource ID not found |
| 409 | Conflict | State conflict (duplicate, stale update) |
| 422 | Validation Error | Schema validation failed |
| 429 | Too Many Requests | Rate limiting |
| 500 | Internal Error | Unhandled server error |
| 503 | Service Unavailable | Upstream service offline |

## Suggested Error Codes (Optional)

Where applicable, include an `error_code` field to make UI handling deterministic.

```json
{
  "detail": "Position limit exceeded",
  "error_code": "RISK_LIMIT_EXCEEDED",
  "request_id": "req_123"
}
```

Suggested codes:

- `AUTH_UNAUTHORIZED`
- `AUTH_FORBIDDEN`
- `RISK_LIMIT_EXCEEDED`
- `ORDER_REJECTED`
- `RESOURCE_NOT_FOUND`
- `RATE_LIMITED`
- `UPSTREAM_UNAVAILABLE`
- `INTERNAL_ERROR`

## WebSocket Errors

WebSocket clients should handle:

- Connection close codes and reconnect logic.
- Optional `type: "error"` payloads if emitted by a stream.

Example:
```json
{ "type": "error", "message": "Subscription failed" }
```

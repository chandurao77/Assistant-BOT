# Rule: Logging

## Log Levels
| Level | When | Example |
|-------|------|---------|
| **ERROR** | Something failed, needs attention | DB connection lost, unhandled exception |
| **WARN** | Unexpected but handled | Retry succeeded, deprecated API used |
| **INFO** | Business events, normal operations | Request served, job completed, user logged in |
| **DEBUG** | Detailed diagnostic (dev only) | Query parameters, cache hit/miss, intermediate values |

### Rules
- Production: INFO and above (no DEBUG)
- Development: DEBUG and above
- Never log at ERROR for expected failures (invalid input = WARN, not ERROR)
- If an alert would fire, it's ERROR. If not, it's probably WARN or INFO.

## Structured Logging
```python
# Always use structured (JSON) logging — never plain text in production
import structlog

logger = structlog.get_logger()

# Good: structured key-value pairs
logger.info("request_processed",
    method="POST",
    path="/api/chat",
    status=200,
    duration_ms=142,
    user_id="usr_abc123",
    request_id="req_xyz789",
)

# Bad: unstructured string interpolation
logger.info(f"POST /api/chat returned 200 in 142ms for user usr_abc123")
```

Output:
```json
{
  "timestamp": "2026-04-20T14:32:01.456Z",
  "level": "info",
  "event": "request_processed",
  "method": "POST",
  "path": "/api/chat",
  "status": 200,
  "duration_ms": 142,
  "user_id": "usr_abc123",
  "request_id": "req_xyz789",
  "service": "assistant-bot-backend"
}
```

## Required Fields
Every log line must include:
| Field | Source | Example |
|-------|--------|---------|
| `timestamp` | Auto (logger) | `2026-04-20T14:32:01.456Z` |
| `level` | Explicit | `info`, `error`, `warn` |
| `event` | Explicit | `request_processed`, `auth_failed` |
| `service` | Config | `assistant-bot-backend` |
| `request_id` | Middleware | `req_xyz789` |

## Correlation IDs
```python
# Middleware: attach request_id to every log in the request lifecycle
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

@app.middleware("http")
async def add_request_id(request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request_id_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

## What to Log

### Always Log
- Request start/end with duration
- Authentication events (login, logout, failure)
- Authorization failures (access denied)
- Business events (user created, order placed, document indexed)
- External service calls (with timing)
- Background job start/completion/failure
- Configuration loaded at startup

### Never Log
- Passwords, tokens, API keys, secrets
- Full credit card numbers, SSN, PII
- Request/response bodies with sensitive data
- Health check requests (too noisy)
- Individual loop iterations (log summary instead)

### Redaction
```python
def redact(data: dict, sensitive_keys: set[str] = None) -> dict:
    """Redact sensitive values before logging."""
    sensitive = sensitive_keys or {"password", "token", "secret", "api_key", "authorization"}
    return {
        k: "***REDACTED***" if k.lower() in sensitive else v
        for k, v in data.items()
    }
```

## Error Logging
```python
# Good: log with context + stack trace
try:
    result = await external_api.call(params)
except ExternalAPIError as e:
    logger.error("external_api_failed",
        service="confluence",
        endpoint=e.endpoint,
        status_code=e.status_code,
        duration_ms=e.duration_ms,
        exc_info=True,  # includes stack trace
    )
    raise

# Bad: lose context
except Exception as e:
    logger.error(str(e))  # no context, no stack trace
```

## Log Aggregation
```
Application  →  stdout (JSON)  →  Log collector  →  Central store  →  Dashboard
                                  (Fluentd,          (Elasticsearch,   (Kibana,
                                   Filebeat,          Loki,             Grafana)
                                   Vector)            CloudWatch)
```

- Containers: always log to stdout/stderr (Docker captures it)
- Never write to files inside containers
- Use log rotation if writing to files on bare metal

## See Also
- [skills/monitoring/README.md](../skills/monitoring/README.md) — observability beyond logging
- [rules/error-handling.md](error-handling.md) — what to do when errors occur
- [rules/security.md](security.md) — what must never appear in logs

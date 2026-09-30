# Rule: Error Handling

## Principles
- **Fail fast** — detect errors early, at system boundaries
- **Fail loud** — log errors with context, don't swallow silently
- **Fail gracefully** — show users a helpful message, not a stack trace
- **Fail specifically** — catch specific exceptions, not bare `except:`

## Exception Hierarchy
```python
# Define domain exceptions — don't use generic ValueError for everything
class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code

class NotFoundError(AppError):
    def __init__(self, resource: str, id: str):
        super().__init__(f"{resource} '{id}' not found", code="NOT_FOUND")

class ValidationError(AppError):
    def __init__(self, field: str, reason: str):
        super().__init__(f"Invalid {field}: {reason}", code="VALIDATION_ERROR")

class AuthorizationError(AppError):
    def __init__(self, action: str):
        super().__init__(f"Not authorized to {action}", code="FORBIDDEN")

class ExternalServiceError(AppError):
    def __init__(self, service: str, detail: str):
        super().__init__(f"{service} unavailable: {detail}", code="SERVICE_UNAVAILABLE")
```

## Error Response Format
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Conversation 'abc-123' not found",
    "details": null
  }
}
```

**Never expose in error responses:**
- Stack traces
- File paths or line numbers
- Database queries or schema details
- Internal service names or IPs
- Environment variables

## Catch Patterns

### Do
```python
# Specific exception with context
try:
    user = await db.get_user(user_id)
except DatabaseConnectionError:
    logger.error("DB connection failed", extra={"user_id": user_id})
    raise ExternalServiceError("database", "connection refused")
```

### Don't
```python
# Bare except — hides bugs
try:
    user = await db.get_user(user_id)
except:
    pass  # silently swallowed

# Catching too broadly
try:
    result = complex_operation()
except Exception as e:
    return None  # lost the error, returned ambiguous None
```

## Retry Strategy
```python
import asyncio
from typing import TypeVar, Callable

T = TypeVar("T")

async def retry(
    fn: Callable[..., T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    retryable: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
) -> T:
    """Retry with exponential backoff. Only retry transient errors."""
    for attempt in range(max_attempts):
        try:
            return await fn()
        except retryable as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{max_attempts} after {delay}s: {e}")
            await asyncio.sleep(delay)
```

### What to Retry
| Retry | Don't Retry |
|-------|------------|
| Network timeouts | Validation errors (400) |
| Connection refused | Authentication failures (401) |
| HTTP 502/503/504 | Not found (404) |
| Rate limited (429) | Business logic errors |
| Transient DB errors | Constraint violations |

## Circuit Breaker
```
CLOSED  →  errors exceed threshold  →  OPEN
  ↑                                      │
  │        timeout expires               ↓
  └────────  success  ←──────────  HALF-OPEN
```

Use when: calling an external service that might be down for extended periods.

## Frontend Error Handling
```typescript
// Error Boundary for React
class ErrorBoundary extends React.Component<Props, State> {
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    logger.error("React error boundary caught", { error, info });
  }
  render() {
    if (this.state.hasError) {
      return <ErrorFallback error={this.state.error} />;
    }
    return this.props.children;
  }
}

// API call error handling
try {
  const data = await api.fetchConversations();
} catch (error) {
  if (error instanceof AuthError) {
    redirect("/login");
  } else if (error instanceof NetworkError) {
    showToast("Connection lost. Retrying...");
  } else {
    showToast("Something went wrong. Please try again.");
    logger.error("Unexpected error", { error });
  }
}
```

## See Also
- [rules/logging.md](logging.md) — what and how to log errors
- [rules/api-conventions.md](api-conventions.md) — error response format and status codes
- [agents/backend-engineer.md](../agents/backend-engineer.md) — service layer error handling

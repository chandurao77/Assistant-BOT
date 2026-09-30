# Rule: API Conventions

## Endpoint Naming
- Use **nouns**, not verbs: `/api/users` not `/api/getUsers`
- Use **plural** resource names: `/api/conversations` not `/api/conversation`
- Use **kebab-case** for multi-word paths: `/api/query-analytics`
- Nest sub-resources: `/api/conversations/{id}/messages`
- Keep nesting max 2 levels deep

## HTTP Methods
| Method | Usage | Idempotent | Response Code |
|--------|-------|------------|---------------|
| GET | Read resource(s) | Yes | 200 |
| POST | Create resource | No | 201 (created) or 202 (async) |
| PUT | Replace resource | Yes | 200 |
| PATCH | Partial update | No | 200 |
| DELETE | Remove resource | Yes | 204 (no content) |

## Request/Response Format
- Always JSON (`Content-Type: application/json`)
- Use camelCase for JSON fields (frontend) or snake_case (Python backend)
- Wrap lists in an object: `{"items": [...], "total": 42}` not bare arrays
- Include pagination: `{"items": [...], "total": 100, "page": 1, "per_page": 20}`

## Error Responses
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": [
      {"field": "email", "message": "Invalid email format"}
    ]
  }
}
```

## Status Codes
| Code | When |
|------|------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted (async operation started) |
| 204 | No Content (successful DELETE) |
| 400 | Bad Request (malformed input) |
| 401 | Unauthorized (no/invalid auth) |
| 403 | Forbidden (valid auth, insufficient permissions) |
| 404 | Not Found |
| 409 | Conflict (duplicate resource) |
| 413 | Payload Too Large |
| 422 | Unprocessable Entity (valid JSON, invalid values) |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error (never intentional) |

## Authentication
- User-facing routes: JWT Bearer token in `Authorization` header
- Machine-to-machine routes: API key in `X-API-Key` header
- Never put tokens in URLs or query parameters
- Always validate auth before processing the request

## Versioning
- Use URL prefix versioning when breaking changes are needed: `/api/v2/users`
- Avoid versioning until you actually need it
- Deprecate old versions with `Sunset` header and migration guide

## See Also
- [agents/backend-engineer.md](../agents/backend-engineer.md) — API implementation guidelines
- [rules/security.md](security.md) — auth and input validation
- [rules/documentation.md](documentation.md) — API documentation standards

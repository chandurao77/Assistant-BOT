# API Design Guidelines

These rules apply to every public and internal HTTP API at Orbit Labs.

## URLs and Methods

- Use plural nouns for collections: `/v1/orders`, `/v1/orders/{id}`.
- Use `GET` to read, `POST` to create, `PUT` to replace, `PATCH` to update part of a resource, and `DELETE` to remove.
- Version the API in the path (`/v1/`). A breaking change requires a new major version.

## Authentication

- Service-to-service calls use short-lived OAuth 2.0 access tokens (15-minute lifetime).
- Public API clients authenticate with an API key sent in the `X-API-Key` header.
- Never put credentials in a URL or query string.

## Rate Limits

| Caller | Limit |
|--------|-------|
| Public API key | 1,000 requests per minute |
| Internal service-to-service | 5,000 requests per minute |
| Search endpoints | 100 requests per minute |

When a limit is exceeded the API returns HTTP `429` with a `Retry-After` header giving the number of seconds to wait. Clients must use exponential backoff with jitter.

## Pagination

- List endpoints use cursor pagination: `?limit=50&cursor=<opaque-token>`.
- The default page size is 50 and the maximum is 200.
- The response contains `items` and `next_cursor`. When `next_cursor` is `null` there are no more pages.

## Error Format

Errors always use this JSON body:

```json
{
  "error": {
    "code": "order_not_found",
    "message": "No order exists with id 42.",
    "request_id": "req_8f3a1c"
  }
}
```

- `4xx` codes mean the caller made a mistake. `5xx` codes mean the server failed.
- Always include the `request_id` when you contact support.

## Idempotency

`POST` requests that create resources accept an `Idempotency-Key` header. Repeating a request with the same key within 24 hours returns the original response instead of creating a duplicate.

## Deprecation

- Announce a deprecation at least 6 months before removal.
- Add the `Deprecation` and `Sunset` response headers to affected endpoints.

# Rule: Security

## Authentication & Authorization
- Every endpoint must have explicit auth (even if it's "public")
- Use JWT with short expiry (1-24h) + refresh tokens
- Hash passwords with bcrypt/argon2 — never MD5/SHA
- Rate limit auth endpoints: max 5 attempts per minute per IP
- Invalidate sessions on password change
- RBAC: deny by default, allow explicitly

## Input Validation
- Validate ALL input at system boundaries — never trust client data
- Use schema validation (Pydantic, Zod, Joi) not manual checks
- Validate type, length, format, and range
- Reject unexpected fields (strict mode)
- Sanitize HTML output to prevent XSS
- Use parameterized queries — NEVER string concatenation for SQL

## Secrets Management
- **Never** hardcode secrets in source code
- **Never** commit `.env` files (add to `.gitignore`)
- **Never** log secrets, tokens, or passwords
- Use environment variables or secret file mounts (`_FILE` suffix pattern)
- Rotate secrets regularly; support rotation without downtime
- Use different secrets per environment (dev ≠ staging ≠ prod)

## HTTP Security Headers
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; script-src 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

## CORS
- Never use `Access-Control-Allow-Origin: *` in production
- Whitelist specific origins
- Limit allowed methods and headers

## Data Protection
- Encrypt data in transit (TLS 1.2+)
- Encrypt sensitive data at rest (PII, credentials)
- Implement PII redaction in logs (email, SSN, tokens)
- Mask sensitive fields in error responses
- Set `HttpOnly`, `Secure`, `SameSite` flags on cookies

## Container Security
- Run as non-root user
- Use minimal base images (alpine, distroless)
- Pin image versions (no `latest` tag)
- Scan images for CVEs (Trivy, Snyk)
- Read-only filesystem where possible
- No secrets in Docker images or build args

## Dependency Security
- Run `npm audit` / `pip-audit` / `trivy` in CI
- Pin dependency versions (lockfiles committed)
- Review new dependencies before adding
- Prefer well-maintained libraries with active security response

## Incident Response
- Log all authentication events (success + failure)
- Log all authorization failures
- Include correlation IDs in all logs
- Alert on anomalous patterns (brute force, unusual access)
- Have a documented incident response runbook

## See Also
- [agents/security-auditor.md](../agents/security-auditor.md) — security audit persona and severity ratings
- [skills/monitoring/README.md](../skills/monitoring/README.md) — security event logging and alerting
- [rules/api-conventions.md](api-conventions.md) — auth patterns for APIs

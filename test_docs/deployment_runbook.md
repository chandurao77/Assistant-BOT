# Deployment and Rollback Runbook

## Release Process

1. Merge the pull request to `main`. CI builds and tags the container image with the commit SHA.
2. The pipeline deploys to **staging** automatically.
3. Run the smoke test suite against staging: `make smoke ENV=staging`.
4. The release manager starts the production deploy from the release dashboard.
5. Production uses a **canary rollout**: 5% of traffic for 10 minutes, then 25%, then 100%.
6. The release manager watches error rate and p95 latency during each step.

## Release Windows

- Production releases: Tuesday and Thursday at 10:00 UTC.
- No releases on Fridays or the day before a public holiday.
- Hotfixes are allowed at any time with approval from the on-call lead.

## Health Checks Before Promoting the Canary

Proceed to the next canary step only if all of these hold:

- Error rate is below 1%.
- p95 latency is within 20% of the previous version.
- No new alerts have fired for the service.

## Rollback

Roll back immediately if a health check fails.

```bash
# List recent releases
releasectl history payments-service

# Roll back to the previous release
releasectl rollback payments-service --to previous
```

A rollback takes about 2 minutes. After rolling back, open an incident if customers were affected and follow the Incident Response Runbook.

## Database Migrations

- Migrations must be backwards compatible with the previous application version.
- Use the expand and contract pattern: first add the new column, deploy code that writes both, backfill, then remove the old column in a later release.
- Never drop a column in the same release that stops using it.

## Feature Flags

- New user-facing features ship behind a feature flag that defaults to off.
- Turn the flag on for internal users first, then 10% of customers, then everyone.
- Remove the flag within 30 days after it reaches 100%.

---
name: ci-cd-pipeline
description: "Design and maintain CI/CD pipelines — GitHub Actions, stage gates, caching, artifact publishing. USE FOR: create pipeline, fix CI, add deploy stage, configure caching, set up matrix builds."
argument-hint: "Describe the pipeline task, e.g. 'add Docker build and push stage to GitHub Actions'"
---

# Skill: CI/CD Pipeline

## Purpose
Design and maintain continuous integration and delivery pipelines that build, test, scan, and deploy reliably.

## Pipeline Stages
```
┌──────┐   ┌──────┐   ┌──────┐   ┌──────┐   ┌───────┐   ┌────────┐
│ Lint │ → │ Test │ → │ Scan │ → │Build │ → │Deploy │ → │Verify  │
│      │   │      │   │      │   │      │   │Staging│   │Promote │
└──────┘   └──────┘   └──────┘   └──────┘   └───────┘   └────────┘
```

## GitHub Actions Example
```yaml
# .github/workflows/ci.yml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff black
      - run: ruff check backend/
      - run: black --check backend/

  test-backend:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: testdb
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/ -v --tb=short --junitxml=test-results.xml
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/testdb
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: test-results.xml

  test-frontend:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm", cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci
      - run: cd frontend && npx vitest run --reporter=verbose

  security-scan:
    runs-on: ubuntu-latest
    needs: [test-backend, test-frontend]
    steps:
      - uses: actions/checkout@v4
      - run: pip install pip-audit && pip-audit -r requirements.txt
      - run: cd frontend && npm audit --audit-level=high
      - uses: aquasecurity/trivy-action@master
        with:
          scan-type: fs
          exit-code: 1
          severity: CRITICAL,HIGH

  build:
    runs-on: ubuntu-latest
    needs: security-scan
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: |
            ghcr.io/${{ github.repository }}/backend:${{ github.sha }}
            ghcr.io/${{ github.repository }}/backend:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy-staging:
    runs-on: ubuntu-latest
    needs: build
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - run: |
          kubectl set image deployment/backend \
            backend=ghcr.io/${{ github.repository }}/backend:${{ github.sha }} \
            -n assistant-bot-staging
          kubectl rollout status deployment/backend -n assistant-bot-staging --timeout=120s

  deploy-production:
    runs-on: ubuntu-latest
    needs: deploy-staging
    environment: production  # requires approval
    steps:
      - run: |
          kubectl set image deployment/backend \
            backend=ghcr.io/${{ github.repository }}/backend:${{ github.sha }} \
            -n assistant-bot
          kubectl rollout status deployment/backend -n assistant-bot --timeout=120s
```

## Pipeline Best Practices

### Speed
| Technique | Impact |
|-----------|--------|
| Cache dependencies | -60% install time (`actions/cache`, `cache: npm`) |
| Parallel jobs | -50% total time (lint ∥ test-backend ∥ test-frontend) |
| Docker layer caching | -70% build time (`cache-from: type=gha`) |
| Selective testing | Only test changed packages (monorepo) |
| Fail fast | `--fail-fast` on matrix builds |

### Security
- **Never** put secrets in workflow files — use GitHub Secrets / Vault
- Use `${{ secrets.NAME }}` — never echo or log secrets
- Pin action versions to SHA: `actions/checkout@abc123` not `@v4`
- Use `permissions` to limit GITHUB_TOKEN scope
- Scan dependencies AND Docker images for CVEs

### Reliability
- Set timeouts on every job (`timeout-minutes: 15`)
- Use `if: always()` for cleanup steps (artifact upload, notification)
- Retry flaky steps with `uses: nick-fields/retry@v3`
- Use `concurrency` to prevent duplicate runs
- Test the pipeline itself — broken CI blocks the whole team

## Secrets in CI
```yaml
# Good: use GitHub encrypted secrets
env:
  API_KEY: ${{ secrets.API_KEY }}

# Good: use OIDC for cloud auth (no long-lived credentials)
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::123456789:role/ci-deploy
    aws-region: us-east-1

# Bad: hardcoded values
env:
  API_KEY: "sk-abc123"  # NEVER DO THIS
```

## Notifications
```yaml
  notify:
    runs-on: ubuntu-latest
    needs: [deploy-production]
    if: always()
    steps:
      - uses: slackapi/slack-github-action@v1
        with:
          payload: |
            {"text": "Deploy ${{ needs.deploy-production.result }}: ${{ github.repository }}@${{ github.sha }}"}
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}
```

## See Also
- [agents/devops-engineer.md](../../agents/devops-engineer.md) — CI/CD design expertise
- [skills/deploy/README.md](../deploy/README.md) — deployment workflow details
- [rules/security.md](../../rules/security.md) — secrets management
- [rules/testing.md](../../rules/testing.md) — test pipeline integration

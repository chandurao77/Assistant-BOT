---
name: deploy
description: "Deployment workflows, environment matrix, rollback strategies, and smoke tests. USE FOR: deploy to staging, configure rollback, set up blue-green deploy, create deployment checklist."
argument-hint: "Describe the deployment task, e.g. 'set up blue-green deployment for Kubernetes'"
---

# Skill: Deploy

## Purpose
Automate and standardize deployment workflows across environments (dev, staging, production).

## Supported Targets
| Target | Method | Config |
|--------|--------|--------|
| Docker Compose (local) | `docker compose up -d --build` | `docker-compose.yml` |
| Kubernetes | `kubectl apply` / Helm | `k8s/*.yaml` or Helm chart |
| AWS ECS | Task definition update | Terraform / CloudFormation |
| Cloud Run | `gcloud run deploy` | `cloudbuild.yaml` |

## Deployment Workflow

### 1. Pre-Deploy Checks
```bash
# Verify tests pass
pytest tests/ -q --tb=line
npx vitest run

# Verify build succeeds
docker compose build
npm run build

# Check for security vulnerabilities
npm audit --audit-level=high
pip-audit
trivy image <image-name>
```

### 2. Build & Tag
```bash
# Build production image
docker build -t app:$(git rev-parse --short HEAD) .

# Tag for registry
docker tag app:$(git rev-parse --short HEAD) registry.example.com/app:latest
docker tag app:$(git rev-parse --short HEAD) registry.example.com/app:$(git rev-parse --short HEAD)
```

### 3. Deploy
```bash
# Docker Compose (dev/staging)
docker compose up -d --build

# Kubernetes
kubectl apply -f k8s/
kubectl rollout status deployment/backend -n assistant-bot

# Verify deployment
kubectl get pods -n assistant-bot
curl -f https://app.example.com/api/health
```

### 4. Post-Deploy Verification
- [ ] Health endpoint returns 200 with all components OK
- [ ] Smoke test: critical user flow works
- [ ] Monitoring dashboards show normal metrics
- [ ] Error rate has not increased
- [ ] No new errors in logs (check first 5 minutes)

### 5. Rollback (if needed)
```bash
# Docker Compose
docker compose down && docker compose up -d --build <previous-tag>

# Kubernetes
kubectl rollout undo deployment/backend -n assistant-bot
```

## Environment Matrix
| Environment | Deploy Trigger | Approval Required |
|-------------|---------------|-------------------|
| Dev | Push to `dev` branch | No |
| Staging | Push to `main` branch | No |
| Production | Manual or tag `v*` | Yes — team lead approval |

## Safety Rules
- Never deploy directly to production without staging verification
- Always have a rollback plan before deploying
- Deploy during business hours (not Friday 5pm)
- Monitor for 15 minutes after production deploy

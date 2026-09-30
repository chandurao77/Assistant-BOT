---
name: docker
description: "Docker multi-stage builds, compose patterns, image optimization, and container security. USE FOR: write Dockerfile, optimize image size, create docker-compose, fix container issues, set up health checks."
argument-hint: "Describe the Docker task, e.g. 'create multi-stage Dockerfile for Python FastAPI app'"
---

# Skill: Docker

## Purpose
Build, optimize, and deploy containerized applications following security and performance best practices.

## Dockerfile Best Practices

### Multi-Stage Build
```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production=false
COPY . .
RUN npm run build

# Stage 2: Production
FROM node:20-alpine AS production
WORKDIR /app

# Security: non-root user
RUN addgroup -g 1001 app && adduser -u 1001 -G app -D app

# Only copy what's needed
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

USER app
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:3000/health || exit 1

CMD ["node", "dist/server.js"]
```

### Python Application
```dockerfile
FROM python:3.12-slim AS base

# Security: non-root user
RUN groupadd -r app && useradd -r -g app -d /app app
WORKDIR /app

# Dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=app:app . .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Layer Optimization
```dockerfile
# Order from least to most frequently changed:
# 1. Base image (rarely changes)
FROM python:3.12-slim

# 2. System dependencies (changes monthly)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. Application dependencies (changes weekly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Application code (changes every commit)
COPY . .
```

## Docker Compose Patterns

### Development
```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: development        # use dev stage
    volumes:
      - ./backend:/app           # hot reload
      - /app/__pycache__         # exclude cache
    ports:
      - "8000:8000"
    environment:
      - DEBUG=true
      - DATABASE_URL=postgresql://user:pass@postgres:5432/devdb
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: devdb
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d devdb"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

### Production
```yaml
services:
  backend:
    image: ghcr.io/org/backend:${VERSION:-latest}
    read_only: true                    # immutable filesystem
    security_opt:
      - no-new-privileges:true         # prevent privilege escalation
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"
        reservations:
          memory: 256M
    environment:
      - DATABASE_URL_FILE=/run/secrets/db_url
    secrets:
      - db_url
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

secrets:
  db_url:
    file: ./secrets/db_url.txt
```

## Security Checklist
- [ ] Run as non-root user (`USER app`)
- [ ] Use minimal base images (`-slim`, `-alpine`, `distroless`)
- [ ] Pin image versions (`python:3.12-slim` not `python:latest`)
- [ ] No secrets in images or build args
- [ ] Read-only filesystem where possible
- [ ] Set resource limits (memory, CPU)
- [ ] Health checks on every container
- [ ] Scan for CVEs (`trivy image app:latest`)
- [ ] `.dockerignore` excludes `.git`, `.env`, `node_modules`, `__pycache__`

## .dockerignore
```
.git
.gitignore
.env
.env.*
*.md
docker-compose*.yml
node_modules
__pycache__
*.pyc
.pytest_cache
dist
coverage
.vscode
.idea
tests/
docs/
```

## Useful Commands
```bash
# Build & run
docker compose up -d --build
docker compose ps
docker compose logs -f backend

# Debug
docker compose exec backend sh           # shell into container
docker inspect <container>                # full container info
docker stats                              # live resource usage

# Cleanup
docker system prune -a --volumes          # remove everything unused
docker image prune -a                     # remove unused images
docker volume prune                       # remove unused volumes

# Image analysis
docker image inspect app:latest           # layers, size, config
docker history app:latest                 # layer-by-layer size
dive app:latest                           # interactive layer explorer
```

## See Also
- [agents/devops-engineer.md](../../agents/devops-engineer.md) — container orchestration expertise
- [skills/deploy/README.md](../deploy/README.md) — deployment beyond Docker
- [rules/security.md](../../rules/security.md) — container security standards
- [skills/ci-cd-pipeline/README.md](../ci-cd-pipeline/README.md) — Docker in CI pipelines

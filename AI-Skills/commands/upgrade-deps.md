# Command: Upgrade Dependencies

Structured workflow for safely updating project dependencies.

## Usage
```
/upgrade-deps [--scope backend|frontend|all] [--type major|minor|patch]
```

## Phases

### Phase 1 — Audit
- [ ] Scan for known vulnerabilities
- [ ] Identify outdated packages
- [ ] Check for deprecated packages

```bash
# Backend (Python)
pip-audit                              # CVEs
pip list --outdated                    # outdated packages
pip install pip-upgrader && pip-upgrade requirements.txt --dry-run

# Frontend (Node)
npm audit                              # CVEs
npm outdated                           # outdated packages
npx npm-check-updates                  # show available updates

# Docker images
trivy image backend:latest             # image CVEs
```

### Phase 2 — Plan
- [ ] Categorize updates:

| Type | Risk | Approach |
|------|------|----------|
| **Patch** (1.1.1 → 1.1.2) | Low | Batch and apply |
| **Minor** (1.1.x → 1.2.0) | Medium | Review changelogs, apply in groups |
| **Major** (1.x.x → 2.0.0) | High | One at a time, dedicated PR |
| **Security** (any CVE) | Urgent | Prioritize regardless of version jump |

- [ ] Read changelogs for breaking changes
- [ ] Check if major updates have migration guides

### Phase 3 — Update
```bash
# Backend — update one at a time for major, batch for patch
pip install --upgrade package-name
pip freeze > requirements.txt

# Frontend — interactive update
npx npm-check-updates -u --target minor   # minor + patch
npm install

# Or specific package
npm install package-name@latest
```

### Phase 4 — Verify
- [ ] All tests pass
- [ ] Application starts correctly
- [ ] Critical user flows work
- [ ] No new deprecation warnings
- [ ] No bundle size regression (frontend)

```bash
# Backend
pytest tests/ -v --tb=short

# Frontend
npx vitest run
npm run build    # check for build errors

# Smoke test
docker compose up -d --build
curl http://localhost:8000/api/health
```

### Phase 5 — Commit
```bash
git add requirements.txt package.json package-lock.json
git commit -m "chore(deps): upgrade dependencies (April 2026)

Updated:
- fastapi 0.114.0 → 0.115.0 (security fix CVE-2026-XXXX)
- react 19.0.0 → 19.1.0
- pytest 8.2.0 → 8.3.0

No breaking changes. All 384 tests pass."
```

## Schedule
- **Security patches**: immediately on discovery
- **Patch updates**: weekly or bi-weekly
- **Minor updates**: monthly
- **Major updates**: quarterly (planned, with migration)

## See Also
- [rules/security.md](../rules/security.md) — dependency security scanning
- [rules/git-conventions.md](../rules/git-conventions.md) — commit format for dependency updates
- [agents/devops-engineer.md](../agents/devops-engineer.md) — CI pipeline for dependency checks

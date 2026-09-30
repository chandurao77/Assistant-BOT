# Command: New Feature

## Usage
```
/new-feature <name> [options]
```

## Workflow

### 1. Plan
- Define the feature scope and acceptance criteria
- Identify affected components (frontend, backend, database, infra)
- Estimate complexity and break into tasks
- Check for existing patterns in the codebase to follow

### 2. Design
- Define API contract (request/response schemas)
- Design database schema changes (if any)
- Plan UI components and state management
- Identify security considerations

### 3. Implement
- Create feature branch: `feat/<name>`
- Backend: routes → services → models → tests
- Frontend: types → API client → hooks → components → tests
- Database: migration → seed data (if needed)

### 4. Test
- Unit tests for business logic
- Integration tests for API endpoints
- Component tests for UI
- Manual testing of the full flow

### 5. Review & Ship
- Self-review the diff before requesting review
- Run full test suite and linter
- Create PR with description, screenshots, and test plan
- Address review feedback

## Options
| Flag | Description |
|------|-------------|
| `--backend-only` | Generate only backend scaffolding |
| `--frontend-only` | Generate only frontend scaffolding |
| `--with-migration` | Include database migration |
| `--with-tests` | Generate test files alongside implementation |

## File Generation Template
```
Backend:
  app/api/routes/<name>.py      — API endpoint
  app/services/<name>.py        — Business logic
  app/models/<name>.py          — Pydantic schemas
  tests/test_<name>.py          — Tests

Frontend:
  src/components/<Name>/        — UI components
  src/hooks/use<Name>.ts        — State management
  src/services/<name>Api.ts     — API client
  src/components/<Name>/*.test  — Tests
```

## Checklist
- [ ] API contract documented
- [ ] Database migration (if schema changes)
- [ ] Input validation on all new endpoints
- [ ] Auth/RBAC applied to new routes
- [ ] Tests written (unit + integration)
- [ ] Error handling for all failure paths
- [ ] Loading/error/empty states in UI
- [ ] Feature flag (if gradual rollout needed)

## See Also
- [rules/api-conventions.md](../rules/api-conventions.md) — API design standards for new endpoints
- [rules/testing.md](../rules/testing.md) — test coverage expectations
- [rules/git-conventions.md](../rules/git-conventions.md) — branch naming and PR format
- [commands/review.md](review.md) — review workflow for the feature PR

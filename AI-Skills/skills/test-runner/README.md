---
name: test-runner
description: "Test orchestration across the full stack — pytest, Vitest, Playwright, parallel execution, CI integration, and coverage reporting. USE FOR: run tests, fix failing tests, add test configuration, set up CI test matrix, generate coverage report."
argument-hint: "Describe the test task, e.g. 'run backend tests with coverage and stop on first failure'"
---

# Skill: Test Runner

## Purpose
Orchestrate test execution across the full stack — backend unit tests, frontend component tests, and E2E tests — with intelligent filtering, parallel execution, and clear reporting.

## Quick Start
```bash
# Run everything
./test-runner.sh all

# Run specific layer
./test-runner.sh backend
./test-runner.sh frontend
./test-runner.sh e2e

# Run matching tests
./test-runner.sh backend --filter "test_cache"
./test-runner.sh frontend --filter "Header"
```

## Test Execution Matrix

### Backend (Python / pytest)
```bash
# Full suite
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -v --tb=short"

# Quick (stop on first failure)
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -q -x"

# With coverage
podman compose exec backend sh -c "cd /app && python -m pytest tests/ --cov=app --cov-report=term-missing"

# Specific file
podman compose exec backend sh -c "cd /app && python -m pytest tests/test_rag_pipeline.py -v"

# Matching pattern
podman compose exec backend sh -c "cd /app && python -m pytest tests/ -k 'cache' -v"
```

### Frontend (Vitest)
```bash
# Full suite
cd frontend && npx vitest run --reporter=verbose

# Watch mode (development)
cd frontend && npx vitest

# With coverage
cd frontend && npx vitest run --coverage

# Specific file
cd frontend && npx vitest run src/services/api.test.ts

# UI mode
cd frontend && npx vitest --ui
```

### E2E (Playwright)
```bash
# Full suite
cd frontend && npx playwright test

# Headed mode (see browser)
cd frontend && npx playwright test --headed

# Specific test
cd frontend && npx playwright test tests/login.spec.ts

# Debug mode
cd frontend && npx playwright test --debug

# Generate report
cd frontend && npx playwright show-report
```

## Output Interpretation

### Pass/Fail Summary
```
Backend:  319 passed, 0 failed (8.2s)  ✅
Frontend:  65 passed, 0 failed (7.5s)  ✅
E2E:        0 tests (not configured)   ⚠️
─────────────────────────────────────────
Total:    384 passed, 0 failed          ✅
```

### Failure Analysis
When tests fail, investigate in this order:
1. **Read the error message** — most failures have clear descriptions
2. **Check the assertion** — expected vs actual values
3. **Check test isolation** — does it pass alone? (`pytest -k "failing_test"`)
4. **Check recent changes** — `git diff` the file under test
5. **Check test data** — are fixtures/mocks set up correctly?

## CI Integration
```yaml
# GitHub Actions example
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Backend tests
      run: |
        podman compose up -d backend
        podman compose exec backend sh -c "cd /app && python -m pytest tests/ -q --tb=short"
    - name: Frontend tests
      run: |
        cd frontend && npm ci && npx vitest run
```

## Best Practices
- Run tests before every commit (use pre-commit hook)
- Run full suite in CI on every PR
- Fix broken tests immediately — never skip or ignore
- Keep test suite fast: < 30s for unit, < 5min for full suite
- Quarantine flaky tests — track and fix within one sprint

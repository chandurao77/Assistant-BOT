# Rule: Testing

## Testing Pyramid
```
        ╱ E2E ╲           Few, slow, high confidence
       ╱───────╲
      ╱ Integr. ╲         Moderate count, test boundaries
     ╱───────────╲
    ╱  Unit Tests  ╲      Many, fast, test logic
   ╱─────────────────╲
```

## Unit Tests
- Test **one behavior** per test
- Name clearly: `test_negative_answer_not_cached` not `test_cache_3`
- Follow **Arrange → Act → Assert** pattern
- Mock external dependencies (HTTP, DB, file system)
- Don't mock the thing you're testing
- Keep tests independent — no shared mutable state
- Fast: entire unit suite should run in < 30 seconds

## Integration Tests
- Test real interactions between components
- Use test databases / test containers (not mocks)
- Test API endpoints end-to-end (request → response)
- Test database queries with real schema
- Test auth flows (login → access protected route → rejected without token)
- Clean up test data after each test

## E2E Tests
- Cover critical user flows only (login, core feature, checkout)
- Use Page Object Model for maintainability
- Run against a staging environment, not production
- Accept some flakiness — retry once before failing
- Keep count low (10-30 tests max for most apps)

## Test Quality Checklist
- [ ] Tests fail when the feature breaks (not just coverage theater)
- [ ] Edge cases covered: null, empty, boundary, error paths
- [ ] No hardcoded magic values — use constants or factories
- [ ] Tests don't depend on execution order
- [ ] Tests don't depend on real time (use faked clocks)
- [ ] Async tests properly awaited
- [ ] Test data cleaned up (no pollution across tests)

## Coverage Targets
| Layer | Target | Notes |
|-------|--------|-------|
| Business logic / services | 85%+ | Core value — must be tested |
| API routes | 80%+ | Request validation, auth, error handling |
| Utilities / helpers | 90%+ | Pure functions — easy to test |
| UI components | 70%+ | Interaction and rendering, not styling |
| Config / boilerplate | Optional | Don't chase coverage on trivial code |

## Test Commands
```bash
# Backend (Python)
pytest tests/ -v --tb=short          # All tests, verbose
pytest tests/ -x                      # Stop on first failure
pytest tests/ -k "test_cache"         # Run matching tests
pytest tests/ --cov=app --cov-report=term-missing  # With coverage

# Frontend (Vitest)
npx vitest run                        # All tests, single run
npx vitest run --reporter=verbose     # Verbose output
npx vitest --coverage                 # With coverage
npx vitest --ui                       # Interactive UI

# E2E (Playwright)
npx playwright test                   # All E2E tests
npx playwright test --headed          # With browser visible
npx playwright show-report            # View HTML report
```

## CI Integration
- Tests run on every push and PR
- PRs blocked if tests fail
- Coverage reported but not gated (avoid gaming)
- Test results visible in PR comments
- Flaky test quarantine: mark as `@pytest.mark.flaky` and fix within 1 sprint

## See Also
- [agents/test-engineer.md](../agents/test-engineer.md) — test strategy design and expertise
- [skills/test-runner/README.md](../skills/test-runner/README.md) — test execution commands and CI setup
- [commands/debug.md](../commands/debug.md) — debugging test failures

# Command: Debug

Structured workflow for diagnosing and resolving bugs systematically.

## Usage
```
/debug <symptom> [--component <name>] [--severity <p1|p2|p3>]
```

## Phases

### Phase 1 — Reproduce
- [ ] Get exact reproduction steps (who, what, when, how often)
- [ ] Reproduce locally — if you can't reproduce it, you can't fix it
- [ ] Identify: is it consistent or intermittent?
- [ ] Capture: error message, stack trace, logs, screenshots

```bash
# Check recent logs
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend

# Check health
curl http://localhost:8000/api/health
```

### Phase 2 — Isolate
- [ ] Narrow down the component (frontend / backend / database / infra)
- [ ] Find the exact line or function where behavior diverges from expectation
- [ ] Binary search through recent commits if regression:

```bash
git log --oneline -20                    # Find suspect range
git bisect start
git bisect bad HEAD
git bisect good <known-good-commit>
# Test at each step, mark good/bad
```

**Isolation techniques:**
| Technique | When |
|-----------|------|
| Add logging | Don't know what's happening |
| Use debugger | Know where, need to inspect state |
| Simplify input | Complex input triggers the bug |
| Disable components | Not sure which component is the cause |
| Check recent changes | "It worked yesterday" |
| Compare environments | Works locally, fails in staging |

### Phase 3 — Diagnose
- [ ] Identify the **root cause** (not just the symptom)
- [ ] Ask: why did this happen? Could it happen elsewhere?
- [ ] Common root causes:

| Category | Examples |
|----------|---------|
| State | Race condition, stale cache, missing initialization |
| Input | Unvalidated input, edge case, encoding issue |
| Dependency | API change, version mismatch, timeout |
| Config | Wrong environment variable, missing secret |
| Logic | Off-by-one, wrong operator, missing null check |

### Phase 4 — Fix
- [ ] Write a failing test that reproduces the bug
- [ ] Implement the minimal fix
- [ ] Verify the test now passes
- [ ] Check for similar bugs in related code
- [ ] Run full test suite

```bash
# Write test first
pytest tests/test_module.py::test_the_bug -v    # Should FAIL

# Fix the code, then
pytest tests/test_module.py::test_the_bug -v    # Should PASS
pytest tests/ -q                                 # All tests pass
```

### Phase 5 — Verify & Document
- [ ] Reproduce original steps — bug is gone
- [ ] No regressions introduced
- [ ] Commit with root cause in message:

```
fix(component): short description

Root cause: <what actually went wrong>
Fix: <what you changed and why>
Closes #<issue-number>
```

## Debugging Cheat Sheet
```bash
# Python
python -m pdb script.py                   # Debugger
python -c "import traceback; traceback.print_exc()"
PYTHONDONTWRITEBYTECODE=1 python -v       # Verbose imports

# Network
curl -v http://localhost:8000/api/health   # Verbose HTTP
docker compose exec backend sh -c "nslookup qdrant"  # DNS check

# Docker
docker compose logs -f backend             # Stream logs
docker compose exec backend sh             # Shell into container
docker inspect <container_id>              # Full container info

# Database
docker compose exec postgres psql -U user -d db -c "SELECT 1"
```

## See Also
- [commands/fix-issue.md](../commands/fix-issue.md) — broader issue resolution workflow
- [rules/testing.md](../rules/testing.md) — writing regression tests
- [skills/monitoring/README.md](../skills/monitoring/README.md) — finding bugs through observability

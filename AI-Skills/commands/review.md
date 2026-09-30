# Command: Code Review

## Usage
```
/review [scope] [options]
```

## Scope
| Scope | Description |
|-------|-------------|
| `--staged` | Review staged git changes (default) |
| `--branch` | Review all changes on current branch vs main |
| `--file <path>` | Review a specific file |
| `--pr <number>` | Review a pull request |

## Review Process

### Pass 1: Security Scan
- [ ] No hardcoded secrets, tokens, or credentials
- [ ] Input validation at all entry points
- [ ] SQL/NoSQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding)
- [ ] Authentication/authorization checks on protected routes
- [ ] No sensitive data in logs or error messages

### Pass 2: Correctness
- [ ] Logic handles edge cases (null, empty, boundary values)
- [ ] Error handling covers all failure paths
- [ ] Async operations properly awaited
- [ ] Resources cleaned up (connections, file handles, listeners)
- [ ] Race conditions addressed in concurrent code
- [ ] Type safety maintained (no unsafe casts or `any`)

### Pass 3: Quality
- [ ] Single responsibility — each function/class does one thing
- [ ] Naming is clear and consistent
- [ ] No dead code, commented-out blocks, or TODOs without tickets
- [ ] Tests exist and are meaningful
- [ ] Dependencies justified and up-to-date
- [ ] Performance considerations for hot paths

### Pass 4: Maintainability
- [ ] Code follows existing project patterns
- [ ] Complex logic has comments explaining "why" (not "what")
- [ ] Public APIs have docstrings/JSDoc
- [ ] Changes are backward compatible (or migration path provided)

## Output Format
```markdown
## Review Summary
**Risk Level**: LOW | MEDIUM | HIGH | CRITICAL

### Must Fix (Blockers)
1. [SECURITY] Description → Suggested fix

### Should Fix
1. [BUG] Description → Suggested fix

### Nits
1. [STYLE] Description → Suggestion

### Positive Notes
- Good use of X pattern in Y file
```

## Options
| Flag | Description |
|------|-------------|
| `--security-only` | Run security checks only |
| `--verbose` | Include line-by-line annotations |
| `--auto-fix` | Apply auto-fixable suggestions |

## See Also
- [agents/code-reviewer.md](../agents/code-reviewer.md) — reviewer persona and expertise
- [rules/security.md](../rules/security.md) — detailed security checklist for Pass 1
- [rules/code-style.md](../rules/code-style.md) — style conventions for Pass 3

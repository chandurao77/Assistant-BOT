# Rule: Git Conventions

## Branch Naming
```
<type>/<short-description>

Types:
  feature/   — new functionality
  fix/       — bug fix
  hotfix/    — urgent production fix
  refactor/  — code restructuring (no behavior change)
  chore/     — tooling, deps, config
  docs/      — documentation only
  test/      — adding or fixing tests
```

**Examples:**
- `feature/user-auth-oidc`
- `fix/cache-staleness-negative-answers`
- `refactor/extract-embedding-service`

**Rules:**
- Lowercase, kebab-case
- Max 50 characters for description
- No personal names or ticket-only branches (`fix/JIRA-123` is bad — add context)

## Commit Messages
```
<type>(<scope>): <subject>

<body>           ← optional, wrap at 72 chars
<footer>         ← optional (BREAKING CHANGE, Closes #123)
```

### Types
| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `chore` | Build, CI, deps, config |
| `perf` | Performance improvement |
| `style` | Formatting (no logic change) |

### Examples
```
feat(auth): add OIDC SSO login flow

fix(cache): skip caching negative LLM responses

refactor(rag): extract reranker into standalone service

test(api): add integration tests for conversation endpoints

chore(deps): bump fastapi to 0.115.0

BREAKING CHANGE: remove v1 API endpoints
```

### Rules
- Subject line: imperative mood, no period, max 72 chars
- Body: explain **why**, not what (the diff shows what)
- One logical change per commit — don't mix refactor + feature
- Never commit secrets, `.env` files, or large binaries

## Pull Requests
### Title
Same format as commit subject: `type(scope): description`

### Description Template
```markdown
## What
Brief description of the change.

## Why
Context, motivation, or link to issue.

## How
Implementation approach (if non-obvious).

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing done (describe scenario)

## Checklist
- [ ] No secrets committed
- [ ] Docs updated (if applicable)
- [ ] Breaking changes documented
```

### Rules
- Keep PRs small: < 400 lines changed (excluding tests and generated files)
- One concern per PR — don't bundle unrelated changes
- Request review from at least 1 person
- Don't merge your own PR unless it's a hotfix
- Squash merge to keep `main` history clean

## Tags & Releases
```
v<major>.<minor>.<patch>

v1.0.0   — first stable release
v1.1.0   — new feature (backward compatible)
v1.1.1   — bug fix
v2.0.0   — breaking change
```

## See Also
- [rules/code-style.md](../rules/code-style.md) — naming conventions enforced in code
- [commands/review.md](../commands/review.md) — PR review workflow
- [commands/fix-issue.md](../commands/fix-issue.md) — commit message template for fixes

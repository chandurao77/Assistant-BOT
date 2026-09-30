# Command: Fix Issue

## Usage
```
/fix-issue <issue-id> [options]
```

## Workflow

### 1. Understand
- Read the issue description, labels, and linked PRs
- Reproduce the bug locally (if applicable)
- Identify the root cause, not just the symptom

### 2. Investigate
- Search codebase for related code (`grep`, `git log`, `git blame`)
- Check recent changes that may have introduced the issue
- Review test coverage for the affected area

### 3. Fix
- Make the minimal change that fixes the root cause
- Don't refactor unrelated code in the same fix
- Add a regression test that fails without the fix and passes with it

### 4. Verify
- Run the full test suite
- Test edge cases manually if the fix involves user-facing behavior
- Check that the fix doesn't break other functionality

### 5. Document
- Write a clear commit message: `fix: <what was broken> (#issue-id)`
- Explain the root cause and fix in the PR description
- Update documentation if the fix changes behavior

## Options
| Flag | Description |
|------|-------------|
| `--branch` | Create a fix branch automatically (`fix/issue-<id>`) |
| `--test-only` | Only generate the regression test, don't apply the fix |
| `--dry-run` | Show what would change without modifying files |

## Commit Message Format
```
fix: prevent cached negative answers from being served after re-ingestion (#142)

Root cause: The semantic cache stored "I don't have enough information"
responses. After new content was ingested, the stale cached negative
answer was returned instead of querying the updated knowledge base.

Fix: Skip caching any LLM response containing negative-answer phrases.
Added 3 regression tests.
```

## See Also
- [commands/debug.md](debug.md) — structured debugging workflow
- [rules/testing.md](../rules/testing.md) — regression test standards
- [rules/git-conventions.md](../rules/git-conventions.md) — branch and commit conventions

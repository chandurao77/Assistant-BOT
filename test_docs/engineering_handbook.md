# Engineering Handbook

Orbit Labs is a fictional company used for this demo. This handbook describes how the engineering team works.

## Branching and Pull Requests

- The default branch is `main`. It is always deployable.
- Create short-lived branches named `feature/<ticket>-<summary>`, `fix/<ticket>-<summary>` or `chore/<summary>`.
- Keep pull requests under 400 changed lines. Split larger work into a stack of smaller PRs.
- Every PR needs one approval from a code owner and a green CI run before merging.
- Use "Squash and merge" so that `main` keeps one commit per change.

## Code Review Expectations

- Reviewers respond within one business day.
- Review for correctness first, then readability, then style. Formatting is handled by the auto-formatter.
- Authors resolve every comment or explain why they disagree. Reviewers do not block on personal preference.

## Continuous Integration

The CI pipeline runs on every push and has these stages:

1. **Lint and format**: `ruff` and `black` for Python, `eslint` and `prettier` for TypeScript.
2. **Unit tests**: must finish in under 5 minutes. Coverage must not drop below 80%.
3. **Build**: container images are built and tagged with the commit SHA.
4. **Security scan**: dependency audit and container image scan. Critical findings fail the build.

## Coding Standards

- Python 3.11 with type hints on all public functions.
- TypeScript in strict mode. Avoid `any`.
- Functions should do one thing. If a function needs a comment to explain each block, split it.
- Log with structured key/value fields, never with string concatenation.
- Never log secrets, tokens, or personal data.

## Testing Policy

- Every bug fix ships with a regression test.
- Prefer many fast unit tests over a few slow end-to-end tests.
- Integration tests use real containers (Postgres, Redis) started by the test harness, not mocks of the database.

## Release Cadence

- Services deploy continuously to staging on every merge to `main`.
- Production releases happen Tuesday and Thursday at 10:00 UTC. There is a change freeze on Fridays and before public holidays.
- Hotfixes can go out at any time with approval from the on-call lead.

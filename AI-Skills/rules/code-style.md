# Rule: Code Style

## General
- **Readability over cleverness** — code is read 10x more than it's written
- **Consistency over preference** — follow the project's existing style
- **Explicit over implicit** — make intent clear without requiring deep context

## Naming Conventions

### Python
- `snake_case` for functions, variables, modules
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- `_leading_underscore` for private/internal
- Prefix booleans: `is_active`, `has_permission`, `can_edit`

### TypeScript/JavaScript
- `camelCase` for functions, variables
- `PascalCase` for classes, components, types, interfaces
- `UPPER_SNAKE_CASE` for constants
- Prefix hooks: `useChat`, `useTheme`
- Prefix booleans: `isLoading`, `hasError`, `canSubmit`

### Files
- Python: `snake_case.py`
- TypeScript components: `PascalCase.tsx`
- TypeScript utilities/hooks: `camelCase.ts`
- Tests: `<name>.test.ts` or `test_<name>.py`

## Functions
- One function, one purpose — if you need "and" to describe it, split it
- Max 20-30 lines (guideline, not dogma)
- Max 3-4 parameters; use an options/config object for more
- Return early for guard clauses — avoid deep nesting
- Name functions as verb phrases: `calculateTotal()`, `fetchUser()`, `validateInput()`

## Comments
- **Don't**: explain what the code does (the code should be clear)
- **Do**: explain why — business rules, workarounds, non-obvious decisions
- **Do**: link to tickets for temporary workarounds: `# HACK: workaround for BUG-123`
- **Don't**: leave commented-out code — use version control instead
- **Do**: document public APIs with docstrings/JSDoc

## Error Handling
- Catch specific exceptions, not bare `except:` / `catch {}`
- Log errors with context (request ID, user ID, input that caused it)
- Don't swallow errors silently — at minimum log them
- Use custom error types for domain-specific failures

## Imports
- Group: stdlib → third-party → local (with blank lines between)
- Prefer explicit imports over wildcards: `from x import y` not `from x import *`
- Sort alphabetically within groups
- Remove unused imports

## Formatting
- Use a formatter (Black for Python, Prettier for TS/JS) — don't argue about style
- Use a linter (Ruff for Python, ESLint for TS/JS) — catch bugs early
- Configure once in project config, run on save and in CI

## See Also
- [rules/documentation.md](documentation.md) — comment and docstring standards
- [rules/git-conventions.md](git-conventions.md) — commit message and branch naming style
- [hooks/post-edit-lint.sh](../hooks/post-edit-lint.sh) — automated lint enforcement

# Command: Refactor

Structured workflow for safely restructuring code without changing behavior.

## Usage
```
/refactor <target> [--scope <module|function|class>] [--reason <why>]
```

## Phases

### Phase 1 — Identify
- [ ] Define what to refactor and why (complexity, duplication, coupling)
- [ ] Identify the blast radius — what depends on this code?
- [ ] Confirm existing test coverage (add tests BEFORE refactoring if missing)
- [ ] Document current behavior as a baseline

```bash
# Check coverage of target
pytest tests/ --cov=app/services/target_module --cov-report=term-missing
# Find all usages
grep -rn "target_function\|TargetClass" backend/app/
```

### Phase 2 — Plan
- [ ] Choose refactoring pattern:

| Pattern | When to Use |
|---------|-------------|
| Extract function/method | Function > 30 lines or does multiple things |
| Extract class/module | Class has too many responsibilities |
| Inline | Abstraction adds complexity without value |
| Rename | Name doesn't communicate intent |
| Move | Code is in the wrong module/layer |
| Replace conditional with polymorphism | Complex if/elif chains |
| Introduce parameter object | Function has > 4 parameters |

- [ ] Break into small, independently verifiable steps
- [ ] Each step must keep tests green

### Phase 3 — Execute
- [ ] Make ONE refactoring move at a time
- [ ] Run tests after EVERY move
- [ ] Commit after each successful move (small commits)
- [ ] Never mix refactoring with behavior changes

```bash
# After each move
pytest tests/ -q -x
git add -A && git commit -m "refactor(scope): describe single move"
```

### Phase 4 — Verify
- [ ] All existing tests still pass
- [ ] No behavior change (same inputs → same outputs)
- [ ] Code metrics improved:

| Metric | Check |
|--------|-------|
| Cyclomatic complexity | Reduced or unchanged |
| Function length | ≤ 30 lines |
| Parameter count | ≤ 4 |
| Duplication | Reduced |
| Coupling | Reduced (fewer imports between modules) |

- [ ] Run linters and type checkers
- [ ] Review diff — is the code actually simpler?

### Phase 5 — Clean Up
- [ ] Remove dead code (unused imports, functions, variables)
- [ ] Update docstrings if function signatures changed
- [ ] Update any documentation referencing changed APIs
- [ ] Final commit with summary

```
refactor(module): restructure X for clarity

- Extracted Y into standalone service
- Reduced function complexity from 12 to 4
- No behavior change — all 42 tests pass
```

## Anti-Patterns
- **Big bang refactor** — changing everything at once. Break it down.
- **Refactor + feature** — never combine. Separate PRs.
- **Refactor without tests** — add tests first, then refactor.
- **Premature abstraction** — don't extract until you see the pattern 3 times.
- **Renaming everything** — only rename if the current name actively misleads.

## See Also
- [rules/code-style.md](../rules/code-style.md) — target code style after refactoring
- [commands/review.md](../commands/review.md) — review the refactoring PR
- [rules/testing.md](../rules/testing.md) — ensure test coverage before refactoring

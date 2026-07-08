---
name: engineering-workflow
description: Core working principles for every engineering task — bug fixes, improvements, refactors, new features, investigations, and agent/loop design in any project. Use this skill on every substantive task, even when the user gives only a one-line problem statement like "the build is broken", "make this faster", or "add retries here". It defines how to discover, scope, implement, verify, and report work.
---

# Engineering Workflow

The user will often give you only a problem statement. Take it
end-to-end: investigate, assess, propose, implement, verify —
following the rules below.

## Discovery first

Do NOT assume what the project contains. At the start of every
task, explore the repo (directory listing, grep, read the relevant
modules, check recent commits) and base all work on what is
actually implemented — never on what you expect a project like
this to contain. If the user mentions a feature, file, or module
you can't find, say so instead of inventing it. State which
module(s) own the problem, with file references from your own
reading, before proposing anything.

## Workflow when given a problem statement

1. **Locate before you theorize.** Find the actual code path for
   the symptom first.
2. **Reproduce or evidence it.** Run the failing case or a test if
   possible. If you can't reproduce, say so and list what evidence
   you're working from instead.
3. **Assess first when the user is describing or thinking.** If
   the message is a question, an observation, or thinking out
   loud, the deliverable is your assessment. Report findings and
   stop. Don't apply a fix until asked.
4. **Fix at the smallest correct scope.** Prefer changing one
   module over cross-cutting refactors unless the problem is
   structural. Never bundle unrelated cleanups into a fix.
5. **Check before destructive actions.** Before any command that
   changes system state (deletes, restarts, migrations, config
   edits, force pushes), confirm the evidence supports that
   specific action.
6. **Verify before reporting.** Audit every claim against an
   actual tool result from this session — test output, a run, a
   diff, a query result. Only report work you can point to
   evidence for. If tests fail, say so with the output. If a step
   was skipped, say that. No optimistic status.
7. **Report outcome-first:** what changed, evidence it works,
   risks, and the suggested next step. No internal shorthand,
   arrow chains, or working abbreviations in the final summary.

## Loop and agent engineering rules

When designing or improving any retry, evaluation, or agent loop:

- **Evaluate → Repair:** score output against evidence before
  accepting it. Below threshold → retry with the critique
  injected; above → continue.
- **Always bound loops:** max-iteration cap (default 2) plus a
  fallback that surfaces the low-confidence result labeled as
  such — never silently loop or silently drop.
- **Gate side effects:** actions with external effects (alerts,
  writes, notifications) need an explicit approval step or
  clearly-configured automation; read-only steps are exempt.
- **Routing must be inspectable:** log which condition fired and
  why, so failures can be traced step-by-step.
- **Token discipline:** retries reuse already-processed context;
  never re-send raw bulk data on a retry.

## Cost and performance

If the change touches an LLM call path, a hot loop, or anything
metered, estimate the cost/latency impact and include it in the
report. Regressions need explicit justification.

## Non-negotiable checks before calling anything done

- [ ] Explored the actual repo state before making claims about it
- [ ] Tests pass (run them; paste the relevant output) — or state
      clearly that no tests cover this path
- [ ] Existing optimizations not regressed if their area was
      touched (measure before/after)
- [ ] The affected UI route/screen actually renders if frontend
      was touched
- [ ] Cost/latency impact estimated if an LLM or metered path
      changed

## Memory

Maintain `LESSONS.md` in the repo root. One lesson per entry, a
one-line summary on top, including why it mattered. Record both
corrections and confirmed approaches. Don't duplicate what the
repo or git history already records; update rather than duplicate;
delete lessons proven wrong. Read `LESSONS.md` before starting any
substantive task.

## Context intake

If the user's request is ambiguous about the larger goal or the
audience, make the most reasonable assumption, state it in one
line, and proceed — don't stall on clarifying questions for things
the repo or the task itself can answer.

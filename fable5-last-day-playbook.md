# Fable 5 — Last-Day Playbook (July 7)

Goal: spend the remaining allowance only on tasks that produce durable
.md files you keep using after Fable moves to credits. Run in this
order — stop wherever the allowance runs out. Each prompt is
copy-paste ready for Claude Code with effort on high.

---

## 1. Seed LESSONS.md from your repo history (QueryQuokka)

Why first: this is the memory file every future Opus 4.8 session
reads. Fable mining months of git history once = compounding value
forever.

```
Read the full git history of this repo: log, diffs of the 30 most
significant commits, reverted commits, and bug-fix commits. Also read
the current code. Produce LESSONS.md in the repo root: one lesson per
entry, one-line summary on top, why it mattered, which files it
applies to. Only include lessons specific to THIS codebase — delete
anything that would be true of any project. Include mistakes that
were fixed (from revert/fix commits) so they are never repeated.
```

Repeat in the ATLAS repo if allowance permits.

---

## 2. Stress-test the CLAUDE.md + skills we built

Why: Fable is the strongest reviewer you'll have access to. Let it
attack the rule files before they harden into habit.

```
Read ~/.claude/CLAUDE.md, ~/.claude/skills/loop-engineering/SKILL.md,
and .claude/skills/queryquokka-engineer/SKILL.md. Act as a hostile
reviewer: find rules that are ambiguous, contradictory, unenforceable,
or that would cause you to behave worse on real tasks in this repo.
Test each rule against 3 realistic task scenarios from this codebase.
Then rewrite all three files with your fixes. Keep them at or under
their current length.
```

---

## 3. LangGraph migration design doc (QueryQuokka)

Why: your hardest open design problem — exactly what Fable is for.
The output guides months of Opus-4.8-level implementation work.

```
Read the current 6-agent pipeline code end to end. Produce
docs/langgraph-migration.md: target graph with conditional routing,
Evaluator+Repair loop (bounded, max 2 repairs, labeled low-confidence
fallback), human interrupt gate for side effects, and a step-by-step
migration plan where each step ships independently and the pipeline
stays runnable after every step. Include per-node token/cost impact
estimates and the test plan per step. Flag every place the current
code makes an assumption that breaks under graph routing.
```

---

## 4. ATLAS retrieval audit → tuning doc

Why: your 92% benchmark has a stubborn last 8%. Fable reasoning over
the failure cases once produces a roadmap Opus can execute.

```
Read the reranking pipeline (keyword/vector/page-type scoring,
thresholds, multi-hop trigger) and the benchmark results including
the failing questions. For each failure, trace the exact scoring path
that produced the wrong answer. Produce docs/retrieval-tuning.md:
failure taxonomy, root cause per failure, proposed parameter or logic
change, expected risk to currently-passing questions, and the order
to apply changes. No code changes — analysis doc only.
```

---

## 5. PolicyPilot memory + repair design

Why: the two pieces you're actively developing; a Fable-quality
design doc de-risks both.

```
Read the PolicyPilot agent pipeline. Produce docs/memory-and-repair.md:
(1) memory selection — what to store per conversation, selection
criteria at retrieval time, staleness/eviction rules; (2) repair loop
— evaluation criteria per intent (refunds, returns, shipping,
billing, warranty), bounded retries, and when to escalate to a human
instead of repairing. Include concrete failure examples the design
must handle.
```

---

## 6. Personal FDE system-design KB

Why: interview prep survives model switches; Fable writes the
strongest version of your own story.

```
Here are my three production AI systems: [paste ATLAS, QueryQuokka,
PolicyPilot summaries]. Produce fde-interview-kb.md: for each system,
the architecture narrative as I should tell it in an FDE interview
(problem → constraints → decisions → tradeoffs → results with
numbers), the 5 hardest follow-up questions an interviewer would ask
per system, and strong answers grounded in the actual design. Delete
any generic interview advice — only content specific to these
systems.
```

---

## Rules while running these

- One task per session, full context up front, effort high.
- Every session ends with: "Audit your output against the actual
  repo/tool results before finalizing. Then append one lesson to
  LESSONS.md."
- Coding/debugging may silently fall back to Opus 4.8 (new
  classifiers) — analysis/design prompts like the above are the
  least likely to be rerouted, another reason they're the right
  spend.
- Do NOT spend Fable on: routine bug fixes, resume tailoring,
  formatting, anything Opus 4.8 does fine.

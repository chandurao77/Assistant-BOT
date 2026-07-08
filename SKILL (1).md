---
name: loop-engineering
description: Rules for designing or modifying any retry, evaluation, agent, or automation loop — evaluator/repair patterns, retry logic, alerting pipelines, scheduled jobs, webhook handlers, agent orchestration. Use whenever the task involves loops that call LLMs, retry on failure, route between steps, or trigger side effects, even if the user just says "add retries" or "make this loop smarter".
---

# Loop Engineering

- **Evaluate → Repair:** score output against evidence before accepting. Below threshold → retry with the critique injected; above → continue.
- **Bound every loop:** max-iteration cap (default 2) plus a fallback that surfaces the low-confidence result labeled as such. Never silently loop or drop.
- **Gate side effects:** alerts, writes, notifications require an explicit approval step or clearly-configured automation. Read-only steps are exempt.
- **Inspectable routing:** log which condition fired and why on every branch, so failures trace step-by-step.
- **Token discipline:** retries reuse already-processed/compressed context. Never re-send raw bulk data on retry.

## Reflection hook

After completing a task that used this skill, evaluate in one or two lines whether these rules helped or got in the way. If a rule was wrong, missing, or unclear, append the finding to `LESSONS.md` under a `## skill-feedback` heading and propose the specific SKILL.md edit. Read that section on next load.

---
name: queryquokka-engineer
description: Project context for the QueryQuokka AI log investigation platform. Use on every QueryQuokka task — bugs, improvements, pipeline changes, UI fixes, onboarding, cost tuning — even one-line problem statements like "investigations are slow" or "the Analyzer is hallucinating".
---

# QueryQuokka

## Current repo state (injected at load)

Recent commits:
!`git log --oneline -10`

Working tree:
!`git status --short`

## Project context

- **Pipeline (6 agents, sequential):** Parser → TimeWindow → StreamClassifier → Summarizer → Analyzer → Assembler
- **Stack:** Python/FastAPI backend; React 18 + TypeScript frontend; Azure OpenAI (GPT-4o / GPT-4o-mini); Elasticsearch; PostgreSQL + pgvector; Redis; AWS ECS Fargate.
- **Budget:** ~$0.05 and ~30s per investigation. Report any change to either.

Verify which features/modules exist by reading the repo — do not assume beyond the above. If the user names something not found in the code, say so.

## Project-specific checks before done

- Token/cost optimizations not regressed if log handling or the LLM path was touched (measure before/after).
- Alerting/noise-reduction behavior verified against real or sample data if touched.
- Affected tab/route renders if investigation views were touched.

## Memory

Read `LESSONS.md` (repo root) before any substantive task. One lesson per entry, one-line summary on top. Update rather than duplicate; delete lessons proven wrong.

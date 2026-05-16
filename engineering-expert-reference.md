# Engineering Expert — Personal Reference

*A single-file reference covering software architect, senior engineer, code reviewer, QA/tester, frontend designer, and AI/ML engineer/researcher/analyst roles, with stack cheatsheets for Java/Spring, Python/FastAPI, React/TypeScript, and AWS/Azure/DevOps.*

---

## Table of Contents

**Roles**
- [Software Architect](#software-architect)
- [Senior Engineer](#senior-engineer)
- [Code Reviewer](#code-reviewer)
- [QA / Tester](#qa--tester)
- [Frontend Designer](#frontend-designer)
- [AI/ML Engineer](#aiml-engineer)
- [AI/ML Researcher](#aiml-researcher)
- [AI/ML Analyst / Reviewer](#aiml-analyst--reviewer)

**Stack cheatsheets**
- [Stack: Java / Spring](#stack-java--spring)
- [Stack: Python / FastAPI / AI-ML](#stack-python--fastapi--ai-ml)
- [Stack: React / TypeScript / Vite / Tailwind](#stack-react--typescript--vite--tailwind)
- [Stack: Cloud / DevOps (AWS, Azure, Docker, K8s, Terraform, CI/CD)](#stack-cloud--devops-aws-azure-docker-kubernetes-terraform-cicd)

---

# Architect

## Mindset

The architect answers "what shape should this system be" — not "what code to write." Optimize for change. Most systems fail because the second feature was hard to add, not because the first feature was slow.

## Default questions before answering any design request

1. What's the scale? (RPS, data volume, user count, growth rate)
2. What's the latency budget? p50, p99, hard cap.
3. What's the consistency requirement? Strong, read-your-writes, eventual.
4. What's the team size and skill profile?
5. What's the deploy target? Cloud-native, on-prem, hybrid.
6. What's the failure budget? (uptime SLO)
7. What does "done" look like in 6 months vs 2 years?

If the user hasn't answered these, name your assumptions in the response.

## Trade-off frameworks

### CAP / PACELC
Pick two of Consistency, Availability, Partition tolerance. Partitions happen, so really you're picking C vs A during a partition. PACELC: Else, pick Latency vs Consistency. Most "we need strong consistency everywhere" requests are really "we need it on this one write path."

### Latency vs throughput vs cost
You get two. Lambda gives latency + cost but tanks throughput at scale; Kafka gives throughput + cost but adds latency; in-memory grids give latency + throughput but cost.

### Build vs buy vs OSS
- **Buy** when solved and not your differentiator (auth, payments, observability).
- **OSS** when mature with a real community (Postgres, Kafka, Redis, Qdrant).
- **Build** only when the thing IS your product or no acceptable option exists.

## Patterns: when to use, when to avoid

| Pattern | Use when | Don't use when |
|---|---|---|
| Monolith | Team < 20, single domain, early | Multiple independent teams, conflicting deploy cadences |
| Microservices | Independent teams + scaling needs | Team < 20, shared data model, no platform team |
| Event-driven (Kafka) | Multiple consumers, replayability, async scale | Strict req/response, low volume, single consumer |
| CQRS + Event Sourcing | Audit/replay is a hard requirement | CRUD-shaped app, small team |
| Saga (orchestration) | Distributed transactions across 3+ services | Two services — don't span them |
| API Gateway / BFF | Multiple clients with different needs | Single client, simple system |
| Strangler Fig | Migrating off a legacy monolith | Greenfield |

## Data layer decisions

- **Postgres first.** JSON, full-text, geo, time-series (TimescaleDB) — most "we need NoSQL" is met by Postgres + indexing.
- **Add Redis** for sub-ms reads, distributed locks, rate limiting, session store.
- **Vector DB** (Qdrant, pgvector) only with a real semantic search / RAG workload.
- **Kafka** when multiple consumers, replayability, or producer/consumer rate mismatch.
- **Search engine** (OpenSearch) when relevance ranking is core.

## Cloud specifics

### AWS
- Compute: ECS Fargate for services, Lambda for spiky/event-driven, EKS only with platform team.
- Data: RDS Postgres (Aurora for scale), DynamoDB for known-pattern KV, S3 for blobs.
- Messaging: SQS queues, SNS fanout, EventBridge cross-service, MSK only if Kafka semantics required.
- Observability: CloudWatch + X-Ray baseline; Datadog/Honeycomb when you hit limits.

### Azure
- Compute: AKS for k8s, Container Apps simpler, Functions event-driven.
- Data: Azure SQL or Postgres Flexible Server, Cosmos DB multi-region KV.
- AI: Azure OpenAI hosted LLM; pair with AI Search for managed RAG or run Qdrant.
- Observability: Application Insights + Log Analytics.

## Scalability checklist

1. **Stateless services.** State in DB/cache, not the process.
2. **Horizontal first.** Vertical OK to ~16 cores; past that, scale out.
3. **Async the slow stuff.** > 100ms off critical path → queue.
4. **Cache aggressively, invalidate carefully.** Cache miss must never DDoS the origin.
5. **Read replicas** for read-heavy. Writes don't scale linearly.
6. **Shard only when forced.** Permanent complexity. Buy bigger boxes first.
7. **Backpressure everywhere.** Every async boundary: bounded queues + rejection policy.
8. **Idempotency keys** on every external write. Retries will happen.

## Failure modes to plan for upfront

- **Database failover.** RTO/RPO? Tested recently?
- **Cache stampede.** Redis dies, 10k requests miss — what happens?
- **Poison messages.** DLQ + alarm + replay tooling.
- **Slow dependency.** Timeouts + circuit breaker (resilience4j, tenacity).
- **Hot key.** 90% of traffic hits one tenant — what then?
- **Schema migration.** Backward-compatible; deploy in two phases (add → migrate → remove).

## Anti-patterns

- "We'll start with microservices" → modular monolith first.
- "We need our own auth" → Auth0, Cognito, Entra, Keycloak.
- "We need our own queue" → Kafka, SQS, RabbitMQ.
- "We need eventual consistency everywhere" → you need it in 2-3 places.
- "Observability later" → later is too late. Instrument day one.

## Output format for an architecture recommendation

```
RECOMMENDATION: [one sentence]

CONTEXT ASSUMED:
- [scale, latency, team, etc.]

DESIGN:
[components + how they connect]

TRADE-OFFS:
- Gain: [what you get]
- Cost: [what you pay]
- Risk: [what could go wrong]

ALTERNATIVES CONSIDERED:
1. [alt 1] — rejected because [reason]
2. [alt 2] — rejected because [reason]

OBSERVABILITY:
- Key metrics: [...]
- Key alerts: [...]
```


---

# Senior Engineer

You're the senior engineer when the question is **"how do I actually build/write this well."** Implementation, idioms, refactoring, debugging.

## Operating principles

1. **Code is read 10× more than written.** Optimize for the reader, not the writer.
2. **Make the change easy, then make the easy change.** (Kent Beck.) If a change is hard, refactor first.
3. **Explicit > clever.** A junior should be able to read your code at 2 AM during an incident.
4. **Functions do one thing.** If you need "and" to describe a function, split it.
5. **Boundaries: pure core, imperative shell.** Push side effects to the edges. Test the pure parts heavily.
6. **Errors are values, not exceptions** — when feasible. Return Result/Either; reserve exceptions for truly exceptional cases.
7. **Premature optimization is the root of evil; premature pessimization is also evil.** Don't write `O(n²)` when `O(n)` is the same effort.

## Code quality checklist

- [ ] **Naming**: would a stranger understand `processData` vs `enrichOrdersWithCustomerEmail`?
- [ ] **Function length**: most functions <30 lines. Long functions need a reason.
- [ ] **Parameter count**: >4 parameters → use an object/record.
- [ ] **Cyclomatic complexity**: nested if/switch hell → extract or table-drive.
- [ ] **Dependencies pointed inward** (clean architecture). Domain doesn't know about Spring/FastAPI.
- [ ] **Null/None handling**: explicit, not implicit. `Optional<T>`, `T | None`, nullable types in TS.
- [ ] **Time and randomness injected**, never read directly — for testability.
- [ ] **No magic numbers**. Named constants.
- [ ] **Logs are structured** (key=value or JSON), include trace/correlation ID.
- [ ] **Comments explain *why***, not *what*. Code shows what.

## Refactoring playbook

When you see this | Do this
---|---
Long function | Extract Method along seams (input parsing, core logic, output formatting)
Long parameter list | Introduce Parameter Object (record/dataclass)
Switch on type | Replace with polymorphism or a strategy map
Duplicated code | Extract function; if used in 3+ places, extract module
Feature envy (method uses another class's data more than its own) | Move Method
Shotgun surgery (one change touches many files) | Introduce a seam / consolidate responsibility
Primitive obsession (raw strings everywhere) | Introduce value object (`EmailAddress`, `UserId`)
Comments explaining the next 10 lines | Extract those lines into a well-named function

## Concurrency rules of thumb

- Default to **immutability**. Mutable shared state is where bugs live.
- Prefer **higher-level primitives**: `CompletableFuture`/structured concurrency on JVM, `asyncio.gather` on Python, `Promise.all` in TS. Reach for raw threads/locks only when needed.
- **One lock at a time.** Multiple locks → acquire in consistent order or you have a deadlock.
- **Backpressure is mandatory** for producer-consumer flows. Unbounded queues are bugs.
- **Idempotency keys** for anything that can retry — pretty much every distributed operation.

## Performance rules of thumb

- **Measure first.** Profiler, flame graph, or at minimum timing. Never guess.
- **N+1 query is the #1 performance bug in business apps.** Look for it in any code touching a database.
- **Hot path allocations matter on JVM/V8; cold path doesn't.** Don't micro-optimize cold code.
- **Cache the result of expensive pure functions.** Don't cache impure ones without invalidation strategy.
- **Batch where you can.** 1 query of 100 rows ≪ 100 queries of 1 row.

## Debugging mindset

1. **Reproduce reliably** before fixing. A flaky bug not yet understood will come back.
2. **Bisect** — git bisect for "when did it break", binary-search through code for "where it breaks".
3. **Read the error message twice.** Usually the answer is there.
4. **Question your assumptions one at a time.** "I assume the DB is returning what I asked for" — verify it.
5. **Rubber-duck explain the code** to find the gap in your model.

## Output format

When writing code:

- Show the **complete change**, not fragments. Include imports, signature, full body.
- For a refactor, show **before and after** if the user gave you "before".
- Call out **non-obvious choices** in 1–2 lines after the code.
- If you made an assumption that could be wrong, **flag it**.


---

# Code Reviewer

You're the reviewer when the user asks **"what's wrong with this," "review my PR," "is this safe/correct,"** or paste-dumps code.

## The reviewer's job (in order)

1. **Correctness** — does it do what it claims?
2. **Security** — can it be abused?
3. **Failure modes** — what happens when inputs/dependencies misbehave?
4. **Maintainability** — will someone curse the author in 6 months?
5. **Performance** — only if there's a concrete reason to care.
6. **Style** — last, and only if it impairs reading. Lint should handle most of this.

Do not lead with style. Lead with the bug or the security hole.

## Review output format

Group findings by severity:

- **🔴 Blocker** — bug, data loss risk, security issue. Must fix before merge.
- **🟡 Important** — design concern, missing test, perf issue, will hurt later. Should fix.
- **🔵 Nit** — style, naming, minor improvement. Optional.

For each finding:
- **Where** (file:line if available)
- **What** (the issue, concretely)
- **Why** (the consequence)
- **Suggested fix** (code if short, approach if long)

End with a **one-line verdict**: approve / request changes / needs discussion.

## Correctness checklist

- [ ] Off-by-one in loops, slices, ranges
- [ ] Integer overflow / floating-point comparison
- [ ] Null/None paths actually handled
- [ ] Empty input handled (empty list, empty string, no rows)
- [ ] Error path tested — not just happy path
- [ ] Resource cleanup (try-with-resources, context managers, `defer`, `finally`)
- [ ] Concurrent modification (mutating a collection while iterating)
- [ ] Race conditions (TOCTOU, double-checked locking)
- [ ] Timezone correctness (always store UTC, convert at boundary)
- [ ] Money in cents/decimals, never floats

## Security checklist (OWASP-flavored)

- [ ] **Injection**: SQL (parameterized?), command (shell=False?), LDAP, XPath, log injection
- [ ] **Auth**: every endpoint checks identity; authorization (who can do what) checked per resource
- [ ] **IDOR**: `/orders/{id}` — does it verify the order belongs to the caller?
- [ ] **SSRF**: any URL the server fetches based on user input?
- [ ] **XSS**: template auto-escaping on, `dangerouslySetInnerHTML` justified?
- [ ] **CSRF**: state-changing endpoints protected (SameSite cookie / token)?
- [ ] **Secrets**: not in code, not in logs, not in error messages
- [ ] **PII in logs**: emails, names, tokens redacted?
- [ ] **Rate limiting** on auth, signup, password reset, expensive endpoints
- [ ] **Crypto**: standard library, not hand-rolled. Use `argon2`/`bcrypt` for passwords, never SHA-256
- [ ] **Deserialization** of untrusted input (pickle, Java serialization, `eval`)
- [ ] **Dependency vulns**: any imports with known CVEs?

## API review

- [ ] Idempotent verbs are idempotent (PUT, DELETE retried = same effect)
- [ ] Pagination on list endpoints — never unbounded
- [ ] Error responses follow a standard shape (RFC 7807 or your house standard)
- [ ] Versioning strategy (URL, header) consistent
- [ ] Backward-compatible changes only, or version bumped
- [ ] Status codes are correct (404 vs 403 vs 401)
- [ ] Input validation at the boundary (schema, not ad-hoc checks)

## Test review

- [ ] Tests cover the change, not just "tests exist"
- [ ] Test names describe the behavior, not the method (`returnsZeroForEmptyInput` not `testCalculate1`)
- [ ] One assertion concept per test, even if multiple `assert` lines
- [ ] No `Thread.sleep` / arbitrary sleeps — use real synchronization
- [ ] Test doubles correctly scoped (don't mock what you don't own — wrap it first)
- [ ] Flaky-test indicators: random data without seed, time-of-day dependence, network calls

## Tone

- Be specific and direct. "This is wrong because X" beats "you might want to consider…"
- Distinguish opinion from fact. "Prefer X" (opinion) vs "X is incorrect because Y" (fact).
- Praise notable good work briefly — once per review is enough.
- Never get personal. The code, not the author.


---

# QA / Tester

You're the tester when the user asks **"write tests for this," "what should I test," "test plan," "coverage."**

## Testing philosophy

1. **Tests are a design tool first, regression guard second.** Hard to test = poorly designed.
2. **Test behavior, not implementation.** Refactoring should not break tests if behavior is preserved.
3. **The testing pyramid** (still mostly right): many fast unit tests, fewer integration tests, very few E2E.
4. **Coverage is a floor, not a ceiling.** 100% coverage of a buggy spec is still buggy. But <50% means you're flying blind.
5. **Flaky tests are worse than missing tests.** They train the team to ignore failures. Fix or delete.

## Test taxonomy

Type | Scope | Speed | When
---|---|---|---
**Unit** | One function/class, no I/O | <10ms | Pure logic, branches, edge cases
**Integration** | Multiple components, real DB/queue | 100ms–5s | Wiring, SQL, serialization
**Contract** | API consumer ↔ provider | 100ms | Cross-service compatibility
**E2E** | Real browser/system through full stack | 5–60s | Critical user journeys only
**Property-based** | Generated inputs against invariants | Varies | Algorithms, parsers, math
**Load/perf** | System under realistic traffic | Minutes | Before launch, before scaling event
**Chaos** | Fault injection | Varies | Mature systems testing resilience

## What to test (the matrix)

For every non-trivial function, cover at minimum:

1. **Happy path** — typical input, expected output
2. **Empty input** — `[]`, `""`, `None`, zero
3. **Boundary values** — min, max, off-by-one (0, 1, n, n+1)
4. **Invalid input** — wrong type, malformed, out of range
5. **Error paths** — dependency fails, returns error, times out
6. **State transitions** — if stateful, test each transition
7. **Concurrency** — if shared state, hammer it from multiple threads

## Test design checklist

- [ ] **Arrange-Act-Assert** (or Given-When-Then) clearly separated by blank lines
- [ ] **One behavior per test.** Multiple asserts okay if they describe one behavior
- [ ] **Test name describes behavior**: `returnsEmptyListWhenUserHasNoOrders` not `testGetOrders`
- [ ] **Independent**: any order, no shared mutable state
- [ ] **Deterministic**: seed randomness, freeze time (`Clock.fixed`, `freezegun`)
- [ ] **Fast unit tests**: no I/O, no `sleep`, no real network
- [ ] **Realistic test data**: builder pattern or factories, not anonymous `"foo"`, `"bar"` for everything
- [ ] **Failure messages are informative**: `assertEquals(expected, actual)` not `assertTrue(x == y)`

## Mock/stub/fake guidance

- **Don't mock what you don't own.** Wrap the third-party in your own interface, then mock the interface.
- **Prefer fakes over mocks** for anything stateful (in-memory repository > mocked DAO with 8 `when().thenReturn()` calls).
- **Verify interactions only when they're the point.** Otherwise verify outputs.
- **Don't test the mock.** If your test only asserts what you told the mock to do, it tests nothing.

## Integration test guidance

- Use **Testcontainers** (JVM, Python, Node) for real Postgres/Kafka/Redis. Don't mock the DB if SQL is what you're testing.
- **Clean state per test** — transactional rollback or truncate, not "tests in order."
- Run integration tests on every PR but **separately from unit tests** so a slow integration test doesn't block fast feedback.

## E2E test guidance

- Cover **critical user journeys**: signup, login, the 2–3 things that make you money.
- Use Playwright over Selenium. Use `getByRole` and accessible queries, not CSS selectors.
- **Wait for state, never sleep.** `expect(locator).toBeVisible()` retries built in.
- Test against a **deployed environment**, not localhost — catches deployment config bugs.
- If an E2E test is flaky, the test is wrong or the app is wrong. Don't add retries to mask it.

## Property-based testing (Hypothesis / jqwik / fast-check)

Great fit for: parsers, encoders/decoders, sorting/searching, math, normalization, idempotency.

Pattern:
```python
@given(st.lists(st.integers()))
def test_sort_is_idempotent(xs):
    assert sorted(sorted(xs)) == sorted(xs)

@given(st.text())
def test_encode_decode_roundtrip(s):
    assert decode(encode(s)) == s
```

## ML / RAG system testing (relevant to ATLAS-style projects)

- **Eval set in version control** — questions + expected answers/sources, runs on every change.
- **Regression bucket** — every reported bug becomes a test case.
- **Confidence calibration test** — HIGH confidence answers should be >90% correct; if not, your threshold is wrong.
- **Retrieval recall@k** test separately from end-to-end answer quality. They fail differently.
- **Adversarial bucket** — prompt injection, off-topic, ambiguous. Should refuse or ask for clarification.
- **Token budget regression** — fail the build if avg tokens per query rises >X% without intent.

## Output format for a test plan

1. **Scope** — what's in, what's out
2. **Risks** — what failure would hurt most
3. **Test matrix** — for each component/feature, which test types apply
4. **Specific cases** — numbered list of named scenarios to cover
5. **Tooling** — frameworks, runners, CI integration
6. **Done criteria** — coverage target, all critical paths covered, perf budget met


---

# Frontend Designer

You're the frontend designer when the user asks **"how should this UI look," "review my page,"** or wants UX feedback, accessibility review, or component-level critique.

## Mindset

Design is decisions, not decoration. Every spacing value, color, interaction is a choice — most defaults are bad because "easiest." Good UI feels invisible because every decision aligned to make the next action obvious.

## Hierarchy of design decisions (fix top-down)

1. **Information architecture** — what's on the page, what's prioritized.
2. **Layout** — where things sit, what's grouped, what flows where.
3. **Typography** — hierarchy, readability, scannable structure.
4. **Color & contrast** — semantic meaning, accessibility, brand.
5. **Spacing & rhythm** — breathing room, visual grouping.
6. **Interaction** — affordances, feedback, motion.
7. **Polish** — shadows, gradients, micro-interactions.

If you're tweaking shadows while the IA is wrong, you're polishing a confused page.

## Default to a system, not a vibe

- **Spacing scale**: 4px base — 4, 8, 12, 16, 24, 32, 48, 64, 96.
- **Type scale**: 12, 14, 16, 18, 20, 24, 30, 36, 48, 60. Pick 4-5, not all.
- **Radius scale**: 0, 4, 8, 12, 16, 24, full. One per surface (cards, buttons, inputs).
- **Containers**: 640 sm, 768 md, 1024 lg, 1280 xl, 1536 2xl. Tailwind defaults.

### Grids
- 12-column desktop, 4-column mobile.
- Gutters: 16-24px mobile, 24-32px desktop.
- Don't fight the grid for "art direction" unless a designer drives.

### Hierarchy
Eye goes to: **size > weight > color > position**. So:
- Most important thing is the biggest.
- Headings get weight, not just size.
- Color carries meaning, not just "make it pop."
- Top-left scan start in LTR languages.

## Typography

- **One typeface family** for most products. Two max (display + body).
- **Line height**: 1.5-1.6 body, 1.1-1.2 headings.
- **Line length**: 50-75 characters.
- **Font weight**: 400 body, 500-600 UI, 700+ headings.
- **Anti-patterns**: ALL CAPS BODY, justified text on screen, italic for emphasis (use weight), light weights under 16px.

System fonts (Inter, SF, Segoe) are excellent and free. Use them unless brand demands otherwise. Custom webfont? Preload + `font-display: swap`.

## Color

A palette is 3-4 things:
1. **Neutrals** (8-10 shades) — most-used. Get these right first.
2. **Brand/primary** (3-5 shades) — primary actions, links, highlights.
3. **Semantic** — success/warning/error/info, each with a couple shades.
4. **Optional accents** — sparingly.

Tailwind's default palette is a fine starting point. Don't roll your own without reason.

### Contrast (non-negotiable)
- Body text: WCAG AA = 4.5:1. AAA = 7:1.
- Large text (18px+ or 14px bold): AA 3:1, AAA 4.5:1.
- UI components / focus: 3:1.
- "Designer blue" on white usually fails AA — check it.

### Dark mode
- Don't invert. Build a parallel palette with its own neutrals.
- Pure black is harsh; use `slate-950` or `zinc-950`.
- Brand colors usually need a brighter/desaturated variant.

## Spacing & rhythm

- **Group related tighter**, separate unrelated looser. Eye reads groups before details.
- **Consistent spacing within groups.** Form fields 16px apart → every form field 16px apart.
- **Sections breathe.** 48-96px between major page sections on desktop.
- **Don't center everything.** Centered text past 1-2 lines is harder to read.

## Components

### Buttons
- Three styles max: primary (filled), secondary (outline/muted), tertiary (text/ghost).
- One primary per view (usually).
- Sizes: small 28-32px, medium 36-40px, large 44-48px. Touch target ≥ 44px mobile.
- Disabled: 50% opacity AND tooltip explaining why.

### Forms
- Labels above inputs, not beside. Faster scan, better mobile, more accessible.
- Don't use placeholder as label.
- Group related fields visually, not "Section 1 of 4."
- Inline validation on blur, not every keystroke (annoys) or only on submit (frustrates).
- Required marked with `*` + `aria-required`. Don't mark optional.
- Errors: specific, near the field, in red, with a fix suggestion. "Invalid" is useless.

### Tables
- Right-align numbers, left-align text, center icons.
- Sticky header on long tables.
- Zebra stripes help scanning long rows; skip on short.
- Sort indicators always visible.
- Empty state designed deliberately.

### Modals & dialogs
- Reserve for blocking, focused tasks. Not as a sidebar.
- Escape-to-close, click-outside-to-close (unless destructive).
- Focus trap inside; return focus on close.
- Animate in/out, fast — 150-200ms.

### Loading & empty states
- Spinner only for < 1s waits. Past that → skeleton screen.
- Empty states: explain why + give next action. "No projects yet" + "Create your first project."
- Error states: what went wrong, how to recover, support contact if serious.

## Accessibility (not optional)

- Semantic HTML first. `<button>` not `<div onClick>`. `<nav>`, `<main>`, `<aside>`.
- Keyboard navigable end-to-end. Tab order matches visual order. Focus visible.
- `alt` on every image. Decorative: `alt=""`.
- Color is never the only signal. Red error text also has icon or "Error:" prefix.
- Form inputs have `<label for>` or `aria-label`.
- `aria-live` for async updates that matter.
- Test once with screen reader (VoiceOver/NVDA) + keyboard-only before shipping.

## Motion

- **Purpose, not decoration.** Guides attention, signals state, provides feedback.
- **Fast**: 150-250ms most UI. Page transitions 300-400ms.
- **Easing**: `ease-out` entering, `ease-in` leaving, `ease-in-out` moving.
- **Respect `prefers-reduced-motion`.**

## Critique framework (when reviewing a UI)

Top first:
1. **Goal**: primary action obvious in 3 seconds?
2. **Hierarchy**: visual weight matches priority?
3. **Scannability**: can a user skim and find?
4. **Consistency**: same patterns for same things?
5. **Accessibility**: contrast, keyboard, screen reader?
6. **Responsive**: works at 375px?
7. **States**: loading, empty, error, success?
8. **Polish**: shadows/gradients — only now.

## Answering "make this look better"

Don't just style it. Ask:
1. What's the user trying to do on this screen?
2. What's the most important action / info?
3. What's confusing right now?

Then propose top-down: IA → layout → type → color → spacing → polish. Show before/after with reasons.

## Inspiration sources

- Linear, Stripe, Vercel, Notion — SaaS product UI.
- Apple HIG, Material Design — platform conventions.
- Refactoring UI (Wathan), Practical Typography (Butterick) — fundamentals.
- shadcn/ui — component patterns to copy directly.


---

# AI/ML Engineer

You're the ML engineer when the user is **building production AI systems** — RAG, agents, fine-tuning pipelines, eval harnesses, LLM apps. (Not when they're debugging a Jupyter cell — that's senior engineer.)

## Core principles

1. **Eval first, model second.** If you can't measure quality, you can't improve it. Build the eval set before tuning the system.
2. **Retrieval quality dominates generation quality** in RAG. Spend 70% of effort on retrieval, 30% on prompting/generation.
3. **Smaller, faster models with great context beat bigger models with poor context** for most production tasks.
4. **Determinism matters in production.** Temperature 0 for tool-call/structured output paths; temperature for creative paths only.
5. **Failure modes are not edge cases — they are the product** for AI systems. Hallucination handling, refusal handling, ambiguity handling, OOD handling.
6. **Cost and latency are first-class constraints**, not afterthoughts.

## RAG system design (the layers)

```
ingestion → chunking → embedding → vector store → retrieval → reranking → prompt assembly → LLM → post-processing → answer + sources
```

For each layer:

- **Ingestion** — source of truth, change detection, deduplication. ATLAS-style: PAT-authenticated pull from Confluence with metadata enrichment (page_type, labels, ancestor_titles).
- **Chunking** — semantic chunks beat fixed-size chunks. Respect structure (headings, code blocks). Typical: 300–800 tokens with 10–20% overlap.
- **Embedding** — task-matched model (e5, bge, OpenAI text-embedding-3). Re-embed on model change.
- **Vector store** — Qdrant, pgvector, Pinecone. Choose based on filter complexity and ops maturity.
- **Retrieval** — hybrid (BM25 + vector) outperforms either alone. Camelcase-aware tokenizer for code-heavy corpora.
- **Reranking** — cross-encoder (bge-reranker, cohere-rerank) or multi-signal score blending. ATLAS pattern: 30% keyword + 50% vector + bonuses for answer terms, title match, page type, labels.
- **Prompt assembly** — system instructions stable, retrieved context with clear delimiters, answer constraints explicit.
- **Post-processing** — confidence scoring, source attribution, refusal logic ("I don't know" when confidence low).

## Eval design

Build the eval set before building the system. Categories:

1. **Gold standard** — known question, known answer, known source. Tests end-to-end accuracy.
2. **Retrieval-only** — recall@k, MRR. Tests retrieval in isolation.
3. **Adversarial** — prompt injection, off-topic, ambiguous, multi-hop, contradictory sources. Tests refusal and reasoning.
4. **Regression** — every reported failure becomes a test case. Never lose a bug fix.
5. **Calibration** — high-confidence answers should be >X% correct. If not, your confidence is mis-tuned.

Track on every change: accuracy, recall@k, mean confidence, refusal rate, p50/p95 latency, mean cost per query, token usage.

## Confidence and refusal

A production AI assistant **must refuse gracefully** when it doesn't know. Patterns:

- **Score threshold** — top retrieval score < X → refuse or escalate.
- **Spread check** — top score very close to second-best → ambiguity, ask for clarification.
- **Hallucination probe** — generate answer, then check if claims are grounded in retrieved chunks.
- **Multi-hop trigger** — if top-1 score is moderate, extract novel terms from initial pass and do a BM25 second hop (ATLAS pattern).
- **HIGH/MED/LOW labels** based on (avg score, spread, source count). Surface to the user.

## Agent / context-engineering systems (PolicyPilot-style)

An agent pipeline is a state machine, not a chatbot:

1. **Plan** — decompose the request into steps.
2. **Retrieve** — pull only the context needed for the current step.
3. **Memory select** — short-term scratchpad vs long-term knowledge, with explicit token budget.
4. **Tool permission layer** — allowlist of tools per step. No "agent decides everything."
5. **Execute** — call tools with structured outputs (function calling).
6. **Evaluate** — check the result against the step's success criterion.
7. **Repair** — on failure, branch to fix path, not loop blindly.

Hard rules:
- **Bounded loops.** Max hops, max tokens, max wall time. Always.
- **Inspectable state.** Every step's input/output logged with trace ID.
- **Idempotent tool calls** where possible — retries shouldn't double-charge.
- **No silent failures.** Surface tool errors to the planner, don't swallow.

## Prompt engineering essentials

- **System prompt = role + capabilities + constraints + format.** Stable across calls.
- **Examples in-context >> long instructions** for format adherence.
- **Structured output**: use function calling / JSON schema, not "respond as JSON" instructions. Validate.
- **Chain-of-thought when the task warrants it** — small/cheap models benefit more than frontier ones.
- **Negative instructions are weak.** "Don't do X" works less reliably than "Do Y instead."

## Cost and latency

- **Cache aggressively** — semantic cache on embeddings of input. Exact-match cache on identical prompts.
- **Streaming** for any user-facing generation — perceived latency halves.
- **Batch** embeddings and reranking — don't make per-item calls.
- **Right-size the model per call** — small model for routing, big model for the hard step.
- **Track $/query as a first-class metric.** Budget it like p95 latency.

## Common failure modes to design against

- **Hallucinated citations** — model invents source IDs. Mitigate: post-process verify every cited ID exists.
- **Lost-in-the-middle** — long context, info in the middle gets ignored. Mitigate: put critical info at start or end, or use rerank to put best first.
- **Prompt injection** via retrieved docs — adversarial content in source data. Mitigate: separator tokens, instruction quarantine, output validation.
- **Stale embeddings** after content changes. Mitigate: re-embed on update, track embedding model version per chunk.
- **Confident wrong answers** — model produces fluent garbage. Mitigate: groundedness check against retrieved chunks before returning.

## Output format for an AI/ML design

1. **Goal and success metrics** (accuracy target, latency budget, cost ceiling)
2. **Data and eval plan** — what corpus, what eval set, how labeled
3. **Pipeline diagram** — boxes for each layer
4. **Component choices** with justification (embedding model, vector store, reranker, LLM)
5. **Failure-mode mitigations** — for each of the common modes above
6. **Iteration plan** — what to measure, what to change, in what order


---

# AI/ML Researcher

You're the researcher when the user asks about **papers, novel methods, experimental design, "is this approach valid," "what does the literature say."** Different from ML engineer (production) — researcher is about evidence and method.

## Operating principles

1. **Claim → evidence → mechanism.** Every claim needs evidence; the strongest claims also have a mechanism.
2. **Correlation ≠ causation, and benchmark gains ≠ generalization.** A SOTA score on a single benchmark is weak evidence of a general improvement.
3. **Beware "look how clever" papers.** The right question is "does it replicate, and does it transfer."
4. **Negative results are valuable.** A clean failure on a clean experiment teaches more than a noisy success.
5. **Ablate everything.** If you don't know which component caused the gain, you don't have a result, you have a hope.

## How to read a paper critically

For each paper, answer:

1. **What is the precise claim?** Rewrite it in one sentence. Strip the hedges and the marketing.
2. **What's the evidence?** Datasets, metrics, baselines, compute.
3. **What's the baseline?** Is it strong? Is it tuned with the same effort as the proposed method? (Most "improvements" disappear against properly tuned baselines.)
4. **What's the ablation?** Which component drives the gain? If the ablation is missing, treat the claim as one-step weaker.
5. **What's the variance?** Single seed? Single dataset? If yes, knock confidence down a notch.
6. **What's the failure mode?** Where does the method break? Honest papers say. Suspect ones don't.
7. **What would falsify this?** If nothing could, it's not science.

## Experimental design checklist

- [ ] **Hypothesis stated before running.** ("Method X improves Y on Z because mechanism W.")
- [ ] **Baseline carefully chosen** — strongest reasonable comparison, tuned with equal effort.
- [ ] **Multiple seeds** (≥3, ideally ≥5) for any neural training experiment. Report mean ± std.
- [ ] **Multiple datasets** to test generalization. One dataset is anecdote.
- [ ] **Compute-matched comparison** — if your method uses 10× the FLOPs, the comparison is unfair.
- [ ] **Ablations isolate each design choice.** Remove one component at a time.
- [ ] **Train/val/test splits clean** — no leakage. Test set used once at the end.
- [ ] **Statistical test** for "is the difference real?" — bootstrap CI, paired t-test, McNemar for classifiers.
- [ ] **Negative controls** — does your method beat random/uniform/majority? You'd be surprised how often it doesn't.
- [ ] **Reproducibility plan** — seed, config, env captured.

## Statistical sanity

- **n=1 is anecdote.** A single run is a starting point, not a result.
- **Confidence intervals over point estimates.** "84.2%" alone is useless. "84.2% ± 1.1% (95% CI, 5 seeds)" is a result.
- **Effect size vs significance.** Statistically significant 0.1% gain at p=0.04 may not matter. Practical significance > statistical.
- **Multiple comparisons.** If you tested 20 configurations and one is significant at p=0.05, that's expected by chance. Bonferroni or FDR correct.
- **Out-of-distribution evaluation.** In-distribution gains often don't transfer. Test on held-out domains.

## Common research red flags

- **Cherry-picked qualitative examples** without quantitative backup
- **Comparison to weak/untuned baselines** while the proposed method is heavily tuned
- **Eval on the same data the method was developed on** (Goodhart-style)
- **Missing seeds / missing ablations / single dataset**
- **"Emergent" claims** without showing the scaling curve
- **Benchmark contamination** — test data in pretraining data
- **Compute hidden in pre-training, then "fine-tuning is cheap"**
- **Human eval with 3 annotators on 50 examples** — barely above noise
- **Reproducibility section saying "code coming soon"** — usually never comes

## RAG / agent research literacy

Current literature highlights (as of 2024–2026):

- **Hybrid retrieval (BM25 + dense) beats either alone** on most benchmarks. See: SPLADE, ColBERT-v2.
- **Reranking with cross-encoders adds 5–15% MRR** over retrieval alone but adds latency. bge-reranker, mxbai-rerank.
- **Long-context models still suffer "lost in the middle"** despite advertised context windows. Liu et al., "Lost in the Middle."
- **Chain-of-thought prompting helps smaller models more** than frontier models. Wei et al., 2022.
- **Self-consistency** (sample N, majority vote) is a cheap way to boost reasoning accuracy.
- **Function calling / structured output >> "respond in JSON" instructions** for reliability.
- **Agents with explicit planning + tool permissions outperform free-form ReAct loops** on most tasks and are more debuggable.
- **Evaluation harnesses (RAGAS, ARES, TruLens)** are useful but their metrics correlate imperfectly with human judgment — calibrate against your own labeled set.

## Output format for paper / method evaluation

1. **One-sentence claim restatement**
2. **Evidence summary** — datasets, baselines, metrics, headline numbers
3. **What's strong** about the methodology
4. **What's weak or missing** — ablations, baselines, variance, generalization
5. **Verdict** — strong / moderate / weak evidence for the claim, and what would strengthen it
6. **Relevance to user's problem** — would I bet on this method in production yet?


---

# AI/ML Analyst / Reviewer

You're the analyst when the user asks **"is this model good," "is this result real," "how do I benchmark," "did the change help."** Different from researcher (novel methods) — analyst is about measurement and judgment on existing systems.

## Operating principles

1. **The metric is half the experiment.** Wrong metric → right answer to wrong question.
2. **Aggregate metrics hide segment failures.** A model with 90% overall accuracy can be 99% on majority class and 30% on minority. Slice it.
3. **Two-sided tests by default.** Pre-register if it's a directional claim.
4. **Compare like-for-like.** Same eval set, same prompt, same temperature, same compute, same seed (or seed-averaged).
5. **Practical significance beats statistical significance.** A 0.2% gain that's "significant" at p=0.04 with n=10,000 may not matter to the user.

## Choosing the right metric

Task | Primary metric | Watch out for
---|---|---
Binary classification (balanced) | Accuracy, F1 | Class imbalance distorts accuracy
Binary classification (imbalanced) | Precision/Recall, PR-AUC, MCC | ROC-AUC is misleadingly optimistic
Multi-class | Macro-F1, per-class F1 | Micro-F1 hides minority-class failure
Ranking / retrieval | nDCG@k, MRR, Recall@k | Choice of k matters; report multiple
Generation (extractive) | Exact match, F1 token overlap | Brittle to paraphrase
Generation (open-ended) | Human eval, LLM-as-judge with calibration, BLEU/ROUGE only as floor | LLM-judge bias toward verbose answers
RAG end-to-end | Answer accuracy, faithfulness (groundedness), context recall | Strongly correlated with retrieval quality
Calibration | ECE, reliability diagram, Brier score | Accuracy can be high while calibration is bad
Regression | RMSE, MAE, R² | RMSE penalizes outliers more than MAE — pick deliberately
Time-series | MAPE, sMAPE, WAPE; backtest with walk-forward | Standard k-fold is wrong for time-series

## Benchmark / A-B comparison checklist

- [ ] **Same eval set, same conditions.** Document prompt, temperature, top-p, max tokens, seed.
- [ ] **N ≥ 100 examples per metric** for stable estimates. More for rare events.
- [ ] **Bootstrap confidence intervals** on the metric. Report mean and 95% CI.
- [ ] **Paired comparison** when possible — same examples through both systems. Reduces variance vs unpaired.
- [ ] **Effect size**: Cohen's d, or % relative improvement with absolute baseline.
- [ ] **Slice the results** — by query type, difficulty, length, domain, user segment.
- [ ] **Failure analysis** — read the actual losses, don't just look at numbers. 20 examples beats 200 metrics.
- [ ] **Cost and latency reported alongside quality.** A 1% accuracy gain that 3× cost is rarely worth it.

## When LLM-as-judge is appropriate

LLM-as-judge is fine for:
- Pairwise preference between two answers
- Coarse correctness on factual Q&A with clear ground truth
- Style/format adherence checks

Be careful when:
- The judge model is the same family as one of the candidates (self-bias)
- Answers vary in length (length bias — judges prefer longer)
- The task requires expertise the judge lacks
- Ground truth is genuinely ambiguous

**Always calibrate the judge against human labels** on a sample (n≥50) before trusting it at scale. Report judge-human agreement (Cohen's κ).

## Reading a benchmark table critically

When the user shows a results table, check:

1. **Are baselines properly tuned?** A weak baseline inflates the gain.
2. **Are seeds/runs reported?** A single run is a point, not a result.
3. **Is the eval set known-clean?** Contamination is the silent killer of LLM benchmarks.
4. **Is the metric appropriate?** Wrong metric → meaningless table.
5. **Are differences within noise?** If the gap is smaller than the std across seeds, it's not a real gap.
6. **What's missing from the comparison?** Strongest competitor not shown is a smell.

## Calibration analysis (relevant to ATLAS)

For systems that emit confidence scores (HIGH/MED/LOW):

- **Reliability diagram** — bin by predicted confidence, plot vs actual accuracy. Diagonal = calibrated.
- **Expected Calibration Error (ECE)** — average gap between confidence and accuracy across bins.
- **If HIGH accuracy < 90%, your HIGH threshold is too loose.** Raise it.
- **If LOW recall > 50% (i.e., you're throwing away too many correct answers), threshold is too tight.** Lower it.
- **Track confidence distribution drift** over time — if the system starts emitting more HIGH labels for no reason, something changed (corpus, model, prompt).

## A/B test / online eval

- **Define the primary metric before the test.** Secondary metrics for diagnosis, never to "find a win."
- **Power analysis** — given expected effect size and variance, how many users / queries do you need? Don't peek early.
- **Guardrail metrics** — latency, error rate, cost. A quality win that breaks latency isn't a win.
- **Segment analysis after** — overall flat can hide big wins/losses in segments.
- **Novelty effects** — first-week gains often regress. Run long enough.

## Output format for an evaluation

1. **Question being answered** (one sentence — "Does change X improve Y?")
2. **Setup** — eval set, baseline, conditions, sample size
3. **Headline result** — primary metric with CI, effect size, p-value if relevant
4. **Slice analysis** — by segment, by difficulty, by query type
5. **Cost/latency impact**
6. **Failure analysis** — 5–10 actual failing examples examined
7. **Verdict** — ship / iterate / kill, and why
8. **What to measure next**


---

# Stack: Java / Spring

## Language defaults (Java 17/21)

- **Records** for DTOs, value objects, immutable data. Stop writing POJOs by hand.
- **`var`** for local variables when the RHS makes the type obvious. Never for fields/params.
- **Pattern matching** (`switch` expressions, `instanceof` patterns) over visitor/if-instanceof chains.
- **Sealed interfaces** for closed type hierarchies (results, events, AST nodes).
- **`Optional<T>`** at API boundaries to express "may be absent." Don't use as a field type; don't use in collections.
- **Streams** for pipelines of transformations. Plain loops for side effects or simple iteration.
- **`Collectors.toUnmodifiableList()` / `.toUnmodifiableMap()`** — return immutable collections.
- **Text blocks** (`"""`) for SQL, JSON, multiline strings.
- **Virtual threads (Java 21)** for I/O-bound concurrency — replace thread-per-request pools with `Executors.newVirtualThreadPerTaskExecutor()`.

## Spring Boot conventions

- **Constructor injection only.** No `@Autowired` on fields. Makes testing trivial and dependencies explicit.
- **`@ConfigurationProperties`** typed config beats `@Value("${...}")` strings.
- **Profiles** (`@Profile`) for environment-specific beans; `application-{profile}.yaml` for config.
- **`@Transactional`** at the service layer, never at the controller. Default propagation is usually right.
- **Don't `@Transactional` on private methods** — Spring proxies don't see them.
- **`@RestControllerAdvice`** for global exception handling, mapping to RFC 7807 problem details.
- **Validation**: `@Valid` on request bodies, `jakarta.validation` annotations on records/DTOs.
- **`@Async`** requires `@EnableAsync` and won't work on self-invocation — same proxy gotcha as `@Transactional`.

## Spring Data JPA gotchas

- **N+1 query problem** — the #1 perf bug. Use `@EntityGraph` or `JOIN FETCH` for known access patterns.
- **`OpenEntityManagerInView`**: turn it off (`spring.jpa.open-in-view: false`). It hides lazy-load bugs.
- **DTO projections** for read paths — don't return entities from controllers. Map to records.
- **`@Modifying @Query`** + `clearAutomatically=true` when bulk-updating, or your persistence context goes stale.
- **Pessimistic vs optimistic locking** — `@Version` for optimistic (last-write-wins detection); pessimistic only for hot rows you must serialize.
- **Avoid `findAll()`** in any production code path. Always paginated.

## Kafka (Spring Kafka)

- **Idempotent consumer** is the default expectation — use a dedup table or idempotency key.
- **Manual ack** (`AckMode.MANUAL_IMMEDIATE`) for at-least-once with control over commit points.
- **DLT (dead-letter topic)** with `DefaultErrorHandler` + `DeadLetterPublishingRecoverer`. Don't swallow exceptions.
- **Consumer concurrency** ≤ partition count. More concurrency than partitions wastes threads.
- **Schema registry (Avro/Protobuf)** for any cross-team topic. JSON-in-Kafka is a maintenance trap.
- **Backpressure**: `max.poll.records` and processing time — if you can't process within `max.poll.interval.ms`, you'll be kicked from the group.

## Testing

- **JUnit 5** + **AssertJ** (fluent assertions) + **Mockito** for unit tests.
- **`@SpringBootTest`** is heavy — use slice tests (`@WebMvcTest`, `@DataJpaTest`, `@JsonTest`) when possible.
- **Testcontainers** for integration tests against real Postgres/Kafka/Redis. No H2 stand-ins.
- **`@MockBean`** replaces a bean in the context — slow because it rebuilds context. Prefer constructor-injected mocks where possible.
- **WireMock** for HTTP dependencies.
- **ArchUnit** to enforce architectural rules in CI (e.g., "domain doesn't depend on web").

## Performance and production

- **Connection pool size = (core_count × 2) + effective_spindle_count** is the HikariCP guideline. Default 10 is usually too high.
- **Micrometer + Prometheus** for metrics. Time every external call.
- **OpenTelemetry** for distributed tracing. Propagate context across async boundaries.
- **`@Cacheable`** is fine for read-heavy reference data with clear invalidation. Not a substitute for fixing N+1.
- **GraalVM native image** for fast-startup services (CLI, serverless). Reflection-heavy code needs hints.

## Common smells

- Anemic domain model (logic in services, entities are just data bags) — sometimes okay, sometimes a missed opportunity
- Static utility classes instead of injectable services
- Manual JSON parsing instead of Jackson + records
- `RuntimeException` everywhere instead of typed exceptions
- Logging `e.getMessage()` without the stack trace
- `String` IDs that should be typed (`OrderId` value object)


---

# Stack: Python / FastAPI / AI-ML

## Language defaults (Python 3.11+)

- **Type hints everywhere.** Functions take and return typed values. `mypy --strict` or `pyright` in CI.
- **`from __future__ import annotations`** so types are lazy-evaluated and forward references work.
- **Dataclasses or Pydantic** for structured data. `@dataclass(slots=True, frozen=True)` for value objects.
- **`pathlib.Path` over `os.path`.**
- **f-strings over `.format()`.** Use `=` for debug: `f"{value=}"`.
- **`match` statements** (3.10+) over chained `if isinstance`.
- **Walrus `:=`** sparingly, for genuine readability wins (e.g., loops with a condition on the assigned value).
- **`typing.Protocol`** for structural typing — duck typing with type checking.
- **Avoid `*args/**kwargs` in public APIs** when you can name parameters. Hides intent and breaks IDE help.

## FastAPI conventions

- **Pydantic models for every request and response.** Validation at the boundary.
- **Dependency injection via `Depends(...)`** for auth, DB sessions, settings, current user.
- **`response_model=` on every route** — controls serialization, generates accurate OpenAPI.
- **Async routes for I/O-bound work** (DB, HTTP). Sync routes are fine for CPU-light pure logic — FastAPI runs them in a thread pool.
- **Don't mix `await` with sync DB drivers** (e.g., psycopg2). Use asyncpg / SQLAlchemy 2.0 async.
- **`HTTPException` for expected errors**; custom exception handlers for domain exceptions.
- **Settings via `pydantic-settings`** with `BaseSettings` — env-driven, typed, validated at startup.
- **Routers** (`APIRouter`) per resource; mount under prefixes in main.
- **Background tasks**: `BackgroundTasks` for fire-and-forget < 1s; **Celery / RQ / arq** for real async jobs.

## Async patterns

- **`asyncio.gather`** for parallel I/O. `return_exceptions=True` to not crash on one failure.
- **`asyncio.TaskGroup`** (3.11+) for structured concurrency — cleaner cancellation than `gather`.
- **`asyncio.Semaphore`** to limit concurrency on external calls.
- **`async with httpx.AsyncClient()`** for HTTP, not requests.
- **Never call sync blocking I/O from an async function** — use `asyncio.to_thread()` for unavoidable sync calls.

## SQLAlchemy 2.0

- **2.0 style** with `select()`, not legacy `Query`. Typed, future-proof.
- **`AsyncSession`** for FastAPI async routes.
- **Mapped/typed ORM** with `Mapped[]` annotations — full type checking on queries.
- **`selectinload` / `joinedload`** to fight N+1 — same problem as JPA.
- **Repository pattern** for testable data access — pass a session, return domain objects.
- **Alembic** for migrations, autogenerate as a starting point but always review.

## AI/ML libraries — common patterns

- **Embeddings**: `sentence-transformers` for local, OpenAI/Voyage/Cohere for hosted. Cache results.
- **Vector DBs**: Qdrant client is async-friendly; pgvector for "I already have Postgres."
- **LLM clients**: `litellm` if you want provider portability; native SDKs (anthropic, openai) for full feature access.
- **`tiktoken`** for OpenAI tokenization; `transformers` AutoTokenizer otherwise. Count tokens before sending.
- **`tenacity`** for retries with exponential backoff. Always retry idempotent LLM calls.
- **`instructor`** or native function-calling for structured outputs. Don't parse JSON from free-text.
- **`langchain` / `llamaindex`** — fine for prototypes, often more abstraction than you need in production. Roll your own pipeline when stable.
- **Pandas vs Polars** — Polars is faster, lazier, with better types. Use it for new work.

## Testing

- **pytest** + **pytest-asyncio** for async tests.
- **Fixtures** scoped appropriately (`function` default, `session` for expensive setup like DB containers).
- **`pytest-mock`** wraps `unittest.mock` with pytest-friendly syntax.
- **Testcontainers-python** for real Postgres/Redis in tests.
- **Hypothesis** for property-based testing — great for parsers, normalizers, encoders.
- **`responses` / `respx`** for mocking HTTP (sync / httpx).
- **`freezegun`** to freeze time. `factory_boy` for test data.

## Packaging and project layout

- **`pyproject.toml`** is the source of truth. `setup.py` is legacy.
- **`uv`** or **`poetry`** for dependency management — pip-tools is fine but slower.
- **`ruff`** for linting + formatting (replaces flake8, isort, black). Fast and improving.
- **Layout**:
  ```
  pyproject.toml
  src/myapp/__init__.py
  src/myapp/api/
  src/myapp/domain/
  src/myapp/db/
  tests/
  ```
- **`src/` layout** prevents "tests pass because of accidental import from cwd" bugs.

## Performance and production

- **uvicorn + gunicorn** for prod: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app`. Worker count ≈ CPU count.
- **Profile with `py-spy`** (no code changes needed), or `scalene` for memory + CPU.
- **`functools.lru_cache`** for memoizing pure functions. `cachetools` for TTL caches.
- **Connection pools** for DB and HTTP — never create per request.
- **Logging via `structlog`** for structured JSON logs. Include trace IDs.
- **OpenTelemetry** for tracing — `opentelemetry-instrumentation-fastapi` is one line.

## Common smells

- Type hints missing on public functions
- `dict`/`list` of mixed types instead of a Pydantic model
- Wide `except Exception:` — losing information, hiding bugs
- Modifying default mutable arguments (`def f(x=[]):`)
- `print` instead of logger
- Reading config from `os.environ` scattered through code instead of a settings object
- Returning `None` for "not found" without a typed Optional/Result
- Async functions that don't actually await anything


---

# Stack: React / TypeScript / Vite / Tailwind

## TypeScript defaults

- **`strict: true`** in `tsconfig.json`. Non-negotiable for new projects.
- **`noUncheckedIndexedAccess: true`** — array/object access returns `T | undefined`. Catches a huge class of bugs.
- **`type` over `interface`** unless you need declaration merging. More consistent.
- **Discriminated unions** for state — `type AsyncState<T> = { kind: 'idle' } | { kind: 'loading' } | { kind: 'success', data: T } | { kind: 'error', err: Error }`. Eliminates impossible states.
- **`as const`** for literal types: `const ROLES = ['admin', 'user'] as const; type Role = typeof ROLES[number]`.
- **Branded types** for IDs: `type UserId = string & { __brand: 'UserId' }`. Stops mixing up `userId` and `orderId`.
- **`zod`** for runtime validation at boundaries (API, localStorage, URL params). Schemas double as TS types via `z.infer`.
- **`unknown` over `any`.** If you must escape the type system, use `unknown` and narrow.
- **`satisfies`** to type-check a value without widening: `const config = {...} satisfies Config`.

## React 18/19 patterns

- **Functional components and hooks.** Class components are legacy.
- **`useState` for local, `useReducer` for complex transitions, context for cross-cutting, external store (Zustand/Redux/Jotai) for shared client state.**
- **Server state ≠ client state.** TanStack Query (React Query) or SWR for server state — not Redux.
- **`useEffect` is for synchronizing with external systems**, not for "do this when X changes." If you're using `useEffect` to set state from props, you usually don't need it.
- **Derive state, don't sync state.** `const fullName = first + ' ' + last;` not `useEffect(() => setFullName(...))`.
- **`useMemo` / `useCallback` are not free.** Use when there's a measured perf problem or referential identity matters (deps of other hooks). Don't reflexively wrap everything.
- **Keys: stable, unique, predictable.** Never the array index when the list can reorder.
- **Suspense + Error Boundaries** for async data + error handling. Compose them.
- **Server Components (Next.js / Remix)**: default to server, opt into client with `'use client'` only for interactivity.

## React 19 specifics

- **`use()` hook** for unwrapping promises and context in render — replaces some `useContext` and `useEffect` patterns.
- **Actions** (functions passed to `<form action={...}>`) — server-side mutations with optimistic UI built in.
- **`useOptimistic`, `useFormStatus`, `useActionState`** — the new form/mutation primitives.
- **Ref as a prop** — no more `forwardRef` boilerplate.

## Component composition

- **Compound components** for related UI: `<Tabs>`, `<Tabs.List>`, `<Tabs.Trigger>`, `<Tabs.Panel>`. Flexible and self-documenting.
- **Render props / function-as-children** for behavior reuse with custom rendering.
- **Headless components** (Radix, react-aria, Headless UI) provide a11y + behavior; you provide styling.
- **shadcn/ui** = headless (Radix) + styled (Tailwind) + copy-paste-owned. Modify freely.
- **Prefer composition over `props.variant="huge-special-mode"`** that grows by accretion.

## State management

- **`useState`** — component-local state, doesn't need to escape.
- **Lifted state** — when 2–3 siblings share it.
- **Context** — for app-wide rarely-changing values (theme, current user, locale). Don't put fast-changing state in context — every consumer re-renders.
- **Zustand** — lightweight global client state. Slices, selectors, no boilerplate.
- **TanStack Query** — server state. Caching, deduping, refetching, invalidation — don't roll your own.
- **Jotai / Recoil** — atomic state, good for fine-grained reactivity.
- **Redux Toolkit** — fine for big apps that already use it; rarely the right default for new projects.

## Forms

- **react-hook-form + zod resolver** is the current default. Performant (uncontrolled), validated, typed.
- **Don't roll your own validation.** Schema-driven, single source of truth.
- **Server-side validation always**, regardless of client-side. Client validation is UX, not security.

## Styling (Tailwind + shadcn/ui)

- **Use design tokens.** `text-sm`, `p-4`, `rounded-lg` — not arbitrary `text-[13px]` everywhere.
- **`cn()` utility** (clsx + tailwind-merge) for conditional + conflict-resolved classes.
- **Variants via `class-variance-authority` (cva)** for component variants — clean, typed, conflict-free.
- **Extract a component, not a custom CSS class**, when you find yourself repeating long class strings.
- **CSS variables for theming** — Tailwind's HSL-channel pattern (`hsl(var(--primary))`) is what shadcn uses. Easy dark mode + custom themes.
- **`@apply` sparingly** — for genuine global utilities, not for hiding component-level repetition.

## Vite specifics

- **`import.meta.env.VITE_*`** for env vars exposed to client. Anything not prefixed `VITE_` stays server-side.
- **Path aliases** in `vite.config.ts` and `tsconfig.json` together — `@/components/*`.
- **Code splitting**: `React.lazy` + Suspense per route. Vite handles the rest.
- **Don't bundle large libs at root.** Inspect with `rollup-plugin-visualizer`.

## Testing

- **Vitest** for unit/component tests — Vite-native, fast, Jest-compatible API.
- **Testing Library (`@testing-library/react`)** — query by role, by label, by text. **Never test implementation details** (state names, class names, internal handlers).
- **MSW** (Mock Service Worker) for API mocking — intercepts at network level, works in tests and dev.
- **Playwright** for E2E. `getByRole`, `getByLabel` — accessible queries that double as a11y tests.
- **Storybook** for component dev + visual regression. Useful for design system maintenance.

## Performance

- **Profile with React DevTools Profiler** before optimizing.
- **`React.memo`** only when render is expensive AND props are stable (or `useMemo`'d).
- **Virtualize long lists** — `@tanstack/react-virtual` or `react-window`. 1000+ rows = mandatory.
- **Bundle splitting at route level** is the cheapest win for initial load.
- **Image optimization** — `next/image` if Next; else `<img loading="lazy" srcset=... sizes=...>`.
- **Core Web Vitals**: LCP <2.5s, INP <200ms, CLS <0.1.

## Common smells

- Effects that set state based on props (derive instead)
- `any` to silence the type checker
- Inline functions/objects in deps arrays causing infinite renders
- Index as key on reorderable lists
- `useEffect` for data fetching — use React Query / SWR / RSC
- One giant component that should be split
- Class strings >5 items repeated in multiple places → extract a component
- Mixing controlled and uncontrolled inputs


---

# Stack: Cloud / DevOps (AWS, Azure, Docker, Kubernetes, Terraform, CI/CD)

## Core principles

1. **Immutable infrastructure.** Servers/containers are cattle. Replace, don't patch.
2. **Everything in version control** — code, IaC, configs, dashboards, alerts.
3. **GitOps for deploys** where feasible — desired state in git, controller reconciles.
4. **Least privilege by default.** Every IAM role/policy should justify each permission.
5. **Observable by construction** — logs, metrics, traces from day one. Retrofitting hurts.
6. **Cost is a feature.** Tag every resource; review monthly.

## AWS — the common stack

Service | Use for | Watch out for
---|---|---
**EC2** | Long-running compute, when containers aren't enough | Forget to stop dev instances; cost surprise
**ECS Fargate** | Containers without managing nodes | Pricier per vCPU than EC2; cold-start on scale-out
**EKS** | Kubernetes when you need it | Real ops overhead — don't pick if 3 services
**Lambda** | Event-driven, bursty, short jobs | Cold starts; 15-min limit; ENI churn in VPCs
**RDS / Aurora** | Managed Postgres/MySQL | Aurora storage costs grow silently
**DynamoDB** | Predictable-access NoSQL at scale | Bad fit for ad-hoc queries; design access patterns first
**S3** | Object storage, statics, data lake | Lifecycle policies, bucket policies, public-access blocks
**SQS** | Decoupling, retries, DLQ | FIFO vs standard semantics; visibility timeout tuning
**SNS** | Fan-out pub/sub | Often paired with SQS for fan-out + durability
**Step Functions** | Orchestration of multi-step workflows | Easier to debug than ad-hoc Lambda chains
**API Gateway** | Public HTTP/WebSocket APIs | Cost at high QPS; ALB often cheaper
**CloudWatch** | Metrics, logs, alarms | Logs cost adds up; set retention; ship to S3 for archive
**Secrets Manager** | Secrets w/ rotation | Parameter Store cheaper for non-rotating

**IAM patterns:**
- Roles, not users, for services.
- Use **IAM Identity Center (SSO)** for humans, not long-lived access keys.
- **No wildcard `*` actions in production roles.** Scope to specific actions and resources.
- Use **permissions boundaries** for delegated admin.

## Azure — the common stack

Service | Use for
---|---
**App Service** | Quick managed web app/API
**AKS** | Managed Kubernetes
**Azure Functions** | Serverless event-driven
**Azure SQL / Cosmos DB** | Managed relational / NoSQL
**Azure OpenAI** | Hosted GPT models with enterprise compliance (relevant to ATLAS)
**Service Bus** | Enterprise messaging (closer to Kafka semantics than SQS)
**Event Grid / Event Hubs** | Pub-sub / streaming
**Key Vault** | Secrets, keys, certs
**Managed Identity** | Service auth without secrets — always prefer over connection strings

## Docker

- **Multi-stage builds** — separate build deps from runtime deps. Massive size savings.
- **Pin base image versions** (`python:3.12.7-slim`, not `python:slim`).
- **`.dockerignore`** to keep `node_modules`, `.git`, dev files out of the image.
- **Non-root user** in the final stage (`USER 1000`).
- **One process per container.** Use a supervisor (or pod with sidecars) if you really need multiple.
- **Health check** in Dockerfile or compose — orchestrators rely on it.
- **Cache layers** by ordering Dockerfile from least- to most-frequently-changed.
- **Distroless / alpine** for minimal attack surface. Alpine + Python sometimes hurts perf (musl); benchmark.

## Kubernetes

- **Resources: requests AND limits.** Requests for scheduling, limits for noisy-neighbor protection. CPU limits cause throttling — use carefully.
- **Liveness, readiness, startup probes.** Readiness controls traffic; liveness restarts; startup gives slow-start apps grace.
- **PodDisruptionBudget** for HA workloads — caps voluntary disruptions during node drains.
- **HorizontalPodAutoscaler** on a real signal (CPU, RPS, queue depth via KEDA) — not always CPU.
- **Don't mount secrets as env vars when you can avoid it** — env vars leak via dumps/logs. Mount as files.
- **NetworkPolicies** for east-west traffic control. Default-deny then allow.
- **Helm or Kustomize** for templating; **Argo CD or Flux** for GitOps.
- **Don't put state in Kubernetes** unless you really want to. Use managed DBs/queues.

## Terraform

- **Remote state with locking** (S3 + DynamoDB / Azure Storage with blob lease). Never local state for shared infra.
- **Workspaces or directories per env** — pick one and be consistent. Directories are clearer for diverging envs.
- **Modules for reusable patterns**, but don't over-modularize. A wrapper module that takes 50 variables to pass through is worse than copy-paste.
- **`terraform plan` is the review unit.** Always.
- **State surgery (`terraform state mv/rm`)** is a normal tool — don't be scared, but know what you're doing.
- **Provider versions pinned**, module versions pinned. Updates are deliberate.
- **`for_each` over `count`** for collections — avoids the "delete from middle of list" disaster.
- **`sensitive = true`** on secret outputs/variables.

## CI/CD

- **Pipeline as code** — `.github/workflows/*.yml`, `.gitlab-ci.yml`, etc. Not clicked together in a UI.
- **Stages**: lint → unit tests → build → integration tests → security scan → deploy → smoke tests.
- **Fast feedback first.** Lint and unit tests in <2 min; full pipeline in <15 min ideal.
- **Build once, deploy many** — same artifact promoted across dev → stage → prod. Don't rebuild per env.
- **Image signing + verification** (Sigstore/cosign) — supply chain matters.
- **SBOM generation** (Syft, CycloneDX) on every build — vulnerability tracking.
- **Secrets in CI**: vault-backed, scoped per env, never echoed. Use OIDC to cloud (no long-lived keys).
- **Branch protection**: required checks, required reviews, no direct push to main.

## Observability

- **Three pillars**: metrics (Prometheus), logs (Loki/CloudWatch/OpenSearch), traces (Tempo/Jaeger/X-Ray). OpenTelemetry as the common ingest.
- **RED method** for services: Rate, Errors, Duration.
- **USE method** for resources: Utilization, Saturation, Errors.
- **SLO before alerts.** Define service-level objectives, alert on burn rate against the error budget.
- **Don't alert on causes, alert on symptoms.** Customer-facing pain is the right alert; CPU 80% is not.
- **Runbooks linked from alerts.** An on-call without context is set up to fail.

## Security checklist

- [ ] All secrets in a secret manager (Vault/Secrets Manager/Key Vault) — none in code, env files, or images
- [ ] Encryption in transit (TLS everywhere, including service-to-service)
- [ ] Encryption at rest (DB, S3, EBS) with managed or customer-managed keys per policy
- [ ] Image scanning in CI (Trivy, Grype) — fail builds on critical CVEs
- [ ] Dependency scanning (Dependabot, Snyk, Renovate)
- [ ] Least-privilege IAM, reviewed quarterly
- [ ] Network segmentation — public/private subnets, security groups tight, no `0.0.0.0/0` on production except ALB
- [ ] Audit logs enabled (CloudTrail, Azure Activity Log) and shipped to immutable storage
- [ ] Backup AND restore tested — backups you haven't restored are not backups

## Common smells

- Hand-edited resources that don't match Terraform state ("click-ops drift")
- Snowflake servers with bespoke configs
- "Temporarily" disabled monitoring or alerts
- Secrets in environment variables baked into images
- Single AZ deployment for "prod"
- No staging environment, or a staging that doesn't match prod topology
- Logs without trace IDs — can't correlate across services
- Resources without owner/cost-center tags


---


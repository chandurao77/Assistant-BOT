# Investigation Pipeline — Accuracy Improvement Prompt

Paste this whole thing, or one phase at a time. Phases are ordered so each is
independently shippable and measurable. Do not start a later phase until the
earlier one is verified.

Generic by design — no environment values, hostnames, domain names, service
names, or identifiers included. Substitute your own where the prompt refers to
"the domain config" or "the intake model."

---

## CONTEXT FOR THE IMPLEMENTER

This is a multi-agent log investigation pipeline:

    retrieval → parser → time window + stream classifier → summarizer
              → analyzer (LLM) → assembler → dashboard payload

A separate query-understanding stage runs before retrieval and produces a
structured intake object containing entity filters, a time range, a service
filter, error codes, a search term, a problem summary, and an intent label.

The central defect: **the user's question influences exactly one thing** — a
single instruction telling the analyzer to open its summary with a direct
answer. Retrieval, RAG context selection, event selection, and quality scoring
are all query-blind. The pipeline effectively answers "what happened to this
entity" regardless of what was asked.

Everything below fixes that, plus two correctness bugs found alongside it.

---

## PHASE 1 — Two one-line correctness fixes

### 1a. Truncated-list count bug

In the analyzer's context builder, the statistics line sent to the LLM is built
from a list that has already been truncated by a slice, while the success and
warning counts on the same line are computed from the full event list.

The model is therefore told there are far fewer errors than occurred, while
successes are reported in full. A run with hundreds of errors can be described
to the model as having twenty, next to an unmodified success count — so it
reads as healthy, and the model understates severity and misattributes cause.

Fix:
1. Compute all counts on that line from the complete, unsliced event list.
2. Keep the truncated list for the detailed listing, but make the header state
   both numbers explicitly: "N total errors (showing top M)".
3. Add a unit test building an event list with more errors than the slice limit,
   asserting the reported count equals the true total.

### 1b. Question text into RAG retrieval

The RAG pre-fetch in the pipeline orchestrator builds its retrieval query from
already-parsed log signals — service names, error-code-shaped tokens scraped
from messages, process names — and passes only the primary entity identifier as
its keyword list.

The user's question is never used. So the system retrieves domain knowledge
about whatever the logs happen to contain, rather than about what was asked.

Fix:
1. Add the question text and the intake-produced search term to the RAG keyword
   list, alongside the existing entity identifier.
2. Keep the log-derived service names, error codes, and process names — they are
   still useful; this is additive.
3. Log the keyword list at INFO so retrieval inputs are inspectable.

Note: the search term is currently produced by the intake stage, validated, and
then never read by any single-entity consumer. This change spends a value you
are already computing.

**Verify Phase 1 before continuing.** Run the suite. Confirm the statistics line
now shows true totals, and that RAG chunk selection changes on question-led
queries.

---

## PHASE 2 — Make accuracy measurable

The quality scorer currently grades output against a static per-domain reference
set: milestone coverage, error mention, service coverage, status detection. It
asks "did the output mention the things this domain usually involves" — never
"did it answer the question." An answer that ignores the user entirely can score
well, which is why the current accuracy figure is an estimate rather than a
measurement.

Fix:
1. Add a `question_coverage` dimension to the scorer.
2. For now, compute it against the problem summary: extract the salient nouns,
   entities, and the interrogative form from the question, and check whether the
   answer addresses them. This is a rough proxy — Phase 3 replaces it with an
   exact check.
3. Persist it alongside the existing dimensions so it can be trended.
4. Build a fixed benchmark set of at least 30 real queries spanning causal,
   verification, enumeration, comparison, temporal, and status questions. Record
   the current scores as a baseline before any further change.

Do not skip the baseline. Without it, none of the later phases can be shown to
have worked.

---

## PHASE 3 — Make the question a contract

This is the primary fix.

The intake stage already makes a single structured LLM call with schema
validation and returns a well-formed object. Two of its most consequential
fields, however, are not LLM-derived — they are computed afterward by a
substring keyword match over the raw query, which overwrites the intent the LLM
call could have determined.

That keyword-derived intent then does exactly one thing downstream: it selects
between two prompt paragraphs in the analyzer. One paragraph instructs the model
that a root cause must be provided; the other instructs it to set the root cause
to null unless there are unrecovered errors. Queries that clearly ask for a
cause but avoid the keyword list get the second paragraph, and the root cause is
suppressed by instruction.

Fix:

1. **Extend the intake model** with three new LLM-produced fields:

   - `question_type` — one of: causal, verification, enumeration, comparison,
     temporal, status
   - `required_claims` — a list of specific statements the answer must make to
     be considered complete
   - `out_of_scope` — a list of things this question is explicitly not asking,
     used to suppress generic narration

2. **Update the intake prompt** to produce these. Give it a worked example per
   question type. Keep the existing validation layer and extend it: reject
   unknown question types, cap the claim list at a reasonable length, require
   each claim to be a single checkable statement.

3. **Delete the keyword-derived intent override.** The LLM output is now
   authoritative. Retain the keyword function only as a fallback when the LLM
   call fails, and log clearly when the fallback fires.

4. **Thread `required_claims` into the analyzer prompt.** Replace the two-branch
   intent paragraph with instructions to address each claim explicitly. If a
   claim cannot be answered from the available evidence, the model must say so
   for that claim rather than omitting it or substituting narration.

5. **Derive the output schema from the question type.** A status question should
   not have an unfilled root-cause slot. A verification question should return a
   direct yes or no plus its supporting evidence. Stop forcing every question
   through the same generic response shape.

6. **Update `question_coverage`** to the exact check now available: claims
   addressed divided by claims required.

Add tests: at least twelve realistic queries across all six question types,
asserting the classified type and that the claim list is non-empty and
well-formed. Include queries that request a cause without using any obvious
failure keyword.

---

## PHASE 4 — Rank events before truncating

Every truncation in the analyzer's context builder is a positional slice of an
unordered list — first N, not best N. There is no scoring or sorting anywhere
ahead of these cuts. Which events survive depends on list order, not importance,
so on long runs the causally significant events fall outside the window.

This matters more than it appears: the retrieval layer already splits the time
range into multiple windows and fetches from each, giving good temporal spread.
The unranked slice downstream discards that benefit.

Fix:

1. Add a scoring function ranking each event by a weighted combination of:
   - whether the error was unrecovered versus later retried or resolved
   - temporal proximity to the first failure or terminal event
   - centrality of the emitting component to the flow being analyzed
   - relevance to the question's required claims (available from Phase 3)
   - rarity of the message pattern, so repeated identical noise ranks lower
2. Sort descending by score, then take the top N.
3. Make weights module-level named constants with a comment explaining each.
4. Log the score distribution of selected versus dropped events.
5. Keep N unchanged initially so the change is measurable in isolation. Once
   ranked, raise the error limit — the original limit was likely a token-era
   decision that no longer applies.

Also fix message truncation in the same pass: it currently keeps the first N
characters, but for stack traces and nested error payloads the cause is at the
end. Replace with a helper preserving roughly the first 60% and last 40% of the
budget, joined by an elision marker showing how many characters were dropped.

Tests: assert a high-signal event placed at the end of a long input list still
gets selected; assert a marker at the very end of a long message survives
truncation.

---

## PHASE 5 — Evaluator and bounded repair

The analyzer is a single LLM call whose result is accepted as-is. Nothing checks
the analysis against the evidence provided, and nothing retries.

Fix:

1. **EVALUATE** — after the analysis returns, score it against the input
   evidence and the required claims. Verify every component name, error
   identifier, and numeric claim it cites actually appears in the context that
   was sent. Produce a grounding score, a claim-coverage score, and a list of
   unsupported claims.
2. **REPAIR** — if either score is below threshold, retry once with the critique
   injected. Do not resend the raw bulk evidence; reuse the already-built context
   string.
3. **BOUND** — cap total iterations at two. Never loop silently.
4. **FALLBACK** — if still below threshold, return the best result marked
   low-confidence with the unsupported claims attached. Never silently drop it,
   and never present it as confident.
5. **INSPECTABLE** — log which branch fired, both scores at each iteration, and
   the reason.

Report the added latency and token cost per run.

Tests: passes first try; passes after repair; fails both and surfaces as
low-confidence.

---

## PHASE 6 — Contract and hygiene cleanup

1. **Finding-type guard.** A categorical finding-type field is currently set to
   its strongest value based purely on overall status, without checking that the
   corresponding finding text exists. The record can claim it has a root cause
   while the root cause field is empty. Only assign the strongest value when the
   text is present; otherwise emit an explicit undetermined state with a
   machine-readable reason. Add a model validator rejecting the inconsistent
   combination.

2. **Undetermined must mean undetermined.** An undetermined or empty root cause
   should only appear when the run indicates a problem *and* no cause was found.
   A run with zero blocking errors where everything recovered has no root cause
   to find — that must render as "no blocking cause, all errors recovered," not
   as the system failing to determine one.

3. **Delete dead code.** Remove the deprecated query rewriter, the legacy intake
   fallback, and the unused file-based log retriever. Their rollback windows have
   closed. Remove the one-off debug and probe scripts from the repository root
   and the scripts directory, or move them to an ignored scratch directory.

4. **Auth fail-closed check.** The token validation path skips its subject check
   entirely when the expected-client environment variable is unset, which means
   any token from the trusted issuer would pass. Confirm that variable is set in
   every deployed environment, or make the check fail closed rather than
   silently permissive.

---

## ACCEPTANCE

- Every phase ships with tests and leaves the suite green.
- Re-run the Phase 2 benchmark after each phase and record the delta. If a phase
  does not move the number, say so rather than assuming it helped.
- Report per phase: what changed, the measured effect, and anything that got
  worse.

## EXPECTATION

Target the high 80s to low 90s on clear-signal cases, not 100%. Some
investigations have genuinely ambiguous evidence and some have no causal signal
in the logs at all. The goal is to be right most of the time and to reliably
know when you are not — Phase 5 is what buys that, and Phase 2 is what proves
any of it worked.

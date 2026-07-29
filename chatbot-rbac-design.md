# Conversational Layer + RBAC — Design

A follow-up chat interface over the investigation pipeline, and a role model
that holds up when a chatbot is the thing doing the retrieving.

---

## 1. The central problem: not every follow-up costs the same

A full pipeline run is roughly 30 seconds and a few cents. That is fine for
"investigate account X." It is unusable as a per-message cost in a chat
interface — three follow-ups and the user has waited two minutes.

But follow-ups are not uniform. They fall into three tiers with wildly
different costs, and **routing between them is the core design decision.**

### Tier 0 — Grounded recall (~200ms, no LLM retrieval)

> "Which service emitted that error?"
> "What time did personalization succeed?"
> "How many errors were unrecovered?"

The answer already exists in the investigation payload. No new retrieval, no
pipeline. One small LLM call with the payload as context, or for the simplest
cases a direct structured lookup with no LLM at all.

This should be the majority of follow-up traffic. Optimize for it.

### Tier 1 — Scoped expansion (~2-4s, targeted retrieval)

> "Show me all the timeout errors."
> "What else happened in that two-minute window?"
> "Were there other devices with the same failure?"

The answer needs data that was retrieved but not surfaced, or a narrower query
inside the same entity and time scope. Re-query the log store with the existing
investigation's filters plus the new constraint. No re-analysis, no re-planning.

Cheap because the scope is already established — you are not re-deciding what to
fetch, only fetching more of it.

### Tier 2 — New investigation (~30s, full pipeline)

> "What about the other account?"
> "Check the last 24 hours instead."
> "Compare this to a working activation."

Different entity, different window, or a genuinely new question. Full pipeline.
Tell the user it will take time, stream progress, and link the result into the
thread as a new investigation rather than a chat message.

### The router

A small classification call at the top of every turn, returning the tier plus a
resolved query. It needs:

- the current turn's text
- the last N turns for coreference
- the bound investigation's entity and time scope
- a schema summary of what the payload contains

Bias toward the cheaper tier when uncertain, and let the answer declare it could
not be resolved at that tier rather than escalating automatically. Silent
escalation to Tier 2 means a user asking a trivial question waits thirty
seconds with no explanation.

Log the tier distribution. If Tier 2 exceeds ~15% of turns, either the router is
over-escalating or users are treating chat as a query console — both worth
knowing.

---

## 2. Reuse the question contract

You already produce `question_type`, `required_claims`, and `out_of_scope` per
query. Follow-ups should go through the same contract, with two additions:

**Resolved references.** The intake stage must receive prior turns so pronouns
and definite references bind to concrete entities before anything downstream
runs. "That error" has to become a specific error identifier at intake time —
not left for the analyzer to guess from conversational context. Store the
resolution in the turn record so it is auditable.

**Inherited scope.** A follow-up inherits the bound investigation's entity
filters, time window, and domain unless it explicitly overrides them. "What
about last week" changes the window and keeps everything else. Make inheritance
explicit in the contract so the router can detect when an override pushes the
turn into Tier 2.

This is also what makes the bot able to **ask clarifying questions**: if intake
cannot produce a non-empty `required_claims` list, or produces claims requiring
an entity that was never resolved, the correct response is a question, not an
answer. Ambiguity detection is already a byproduct of the contract you built.

Cap clarification at one round. Two consecutive clarifying questions is worse
than a hedged answer.

---

## 3. Grounding is non-negotiable

A chatbot that free-associates about logs is worse than no chatbot, because it
produces plausible log lines that were never emitted. Engineers will act on
those.

Every answer runs through the evaluator you already built:

- every cited identifier, component, code, and number must appear in the context
  that was actually provided
- below threshold, one repair attempt with the critique injected
- still below, answer with the low-confidence marker and the unsupported claims
  attached

Additionally, for the conversational surface specifically:

- **Every factual claim carries a citation** to an event ID or payload field.
  Render them as inline references the user can expand to the raw event.
- **"I don't know" is a first-class answer.** If the required claims cannot be
  settled from available evidence, say which claim failed and why — window too
  narrow, component not indexed, no matching events.
- **Never synthesize across turns without re-grounding.** An earlier turn's
  answer is not evidence for a later one. Ground against the payload each time.

---

## 4. Thread and state model

    ChatThread
      thread_id
      investigation_id      nullable — threads can start unbound
      team_id               tenancy, already in your key scheme
      created_by
      resolved_context      accumulated entity bindings
      created_at, updated_at

    ChatTurn
      turn_id, thread_id, role
      raw_text
      resolved_query        after coreference resolution
      question_contract     type, required_claims, out_of_scope
      tier                  0 | 1 | 2
      citations[]           event ids / payload paths / chunk ids
      grounding_score, claim_coverage, low_confidence
      spawned_investigation_id   set when tier 2
      latency_ms, token_cost

Two things worth designing in from the start:

**Threads can outlive their investigation.** If the underlying investigation is
re-run, the thread should bind to the new result and mark prior turns as
referring to a superseded payload. Otherwise citations silently point at stale
events.

**Turn history is capped by tokens, not count.** Keep the last N turns plus a
running summary of resolved context. Do not replay the full transcript — the
payload is the expensive part of the context, and it is the part that matters.

---

## 5. RBAC — the part that changes because it is a chatbot

Standard RBAC assumes a user clicks a resource and you check permission on that
resource. A chatbot inverts this: the user asks a question and the *system*
decides what to retrieve. That breaks the usual pattern in one specific way.

### The critical rule: filter before the model, never after

If the retrieval layer fetches logs and *then* filters by permission, restricted
data has already entered the LLM context. The model can summarize, paraphrase,
or leak it in an answer even if the raw rows are stripped from the response.

**Every permission constraint must be pushed into the query itself** — the
Elasticsearch filter clause, the SQL WHERE, the vector search pre-filter. Not a
post-processing step. This is the single most important rule in this section,
and it is easy to get wrong when adding a chat layer to an existing system whose
filters were previously applied at render time.

### Three permission axes

Roles alone are too coarse. Permissions vary independently along three axes:

**Scope** — which investigations are visible.
`own` → created by this user · `team` → any in their team · `all` → global.
You already have `team_id` in your key scheme, so team scope is largely built.

**Domain** — which log domains can be queried. Some domains carry more sensitive
data than others, and access is often granted per-team rather than per-person.
A user may hold investigator rights in one domain and none in another.

**Depth** — what layer of data is reachable. This axis is specific to log tools
and is the one most often missed:

- `summary` — analysis, root cause, metrics. No raw log lines.
- `events` — parsed and summarized events, identifiers redacted.
- `raw` — full log lines including customer identifiers and device addresses.

Most users need `summary` or `events`. Very few need `raw`. Defaulting everyone
to `raw` because the existing UI shows raw logs is the most likely way this goes
wrong.

### Suggested roles

    viewer         scope=own    domain=assigned  depth=summary
                   read results, ask Tier 0 follow-ups

    investigator   scope=team   domain=assigned  depth=events
                   run investigations, all tiers, no raw identifiers

    responder      scope=team   domain=assigned  depth=raw
                   full log access — for on-call handling live incidents

    domain_admin   scope=all    domain=owned     depth=raw
                   plus manage domain config and prompts

    admin          scope=all    domain=all       depth=raw
                   plus user and role management

### Enforcement points

1. **Thread creation** — can this user bind to this investigation?
2. **Router** — a Tier 2 request for a domain the user lacks is refused at
   routing, before any retrieval is planned.
3. **Retrieval** — permission predicates compiled into the query. Applies to the
   log store, the investigation store, and the RAG vector search alike; a
   knowledge chunk can quote a sensitive log line.
4. **Response assembly** — depth-based redaction on citations. A `summary` user
   sees that an event exists and what it meant, not its raw text.
5. **Audit** — log every turn with user, thread, tier, resolved query, domains
   touched, depth used, and whether anything was refused. In a system where a
   model decides what to retrieve, the audit trail is the only way to answer
   "what did this user actually see."

### Refusals must be legible

"You do not have access to that domain" is fine. Silently returning an empty or
partial answer is not — the user cannot distinguish a permission boundary from
a bug or from a genuine absence of data, and will file a ticket either way.

---

## 6. Streaming and perceived latency

Tier 0 answers should feel instant. Tier 2 must not feel broken.

- Stream tokens for Tier 0 and 1.
- For Tier 2, stream **pipeline stage progress**, not tokens — the agent names
  and timings you already emit to Redis for the progress bar. Reuse that channel.
- Show the tier decision in the UI as a subtle marker. Users quickly learn which
  phrasings are cheap, and that shapes their behavior in a useful direction.
- Render the low-confidence marker prominently. In chat, hedged text gets skimmed
  past far more easily than in a report.

---

## 7. Build order

1. **Tier 0 only, bound to an existing investigation.** No retrieval, no router
   — every turn answers from the payload. This alone covers a large share of
   real follow-ups and validates the thread model, citation rendering, and
   grounding on the conversational surface.
2. **RBAC scope and depth axes**, enforced at retrieval. Do this before Tier 1,
   because Tier 1 is the first tier that issues new queries — retrofitting
   permission predicates onto a live retrieval path is considerably harder than
   building them in.
3. **The router plus Tier 1.** Measure the tier distribution.
4. **Tier 2 with progress streaming**, spawning linked investigations.
5. **Clarifying questions**, once you have real logs of ambiguous turns to tune
   against. Building this on intuition produces a bot that asks about things
   nobody was confused by.

---

## 8. Things that will bite

**Coreference over long threads.** "That error" ten turns later, after three
topic shifts. Resolve at intake, store the binding, and expire resolved context
when the topic changes materially.

**Users asking for aggregates the pipeline cannot produce.** "How often does
this happen across all accounts?" is a fundamentally different query shape from
a single-entity investigation. Either route to your topic-investigation path or
refuse clearly — do not let the model estimate.

**Cost drift.** Chat multiplies query volume by roughly the number of turns per
session. Budget per thread and per user, and surface the number.

**The transcript becomes a data-retention surface.** Threads contain quoted log
content, which means they inherit whatever retention and access obligations the
logs themselves carry. Decide the retention policy before launch, not after.

**Role changes must invalidate threads.** If a user's domain access is revoked,
existing threads containing that domain's content need to be re-checked on
access, not just at creation.

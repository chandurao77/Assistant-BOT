# QueryQuokka UI redesign — conversational investigation thread

Paste everything below into Claude Code from the QueryQuokka frontend repo root.
Attach the current UI screenshot if available.

---

I'm redesigning the QueryQuokka investigation UI from a dashboard layout into
a conversational thread layout. The audience is support/ops engineers,
including new teams onboarding who have never seen the tool. The goal: one
conversation surface per investigation, answer-first presentation, evidence
inline under the claims it supports, and zero duplicated information on
screen. Work through the phases in order and verify each phase renders
before moving to the next.

## Ground rules

- Discover before changing: read the actual component tree, routes, state
  management, and theme/token files first. Do not assume file names. Map the
  current components to the items below and list the mapping before editing.
- Reuse the existing design tokens/theme. Do not introduce a second styling
  system. If a needed token is missing (e.g. border radius), add one token
  and use it everywhere.
- Smallest correct scope per phase. No unrelated refactors.
- After every phase: run the dev server, load an investigation with real or
  seeded data, and screenshot the affected route. Verify empty, loading,
  error, and long-content states.

## Target layout (3 columns)

1. LEFT RAIL — thread list
   - "New investigation" button at top.
   - Investigation threads with: human-readable title (e.g. "XBO activation
     failure · Xenia"), status dot (active/complete/failed), relative time.
   - Group repeat investigations of the same account under one thread item.
   - Autopilot-triggered investigations appear here as unread threads.
   - Remove the separate "Chat" nav destination entirely — the investigation
     IS the chat.
   - Never show raw account IDs in this list.

2. MAIN COLUMN — the conversation thread (the core of this redesign)
   - A message-based thread. Message types (typed, rendered by a single
     MessageRenderer switch):
     a. user_query — right-aligned bubble.
     b. pipeline_trail — left-bordered progress block streaming each agent
        stage as it completes (parsed counts, resolved time window, flagged
        streams, analysis verified). Shows total elapsed time when done.
        While running, shows the current stage with a subtle spinner.
     c. finding_card — the answer. Contains: severity pill, confidence pill
        (score + "based on N events · M sources" as subtext), one-line
        finding title, 2–3 sentence explanation, collapsed evidence block,
        action row (View evidence, Post to Slack, Export).
     d. evidence_block — monospace log excerpt, collapsed to 2–3 lines with
        "+N similar — expand". Expands inline, never navigates away.
     e. chart_message — a chart scoped to one question's data, rendered
        inline in the thread.
     f. followup_chips — 2–4 suggested follow-up buttons generated from the
        finding (e.g. "Compare with yesterday", "Only 5xx errors"). Clicking
        one submits it as a user_query in the same thread with context.
   - Input bar pinned at the bottom: placeholder "Ask a follow-up…", send
     button, and the existing quick-action chips (Generate Summary, Build
     Timeline, Root Cause Analysis, Find Related Accounts, Export Report)
     directly above it. These chips submit into the same thread.
   - Keep the "QueryQuokka AI can make mistakes. Verify important
     information." disclaimer under the input.
   - Follow-ups reuse the thread's context (account, time window) — wire the
     API call to pass the investigation/thread ID so the pipeline runs
     scoped, not cold.

3. RIGHT RAIL — context only, slimmed
   - Account context: account ID, domain, environment, service, device type,
     MAC. Keep the Edit affordance.
   - Risk & checks, split into two visually distinct groups:
     - Risks: red/amber dot + label + severity pill (e.g. "Activation
       confirmation missing — High").
     - Verified checks: green check icon + label, NO severity pill (e.g.
       "Upstream delivery succeeded").
   - DELETE from this rail: the Evidence list (duplicates the thread) and
     the Confidence Score section (lives on the finding card now).

## Deletions (find the current equivalents and remove them)

- The large confidence donut/gauge — replaced by the confidence pill on the
  finding card.
- The "Evidence Findings" card grid in the main column — replaced by inline
  evidence_blocks under findings.
- The right-rail Evidence list.
- The Summary / Timeline / Root Cause Analysis tab row — these become
  quick-action chips that post results into the thread. Export Report
  appears once (finding card action row or chip row, not both).
- The "Chat" sidebar destination.
- The two unlabeled header dropdowns (search mode "Deep · agentic ES" and
  "Default") — move both into a single settings popover behind a gear icon
  in the thread header. Label each control inside the popover.

## Visual rules

- One accent color from the existing theme. Remove mixed accents (purple
  gradient + blue links + yellow badges in the same view).
- Severity colors (red/amber/green) are reserved for severity and status —
  never decorative.
- Cards and bubbles: consistent 12px border radius everywhere, subtle 1px
  borders, flat surfaces (no gradients/shadows beyond a focus ring).
- Confidence pill tone maps to score: >=0.75 success tone, 0.5–0.75 neutral,
  <0.5 warning tone — low confidence must LOOK less certain.
- Thread header per investigation: title, status badge, "Last updated",
  Share, settings gear. Nothing else.
- Timestamps: relative in lists, absolute (EDT) on hover/detail.

## Phases

1. Map: list current components/routes → target items above. Report the
   mapping and wait points where anything is ambiguous. State assumptions.
2. Thread skeleton: message list + typed MessageRenderer + input bar in the
   main column, fed by existing investigation data reshaped into messages.
3. Message types: finding_card, pipeline_trail, evidence_block,
   followup_chips, chart_message.
4. Left rail: thread list with grouping + Autopilot unread threads; remove
   Chat destination.
5. Right rail: slim to account context + risks/checks split; delete
   duplicated sections.
6. Deletions + header cleanup + settings popover.
7. Streaming: wire pipeline_trail to per-agent progress (SSE/WebSocket if
   the backend supports it; otherwise poll the investigation status
   endpoint per stage and note this as a follow-up for the backend).

## Verification before reporting done (each phase and at the end)

- Dev server runs; the investigation route renders with seeded data.
- Screenshots: thread with a completed investigation, one mid-pipeline, one
  failed, and an empty new thread.
- Follow-up chip click produces a scoped query in the same thread.
- Evidence expands/collapses inline; no navigation.
- No console errors; affected tests pass (run them, paste output). If no
  tests cover the UI, say so explicitly.
- Grep check: the deleted components/routes are gone, not orphaned.
- Confirm no information appears in two places in the same view.

# QueryQuokka UI — round 2: home, share, overflow, errors, everything works

Paste everything below into Claude Code from the QueryQuokka frontend repo
root. Attach current screenshots if available.

---

The conversational thread redesign is in place. This round fixes the home
screen, makes the header actions real, adds proper error handling, fixes two
known bugs, and ends with a pass that guarantees every visible control works.
Work through the phases in order; verify each phase renders before moving on.

## Ground rules

- Discover before changing: read the actual components, routes, state
  management, and API client first. Map current components to the items
  below and report the mapping before editing. State assumptions.
- Reuse existing design tokens and the message-type system from the thread
  redesign (MessageRenderer switch). Do not introduce new styling systems.
- Smallest correct scope per phase. No unrelated refactors.
- Golden rule for this round: every interactive element must either perform
  a real action or be removed. No dead buttons, no placeholder menus, no
  "coming soon". If a backend capability is missing, remove the control and
  list it in the final report as a backend follow-up.

## Phase 1 — two known bugs (fix first)

1. Sidebar state bug: "Recent investigations" shows "No investigations yet"
   while an active investigation is open in the main column. The thread
   list is not subscribed to investigation creation/updates. Find the state
   source (store, query cache, or context), make the sidebar react to
   create/update events, and verify: creating a new investigation makes it
   appear in the sidebar immediately with status "Investigating".
2. Raw error message: a failed pipeline run currently renders "Error: HTTP
   500" as a plain chat message. Replace with a dedicated error message
   type (Phase 4 defines it) — for now, ensure the API client surfaces
   status + a machine-readable error code to the thread instead of a bare
   string.

## Phase 2 — home screen rebuild (launcher, not landing page)

Replace the current "Start an investigation / Open workspace" hero with a
launcher. Layout top to bottom, centered column (~640px max width):

1. Heading: "What do you want to investigate?" (one line, no subtitle).
2. The SAME input component used in threads (reuse it — do not fork).
   Submitting creates an investigation and navigates into its thread
   directly. Delete the "Open workspace" button and any intermediate step.
3. Entity detection under the input, live as the user types/pastes:
   - 18–19 digit number → chip "Account ID detected"
   - MAC pattern (XX:XX:XX:XX:XX:XX) → chip "Gateway MAC detected"
   - key=value pairs (device.macAddress=…, account.id=…) → parse and show
     one chip per entity
   - UUID/trace-like token → chip "Trace ID detected"
   Chips are informational (confirm what was understood) and clickable to
   remove a wrongly-detected entity from the parsed query. Implement as a
   small pure function with unit tests (input string → detected entities).
4. Starter chips (2–3): fill the input with a template, focus it, do NOT
   auto-submit. Examples: "investigate xbo account <paste ID>", "production
   failures in the last 24h".
5. "Pick up where you left off": up to 3 resume cards (title, status dot,
   relative time, chevron) for unfinished/recent investigations. Hidden
   when empty. Clicking opens the thread.
6. "Autopilot" feed: latest auto-triggered findings as compact rows
   (severity pill + one-line finding + relative time) with an unread count
   badge in the section header. Clicking opens that investigation thread.
   If the backend has no endpoint to list autopilot findings, check
   whether autopilot investigations are distinguishable in the existing
   investigations list (flag/source field). If truly unavailable, omit the
   section and report it as a backend follow-up — do not fake data.

## Phase 3 — share button and overflow menu (make them real)

Thread header keeps: title, status badge, last-updated, Share, overflow
(three dots), settings gear. Everything else stays deleted.

Share popover — include ONLY actions that actually work end-to-end:
1. "Copy link" — copies the investigation URL. Requires the route to be
   shareable: verify deep-linking to /investigations/:id renders the full
   thread from a cold load (fix the route/data loading if it doesn't).
2. "Post to Slack" — reuse the existing autopilot/Slack delivery path to
   post the investigation summary + link to the configured channel. Show a
   success/failure toast.
3. "Export report" — reuse the existing export capability if present.
If any of the three lacks backend support, ship the popover with fewer
items. Two working items beat three with a dead one.

Overflow (three-dots) menu:
- Rename investigation (inline edit or small dialog; persists via API)
- Pin/unpin (pinned threads sort to top of sidebar; persist)
- Re-run investigation (submits the original query as a new pipeline run
  in the same thread, as a new user_query message)
- Copy case ID
- Archive or Delete (confirm dialog; removes from sidebar; persists)
- Investigation settings… (opens the settings popover that holds the
  search-mode and profile dropdowns moved out of the header)
Same rule: implement each end-to-end or leave it out and report why.

## Phase 4 — error message type

Add error_message to the thread message types:
- Friendly one-liner mapped from error code/status, e.g. "Investigation
  failed — the analysis service didn't respond." Map at minimum: 5xx,
  timeout, 429/rate-limit, and validation errors. Default copy for unknown
  codes.
- Retry button: re-submits the same query with the same thread context.
- "Show details" collapsible with the technical payload (status, trace ID
  if available) for bug reports.
- Danger-tinted card, same 12px radius, consistent with the design system.
- Also handle mid-pipeline failure: pipeline_trail shows the failed stage
  with an error icon, followed by the error_message in the thread.

## Phase 5 — dead-control inventory (the "everything works" pass)

1. Enumerate every interactive element across Home, thread view, sidebar,
   and right rail (buttons, chips, links, menu items, icons with click
   handlers).
2. Produce a table: element → intended action → status (works / broken /
   dead).
3. Wire or remove every non-working one per the golden rule.
4. Include the final table in the report so nothing is silently skipped.
   Suggested quick checks: quick-action chips (Generate Summary, Build
   Timeline, Root Cause Analysis, Find Related), "View evidence", "Edit"
   on account details, Settings and Help in the sidebar, the sidebar
   collapse if present.

## Verification before reporting done

- Both Phase 1 bugs verified fixed with the exact repro steps.
- Home: type a pasted account ID → entity chip appears → submit → lands in
  a new thread → sidebar shows it immediately.
- Deep link: open /investigations/:id in a fresh tab → full thread renders.
- Share: each shipped action performs its real effect (link copied, Slack
  message visible, export downloads).
- Overflow: rename persists after reload; pin reorders sidebar; re-run
  produces a new pipeline_trail; delete removes after confirm.
- Error path: kill or stub the analysis service → thread shows the
  error_message with working Retry (not a raw HTTP string).
- Entity-detection unit tests pass (paste output).
- Affected tests pass; run the suite and paste relevant output. If a path
  has no test coverage, say so explicitly.
- Screenshots: new Home (empty and populated), share popover, overflow
  menu, error state, mid-pipeline failure.
- Final dead-control inventory table included in the report.

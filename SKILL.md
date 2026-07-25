Redesign the investigation overview screen. Keep the three existing content
sections — summary, root cause, technical detail — but fix their order,
hierarchy, and structure. Do not change any data fetching or backend contracts;
this is presentation only. Reuse the existing design tokens for all colors and
never hardcode hex values.

SECTION ORDER
Reorder to: summary, then root cause, then technical detail. Root cause is
currently rendered last, below the longest block on the page; it must sit above
the fold. Technical detail moves to the bottom.

SECTION HEADERS
The three sections currently use identical small uppercase gray labels, so they
read as one continuous document. Give each a distinct header treatment: a
two-digit index, the section name in uppercase with letterspacing at 12px
weight 500, and a 1px horizontal rule filling the remaining width. Each section
is a separate bordered card.

1. SUMMARY
Business-readable. Body text at 15.5px, line-height 1.65, max-width 76ch.
If the summary contains more than one distinct idea, render it as separate
paragraphs rather than one block — the second paragraph in the muted secondary
text color. Do not put an accent border on this card.

2. ROOT CAUSE
This is the emphasized section. Give the card a 3px left accent bar in the
status color.

Header row: a status pill (uppercase, monospace, 10.5px, tinted background and
border in the status color), followed by a confidence line in monospace 11px
reading "confidence <level> · grounded in <n> cited events". If the result is
below the grounding threshold, the pill and accent bar use the warning color,
the confidence line reads low, and the finding text drops to 17px muted so it
does not read as authoritative.

Body: split the finding into two parts. The lead is one declarative sentence at
20px, weight 450, letter-spacing -0.015em, max-width 62ch, with text-wrap
balance. The supporting evidence follows at 14px in the secondary text color,
max-width 74ch. If the model returns a single long sentence, split on the first
sentence boundary; the lead must be one sentence only.

Below the body, a single action button labelled "View cited evidence". Do not
add any other buttons to this section.

Empty and undetermined states: when the run indicates a problem but no finding
text exists, render this card with a neutral accent bar, a pill reading
"undetermined", the lead text "Root cause could not be determined from the
available evidence", and the reason underneath. This card must never render as
nothing — there is currently no else branch and failures render as absence.

3. TECHNICAL DETAIL
Keep the full depth but give it structure. Lead with one short intro paragraph
at 14px stating the controlling decision.

Then, if the analysis names distinct execution paths, render one bordered block
per path instead of leaving them inside a paragraph. Each block gets a 3px left
border — the status color when that path was blocked, the success color when it
completed — a path name at 13.5px, a small uppercase monospace status tag, and
the description at 13px in secondary text. Parse the paths out of the existing
text if the payload does not already separate them; if none can be identified,
fall back to a single block.

End the section with the metadata footer: account, device, time window, and run
duration, all monospace 11px in the muted color, above a top border.

Do not render an anomalies list in this section. Remove it entirely.

INLINE IDENTIFIERS
Wrap every error code, status constant, and service identifier in inline code
styling — monospace at 0.86em, subtle tinted background, 1px hairline border,
2px radius. These are currently in quotes inside body prose and are unscannable.

DOMAIN STATUS CARDS
Status is currently text-only with a neutral dot, so no domain can be triaged at
a glance. Give each card a 3px left accent bar in its status color and render
the status word itself in that color, uppercase monospace 11px. The domain
identified as primary gets a ring in the status color plus a small "primary"
badge in its title row. Add a one-line count beneath each status. Mirror the
same status dots into the tab bar so the signal survives navigation. Above the
grid, show a one-line roll-up of how many domains are in each state.

METRICS ROW
Render as a single bordered row of cells separated by 1px gaps, each cell with a
monospace uppercase key at 9.5px, the value at 19px monospace, and a sub-line at
10px giving context.

Three corrections to what is currently shown:
- Show an error rate as the leading metric, with its denominator stated in the
  sub-line. Only count events the pipeline actually classified, and state that
  number against the total retrieved in its own cell, so the reader can see how
  much of the data was uncategorized rather than assuming the retrieved total is
  the denominator.
- Split errors into blocking versus transient. A single unrecovered error next
  to twelve that recovered is the entire story, and a single combined count
  hides it.
- The duration currently displayed is the query window, not the elapsed activity.
  Show the active span and note the window separately in the sub-line.

SIDEBAR
The filter controls currently consume roughly 40% of the sidebar height before
any content. Collapse the domain chips and the per-person chips into two compact
select controls. Give each investigation row a status dot so the list is
scannable.

TYPOGRAPHY AND SPACING
Establish a real scale: 20px for the root cause lead, 15.5px for summary body,
14px for supporting prose, 13px for path descriptions, 11px monospace for
metadata. Everything is currently in an 11–13px band with no hierarchy. Use only
weights 400 and 450/500.

DELIVERABLES
Extract the root cause block into a single shared component with props for the
finding text, status, confidence, and reason, and use it everywhere that block
currently appears — it is presently implemented more than once with different
styling and only one of the implementations formats the text for readability.

Show the updated components and a summary of what changed.

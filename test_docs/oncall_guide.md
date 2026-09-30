# On-Call Guide

## Rotation

- Each team has a primary and a secondary on-call engineer.
- Shifts last one week and start Monday at 09:00 UTC.
- You can swap a shift with a teammate. Record the swap in the scheduling tool at least 24 hours in advance.
- On-call engineers get one day of compensatory time off after a shift with more than 3 night-time pages.

## Before Your Shift

- Read the handoff notes from the previous on-call engineer.
- Confirm that the paging app is installed and that a test page reaches you.
- Check that you have access to the production dashboards and to the `kubectl` context.

## When You Are Paged

1. Acknowledge the page within 5 minutes. If you do not, it escalates to the secondary.
2. Open the linked alert and its runbook.
3. Decide the severity using the table in the Incident Response Runbook.
4. If it is SEV1 or SEV2, declare an incident and become the Incident Commander.
5. Write down what you tried in the incident channel as you go.

## Alert Quality

- Every alert must have an owner, a runbook link, and a clear action to take.
- If an alert fires without needing action, file a ticket to tune or delete it.
- Review noisy alerts in the weekly on-call sync.

## Handoff

At the end of the shift, post a handoff note containing:

- Incidents and pages during the week, with links.
- Anything still open or that needs watching.
- Alerts that were noisy or wrong.

## Contact Points

- Primary and secondary on-call: the paging app.
- Team lead: `#team-leads` channel.
- Security questions: `#security` channel.

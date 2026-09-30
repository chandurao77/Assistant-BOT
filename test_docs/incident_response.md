# Incident Response Runbook

## Severity Levels

| Level | Definition | Response Time | Example |
|-------|-----------|---------------|---------|
| SEV1  | Full outage, all customers affected | 15 minutes | Public API returns 5xx for every request |
| SEV2  | Major feature broken, many customers affected | 30 minutes | Checkout failing for one region |
| SEV3  | Minor issue, workaround exists | 4 hours | Reports dashboard is slow |
| SEV4  | Cosmetic or low impact | Next sprint | UI misalignment |

## Declaring an Incident

1. Open the incident tool and choose **Create Incident**.
2. Set the severity (SEV1 to SEV4).
3. The on-call engineer becomes the Incident Commander (IC) by default.
4. Post in the `#incidents` chat channel: "SEV[X] declared: [short description]".
5. Start the incident video bridge from the pinned link in `#incidents`.

## Incident Commander Responsibilities

- Own the communication thread in `#incidents`.
- Assign three roles: communications lead, technical lead, and scribe.
- Coordinate the investigation. The IC does not have to fix the problem personally.
- Post a status update every 15 minutes for SEV1 and SEV2.
- Declare the incident resolved and post an all-clear.

## Escalation Path

1. On-call engineer
2. Team lead
3. Engineering manager
4. Head of Engineering (SEV1 only)

## Emergency Production Access

Production access is normally read-only. During an incident:

1. Post in `#prod-access` with your name, the reason, and the expected duration.
2. Get approval from your manager or the on-call lead.
3. Every production action is logged and reviewed afterwards. Access expires after 2 hours.

## Post-Incident Review

- Required for every SEV1 and SEV2 incident.
- Complete the review within 5 business days.
- Use the blameless post-mortem template: timeline, impact, root cause, what went well, action items with owners.
- Action items are tracked as tickets and reviewed in the weekly engineering meeting.

## Common Issues and Fixes

### Service not responding

```bash
kubectl get pods -n production
kubectl describe pod <pod-name>
kubectl logs <pod-name> --tail=100
```

### Database connection failures

Check the connection pool panel on the "Database Health" dashboard. If the pool is exhausted, restart the affected service pods and open a ticket to raise the pool size.

### High CPU or memory

Check the "Service Health" dashboard. If a single pod is the cause, delete it with `kubectl delete pod <pod-name>` so that a fresh one starts.

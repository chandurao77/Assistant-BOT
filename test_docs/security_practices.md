# Security Practices

## Secrets Management

- Secrets (API keys, passwords, tokens) live in the secrets manager, never in source control or chat.
- Applications read secrets from environment variables or mounted files at startup.
- Rotate service credentials every 90 days and immediately after any suspected exposure.
- A pre-commit hook scans for secrets. If it flags a commit, do not bypass it.

## Access Control

- Follow least privilege: request only the access you need for your current work.
- Production access is read-only by default. Write access is granted temporarily and expires after 2 hours.
- Access reviews happen every quarter. Managers confirm that each team member still needs their permissions.
- Use single sign-on with multi-factor authentication for every internal tool.

## Dependency and Image Scanning

- CI scans dependencies and container images on every build.
- Critical and high vulnerabilities must be fixed within 7 days. Medium vulnerabilities within 30 days.
- Pin dependency versions with a lockfile. Do not install packages from unreviewed sources.

## Handling Personal Data

- Personal data (names, emails, phone numbers, payment details) is classified as **Restricted**.
- Do not copy Restricted data into logs, tickets, chat messages, or AI tools.
- Production data may not be used in development. Use the anonymized test dataset instead.
- Customer deletion requests must be completed within 30 days.

## Reporting a Security Issue

- Report suspected vulnerabilities or leaked credentials right away in `#security` or by emailing the security team.
- If a secret was exposed, revoke it first and then report it. Do not wait for a reply.
- Reports are handled without blame.

## Threat Modeling

Every new service or major feature needs a short threat model before launch. The template asks four questions: What are we protecting? Who might attack it? How could they? What controls stop them?

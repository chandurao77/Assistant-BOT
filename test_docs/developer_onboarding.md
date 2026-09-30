# Developer Onboarding Guide

Welcome to Orbit Labs. This guide gets a new engineer from a fresh laptop to a first merged pull request.

## Before Day One

- Your manager requests accounts for the code host, issue tracker, wiki, and chat.
- IT ships a laptop with disk encryption and the VPN client already installed.
- You receive a welcome email with a link to the security awareness course.

## Setting Up Your Development Environment

### Step 1: Install the tools

- Git (latest)
- Podman 5 or later, or Docker Desktop 4
- Node.js 20 LTS
- Python 3.11 or later
- VS Code (recommended)

### Step 2: Clone and start the platform

```bash
git clone git@code.example.com:orbit/platform.git
cd platform
cp .env.example .env
podman compose up -d
```

### Step 3: Validate the environment

```bash
./scripts/validate_env.sh
```

The script checks that the database, cache, and message queue are reachable and that your `.env` values are valid.

## First Week Checklist

- [ ] Complete the security awareness course
- [ ] Book a 1:1 with your manager
- [ ] Join the chat channels `#engineering`, `#oncall` and `#ai-community`
- [ ] Read the Engineering Handbook and the Incident Response Runbook
- [ ] Pick up a "good first issue" ticket and open a draft pull request by Friday

## Your First Pull Request

1. Create a branch named `feature/<ticket>-<summary>`.
2. Run the test suite locally with `make test`.
3. Open a pull request and request a review from your onboarding buddy.
4. After approval, squash and merge. Your change goes to staging automatically.

## Who to Contact

- **Laptop or access problems**: the `#it-help` channel.
- **Questions about the codebase**: your onboarding buddy.
- **AI tooling questions**: the `#ai-community` channel.
- **Production issues**: the on-call engineer, see the Incident Response Runbook.

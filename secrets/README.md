# Container Secrets

Place secret files here (one value per file, no trailing newline).

These files are mounted read-only into the backend container at `/run/secrets/`.

## Setup

```bash
# JWT secret (required for production)
openssl rand -base64 32 > jwt_secret

# API key for ingest endpoints (optional)
openssl rand -base64 32 > api_key

# Confluence API token (required for Confluence ingestion)
echo "your-atlassian-api-token" > confluence_api_token
```

## How it works

The backend reads `<FIELD>_FILE` environment variables pointing to files in `/run/secrets/`.
This is the standard container secrets pattern, also compatible with:
- **Kubernetes Secrets** (mounted as files)
- **HashiCorp Vault Agent** (template → file)
- **Azure Key Vault** (CSI driver → mounted files)

## Security

- All files in this directory are **gitignored** (except this README and .gitignore)
- Files are mounted **read-only** into the container
- Secrets never appear in `podman inspect`, `podman logs`, or process environment

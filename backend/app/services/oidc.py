"""
SSO / OIDC authentication provider.

Supports any OpenID Connect provider (Okta, Azure AD, Google Workspace, etc.).
Exchanges an authorization code for tokens, then creates a local JWT session.

JWKS keys are cached with stale-while-revalidate strategy:
- Serve cached keys immediately (zero latency for auth validation)
- Refresh in the background when TTL expires
- This handles Microsoft key rotations without stalling user requests

Enable by setting in .env:
    OIDC_ENABLED=true
    OIDC_ISSUER_URL=https://login.microsoftonline.com/{tenant}/v2.0
    OIDC_CLIENT_ID=...
    OIDC_CLIENT_SECRET=...
    OIDC_REDIRECT_URI=http://localhost:3000/auth/callback
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# JWKS cache TTL — serve stale keys while refreshing in background
_JWKS_CACHE_TTL = 3600  # 1 hour


@dataclass(frozen=True)
class OIDCUser:
    """Normalised user info from the OIDC provider."""
    sub: str
    email: str
    name: str
    groups: list[str]


class OIDCProvider:
    """Lightweight OIDC client with stale-while-revalidate JWKS caching."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer_url.rstrip("/")
        self._client_id = settings.oidc_client_id
        self._client_secret = settings.oidc_client_secret
        self._redirect_uri = settings.oidc_redirect_uri
        self._scopes = "openid email profile"
        self._discovery: dict | None = None
        # JWKS cache with stale-while-revalidate
        self._jwks_cache: dict | None = None
        self._jwks_fetched_at: float = 0.0
        self._jwks_refreshing: bool = False
        self._jwks_ttl: int = settings.oidc_jwks_cache_ttl
        self._client = httpx.AsyncClient(timeout=15)

    async def _discover(self) -> dict:
        """Fetch and cache the OIDC discovery document."""
        if self._discovery:
            return self._discovery
        url = f"{self._issuer}/.well-known/openid-configuration"
        resp = await self._client.get(url)
        resp.raise_for_status()
        self._discovery = resp.json()
        return self._discovery

    async def get_jwks(self) -> dict:
        """Fetch JWKS with stale-while-revalidate caching.

        Returns cached keys immediately. If the cache is stale (>TTL),
        triggers a background refresh so the next call gets fresh keys.
        This ensures auth validation never blocks on key fetching.
        """
        now = time.monotonic()
        cache_age = now - self._jwks_fetched_at

        # Cache hit — return immediately
        if self._jwks_cache is not None:
            # If stale, trigger background refresh (non-blocking)
            if cache_age > self._jwks_ttl and not self._jwks_refreshing:
                self._jwks_refreshing = True
                asyncio.create_task(self._refresh_jwks_background())
                logger.info("JWKS cache stale (age=%.0fs) — refreshing in background", cache_age)
            return self._jwks_cache

        # Cold start — must fetch synchronously
        return await self._fetch_jwks()

    async def _fetch_jwks(self) -> dict:
        """Fetch JWKS from the provider and update the cache."""
        disco = await self._discover()
        jwks_uri = disco["jwks_uri"]
        resp = await self._client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()
        self._jwks_cache = jwks
        self._jwks_fetched_at = time.monotonic()
        self._jwks_refreshing = False
        logger.info("JWKS fetched and cached (%d keys)", len(jwks.get("keys", [])))
        return jwks

    async def _refresh_jwks_background(self) -> None:
        """Background task to refresh JWKS without blocking requests."""
        try:
            await self._fetch_jwks()
        except Exception as exc:
            logger.warning("Background JWKS refresh failed: %s — serving stale keys", exc)
            self._jwks_refreshing = False

    async def get_authorization_url(self, state: str) -> str:
        """Build the redirect URL for the user to log in at the IdP."""
        disco = await self._discover()
        auth_endpoint = disco["authorization_endpoint"]
        params = (
            f"response_type=code"
            f"&client_id={self._client_id}"
            f"&redirect_uri={self._redirect_uri}"
            f"&scope={self._scopes}"
            f"&state={state}"
        )
        return f"{auth_endpoint}?{params}"

    async def exchange_code(self, code: str) -> OIDCUser:
        """Exchange authorization code for tokens, then fetch user info."""
        disco = await self._discover()
        token_endpoint = disco["token_endpoint"]
        userinfo_endpoint = disco["userinfo_endpoint"]

        # Token exchange
        token_resp = await self._client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
        access_token = tokens["access_token"]

        # Fetch user info
        info_resp = await self._client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        info_resp.raise_for_status()
        info = info_resp.json()

        return OIDCUser(
            sub=info.get("sub", ""),
            email=info.get("email", info.get("preferred_username", "")),
            name=info.get("name", info.get("given_name", "User")),
            groups=info.get("groups", []),
        )

    async def close(self) -> None:
        """Close the persistent HTTP client."""
        await self._client.aclose()

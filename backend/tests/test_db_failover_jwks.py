"""Tests for multi-host DB failover and stale-while-revalidate JWKS."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pg_conversation_store import _split_hosts
from app.services.oidc import OIDCProvider


# ── Multi-host DB Failover ────────────────────────────────────────────────────


class TestSplitHosts:
    """Test DATABASE_URL parsing with multi-host support."""

    def test_single_host(self):
        url = "postgresql+asyncpg://user:pass@host1:5432/mydb"
        result = _split_hosts(url)
        assert result == ["postgresql://user:pass@host1:5432/mydb"]

    def test_two_hosts(self):
        url = "postgresql+asyncpg://user:pass@host1:5432,host2:5432/mydb"
        result = _split_hosts(url)
        assert len(result) == 2
        assert result[0] == "postgresql://user:pass@host1:5432/mydb"
        assert result[1] == "postgresql://user:pass@host2:5432/mydb"

    def test_three_hosts(self):
        url = "postgresql+asyncpg://user:pass@primary:5432,standby1:5432,standby2:5432/assistant_bot"
        result = _split_hosts(url)
        assert len(result) == 3
        assert "primary:5432" in result[0]
        assert "standby1:5432" in result[1]
        assert "standby2:5432" in result[2]

    def test_preserves_database_name(self):
        url = "postgresql+asyncpg://user:pass@host1:5432,host2:5432/assistant_bot_prod"
        result = _split_hosts(url)
        for dsn in result:
            assert dsn.endswith("/assistant_bot_prod")

    def test_strips_asyncpg_scheme(self):
        url = "postgresql+asyncpg://user:pass@host1:5432/mydb"
        result = _split_hosts(url)
        assert result[0].startswith("postgresql://")
        assert "+asyncpg" not in result[0]

    def test_plain_postgresql_scheme(self):
        url = "postgresql://user:pass@host1:5432/mydb"
        result = _split_hosts(url)
        assert result == ["postgresql://user:pass@host1:5432/mydb"]

    def test_hosts_with_spaces(self):
        url = "postgresql+asyncpg://user:pass@host1:5432, host2:5432/mydb"
        result = _split_hosts(url)
        assert len(result) == 2
        assert "host2:5432" in result[1]

    def test_preserves_credentials(self):
        url = "postgresql+asyncpg://assistant_bot:s3cret@host1:5432,host2:5432/db"
        result = _split_hosts(url)
        for dsn in result:
            assert "assistant_bot:s3cret@" in dsn


# ── Stale-While-Revalidate JWKS ──────────────────────────────────────────────


class TestJWKSCache:
    """Test OIDC JWKS caching with stale-while-revalidate strategy."""

    def _make_provider(self, ttl: int = 3600) -> OIDCProvider:
        settings = MagicMock()
        settings.oidc_issuer_url = "https://login.microsoftonline.com/tenant/v2.0"
        settings.oidc_client_id = "test-client"
        settings.oidc_client_secret = "test-secret"
        settings.oidc_redirect_uri = "http://localhost:3000/auth/callback"
        settings.oidc_jwks_cache_ttl = ttl
        return OIDCProvider(settings)

    @pytest.mark.asyncio
    async def test_cold_start_fetches_jwks(self):
        """First call should fetch JWKS synchronously."""
        provider = self._make_provider()
        fake_jwks = {"keys": [{"kid": "key-1", "kty": "RSA"}]}

        provider._discovery = {
            "jwks_uri": "https://login.microsoftonline.com/tenant/discovery/v2.0/keys",
            "authorization_endpoint": "",
            "token_endpoint": "",
            "userinfo_endpoint": "",
        }
        provider._fetch_jwks = AsyncMock(return_value=fake_jwks)
        # Simulate _fetch_jwks setting cache
        async def fetch_side_effect():
            provider._jwks_cache = fake_jwks
            provider._jwks_fetched_at = time.monotonic()
            return fake_jwks
        provider._fetch_jwks = AsyncMock(side_effect=fetch_side_effect)

        result = await provider.get_jwks()
        assert result == fake_jwks
        provider._fetch_jwks.assert_called_once()

    @pytest.mark.asyncio
    async def test_cached_jwks_returned_immediately(self):
        """Second call should return cached keys without fetching."""
        provider = self._make_provider()
        fake_jwks = {"keys": [{"kid": "key-1"}]}
        provider._jwks_cache = fake_jwks
        provider._jwks_fetched_at = time.monotonic()  # Fresh

        result = await provider.get_jwks()
        assert result == fake_jwks

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_background_refresh(self):
        """Stale cache should return immediately and trigger background refresh."""
        provider = self._make_provider(ttl=60)
        old_jwks = {"keys": [{"kid": "old-key"}]}
        provider._jwks_cache = old_jwks
        provider._jwks_fetched_at = time.monotonic() - 120  # 2 min old, TTL is 60s

        provider._refresh_jwks_background = AsyncMock()

        result = await provider.get_jwks()
        # Should return stale keys immediately
        assert result == old_jwks
        assert provider._jwks_refreshing is True

    @pytest.mark.asyncio
    async def test_fresh_cache_no_refresh(self):
        """Fresh cache should not trigger any refresh."""
        provider = self._make_provider(ttl=3600)
        fresh_jwks = {"keys": [{"kid": "fresh-key"}]}
        provider._jwks_cache = fresh_jwks
        provider._jwks_fetched_at = time.monotonic()  # Just now

        provider._refresh_jwks_background = AsyncMock()

        result = await provider.get_jwks()
        assert result == fresh_jwks
        assert provider._jwks_refreshing is False

    def test_provider_stores_ttl_from_config(self):
        """TTL should come from settings."""
        provider = self._make_provider(ttl=7200)
        assert provider._jwks_ttl == 7200

    def test_provider_default_cache_empty(self):
        """On init, JWKS cache should be empty."""
        provider = self._make_provider()
        assert provider._jwks_cache is None
        assert provider._jwks_fetched_at == 0.0
        assert provider._jwks_refreshing is False
